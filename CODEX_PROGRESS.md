# Codex 專案進度

此檔案由 Codex 在每次完成程式修改後更新，供後續開發與 GitHub 備份參考。

## 2026-09-06 — 建立 Codex 進度規範

### 已完成
- 建立根目錄 `AGENTS.md`，要求每次程式修改完成後更新本進度檔。
- 建立本檔案，作為後續工作進度、驗證結果與待辦事項的集中紀錄。

### 驗證
- 確認專案根目錄目前沒有既有 `AGENTS.md`，因此未覆蓋原有規範。

### 目前限制
- 無。

### 下一步
- 下一次修改程式時，依 `AGENTS.md` 格式新增進度紀錄。

## 2026-09-06 — 整理正式入口與舊版程式

### 已完成
- 確認根目錄 `run_gui.py` 是目前正式 GUI 入口。
- 保留 `peanut_app`、根目錄 `detect_open_gopro.py` 相容入口、`中興AI競賽/detect_open_gopro.py` 與目前使用中的 `main_control/main_control.ino`。
- 將舊版 `detect.py`、`gopro_arduino.py`、Arduino 整合前備份，以及重複的 `中興AI競賽/arduio` 快照移至 `archive_legacy`。
- 在封存資料夾加入說明，避免誤把舊版當成正式入口。

### 驗證
- 已檢查 `run_gui.py` 對 `peanut_app.gui` 的引用。
- 已確認根目錄沒有再保留舊版 `detect.py` 與 `gopro_arduino.py`。

### 目前限制
- `archive_legacy/arduio_legacy_snapshot` 仍保留作為歷史比對資料，不應直接執行。

### 下一步
- 後續以根目錄 `run_gui.py` 為唯一正式啟動方式。

## 2026-09-06 — 整理專案根目錄

### 已完成
- 根目錄只保留 `run_gui.py`、執行所需套件與資料夾、GoPro 相容入口、備份 EXE 及 Codex 規範檔。
- 說明文件移至 `docs`。
- 測試腳本移至 `tools`，舊版硬體測試與獨立 Arduino 程式移至 `archive_legacy`。
- 保留 `peanut_app`、`中興AI競賽`、`main_control`、`production_data` 與 `runs`，因為它們是目前執行或資料保存所需的內容。

### 驗證
- 確認 `run_gui.py` 仍直接引用根目錄 `peanut_app.gui`。
- 確認根目錄不再有舊版 `detect.py`、獨立 `gopro_arduino.py`、硬體測試腳本或開發測試資料夾。

### 目前限制
- `requirements.txt`、`requirements-gopro.txt` 與 `detect_open_gopro.py` 仍放在根目錄，方便換電腦安裝與維持相容匯入。

### 下一步
- 使用 `python .\\run_gui.py` 啟動正式 GUI；需要查文件時查看 `docs`。

## 2026-09-06 — 登錄 X 模型並比較訓練結果

### 已完成
- 修正 `peanut_app/training.py`：X 模型訓練完成後會讀取最佳 epoch 指標並寫入 `model_versions`。
- 修正 `peanut_app/gui.py`：X 模型訓練完成後會立即刷新模型版本清單。
- 將本次已完成的 `x_model_training_20260906_174932` 補登錄為 `x_auto_20260906_174932`，目前保留為候選、未啟用。
- 比較目前模型：現用 S 模型 `s_auto_20260905_141036_0006` 的最佳 mAP50-95 為 0.8847；新 X 模型為 0.8781。X 模型 Precision 0.9739、Recall 0.9807、mAP50 0.9926。

### 驗證
- 查詢 SQLite `model_versions`，已看到 `x_auto_20260906_174932`。
- `python -m py_compile .\\peanut_app\\training.py .\\peanut_app\\gui.py` 通過。

### 目前限制
- `training_20260906_150210_0008` 的 M 候選結果只有 65 個 epoch，且尚未登錄為完整模型版本；需確認訓練是否中途停止後再決定是否採用。
- X 模型雖已登錄，但不會自動取代目前使用中的 S 模型，需在模型版本清單選取並按「使用／回復到選取版本」。

### 下一步
- 重新開啟 GUI 的「AI 更新 → 模型更新」頁籤即可看到新的 X 候選版本。

## 2026-09-06 — 修正 M 模型命名

### 已完成
- 根據訓練輸出的 `YOLO26m summary`，確認 `x_model_training_20260906_174932` 實際訓練的是 M 架構，不是 X 架構。
- 將已登錄版本從 `x_auto_20260906_174932` 修正為 `m_auto_20260906_174932`；它仍是候選、未啟用。
- 將人工標註後的訓練按鈕、訊息、函式與後續版本命名改為「訓練 M 模型」。X 僅用於代表自動標註與人工確認資料流程。
- 後續 M 候選一律使用 `m_auto_...`，因此被選取後可由 GoPro 生產流程正確載入。

### 驗證
- 查詢 SQLite `model_versions` 後已完成版本更名。
- `python -m py_compile .\\peanut_app\\training.py .\\peanut_app\\gui.py` 通過。

### 目前限制
- 這次既有訓練輸出資料夾名稱仍為 `x_model_training_20260906_174932`，僅是歷史資料夾名稱；權重本身和登錄版本已正確識別為 M。

### 下一步
- 重新開啟 GUI 後，在「模型版本與回復」會看到 `m_auto_20260906_174932`。

## 2026-09-06 — 訓練完成後自動刷新模型清單

### 已完成
- M 模型訓練成功後會自動寫入 `model_versions`，並透過 `m_training_done` 事件刷新 GUI 的模型版本清單。
- 離線更新流程原有的 `training_done` 自動登錄與刷新行為維持不變。

### 驗證
- `python -m py_compile .\\peanut_app\\training.py .\\peanut_app\\gui.py .\\run_gui.py` 通過。
- 確認資料庫內已有 `m_auto_20260906_174932` 候選版本。

### 目前限制
- 本次 GitHub 同步因自動審核達到帳號使用上限而未完成；程式修改已保留在本機工作區。

### 下一步
- 重新開啟 GUI 後執行 M 訓練，訓練完成時會立即看到新版本；GitHub 恢復可用後再提交同步。

## 2026-09-07 — 簡化 AI 更新按鈕名稱

### 已完成
- 將 AI 更新頁面的三個按鈕依序改為「訓練M」、「訓練X」、「人工確認」。
- 保留既有三個流程與按鈕順序，僅調整畫面名稱。

### 驗證
- `python -m py_compile .\\peanut_app\\gui.py .\\peanut_app\\training.py .\\run_gui.py` 通過。

### 目前限制
- GitHub 同步仍待帳號使用額度恢復；本機變更尚未推送。

### 下一步
- 重新開啟 GUI 確認新按鈕名稱。

## 2026-09-07 — 決賽繳交資料初稿

### 已完成
- 新增「決賽繳交資料夾」：成果報告 PDF 12 頁（成果內容 8 頁）、84 × 120 cm 英文海報、作品照片（60,864 bytes）、150 秒 1080p MP4。
- 使用專案原始幀、GUI 圖及完成訓練的 S/M CSV、M 混淆矩陣；附可編輯 Markdown、生成程式、資料來源及繳交檢查清單。

### 驗證
- 生成程式 AST 語法檢查通過，PDF 經 Poppler 轉圖並檢查版面；pypdf 確認頁數及海報 840 × 1200 mm。
- 影片驗證：1500 幀、10 FPS、1920 × 1080、20,156,109 bytes；0、75、149 秒成功解碼。
- git status 顯示新增資料夾，既有 gui.py、training.py 變更保留；未上傳。

### 目前限制
- 正式參賽編號、題名需核對，隊員合照尚缺，心得需本人確認；作品照片目前為機台局部。
- 影片為無配音靜態圖文介紹，未以 Media Player Classic 實播。
- 決賽格式依使用者截圖；Google Sites 頁面未成功擷取，期限需再次核對。
- 提供 PDF 與 Markdown，沒有 Word/PPTX；未上傳競賽系統、YouTube 或 GitHub。

### 下一步
- 補齊報名資訊及真實隊員照片，確認心得與最新規定，再提交。

## 2026-09-07 — M 訓練啟動錯誤診斷與 AMP 避障

### 已完成
- peanut_app/training.py：兩個 M 訓練入口改用 amp=False（FP32），避開 Ultralytics 額外載入／下載 yolo26n.pt 的 AMP 檢查。
- 自動標註前預先載入 M 起始權重；載入失敗顯示檔案路徑、大小及原始錯誤。人工確認訓練入口統一使用 m_model_path。
- 訓練失敗保存 error_traceback.txt；將 32／13 等新增資料數明確標示為「新增標註」，與混合總量區別。
- 保留既有未提交修改及資料集，未替換或啟用權重。

### 驗證
- python -m py_compile peanut_app/training.py peanut_app/gui.py 通過。
- python -m unittest discover -s tools/tests -p test_core.py：10 個測試通過。
- train-13/weights/best.pt ZIP CRC 檢查通過，YOLO 真實載入成功，類別 normal/mold/small 正確。
- 臨時截斷權重測試確認錯誤包含路徑與 PytorchStreamReader 訊息。
- 真實 FP32 trainer 初始化成功到資料載入器入口；測試以 mock 在入口停止，並確認未呼叫 AMP 檢查。

### 目前限制
- 原始 central directory 錯誤未重現，無法確認當時損壞檔案；診斷觀察到 AMP 額外權重下載嘗試，但不能視為根因已證實。
- 未執行完整訓練；未隔離的啟動診斷受沙箱 Windows multiprocessing Pipe 存取限制而停止。
- FP32 可能增加 GPU 記憶體用量並降低速度；尚待 GUI 實際訓練驗證。
- 診斷輸出位於 production_data/training/diagnostic，沒有產生或登錄新模型。

### 下一步
- 重新開啟程式後重試訓練 M；如仍失敗，依新 error_traceback.txt 定位實際出錯位置。

## 2026-09-07 — 沿用既有 X 標註供 M 訓練

### 已完成
- peanut_app/training.py：離線更新先檢查 x_labels_path，標註檔存在即沿用，不再送入 X 推論，也不改寫人工標註或審核狀態。
- 只有缺少標註檔的影像才執行 X 自動標註；全部已有標註時不載入 X 模型，直接準備 M 訓練資料。
- 納入 X_TRAINING 資料，顯示沿用／待標註張數；訓練仍僅使用 AUTO_CANDIDATE、APPROVED、X_TRAINING。
- 新增 tools/tests/test_training_reuse.py，驗證全數沿用及混合既有／缺失標註兩種情境。

### 驗證
- python -m unittest discover -s tools/tests -p test_training_reuse.py：2 項通過；使用 mock 驗證 X 載入／推論次數、既有檔案與審核狀態保留。
- python -m unittest discover -s tools/tests -p test_core.py：10 項通過。
- python -m py_compile peanut_app/training.py：通過。
- git status 可見本次 training.py、測試與進度檔變更；保留其他既有修改。

### 目前限制
- 尚未執行完整 GPU 訓練。
- 判定依據是資料庫記錄的標註檔實際存在；檔案遺失或先前未產生標註檔時仍會嘗試標註。
- 人工確認頁的明確重新標註功能維持原行為；待審核資料不會因沿用標註而自動核准。

### 下一步
- 重新開啟程式執行訓練 M，確認沿用／待標註張數與訓練結果。

## 2026-09-07 — 恢復 AMP 混合精度訓練

### 已完成
- 依使用者要求，peanut_app/training.py 兩個 M 訓練入口恢復 amp=True，更新進度訊息。
- 確認中興AI競賽/yolo26n.pt ZIP CRC 完整且 YOLO 可載入；將該本機權重複製至專案根目錄 yolo26n.pt，供從專案目錄啟動的 AMP 檢查直接使用，避免再次下載。
- 保留既有 X 標註沿用邏輯、錯誤紀錄及 M 起始權重檢查；未停止現行訓練、未覆寫訓練 checkpoint。

### 驗證
- python -m py_compile peanut_app/training.py：通過。
- python -m unittest discover -s tools/tests -p test_training_reuse.py：2 項通過。
- python -m unittest discover -s tools/tests -p test_core.py：10 項通過。
- 根目錄 yolo26n.pt 以 YOLO 實際載入成功。
- git status 顯示程式、測試與進度檔；權重依既有 *.pt 規則忽略，不會交由 Git 備份。

### 目前限制
- 正在執行的 FP32 訓練不會即時切換 AMP，需新啟動的程式／訓練才套用。
- 尚未執行完整 AMP 訓練或速度比較，也未替現行訓練執行 checkpoint 接續。
- 從其他工作目錄啟動時，Ultralytics 的相對權重搜尋位置可能不同。

### 下一步
- 後續重新開啟程式執行訓練時確認 amp=True 及 AMP checks passed；若要保留現行 116 回進度，應從該次 last.pt 接續，而非直接新建訓練。

## 2026-09-07 — 清除已中斷的訓練輸出

### 已完成
- 刪除 production_data/training 下 5 個已開始但未完成的訓練資料夾：training_20260905_135021_0003、training_20260905_135456_0004、training_20260905_140804_0005、training_20260906_150210_0008、training_20260907_015041_0013，約 3.33 GB。
- 對應 training_runs 第 3、4、5、8、13 筆改為 CANCELLED，保留歷史路徑與註記；資料庫變更前備份於 production_data/before_interrupted_cleanup_20260907.sqlite3。
- 完整保留使用者排除的中興AI競賽/runs/detect，以及已完成模型、人工標註和 X 標註。

### 驗證
- 刪除前確認無 Python 程序；5 個 last.pt 均仍有 optimizer，epoch 分別為 10、89、5、64、114（零起算），未完成結束處理。
- 確認刪除目錄沒有現行 training_samples 標註或 model_versions 權重引用。
- PowerShell 刪除前解析絕對路徑並限制為 production_data/training 的直接子目錄；刪除後 5 個目錄均不存在。
- SQLite pragma integrity_check 為 ok；兩個已完成登錄權重及排除目錄內預設模型仍存在。

### 目前限制
- 原本包含診斷及啟動失敗項目的操作遭自動審核拒絕，未執行；縮小為上述 5 個確實中斷項目後已成功。
- 啟動即失敗、僅自動標註及 diagnostic 目錄保留。
- 已刪除的中斷 checkpoint（包含使用者提及約 116 回的訓練）無法再接續；資料庫備份不包含訓練檔案。

### 下一步
- 後續訓練使用保留的完整模型與既有標註。

## 2026-09-07 — 僅保留指定三個模型的訓練成果

### 已完成
- 依使用者圖片保留 yolov26s_best、s_auto_20260905_141036_0006、m_auto_20260906_174932，三個權重均存在。
- 刪除剩餘 training_20260830_153947_0001、training_20260905_134540_0002、training_20260905_143618_0007、training_20260906_174915_0009、training_20260907_011006_0010、training_20260907_011355_0011、training_20260907_014451_0012 及 diagnostic，共 8 個資料夾、2,350,674,988 bytes。
- 對應資料庫紀錄標為 CANCELLED 並保留清理註記；資料庫備份為 production_data/before_keep_three_20260907.sqlite3。
- 未刪除中興AI競賽/runs/detect 下任何內容；保留指定模型的完整輸出、評估圖、人工與 X 標註，以及訓練所需的基礎權重。

### 驗證
- 刪除前確認資料庫沒有新訓練紀錄，現行 Python 程序為 run_gui.py；清理目標均為既有舊訓練。
- 每個刪除目標均解析絕對路徑並驗證位於 production_data/training 直接子層，8 個目錄刪除後均不存在。
- 三個 model_versions 權重實際存在，預設排除目錄內模型存在，SQLite integrity_check 為 ok。

### 目前限制
- 已刪除訓練輸出無法接續，SQLite 備份僅包含資料庫。
- 標註資料夾和模型相關評估輸出保留，不視為額外模型版本。

### 下一步
- 使用保留的模型及既有標註進行後續訓練。

## 2026-09-07 — 決賽資料第二版優化與 Canva 匯入準備

### 已完成
- 從 92 張保存影像與 3 段 GoPro 原始影片挑選素材，補 3 種輸送情境、人工確認介面、驗證預測與標註圖；照片來源記錄含 SHA-256。
- 重排報告 13 頁（正文 9 頁），補控制腳位、相機／訓練參數、資料追溯、47 筆標註狀態、477／516／490 張資料集分布、曲線與矩陣解讀及原始來源。
- 重做英文 84 × 120 cm 海報；影片升為 30 FPS，加入 36 秒原速輸送動態片段，總長維持 150 秒，另附 SRT。
- 產生 Canva HTML 與 ZIP 匯入素材；第一版報告及遮擋照片移至製作來源/歷史初稿，更新繳交檢查說明。

### 驗證
- 新增 Python 來源 AST 檢查通過；PDF 以 Poppler 轉圖檢查頁面，pypdf 確認報告 13 頁、海報 1 頁與 840 × 1200 mm。
- 影片 4500 幀、30 FPS、1920 × 1080、99,267,019 bytes；0、17、45、70、105、128、149 秒成功解碼，另檢視動態片段取樣畫面。
- Canva ZIP 完整性檢查通過，僅含 index.html 與三張所需照片／圖表。
- git status 確認決賽資料夾為新增；既有 gui.py、training.py 及 tools/tests/test_training_reuse.py 等其他工作變更未改動。

### 目前限制
- Canva import-design-from-url 上傳本機 ZIP 遭自動核准審查拒絕，理由為尚無將專案照片與數據傳至 Canva 的明確授權；未以替代管道繞過，未建立 Canva 設計。
- 仍缺正式編號、真實隊員合照及整機全景，心得需本人確認。影片無配音，未用 Media Player Classic 實播。
- 根目錄既有 .gitignore 排除 MP4、ZIP，影片和 Canva ZIP 需另行備份；未對外提交或推送。

### 下一步
- 取得使用者同意將已備妥海報內容、照片與圖表傳至 Canva 後，重試匯入並確認版面與尺寸。
- 補正式參賽資訊及隊員合照，再依最新主辦規定提交。

## 2026-09-07 — 修正 VS Code 啟動造成 M 訓練 AMP 權重誤讀

### 已完成
- 讀取 training_20260907_113734_0014/error_traceback.txt，確認失敗於 check_amp 內 YOLO('yolo26n.pt')，並非 M 起始模型。
- 查得一個 run_gui.py 程序 cwd 為 Microsoft VS Code 安裝目錄，其中 yolo26n.pt 僅 4,194,304 bytes 且非完整 ZIP；專案根目錄及中興AI競賽的權重為 5,544,453 bytes 且完整。
- run_gui.py 在進入 run_app 前固定 cwd 為專案根目錄，使 AMP 檢查讀取既有完整輔助權重。
- 保留 M 訓練目標及 amp=True，未修改 VS Code 目錄檔案，未替換使用者的 M 模型。

### 驗證
- 真實 CUDA 執行 check_amp(M 模型)：AMP checks passed，回傳 True。
- 從臨時外部工作目錄以 runpy 啟動（mock GUI），確認 run_app 被呼叫時 cwd 已為專案根目錄。
- python -m py_compile run_gui.py peanut_app/training.py 通過。
- 標註沿用 2 項測試與核心 10 項測試全部通過。

### 目前限制
- 已開啟 GUI 的工作目錄不會被程式檔修改即時更正，需關閉舊 GUI 再啟動。
- 未執行完整 M 訓練；本次已驗證實際出錯的 GPU AMP 檢查。
- yolo26n.pt 僅用於 AMP 輔助檢查，M 仍由 m_model_path 接續訓練。

### 下一步
- 關閉舊視窗並重新啟動 run_gui.py，再執行訓練 M。

## 2026-09-07 — Qwen 分析截斷處理與 VENV 刪除結果

### 已完成
- analytics.py、config.py：預設輸出上限提高至 4096 tokens；要求精簡完整四節，缺少完成結尾或 done_reason=length 時自動重新生成一次，提高上限至最多 8192。
- 兩次仍未完成會明確標示未完成，不補造完成標記；gui.py 只以末尾完整標記判定完成。
- 簡述超過 500 字或 5 個條目時補上省略提示，導引查看詳細說明。
- 前一回合依使用者要求刪除中興AI競賽/.venv；工具被中斷後本回合確認資料夾已不存在，沒有繼續刪除其他環境。

### 驗證
- mock HTTP 驗證正常完成一次返回、截斷後提高至 8192 重試、兩次截斷保持未完成狀態，全部通過。
- python -m py_compile peanut_app/analytics.py peanut_app/gui.py peanut_app/config.py 通過。
- python -m unittest discover -s tools/tests -p test_core.py：10 項通過。
- Test-Path 中興AI競賽/.venv 回傳 False。

### 目前限制
- 未實際呼叫 Qwen 生成新報告；較長輸出及一次重試可能增加等待時間，每次仍受連線逾時限制。
- 簡述刻意僅顯示摘要，完整內容在詳細說明；若模型仍未完成，會明確顯示警示。

### 下一步
- 重新開啟程式，按 Qwen 分析確認完整四節及最後的完成標記。

## 2026-09-07 — 詳細分析完成後另行生成簡述

### 已完成
- analytics.py：先呼叫 Qwen 生成完整四節詳細分析，確認完成後，再以該完整分析作為第二次請求內容，生成現況、風險、行動三個短摘要條目。
- gui.py：簡述與詳細說明分別顯示獨立內容，移除前 500 字截取方式。
- 摘要要求保留數字與樣本限制、不新增結論；摘要生成失敗時明確提示，仍保留完整詳細分析。

### 驗證
- mock HTTP 確認正常流程呼叫兩次，第二次 prompt 包含第一次完整結果，兩頁顯示各自內容。
- mock 摘要連線逾時確認詳細內容完整保留。
- python -m py_compile peanut_app/analytics.py peanut_app/gui.py 通過。
- python -m unittest discover -s tools/tests -p test_core.py：10 項通過。

### 目前限制
- 尚未以本機 Qwen 實際生成新報告；兩次生成會增加等待時間。
- 未完成的詳細分析不會送入摘要；舊格式報告會提示查看詳細說明。

### 下一步
- 重新啟動程式後按 Qwen 分析，檢視獨立生成的簡述與詳細說明。
## 2026-09-07 — 滾筒根數與八字形連接件用途補充

### 已完成
- 成果報告補充來料尺寸偏差影響滾筒排列：原規劃 23 根，實際調整為 22 根，仍留有剩餘空間。
- 明確說明八字形連接件控制相鄰滾筒間距，摩擦材料帶動自轉；同步兩份成果報告。

### 驗證
- 兩份 DOCX 重新讀取成功，確認 23／22 根與連接件用途文字，五張圖片維持上及下文繞圖。

### 目前限制
- 尚未完成逐頁視覺驗證。

### 下一步
- 可補連接件與摩擦接觸位置近照，完成頁面檢查。

## 2026-09-07 — 成果導向改寫與壓克力管尺寸補充

### 已完成
- 新增 `硬體與配電成果報告.docx` 並同步決賽繳交資料夾；保留五張照片的上及下文繞圖。
- 依使用者要求移除待確認資料表、後續測試建議與不必要的負面敘述，著重自製機構、摩擦傳動改良、四通道分流及配電整合；未新增未量測的效能數字。
- 補充壓克力管來料內、外徑均較設計尺寸大約 0.3 mm，影響配合與齒輪嚙合；以此說明依材料尺寸調整機構的實作歷程。
- 自製成果接續操作章節，避免另留一頁短篇待補內容。

### 驗證
- 重建並重新讀取 DOCX 成功，確認 0.3 mm 材料偏差及 6V 供電內容。
- 確認指定待補表格已移除，五張圖片皆維持上及下文繞圖。

### 目前限制
- 逐頁視覺驗證仍未完成；未宣稱已驗證頁面配置。

### 下一步
- 可補充摩擦布接觸位置、齒輪配合或撥片分流近照，作為機構改良段落的圖示。

## 2026-09-07 — 照片改為上及下文繞圖

### 已完成
- 報告 5 張圖片全部轉為 Word 浮動圖片及 `wrapTopAndBottom`，水平置中、隨段落定位。
- 圖片錨點段落改用單行間距，解除固定行高；另存 `硬體與配電報告_上及下排版.docx` 並同步決賽繳交資料夾。

### 驗證
- 重建成功；檢查 DOCX XML，5 張圖片皆為上及下文繞圖，無剩餘 inline 圖片。

### 目前限制
- 尚未完成 Word 逐頁視覺驗證。

### 下一步
- 在 Word 確認照片完整顯示與分頁位置。

## 2026-09-07 — 確認伺服馬達降壓供電

### 已完成
- 依使用者確認，報告補入 12V 經降壓模組轉為 6V 供四顆 MG996R 使用，移除對應待確認項目。
- 優化版被鎖定，另存 `硬體與配電報告_優化版_6V更新.docx`，同步決賽繳交資料夾。

### 驗證
- 重建成功，重新讀取兩份 DOCX 確認包含 6V 供電說明。

### 目前限制
- 尚未完成逐頁視覺驗證；機構尺寸細節及量化測試資料仍待補。

### 下一步
- 完成頁面視覺驗證，取得機構量測與分流測試資料。

## 2026-09-07 — 硬體報告圖文與配電內容優化

### 已完成
- 新增 `硬體與配電報告_優化版.docx`，並同步至決賽繳交資料夾；原版被開啟鎖定，故另存新檔。
- 精選 5 張整機、CAD、配電及控制桿照片，移除軟體截圖與重複照片，統一圖號，新增頁碼。
- 補充 110V 輸入、12V／100W 輸出、12V／10A 繼電器與 4 顆 MG996R；依使用者要求不在報告中提接地。
- 修正已提供照片仍列為待補的文字，區分已觀察的機構改版與尚未量測的效能。
- 新增 `硬體報告_qa/optimize_report.py` 及本地照片資產供重建使用。

### 驗證
- Python 語法檢查及 DOCX 重新讀取成功；5 張嵌入圖片，關鍵規格檢查通過。
- LibreOffice 渲染工具不可用；另嘗試 Word COM 匯出，尚未取得 PDF，故尚未完成逐頁視覺驗證。

### 目前限制
- MG996R 供電電壓與降壓方式、機構尺寸細節及量化分流測試待補。
- 文件頁面外觀仍需完成視覺驗證。

### 下一步
- 補齊伺服供電資料，確認 Word 分頁與照片位置。

## 2026-09-07 — 建立硬體與配電系統報告初稿

### 已完成
- 依競賽成果報告範例建立獨立的 `硬體與配電報告.docx`。
- 報告內容涵蓋滾筒驅動改版、17HS4417 同軸馬達、摩擦布方案、撥片分流、控制箱、端子台、導軌、配線槽、按鈕、選擇開關與急停配置。
- 將現有生產影像與 GUI／標註畫面嵌入報告，缺少的控制箱及撥片側視照片以待補項目標示。
- 新增可重建報告的 `硬體報告_qa/build_hardware_report.py`。
- 另將報告複製至 `決賽繳交資料夾/硬體與配電報告.docx` 供後續整理。
- 已加入使用者提供的控制箱照片，並補充端子台、配線槽、導軌、驅動器、電源供應器與腳輪說明。
- 已加入兩張整機 3D 設計圖，以及四張整機實體照片，補強結構、控制桿與滾筒配置說明。
- 已補充配電資料：主電源 12V、電源供應器 100W，急停切斷繼電器使整機電源停止。

### 驗證
- 使用 bundled Python 執行 `py_compile` 通過。
- 使用 `python-docx` 重新讀取文件成功：45 個段落、3 個表格、11 張嵌入圖片。
- 已嘗試使用文件技能的 `render_docx.py`；目前環境找不到 LibreOffice `soffice.exe`，因此無法完成 PNG/PDF 視覺渲染檢查。

### 目前限制
- 尚未取得控制箱正面、急停與控制桿、撥片分流側視照片。
- 斷路器／保險絲規格與接地方式尚未提供。

### 下一步
- 補上上述照片與配電規格後，替換待補段落並完成正式繳交版排版檢查。
