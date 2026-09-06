import cv2
import numpy as np
import time
import threading
from pathlib import Path

# =========================================================
# 1. GoPro OpenGoPro multi_webcam
# =========================================================

from multi_webcam.webcam import Webcam


# =========================================================
# 2. 儲存資料夾
# =========================================================

SAVE_DIR = (
    Path.home()
    / "OneDrive"
    / "Desktop"
    / "gopro photos"
)

SAVE_DIR.mkdir(
    parents=True,
    exist_ok=True
)

print()
print("照片儲存位置：")
print(SAVE_DIR)


# =========================================================
# 3. GoPro HERO12 即時畫面
#    Open GoPro Webcam Stream
# =========================================================

GOPRO_SERIAL = "468"
GOPRO_PORT = 8554

STREAM_URL = (
    f"udp://0.0.0.0:{GOPRO_PORT}"
    "?overrun_nonfatal=1&fifo_size=50000000"
)

print()
print("正在啟動 GoPro HERO12 Webcam Stream...")

gopro = Webcam(GOPRO_SERIAL)

try:

    gopro.enable()

    gopro.start(
        port=GOPRO_PORT
    )

    print(
        f"GoPro Webcam Stream 已啟動：UDP {GOPRO_PORT}"
    )

except Exception as e:

    print(
        f"❌ 無法啟動 GoPro Webcam Stream：{e}"
    )

    raise SystemExit


time.sleep(1)


# =========================================================
# 4. OpenCV 開啟 UDP Stream
# =========================================================

cap = cv2.VideoCapture(
    STREAM_URL,
    cv2.CAP_FFMPEG
)

if not cap.isOpened():

    print(
        "❌ OpenCV 無法開啟 GoPro Webcam UDP Stream"
    )

    try:
        gopro.stop()
    except Exception:
        pass

    try:
        gopro.disable()
    except Exception:
        pass

    raise SystemExit


print()
print("✅ GoPro Webcam 即時畫面已開啟")
print(
    f"Stream URL：{STREAM_URL}"
)


# =========================================================
# 5. Latest Frame Reader
# =========================================================

class LatestFrameReader:

    def __init__(self, capture):

        self.capture = capture

        self.frame = None

        self.ret = False

        self.running = True

        self.lock = threading.Lock()

        self.thread = threading.Thread(
            target=self._reader,
            daemon=True
        )

        self.thread.start()


    def _reader(self):

        while self.running:

            ret, frame = self.capture.read()

            if not ret:

                time.sleep(0.001)

                continue

            with self.lock:

                self.ret = True

                self.frame = frame


    def read(self):

        with self.lock:

            if self.frame is None:

                return False, None

            return (
                self.ret,
                self.frame.copy()
            )


    def stop(self):

        self.running = False


# =========================================================
# 6. 透視校正設定
# =========================================================

# ---------------------------------------------------------
# GoPro 原始畫面的四個角
#
# 左上
# 右上
# 右下
# 左下
# ---------------------------------------------------------

POINTS = np.float32([

    [555, 40],       # 左上

    [1590, 99],      # 右上

    [1918, 992],     # 右下

    [375, 1034]      # 左下

])


# =========================================================
# 7. 校正後輸出的影像大小
# =========================================================

OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080


# =========================================================
# 8. 校正後四個角的位置
# =========================================================

DST_POINTS = np.float32([

    [0, 0],

    [OUTPUT_WIDTH, 0],

    [OUTPUT_WIDTH, OUTPUT_HEIGHT],

    [0, OUTPUT_HEIGHT]

])


# =========================================================
# 9. 計算透視變換矩陣
# =========================================================

matrix = cv2.getPerspectiveTransform(
    POINTS,
    DST_POINTS
)

print()
print("透視校正矩陣建立完成")

print(
    f"校正後解析度："
    f"{OUTPUT_WIDTH} x {OUTPUT_HEIGHT}"
)


# =========================================================
# 10. 啟動 Latest Frame Reader
# =========================================================

frame_reader = LatestFrameReader(cap)

print()
print("等待 GoPro 第一張即時影像...")


wait_start = time.time()

while True:

    ret, first_frame = frame_reader.read()

    if ret and first_frame is not None:

        print(
            f"✅ 收到 GoPro 影像："
            f"{first_frame.shape[1]} x "
            f"{first_frame.shape[0]}"
        )

        break


    if time.time() - wait_start > 10:

        print(
            "❌ 10 秒內沒有收到 GoPro Webcam 影像"
        )

        frame_reader.stop()

        cap.release()

        try:
            gopro.stop()
        except Exception:
            pass

        try:
            gopro.disable()
        except Exception:
            pass

        raise SystemExit


    time.sleep(0.05)


# =========================================================
# 11. 自動尋找下一個照片編號
# =========================================================

existing_files = list(
    SAVE_DIR.glob("peanut_*.jpg")
)

numbers = []

for file in existing_files:

    try:

        number = int(
            file.stem.split("_")[-1]
        )

        numbers.append(number)

    except ValueError:

        pass


if numbers:

    photo_count = max(numbers) + 1

else:

    photo_count = 1


print()
print(
    f"下一張照片編號：{photo_count}"
)


# =========================================================
# 12. 主迴圈
# =========================================================

print()
print("================================")
print("GoPro 資料集擷取模式")
print("================================")
print()
print("Space → 擷取照片")
print("Q     → 離開")
print()
print(
    f"照片會儲存到：{SAVE_DIR}"
)
print()


while True:

    # =====================================================
    # 12-1. 取得最新影像
    # =====================================================

    ret, frame = frame_reader.read()

    if not ret or frame is None:

        continue


    # =====================================================
    # 12-2. 透視校正
    # =====================================================

    corrected = cv2.warpPerspective(

        frame,

        matrix,

        (
            OUTPUT_WIDTH,
            OUTPUT_HEIGHT
        )

    )


    # =====================================================
    # 12-3. 顯示操作提示
    # =====================================================

    cv2.putText(

        corrected,

        "SPACE: Capture",

        (30, 50),

        cv2.FONT_HERSHEY_SIMPLEX,

        1.0,

        (0, 255, 0),

        2

    )


    cv2.putText(

        corrected,

        "Q: Quit",

        (30, 90),

        cv2.FONT_HERSHEY_SIMPLEX,

        1.0,

        (0, 255, 0),

        2

    )


    cv2.putText(

        corrected,

        f"Next: peanut_{photo_count:04d}.jpg",

        (30, 130),

        cv2.FONT_HERSHEY_SIMPLEX,

        0.8,

        (0, 255, 255),

        2

    )


    # =====================================================
    # 12-4. 顯示畫面
    # =====================================================

    cv2.imshow(

        "GoPro Dataset Capture",

        corrected

    )


    # =====================================================
    # 12-5. 鍵盤
    # =====================================================

    key = cv2.waitKey(1) & 0xFF


    # -----------------------------------------------------
    # Q：離開
    # -----------------------------------------------------

    if key == ord("q"):

        break


    # -----------------------------------------------------
    # Space：擷取照片
    # -----------------------------------------------------

    if key == ord(" "):

        filename = (
            SAVE_DIR
            / f"peanut_{photo_count:04d}.jpg"
        )


        success = cv2.imwrite(

            str(filename),

            corrected

        )


        if success:

            print(
                f"✅ 已儲存：{filename.name}"
            )

            photo_count += 1

        else:

            print(
                f"❌ 儲存失敗：{filename}"
            )


# =========================================================
# 13. 清理
# =========================================================

print()
print("正在關閉系統...")


frame_reader.stop()


try:

    cap.release()

except Exception:

    pass


try:

    cv2.destroyAllWindows()

except Exception:

    pass


try:

    gopro.stop()

    print(
        "GoPro Webcam 已停止"
    )

except Exception:

    pass


try:

    gopro.disable()

    print(
        "GoPro Webcam 已關閉"
    )

except Exception:

    pass


print()
print("================================")
print("資料集擷取結束")
print(
    f"照片儲存位置：{SAVE_DIR}"
)
print("================================")