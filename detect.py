# =============================================================================
# 花生辨識與生產管理系統：TODO／規格備忘／待解決邏輯問題
# =============================================================================
# Python GUI 新版入口為 run_gui.py，模組放在 peanut_app/；本檔保留為舊版辨識參考。
# Arduino 整合依使用者指示延後，目前 Python 只保存預定指令時間，不傳送硬體命令。
#
#
# 狀態標記：
#   [x] 已確認的需求或規則
#   [ ] 尚未實作
#   [?] 尚待確認或需要實測的規格
#
# -----------------------------------------------------------------------------
# 一、已確認規格
# -----------------------------------------------------------------------------
# [x] 現階段使用影片檔，後續改成 GoPro 即時影像。
# [x] 花生移動方向為「由右往左」。
# [x] 畫面由上到下分成四道，使用花生中心點判斷所在道別。
# [x] 工單格式：YYMDD-VVV-TTT-RRR，例如 26H30-001-001-001。
#     M 使用英文字母表示月份：A=1 月、B=2 月……L=12 月。
# [x] 使用 GoPro 掃描物料批號；仍需確認條碼種類及資料格式。
# [x] 每顆花生保存含部分背景的裁切圖。
# [x] 分類優先順序：mold > small > normal。
# [x] 信心值使用中央幀與前後各 3 幀，共 7 幀的資料計算。
# [x] 面積與估算重量也使用上述 7 幀的平均值。
# [x] 面積轉重量公式後續以實際花生面積與重量資料校正。
# [x] 達到目標重量後立即停止全部設備，並建立可清除的異常。
# [x] 若清除異常後仍使用已達標的同一張工單重新啟動，系統會再次立即停止。
# [x] NG 位於兩道邊界區時，相鄰兩道撥片都要動作。
# [x] 邊界區以花生中心點判斷，不以 Bounding Box 是否接觸判斷。
# [x] 預估誤排除率 = 預估被誤排的 normal 數 / normal 總數 * 100%。
# [x] 線上使用 s 模型，線下使用 x 模型自動標註後訓練 s 模型。
# [x] 本地 Ollama `qwen3.5:9b` 分析統計資料；只允許本機 loopback，禁止區網。
#
# -----------------------------------------------------------------------------
# 二、GUI TODO
# -----------------------------------------------------------------------------
# [x] 建立主畫面並顯示辨識影像。
# [x] 顯示 normal／mold／small 的數量與百分比。
# [x] 顯示目前工單、累計估算重量、目標重量及機器狀態。
# [x] 增加開始、暫停、停止與異常清除控制。
# [x] 「生產設定」頁面：
#     - 廠商編號、物料批號、物料製造日期、生產目標重量。
#     - 廠商編號、花生種類編號、工單流水號。
#     - GoPro 掃碼輸入物料批號，也要保留手動輸入方式。
#     - 顯示 AI 分析數據。
# [x] 「異常狀況」頁面：
#     - 顯示發生時間、異常類型、內容、是否已清除。
#     - 尚未填寫生產資料、達到目標重量、速度異常、相機中斷、
#       Arduino 中斷、模型錯誤、照片或資料寫入失敗等。
# [x] 「AI 更新」頁面：
#     - 顯示資料集數量、目前模型、候選模型及訓練狀態。
#     - 啟動 x 模型自動標註及 s 模型訓練。
#     - 新模型訓練完成後自動啟用，但不覆蓋舊權重；保留版本、資料與回復入口。
# [x] GUI 主執行緒不直接執行耗時辨識、資料寫入或訓練。
#
# -----------------------------------------------------------------------------
# 三、每顆花生的辨識、截圖與資料 TODO
# -----------------------------------------------------------------------------
# [x] 新版判定線使用原始影像的水平中央 width // 2，而不是固定 X=500。
# [x] 右往左通過中央的條件為：上一位置在中央右側，這一位置到達或越過中央。
#     只判斷 cx <= 中央線會讓剛出現在左側的物件被錯誤計數。
# [x] 每個 Track 保存中央前 3 幀、中央幀、中央後 3 幀的偵測資料。
# [x] 中央幀取中心 X 最接近中央線的那一幀。
# [x] 中央後第 3 幀完成後，才鎖定分類、平均信心值、平均面積及估算重量。
# [x] 保存中央幀的花生裁切圖，裁切時在 Bounding Box 四周保留可調背景邊距。
# [x] 圖片名稱：工單號-P000001.jpg；流水號由 SQLite 持久保存。
# [ ] 建議每顆資料至少保存：
#     - 工單號、花生流水號、Track ID、時間。
#     - normal／mold／small、中央幀信心值、7 幀平均信心值。
#     - 各類別在 7 幀中的出現次數及有效幀數。
#     - 7 幀平均面積、估算重量、道別、是否位於邊界區。
#     - 使用模型的版本及權重檔雜湊值。
#     - 廠商編號、物料批號、物料製造日期、生產日期。
#     - 圖片路徑、預計啟動的撥片、是否預估誤排 normal。
# [x] 使用 SQLite 保存工單、逐顆資料、異常、模型版本及訓練紀錄。
# [x] Track 完成或離開畫面後清除暫存，避免長時間運作造成記憶體持續增加。
# [ ] 處理追蹤 ID 中斷或改變，避免同一顆被重複計數。
#
# -----------------------------------------------------------------------------
# 四、Arduino 指令排程 TODO
# -----------------------------------------------------------------------------
# [x] 暫定在花生通過中央的時間點後 1 秒輸出 Arduino 撥片指令。
# [ ] 使用下方 ARDUINO_COMMAND_DELAY_SECONDS 全域變數控制暫定延遲。
# [ ] 不可在辨識迴圈中使用 time.sleep(1) 阻塞程式；應記錄：
#     command_due_time = center_cross_time + ARDUINO_COMMAND_DELAY_SECONDS
#     再由非阻塞排程佇列於到期時送出指令。
# [ ] 1 秒只是目前暫用值；後續改成攝影中央至撥片距離、輸送速度、
#     通訊延遲及伺服反應時間的校正結果。
# [ ] 等待中央後 3 幀才能完成判定；必須確認能在 1 秒期限前完成運算與傳送。
# [ ] 正常品不撥除；mold 或 small 依所在道別啟動對應 MG996r。
# [ ] NG 中心位於邊界區時，同時安排相鄰兩道撥片。
# [ ] 合併同一撥片時間重疊的事件，避免伺服重複收到互相衝突的角度指令。
# [ ] Arduino 指令需要事件編號、ACK 回覆、逾時及重送／停止策略。
# [ ] 實體啟動鈕應先通知 Python；Python 驗證工單與系統狀態後才允許運轉。
# [ ] 實體停止鈕必須由 Arduino 本機立即停止，不可等待 Python 回覆。
# [ ] 速度異常時傳送停止指令、鎖定異常狀態，清除異常後才能重新啟動。
#
# -----------------------------------------------------------------------------
# 五、四道、邊界與誤排除 TODO
# -----------------------------------------------------------------------------
# [x] 建立暫定四道 Y 範圍及三個道間邊界區；正式數值仍須校正。
# [x] NG 與 normal 位於同一道，且沿輸送方向的距離不超過一顆花生長度時，
#     將該 normal 標記為「預估誤排」。
# [ ] 正式版本改用預計到達撥片的時間區間判斷是否一起被排除。
# [x] 邊界 NG 會影響相鄰兩道，因此兩道內可能被波及的 normal 都要檢查。
# [x] 同一顆 normal 被多個 NG 撥片事件波及時只計算一次。
# [x] 沒有終端感測器或第二部攝影機前，介面標示為「預估誤排除率」。
#
# -----------------------------------------------------------------------------
# 六、重量、達標與機器狀態 TODO
# -----------------------------------------------------------------------------
# [x] 先保存 7 幀平均面積；重量公式尚未完成時顯示「待校正」。
# [ ] 後續用實測資料建立面積轉重量公式，必要時四道分別校正。
# [ ] 累計估算重量 >= 目標重量時：
#     - 立即送出全部停止指令。
#     - 鎖定「已達目標重量」異常。
#     - 記錄停止時間、累計重量及當時尚在途中的 Track。
# [ ] 接受停止重量可能超過目標，因為每顆重量需要等中央後 3 幀才會完成。
# [ ] 清除「已達目標重量」後若沿用原工單，重新啟動會因仍達標而再次停止。
# [ ] 機器狀態至少包含 STOPPED、RUNNING、FAULT；達標事件歸入可清除 FAULT。
#
# -----------------------------------------------------------------------------
# 七、自動標註、模型訓練與 AI 分析 TODO
# -----------------------------------------------------------------------------
# [x] 保存無框線文字的完整中央原始幀，以及該幀全部花生座標與信心值。
# [x] x 模型只把高於門檻的標註加入自動訓練候選集；預設門檻 0.90。
# [x] x 與 s 類別、數量或位置不一致時，放入人工確認區。
# [x] 低信心與 unknown 保存完整原始幀及座標，保留供人工標註。
# [x] 每顆只保存一張中央訓練幀，避免相鄰幀被拆到 train/val。
# [x] 嚴格依工單／物料批次切分資料；不足兩個群組時禁止訓練。
# [x] 新模型訓練完成後自動啟用；舊模型、資料與啟用紀錄保留以便回復。
# [ ] 評估模型不能只看平均信心值，還要使用固定驗證集比較 precision、
#     recall、mAP、各類別錯誤率及誤排除率。
# [x] 使用 Python／SQL 先計算可靠的統計值，再交給 qwen3.5:9b 解讀與產生提示。
# [ ] 廠商 NG 率、季節重量等分析要同時顯示樣本數，避免小樣本誤導。
#
# -----------------------------------------------------------------------------
# 八、目前待確認／待補資料
# -----------------------------------------------------------------------------
# [?] 7 幀分類門檻：mold、small 各需要在 7 幀中出現幾次？
# [?] 最終類別平均信心值只平均該類出現的幀，或缺少的幀以 0 計算？
# [?] GoPro 掃描 QR Code、一般條碼或兩者；條碼內的欄位格式為何？
# [?] 右往左運轉時 Arduino 應使用 L 還是 R？
# [?] 使用哪一份 Arduino 主程式為準；目前工作區版本與完成項目不一致。
# [?] Arduino 鮑率與完整的 Python/Arduino 指令、回報、ACK 格式。
# [?] 四顆 MG996r 的道別、角度、保持時間、復位角度及冷卻時間。
# [?] 攝影中央到各撥片的距離、輸送速度及一顆花生長度的判定值。
# [?] 速度異常由影像速度、馬達回報或編碼器判斷，以及允許範圍與持續時間。
# [?] 面積轉重量公式及校正資料；20 顆可先試算，後續應增加樣本。
# [x] Qwen 使用 Ollama 執行，模型指令：ollama run qwen3.5:9b。
# [?] 使用者回覆的第 4 點尚未完成，等待後續補充。
#
# =============================================================================

from ultralytics import YOLO
import cv2
from collections import deque


# 暫用：花生通過影像中央後，延遲多少秒傳送 Arduino 撥片指令。
# 注意：目前尚未接上 Arduino 排程；未來需改用實際距離與輸送速度校正。
ARDUINO_COMMAND_DELAY_SECONDS = 1.0

# =========================
# 1. 載入模型
# =========================

model = YOLO(
    r"C:\Users\user\OneDrive - 中原大學\桌面\大學作品集\花生機\yolo\yolov26s_best.pt"
)

# =========================
# 2. 影片路徑
# =========================

video_path = r"C:\Users\user\OneDrive - 中原大學\桌面\大學作品集\花生機\影片素材\video_001.mp4"

cap = cv2.VideoCapture(video_path)

if not cap.isOpened():
    print("無法開啟影片")
    exit()

# =========================
# 3. 取得影片資訊
# =========================

fps = cap.get(cv2.CAP_PROP_FPS)

if fps <= 0:
    fps = 30

width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

video_duration = total_frames / fps

print(f"影片 FPS：{fps:.2f}")
print(f"影片解析度：{width} x {height}")
print(f"總幀數：{total_frames}")
print(f"影片長度：約 {video_duration:.2f} 秒")

# =========================
# 4. 判定線
# =========================
#
# 花生由左往右移動
#
# Center X 通過這條線
# 就進行最終分類
#

DECISION_LINE_X = 500

print(f"判定線位置：X = {DECISION_LINE_X}")

# =========================
# 5. Mold 判定設定
# =========================

# 最近幾幀
MOLD_WINDOW = 10

# 最近10幀中
# 出現5次 mold
# 就判定 MOLD
MOLD_THRESHOLD = 5

print(
    f"Mold 判定：最近 {MOLD_WINDOW} 幀中，"
    f"累積 {MOLD_THRESHOLD} 次 mold → MOLD"
)

# =========================
# 6. Tracking 資料
# =========================

# 每個 ID 最近10幀的 mold 紀錄
mold_history = {}

# 每個 ID 的目前分類
final_class = {}

# 每個 ID 是否已經通過判定線
passed_line = {}

# 每個 ID 通過判定線後的最終分類
locked_class = {}

# =========================
# 7. 開始處理影片
# =========================

WINDOW_NAME = "Peanut Detection"
WINDOW_WIDTH = 960
WINDOW_HEIGHT = 540

cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
cv2.resizeWindow(WINDOW_NAME, WINDOW_WIDTH, WINDOW_HEIGHT)

frame_number = 0

while True:

    ret, frame = cap.read()

    if not ret:
        print("影片播放完畢")
        break

    frame_number += 1

    # =========================
    # YOLO Tracking
    # =========================

    results = model.track(
        frame,
        imgsz=640,
        conf=0.7,
        persist=True,
        tracker="bytetrack.yaml",
        verbose=False
    )

    # =========================
    # 8. 畫判定線
    # =========================

    cv2.line(
        frame,
        (DECISION_LINE_X, 0),
        (DECISION_LINE_X, height),
        (255, 0, 255),
        3
    )

    cv2.putText(
        frame,
        "DECISION LINE",
        (DECISION_LINE_X - 180, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 0, 255),
        2
    )

    # =========================
    # 9. 處理每個 Bounding Box
    # =========================

    for result in results:

        for box in result.boxes:

            # =========================
            # Class
            # =========================

            cls = int(box.cls[0])
            name = model.names[cls]

            # =========================
            # Confidence
            # =========================

            conf = float(box.conf[0])

            # =========================
            # Tracking ID
            # =========================

            if box.id is not None:
                track_id = int(box.id[0])
            else:
                track_id = -1

            if track_id == -1:
                continue

            # =========================
            # Bounding Box
            # =========================

            x1, y1, x2, y2 = map(
                int,
                box.xyxy[0]
            )

            # =========================
            # Center
            # =========================

            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)

            # =========================
            # 初始化新的 ID
            # =========================

            if track_id not in mold_history:

                mold_history[track_id] = deque(
                    maxlen=MOLD_WINDOW
                )

                final_class[track_id] = "normal"

                passed_line[track_id] = False

                locked_class[track_id] = None

            # =========================
            # 如果還沒通過判定線
            # 才更新分類
            # =========================

            if not passed_line[track_id]:

                # =========================
                # 記錄 Mold
                # =========================

                if name == "mold":

                    mold_history[track_id].append(1)

                else:

                    mold_history[track_id].append(0)

                # =========================
                # Mold Count
                # =========================

                mold_count = sum(
                    mold_history[track_id]
                )

                # =========================
                # SMALL
                # =========================
                #
                # 偵測到一次 small
                # 立即判定 SMALL
                #

                if name == "small":

                    final_class[track_id] = "small"

                # =========================
                # MOLD
                # =========================
                #
                # 最近10幀中
                # mold >= 3
                #

                elif (
                    final_class[track_id] == "normal"
                    and
                    mold_count >= MOLD_THRESHOLD
                ):

                    final_class[track_id] = "mold"

            else:

                # 已經通過判定線
                # 不再更新 Mold Count

                mold_count = sum(
                    mold_history[track_id]
                )

            # =========================
            # 10. 判斷是否通過判定線
            # =========================
            #
            # 花生由左往右移動
            #
            # Center X >= 判定線
            #

            if (
                not passed_line[track_id]
                and
                cx <= DECISION_LINE_X
            ):

                passed_line[track_id] = True

                # 鎖定最終分類
                locked_class[track_id] = final_class[track_id]

                print(
                    f"ID {track_id} 通過判定線 → "
                    f"{locked_class[track_id].upper()}"
                )

                # =========================
                # 未來可以在這裡控制 Arduino
                # =========================

                if locked_class[track_id] == "mold":

                    print(
                        f"ID {track_id} → MOLD → 啟動撥桿"
                    )

                elif locked_class[track_id] == "small":

                    print(
                        f"ID {track_id} → SMALL → 啟動撥桿"
                    )

                else:

                    print(
                        f"ID {track_id} → NORMAL → 不動作"
                    )

            # =========================
            # 最終分類
            # =========================

            if passed_line[track_id]:

                current_final = locked_class[track_id]

            else:

                current_final = final_class[track_id]

            # =========================
            # 顏色
            # =========================

            if current_final == "normal":

                color = (0, 255, 0)

            elif current_final == "mold":

                color = (0, 0, 255)

            elif current_final == "small":

                color = (0, 255, 255)

            else:

                color = (255, 255, 255)

            # =========================
            # Bounding Box
            # =========================

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                color,
                2
            )

            # =========================
            # Center
            # =========================

            cv2.circle(
                frame,
                (cx, cy),
                5,
                color,
                -1
            )

            # =========================
            # ID
            # =========================

            id_text = f"ID: {track_id}"

            cv2.putText(
                frame,
                id_text,
                (x1, max(y1 - 60, 25)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2
            )

            # =========================
            # YOLO 判定
            # =========================

            yolo_text = f"YOLO: {name} {conf:.2f}"

            cv2.putText(
                frame,
                yolo_text,
                (x1, max(y1 - 35, 25)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2
            )

            # =========================
            # 最終判定
            # =========================

            final_text = (
                f"Final: {current_final.upper()}"
            )

            cv2.putText(
                frame,
                final_text,
                (x1, max(y1 - 10, 25)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2
            )

            # =========================
            # Mold Count
            # =========================

            mold_text = (
                f"Mold Count: "
                f"{mold_count}/{MOLD_WINDOW}"
            )

            cv2.putText(
                frame,
                mold_text,
                (x1, y2 + 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2
            )

            # =========================
            # Center 座標
            # =========================

            coord_text = (
                f"Center: ({cx}, {cy})"
            )

            cv2.putText(
                frame,
                coord_text,
                (x1, y2 + 45),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2
            )

            # =========================
            # 通過狀態
            # =========================

            if passed_line[track_id]:

                status_text = "PASSED"

                cv2.putText(
                    frame,
                    status_text,
                    (x1, y2 + 70),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color,
                    2
                )

    # =========================
    # 11. 顯示 Frame
    # =========================

    progress = (
        f"Frame: {frame_number}/{total_frames}"
    )

    cv2.putText(
        frame,
        progress,
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2
    )

    # =========================
    # 12. 顯示畫面
    # =========================

    cv2.imshow(
        WINDOW_NAME,
        frame
    )

    # 不等待33ms
    key = cv2.waitKey(1) & 0xFF

    # Q：離開
    if key == ord("q"):
        break

    # =========================
    # Space：暫停
    # =========================

    if key == ord(" "):

        print("影片處理暫停，按 Space 繼續")

        while True:

            key = cv2.waitKey(0) & 0xFF

            if key == ord(" "):

                print("影片處理繼續")
                break

            if key == ord("q"):

                cap.release()
                cv2.destroyAllWindows()
                exit()

# =========================
# 13. 結束
# =========================

cap.release()
cv2.destroyAllWindows()

print()
print("================================")
print("辨識完成！")
print("================================")
