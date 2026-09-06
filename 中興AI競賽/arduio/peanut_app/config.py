from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_PARENT = PROJECT_ROOT.parent
YOLO_ROOT = PROJECT_PARENT / "yolo"
VIDEO_ROOT = PROJECT_PARENT / "影片素材"
DATA_ROOT = PROJECT_ROOT / "production_data"


# 暫用：花生通過影像中央後，延遲多少秒才應送出撥片指令。
# Python 影片版只建立排程事件，不會連線或傳送指令給 Arduino。
# 後續必須以攝影中央至撥片距離、輸送速度與伺服反應時間取代。
ARDUINO_COMMAND_DELAY_SECONDS = 1.0


@dataclass(frozen=True)
class AppConfig:
    model_path: Path = YOLO_ROOT / "yolov26s_best.pt"
    x_model_path: Path = YOLO_ROOT / "yolov26x_best.pt"
    video_path: Path = VIDEO_ROOT / "video_001.mp4"
    data_root: Path = DATA_ROOT
    database_path: Path = DATA_ROOT / "peanut_production.sqlite3"
    image_root: Path = DATA_ROOT / "peanut_images"
    training_capture_root: Path = DATA_ROOT / "training_captures"
    training_root: Path = DATA_ROOT / "training"
    calibration_path: Path = DATA_ROOT / "weight_calibration.json"

    display_width: int = 960
    display_height: int = 540
    inference_image_size: int = 640
    # 低門檻用來保留低信心物件；正式七幀分類另使用 production_confidence。
    detection_confidence: float = 0.25
    production_confidence: float = 0.70
    tracker_name: str = "bytetrack.yaml"

    pre_center_frames: int = 3
    post_center_frames: int = 3

    # 目前是可調整的暫定值，正式門檻仍待使用者確認及實測。
    mold_min_hits: int = 3
    small_min_hits: int = 1
    normal_min_hits: int = 1

    lane_count: int = 4
    lane_boundary_half_width_ratio: float = 0.015
    crop_margin_ratio: float = 0.20
    stale_track_frames: int = 90
    recent_record_frames: int = 180

    arduino_command_delay_seconds: float = ARDUINO_COMMAND_DELAY_SECONDS
    model_version: str = "yolov26s_best"
    qwen_endpoint: str = "http://127.0.0.1:11434/api/generate"
    qwen_model: str = "qwen3.5:9b"
    qwen_timeout_seconds: int = 300
    qwen_num_predict: int = 512

    def ensure_directories(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.image_root.mkdir(parents=True, exist_ok=True)
        self.training_capture_root.mkdir(parents=True, exist_ok=True)
        self.training_root.mkdir(parents=True, exist_ok=True)
