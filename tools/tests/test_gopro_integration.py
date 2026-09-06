import importlib
import queue
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

import test_core
from peanut_app.gopro_detection import GoProDetectionWorker


class GoProIntegrationTests(unittest.TestCase):
    setUp = test_core.CoreTests.setUp
    tearDown = test_core.CoreTests.tearDown

    def worker(self):
        return GoProDetectionWorker(self.config, self.database, self.work_order,
                                    "gopro", queue.Queue())

    def frame(self, worker, number, x, label, triggered=False, seen=True):
        box = SimpleNamespace(id=np.array([1]), cls=np.array([0]),
                              conf=np.array([0.9]), xyxy=np.array([[x, 295, x+40, 335]]))
        raw = np.zeros((1080, 1920, 3), dtype=np.uint8)
        worker._on_frame(raw, raw, [SimpleNamespace(boxes=[box] if seen else [])],
                         {0: label}, {1: label}, {1: triggered}, number, number/30,
                         {1} if seen else set())

    def test_final_small_overrides_earlier_normal_and_is_counted_once(self):
        worker = self.worker()
        self.frame(worker, 1, 360, "normal")
        self.frame(worker, 2, 2, "small", True)
        self.frame(worker, 3, 0, "small", True)
        stats = self.database.stats(self.work_order.id)
        self.assertEqual((stats.normal, stats.small, stats.total), (0, 1, 1))
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM peanuts").fetchone()
        self.assertEqual(row["eject_lanes_json"], "[1, 2]")
        self.assertEqual(row["record_status"], "GOPRO_TRIGGERED")
        self.assertTrue(list(self.config.training_capture_root.rglob("*.json")))

    def test_lost_track_uses_original_first_matching_servo(self):
        worker = self.worker()
        self.frame(worker, 1, 20, "mold")
        self.frame(worker, 2, 0, "mold", True, seen=False)
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM peanuts").fetchone()
        self.assertEqual(row["record_status"], "GOPRO_PREDICTED")
        self.assertEqual(row["eject_lanes_json"], "[1]")

    def test_import_does_not_load_hardware_packages(self):
        with patch.dict(sys.modules, {"serial": None, "multi_webcam": None}):
            import detect_open_gopro
            importlib.reload(detect_open_gopro)

    def test_model_failure_closes_serial_and_resets_servos(self):
        from detect_open_gopro import run_detection
        serial_device = Mock()
        serial_device.readline.return_value = b""
        fake_yolo = SimpleNamespace(YOLO=Mock(side_effect=RuntimeError("bad model")))
        modules = {"ultralytics": fake_yolo,
                   "serial": SimpleNamespace(Serial=Mock(return_value=serial_device)),
                   "multi_webcam": SimpleNamespace(),
                   "multi_webcam.webcam": SimpleNamespace(Webcam=Mock())}
        with patch.dict(sys.modules, modules), patch("time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "bad model"):
                run_detection(on_frame=Mock())
        serial_device.close.assert_called_once()
        # Four initialization commands, FAULT, S, then four safe reset commands.
        self.assertEqual(serial_device.write.call_count, 10)

    def test_missing_model_does_not_open_serial(self):
        from detect_open_gopro import run_detection
        with patch.dict(sys.modules, {"serial": None}):
            with self.assertRaises(FileNotFoundError):
                run_detection(model_path=self.config.model_path)

    def test_gui_uses_working_engine_defaults(self):
        import detect_open_gopro as entry
        worker = self.worker()
        self.assertEqual(worker.arduino_port, "COM7")
        self.assertEqual(worker.model_path, entry.DEFAULT_MODEL)
        self.assertEqual(entry.run_detection.__module__, "中興AI競賽.detect_open_gopro")
        self.assertEqual(entry.LANE_RANGES[0], (75, 330))
        self.assertTrue(callable(worker._on_started))
        self.assertEqual(entry.GOPRO_WEBCAM_RESOLUTION, 12)
        self.assertEqual(entry.GOPRO_WEBCAM_FOV, 4)

    def test_started_callback_updates_work_order_and_emits_event(self):
        worker = self.worker()
        values = {"fps": 30.0, "width": 1920, "height": 1080}
        worker._on_started(values)
        event = worker.event_queue.get_nowait()
        self.assertEqual(event.kind, "started")
        self.assertEqual(event.payload, values)
        self.assertEqual(self.database.latest_work_order().status, "RUNNING")

    def test_connection_error_is_reported_without_exiting(self):
        worker = self.worker()
        with (
            patch("detect_open_gopro.run_detection", side_effect=RuntimeError("COM7 disconnected")),
            patch.object(worker, "_monitor_arduino_after_fault"),
        ):
            worker.run()
        events = []
        while not worker.event_queue.empty():
            events.append(worker.event_queue.get_nowait())
        error = next(event for event in events if event.kind == "error")
        self.assertIn("COM7", error.payload["message"])
        self.assertTrue(worker._faulted)

    def test_same_lane_normal_and_ng_counts_only_ng(self):
        worker = self.worker()
        normal = SimpleNamespace(
            id=np.array([1]), cls=np.array([0]), conf=np.array([0.9]),
            xyxy=np.array([[2, 200, 42, 240]]),
        )
        mold = SimpleNamespace(
            id=np.array([2]), cls=np.array([1]), conf=np.array([0.9]),
            xyxy=np.array([[2, 210, 42, 250]]),
        )
        raw = np.zeros((1080, 1920, 3), dtype=np.uint8)
        worker._on_frame(
            raw, raw, [SimpleNamespace(boxes=[normal, mold])],
            {0: "normal", 1: "mold"},
            {1: "normal", 2: "mold"}, {1: True, 2: True}, 1, 0.1, {1, 2},
        )
        stats = self.database.stats(self.work_order.id)
        self.assertEqual((stats.normal, stats.mold, stats.total), (0, 1, 1))

    def test_ng_priority_is_independent_of_detection_order(self):
        from detect_open_gopro import resolve_ng_priority_pins
        objects = [("normal", 220), ("mold", 230)]
        self.assertEqual(resolve_ng_priority_pins({2}, objects), {2})
        self.assertEqual(resolve_ng_priority_pins({2}, reversed(objects)), {2})

    def test_gui_controls_send_arduino_start_and_stop_commands(self):
        worker = self.worker()
        sender = Mock()
        worker._on_arduino_ready(sender)
        worker.pause()
        worker.resume()
        worker.stop()
        self.assertEqual(
            [call.args[0] for call in sender.call_args_list], ["S", "START", "S"]
        )

    def test_indicator_state_is_sent_to_arduino(self):
        worker = self.worker()
        sender = Mock()
        worker._on_arduino_ready(sender)
        worker.set_indicator_state("FAULT")
        self.assertEqual(worker._indicator_state, "FAULT")
        sender.assert_called_once_with("STATE,FAULT")

    def test_physical_button_state_updates_worker(self):
        worker = self.worker()
        worker._on_arduino_event("PY:STATE:STOPPED")
        self.assertTrue(worker.pause_event.is_set())
        self.assertEqual(worker.event_queue.get_nowait().payload, "STOPPED")
        worker._on_arduino_event("PY:STATE:RUNNING")
        self.assertFalse(worker.pause_event.is_set())
        self.assertEqual(worker.event_queue.get_nowait().payload, "RUNNING")
        worker._on_arduino_event("PY:BUTTON:YELLOW")
        self.assertEqual(worker.event_queue.get_nowait().kind, "arduino_yellow")
        worker._on_arduino_event("PY:DIRECTION:R")
        self.assertEqual(worker.arduino_direction, "R")
        self.assertEqual(worker.event_queue.get_nowait().kind, "arduino_direction")

    def test_serial_disconnect_creates_current_fault(self):
        worker = self.worker()
        worker._on_arduino_event("PY:ERROR:cable removed")
        active = self.database.list_anomalies(
            work_order_id=self.work_order.id, active_only=True
        )
        self.assertEqual(active[0].code, "ARDUINO_SERIAL_ERROR")
        self.assertTrue(worker._faulted)

    def test_yellow_button_keeps_current_missing_production_anomaly(self):
        from peanut_app.domain import MachineState, Severity
        from peanut_app.gui import PeanutProductionApp

        app = PeanutProductionApp(self.config)
        app.withdraw()
        app.current_work_order = None
        app.database.add_anomaly(
            "MISSING_PRODUCTION_DATA", "尚未填入生產資料", Severity.WARNING
        )
        app.database.add_anomaly(
            "GOPRO_RUNTIME_ERROR", "先前的程式錯誤", Severity.CRITICAL,
            self.work_order.id,
        )
        app._handle_arduino_yellow()
        active_codes = {
            item.code for item in app.database.list_anomalies(active_only=True)
        }
        self.assertEqual(active_codes, {"MISSING_PRODUCTION_DATA"})
        self.assertEqual(app.machine_state, MachineState.FAULT)
        app.destroy()

    def test_arduino_firmware_exposes_machine_protocol_and_lamps(self):
        from pathlib import Path

        firmware = Path("main_control/main_control.ino").read_text(
            encoding="utf-8-sig"
        )
        for token in (
            "PY:STATE:RUNNING", "PY:STATE:STOPPED", "PY:BUTTON:YELLOW",
            "PY:DIRECTION:", "startSelectedDirection", "STATE,RUNNING",
            "updateStatusLamps", "YELLOW_BLINK_INTERVAL",
        ):
            self.assertIn(token, firmware)
