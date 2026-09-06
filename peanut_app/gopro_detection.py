from __future__ import annotations

from collections import Counter
from datetime import datetime
import threading
import time

from .detection import DetectionWorker, FrameSnapshot, Observation, TrackState
from .domain import PeanutRecord, Severity
from detect_open_gopro import DEFAULT_MODEL, DEFAULT_ARDUINO_PORT, DEFAULT_GOPRO_SERIAL, LANE_RANGES
from .model_registry import file_hash


class GoProDetectionWorker(DetectionWorker):
    """Use the completed sorter for hardware decisions and persist its final results."""

    def __init__(self, *args, arduino_port=DEFAULT_ARDUINO_PORT, gopro_serial=DEFAULT_GOPRO_SERIAL, **kwargs):
        super().__init__(*args, **kwargs)
        self.arduino_port = arduino_port
        self.gopro_serial = gopro_serial
        self.recorded_ids = set()
        self._arduino_sender = None
        self._recovery_stop = threading.Event()
        self.monitoring_fault = False
        self._indicator_state = "STOPPED"
        self.arduino_direction = "L"
        # 新訓練並啟用的 M 模型直接供下次 GoPro 生產使用；在尚未有 M 候選時，
        # 繼續使用已驗證的 train-13 M 模型，避免誤載舊 S 版本。
        if not self.model_version.startswith("m_auto_"):
            self.model_path = DEFAULT_MODEL
            self.model_version = "gopro-train-13"
            self.model_hash = file_hash(DEFAULT_MODEL)

    def run(self):
        try:
            from detect_open_gopro import run_detection
            self._emit("status", "正在連線 GoPro 與 Arduino，初始化撥桿")
            run_detection(
                model_path=self.model_path,
                arduino_port=self.arduino_port,
                gopro_serial=self.gopro_serial,
                stop_event=self.stop_event,
                pause_event=self.pause_event,
                on_started=self._on_started,
                on_arduino_ready=self._on_arduino_ready,
                on_arduino_event=self._on_arduino_event,
                on_frame=self._on_frame,
            )
            if self._faulted:
                self._monitor_arduino_after_fault()
            else:
                self.database.set_work_order_status(self.work_order.id, "STOPPED")
                self._emit("stopped")
        except (Exception, SystemExit) as exc:
            self._faulted = True
            self.database.set_work_order_status(self.work_order.id, "FAULT")
            message = str(exc)
            camera_error = any(
                token in message.lower()
                for token in ("gopro", "webcam", "udp stream", "opencv")
            )
            anomaly_code = "CAMERA_CONNECTION_ERROR" if camera_error else "GOPRO_RUNTIME_ERROR"
            anomaly_id = self.database.add_anomaly(
                code=anomaly_code, message=message,
                severity=Severity.CRITICAL, work_order_id=self.work_order.id,
                deduplicate_active=False,
            )
            self._emit("error", {"message": message, "anomaly_id": anomaly_id, "code": anomaly_code})
            self._monitor_arduino_after_fault()

    def _on_arduino_ready(self, sender):
        self._arduino_sender = sender

    def _on_arduino_event(self, line):
        if line == "PY:STATE:RUNNING":
            self.pause_event.clear()
            self._emit("arduino_state", "RUNNING")
        elif line == "PY:STATE:STOPPED":
            self.pause_event.set()
            self._emit("arduino_state", "STOPPED")
        elif line == "PY:STATE:FAULT":
            self.pause_event.set()
            self._emit("arduino_state", "FAULT")
        elif line == "PY:BUTTON:YELLOW":
            self._emit("arduino_yellow")
        elif line.startswith("PY:DIRECTION:"):
            direction = line.rsplit(":", 1)[-1]
            if direction in {"L", "R"}:
                self.arduino_direction = direction
                self._emit("arduino_direction", direction)
        elif line.startswith("PY:ERROR:"):
            self._faulted = True
            self.database.set_work_order_status(self.work_order.id, "FAULT")
            self.database.add_anomaly(
                code="ARDUINO_SERIAL_ERROR",
                message=f"Arduino 連線中斷：{line[9:]}",
                severity=Severity.CRITICAL,
                work_order_id=self.work_order.id,
                deduplicate_active=False,
            )
            self._emit("arduino_state", "FAULT")
            self._emit("status", f"Arduino 連線中斷：{line[9:]}")

    def _send_machine_command(self, command):
        sender = self._arduino_sender
        if sender is None:
            return
        try:
            sender(command)
        except Exception as exc:
            self._emit("status", f"Arduino {command} 指令失敗：{exc}")

    def stop(self):
        self._recovery_stop.set()
        self._send_machine_command("S")
        super().stop()

    def pause(self):
        self._send_machine_command("S")
        super().pause()

    def resume(self):
        super().resume()
        self._send_machine_command("START")

    def set_indicator_state(self, state):
        self._indicator_state = state
        self._send_machine_command(f"STATE,{state}")

    def _monitor_arduino_after_fault(self):
        """Keep the physical yellow button usable after a fatal detection error."""
        try:
            import serial

            connection = None
            for _ in range(10):
                if self._recovery_stop.is_set():
                    return
                try:
                    connection = serial.Serial(
                        self.arduino_port, 115200, timeout=0.25, write_timeout=2
                    )
                    break
                except Exception:
                    time.sleep(0.5)
            if connection is None:
                return

            lock = threading.Lock()

            def sender(command):
                with lock:
                    connection.write(f"{command.strip()}\n".encode("utf-8"))

            self._arduino_sender = sender
            self.monitoring_fault = True
            self._indicator_state = "FAULT"
            time.sleep(2)
            sender("STATE,FAULT")
            self._emit("status", "異常等待中；按黃色按鈕重新檢查異常")

            while not self._recovery_stop.is_set():
                raw_line = connection.readline()
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line == "PY:BUTTON:YELLOW":
                    self._on_arduino_event(line)
                    # GUI 在主執行緒重新檢查後會回傳 STATE。
                    for _ in range(20):
                        if self._indicator_state != "FAULT":
                            break
                        if self._recovery_stop.wait(0.05):
                            break
                    if self._indicator_state != "FAULT":
                        break
                elif line.startswith("PY:STATE:"):
                    self._on_arduino_event(line)
        except Exception as exc:
            self._emit("status", f"Arduino 異常等待連線失敗：{exc}")
        finally:
            self.monitoring_fault = False
            sender = self._arduino_sender
            if sender is not None:
                try:
                    sender("S")
                except Exception:
                    pass
            self._arduino_sender = None
            if 'connection' in locals() and connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def _on_started(self, values):
        self.database.set_work_order_status(self.work_order.id, "RUNNING")
        self._emit("started", values)

    def _on_frame(self, display, raw, results, names, locked, triggered,
                  frame_number, elapsed, seen):
        observations = []
        height, width = raw.shape[:2]
        for result in results:
            for box in result.boxes:
                if box.id is None:
                    continue
                track_id = int(box.id[0].item())
                class_id = int(box.cls[0].item())
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                x1, y1 = max(0, min(x1, width-1)), max(0, min(y1, height-1))
                x2, y2 = max(x1+1, min(x2, width)), max(y1+1, min(y2, height))
                observation = Observation(
                    track_id, class_id, frame_number, elapsed,
                    str(names[class_id]).lower(), float(box.conf[0].item()),
                    (x1, y1, x2, y2), (x1+x2)//2, (y1+y2)//2,
                    float((x2-x1)*(y2-y1)), self._crop_with_margin(raw, (x1,y1,x2,y2)),
                )
                observations.append(observation)
        snapshot = FrameSnapshot(frame_number, raw.copy(), observations)
        for observation in observations:
            tid = observation.track_id
            if tid in self.recorded_ids:
                continue
            state = self.tracks.setdefault(tid, TrackState(tid))
            state.observations.append(observation)
            state.observations = state.observations[-10:]
            state.last_seen_frame = frame_number
            # Keep the first decision-line image, or the latest image before it.
            if not state.crossed_center:
                state.center_snapshot = snapshot
                if observation.cx <= 400:
                    state.crossed_center = True
        candidates = [
            tid for tid, did_trigger in triggered.items()
            if did_trigger and tid not in self.recorded_ids and tid in self.tracks
        ]
        active_ng_lanes = set()
        for tid, state in self.tracks.items():
            label = locked.get(tid)
            if label not in {"mold", "small"} or not state.observations:
                continue
            active_ng_lanes.update(self._lanes_for_y(state.observations[-1].cy))

        for tid in candidates:
            state = self.tracks.get(tid)
            if state is None:
                continue
            label = locked[tid]
            lanes = set(self._lanes_for_y(state.observations[-1].cy))
            if label == "normal" and lanes & active_ng_lanes:
                # Same-lane simultaneous detections are one NG production event.
                self.recorded_ids.add(tid)
                del self.tracks[tid]
                continue
            self._record_trigger(tid, label, elapsed, tid not in seen)
            if self.stop_event.is_set():
                break
        self.tracks = {tid: state for tid, state in self.tracks.items()
                       if frame_number - state.last_seen_frame <= 15}
        self._emit("frame", display)

    def _record_trigger(self, tid, label, elapsed, predicted):
        state = self.tracks[tid]
        window = state.observations
        last = window[-1]
        lanes = self._lanes_for_y(last.cy)
        # The original lost-track prediction uses the first matching servo.
        eject = lanes[:1] if predicted else lanes
        area = sum(o.area_px2 for o in window) / len(window)
        directory = self.config.image_root / self.work_order.work_order_no
        directory.mkdir(parents=True, exist_ok=True)
        image_path = directory / f"{self.work_order.work_order_no}-P{self.next_sequence:06d}.jpg"
        central = next((o for o in state.center_snapshot.observations if o.track_id == tid), last)
        import cv2
        if not cv2.imwrite(str(image_path), central.crop):
            raise RuntimeError(f"無法保存花生影像：{image_path}")
        record = PeanutRecord(
            work_order_id=self.work_order.id, sequence_no=self.next_sequence, track_id=tid,
            detected_at=datetime.now().isoformat(timespec="seconds"), classification=label,
            confidence_center=central.confidence,
            confidence_mean=sum(o.confidence for o in window)/len(window),
            valid_frames=len(window), class_counts=dict(Counter(o.label for o in window)),
            area_mean_px2=area,
            lane=lanes[0] if lanes else 0, boundary_between=lanes if len(lanes)==2 else None,
            eject_lanes=eject if label in {"mold", "small"} else (),
            predicted_false_reject=False, model_version=self.model_version,
            model_hash=self.model_hash, image_path=image_path, session_token=self.session_token,
            center_frame_number=central.frame_number, center_time_seconds=central.video_time_seconds,
            command_due_time_seconds=elapsed if label in {"mold", "small"} and eject else None,
            mean_width_px=sum(o.width for o in window)/len(window),
            speed_px_per_frame=self._mean_speed(window),
            record_status="GOPRO_PREDICTED" if predicted else "GOPRO_TRIGGERED",
        )
        record.id = self.database.insert_peanut(record)
        self._save_training_snapshot(state.center_snapshot, record)
        self.next_sequence += 1
        self.recorded_ids.add(tid)
        del self.tracks[tid]
        self._emit("peanut", record)
        stats = self.database.stats(self.work_order.id)
        self._emit("stats", stats)

    @staticmethod
    def _lanes_for_y(cy):
        return tuple(i for i, (lo, hi) in enumerate(LANE_RANGES, 1) if lo <= cy <= hi)
