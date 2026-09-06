from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class MachineState(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FAULT = "FAULT"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(slots=True)
class WorkOrderInput:
    vendor_code: str
    variety_code: str
    material_lot: str
    material_manufacture_date: str
    target_weight_g: float


@dataclass(slots=True)
class WorkOrder:
    id: int
    work_order_no: str
    supplier_name: str
    vendor_code: str
    variety_code: str
    material_lot: str
    material_manufacture_date: str
    target_weight_g: float
    production_date: str
    created_at: str
    status: str


@dataclass(slots=True)
class Anomaly:
    id: int
    work_order_id: int | None
    code: str
    severity: str
    message: str
    created_at: str
    cleared_at: str | None


@dataclass(slots=True)
class PeanutRecord:
    work_order_id: int
    sequence_no: int
    track_id: int
    detected_at: str
    classification: str
    confidence_center: float
    confidence_mean: float
    valid_frames: int
    class_counts: dict[str, int]
    area_mean_px2: float
    lane: int
    boundary_between: tuple[int, int] | None
    eject_lanes: tuple[int, ...]
    predicted_false_reject: bool
    model_version: str
    model_hash: str
    image_path: Path
    session_token: str
    center_frame_number: int
    center_time_seconds: float
    command_due_time_seconds: float | None
    mean_width_px: float
    speed_px_per_frame: float
    record_status: str = "COMPLETE"
    id: int | None = None


@dataclass(slots=True)
class ProductionStats:
    normal: int = 0
    mold: int = 0
    small: int = 0
    unknown: int = 0
    predicted_false_rejects: int = 0

    @property
    def classified_total(self) -> int:
        return self.normal + self.mold + self.small

    @property
    def total(self) -> int:
        return self.classified_total + self.unknown

    def percentage(self, classification: str) -> float:
        if self.classified_total == 0:
            return 0.0
        value = getattr(self, classification, 0)
        return value / self.classified_total * 100.0

    @property
    def false_reject_rate(self) -> float:
        if self.normal == 0:
            return 0.0
        return self.predicted_false_rejects / self.normal * 100.0


@dataclass(slots=True)
class WorkerEvent:
    kind: str
    payload: Any = field(default=None)
    emitted_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
