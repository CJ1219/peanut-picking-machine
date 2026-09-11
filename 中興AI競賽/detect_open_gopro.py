"""Completed GoPro sorting engine, shared by standalone mode and the production GUI.
Importing this module never opens hardware. Call run_detection explicitly.
"""
from pathlib import Path
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
# Preserve the working script's model when present; support moving this project.
SOURCE_MODEL = Path(r"D:\中興AI競賽\runs\detect\train-13\weights\best.pt")
DEFAULT_MODEL = SOURCE_MODEL if SOURCE_MODEL.is_file() else ROOT / "中興AI競賽/runs/detect/train-13/weights/best.pt"
DEFAULT_ARDUINO_PORT = "COM7"
DEFAULT_GOPRO_SERIAL = "468"
# GoPro Webcam 最高支援 1080p；Linear 可減少畫面邊緣變形，方便 AI 辨識。
GOPRO_WEBCAM_RESOLUTION = 12
GOPRO_WEBCAM_FOV = 4
SERVO_Y_OFFSET = 30
SERVO_OVERLAP_HALF_WIDTH = 40
SERVO_BOUNDARIES = tuple(y - SERVO_Y_OFFSET for y in (360, 598, 811))
LANE_RANGES = (
    (105 - SERVO_Y_OFFSET, SERVO_BOUNDARIES[0] + SERVO_OVERLAP_HALF_WIDTH),
    (SERVO_BOUNDARIES[0] - SERVO_OVERLAP_HALF_WIDTH,
     SERVO_BOUNDARIES[1] + SERVO_OVERLAP_HALF_WIDTH),
    (SERVO_BOUNDARIES[1] - SERVO_OVERLAP_HALF_WIDTH,
     SERVO_BOUNDARIES[2] + SERVO_OVERLAP_HALF_WIDTH),
    (SERVO_BOUNDARIES[2] - SERVO_OVERLAP_HALF_WIDTH, 953 - SERVO_Y_OFFSET),
)
DEFAULT_TRACKER = ROOT / "中興AI競賽/peanut_bytetrack.yaml"


def resolve_ng_priority_pins(normal_trigger_pins, active_objects):
    """Return lanes where a triggering normal overlaps a current NG."""
    active_ng_pins = set()
    for classification, cy in active_objects:
        if classification not in {"mold", "small"}:
            continue
        for pin, (y_min, y_max) in enumerate(LANE_RANGES, start=2):
            if y_min <= cy <= y_max:
                active_ng_pins.add(pin)
    return set(normal_trigger_pins) & active_ng_pins


def run_detection(*, model_path=DEFAULT_MODEL, tracker_path=DEFAULT_TRACKER,
                  arduino_port=DEFAULT_ARDUINO_PORT, gopro_serial=DEFAULT_GOPRO_SERIAL, gopro_port=8554,
                  stop_event=None, pause_event=None, on_frame=None, on_started=None,
                  on_arduino_ready=None, on_arduino_event=None):
    stop_event = stop_event if stop_event is not None else threading.Event()
    pause_event = pause_event if pause_event is not None else threading.Event()
    if not Path(model_path).is_file():
        raise FileNotFoundError(f"找不到模型：{model_path}")
    if not Path(tracker_path).is_file():
        raise FileNotFoundError(f"找不到追蹤設定：{tracker_path}")
    arduino = gopro = cap = frame_reader = None
    serial_reader_thread = None
    serial_reader_stop = threading.Event()
    session_start = time.monotonic()
    try:
        from ultralytics import YOLO
        import cv2
        import numpy as np
        import serial
        from collections import deque

        # GoPro OpenGoPro multi_webcam package
        from multi_webcam.webcam import Webcam


        # =========================================================
        # 1. Arduino Serial 設定
        # =========================================================

        ARDUINO_PORT = arduino_port
        ARDUINO_BAUDRATE = 115200

        try:
            arduino = serial.Serial(
                ARDUINO_PORT,
                ARDUINO_BAUDRATE,
                timeout=1, write_timeout=2
            )

            # 等待 Arduino 重置完成
            time.sleep(2)

            print(f"Arduino 已連接：{ARDUINO_PORT}")
            print(f"Baud Rate：{ARDUINO_BAUDRATE}")

        except Exception as e:
            print(f"無法連接 Arduino：{e}")
            raise RuntimeError(f"Arduino 連線失敗（{ARDUINO_PORT}）：{e}") from e

        serial_lock = threading.Lock()

        def send_arduino_command(command):
            """Thread-safe entry point shared with the GUI controls."""
            payload = f"{command.strip()}\n".encode("utf-8")
            with serial_lock:
                arduino.write(payload)
            print(f"Arduino 指令 → {command.strip()}")


        # =========================================================
        # 1-1. Servo 角度設定
        # =========================================================

        # Normal 花生通過時
        SERVO_NORMAL_ANGLE = 135

        # Mold / Small 篩除角度
        SERVO_REJECT_ANGLE = 45


        # =========================================================
        # 1-3. 傳送 Servo 指令
        # =========================================================

        def send_servo_command(servo_name, angle):
            if stop_event.is_set():
                return

            command = f"{servo_name},{angle}\n"

            try:
                send_arduino_command(command)

            except Exception as e:

                raise RuntimeError(f"Arduino 傳送失敗：{e}") from e


        # =========================================================
        # 1-4. Servo Pin 對應名稱
        # =========================================================

        servo_names = {

            2: "servo1",
            3: "servo2",
            4: "servo3",
            5: "servo4"

        }


        # =========================================================
        # 1-5. 啟動時全部 Servo 回到 135°
        # =========================================================

        print()
        print("初始化 Servo...")

        for pin, servo_name in servo_names.items():

            send_servo_command(
                servo_name,
                SERVO_NORMAL_ANGLE
            )

        print("所有 Servo → 135°")
        print()

        if on_arduino_ready:
            on_arduino_ready(send_arduino_command)

        def read_arduino_events():
            while not serial_reader_stop.is_set():
                try:
                    raw_line = arduino.readline()
                except Exception as exc:
                    if on_arduino_event and not serial_reader_stop.is_set():
                        on_arduino_event(f"PY:ERROR:{exc}")
                    stop_event.set()
                    return
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line.startswith("PY:") and on_arduino_event:
                    on_arduino_event(line)

        serial_reader_thread = threading.Thread(
            target=read_arduino_events, name="arduino-status-reader", daemon=True
        )
        serial_reader_thread.start()


        # =========================================================
        # 2. 載入 YOLO 模型
        # =========================================================

        model = YOLO(
            str(model_path)
        )


        # =========================================================
        # 3. GoPro HERO12 即時畫面（Open GoPro Webcam Stream）
        # =========================================================

        GOPRO_SERIAL = gopro_serial
        GOPRO_PORT = gopro_port

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
                port=GOPRO_PORT,
                resolution=GOPRO_WEBCAM_RESOLUTION,
                fov=GOPRO_WEBCAM_FOV,
            )
            print(f"GoPro Webcam Stream 已啟動：UDP {GOPRO_PORT}")
        except Exception as e:
            print(f"❌ 無法啟動 GoPro Webcam Stream：{e}")
            raise RuntimeError("GoPro 串流啟動失敗")

        time.sleep(1)

        cap = cv2.VideoCapture(
            STREAM_URL, cv2.CAP_FFMPEG,
            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000]
        )

        if not cap.isOpened():
            raise RuntimeError("OpenCV 無法開啟 GoPro Webcam UDP Stream")

        print("✅ GoPro Webcam 即時畫面已開啟")
        print(f"Stream URL：{STREAM_URL}")


        # =========================================================
        # 3-0. Latest Frame Reader
        # =========================================================

        class LatestFrameReader:

            def __init__(self, capture):
                self.capture = capture
                self.frame = None
                self.ret = False
                self.running = True
                self.sequence = 0
                self.consumed = 0
                self.lock = threading.Lock()
                self.thread = threading.Thread(target=self._reader, daemon=True)
                self.thread.start()

            def _reader(self):
                while self.running:
                    ret, frame = self.capture.read()
                    if not ret:
                        time.sleep(0.001)
                        continue
                    with self.lock:
                        self.sequence += 1
                        self.ret = True
                        self.frame = frame

            def read(self):
                with self.lock:
                    if self.frame is None or self.sequence == self.consumed:
                        return False, None
                    self.consumed = self.sequence
                    return self.ret, self.frame.copy()

            def stop(self):
                self.running = False

        # =========================================================
        # 3-1. 透視校正設定
        # =========================================================

        # ---------------------------------------------------------
        # GoPro 原始畫面的四個角
        #
        # 順序一定要：
        #
        # 左上
        # 右上
        # 右下
        # 左下
        # ---------------------------------------------------------

        POINTS = np.float32([

            [550, 40],       # 左上

            [1645, 99],      # 右上

            [1918, 992],     # 右下

            [342, 1034]      # 左下

        ])


        # ---------------------------------------------------------
        # 校正後輸出的影像大小
        # ---------------------------------------------------------

        OUTPUT_WIDTH = 1920
        OUTPUT_HEIGHT = 1080


        # ---------------------------------------------------------
        # 校正後四個角的位置
        # ---------------------------------------------------------

        DST_POINTS = np.float32([

            [0, 0],                           # 左上

            [OUTPUT_WIDTH - 1, 0],            # 右上

            [OUTPUT_WIDTH - 1, OUTPUT_HEIGHT - 1],    # 右下

            [0, OUTPUT_HEIGHT - 1]            # 左下

        ])


        # ---------------------------------------------------------
        # 計算透視變換矩陣（POINTS 是在 1920 x 1080 原始畫面量測）
        # ---------------------------------------------------------

        POINTS_REFERENCE_SIZE = (1920, 1080)


        def build_perspective_matrix(frame_shape):
            frame_height, frame_width = frame_shape[:2]
            reference_width, reference_height = POINTS_REFERENCE_SIZE
            # 不同長寬比可能代表 GoPro 改變裁切範圍，不能只靠縮放沿用四角。
            if abs(frame_width / frame_height - reference_width / reference_height) > 0.01:
                raise ValueError("GoPro 串流長寬比已變更，請重新量測 POINTS 與 POINTS_REFERENCE_SIZE")
            scale = np.float32([
                frame_width / reference_width,
                frame_height / reference_height,
            ])
            return cv2.getPerspectiveTransform(POINTS * scale, DST_POINTS)


        print("透視校正矩陣將依實際串流解析度建立")


        # =========================================================
        # 4. 取得影片資訊
        # =========================================================

        fps = cap.get(
            cv2.CAP_PROP_FPS
        )

        if fps <= 0:

            fps = 30


        width = OUTPUT_WIDTH
        height = OUTPUT_HEIGHT


        print(
            f"影片 FPS：{fps:.2f}"
        )

        print(
            f"校正後解析度：{width} x {height}"
        )


        # =========================================================
        # 5. 判定線
        # =========================================================

        # 花生由右往左移動
        #
        # Center X <= 400
        # 就鎖定最終分類

        DECISION_LINE_X = 400

        print(
            f"判定線位置：X = {DECISION_LINE_X}"
        )


        # =========================================================
        # 5-1. Trigger Line
        # =========================================================

        # 花生由右往左移動
        #
        # Bounding Box 左邊界 X <= 5
        # 就啟動對應撥桿

        TRIGGER_LINE_X = 5

        print(
            f"Trigger Line 位置：X = {TRIGGER_LINE_X}"
        )


        # =========================================================
        # 5-2. 四個撥桿區域
        # =========================================================

        # Shared ranges keep the GUI, control logic and overlay consistent.
        SERVO1_Y_MIN, SERVO1_Y_MAX = LANE_RANGES[0]
        SERVO1_PIN = 2

        SERVO2_Y_MIN, SERVO2_Y_MAX = LANE_RANGES[1]
        SERVO2_PIN = 3

        SERVO3_Y_MIN, SERVO3_Y_MAX = LANE_RANGES[2]
        SERVO3_PIN = 4

        SERVO4_Y_MIN, SERVO4_Y_MAX = LANE_RANGES[3]
        SERVO4_PIN = 5


        # =========================================================
        # 6. Mold 判定設定
        # =========================================================

        # 最近 10 幀
        MOLD_WINDOW = 10

        # 最近 10 幀中
        # 出現 5 次 mold
        # 就判定 MOLD

        MOLD_THRESHOLD = 5

        print(
            f"Mold 判定：最近 {MOLD_WINDOW} 幀中，"
            f"累積 {MOLD_THRESHOLD} 次 mold → MOLD"
        )


        # =========================================================
        # 6-1. Lost Track 軌跡預測設定
        # =========================================================

        # Bounding Box 在 Trigger Line 前短暫消失時，
        # 最多持續預測幾個 frame。
        MAX_LOST_FRAMES = 15

        # 用最近幾個 x1 位置估計花生向左移動速度。
        POSITION_HISTORY_LENGTH = 5

        # 每個 Track ID 最近的 x1 歷史
        position_history = {}

        # 每個 Track ID 連續遺失的 frame 數
        lost_frames = {}

        # 每個 Track ID 最後一次實際偵測到的 bbox
        last_bbox = {}

        # 每個 Track ID 最後一次實際偵測到的 Y 中心
        last_cy = {}

        # 本 frame 實際被 YOLO / ByteTrack 看見的 Track ID
        seen_this_frame = set()


        # =========================================================
        # 7. Tracking 資料
        # =========================================================

        # 每個 ID 最近 10 幀的 mold 紀錄
        mold_history = {}

        # 每個 ID 的目前分類
        final_class = {}

        # 每個 ID 是否已經通過判定線
        passed_line = {}

        # 每個 ID 通過判定線後的最終分類
        locked_class = {}

        # 每個 ID 是否已經觸發撥桿
        triggered = {}


        # =========================================================
        # 7-1. 啟動最新影像讀取執行緒
        # =========================================================

        frame_reader = LatestFrameReader(cap)

        print("等待 GoPro 第一張即時影像...")
        wait_start = time.time()

        while True:
            if stop_event.is_set():
                return
            ret, first_frame = frame_reader.read()
            if ret and first_frame is not None:
                print(
                    f"✅ 收到 GoPro 影像："
                    f"{first_frame.shape[1]} x {first_frame.shape[0]}"
                )
                break
            if time.time() - wait_start > 10:
                raise RuntimeError("10 秒內沒有收到 GoPro Webcam 影像")
            time.sleep(0.05)


        # =========================================================
        # 7-2. 系統清理函式
        # =========================================================

        # =========================================================
        # 7-3. 影像銳化：強化花生表面黑點、霉斑與細部紋理
        # =========================================================

        def sharpen_image(frame):
            # 輕微銳化，避免過度強化 normal 花生的正常紋理
            kernel = np.array([
                [0, -1, 0],
                [-1, 5, -1],
                [0, -1, 0]
            ], dtype=np.float32)

            return cv2.filter2D(
                frame,
                -1,
                kernel
            )


        # 是否另外顯示銳化後的畫面，方便 A/B 比較
        # =========================================================
        # 8. 主迴圈
        # =========================================================

        matrix = build_perspective_matrix(first_frame.shape)
        matrix_frame_shape = first_frame.shape[:2]
        show_geometry_comparison = False
        frame_number = 0
        last_frame_at = time.monotonic()
        # Start the conveyor only after the model, GoPro and first frame are ready.
        send_arduino_command("START")
        if on_started:
            on_started({"fps": fps, "width": width, "height": height})
        while not stop_event.is_set():
            if pause_event.is_set():
                stop_event.wait(0.05)
                last_frame_at = time.monotonic()
                continue

            # =====================================================
            # 8-1. 讀取 GoPro 原始畫面
            # =====================================================

            # 永遠取得 GoPro 最新一張影像，避免 YOLO 處理造成 frame 排隊
            ret, frame = frame_reader.read()

            if not ret or frame is None:

                if time.monotonic() - last_frame_at > 10:
                    raise RuntimeError("GoPro 超過 10 秒沒有新影像")

                time.sleep(0.001)

                continue

            last_frame_at = time.monotonic()
            frame_number += 1
            if frame.shape[:2] != matrix_frame_shape:
                matrix = build_perspective_matrix(frame.shape)
                matrix_frame_shape = frame.shape[:2]

            corrected = cv2.warpPerspective(

                frame,

                matrix,

                (
                    OUTPUT_WIDTH,
                    OUTPUT_HEIGHT
                )

            )


            # =====================================================
            # 8-2-1. 影像銳化
            #
            # YOLO 使用 sharpened 進行辨識；
            # 判定線、Bounding Box 與 Servo 區域仍畫在 corrected，
            # 因為兩者解析度與座標完全相同。
            # =====================================================

            sharpened = sharpen_image(corrected)


            
            # 顯示畫面也使用 sharpen 後影像
            display_frame = sharpened.copy()
        # =====================================================
            # 8-3. YOLO Tracking
            # =====================================================

            results = model.track(

                sharpened,

                imgsz=1024,

                conf=0.5,

                persist=True,

                tracker=str(tracker_path),

                verbose=False

            )


            # =====================================================
            # 9. 畫判定線
            #
            # 注意：
            # 這裡改成畫在 corrected
            # =====================================================

            cv2.line(

                display_frame,

                (DECISION_LINE_X, 0),

                (DECISION_LINE_X, height),

                (255, 0, 255),

                3

            )


            cv2.putText(

                display_frame,

                "DECISION LINE",

                (DECISION_LINE_X + 10, 60),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.7,

                (255, 0, 255),

                2

            )


            # =====================================================
            # 9-1. Trigger Line
            # =====================================================

            cv2.line(

                display_frame,

                (TRIGGER_LINE_X, 0),

                (TRIGGER_LINE_X, height),

                (0, 165, 255),

                3

            )


            cv2.putText(

                display_frame,

                "TRIGGER LINE",

                (TRIGGER_LINE_X + 10, 60),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.7,

                (0, 165, 255),

                2

            )


            # =====================================================
            # 9-2. 四個撥桿區域
            # =====================================================

            # Highlight adjacent servo overlap on the display image only.
            servo_regions = (
                (SERVO1_Y_MIN, SERVO1_Y_MAX),
                (SERVO2_Y_MIN, SERVO2_Y_MAX),
                (SERVO3_Y_MIN, SERVO3_Y_MAX),
                (SERVO4_Y_MIN, SERVO4_Y_MAX),
            )
            for index, (first, second) in enumerate(
                zip(servo_regions, servo_regions[1:]), start=1
            ):
                top = max(0, first[0], second[0])
                bottom = min(display_frame.shape[0] - 1, first[1], second[1])
                if top > bottom:
                    continue
                band = display_frame[top:bottom + 1, :]
                tint = np.full_like(band, (0, 165, 255))
                cv2.addWeighted(band, 0.75, tint, 0.25, 0, dst=band)
                for edge_y in (top, bottom):
                    cv2.line(display_frame, (0, edge_y),
                             (display_frame.shape[1] - 1, edge_y), (0, 165, 255), 2)
                cv2.putText(display_frame, f"Overlap {index}-{index + 1}",
                            (10, max(18, (top + bottom) // 2 + 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)

            # Servo1

            cv2.line(

                display_frame,

                (0, SERVO1_Y_MIN),

                (width, SERVO1_Y_MIN),

                (0, 0, 0),

                2

            )


            cv2.line(

                display_frame,

                (0, SERVO_BOUNDARIES[0]),

                (width, SERVO_BOUNDARIES[0]),

                (0, 0, 0),

                2

            )


            # Servo2

            cv2.line(

                display_frame,

                (0, SERVO_BOUNDARIES[1]),

                (width, SERVO_BOUNDARIES[1]),

                (0, 0, 0),

                2

            )


            # Servo3

            cv2.line(

                display_frame,

                (0, SERVO_BOUNDARIES[2]),

                (width, SERVO_BOUNDARIES[2]),

                (0, 0, 0),

                2

            )


            # Servo4

            cv2.line(

                display_frame,

                (0, SERVO4_Y_MAX),

                (width, SERVO4_Y_MAX),

                (0, 0, 0),

                2

            )


            # =====================================================
            # 9-3. 區域名稱
            # =====================================================

            cv2.putText(

                display_frame,

                "Servo1 (PIN 2)",

                (100, 250),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.8,

                (0, 0, 0),

                2

            )


            cv2.putText(

                display_frame,

                "Servo2 (PIN 3)",

                (100, 480),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.8,

                (0, 0, 0),

                2

            )


            cv2.putText(

                display_frame,

                "Servo3 (PIN 4)",

                (100, 700),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.8,

                (0, 0, 0),

                2

            )


            cv2.putText(

                display_frame,

                "Servo4 (PIN 5)",

                (100, 890),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.8,

                (0, 0, 0),

                2

            )


            # =====================================================
            # 10. 處理每個 Bounding Box
            # =====================================================

            # 每一幀重新記錄實際被 YOLO / ByteTrack 看見的 ID
            seen_this_frame.clear()
            new_normal_trigger_pins = set()

            for result in results:

                for box in result.boxes:

                    # =================================================
                    # Class
                    # =================================================

                    cls = int(
                        box.cls[0]
                    )

                    name = model.names[cls]


                    # =================================================
                    # Confidence
                    # =================================================

                    conf = float(
                        box.conf[0]
                    )


                    # =================================================
                    # Tracking ID
                    # =================================================

                    if box.id is not None:

                        track_id = int(
                            box.id[0]
                        )

                    else:

                        track_id = -1


                    if track_id == -1:

                        continue


                    # =================================================
                    # Bounding Box
                    # =================================================

                    x1, y1, x2, y2 = map(

                        int,

                        box.xyxy[0]

                    )


                    # =================================================
                    # Center
                    # =================================================

                    cx = int(
                        (x1 + x2) / 2
                    )

                    cy = int(
                        (y1 + y2) / 2
                    )


                    # =================================================
                    # 更新 Lost Track 軌跡資料
                    # =================================================

                    # 這個 ID 本幀仍有被實際偵測到
                    seen_this_frame.add(track_id)

                    # 重新看到後，遺失幀數歸零
                    lost_frames[track_id] = 0

                    # 注意：position_history 會在新 ID 初始化後才存在，
                    # 因此此處先暫存 bbox，初始化後再 append。
                    last_bbox[track_id] = (
                        x1,
                        y1,
                        x2,
                        y2
                    )

                    last_cy[track_id] = cy


                    # =================================================
                    # 初始化新的 ID
                    # =================================================

                    if track_id not in mold_history:

                        mold_history[track_id] = deque(
                            maxlen=MOLD_WINDOW
                        )

                        final_class[track_id] = "normal"

                        passed_line[track_id] = False

                        locked_class[track_id] = None

                        triggered[track_id] = False

                        position_history[track_id] = deque(
                            maxlen=POSITION_HISTORY_LENGTH
                        )

                        lost_frames[track_id] = 0


                    # 記錄目前 bbox 左邊界，用於後續速度預測
                    position_history[track_id].append(x1)


                    # =================================================
                    # SMALL 立即永久鎖定
                    #
                    # 只要同一個 Tracking ID 任一幀被偵測為 small，
                    # 就立即鎖定為 small。
                    # 後續即使 YOLO 判成 normal 或 mold，
                    # 此 ID 的最終分類都不再更改。
                    # =================================================

                    if name == "small":

                        if locked_class[track_id] != "small":

                            final_class[track_id] = "small"

                            locked_class[track_id] = "small"

                            print(
                                f"ID {track_id} 偵測到 SMALL "
                                f"→ 立即永久鎖定 SMALL"
                            )


                    # =================================================
                    # 如果還沒通過判定線
                    # 且尚未被永久鎖定為 SMALL
                    # 才更新 normal / mold 分類
                    # =================================================

                    if (

                        not passed_line[track_id]

                        and

                        locked_class[track_id] != "small"

                    ):

                        # =============================================
                        # 記錄 Mold
                        # =============================================

                        if name == "mold":

                            mold_history[track_id].append(1)

                        else:

                            mold_history[track_id].append(0)


                        # =============================================
                        # Mold Count
                        # =============================================

                        mold_count = sum(
                            mold_history[track_id]
                        )


                        # =============================================
                        # MOLD
                        # =============================================

                        if (

                            final_class[track_id] == "normal"

                            and

                            mold_count >= MOLD_THRESHOLD

                        ):

                            final_class[track_id] = "mold"


                    else:

                        mold_count = sum(
                            mold_history[track_id]
                        )


                    # =================================================
                    # 11. 判斷是否通過判定線
                    # =================================================

                    if (

                        not passed_line[track_id]

                        and

                        cx <= DECISION_LINE_X

                    ):

                        passed_line[track_id] = True

                        # 若之前已經因偵測到 SMALL 而永久鎖定，
                        # 通過判定線時不可再覆蓋。
                        if locked_class[track_id] != "small":

                            locked_class[track_id] = (
                                final_class[track_id]
                            )


                        print(

                            f"ID {track_id} 通過判定線 → "

                            f"{locked_class[track_id].upper()}"

                        )


                    # =================================================
                    # 12. Trigger Line
                    # =================================================

                    if (

                        passed_line[track_id]

                        and

                        not triggered[track_id]

                        and

                        x1 <= TRIGGER_LINE_X

                    ):

                        triggered[track_id] = True

                        trigger_class = locked_class[track_id]


                        print()
                        print("================================")

                        print(
                            f"ID {track_id} 到達 TRIGGER LINE"
                        )

                        print(
                            f"最終分類：{trigger_class.upper()}"
                        )

                        print(
                            f"Center：({cx}, {cy})"
                        )


                        # =================================================
                        # NORMAL
                        # =================================================

                        if trigger_class == "normal":

                            # Do not send 135 here. If an NG is present in the same
                            # lane later in this frame, NG must win and stay rejected.
                            for pin, (y_min, y_max) in enumerate(LANE_RANGES, start=2):
                                if y_min <= cy <= y_max:
                                    new_normal_trigger_pins.add(pin)

                            print(

                                f"ID {track_id} → "

                                f"NORMAL → 不動作"

                            )

                            print(

                                f"Servo 維持 "

                                f"{SERVO_NORMAL_ANGLE}°"

                            )


                        # =================================================
                        # MOLD / SMALL
                        # =================================================

                        elif (

                            trigger_class == "mold"

                            or

                            trigger_class == "small"

                        ):

                            servo_pins = []


                            # =============================================
                            # Servo1
                            # =============================================

                            if (

                                SERVO1_Y_MIN

                                <= cy

                                <= SERVO1_Y_MAX

                            ):

                                servo_pins.append(
                                    SERVO1_PIN
                                )


                            # =============================================
                            # Servo2
                            # =============================================

                            if (

                                SERVO2_Y_MIN

                                <= cy

                                <= SERVO2_Y_MAX

                            ):

                                servo_pins.append(
                                    SERVO2_PIN
                                )


                            # =============================================
                            # Servo3
                            # =============================================

                            if (

                                SERVO3_Y_MIN

                                <= cy

                                <= SERVO3_Y_MAX

                            ):

                                servo_pins.append(
                                    SERVO3_PIN
                                )


                            # =============================================
                            # Servo4
                            # =============================================

                            if (

                                SERVO4_Y_MIN

                                <= cy

                                <= SERVO4_Y_MAX

                            ):

                                servo_pins.append(
                                    SERVO4_PIN
                                )


                            # =============================================
                            # 啟動 Servo
                            # =============================================

                            if servo_pins:

                                for servo_pin in servo_pins:

                                    servo_name = (
                                        servo_names[servo_pin]
                                    )


                                    send_servo_command(

                                        servo_name,

                                        SERVO_REJECT_ANGLE

                                    )


                                    print(

                                        f"ID {track_id} → "

                                        f"{trigger_class.upper()} → "

                                        f"{servo_name} → "

                                        f"{SERVO_REJECT_ANGLE}°"

                                    )


                            else:

                                print(

                                    f"ID {track_id} → "

                                    f"Y = {cy} "

                                    f"不在任何撥桿區域"

                                )


                        print("================================")
                        print()


                    # =================================================
                    # 最終分類
                    # =================================================

                    if passed_line[track_id]:

                        current_final = (
                            locked_class[track_id]
                        )

                    else:

                        current_final = (
                            final_class[track_id]
                        )


                    # =================================================
                    # 顏色
                    # =================================================

                    if current_final == "normal":

                        color = (0, 255, 0)

                    elif current_final == "mold":

                        color = (0, 0, 255)

                    elif current_final == "small":

                        color = (0, 255, 255)

                    else:

                        color = (255, 255, 255)


                    # =================================================
                    # Bounding Box
                    # =================================================

                    cv2.rectangle(

                display_frame,

                        (x1, y1),

                        (x2, y2),

                        color,

                        2

                    )


                    # =================================================
                    # Center
                    # =================================================

                    cv2.circle(

                display_frame,

                        (cx, cy),

                        5,

                        color,

                        -1

                    )


                    # =================================================
                    # ID
                    # =================================================

                    id_text = f"ID: {track_id}"

                    cv2.putText(

                display_frame,

                        id_text,

                        (x1, max(y1 - 60, 25)),

                        cv2.FONT_HERSHEY_SIMPLEX,

                        0.6,

                        color,

                        2

                    )


                    # =================================================
                    # YOLO 判定
                    # =================================================

                    yolo_text = (

                        f"YOLO: {name} {conf:.2f}"

                    )

                    cv2.putText(

                display_frame,

                        yolo_text,

                        (x1, max(y1 - 35, 25)),

                        cv2.FONT_HERSHEY_SIMPLEX,

                        0.6,

                        color,

                        2

                    )


                    # =================================================
                    # 最終判定
                    # =================================================

                    final_text = (

                        f"Final: "

                        f"{current_final.upper()}"

                    )

                    cv2.putText(

                display_frame,

                        final_text,

                        (x1, max(y1 - 10, 25)),

                        cv2.FONT_HERSHEY_SIMPLEX,

                        0.6,

                        color,

                        2

                    )


                    # =================================================
                    # Mold Count
                    # =================================================

                    mold_text = (

                        f"Mold Count: "

                        f"{mold_count}/"

                        f"{MOLD_WINDOW}"

                    )

                    cv2.putText(

                display_frame,

                        mold_text,

                        (x1, min(y2 + 20, height - 80)),

                        cv2.FONT_HERSHEY_SIMPLEX,

                        0.5,

                        color,

                        2

                    )


                    # =================================================
                    # Center 座標
                    # =================================================

                    coord_text = (

                        f"Center: "

                        f"({cx}, {cy})"

                    )

                    cv2.putText(

                display_frame,

                        coord_text,

                        (x1, min(y2 + 45, height - 55)),

                        cv2.FONT_HERSHEY_SIMPLEX,

                        0.5,

                        color,

                        2

                    )


                    # =================================================
                    # 通過狀態
                    # =================================================

                    if passed_line[track_id]:

                        status_text = "PASSED"

                        cv2.putText(

                display_frame,

                            status_text,

                            (x1, min(y2 + 70, height - 30)),

                            cv2.FONT_HERSHEY_SIMPLEX,

                            0.6,

                            color,

                            2

                        )


                    # =================================================
                    # Trigger 狀態
                    # =================================================

                    if triggered[track_id]:

                        trigger_text = "TRIGGERED"

                        cv2.putText(

                display_frame,

                            trigger_text,

                            (x1, min(y2 + 95, height - 5)),

                            cv2.FONT_HERSHEY_SIMPLEX,

                            0.6,

                            color,

                            2

                        )


            # =====================================================
            # 12-1. Lost Track 軌跡預測補償
            #
            # Trigger Line 位置完全不變。
            # 若物件已通過 Decision Line，但在碰 Trigger Line 前
            # YOLO / ByteTrack 暫時失去 bbox，便使用最近的 x1
            # 移動速度繼續往左預測。
            # =====================================================

            for track_id in list(position_history.keys()):

                # 本幀有正常 bbox，不需要預測
                if track_id in seen_this_frame:
                    continue

                # 只補償已通過 Decision Line 的花生
                if not passed_line.get(track_id, False):
                    continue

                # 已觸發 Servo 的 ID 不再處理
                if triggered.get(track_id, False):
                    continue

                # 必須已經有鎖定分類
                if locked_class.get(track_id) is None:
                    continue

                if track_id not in last_bbox:
                    continue

                history = position_history.get(track_id)

                # 至少需要兩個位置才能估計速度
                if history is None or len(history) < 2:
                    continue

                lost_frames[track_id] = (
                    lost_frames.get(track_id, 0) + 1
                )

                # 遺失太久就停止預測，避免誤觸發
                if lost_frames[track_id] > MAX_LOST_FRAMES:
                    continue

                x_values = list(history)

                # 計算最近 x1 每 frame 位移
                x_deltas = [
                    x_values[i] - x_values[i - 1]
                    for i in range(1, len(x_values))
                ]

                velocity_x = (
                    sum(x_deltas) / len(x_deltas)
                )

                # 花生是由右往左；若速度不是負值，不使用預測
                if velocity_x >= 0:
                    continue

                last_x1, last_y1, last_x2, last_y2 = (
                    last_bbox[track_id]
                )

                predicted_x1 = int(
                    last_x1
                    + velocity_x * lost_frames[track_id]
                )

                bbox_width = (
                    last_x2 - last_x1
                )

                predicted_x2 = (
                    predicted_x1 + bbox_width
                )

                predicted_y1 = last_y1
                predicted_y2 = last_y2

                cy = last_cy.get(
                    track_id,
                    int((last_y1 + last_y2) / 2)
                )


                # -------------------------------------------------
                # 畫出預測中的 Bounding Box
                # 青色代表目前是軌跡預測，而不是 YOLO 真實 bbox。
                # -------------------------------------------------

                cv2.rectangle(

                    display_frame,

                    (
                        predicted_x1,
                        predicted_y1
                    ),

                    (
                        predicted_x2,
                        predicted_y2
                    ),

                    (255, 255, 0),

                    2

                )


                cv2.putText(

                    display_frame,

                    f"ID {track_id} PREDICTED",

                    (
                        max(0, predicted_x1),
                        max(30, predicted_y1 - 10)
                    ),

                    cv2.FONT_HERSHEY_SIMPLEX,

                    0.6,

                    (255, 255, 0),

                    2

                )


                # -------------------------------------------------
                # 預測 bbox 左邊界碰到真正 Trigger Line
                # -------------------------------------------------

                if predicted_x1 <= TRIGGER_LINE_X:

                    # 依照最後 Y 位置決定對應 Servo
                    servo_pin = None

                    if SERVO1_Y_MIN <= cy <= SERVO1_Y_MAX:
                        servo_pin = SERVO1_PIN

                    elif SERVO2_Y_MIN <= cy <= SERVO2_Y_MAX:
                        servo_pin = SERVO2_PIN

                    elif SERVO3_Y_MIN <= cy <= SERVO3_Y_MAX:
                        servo_pin = SERVO3_PIN

                    elif SERVO4_Y_MIN <= cy <= SERVO4_Y_MAX:
                        servo_pin = SERVO4_PIN


                    if servo_pin is not None:

                        servo_name = servo_names[
                            servo_pin
                        ]

                        object_class = locked_class[
                            track_id
                        ]

                        # Normal 放行，其餘 Small / Mold 篩除
                        if object_class == "normal":
                            # A normal prediction never resets a servo. This keeps an
                            # NG rejection active when both appear in the same lane.
                            new_normal_trigger_pins.add(servo_pin)
                            target_angle = None

                        else:

                            target_angle = (
                                SERVO_REJECT_ANGLE
                            )


                        if target_angle is not None:
                            send_servo_command(
                                servo_name,
                                target_angle
                            )

                        triggered[track_id] = True


                        print(
                            f"[PREDICTED TRIGGER] "
                            f"ID={track_id} | "
                            f"{object_class} | "
                            f"{servo_name} -> "
                            f"{target_angle if target_angle is not None else 'PASS'} | "
                            f"predicted_x1="
                            f"{predicted_x1}"
                        )


            # NG priority: if a normal reaches the trigger while any current NG
            # occupies the same lane, reject that lane. One 45-degree command is
            # sent per affected lane, independent of YOLO box iteration order.
            active_objects = [
                (locked_class.get(active_id) or final_class.get(active_id), last_cy[active_id])
                for active_id in seen_this_frame
                if active_id in last_cy
            ]
            for pin in sorted(resolve_ng_priority_pins(new_normal_trigger_pins, active_objects)):
                send_servo_command(servo_names[pin], SERVO_REJECT_ANGLE)
                print(f"[NG PRIORITY] 同通道有 NG → {servo_names[pin]} -> {SERVO_REJECT_ANGLE}°")

            # =====================================================
            # 13. 顯示「校正後」畫面
            # =====================================================

            if on_frame:
                on_frame(display_frame, corrected, results, model.names,
                         locked_class, triggered, frame_number, time.monotonic() - session_start,
                         seen_this_frame)
            else:
                cv2.imshow("Peanut Detection", display_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("v"):
                    show_geometry_comparison = not show_geometry_comparison
                    if not show_geometry_comparison:
                        cv2.destroyWindow("Geometry: RAW | PERSPECTIVE")

                if show_geometry_comparison:
                    # 比較相同長寬比、未銳化的畫面，避免將銳化誤認為幾何變形。
                    raw_preview = cv2.resize(frame, (960, 540))
                    corrected_preview = cv2.resize(corrected, (960, 540))
                    cv2.putText(raw_preview, "RAW", (20, 35), cv2.FONT_HERSHEY_SIMPLEX,
                                1, (0, 255, 0), 2)
                    cv2.putText(corrected_preview, "PERSPECTIVE", (20, 35),
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                    cv2.imshow("Geometry: RAW | PERSPECTIVE",
                               np.hstack([raw_preview, corrected_preview]))

                if key == ord("s"):
                    snapshot_dir = Path(__file__).resolve().parent / "geometry_snapshots"
                    snapshot_dir.mkdir(exist_ok=True)
                    stamp = time.time_ns()
                    for label, snapshot in (("raw", frame), ("perspective", corrected)):
                        path = snapshot_dir / f"{stamp}_{label}.png"
                        # imencode + tofile 支援 Windows 中文路徑。
                        ok, encoded = cv2.imencode(".png", snapshot)
                        if not ok:
                            raise RuntimeError(f"無法編碼截圖：{path}")
                        encoded.tofile(str(path))
                    print(f"幾何診斷截圖已儲存：{snapshot_dir}")


                if key == ord("q"):
                    break
                if key == ord(" "):
                    while not stop_event.is_set():
                        key = cv2.waitKey(50) & 0xFF
                        if key == ord(" "):
                            break
                        if key == ord("q"):
                            stop_event.set()
                            break
    finally:
        # Attempt every cleanup even when a disconnected device raises an error.
        import sys
        original_error = sys.exc_info()[0] is not None
        errors = []
        def release(action):
            try:
                action()
            except Exception as exc:
                errors.append(str(exc))
        serial_reader_stop.set()
        if serial_reader_thread is not None:
            release(lambda: serial_reader_thread.join(timeout=2))
        if frame_reader is not None:
            release(frame_reader.stop)
            release(lambda: frame_reader.thread.join(timeout=3))
        if cap is not None:
            release(cap.release)
        if arduino is not None:
            if original_error:
                release(lambda: arduino.write(b"STATE,FAULT\n"))
            release(lambda: arduino.write(b"S\n"))
            for name in ("servo1", "servo2", "servo3", "servo4"):
                release(lambda name=name: arduino.write(f"{name},135\n".encode("utf-8")))
            release(arduino.close)
        if gopro is not None:
            release(gopro.stop)
            release(gopro.disable)
        if on_frame is None:
            import cv2
            release(cv2.destroyAllWindows)
        if errors and not original_error:
            raise RuntimeError("硬體清理失敗：" + "; ".join(errors))


if __name__ == "__main__":
    run_detection()
