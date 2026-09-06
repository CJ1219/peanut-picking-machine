from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class WeightCalibration:
    """將影像面積換算成公克；公式未校正時明確回傳 None。"""

    enabled: bool = False
    formula: str = "linear"
    coefficient_a: float = 0.0
    coefficient_b: float = 0.0
    exponent: float = 1.0
    note: str = "待加入實測面積與重量校正資料"

    @classmethod
    def load(cls, path: Path) -> "WeightCalibration":
        path = Path(path)
        if not path.exists():
            calibration = cls()
            calibration.save(path)
            return calibration
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                enabled=bool(values.get("enabled", False)),
                formula=str(values.get("formula", "linear")),
                coefficient_a=float(values.get("coefficient_a", 0.0)),
                coefficient_b=float(values.get("coefficient_b", 0.0)),
                exponent=float(values.get("exponent", 1.0)),
                note=str(values.get("note", "")),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return cls(note="校正檔讀取失敗，重量估算已停用")

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "enabled": self.enabled,
                    "formula": self.formula,
                    "coefficient_a": self.coefficient_a,
                    "coefficient_b": self.coefficient_b,
                    "exponent": self.exponent,
                    "note": self.note,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def estimate_grams(self, area_px2: float) -> float | None:
        if not self.enabled or area_px2 <= 0:
            return None
        if self.formula == "power":
            value = self.coefficient_a * (area_px2 ** self.exponent) + self.coefficient_b
        else:
            value = self.coefficient_a * area_px2 + self.coefficient_b
        return max(0.0, float(value))
