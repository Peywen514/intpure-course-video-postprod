"""集中設定：字幕樣式預設值、贅詞清單、編碼參數、品牌路徑。"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
WORK_DIR = BASE_DIR / "work"
OUTPUT_DIR = BASE_DIR / "output"
BRANDS_DIR = BASE_DIR / "brands"
FONTS_DIR = BASE_DIR / "fonts"

DEFAULT_BRAND = "default"

# ASS 字幕樣式預設值（1920x1080 課程影片）。
# Fontname 集中在這裡，之後要換成其他可商用授權開源字體只改這一個值。
#
# 2026-07-16 改用隨repo打包的靜態字重版本（fonts/NotoSansTC-Bold.otf，見
# THIRD_PARTY_NOTICES.md），不再依賴系統安裝的可變字型：libass 在 Windows 上用
# DirectWrite 比對可變字型（一個檔案含所有粗細）的粗細時會選錯（實測會選到最細的
# Thin，不是 Bold: -1 要求的粗體），改用單一粗細的靜態字型檔可以避開這個問題，
# 且不用再依賴使用者電腦上剛好有沒有裝這個字型（也讓 Mac/Linux 一致）。
# lib/pipeline.py 的 stage_captions 呼叫 ffmpeg 時會用 fontsdir=FONTS_DIR 指定
# 去哪裡找這個字型檔。
# MarginV / MarginL / MarginR / Spacing / Fontsize 是 picker 工具可個別調整的欄位；
# 沒有 work/<episode>/style_override.json 時就用這組預設值。
CAPTION_STYLE = {
    "Name": "Cap",
    "Fontname": "Noto Sans TC",
    "Fontsize": 70,
    "PrimaryColour": "&H00FFFFFF",   # 白字
    "OutlineColour": "&H00000000",   # 純黑不透明描邊
    "BackColour": "&H00000000",
    "Bold": -1,
    "Italic": 0,
    "Underline": 0,
    "StrikeOut": 0,
    "ScaleX": 100,
    "ScaleY": 100,
    "Spacing": 2,       # 字間距，picker 可調
    "Angle": 0,
    "BorderStyle": 1,   # 1 = 真描邊（非底框）
    "Outline": 4,       # 2026-07-13 驗收：3px 在複雜背景下不夠清楚，調成 4
    "Shadow": 0,
    "Alignment": 2,     # 置中靠底
    "MarginL": 120,     # picker 可調（寬度）
    "MarginR": 120,     # picker 可調（寬度）
    "MarginV": 60,      # picker 可調（高度）
    "Encoding": 1,
}

PLAY_RES_X = 1920
PLAY_RES_Y = 1080

# Phase 2 贅詞跳剪：高信心自動剪 vs 只標記待人工確認
FILLER_AUTO_CUT = ["呃", "嗯", "啊", "欸"]
FILLER_FLAG_ONLY = ["那個", "這個", "就是", "然後"]
FILLER_CUT_PADDING_MS = 100  # 剪除前後緩衝，避免咬到相鄰字音

# Phase 2c 純安靜停頓偵測：跟上面的固定詞表比對是互補的偵測維度——這裡不管有沒有
# 講贅詞，只抓「音軌本身安靜超過門檻」的空檔（例如切換視窗、想接下來要點哪裡）。
# 技術手法：2026-07-14 起改用 auto-editor（開源剪輯工具，只借用它的偵測結果，不讓它
# 接管剪輯）當偵測引擎，環境沒裝/呼叫失敗時自動退回舊版 ffmpeg silencedetect 濾鏡
# 當 fallback（見 lib/silence_detect.py 開頭 docstring 的完整說明）。
SILENCE_MIN_DURATION_MS = 1500
# 依據：正常說話換氣的自然停頓多半 < 1 秒，螢幕錄影課程偶爾拉長到 1~1.2 秒也還算正常語氣；
# 抓 > 1.5 秒才夠保守，避免把正常語氣停頓誤判成「發呆空檔」。本機另一個專案
# video-autopilot-kit 的 delivery_qa.py 用同一套 silencedetect 手法抓「句間死空檔」時
# 也是用 1.5 秒當門檻，兩邊經驗一致。
SILENCE_NOISE_DB = -30
# 依據：ffmpeg silencedetect 官方文件範例常用的門檻值。螢幕錄影課程的麥克風/系統底噪
# 通常不會是錄音室等級的乾淨，門檻抓太嚴（例如 -50dB）容易把「還在講話但聲音小」誤判
# 成靜音；-30dB 是常見的折衷值。這個常數現在兩個引擎共用：auto-editor 走
# lib/silence_detect.py 的 _db_to_amplitude_ratio() 換算成它自己的線性 threshold
# 參數（amplitude = 10^(dB/20)），fallback 用的 ffmpeg silencedetect 直接吃 dB，
# 不用另外維護兩組門檻常數。
SILENCE_EDGE_IGNORE_SEC = 2.0
# 依據：影片開頭（錄影開場等待）與結尾（講完話但影片還沒切掉）的靜音是正常收尾，
# 不是「贅詞式空檔」，只處理片中內部的靜音區間（見規格邊界情況）。2 秒緩衝足夠涵蓋
# 一般開場/收尾等待，同時不會誤吃片頭片尾之後緊接的第一段/最後一段正常語音間的停頓。
SILENCE_KEEP_BUFFER_MS = 400
# 依據：保守剪法——偵測到的靜音區間不整段剪光，只剪中段，前後各留一半（200ms）當緩衝。
# 扣掉 FILLER_CUT_PADDING_MS（100ms）的剪輯咬字緩衝往外擴一次之後，仍會淨留約 200ms
# 的停頓感，讓剪完的片子還有一絲自然停頓，不會因為整段安靜全部剪光而讓畫面跳太快、
# 觀眾覺得突兀。

# 斷句品質控管（group_words 硬斷點若卡在下列情況，會往前回溯找上一個更合適的斷點；
# 找不到才 fallback 用原本的硬斷，見 lib/ass_builder.py 的 _eligible_break）。
# 參考手法：本機另一個專案 video-autopilot-kit 的 word_captions.py 也是用「回溯找合格
# 斷點」處理同樣的問題（TAIL_DANGLER_TOKENS / HEAD_DANGLERS / NEVER_SPLIT 的概念），
# 這裡是依我們自己的資料結構重新設計，不是照抄。

# 連接詞不留在行尾：硬斷點如果卡在這些詞後面（下一行接著講因果/轉折的下半句），
# 讀起來會斷得很怪，往前找上一個斷點。清單先列課程講解常見的因果/轉折/條件連接詞，
# 使用者之後可以自己擴充。
CONNECTIVE_WORDS = [
    "然後", "但是", "而且", "所以", "因為", "不過", "接著", "另外",
    "因此", "如果", "雖然", "雖說", "只是", "於是", "同時", "還有",
]

# 下一行開頭不要是這些虛詞：這些字通常是接在前一個字/詞後面的助詞，斷在它們前面
# 代表把一個詞或語氣硬生生切成上下兩行，讀起來會覺得上一行話沒講完。
HEAD_DANGLER_CHARS = set("了的地得着嗎呢吧啦喔耶")

# 不能斷開的詞（斷句硬斷點若剛好落在這些詞中間，視為腰斬複合詞/專有名詞，往前回溯找
# 更合適的斷點）。這份清單無法窮舉，先放 Excel / Office 課程常見的專有名詞當範例，
# 使用者可以自己再擴充：NEVER_SPLIT_TERMS.append("新詞")。
NEVER_SPLIT_TERMS = [
    "雲端", "試算表", "巨集", "樞紐分析表", "工作表", "活頁簿", "函式",
    "儲存格", "格式化", "下拉式選單", "快捷鍵", "簡報", "投影片",
]

# Phase 3 輸出自動 QA：取代/補強「verify_frames.py 手動一張一張抽幀看」的驗收方式。
# 動機：曾經真的發生過 pipeline 邏輯改壞、「完整版」最終輸出完全沒有字幕匹配成功，
# 靠人工手動抽幀才發現的事故；contact sheet 把全片抽幀拼成一張總覽圖，人一次看完，
# 不用像 verify_frames.py 那樣一張一張開檔案。

# 抽幀張數 / 網格排列：24 張排成 6x4，是「看得夠密（每張約略代表全片 1/24 的段落，
# 抓得到中段忘記匹配字幕之類的問題）」跟「總覽圖不會大到看不清楚每一格」之間的折衷值；
# 6x4 對應常見螢幕寬高比排版也剛好整除，之後要調密一點/鬆一點都可以直接改這幾個數字。
QA_CONTACT_SHEET_FRAMES = 24
QA_CONTACT_SHEET_COLS = 6
QA_CONTACT_SHEET_ROWS = 4
# 每格縮圖大小：16:9 對應課程影片本身的畫面比例（PLAY_RES_X/Y），維持不變形；
# 320x180 在 6x4 網格下總圖是 1920x720，肉眼看單格內容還夠清楚，檔案也不會太大。
QA_CONTACT_SHEET_CELL_W = 320
QA_CONTACT_SHEET_CELL_H = 180
# 跳過頭尾各 5%：沿用 verify_frames.py 既有的邏輯，避免抽到片頭/片尾常見的黑幀或
# 品牌轉場，那些畫面本來就不是要驗收的教學內容本身。
QA_CONTACT_SHEET_EDGE_SKIP_RATIO = 0.05

# 字幕對準抽驗（caption sync）：跟 SILENCE_MIN_DURATION_MS 等跳剪用的門檻是不同用途，
# 特意分開設常數，不共用——跳剪只想抓「夠長才值得剪」的停頓，這裡則是想抓「這句字幕
# 顯示的時間範圍內，音軌到底有沒有在講話」，所以门槛要抓得比跳剪敏感（更短的靜音也算），
# 且不忽略頭尾（片頭片尾的字幕如果對不準，一樣要抓出來，不該因為它在邊界就被跳過）。
QA_SYNC_SILENCE_MIN_DURATION_MS = 300
# 依據：字幕對準檢查不是「找該剪的贅詞停頓」，而是想知道字幕視窗裡有沒有任何一段
# 明顯的安靜，門檻放低一點（0.3 秒）比較容易抓到「時間軸對不準」的線索。
QA_SYNC_SILENCE_NOISE_DB = -30
# 依據：跟 SILENCE_NOISE_DB 用同一個折衷值（見上面說明），螢幕錄影課程的麥克風/系統
# 底噪通常不是錄音室等級，-30dB 是常見折衷，不用另外調。
QA_SYNC_SILENCE_EDGE_IGNORE_SEC = 0.0
# 依據：跳剪偵測要忽略片頭片尾正常的等待/收尾靜音，但這裡是「檢查字幕本身有沒有對準」，
# 就算是片頭片尾的字幕一樣要驗，不能因為它落在邊界就被濾掉。

# 字幕落在靜音區間的比例超過這個門檻 → 列為「待人工複查」的可疑字幕。
QA_CAPTION_SYNC_OVERLAP_THRESHOLD = 0.70
# 依據：規格要求「大部分（例如超過 70%）都落在靜音區間」；字幕本來就可能在講話前後
# 稍微提早/延後幾百毫秒顯示是正常的（不是每個字都精準卡在聲音起訖），只有「這句字幕
# 顯示的時間裡有 7 成以上根本沒聲音」才夠可疑，值得列出來讓人工複查，避免正常的
# 些微時間差被誤判成一堆假警報。

# ⚠️ 重要限制（務必寫在呼叫端的說明/docstring 裡，不要讓使用者誤以為這是絕對判定）：
# 這個檢查完全基於 ffmpeg silencedetect 的音量門檻，不是逐字語音辨識比對，安靜偵測
# 本身就可能有誤差（例如老師講話音量忽大忽小、環境噪音、BGM 蓋過人聲等），列出來的
# 「可疑字幕」只是輔助人工判斷的線索，不代表這句字幕真的對不準，也不會自動判定整支
# 影片「驗收失敗」。

# 畫幅比警示（Phase 6，2026-07-14 新增）：目前所有課程影片都是 1920x1080（16:9），字幕
# 樣式也是照這個比例調校的；ASS 字幕的 PlayResX/Y 會被 ffmpeg 自動等比例縮放對應到實際
# 畫面尺寸，所以「解析度變但畫幅比不變」不會跑版，不需要處理。只有畫幅比本身跟預設不同
# （4:3、超寬螢幕之類）才會讓字幕非等比拉伸——user 明確要求先不做裁切/信箱化，只要在
# 品質檢查加輕量警示即可（先防未然，真的遇到再決定裁切策略）。
QA_ASPECT_RATIO_TOLERANCE = 0.02
# 依據：允許 2% 的畫幅比誤差再判定為「不符」，避免正常的解析度捨入（例如 1920x1080 跟
# 1918x1080 這種編碼過程常見的微小差異）被誤判成警示。

# 字幕翻譯（Phase 4，2026-07-14 新增）：輸出跟原文同一組時間碼的 .srt，只換文字，
# 不燒錄進影片（呼應 docs/handbook_同類產品比較_HelloIrene.md 的市場掃描結論——這塊
# 是我方原本的功能缺口）。

# 引擎選 Google Cloud Translation API（不是 DeepL）：DeepL API Free 方案已經停止開放
# 新申請（只有舊帳號能繼續用），Google 的 500,000 字元/月免費額度目前仍開放新帳號註冊，
# 且沒有到期日；這個專案的用量（單集頂多幾千字）幾乎不會超出免費額度，是目前查到
# 費用最低的選項。之後如果要換/加引擎，在 lib/translate.py 的 _ENGINES 註冊新的
# _call_xxx() 函式，這裡改 TRANSLATE_ENGINE 即可切換，不用動 stage_translate 呼叫端。
TRANSLATE_ENGINE = "google"
TRANSLATE_SOURCE_LANG = "zh-TW"

# 目標語言清單：儀表板依這份清單、每個語言各自顯示一顆翻譯按鈕。之後要多開一個語言
# 直接在這裡加語言代碼（Google Translate 的 target 代碼，例如 "ja"、"ko"、"vi"）。
TRANSLATE_TARGET_LANGS = ["en"]

# 動態 B-Roll 生成（Phase 5，2026-07-14 新增，同日改走免費素材庫路線）：原本設想接生成式
# 圖像/影片 API（Stable Diffusion/Runway 之類）會持續燒錢，先只搭架構不接引擎；後來查到開源
# 專案 AI-B-roll（github.com/Anil-matcha/AI-B-roll，MIT）的做法是拿逐字稿關鍵字去免費圖庫
# 搜尋既有素材，不是生成全新畫面——改用 Pexels Video API（授權查證見 THIRD_PARTY_NOTICES.md：
# 允許商業用途，內容本身免標註，但 API 使用條款額外要求顯著連結回 Pexels），成本模型從
# 「持續燒生成式 API 額度」變成「近乎零成本的搜尋+下載」，courses 常見的通用場景 B-Roll
# （城市空拍、辦公室畫面等）用真實素材庫搜尋反而更實用。
BROLL_ENGINE = "pexels"

# 統一輸出編碼設定（匹配字幕、片頭尾 concat 都套用同一組，維持一致）
ENCODE_PRESET = {
    "video_codec": "libx264",
    "pix_fmt": "yuv420p",
    "audio_codec": "aac",
    "audio_rate": 48000,
    "audio_channels": 2,
}
