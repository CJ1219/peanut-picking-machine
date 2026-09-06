from __future__ import annotations

import json
import random
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import AppConfig
from .database import ProductionDatabase
from .model_registry import file_hash


ProgressCallback = Callable[[str], None]


class TrainingPipeline:
    """以原始完整幀執行 x 自動標註、x/s 分流及 s 模型訓練。"""

    def __init__(self, config: AppConfig, database: ProductionDatabase):
        self.config = config
        self.database = database

    def run(
        self,
        auto_label_confidence: float = 0.90,
        epochs: int = 100,
        progress: ProgressCallback | None = None,
    ) -> Path:
        from ultralytics import YOLO

        callback = progress or (lambda _message: None)
        if not self.config.x_model_path.exists():
            raise FileNotFoundError(f"找不到 x 模型：{self.config.x_model_path}")

        active_model = self.database.active_model()
        s_model_path = (
            Path(active_model["weight_path"])
            if active_model is not None
            else self.config.model_path
        )
        if not s_model_path.exists():
            raise FileNotFoundError(f"找不到目前 s 模型：{s_model_path}")

        samples = self.database.training_sample_rows(
            statuses=(
                "CAPTURED",
                "AUTO_CANDIDATE",
                "APPROVED",
                "NEEDS_REVIEW",
                "NEEDS_MANUAL_LABEL",
            )
        )
        if len(samples) < 2:
            raise RuntimeError("至少需要 2 張已保存的完整原始幀才能建立候選資料集")

        run_id = self.database.create_training_run(self.config.x_model_path, s_model_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_root = self.config.training_root / f"training_{timestamp}_{run_id:04d}"
        dataset_root = run_root / "dataset"
        auto_label_root = run_root / "x_auto_labels"
        auto_label_root.mkdir(parents=True, exist_ok=True)

        try:
            self.database.update_training_run(run_id, "AUTO_LABELING")
            callback("載入 x 模型，對完整無框線原始幀執行高信心自動標註……")
            x_model = YOLO(str(self.config.x_model_path))
            names = x_model.names

            for index, sample in enumerate(samples, start=1):
                image_path = Path(sample["image_path"])
                metadata_path = Path(sample["metadata_path"])
                if not image_path.exists() or not metadata_path.exists():
                    self.database.update_training_sample_review(
                        sample["id"],
                        "NEEDS_MANUAL_LABEL",
                        "原始幀或座標 metadata 遺失",
                    )
                    continue

                result = x_model.predict(
                    source=str(image_path),
                    conf=auto_label_confidence,
                    imgsz=self.config.inference_image_size,
                    verbose=False,
                )[0]
                x_detections: list[dict] = []
                label_lines: list[str] = []
                for box in result.boxes:
                    confidence = float(box.conf[0].item())
                    if confidence < auto_label_confidence:
                        continue
                    class_id = int(box.cls[0].item())
                    x_center, y_center, width, height = box.xywhn[0].tolist()
                    x_detections.append(
                        {
                            "class_id": class_id,
                            "confidence": confidence,
                            "xywhn": [x_center, y_center, width, height],
                        }
                    )
                    label_lines.append(
                        f"{class_id} {x_center:.8f} {y_center:.8f} "
                        f"{width:.8f} {height:.8f}"
                    )

                x_label_path = auto_label_root / f"sample_{sample['id']:08d}.txt"
                if label_lines:
                    x_label_path.write_text("\n".join(label_lines) + "\n", encoding="utf-8")

                current_status = str(sample["review_status"])
                if current_status == "APPROVED":
                    continue
                if current_status == "NEEDS_MANUAL_LABEL":
                    if label_lines:
                        self.database.update_training_sample_review(
                            sample["id"],
                            "NEEDS_MANUAL_LABEL",
                            "線上低信心或 unknown；保留 x 候選框供人工標註參考",
                            x_label_path,
                        )
                    continue
                if not x_detections:
                    self.database.update_training_sample_review(
                        sample["id"],
                        "NEEDS_MANUAL_LABEL",
                        "x 模型沒有足夠高信心的標註",
                    )
                    continue

                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                s_detections = [
                    item
                    for item in metadata.get("objects", [])
                    if float(item.get("confidence", 0.0)) >= self.config.production_confidence
                ]
                if self._x_s_agree(x_detections, s_detections):
                    self.database.update_training_sample_review(
                        sample["id"],
                        "AUTO_CANDIDATE",
                        "x 高信心且與線上 s 判定一致，自動加入訓練候選集",
                        x_label_path,
                    )
                else:
                    self.database.update_training_sample_review(
                        sample["id"],
                        "NEEDS_REVIEW",
                        "x 與 s 的類別、數量或位置不一致，等待人工確認",
                        x_label_path,
                    )
                if index % 25 == 0 or index == len(samples):
                    callback(f"自動標註與分流：{index}/{len(samples)}")

            accepted_rows = self.database.training_sample_rows(
                statuses=("AUTO_CANDIDATE", "APPROVED")
            )
            if len(accepted_rows) < 2:
                raise RuntimeError("自動候選與人工核准資料合計不足 2 張，暫不訓練")

            items = []
            for sample in accepted_rows:
                image_path = Path(sample["image_path"])
                label_path = Path(sample["x_labels_path"] or "")
                if image_path.exists() and label_path.is_file():
                    group = f"{sample['work_order_no']}::{sample['material_lot']}"
                    items.append((image_path, label_path, group, int(sample["id"])))
            train_items, validation_items = self._group_split(items)
            callback("已依工單／物料批次切分 train/val；同一批次不會跨資料集。")

            for split_name, split_items in (("train", train_items), ("val", validation_items)):
                image_directory = dataset_root / "images" / split_name
                label_directory = dataset_root / "labels" / split_name
                image_directory.mkdir(parents=True, exist_ok=True)
                label_directory.mkdir(parents=True, exist_ok=True)
                for image_path, label_path, _group, sample_id in split_items:
                    unique_stem = f"sample_{sample_id:08d}_{image_path.stem}"
                    shutil.copy2(image_path, image_directory / f"{unique_stem}{image_path.suffix}")
                    shutil.copy2(label_path, label_directory / f"{unique_stem}.txt")

            dataset_yaml = dataset_root / "dataset.yaml"
            name_items = names.items() if isinstance(names, dict) else enumerate(names)
            name_lines = "\n".join(
                f"  {class_id}: {class_name}" for class_id, class_name in name_items
            )
            dataset_yaml.write_text(
                f"path: {dataset_root.as_posix()}\n"
                "train: images/train\n"
                "val: images/val\n"
                "names:\n"
                f"{name_lines}\n",
                encoding="utf-8",
            )
            self.database.update_training_run(run_id, "TRAINING", dataset_path=dataset_yaml)
            callback(
                f"資料集完成：train={len(train_items)}、val={len(validation_items)}；"
                "開始訓練 s 模型……"
            )

            s_model = YOLO(str(s_model_path))
            training_result = s_model.train(
                data=str(dataset_yaml),
                epochs=epochs,
                imgsz=self.config.inference_image_size,
                project=str(run_root / "runs"),
                name="s_candidate",
                exist_ok=False,
            )
            output_path = Path(training_result.save_dir)
            candidate_path = output_path / "weights" / "best.pt"
            if not candidate_path.exists():
                raise RuntimeError(f"訓練完成但找不到新權重：{candidate_path}")

            metrics: dict[str, float] = {}
            for name, value in getattr(training_result, "results_dict", {}).items():
                try:
                    metrics[str(name)] = float(value)
                except (TypeError, ValueError):
                    continue
            candidate_version = f"s_auto_{timestamp}_{run_id:04d}"
            self.database.register_model_version(
                version=candidate_version,
                weight_path=candidate_path,
                weight_hash=file_hash(candidate_path),
                metrics=metrics,
                active=False,
            )
            self.database.activate_model(candidate_version, reason="AUTO_AFTER_TRAINING")
            self.database.update_training_run(
                run_id,
                "ACTIVE",
                message=(
                    f"訓練完成並自動啟用 {candidate_version}；舊權重與啟用紀錄均已保留"
                ),
                output_path=output_path,
                finished=True,
            )
            callback(
                f"訓練完成並自動啟用：{candidate_version}。"
                "舊模型未被覆蓋，可在模型版本頁回復。"
            )
            return output_path
        except Exception as exc:
            self.database.update_training_run(
                run_id,
                "FAILED",
                message=str(exc),
                dataset_path=dataset_root if dataset_root.exists() else None,
                finished=True,
            )
            raise

    @staticmethod
    def _x_s_agree(x_detections: list[dict], s_detections: list[dict]) -> bool:
        if len(x_detections) != len(s_detections):
            return False
        unmatched = list(range(len(s_detections)))
        for x_item in x_detections:
            matched_index = None
            for s_index in unmatched:
                s_item = s_detections[s_index]
                if int(x_item["class_id"]) != int(s_item.get("class_id", -1)):
                    continue
                if TrainingPipeline._iou_xywhn(
                    x_item["xywhn"], s_item.get("bbox_xywhn", [0, 0, 0, 0])
                ) >= 0.5:
                    matched_index = s_index
                    break
            if matched_index is None:
                return False
            unmatched.remove(matched_index)
        return not unmatched

    @staticmethod
    def _iou_xywhn(first, second) -> float:
        def xyxy(box):
            x_center, y_center, width, height = [float(value) for value in box]
            return (
                x_center - width / 2,
                y_center - height / 2,
                x_center + width / 2,
                y_center + height / 2,
            )

        ax1, ay1, ax2, ay2 = xyxy(first)
        bx1, by1, bx2, by2 = xyxy(second)
        intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(
            0.0, min(ay2, by2) - max(ay1, by1)
        )
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        union = area_a + area_b - intersection
        return intersection / union if union > 0 else 0.0

    @staticmethod
    def _group_split(items):
        groups = defaultdict(list)
        for item in items:
            groups[item[2]].append(item)
        group_names = sorted(groups)
        if len(group_names) < 2:
            raise RuntimeError(
                "驗證資料必須按工單／批次分割；目前不足 2 個不同工單／批次，暫不訓練"
            )
        random.Random(20260830).shuffle(group_names)
        validation_group_count = max(1, round(len(group_names) * 0.2))
        validation_groups = set(group_names[:validation_group_count])
        train_items = [item for item in items if item[2] not in validation_groups]
        validation_items = [item for item in items if item[2] in validation_groups]
        if not train_items or not validation_items:
            raise RuntimeError("資料無法依工單／批次切分為非空的 train 與 val")
        return train_items, validation_items
