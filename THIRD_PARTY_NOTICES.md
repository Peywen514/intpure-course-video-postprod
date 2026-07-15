# 第三方資源授權聲明

本專案使用或參考下列第三方資源。查證日期 2026-07-13。

| 資源 | 授權 | 使用方式 | 備註 |
|---|---|---|---|
| faster-whisper (SYSTRAN) | MIT | pip 依賴，語音辨識 | |
| Whisper model weights (OpenAI) | MIT | 經 faster-whisper 自動下載之 CTranslate2 轉換版權重 | OpenAI 官方明文 code 與 model weights 皆為 MIT |
| FFmpeg (Gyan.FFmpeg full build) | GPLv3 | 外部程式，本工具以 subprocess 呼叫，**不散布、不打包** | 使用者需自行 `winget install Gyan.FFmpeg` 安裝；本工具不因此受 GPL 拘束（GPL FAQ：命令列呼叫外部獨立程式不構成 derivative work） |
| Noto Sans TC | SIL Open Font License 1.1 | 字幕燒錄用字型；文字燒進影片畫面屬渲染輸出，OFL 不限制渲染輸出的使用 | 字型可透過 `config.py` 替換 |
| 片頭/片尾素材（Blender 渲染） | 本專案/客戶自有 | 以 Blender（GPL）渲染；Blender 官方聲明渲染輸出（影片/圖片/`.blend` 檔）完全歸使用者所有，不受 GPL 拘束 | 不打包 Blender 本身 |
| Pexels 影片素材（B-Roll，透過 Pexels API） | [Pexels License](https://www.pexels.com/license/) | `lib/broll.py` 呼叫 Pexels Video API 依 prompt 關鍵字搜尋並下載素材，剪進最終影片 | 2026-07-14 查證：**允許商業用途**，內容本身**不需要標註**攝影師/Pexels 出處；禁止「未修改直接轉售」「在其他圖庫平台轉散布」「當商標使用」。**注意兩層授權不同**：內容授權本身免標註，但 **Pexels API 使用條款額外要求「顯著連結回 Pexels」**（跟內容授權是分開的規定），發布最終影片時建議在說明欄/致謝名單附上 Pexels 連結才算完整合規。API 有速率限制（200 次/小時、20,000 次/月），個人專案用量遠低於此門檻。 |

## 手法參考聲明

字幕 ASS 樣式（白字黑框、置中靠底、字間距等參數配置概念）之手法參考自
[video-autopilot-kit](https://github.com/Hao0321/video-autopilot-kit)（MIT License）的公開實作
（`src/longform_maker/word_captions.py`、`src/silent_vlog_maker/shorts_vertical.py`）。
本專案**未 import、未複製其程式碼**，相關邏輯為理解手法後獨立重寫。

## 給未來的自己（如果要打包發布本工具）

- **絕不可**把 `ffmpeg.exe`（或任何 GPL 授權的執行檔）直接包進安裝包/zip 發給他人；一鍵安裝腳本可以「代跑」winget 安裝指令，但不能夾帶執行檔本身。
- 若字型檔本身（而非燒錄後的影片）要隨工具散布，需附上該字型的 OFL.txt 授權全文。
- faster-whisper 依賴的 `PyAV` 套件之預編譯 wheel 亦含 GPL 授權的 x264/x265，pip install 使用無虞，但若改用 PyInstaller 等方式打包整個 Python 環境發布，屆時需重新評估。
