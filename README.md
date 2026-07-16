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

## 同事安裝（3 步驟）

1. 裝 [Python 3.9+](https://www.python.org/downloads/)（安裝時記得勾選 "Add python.exe to PATH"）
2. 開命令提示字元，執行：
   ```bash
   git clone https://github.com/intpure/intpure-course-video-postprod.git
   cd intpure-course-video-postprod
   winget install Gyan.FFmpeg
   ```
3. 雙擊資料夾裡的 `啟動儀表板.bat`——第一次執行會自動安裝所需的 Python 套件（需要網路，約幾分鐘），之後每次雙擊直接開啟儀表板網頁

> ⚠️ 這個 repo 平常設為 private，同事要 clone 前需先暫時轉 public，下載完畢後記得改回來——完整判斷依據見下方「分享/公開前檢查清單」。

## 分享/公開前檢查清單

之後每次要開放這個 repo（暫時轉 public 給同事 clone，或其他分享方式）之前，照這份清單過一次：

1. **依賴授權都是寬鬆授權，程式碼本身可以分享**——`faster-whisper`／`stable-ts`／`auto-editor`／`torch`／`openai-whisper` 都是 MIT/Unlicense/Apache/BSD 這類允許自由散布、修改、商用的授權，沒有會強迫本專案程式碼也要開源的條款。完整清單見 `THIRD_PARTY_NOTICES.md`。
2. **FFmpeg（GPLv3）的限制範圍很窄，不影響分享程式碼**：只禁止「把 `ffmpeg.exe` 執行檔本身打包進安裝包/zip 發布」，不禁止分享「呼叫它的程式碼」。本專案本來就沒有夾帶 `ffmpeg.exe`（要求每台機器自行 `winget install`），所以這條不構成 repo 要保持 private 的理由。
3. **真正該保密的是內容/品牌素材，不是授權問題**：`brands/<客戶代號>/` 放的是實際課程內容片段或客戶品牌素材（LOGO、片頭尾影片），這些不是開源套件、沒有授權允許公開分享——開放存取前務必確認 `brands/` 底下沒有夾帶真實素材（`brands/default/` 平時應保持空白模板，細節見 `brands/default/README.md`）。
4. **API 金鑰一律走環境變數**（`GOOGLE_TRANSLATE_API_KEY`／`PEXELS_API_KEY`），不寫進程式碼或版控；分享前可用 `git grep -i "api_key\|secret\|password"` 掃一次確認沒有漏網的硬編碼金鑰。
5. **依賴版本已鎖定**（見 `requirements.txt`），保留可重現性；要升版本時記得重新走一次完整流程實測，並更新 `THIRD_PARTY_NOTICES.md` 對應的查證日期。
6. **公開完記得改回 private**：`gh repo edit intpure/intpure-course-video-postprod --visibility private`（或 GitHub 網頁 Settings → Danger Zone）。

## 使用方式（推薦：儀表板網頁）

1. **雙擊 `啟動儀表板.bat`**（或手動打 `python app.py`）— 會開一個黑色視窗＋自動跳出瀏覽器（預設 http://127.0.0.1:8080/）；不想用的時候關掉那個黑色視窗即可停止伺服器
2. 網頁最上方「選擇檔案」上傳要處理的原始影片（會自動存進 `input/`；也可以不透過網頁、直接把檔案手動複製進 `input/` 資料夾，效果一樣）
3. 網頁上針對每個集數依序點按鈕：① 開始轉錄 → ② 校對字幕（可略過，語音辨識偶爾會有錯字，開新分頁對照影片逐句修正）→ ③ 調整字幕位置（可略過）→ ④ 匹配字幕 → ⑤ 偵測贅詞 → 勾選要剪除的模糊詞按「確認送出」 → ⑥ 套用跳剪 → ⑦ 套用片頭尾 → ⑧ 品質檢查 → ⑨ 翻譯字幕（可略過，輸出跟原文同一組時間碼的 `.srt`，不燒錄進影片）
4. 每個階段完成的狀態會即時反映在集數卡片上的徽章；產出的影片可以直接在頁面上點連結播放或下載

不需要打指令、不需要知道背後跑的是哪支 Python 檔、也不用自己找資料夾複製檔案——雙擊 `.bat`、網頁上傳影片、點按鈕即可。

`啟動儀表板.bat` 會依序檢查 Python / ffmpeg 是否在 PATH 上；若 ffmpeg 不在 PATH，會改用萬用字元自動搜尋 winget 安裝的 `Gyan.FFmpeg` 資料夾（不寫死版本號，不同機器裝到不同 ffmpeg 版本也找得到）；若必要的 Python 套件（faster-whisper / stable-ts / auto-editor）還沒裝，第一次執行會自動 `pip install -r requirements.txt`。三項都找不到才會顯示對應的錯誤訊息並中止。**這幾個檢查/自動修復的邏輯已個別做過隔離測試**[unit-test]，但完整流程目前只在本機這台機器實測跑通過[manual-check]，還沒有同事在自己電腦上實際跑過一輪——第一次拿去給同事用時，建議在旁邊看著跑一次，確認沒有卡在環境差異（例如字型、防毒軟體攔截等）上。

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

品牌素材（片頭/片尾/LOGO/色票）放在 `brands/<客戶代號>/`，`06_bumper_concat.py --brand <代號>` 指定套用哪一份。`brands/default/` 預設是空白模板（放你的 `intro.mp4`/`outro.mp4` 即可生效），新增客戶只要複製整個資料夾改名，不需修改工具程式碼，細節見 `brands/default/README.md`。

## 致謝 / References

字幕 ASS 樣式（白字黑框、置中靠底、字間距等參數概念）之手法參考自
[video-autopilot-kit](https://github.com/Hao0321/video-autopilot-kit)（MIT License）的公開實作；
本專案未複製其程式碼，字幕產生邏輯為獨立重寫。
