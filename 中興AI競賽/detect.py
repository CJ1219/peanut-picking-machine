from ultralytics import YOLO
import cv2
import numpy as np
import serial
import time
import atexit
from collections import deque


# =========================================================
# 1. Arduino Serial 設定
# =========================================================

ARDUINO_PORT = "COM3"
ARDUINO_BAUDRATE = 115200

try:
    arduino = serial.Serial(
        ARDUINO_PORT,
        ARDUINO_BAUDRATE,
        timeout=1
    )

    # 等待 Arduino 重置完成
    time.sleep(2)

    print(f"Arduino 已連接：{ARDUINO_PORT}")
    print(f"Baud Rate：{ARDUINO_BAUDRATE}")

except Exception as e:
    print(f"無法連接 Arduino：{e}")
    exit()


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

    command = f"{servo_name},{angle}\n"

    try:
        arduino.write(command.encode("utf-8"))

        print(
            f"Arduino 指令 → {command.strip()}"
        )

    except Exception as e:

        print(
            f"Arduino 傳送失敗：{e}"
        )


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


# =========================================================
# 2. 載入 YOLO 模型
# =========================================================

model = YOLO(
    r"C:\Users\baifa\OneDrive\Desktop\中興AI競賽\runs\detect\train-10\weights\best.pt"
)


# =========================================================
# 3. GoPro Webcam 初始化
# =========================================================

CAMERA_ID = 0
CAMERA_RETRY = 5
CAMERA_WARMUP_SECONDS = 3
BLACK_FRAME_MEAN_THRESHOLD = 2.0


def init_gopro_webcam(camera_id=0, max_retry=5):
    """
    以 DirectShow 開啟 GoPro Webcam。

    GoPro Webcam 偶爾會出現「裝置可以開啟，但 frame 全黑」的情況，
    因此這裡會：
      1. 開啟 DirectShow 相機
      2. 暖機並連續讀取多張 frame
      3. 檢查 frame 平均亮度，排除全黑畫面
      4. 成功後才設定 1920x1080
      5. 若設定解析度後又黑屏，release 後重新初始化
    """

    for attempt in range(1, max_retry + 1):

        print()
        print(f"正在初始化 GoPro Webcam... {attempt}/{max_retry}")

        cap = cv2.VideoCapture(
            camera_id,
            cv2.CAP_DSHOW
        )

        if not cap.isOpened():
            print("❌ DirectShow 無法開啟 GoPro Webcam")
            cap.release()
            time.sleep(3)
            continue

        # 先不要立刻設定解析度，讓 GoPro Webcam session 有時間穩定。
        time.sleep(CAMERA_WARMUP_SECONDS)

        live_frame_found = False

        for _ in range(30):

            ret, test_frame = cap.read()

            if ret and test_frame is not None:

                mean_value = float(test_frame.mean())

                if mean_value > BLACK_FRAME_MEAN_THRESHOLD:
                    live_frame_found = True
                    break

            time.sleep(0.05)

        if not live_frame_found:
            print("⚠️ GoPro 已開啟，但目前取得的是全黑畫面")
            print("   釋放相機後重新嘗試...")
            cap.release()
            cv2.destroyAllWindows()
            time.sleep(3)
            continue

        # 已確認能取得非黑畫面後，再要求原程式所需的解析度。
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

        time.sleep(1.5)

        # 確認解析度 negotiation 後仍然有正常影像。
        resolution_ok = False

        for _ in range(30):

            ret, test_frame = cap.read()

            if ret and test_frame is not None:

                mean_value = float(test_frame.mean())

                if mean_value > BLACK_FRAME_MEAN_THRESHOLD:
                    resolution_ok = True
                    break

            time.sleep(0.05)

        if not resolution_ok:
            print("⚠️ 設定 1920x1080 後變成黑畫面，重新初始化...")
            cap.release()
            cv2.destroyAllWindows()
            time.sleep(3)
            continue

        actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = cap.get(cv2.CAP_PROP_FPS)

        print("✅ GoPro Webcam 初始化成功")
        print(f"Camera ID：{camera_id}")
        print(f"實際解析度：{actual_width} x {actual_height}")
        print(f"Camera FPS：{actual_fps:.2f}")
        print(f"Frame Mean：{mean_value:.2f}")

        return cap

    return None


cap = init_gopro_webcam(
    CAMERA_ID,
    CAMERA_RETRY
)

if cap is None:
    print()
    print("❌ GoPro Webcam 初始化失敗")
    print("請確認 GoPro Webcam Preview 已正常顯示，再關閉 Preview 後重試。")

    arduino.close()
    raise SystemExit


print("GoPro 已開啟")


# =========================================================
# 3-0. 安全釋放 GoPro Webcam
# =========================================================

def release_gopro_webcam():
    global cap

    try:
        if cap is not None and cap.isOpened():
            print("正在釋放 GoPro Webcam...")
            cap.release()
            print("✅ GoPro Webcam 已釋放")
    except Exception as e:
        print(f"釋放 GoPro Webcam 時發生錯誤：{e}")

    try:
        cv2.destroyAllWindows()
    except Exception:
        pass


# 正常結束、SystemExit 或未處理 Exception 時都嘗試釋放相機。
atexit.register(release_gopro_webcam)


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

    [477, 0],       # 左上

    [1627, 94],      # 右上

    [1919, 1006],     # 右下

    [165, 989]      # 左下

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

    [OUTPUT_WIDTH, 0],                # 右上

    [OUTPUT_WIDTH, OUTPUT_HEIGHT],    # 右下

    [0, OUTPUT_HEIGHT]                # 左下

])


# ---------------------------------------------------------
# 計算透視變換矩陣
# ---------------------------------------------------------

matrix = cv2.getPerspectiveTransform(
    POINTS,
    DST_POINTS
)


print("透視校正矩陣建立完成")


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

TRIGGER_LINE_X = 65

print(
    f"Trigger Line 位置：X = {TRIGGER_LINE_X}"
)


# =========================================================
# 5-2. 四個撥桿區域
# =========================================================

SERVO1_Y_MIN = 105
SERVO1_Y_MAX = 360
SERVO1_PIN = 2

SERVO2_Y_MIN = 341
SERVO2_Y_MAX = 598
SERVO2_PIN = 3

SERVO3_Y_MIN = 579
SERVO3_Y_MAX = 811
SERVO3_PIN = 4

SERVO4_Y_MIN = 792
SERVO4_Y_MAX = 953
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
# 8. 主迴圈
# =========================================================

while True:

    # =====================================================
    # 8-1. 讀取 GoPro 原始畫面
    # =====================================================

    ret, frame = cap.read()

    if not ret:

        print("❌ 無法取得 GoPro 影像")

        continue


    # =====================================================
    # 8-2. 透視校正
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
    # 8-3. YOLO Tracking
    # =====================================================

    results = model.track(

        corrected,

        imgsz=1024,

        conf=0.5,

        persist=True,

        tracker="bytetrack.yaml",

        verbose=False

    )


    # =====================================================
    # 9. 畫判定線
    #
    # 注意：
    # 這裡改成畫在 corrected
    # =====================================================

    cv2.line(

        corrected,

        (DECISION_LINE_X, 0),

        (DECISION_LINE_X, height),

        (255, 0, 255),

        3

    )


    cv2.putText(

        corrected,

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

        corrected,

        (TRIGGER_LINE_X, 0),

        (TRIGGER_LINE_X, height),

        (0, 165, 255),

        3

    )


    cv2.putText(

        corrected,

        "TRIGGER LINE",

        (TRIGGER_LINE_X + 10, 100),

        cv2.FONT_HERSHEY_SIMPLEX,

        0.7,

        (0, 165, 255),

        2

    )


    # =====================================================
    # 9-2. 四個撥桿區域
    # =====================================================

    # Servo1

    cv2.line(

        corrected,

        (0, SERVO1_Y_MIN),

        (width, SERVO1_Y_MIN),

        (0, 0, 0),

        2

    )


    cv2.line(

        corrected,

        (0, SERVO1_Y_MAX),

        (width, SERVO1_Y_MAX),

        (0, 0, 0),

        2

    )


    # Servo2

    cv2.line(

        corrected,

        (0, SERVO2_Y_MAX),

        (width, SERVO2_Y_MAX),

        (0, 0, 0),

        2

    )


    # Servo3

    cv2.line(

        corrected,

        (0, SERVO3_Y_MAX),

        (width, SERVO3_Y_MAX),

        (0, 0, 0),

        2

    )


    # Servo4

    cv2.line(

        corrected,

        (0, SERVO4_Y_MAX),

        (width, SERVO4_Y_MAX),

        (0, 0, 0),

        2

    )


    # =====================================================
    # 9-3. 區域名稱
    # =====================================================

    cv2.putText(

        corrected,

        "Servo1 (PIN 2)",

        (100, 250),

        cv2.FONT_HERSHEY_SIMPLEX,

        0.8,

        (0, 0, 0),

        2

    )


    cv2.putText(

        corrected,

        "Servo2 (PIN 3)",

        (100, 480),

        cv2.FONT_HERSHEY_SIMPLEX,

        0.8,

        (0, 0, 0),

        2

    )


    cv2.putText(

        corrected,

        "Servo3 (PIN 4)",

        (100, 700),

        cv2.FONT_HERSHEY_SIMPLEX,

        0.8,

        (0, 0, 0),

        2

    )


    cv2.putText(

        corrected,

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


            # =================================================
            # 如果還沒通過判定線
            # 才更新分類
            # =================================================

            if not passed_line[track_id]:

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
                # SMALL
                # =============================================

                if name == "small":

                    final_class[track_id] = "small"


                # =============================================
                # MOLD
                # =============================================

                elif (

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

                cx <= TRIGGER_LINE_X

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

                corrected,

                (x1, y1),

                (x2, y2),

                color,

                2

            )


            # =================================================
            # Center
            # =================================================

            cv2.circle(

                corrected,

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

                corrected,

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

                corrected,

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

                corrected,

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

                corrected,

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

                corrected,

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

                    corrected,

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

                    corrected,

                    trigger_text,

                    (x1, min(y2 + 95, height - 5)),

                    cv2.FONT_HERSHEY_SIMPLEX,

                    0.6,

                    color,

                    2

                )


    # =====================================================
    # 13. 顯示「校正後」畫面
    # =====================================================

    cv2.imshow(

        "Peanut Detection",

        corrected

    )


    # =====================================================
    # 鍵盤
    # =====================================================

    key = cv2.waitKey(1) & 0xFF


    # Q：離開

    if key == ord("q"):

        break


    # =====================================================
    # Space：暫停
    # =====================================================

    if key == ord(" "):

        print(
            "影片處理暫停，按 Space 繼續"
        )


        while True:

            key = cv2.waitKey(0) & 0xFF


            if key == ord(" "):

                print(
                    "影片處理繼續"
                )

                break


            if key == ord("q"):

                release_gopro_webcam()

                arduino.close()

                exit()


# =========================================================
# 14. 結束
# =========================================================

release_gopro_webcam()


# =========================================================
# 14-1. 所有 Servo 回到 135°
# =========================================================

print()

print(
    "影片結束，所有 Servo 回到 135°"
)


for pin, servo_name in servo_names.items():

    send_servo_command(

        servo_name,

        SERVO_NORMAL_ANGLE

    )


time.sleep(0.5)


# =========================================================
# 14-2. 關閉 Arduino Serial
# =========================================================

arduino.close()


print()

print("================================")

print("辨識完成！")

print("Arduino Serial 已關閉")

print("================================")