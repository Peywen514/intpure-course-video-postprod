# 課程影片後製

線上課程影片後製自動化工具：語音辨識轉字幕、字幕位置/寬度/字距互動調整、匹配、（後續）贅詞跳剪、片頭片尾套用。設計成可跨案共用，不綁死單一客戶。

## 環境需求

- Python 3.9+
- **ffmpeg / ffprobe**：需自行安裝並加入 PATH（`winget install Gyan.FFmpeg`，或至 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 下載）。
  **本工具不包含、不散布 ffmpeg 執行檔**——ffmpeg（Gyan.FFmpeg full build）為 GPLv3 授權，本工具僅以子行程（subprocess）呼叫外部 `ffmpeg.exe`，不連結、不打包其原始碼或二進位檔。若未來需要將本工具打包發布給其他人安裝，請勿把 `ffmpeg.exe` 一併塞進安裝包/zip，應讓對方自行透過上述方式安裝。詳見 `THIRD_PARTY_NOTICES.md`。
- 思源黑體（Noto Sans TC）：Windows 系統若已安裝可直接使用（`C:\Windows\Fonts\NotoSansTC-VF.ttf`）。字型名稱設定在 `config.py`，之後可替換成其他可商用授權的開源字體。
- `pip install -r requirements.txt`（faster-whisper）
- （可選）字幕翻譯功能需要環境變數 `GOOGLE_TRANSLATE_API_KEY`（GCP 專案開通 Cloud Translation API 後建立的金鑰）。沒設定這個變數也不影響其他階段，只有按下「翻譯」按鈕時才會用到，未設定時會顯示缺金鑰的錯誤訊息。目標語言清單在 `config.py` 的 `TRANSLATE_TARGET_LANGS`。
- （可選）B-Roll 素材搜尋功能需要環境變數 `PEXELS_API_KEY`（[pexels.com/api](https://www.pexels.com/api/) 免費申請）。用途：拿字幕文字當關鍵字去 Pexels 搜尋免費商用影片素材下載，不是生成式 AI。授權查證見 `THIRD_PARTY_NOTICES.md`——內容免標註但 API 使用條款要求顯著連結回 Pexels，發布最終影片時記得在說明欄/致謝名單附上。

## 使用方式（推薦：儀表板網頁）

1. **雙擊 `啟動儀表板.bat`**（或手動打 `python app.py`）— 會開一個黑色視窗＋自動跳出瀏覽器（預設 http://127.0.0.1:8080/）；不想用的時候關掉那個黑色視窗即可停止伺服器
2. 網頁最上方「選擇檔案」上傳要處理的原始影片（會自動存進 `input/`；也可以不透過網頁、直接把檔案手動複製進 `input/` 資料夾，效果一樣）
3. 網頁上針對每個集數依序點按鈕：① 開始轉錄 → ② 校對字幕（可略過，語音辨識偶爾會有錯字，開新分頁對照影片逐句修正）→ ③ 調整字幕位置（可略過）→ ④ 匹配字幕 → ⑤ 偵測贅詞 → 勾選要剪除的模糊詞按「確認送出」 → ⑥ 套用跳剪 → ⑦ 套用片頭尾 → ⑧ 品質檢查 → ⑨ 翻譯字幕（可略過，輸出跟原文同一組時間碼的 `.srt`，不燒錄進影片）
4. 每個階段完成的狀態會即時反映在集數卡片上的徽章；產出的影片可以直接在頁面上點連結播放或下載

不需要打指令、不需要知道背後跑的是哪支 Python 檔、也不用自己找資料夾複製檔案——雙擊 `.bat`、網頁上傳影片、點按鈕即可。

`啟動儀表板.bat` 會自動把 winget 裝的 ffmpeg 路徑補進當次執行的 PATH（這台機器的系統 PATH 目前還沒真的刷新到新開的視窗，所以用這個方式繞開，不依賴系統設定）。若要在別台電腦上用，該台機器需要先自行安裝 Python 3.9+ 與 ffmpeg（`winget install Gyan.FFmpeg`），且 `啟動儀表板.bat` 裡寫死的 ffmpeg 路徑可能要依該機器實際安裝路徑調整——**目前這個 `.bat` 只在本機驗證過，還沒打包成能直接在別人電腦上開箱即用的安裝檔**，之後真的要給同事用時再處理。

## 使用方式（進階：命令列，逐一手動跑）

也可以不開儀表板、直接下指令跑（`app.py` 底層呼叫的也是同一套 `lib/pipeline.py`，行為一致）：

1. `python 01_transcribe.py <影片檔名>` — 語音辨識轉逐字時間戳，輸出 `work/<集數>/transcript.json`
2. （可選）`python 02_picker_launch.py <集數>` — 開啟拖拉調整工具，設定字幕位置/寬度/字距，存成 `work/<集數>/style_override.json`；沒開這步就用 `config.py` 的預設值
3. `python 03_captions.py <集數>` — 匹配字幕，輸出 `output/<集數>_captioned.mp4`
4. `python 04_filler_detect.py <集數>` — 贅詞偵測，輸出 `work/<集數>/filler_review.json`
5. `python 04b_confirm_review.py <集數> --interactive`（或 `--approve 0,2` / `--approve-all` / `--approve-none`）— 確認要剪除的模糊詞，寫入 `work/<集數>/approved_cuts.json`
6. `python 05_jumpcut.py <集數>` — 套用跳剪，輸出 `output/<集數>_jumpcut.mp4`
7. `python 06_bumper_concat.py <集數> --brand default` — 套用片頭/片尾，輸出 `output/<集數>_final.mp4`

**注意順序**：若同時使用贅詞跳剪功能，跳剪必須在字幕匹配**之後**執行（`05_jumpcut.py` 預設會找 `output/<集數>_captioned.mp4` 當來源，沒有才退回原始檔）——字幕是逐格畫進畫面的，剪掉整段區間不影響剩下片段的字幕正確性，時間軸跟原始轉錄一致，所以直接在已匹配字幕的版本上跳剪是安全的；反過來若先跳剪、字幕匹配用的還是舊時間軸，才會對不上。

## 多案共用

品牌素材（片頭/片尾/LOGO/色票）放在 `brands/<客戶代號>/`，`06_bumper_concat.py --brand <代號>` 指定套用哪一份。新增客戶只要複製 `brands/_template/` 建新資料夾放素材，不需修改工具程式碼。

## 致謝 / References

字幕 ASS 樣式（白字黑框、置中靠底、字間距等參數概念）之手法參考自
[video-autopilot-kit](https://github.com/Hao0321/video-autopilot-kit)（MIT License）的公開實作；
本專案未複製其程式碼，字幕產生邏輯為獨立重寫。
