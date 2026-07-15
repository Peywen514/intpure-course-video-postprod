# 同類產品比較｜Hello Irene（eleanorfilm.academy）

> 建立日期：2026-07-14
> 用途：與「課程影片後製」私人專案的功能對照 + 自建 vs 購買決策參考
> 來源：https://www.eleanorfilm.academy/hello-irene（早鳥預購頁，7/14–7/28，正式版 7/29 上線）

## 一、Hello Irene 是什麼

一套 **Claude Code skill 包**（不是獨立軟體）。官網明講「這套要搭配付費版的 Claude Code」
「直接動你電腦裡的檔案」，需要付費 Claude Pro/Max 帳號才能跑，不用寫程式、貼指令即可用。
透過「藍諾學院」課程平台販售，定位為「AI 影片後製團隊」，鎖定接案剪輯者、個人品牌經營者、
剛起步的自媒體新手。

**分工邏輯**：使用者只管「拍片、剪輯、發布」（創作/靈魂部分），雜務全部交給 Irene。

**定價**：
- 早鳥預購 NT$720（原價 NT$3,300），7/28 後漲價，正式版 7/29 上線
- 搭配剪輯課組合包 NT$3,330（原價 NT$6,630）
- 可選每月 NT$99 訂閱持續拿最新版（買斷版仍可永久使用舊版）

## 二、四大功能 vs 你的「課程影片後製」現況

| Hello Irene 功能 | 說明 | 你的專案現況 | 重疊程度 |
|---|---|---|---|
| 📝 字幕醫生 | 錯字/簡體轉繁體修正、也是翻譯師 | `caption_editor.html` 校對頁面 + `lib/glossary.py` 錯字詞庫（累積修正、自動套用、當 Whisper initial_prompt）；2026-07-14 起套用時機改到斷句前 | **高度重疊**，你的做法更細（連跨斷句邊界都處理過） |
| 🌏 字幕翻譯師 | 同一組時間碼換語言，翻譯濃縮不逐字，時間碼零位移 | 沒有 | **缺口**，目前完全沒有翻譯階段 |
| 🗂️ 素材整理師 | 整坨素材倒進來，逐支看過分類、附理由、絕不刪檔 | 沒有 | **缺口**，你的流程是從「已選定的單一影片」開始轉錄，沒有前置的多素材篩選/分類環節 |
| ✨ 動態 B-Roll 工作室 | 打一句話生動畫/圖（10 種風格 31 張模板），錄螢幕當 B-Roll | 沒有 | **缺口**，屬於生成式內容創作，跟「剪既有影片」方向不同 |
| （加碼）IG 帳號健檢 | 帳號健檢、內容發想、發布後成效分析 | 沒有 | 完全不同範疇，你的專案不碰發布後數據 |

**反過來看，你有但 Hello Irene 沒提到的**：
- 贅詞跳剪（呃/嗯/啊/欸自動剪，那個/這個/就是/然後標記待確認）
- 純安靜停頓跳剪（死空檔偵測）
- 片頭/片尾套用（多品牌 `brands/<代號>/` 架構）
- 輸出自動 QA（contact sheet 總覽圖 + 字幕對準抽驗）
- 拖拉調整字幕位置/寬度/字距（仿剪映）

這些屬於 Hello Irene 劃給「你自己剪」的範疇，它不碰。

## 三、技術路線差異

| | Hello Irene | 課程影片後製（你的專案） |
|---|---|---|
| 執行方式 | Claude Code skill，每次呼叫消耗付費 Claude 額度 | 本機常駐 Python + ffmpeg + faster-whisper，網頁儀表板 |
| 成本模型 | 持續耗用 LLM token（買斷/訂閱 + Claude 本身費用） | 一次性跑完，不持續耗 LLM |
| 客製化 | 別人寫的 prompt，無法照你的 `stage_*` pipeline 客製 | 邏輯集中在 `lib/pipeline.py`，可自由擴充 |
| 商業模式 | 已包裝成課程/工具在賣（NT$720 起） | 私人專案，目前不對外 |

## 四、自建 vs 購買：建議

- **字幕修正**：不用買，你已有更細的版本。
- **翻譯**：建議自己接。只是在既有 `segments_override.json`／ASS 時間碼上加一層 LLM 呼叫（丟給
  Claude API 或翻譯 API），比買現成包更貼合你的資料結構，前期工夫也不大。
- **素材整理、動畫/B-Roll 生成**：這兩塊較新，是唯一「買可能真的省事」的部分——但要注意
  Hello Irene 是 Claude Code skill，長期使用會持續耗你的 Claude 付費額度，跟你現在「跑一次
  ffmpeg 就結束」的成本模型不同。若要做，動畫生成那塊需要額外接生成式 API（Stable Diffusion/
  Runway 等），是目前唯一真正需要新技術投入的部分。

**結論**：720 元本身不是重點，會不會用得順手、能不能整合進你現有架構才是。傾向先自己把翻譯功能
補進 pipeline，素材整理/動畫生成視需求再評估要不要買或自建。

## 五、2026-07-14 執行進度

- [x] **翻譯功能**：已實作。`lib/translate.py`（Google Cloud Translation API，理由：DeepL API
  Free 方案已停止開放新申請，Google 500,000 字元/月免費額度仍開放新帳號）+ `stage_translate`
  + 儀表板 ⑨ 翻譯按鈕（依 `config.TRANSLATE_TARGET_LANGS` 動態產生）。核心邏輯（SRT 時間碼
  組裝、空字串跳過）`[unit-test]` 驗證過；實際打 API 那段還沒測，需要設定
  `GOOGLE_TRANSLATE_API_KEY` 後在儀表板跑一次才算完整驗證。
- [x] **動畫/B-Roll 生成**：先搭架構、不接真的生成引擎（user 明確要求，因為這塊會持續
  產生真正的 API 費用，不像翻譯有免費額度）。`lib/broll.py` 的 `_ENGINES` 刻意留空，
  `build_plan()` 只把使用者手動標記的時間點配上對應字幕文字組成建議 prompt，
  `generate_assets()` 呼叫會丟 `BRollError` 直到選定引擎。目前只有後端 API
  （`/api/broll/save_markers`、`/api/run/broll_plan`），**還沒有儀表板標記 UI**，
  之後要接引擎前得先補這塊。
- [x] **素材整理分類標準**：發去跨模型 red-team（codex/agy/Claude 三家獨立意見）問建議，
  三家高度共識，摘要如下（完整三方逐字紀錄見對話紀錄，未另存檔）：
  - **優先序共識**：技術中繼資料（ffprobe，零成本）→ 有聲/無聲/靜音區段（重用既有
    `lib/silence_detect.py`）→ 逐字稿/關鍵字（重用既有 faster-whisper 轉錄結果）→
    畫面來源類型（螢幕錄影 vs 講師鏡頭，中高成本）→ 內容主題分類（成本最高、最主觀，
    優先度最低）。
  - **NG/重錄判定必須維持這專案一貫的「高信心自動 vs 模糊標記待確認」兩層設計**（呼應
    `config.FILLER_AUTO_CUT` / `FILLER_FLAG_ONLY` 的模式），絕不能自動判定/刪除，只能標
    「疑似 NG，待人工確認」+ 理由 + 信心分數 + 時間碼。常見誤判：講師刻意重複強調重點
    會被誤判成重錄；無聲不等於廢片（可能是操作畫面/等待畫面）。
  - **絕不刪檔的落實方式**：分類結果只能是額外的標記/資料庫紀錄（或 JSON 清單），不能對
    `input/` 底下的實體檔案做搬移/改名/建捷徑——延續這個專案目前所有階段「只讀 input/、
    只寫 work/output/」的邊界。
  - **分歧點**：codex 額外提出「重複素材/相似 take 分組」「file-level vs segment-level
    分類」兩個我方跟 agy 沒特別強調的維度；agy 額外強調本機硬體資源限制（VRAM、降採樣
    處理、併發數限制）與檔案鎖定（File Lock）風險，並具體建議 CLIP 模型做螢幕錄影 vs
    講師鏡頭的 zero-shot 分類。
  - **目前狀態**：只有建議，**尚未動工**，需要再跟 user 確認要從哪個維度開始做（三家
    一致建議先做零成本的技術中繼資料 + 靜音偵測當 MVP 第一階段）。

- [ ] 若後續想同時走「販售課程/工具」路線，可參考 Hello Irene 的早鳥+訂閱定價模式

## 六、開源參考（2026-07-14 補查，只借手法不抄程式碼，比照 video-autopilot-kit/OpenCut-app 的先例）

user 問「這些應該都有開源專案可以參考，查了嗎」——一開始沒查就直接動工，這裡補上：

- **字幕翻譯**：多個開源 SRT 翻譯工具（[subtitle-translator](https://github.com/rockbenben/subtitle-translator)、
  [gemini-srt-translator](https://github.com/MaKTaiL/gemini-srt-translator)、
  [llm-subtrans](https://github.com/machinewrapped/llm-subtrans) 等）都採用「時間碼/編號在本機抽出，
  翻譯引擎只看純文字，翻完再重新組回時間碼」的手法——這點跟 `lib/translate.py` 已經獨立做的
  方式一致（`translate_texts()` 只丟純文字給引擎，時間碼由 `build_srt()` 事後套用），算是驗證了
  現有實作方向沒有繞遠路，不需要改架構。部分工具（如 better-ai-srt-translation）在用「一次丟多行
  給 LLM 對話式翻譯」時會用 marker 系統維持行對應——這個技巧目前用不到（Google Translate API
  的 `q` 陣列輸入本身就保證順序），但**如果之後 `TRANSLATE_ENGINE` 換成 LLM chat completion
  類引擎，這個 marker 手法會變成必要**，先記錄在這裡。

- **素材整理**：[video-analyzer](https://github.com/byjlw/video-analyzer)、
  [video-understanding-local](https://github.com/Grigorij-Dudnik/video-understanding-local)、
  [VideoHighlighter](https://github.com/Aseiel/VideoHighlighter) 這幾個開源專案都是「Whisper 轉錄
  + 本機視覺模型（Ollama 跑 SmolVLM2/YOLO/BLIP 之類）分析畫面 + LLM 生成摘要/描述性檔名」的組合，
  而且**都強調完全本機跑、不用雲端 API**——這跟 red-team 三家原本評估「視覺辨識這塊成本高、
  優先度低」的判斷有出入，**修正**：如果用本機 Ollama + 輕量視覺模型（跟 agy 建議的 CLIP
  是同個方向），畫面來源分類（螢幕錄影 vs 講師鏡頭）其實可以做到接近零雲端成本，只是吃本機
  運算資源（呼應 agy 提到的 VRAM/降採樣考量）。這幾個專案的「轉錄+視覺分析+生成描述性檔名」
  整體架構值得之後動工時直接參考。

- **B-Roll 生成**：查到 [AI-B-roll](https://github.com/Anil-matcha/AI-B-roll) 這個開源專案，**做法
  跟原本設想的「文字生圖/生動畫」完全不同**——它是用 Whisper 逐字稿抽關鍵字，去 Pexels（免費
  圖庫影片 API）搜尋、下載對應的真實素材庫 B-Roll 影片，不是用生成式 AI 產生全新畫面。
  **這個發現改變了原本的判斷，user 2026-07-14 已拍板改走這個方向並確認 Pexels 授權**：
  查證 [Pexels License](https://www.pexels.com/license/) + [API 使用條款](https://www.pexels.com/api/documentation/)——
  內容本身允許商業用途、免標註；但 **API 使用條款額外要求顯著連結回 Pexels**（跟內容授權是
  分開的規定），發布最終影片時要在說明欄/致謝名單附上；速率限制 200 次/小時、20,000 次/月，
  個人專案用量遠低於此門檻。已實作：`config.BROLL_ENGINE = "pexels"`、`lib/broll.py` 的
  `_call_pexels()`（查詢 Pexels Video API、下載最接近 1920x1080 的檔案）、
  `stage_broll_generate`（讀 `broll_plan.json` 逐項下載到 `work/<episode>/broll/`）。
  核心邏輯（`build_plan` 時間重疊比對、`generate_assets` 空 prompt 跳過/缺金鑰報錯）
  `[unit-test]` 驗證過；實際打 Pexels API 那段還沒測，需要你申請 `PEXELS_API_KEY`
  （[pexels.com/api](https://www.pexels.com/api/) 免費）後跑一次才算完整驗證。
  **還沒做的部分**：儀表板標記 UI（目前只有後端 API `/api/broll/save_markers`、
  `/api/run/broll_plan`、`/api/run/broll_generate`，沒有讓使用者在網頁上標記時間點的介面）。

  Sources: [subtitle-translator](https://github.com/rockbenben/subtitle-translator) ·
  [gemini-srt-translator](https://github.com/MaKTaiL/gemini-srt-translator) ·
  [video-analyzer](https://github.com/byjlw/video-analyzer) ·
  [video-understanding-local](https://github.com/Grigorij-Dudnik/video-understanding-local) ·
  [AI-B-roll](https://github.com/Anil-matcha/AI-B-roll)
