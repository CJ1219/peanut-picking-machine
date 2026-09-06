from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


BARCODE_PREFIX = "PEANUT-WO:"
TEST_WORK_ORDER_COUNT = 100


@dataclass(frozen=True, slots=True)
class TestWorkOrder:
    number: int
    vendor_code: str
    variety_code: str
    material_lot: str
    material_manufacture_date: str
    target_kg: float

    @property
    def barcode_value(self) -> str:
        return f"{BARCODE_PREFIX}{self.number:03d}"


def get_test_work_order(number: int) -> TestWorkOrder:
    if not 1 <= number <= TEST_WORK_ORDER_COUNT:
        raise ValueError(f"測試條碼編號必須介於 1 與 {TEST_WORK_ORDER_COUNT} 之間")
    manufacture_day = date(2026, 8, 1) + timedelta(days=(number - 1) % 31)
    return TestWorkOrder(
        number=number,
        vendor_code=f"{((number - 1) % 10) + 1:03d}",
        variety_code=f"{((number - 1) % 5) + 1:03d}",
        material_lot=f"TEST-202609-{number:03d}",
        material_manufacture_date=manufacture_day.isoformat(),
        target_kg=float(5 + ((number - 1) % 10)),
    )


def parse_test_work_order_number(value: str) -> int | None:
    text = value.strip()
    if text.upper().startswith(BARCODE_PREFIX):
        text = text[len(BARCODE_PREFIX):]
    if not text.isdigit():
        return None
    number = int(text)
    return number if 1 <= number <= TEST_WORK_ORDER_COUNT else None


def all_test_work_orders() -> list[TestWorkOrder]:
    return [get_test_work_order(number) for number in range(1, TEST_WORK_ORDER_COUNT + 1)]
