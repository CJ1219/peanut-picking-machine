from __future__ import annotations

import csv
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFont

from peanut_app.test_work_orders import all_test_work_orders


OUTPUT_DIR = Path(__file__).resolve().parent / "production_data" / "test_barcodes"


def generate() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    encoder = cv2.QRCodeEncoder_create()
    rows = all_test_work_orders()
    label_font = ImageFont.load_default(size=22)
    detail_font = ImageFont.load_default(size=14)
    cards: list[Image.Image] = []
    with (OUTPUT_DIR / "work_orders.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("barcode_number", "barcode_value", "vendor_code", "variety_code",
                         "material_lot", "manufacture_date", "target_kg"))
        for row in rows:
            qr = encoder.encode(row.barcode_value)
            qr = cv2.resize(qr, (360, 360), interpolation=cv2.INTER_NEAREST)
            card = Image.new("RGB", (440, 500), "white")
            card.paste(Image.fromarray(qr).convert("RGB"), (40, 30))
            draw = ImageDraw.Draw(card)
            draw.text((20, 400), f"#{row.number:03d}  {row.barcode_value}", fill="black", font=label_font)
            draw.text((20, 438),
                      f"V{row.vendor_code} / P{row.variety_code} / {row.target_kg:g} kg",
                      fill="black", font=detail_font)
            draw.text((20, 462), row.material_lot, fill="black", font=detail_font)
            card.save(OUTPUT_DIR / f"barcode_{row.number:03d}.png")
            cards.append(card)
            writer.writerow((row.number, row.barcode_value, row.vendor_code, row.variety_code,
                             row.material_lot, row.material_manufacture_date, row.target_kg))

    pages: list[Image.Image] = []
    for offset in range(0, len(cards), 12):
        page = Image.new("RGB", (1760, 1500), "white")
        for position, card in enumerate(cards[offset:offset + 12]):
            x = (position % 4) * 440
            y = (position // 4) * 500
            page.paste(card, (x, y))
        pages.append(page)
    pages[0].save(
        OUTPUT_DIR / "100_test_barcodes_print.pdf",
        save_all=True,
        append_images=pages[1:],
        resolution=150,
    )
    return OUTPUT_DIR


if __name__ == "__main__":
    print(generate())
