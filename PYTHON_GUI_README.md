# 花生 AI 生產管理 Python 版

已整合影片測試與 GoPro 生產模式。GoPro 模式沿用 `detect_open_gopro.py` 的辨識與 Arduino 撥桿控制，影片模式仍不送硬體指令。

GUI 預設為 GoPro 即時生產。按「開始生產」會在即時系統準備完成後向 Arduino 送 `L`；暫停和停止送 `S`，繼續再送 `L`。同通道同時出現 normal 與 NG 時以 NG 為準，送出排除動作且統計只計 NG。

新版 Arduino 韌體會把實體綠／紅／黃按鈕回報 Python，並以綠燈長亮、紅燈長亮、黃燈閃爍分別表示運轉、停止、異常。黃色按鈕只會清除重新檢查後已不存在的異常。

GoPro 安裝：`python -m pip install -r requirements-gopro.txt`。開啟 GUI 後選「GoPro 生產（控制 Arduino）」，填 COM 與序號尾碼即可啟動。新版規則、模型位置及移機差異請先讀完整說明書頂端的「2026-09-05：GoPro 生產整合版更新」；以下七幀說明為影片模式。

完整操作、安裝及換電腦交付方式請閱讀：`使用說明書_含換電腦準備.md`。

## 啟動

```powershell
python .\run_gui.py
```

操作順序：

1. 進入「生產設定」建立工單。
2. 選擇測試影片。
3. 按「開始」載入 s 模型並辨識。
4. 生產資料、逐顆紀錄、異常及模型訓練紀錄會保存在 `production_data`。

## 已完成的 Python 功能

- Tkinter GUI、960×540 比例辨識畫面、開始／暫停／停止。
- 生產設定與 `YYMDD-VVV-TTT-RRR` 工單號。
- GoPro／攝影機 QR Code 和一般條碼掃描入口，也能手動輸入批號。
- SQLite 工單、逐顆花生、異常、模型版本與訓練紀錄。
- 花生由右往左通過影像中央的真正跨線判斷。
- 中央前 3 幀、中央幀、中央後 3 幀的七幀資料聚合。
- `mold > small > normal`、數量、百分比及 unknown 數量。
- 含部分背景的逐顆裁切圖。
- 每顆通過中央時另存沒有框線文字的完整原始幀，以及該幀全部花生座標。
- 四道、三個邊界區、邊界 NG 雙道排除計畫。
- 暫定中央時間後 1 秒的 Arduino 指令到期時間；只記錄、不傳送。
- 預估 normal 誤排除率。
- 面積／重量校正接口與目標重量停止邏輯。
- 異常查看與清除。
- Python/SQLite 統計和本地 Qwen HTTP 分析接口。
- x 高信心自動標註；x/s 不一致進人工確認區，低信心與 unknown 保留供人工標註。
- train/val 嚴格依工單與物料批次分割，不足兩個批次時不啟動訓練。
- 新 s 模型訓練完成後自動啟用；舊權重與啟用紀錄保留，可從 GUI 回復。

## 影像保存

- `production_data/peanut_images/<工單>/`：每顆花生含部分背景的中央裁切圖。
- `production_data/training_captures/<工單>/images/`：沒有框線文字的完整原始幀。
- `production_data/training_captures/<工單>/metadata/`：當時全部花生的 class、信心值、Track ID、`xyxy` 與正規化 `xywh` 座標。

相同中央幀有多顆花生時只保存一次原始圖，metadata 會列出該幀所有物件。

## 重量校正

第一次啟動後會產生：

`production_data/weight_calibration.json`

校正完成前 `enabled` 保持 `false`，GUI 會顯示「待校正」，也不會用虛構重量觸發達標。線性公式為：

```text
重量(g) = coefficient_a × 七幀平均面積(px²) + coefficient_b
```

若使用冪次公式，將 `formula` 設為 `power`：

```text
重量(g) = coefficient_a × 面積^exponent + coefficient_b
```

## 目前仍是暫定值

- mold 至少 3/7 幀；small 至少 1/7 幀。
- 追蹤最低信心為 0.25，用來保留低信心資料；正式七幀分類最低信心為 0.70。
- 三個道間邊界的半寬為原始影像高度的 1.5%。
- 誤排除使用追蹤速度與花生框寬粗估，硬體距離完成後要改成抵達撥片時間窗。
- Arduino 撥片到期時間為中央通過後 1 秒。
- Qwen 固定使用本機 Ollama loopback `http://127.0.0.1:11434/api/generate`，預設模型為 `qwen3.5:9b`。GUI 不提供位址欄，程式會拒絕區網 IP；影像、生產資料與提示內容不會由本程式送到其他電腦。
- 本地分析會關閉 thinking、限制最多 512 tokens，逾時上限為 300 秒，避免 9B 模型長時間思考造成 `timed out`。

啟動或首次下載模型：

```powershell
ollama run qwen3.5:9b
```

## 測試

```powershell
python -m unittest discover -s .\tests -v
```
