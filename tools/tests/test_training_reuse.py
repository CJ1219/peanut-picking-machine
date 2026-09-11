import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from peanut_app.config import AppConfig
from peanut_app.training import TrainingPipeline


class TrainingReuseTests(unittest.TestCase):
    def check_reuse(self, missing_label):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            weight = root / "m.pt"
            weight.touch()
            label = root / "existing.txt"
            label.write_text("0 0.5 0.5 0.2 0.2\n")
            image = root / "frame.jpg"
            image.touch()
            metadata = root / "frame.json"
            metadata.write_text('{"objects": []}')
            rows = [
                dict(id=i, image_path=str(image), metadata_path=str(metadata),
                     x_labels_path=str(label), review_status=status,
                     work_order_no="WO", material_lot="LOT")
                for i, status in enumerate(("APPROVED", "X_TRAINING", "NEEDS_REVIEW"), 1)
            ]
            if missing_label:
                rows.append(dict(rows[0], id=4, review_status="CAPTURED",
                                 x_labels_path=str(root / "missing.txt")))
            database = Mock()
            database.training_sample_rows.side_effect = [rows, rows[:2]]
            database.create_training_run.return_value = 1
            config = AppConfig(m_model_path=weight, x_model_path=weight if missing_label else root / "no-x.pt",
                               training_root=root / "training")
            pipeline = TrainingPipeline(config, database)
            model = Mock(names={0: "normal"})
            teacher = Mock(names={0: "normal"})
            teacher.predict.return_value = [Mock(boxes=[])]
            with patch.object(pipeline, "_load_training_model", return_value=model), \
                 patch("ultralytics.YOLO", return_value=teacher) as load_x, \
                 patch.object(pipeline, "_prepare_mixed_dataset", side_effect=RuntimeError("STOP_AT_DATASET")) as prepare:
                with self.assertRaisesRegex(RuntimeError, "STOP_AT_DATASET"):
                    pipeline.run()
            self.assertEqual(load_x.call_count, int(missing_label))
            self.assertEqual(teacher.predict.call_count, int(missing_label))
            self.assertEqual(len(prepare.call_args.args[1]), 2)
            self.assertEqual(label.read_text(), "0 0.5 0.5 0.2 0.2\n")
            for call in database.update_training_sample_review.call_args_list:
                self.assertEqual(call.args[0], 4)

    def test_existing_labels_skip_x_and_preserve_review_status(self):
        self.check_reuse(False)

    def test_missing_label_file_is_only_sample_sent_to_x(self):
        self.check_reuse(True)


if __name__ == "__main__":
    unittest.main()
