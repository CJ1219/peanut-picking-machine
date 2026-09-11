from __future__ import annotations

import csv
import json
import random
import shutil
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import AppConfig
from .database import ProductionDatabase
from .model_registry import file_hash


ProgressCallback = Callable[[str], None]


class TrainingPipeline:
    """以原始完整幀執行 x 自動標註、資料分流及 M 模型訓練。"""

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
        m_model_path = self.config.m_model_path
        if not m_model_path.exists():
            raise FileNotFoundError(f"找不到 M 模型：{m_model_path}")

        samples = self.database.training_sample_rows(
            statuses=(
                "CAPTURED",
                "AUTO_CANDIDATE",
                "APPROVED",
                "X_TRAINING",
                "NEEDS_REVIEW",
                "NEEDS_MANUAL_LABEL",
            )
        )
        if len(samples) < 2:
            raise RuntimeError("至少需要 2 張已保存的完整原始幀才能建立候選資料集")

        run_id = self.database.create_training_run(self.config.x_model_path, m_model_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_root = self.config.training_root / f"training_{timestamp}_{run_id:04d}"
        dataset_root = run_root / "dataset"
        auto_label_root = run_root / "x_auto_labels"
        auto_label_root.mkdir(parents=True, exist_ok=True)

        try:
            callback(f"檢查 M 訓練起始權重：{m_model_path}")
            m_model = self._load_training_model(m_model_path)
            self.database.update_training_run(run_id, "AUTO_LABELING")
            pending_samples = [
                sample for sample in samples
                if not Path(sample["x_labels_path"] or "").is_file()
            ]
            callback(
                f"沿用既有 X 標註：{len(samples) - len(pending_samples)} 張；"
                f"待標註：{len(pending_samples)} 張。"
            )
            names = m_model.names
            if pending_samples:
                if not self.config.x_model_path.is_file():
                    raise FileNotFoundError(f"找不到 x 模型：{self.config.x_model_path}")
                callback("載入 X 模型，只對尚無標註檔的完整原始幀執行高信心自動標註……")
                x_model = YOLO(str(self.config.x_model_path))
                names = x_model.names

            for index, sample in enumerate(pending_samples, start=1):
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
                        "X 高信心且與線上 M 判定一致，自動加入訓練候選集",
                        x_label_path,
                    )
                else:
                    self.database.update_training_sample_review(
                        sample["id"],
                        "NEEDS_REVIEW",
                        "X 與線上 M 的類別、數量或位置不一致，等待人工確認",
                        x_label_path,
                    )
                if index % 25 == 0 or index == len(pending_samples):
                    callback(f"自動標註與分流：{index}/{len(pending_samples)}")

            accepted_rows = self.database.training_sample_rows(
                statuses=("AUTO_CANDIDATE", "APPROVED", "X_TRAINING")
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
            train_items, validation_items = self._prepare_mixed_dataset(dataset_root, items)
            callback("已按原始資料集比例隨機加入新標註，建立 train/val。")

            for split_name, split_items in (("train", train_items), ("val", validation_items)):
                image_directory = dataset_root / "images" / split_name
                label_directory = dataset_root / "labels" / split_name
                image_directory.mkdir(parents=True, exist_ok=True)
                label_directory.mkdir(parents=True, exist_ok=True)
                for image_path, label_path, _group, sample_id in split_items:
                    unique_stem = f"sample_{sample_id:08d}_{image_path.stem}"
                    shutil.copy2(image_path, image_directory / f"{unique_stem}{image_path.suffix}")
                    shutil.copy2(label_path, label_directory / f"{unique_stem}.txt")

            mixed_counts = self._dataset_image_counts(dataset_root)
            callback(
                "混合資料集："
                f"train={mixed_counts['train']} + val={mixed_counts['val']} + "
                f"test={mixed_counts['test']} = {sum(mixed_counts.values())} 張"
            )

            dataset_yaml = dataset_root / "dataset.yaml"
            name_items = names.items() if isinstance(names, dict) else enumerate(names)
            name_lines = "\n".join(
                f"  {class_id}: {class_name}" for class_id, class_name in name_items
            )
            dataset_yaml.write_text(
                f"path: {dataset_root.as_posix()}\n"
                "train: images/train\n"
                "val: images/val\n"
                "test: images/test\n"
                "names:\n"
                f"{name_lines}\n",
                encoding="utf-8",
            )
            self.database.update_training_run(run_id, "TRAINING", dataset_path=dataset_yaml)
            callback(
                f"新增標註：train={len(train_items)}、val={len(validation_items)}；"
                "開始訓練 M 模型……"
            )

            callback("使用 AMP 混合精度訓練（啟用速度與顯示記憶體最佳化）。")
            training_result = m_model.train(
                data=str(dataset_yaml),
                epochs=epochs,
                imgsz=self.config.inference_image_size,
                project=str(run_root / "runs"),
                name="m_candidate",
                exist_ok=False,
                amp=True,
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
            candidate_version = f"m_auto_{timestamp}_{run_id:04d}"
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
            error_log = run_root / "error_traceback.txt"
            error_log.write_text(traceback.format_exc(), encoding="utf-8")
            callback(f"訓練失敗，完整錯誤紀錄：{error_log}")
            self.database.update_training_run(
                run_id,
                "FAILED",
                message=str(exc),
                dataset_path=dataset_root if dataset_root.exists() else None,
                finished=True,
            )
            raise

    def refresh_x_labels(
        self,
        sample_ids: list[int] | None = None,
        confidence: float = 0.70,
        progress: ProgressCallback | None = None,
    ) -> int:
        """只重新執行 X 自動標註，不啟動 S 模型訓練。"""
        from ultralytics import YOLO
        import cv2
        import numpy as np

        if not self.config.x_model_path.exists():
            raise FileNotFoundError(f"找不到 x 模型：{self.config.x_model_path}")
        callback = progress or (lambda _message: None)
        samples = self.database.training_sample_rows(
            statuses=("CAPTURED", "AUTO_CANDIDATE", "APPROVED", "NEEDS_REVIEW", "NEEDS_MANUAL_LABEL")
        )
        wanted = {int(value) for value in sample_ids} if sample_ids else None
        if wanted is not None:
            samples = [sample for sample in samples if int(sample["id"]) in wanted]
        if not samples:
            return 0

        output_root = self.config.training_root / (
            f"x_refresh_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        output_root.mkdir(parents=True, exist_ok=True)
        x_model = YOLO(str(self.config.x_model_path))
        refreshed = 0
        for index, sample in enumerate(samples, start=1):
            original = Path(sample["image_path"])
            if not original.is_file():
                matches = list(self.config.data_root.rglob(original.name))
                original = matches[0] if matches else original
            if not original.is_file():
                self.database.set_training_sample_x_labels(
                    int(sample["id"]), None, "原始影像遺失，無法執行 X 自動標註"
                )
                continue
            try:
                image = cv2.imdecode(
                    np.frombuffer(original.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR
                )
                if image is None:
                    raise ValueError("影像解碼失敗")
                result = x_model.predict(
                    source=image,
                    conf=confidence,
                    imgsz=self.config.inference_image_size,
                    verbose=False,
                )[0]
                lines: list[str] = []
                for box in result.boxes:
                    score = float(box.conf[0].item())
                    if score < confidence:
                        continue
                    class_id = int(box.cls[0].item())
                    x_center, y_center, box_width, box_height = box.xywhn[0].tolist()
                    lines.append(
                        f"{class_id} {x_center:.8f} {y_center:.8f} "
                        f"{box_width:.8f} {box_height:.8f}"
                    )
                label_path = output_root / f"sample_{int(sample['id']):08d}.txt"
                if lines:
                    label_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    self.database.set_training_sample_x_labels(
                        int(sample["id"]), label_path,
                        f"X 模型重新標註完成，共 {len(lines)} 個候選框（信心 ≥ {confidence:.2f}）",
                    )
                else:
                    self.database.set_training_sample_x_labels(
                        int(sample["id"]), None,
                        f"X 模型重新標註後沒有達到信心 {confidence:.2f} 的候選框",
                    )
                refreshed += 1
            except Exception as exc:
                self.database.set_training_sample_x_labels(
                    int(sample["id"]), None, f"X 自動標註失敗：{exc}"
                )
            if index % 10 == 0 or index == len(samples):
                callback(f"X 標註刷新：{index}/{len(samples)}")
        return refreshed

    def train_m_model(self, epochs: int = 30, progress: ProgressCallback | None = None) -> Path:
        """以人工確認的 X 標註資料接續訓練 M 候選模型，保留目前模型不變。"""
        from ultralytics import YOLO

        callback = progress or (lambda _message: None)
        samples = self.database.training_sample_rows(statuses=("X_TRAINING",))
        samples = [sample for sample in samples if sample["x_labels_path"]]
        if len(samples) < 2:
            raise RuntimeError("至少需要 2 筆已加入 X 訓練集的人工標註")
        callback(f"檢查 M 訓練起始權重：{self.config.m_model_path}")
        model = self._load_training_model(self.config.m_model_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = self.config.training_root / f"m_model_training_{timestamp}"
        train_images, train_labels = root / "images" / "train", root / "labels" / "train"
        val_images, val_labels = root / "images" / "val", root / "labels" / "val"
        for folder in (train_images, train_labels, val_images, val_labels):
            folder.mkdir(parents=True, exist_ok=True)
        new_items = []
        for sample in samples:
            image_path = Path(sample["image_path"])
            if not image_path.is_file():
                matches = list(self.config.data_root.rglob(image_path.name))
                image_path = matches[0] if matches else image_path
            label_path = Path(sample["x_labels_path"])
            if not label_path.is_file():
                matches = list(self.config.data_root.rglob(label_path.name))
                label_path = matches[0] if matches else label_path
            if not image_path.is_file() or not label_path.is_file():
                continue
            new_items.append((image_path, label_path, "manual", int(sample["id"])))
        train_items, validation_items = self._prepare_mixed_dataset(root, new_items)
        for split, items in (("train", train_items), ("val", validation_items)):
            image_dir = root / "images" / split
            label_dir = root / "labels" / split
            for image_path, label_path, _group, sample_id in items:
                (image_dir / f"sample_{sample_id}{image_path.suffix.lower()}").write_bytes(image_path.read_bytes())
                (label_dir / f"sample_{sample_id}.txt").write_text(label_path.read_text(encoding="utf-8"), encoding="utf-8")
        mixed_counts = self._dataset_image_counts(root)
        yaml_path = root / "data.yaml"
        yaml_path.write_text(
            f"path: {root.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\n"
            "names:\n  0: normal\n  1: mold\n  2: small\n",
            encoding="utf-8",
        )
        callback(
            f"混合資料集：train={mixed_counts['train']} + val={mixed_counts['val']} + "
            f"test={mixed_counts['test']} = {sum(mixed_counts.values())} 張；"
            f"開始訓練 M 模型（使用 {len(samples)} 筆人工確認的 X 標註，epochs={epochs}）"
        )
        callback("使用 AMP 混合精度訓練（啟用速度與顯示記憶體最佳化）。")
        try:
            result = model.train(
                data=str(yaml_path), epochs=epochs, imgsz=self.config.inference_image_size,
                project=str(root / "runs"), name="m_candidate", exist_ok=True, verbose=False,
                amp=True,
            )
        except Exception:
            error_log = root / "error_traceback.txt"
            error_log.write_text(traceback.format_exc(), encoding="utf-8")
            callback(f"訓練失敗，完整錯誤紀錄：{error_log}")
            raise
        candidate = Path(result.save_dir) / "weights" / "best.pt"
        if not candidate.is_file():
            raise RuntimeError("M 模型訓練完成但找不到 best.pt")
        metrics: dict[str, float] = {}
        results_csv = candidate.parent.parent / "results.csv"
        if results_csv.is_file():
            with results_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            if rows:
                best_row = max(
                    rows,
                    key=lambda row: float(row.get("metrics/mAP50-95(B)", 0) or 0),
                )
                for key in (
                    "metrics/precision(B)",
                    "metrics/recall(B)",
                    "metrics/mAP50(B)",
                    "metrics/mAP50-95(B)",
                ):
                    if best_row.get(key):
                        metrics[key] = float(best_row[key])
                metrics["best_epoch"] = float(best_row.get("epoch", 0) or 0)
        candidate_version = f"m_auto_{timestamp}"
        self.database.register_model_version(
            version=candidate_version,
            weight_path=candidate,
            weight_hash=file_hash(candidate),
            metrics=metrics,
            active=False,
        )
        callback(f"M 模型候選完成：{candidate}")
        return candidate

    @staticmethod
    def _load_training_model(path: Path):
        from ultralytics import YOLO

        if not path.is_file():
            raise FileNotFoundError(f"找不到 M 訓練起始權重：{path}")
        try:
            return YOLO(str(path))
        except Exception as exc:
            raise RuntimeError(
                f"無法載入 M 訓練起始權重：{path}（{path.stat().st_size:,} bytes）。"
                f"請確認權重完整且格式相容。原始錯誤：{exc}"
            ) from exc

    def _prepare_mixed_dataset(self, dataset_root: Path, new_items: list[tuple]) -> tuple[list[tuple], list[tuple]]:
        """複製原始 train/val，再按原始比例隨機分配新增資料。"""
        base_root = self.config.base_dataset_path
        base_counts = {}
        for split in ("train", "val", "test"):
            image_dir = base_root / "images" / split
            label_dir = base_root / "labels" / split
            out_image = dataset_root / "images" / split
            out_label = dataset_root / "labels" / split
            out_image.mkdir(parents=True, exist_ok=True)
            out_label.mkdir(parents=True, exist_ok=True)
            count = 0
            for image in image_dir.glob("*") if image_dir.is_dir() else []:
                label = label_dir / f"{image.stem}.txt"
                if not label.is_file():
                    continue
                shutil.copy2(image, out_image / f"base_{image.name}")
                shutil.copy2(label, out_label / f"base_{image.stem}.txt")
                count += 1
            base_counts[split] = count
        total_base = sum(base_counts.values())
        train_ratio = base_counts.get("train", 0) / total_base if total_base else 0.8
        shuffled = list(new_items)
        random.Random(20260905).shuffle(shuffled)
        if len(shuffled) > 1:
            split_at = max(1, min(len(shuffled) - 1, round(len(shuffled) * train_ratio)))
        else:
            split_at = len(shuffled)
        return shuffled[:split_at], shuffled[split_at:]

    @staticmethod
    def _dataset_image_counts(dataset_root: Path) -> dict[str, int]:
        return {
            split: sum(
                1 for path in (dataset_root / "images" / split).glob("*")
                if path.is_file()
            )
            for split in ("train", "val", "test")
        }

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
                "X 自動標註已完成並保留；S 模型暫不訓練：驗證資料必須按工單／批次分割，"
                "目前不足 2 個不同工單／批次。請建立第二個工單／批次後再訓練 S。"
            )
        random.Random(20260830).shuffle(group_names)
        validation_group_count = max(1, round(len(group_names) * 0.2))
        validation_groups = set(group_names[:validation_group_count])
        train_items = [item for item in items if item[2] not in validation_groups]
        validation_items = [item for item in items if item[2] in validation_groups]
        if not train_items or not validation_items:
            raise RuntimeError("資料無法依工單／批次切分為非空的 train 與 val")
        return train_items, validation_items
