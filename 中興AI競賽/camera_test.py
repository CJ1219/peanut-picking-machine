import cv2
import time
import threading
import atexit

from multi_webcam.webcam import Webcam


# =========================================================
# GoPro 設定
# =========================================================

GOPRO_SERIAL = "468"
GOPRO_PORT = 8554

# 降低 UDP 緩衝，避免畫面累積太多舊幀
STREAM_URL = (
    f"udp://0.0.0.0:{GOPRO_PORT}"
    "?overrun_nonfatal=1&fifo_size=1000000"
)

WINDOW_NAME = "GoPro Camera"


# =========================================================
# 永遠只保留最新一幀
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

            return self.ret, self.frame.copy()

    def stop(self):
        self.running = False


# =========================================================
# 啟動 GoPro Webcam
# =========================================================

print("正在啟動 GoPro Webcam...")

gopro = Webcam(GOPRO_SERIAL)

try:
    gopro.enable()
    gopro.start(port=GOPRO_PORT)

except Exception as e:
    print(f"GoPro 啟動失敗：{e}")
    raise SystemExit

time.sleep(1)


# =========================================================
# OpenCV 開啟 UDP 串流
# =========================================================

cap = cv2.VideoCapture(
    STREAM_URL,
    cv2.CAP_FFMPEG
)

# 某些 OpenCV / FFmpeg 環境可能不支援，
# 但設定為 1 有機會進一步降低緩衝延遲。
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not cap.isOpened():

    print("OpenCV 無法開啟 GoPro UDP Stream")

    try:
        gopro.stop()
    except Exception:
        pass

    try:
        gopro.disable()
    except Exception:
        pass

    raise SystemExit


# =========================================================
# 最新影像讀取執行緒
# =========================================================

frame_reader = LatestFrameReader(cap)

_cleanup_done = False


def cleanup():

    global _cleanup_done

    if _cleanup_done:
        return

    _cleanup_done = True

    print("\n正在關閉 GoPro...")

    try:
        frame_reader.stop()
    except Exception:
        pass

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
    except Exception:
        pass

    try:
        gopro.disable()
    except Exception:
        pass

    print("GoPro 已關閉")


atexit.register(cleanup)


# =========================================================
# 固定顯示視窗大小
# =========================================================

cv2.namedWindow(
    WINDOW_NAME,
    cv2.WINDOW_NORMAL
)

cv2.resizeWindow(
    WINDOW_NAME,
    1280,
    720
)


# =========================================================
# 等待第一張影像
# =========================================================

print("等待 GoPro 第一張影像...")

start_time = time.time()

while True:

    ret, frame = frame_reader.read()

    if ret and frame is not None:

        print(
            f"收到 GoPro 影像："
            f"{frame.shape[1]} x {frame.shape[0]}"
        )

        break

    if time.time() - start_time > 10:

        print("10 秒內沒有收到 GoPro 影像")
        cleanup()
        raise SystemExit

    time.sleep(0.01)


print("GoPro 即時畫面已開啟")
print("按 Q 離開")


# =========================================================
# 主迴圈：只顯示鏡頭
# =========================================================

while True:

    ret, frame = frame_reader.read()

    if not ret or frame is None:
        time.sleep(0.001)
        continue

    cv2.imshow(
        WINDOW_NAME,
        frame
    )

    key = cv2.waitKey(1) & 0xFF

    if key == ord("q"):
        break


cleanup()
