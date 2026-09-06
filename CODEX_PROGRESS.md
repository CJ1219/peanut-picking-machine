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
