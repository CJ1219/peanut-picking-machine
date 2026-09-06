from __future__ import annotations

import json
import queue
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .config import AppConfig
from .database import ProductionDatabase
from .domain import PeanutRecord, Severity, WorkerEvent, WorkOrder
from .model_registry import file_hash
from .weight import WeightCalibration


@dataclass(slots=True)
class Observation:
    track_id: int
    class_id: int
    frame_number: int
    video_time_seconds: float
    label: str
    confidence: float
    bbox: tuple[int, int, int, int]
    cx: int
    cy: int
    area_px2: float
    crop: np.ndarray | None = None

    @property
    def width(self) -> int:
        return max(0, self.bbox[2] - self.bbox[0])


@dataclass(slots=True)
class TrackState:
    track_id: int
    observations: list[Observation] = field(default_factory=list)
    crossed_center: bool = False
    center_index: int | None = None
    center_snapshot: FrameSnapshot | None = None
    last_seen_frame: int = 0
    finalized: bool = False


@dataclass(slots=True)
class FrameSnapshot:
    frame_number: int
    frame: np.ndarray
    observations: list[Observation]


class DetectionWorker(threading.Thread):
    """影片辨識背景工作；不直接操作 GUI 或 Arduino。"""

    def __init__(
        self,
        config: AppConfig,
        database: ProductionDatabase,
        work_order: WorkOrder,
        video_source: str | Path,
        event_queue: queue.Queue[WorkerEvent],
    ) -> None:
        super().__init__(name="peanut-detection", daemon=True)
        self.config = config
        self.database = database
        self.work_order = work_order
        self.video_source = str(video_source)
        self.event_queue = event_queue
        self.session_token = datetime.now().strftime("%Y%m%dT%H%M%S_%f")
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.tracks: dict[int, TrackState] = {}
        self.completed_tracks: dict[int, int] = {}
        self.recent_records: list[PeanutRecord] = []
        self.frame_snapshots: dict[int, FrameSnapshot] = {}
        self.weight_calibration = WeightCalibration.load(config.calibration_path)
        active_model = database.active_model()
        if active_model is None:
            self.model_path = config.model_path
            self.model_version = config.model_version
            self.model_hash = file_hash(config.model_path)
        else:
            self.model_path = Path(active_model["weight_path"])
            self.model_version = str(active_model["version"])
            self.model_hash = str(active_model["weight_hash"])
        self.next_sequence = database.next_peanut_sequence(work_order.id)
        self._faulted = False

    def _emit(self, kind: str, payload=None) -> None:
        self.event_queue.put(WorkerEvent(kind=kind, payload=payload))

    def stop(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()

    def pause(self) -> None:
        self.pause_event.set()

    def resume(self) -> None:
        self.pause_event.clear()

    def run(self) -> None:
        capture = None
        try:
            if not self.model_path.exists():
                raise FileNotFoundError(f"找不到模型：{self.model_path}")

            from ultralytics import YOLO

            self._emit("status", "正在載入模型")
            model = YOLO(str(self.model_path))
            capture = cv2.VideoCapture(self.video_source)
            if not capture.isOpened():
                raise RuntimeError(f"無法開啟影片來源：{self.video_source}")

            fps = float(capture.get(cv2.CAP_PROP_FPS))
            if fps <= 0:
                fps = 30.0
            frame_interval = 1.0 / fps
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            center_x = width // 2
            frame_number = 0

            self.database.set_work_order_status(self.work_order.id, "RUNNING")
            self._emit("started", {"fps": fps, "width": width, "height": height})

            while not self.stop_event.is_set():
                while self.pause_event.is_set() and not self.stop_event.is_set():
                    time.sleep(0.05)
                if self.stop_event.is_set():
                    break

                loop_started = time.perf_counter()
                ok, raw_frame = capture.read()
                if not ok:
                    self._emit("video_finished")
                    break

                frame_number += 1
                video_time_seconds = frame_number / fps
                results = model.track(
                    raw_frame,
                    imgsz=self.config.inference_image_size,
                    conf=self.config.detection_confidence,
                    persist=True,
                    tracker=self.config.tracker_name,
                    verbose=False,
                )

                annotated = raw_frame.copy()
                seen_track_ids: set[int] = set()
                frame_observations: list[Observation] = []
                for result in results:
                    for box in result.boxes:
                        track_id = int(box.id[0].item()) if box.id is not None else -1
                        class_id = int(box.cls[0].item())
                        label = str(model.names[class_id]).lower()
                        confidence = float(box.conf[0].item())
                        x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
                        x1 = max(0, min(x1, width - 1))
                        x2 = max(x1 + 1, min(x2, width))
                        y1 = max(0, min(y1, height - 1))
                        y2 = max(y1 + 1, min(y2, height))
                        cx = (x1 + x2) // 2
                        cy = (y1 + y2) // 2
                        crop = self._crop_with_margin(raw_frame, (x1, y1, x2, y2))
                        observation = Observation(
                            track_id=track_id,
                            class_id=class_id,
                            frame_number=frame_number,
                            video_time_seconds=video_time_seconds,
                            label=label,
                            confidence=confidence,
                            bbox=(x1, y1, x2, y2),
                            cx=cx,
                            cy=cy,
                            area_px2=float((x2 - x1) * (y2 - y1)),
                            crop=crop,
                        )
                        if track_id >= 0:
                            seen_track_ids.add(track_id)
                        frame_observations.append(observation)
                        self._draw_box(annotated, observation, track_id)

                self._remember_frame_snapshot(
                    FrameSnapshot(
                        frame_number=frame_number,
                        frame=raw_frame.copy(),
                        observations=frame_observations,
                    )
                )
                for observation in frame_observations:
                    if observation.track_id < 0 or observation.track_id in self.completed_tracks:
                        continue
                    self._update_track(
                        observation.track_id,
                        observation,
                        center_x,
                        height,
                    )

                self._cleanup_tracks(frame_number, seen_track_ids)
                self._draw_guides(annotated, center_x, height, width)
                self._emit("frame", annotated)

                elapsed = time.perf_counter() - loop_started
                if elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)

            self._flush_interrupted_tracks(height)
            if not self._faulted:
                self.database.set_work_order_status(self.work_order.id, "STOPPED")
                self._emit("stopped")
        except Exception as exc:
            self._faulted = True
            self.database.set_work_order_status(self.work_order.id, "FAULT")
            anomaly_id = self.database.add_anomaly(
                code="PYTHON_RUNTIME_ERROR",
                message=str(exc),
                severity=Severity.CRITICAL,
                work_order_id=self.work_order.id,
                deduplicate_active=False,
            )
            self._emit("error", {"message": str(exc), "anomaly_id": anomaly_id})
        finally:
            if capture is not None:
                capture.release()

    def _update_track(
        self,
        track_id: int,
        observation: Observation,
        center_x: int,
        frame_height: int,
    ) -> None:
        state = self.tracks.setdefault(track_id, TrackState(track_id=track_id))
        previous = state.observations[-1] if state.observations else None
        state.observations.append(observation)
        state.last_seen_frame = observation.frame_number

        if not state.crossed_center:
            if previous is not None and previous.cx > center_x >= observation.cx:
                previous_index = len(state.observations) - 2
                current_index = len(state.observations) - 1
                if abs(previous.cx - center_x) <= abs(observation.cx - center_x):
                    state.center_index = previous_index
                else:
                    state.center_index = current_index
                state.crossed_center = True
                center_frame_number = state.observations[state.center_index].frame_number
                state.center_snapshot = self.frame_snapshots.get(center_frame_number)
            elif len(state.observations) > self.config.pre_center_frames + 1:
                state.observations = state.observations[-(self.config.pre_center_frames + 1) :]

        if not state.crossed_center or state.center_index is None or state.finalized:
            return

        post_count = len(state.observations) - state.center_index - 1
        if post_count < self.config.post_center_frames:
            return

        state.finalized = True
        record = self._build_record(state, frame_height, interrupted=False)
        record.id = self.database.insert_peanut(record)
        self._save_training_snapshot(state.center_snapshot, record)
        self.recent_records.append(record)
        self._update_false_rejects(record)
        self.completed_tracks[track_id] = observation.frame_number
        self.tracks.pop(track_id, None)

        stats = self.database.stats(self.work_order.id)
        self._emit("peanut", record)
        self._emit("stats", stats)
        self._check_target_weight(stats)

    def _build_record(
        self, state: TrackState, frame_height: int, interrupted: bool
    ) -> PeanutRecord:
        assert state.center_index is not None
        start = max(0, state.center_index - self.config.pre_center_frames)
        stop = state.center_index + self.config.post_center_frames + 1
        window = state.observations[start:stop]
        center = state.observations[state.center_index]
        classification_window = [
            observation
            for observation in window
            if observation.confidence >= self.config.production_confidence
        ]
        counts = Counter(observation.label for observation in classification_window)

        expected_frames = self.config.pre_center_frames + self.config.post_center_frames + 1
        if interrupted or len(classification_window) < expected_frames:
            classification = "unknown"
        elif counts["mold"] >= self.config.mold_min_hits:
            classification = "mold"
        elif counts["small"] >= self.config.small_min_hits:
            classification = "small"
        elif counts["normal"] >= self.config.normal_min_hits:
            classification = "normal"
        else:
            classification = "unknown"

        matching_confidences = [
            item.confidence for item in classification_window if item.label == classification
        ]
        if not matching_confidences:
            matching_confidences = [item.confidence for item in classification_window]
        if not matching_confidences:
            matching_confidences = [item.confidence for item in window]
        confidence_mean = sum(matching_confidences) / len(matching_confidences)
        area_mean = sum(item.area_px2 for item in window) / len(window)
        mean_width = sum(item.width for item in window) / len(window)
        speed = self._mean_speed(window)
        lane, boundary_between = self._lane_for_y(center.cy, frame_height)
        if not interrupted and classification in {"mold", "small"}:
            eject_lanes = boundary_between or (lane,)
            command_due = (
                center.video_time_seconds + self.config.arduino_command_delay_seconds
            )
        else:
            eject_lanes = ()
            command_due = None

        image_directory = self.config.image_root / self.work_order.work_order_no
        image_directory.mkdir(parents=True, exist_ok=True)
        image_path = image_directory / (
            f"{self.work_order.work_order_no}-P{self.next_sequence:06d}.jpg"
        )
        if center.crop is None or not cv2.imwrite(str(image_path), center.crop):
            self.database.add_anomaly(
                code="IMAGE_SAVE_FAILED",
                message=f"無法儲存第 {self.next_sequence} 顆花生圖片",
                severity=Severity.CRITICAL,
                work_order_id=self.work_order.id,
                deduplicate_active=False,
            )

        weight_estimate = None if interrupted else self.weight_calibration.estimate_grams(area_mean)
        record = PeanutRecord(
            work_order_id=self.work_order.id,
            sequence_no=self.next_sequence,
            track_id=state.track_id,
            detected_at=datetime.now().isoformat(timespec="milliseconds"),
            classification=classification,
            confidence_center=center.confidence,
            confidence_mean=confidence_mean,
            valid_frames=len(classification_window),
            class_counts={name: int(counts[name]) for name in ("normal", "mold", "small")},
            area_mean_px2=area_mean,
            weight_est_g=weight_estimate,
            lane=lane,
            boundary_between=boundary_between,
            eject_lanes=tuple(eject_lanes),
            predicted_false_reject=False,
            model_version=self.model_version,
            model_hash=self.model_hash,
            image_path=image_path,
            session_token=self.session_token,
            center_frame_number=center.frame_number,
            center_time_seconds=center.video_time_seconds,
            command_due_time_seconds=command_due,
            mean_width_px=mean_width,
            speed_px_per_frame=speed,
            record_status="INTERRUPTED" if interrupted else "COMPLETE",
        )
        self.next_sequence += 1
        return record

    def _flush_interrupted_tracks(self, frame_height: int) -> None:
        """立即停止或影片結束時，保存已跨中央但尚未完成七幀的物件。"""
        interrupted_states = [
            state
            for state in self.tracks.values()
            if state.crossed_center
            and state.center_index is not None
            and not state.finalized
        ]
        for state in interrupted_states:
            state.finalized = True
            record = self._build_record(state, frame_height, interrupted=True)
            record.id = self.database.insert_peanut(record)
            self._save_training_snapshot(state.center_snapshot, record)
            self.completed_tracks[state.track_id] = state.last_seen_frame
            self._emit("peanut", record)
        if interrupted_states:
            self._emit("stats", self.database.stats(self.work_order.id))
            self._emit(
                "status",
                f"已保存 {len(interrupted_states)} 顆未收滿七幀的 INTERRUPTED 紀錄",
            )
        self.tracks.clear()

    def _remember_frame_snapshot(self, snapshot: FrameSnapshot) -> None:
        self.frame_snapshots[snapshot.frame_number] = snapshot
        keep_count = self.config.pre_center_frames + self.config.post_center_frames + 4
        cutoff = snapshot.frame_number - keep_count
        self.frame_snapshots = {
            frame_number: value
            for frame_number, value in self.frame_snapshots.items()
            if frame_number >= cutoff
        }

    def _save_training_snapshot(
        self, snapshot: FrameSnapshot | None, record: PeanutRecord
    ) -> None:
        if snapshot is None:
            self.database.add_anomaly(
                code="TRAINING_FRAME_MISSING",
                message=f"第 {record.sequence_no} 顆找不到無標記中央原始幀",
                severity=Severity.WARNING,
                work_order_id=self.work_order.id,
                deduplicate_active=False,
            )
            return

        sample_directory = self.config.training_capture_root / self.work_order.work_order_no
        image_directory = sample_directory / "images"
        metadata_directory = sample_directory / "metadata"
        image_directory.mkdir(parents=True, exist_ok=True)
        metadata_directory.mkdir(parents=True, exist_ok=True)
        stem = (
            f"{self.work_order.work_order_no}-S{self.session_token}"
            f"-F{snapshot.frame_number:08d}"
        )
        image_path = image_directory / f"{stem}.jpg"
        metadata_path = metadata_directory / f"{stem}.json"

        if not image_path.exists() and not cv2.imwrite(str(image_path), snapshot.frame):
            self.database.add_anomaly(
                code="TRAINING_IMAGE_SAVE_FAILED",
                message=f"無法保存訓練原始幀：{image_path.name}",
                severity=Severity.CRITICAL,
                work_order_id=self.work_order.id,
                deduplicate_active=False,
            )
            return

        frame_height, frame_width = snapshot.frame.shape[:2]
        objects = []
        for item in snapshot.observations:
            x1, y1, x2, y2 = item.bbox
            objects.append(
                {
                    "track_id": item.track_id,
                    "class_id": item.class_id,
                    "class_name": item.label,
                    "confidence": item.confidence,
                    "bbox_xyxy": [x1, y1, x2, y2],
                    "bbox_xywhn": [
                        ((x1 + x2) / 2) / frame_width,
                        ((y1 + y2) / 2) / frame_height,
                        (x2 - x1) / frame_width,
                        (y2 - y1) / frame_height,
                    ],
                }
            )

        metadata = {
            "work_order_no": self.work_order.work_order_no,
            "material_lot": self.work_order.material_lot,
            "session_token": self.session_token,
            "frame_number": snapshot.frame_number,
            "image_width": frame_width,
            "image_height": frame_height,
            "source_model_version": self.model_version,
            "source_model_hash": self.model_hash,
            "objects": objects,
            "associated_peanuts": [],
        }
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        associated = metadata.setdefault("associated_peanuts", [])
        if record.sequence_no not in [item.get("sequence_no") for item in associated]:
            associated.append(
                {
                    "sequence_no": record.sequence_no,
                    "classification": record.classification,
                    "confidence_mean": record.confidence_mean,
                    "record_status": record.record_status,
                }
            )
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        needs_manual = (
            record.classification == "unknown"
            or record.record_status != "COMPLETE"
            or record.confidence_mean < self.config.production_confidence
        )
        review_status = "NEEDS_MANUAL_LABEL" if needs_manual else "CAPTURED"
        reason = (
            "低信心、unknown 或未完成七幀，保留供人工標註"
            if needs_manual
            else "等待 x 模型高信心自動標註與 x/s 一致性比較"
        )
        self.database.upsert_training_sample(
            work_order_id=self.work_order.id,
            session_token=self.session_token,
            frame_number=snapshot.frame_number,
            image_path=image_path,
            metadata_path=metadata_path,
            review_status=review_status,
            review_reason=reason,
        )

    @staticmethod
    def _mean_speed(window: list[Observation]) -> float:
        speeds: list[float] = []
        for first, second in zip(window, window[1:]):
            frame_delta = second.frame_number - first.frame_number
            if frame_delta > 0:
                speeds.append(abs(second.cx - first.cx) / frame_delta)
        return sum(speeds) / len(speeds) if speeds else 0.0

    def _lane_for_y(self, cy: int, frame_height: int) -> tuple[int, tuple[int, int] | None]:
        lane_height = frame_height / self.config.lane_count
        half_width = max(1, int(frame_height * self.config.lane_boundary_half_width_ratio))
        for boundary_index in range(1, self.config.lane_count):
            boundary_y = int(lane_height * boundary_index)
            if abs(cy - boundary_y) <= half_width:
                return boundary_index, (boundary_index, boundary_index + 1)
        lane = min(self.config.lane_count, max(1, int(cy / lane_height) + 1))
        return lane, None

    def _update_false_rejects(self, newest: PeanutRecord) -> None:
        minimum_frame = newest.center_frame_number - self.config.recent_record_frames
        self.recent_records = [
            item for item in self.recent_records if item.center_frame_number >= minimum_frame
        ]
        for other in self.recent_records:
            if other is newest:
                continue
            if newest.classification in {"mold", "small"} and other.classification == "normal":
                ng, normal = newest, other
            elif other.classification in {"mold", "small"} and newest.classification == "normal":
                ng, normal = other, newest
            else:
                continue

            normal_lanes = set(normal.boundary_between or (normal.lane,))
            if not normal_lanes.intersection(ng.eject_lanes):
                continue
            average_speed = (ng.speed_px_per_frame + normal.speed_px_per_frame) / 2.0
            average_speed = max(average_speed, 1.0)
            estimated_separation = (
                abs(ng.center_frame_number - normal.center_frame_number) * average_speed
            )
            peanut_length = max(ng.mean_width_px, normal.mean_width_px)
            if estimated_separation <= peanut_length and normal.id is not None:
                if self.database.mark_false_reject(normal.id):
                    normal.predicted_false_reject = True
                    self._emit("false_reject", normal)

    def _check_target_weight(self, stats) -> None:
        if not self.weight_calibration.enabled:
            return
        if stats.total_weight_g < self.work_order.target_weight_g:
            return
        self._faulted = True
        self.database.set_work_order_status(self.work_order.id, "FAULT")
        anomaly_id = self.database.add_anomaly(
            code="TARGET_WEIGHT_REACHED",
            message=(
                f"已達目標重量：{stats.total_weight_g:.2f} g / "
                f"{self.work_order.target_weight_g:.2f} g，Python 辨識已立即停止"
            ),
            severity=Severity.CRITICAL,
            work_order_id=self.work_order.id,
        )
        self._emit("target_reached", {"stats": stats, "anomaly_id": anomaly_id})
        self.stop_event.set()

    def _cleanup_tracks(self, frame_number: int, seen_track_ids: set[int]) -> None:
        stale_ids = [
            track_id
            for track_id, state in self.tracks.items()
            if track_id not in seen_track_ids
            and frame_number - state.last_seen_frame > self.config.stale_track_frames
        ]
        for track_id in stale_ids:
            self.tracks.pop(track_id, None)

        completed_cutoff = frame_number - self.config.stale_track_frames * 4
        self.completed_tracks = {
            track_id: completed_frame
            for track_id, completed_frame in self.completed_tracks.items()
            if completed_frame >= completed_cutoff
        }

    def _crop_with_margin(
        self, frame: np.ndarray, bbox: tuple[int, int, int, int]
    ) -> np.ndarray:
        x1, y1, x2, y2 = bbox
        margin_x = int((x2 - x1) * self.config.crop_margin_ratio)
        margin_y = int((y2 - y1) * self.config.crop_margin_ratio)
        crop_x1 = max(0, x1 - margin_x)
        crop_y1 = max(0, y1 - margin_y)
        crop_x2 = min(frame.shape[1], x2 + margin_x)
        crop_y2 = min(frame.shape[0], y2 + margin_y)
        return frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()

    def _draw_guides(self, frame: np.ndarray, center_x: int, height: int, width: int) -> None:
        cv2.line(frame, (center_x, 0), (center_x, height), (255, 0, 255), 2)
        cv2.putText(
            frame,
            "CENTER / R -> L",
            (max(5, center_x - 170), 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 0, 255),
            2,
        )
        lane_height = height / self.config.lane_count
        half_width = max(1, int(height * self.config.lane_boundary_half_width_ratio))
        overlay = frame.copy()
        for boundary_index in range(1, self.config.lane_count):
            boundary_y = int(lane_height * boundary_index)
            cv2.rectangle(
                overlay,
                (0, boundary_y - half_width),
                (width, boundary_y + half_width),
                (255, 120, 0),
                -1,
            )
            cv2.line(frame, (0, boundary_y), (width, boundary_y), (255, 120, 0), 1)
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
        for lane in range(1, self.config.lane_count + 1):
            label_y = int((lane - 0.5) * lane_height)
            cv2.putText(
                frame,
                f"L{lane}",
                (10, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2,
            )

    @staticmethod
    def _draw_box(frame: np.ndarray, observation: Observation, track_id: int) -> None:
        colors = {
            "normal": (0, 210, 0),
            "mold": (0, 0, 255),
            "small": (0, 220, 255),
        }
        color = colors.get(observation.label, (220, 220, 220))
        x1, y1, x2, y2 = observation.bbox
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.circle(frame, (observation.cx, observation.cy), 4, color, -1)
        cv2.putText(
            frame,
            f"#{track_id} {observation.label} {observation.confidence:.2f}",
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )
