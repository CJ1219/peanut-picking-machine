from __future__ import annotations

import cv2
import numpy as np


class BarcodeDecoder:
    """使用 OpenCV 支援 QR Code，並在目前 OpenCV 有功能時支援一般條碼。"""

    def __init__(self) -> None:
        self.qr_detector = cv2.QRCodeDetector()
        barcode_type = getattr(cv2, "barcode_BarcodeDetector", None)
        self.barcode_detector = barcode_type() if barcode_type is not None else None

    def decode(self, frame: np.ndarray) -> tuple[str, str] | None:
        qr_value, points, _ = self.qr_detector.detectAndDecode(frame)
        if qr_value:
            return qr_value.strip(), "QR"

        if self.barcode_detector is None:
            return None
        try:
            result = self.barcode_detector.detectAndDecode(frame)
            if not result:
                return None
            if len(result) == 4:
                ok, decoded_info, decoded_types, _ = result
                if not ok:
                    return None
            elif len(result) == 3:
                decoded_info, decoded_types, _ = result
            else:
                return None
            if isinstance(decoded_info, str):
                decoded_info = (decoded_info,)
            if isinstance(decoded_types, str):
                decoded_types = (decoded_types,)
            for index, value in enumerate(decoded_info):
                if value:
                    barcode_name = decoded_types[index] if index < len(decoded_types) else "BARCODE"
                    return str(value).strip(), str(barcode_name)
        except (cv2.error, TypeError, ValueError):
            return None
        return None
