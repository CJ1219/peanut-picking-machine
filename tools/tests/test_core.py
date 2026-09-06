from __future__ import annotations

import queue
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np

from peanut_app.config import AppConfig
from peanut_app.database import ProductionDatabase
from peanut_app.detection import DetectionWorker, FrameSnapshot, Observation
from peanut_app.domain import WorkOrderInput
from peanut_app.weight import WeightCalibration
from peanut_app.training import TrainingPipeline
from peanut_app.analytics import AnalyticsService
from peanut_app.test_work_orders import get_test_work_order, parse_test_work_order_number


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.config = AppConfig(
            model_path=root / "missing-s.pt",
            x_model_path=root / "missing-x.pt",
            video_path=root / "missing.mp4",
            data_root=root,
            database_path=root / "test.sqlite3",
            image_root=root / "images",
            training_capture_root=root / "captures",
            training_root=root / "training",
            calibration_path=root / "calibration.json",
        )
        self.config.ensure_directories()
        self.database = ProductionDatabase(self.config.database_path)
        self.work_order = self.database.create_work_order(
            WorkOrderInput(
                vendor_code="001",
                variety_code="001",
                material_lot="LOT-001",
                material_manufacture_date="2026-08-01",
                target_weight_g=1000.0,
            ),
            production_day=date(2026, 8, 30),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_work_order_number(self) -> None:
        self.assertEqual(self.work_order.work_order_no, "26H30-001-001-001")

    def test_weight_is_disabled_until_calibrated(self) -> None:
        calibration = WeightCalibration.load(self.config.calibration_path)
        self.assertFalse(calibration.enabled)
        self.assertIsNone(calibration.estimate_grams(1200.0))

    def test_right_to_left_crossing_builds_seven_frame_record(self) -> None:
        worker = DetectionWorker(
            config=self.config,
            database=self.database,
            work_order=self.work_order,
            video_source=self.config.video_path,
            event_queue=queue.Queue(),
        )
        center_x = 500
        frame_height = 400
        xs = [650, 600, 550, 510, 490, 450, 410]
        labels = ["normal", "mold", "mold", "mold", "normal", "normal", "normal"]
        crop = np.zeros((40, 80, 3), dtype=np.uint8)
        raw_frame = np.zeros((100, 800, 3), dtype=np.uint8)
        for frame_number, (cx, label) in enumerate(zip(xs, labels), start=1):
            observation = Observation(
                track_id=1,
                class_id={"normal": 0, "mold": 1, "small": 2}[label],
                frame_number=frame_number,
                video_time_seconds=frame_number / 30.0,
                label=label,
                confidence=0.9,
                bbox=(cx - 40, 30, cx + 40, 70),
                cx=cx,
                cy=50,
                area_px2=3200.0,
                crop=crop,
            )
            worker._remember_frame_snapshot(
                FrameSnapshot(
                    frame_number=frame_number,
                    frame=raw_frame.copy(),
                    observations=[observation],
                )
            )
            worker._update_track(1, observation, center_x, frame_height)

        stats = self.database.stats(self.work_order.id)
        self.assertEqual(stats.mold, 1)
        self.assertEqual(stats.classified_total, 1)
        saved_images = list(self.config.image_root.glob("*/*.jpg"))
        self.assertEqual(len(saved_images), 1)
        training_images = list(self.config.training_capture_root.glob("*/images/*.jpg"))
        metadata_files = list(self.config.training_capture_root.glob("*/metadata/*.json"))
        self.assertEqual(len(training_images), 1)
        self.assertEqual(len(metadata_files), 1)
        metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
        self.assertEqual(len(metadata["objects"]), 1)
        self.assertNotIn("annotated", metadata)
        samples = self.database.training_sample_rows()
        self.assertEqual(samples[0]["review_status"], "CAPTURED")

    def test_stop_preserves_crossed_track_as_interrupted(self) -> None:
        worker = DetectionWorker(
            config=self.config,
            database=self.database,
            work_order=self.work_order,
            video_source=self.config.video_path,
            event_queue=queue.Queue(),
        )
        crop = np.zeros((40, 80, 3), dtype=np.uint8)
        for frame_number, cx in enumerate([650, 600, 550, 510, 490], start=1):
            worker._update_track(
                2,
                Observation(
                    track_id=2,
                    class_id=0,
                    frame_number=frame_number,
                    video_time_seconds=frame_number / 30.0,
                    label="normal",
                    confidence=0.9,
                    bbox=(cx - 40, 30, cx + 40, 70),
                    cx=cx,
                    cy=50,
                    area_px2=3200.0,
                    crop=crop,
                ),
                center_x=500,
                frame_height=400,
            )
        worker._flush_interrupted_tracks(frame_height=400)
        stats = self.database.stats(self.work_order.id)
        self.assertEqual(stats.unknown, 1)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT record_status, weight_est_g FROM peanuts LIMIT 1"
            ).fetchone()
        self.assertEqual(row["record_status"], "INTERRUPTED")
        self.assertIsNone(row["weight_est_g"])

    def test_x_s_agreement_uses_class_and_iou(self) -> None:
        x_items = [{"class_id": 1, "xywhn": [0.5, 0.5, 0.2, 0.2]}]
        s_items = [{"class_id": 1, "bbox_xywhn": [0.5, 0.5, 0.2, 0.2]}]
        self.assertTrue(TrainingPipeline._x_s_agree(x_items, s_items))
        s_items[0]["class_id"] = 0
        self.assertFalse(TrainingPipeline._x_s_agree(x_items, s_items))

    def test_dataset_split_requires_two_work_order_batches(self) -> None:
        single_group = [(Path("a.jpg"), Path("a.txt"), "WO1::LOT1", 1)]
        with self.assertRaises(RuntimeError):
            TrainingPipeline._group_split(single_group)
        items = single_group + [(Path("b.jpg"), Path("b.txt"), "WO2::LOT2", 2)]
        train_items, validation_items = TrainingPipeline._group_split(items)
        self.assertTrue(train_items)
        self.assertTrue(validation_items)
        self.assertNotEqual(train_items[0][2], validation_items[0][2])

    def test_model_auto_activation_and_rollback_preserve_versions(self) -> None:
        root = Path(self.temporary_directory.name)
        baseline = root / "baseline.pt"
        candidate = root / "candidate.pt"
        baseline.write_bytes(b"baseline")
        candidate.write_bytes(b"candidate")
        self.database.ensure_initial_model("baseline", baseline, "hash-base")
        self.database.register_model_version(
            "candidate", candidate, "hash-candidate", {"mAP50": 0.9}, active=False
        )
        self.database.activate_model("candidate", "AUTO_AFTER_TRAINING")
        self.assertEqual(self.database.active_model()["version"], "candidate")
        self.database.activate_model("baseline", "MANUAL_ROLLBACK_OR_SELECTION")
        self.assertEqual(self.database.active_model()["version"], "baseline")
        self.assertEqual(len(self.database.model_version_rows()), 2)

    def test_qwen_rejects_lan_endpoint(self) -> None:
        with self.assertRaises(ValueError):
            AnalyticsService(self.database).qwen_report(
                endpoint="http://192.168.1.10:11434/api/generate",
                model="qwen3.5:9b",
            )

    def test_quick_work_order_number_matches_barcode_payload(self) -> None:
        first = get_test_work_order(1)
        last = get_test_work_order(100)
        self.assertEqual(first.barcode_value, "PEANUT-WO:001")
        self.assertEqual(first.material_lot, "TEST-202609-001")
        self.assertEqual(parse_test_work_order_number("1"), 1)
        self.assertEqual(parse_test_work_order_number(last.barcode_value), 100)
        self.assertIsNone(parse_test_work_order_number("101"))

    def test_batch_history_lists_and_deletes_selected_work_order(self) -> None:
        second = self.database.create_work_order(
            WorkOrderInput(
                vendor_code="002",
                variety_code="003",
                material_lot="LOT-DELETE",
                material_manufacture_date="2026-08-02",
                target_weight_g=2000.0,
            ),
            production_day=date(2026, 8, 31),
        )
        rows = self.database.list_production_batches()
        self.assertEqual([row["id"] for row in rows], [second.id, self.work_order.id])
        self.database.add_anomaly("TEST", "delete me", work_order_id=second.id)
        self.database.delete_production_batches([second.id])
        self.assertIsNone(self.database.get_work_order(second.id))
        self.assertEqual(len(self.database.list_production_batches()), 1)
        self.assertFalse(self.database.list_anomalies(work_order_id=second.id))


if __name__ == "__main__":
    unittest.main()
