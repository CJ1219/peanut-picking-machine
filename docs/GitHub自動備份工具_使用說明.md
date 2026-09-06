# GitHub 自動備份工具

執行 `花生機_GitHub自動備份.exe`，按下「立即上傳到 GitHub」即可完成：

1. 建立四個備份資料夾的 `.gitkeep`。
2. 將程式碼變更加入 Git。
3. 有變更時自動建立提交。
4. 上傳到 `CJ1219/peanut-picking-machine` 的 `main` 分支。

## 使用條件

- EXE 必須放在 `D:\花生機code` 專案根目錄，也就是與 `.git`、`.gitignore` 同一層。
- 電腦需安裝 Git for Windows，並已登入可上傳此 GitHub 倉庫的帳號。
- 上傳內容由 `.gitignore` 控制。

## 不會上傳的內容

- `.venv`
- 測試影片
- ZIP 與快取
- 模型檔
- 資料庫
- `production_data` 的實際內容
- `中興AI競賽/dataset`、`dataset_sharpen`、`runs` 的實際內容

上述四個大型資料夾只會在 GitHub 保留 `.gitkeep` 空資料夾結構。日後換電腦時，將另外備份的實際內容複製回對應資料夾即可。
