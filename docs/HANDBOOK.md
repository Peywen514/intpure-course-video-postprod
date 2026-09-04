# 課程影片後製工具 · HANDBOOK

> 動工前先讀這份，不用回頭問 user 已經拍板過的問題。README.md 是給「同事安裝/使用」看的，
> 這份是給接手開發/維護的人（含未來的 AI session）看的：架構、現況、踩坑、SOP。

## 這個 repo 是什麼、跟其他地方的關係

這是**真正分享給同事（Paggy）用的正式版本**。2026-07-15 從 `D:\本地端CLI\課程影片後製\`
（另一個開發者本機的 `local-cli-workspace` monorepo 底下）獨立 fork 出來，之後完全獨立演進，
功能已經遠超過那份原始版本。**之後任何開發都應該直接在這個 repo 進行**，不要跑去改
`local-cli-workspace` 裡那份舊的（那份已經停止跟這裡同步）。

帳號體系（2026-09-04 才理清楚，之前繞了不少冤枉路）：
- `intpure`：**個人帳號**，這個 repo 目前還掛在它底下。
- `Intpure22`：2026-09-04 新建的免費 GitHub **組織**，方便多人共編。跟 `intpure`
  是完全獨立的兩個帳號，**repo 沒有自動搬過去**，加入 `Intpure22` 成員也不會自動繼承
  `intpure` 底下 repo 的權限。
- 要讓某個帳號對這個 repo 有 push 權限：`intpure` 帳號登入 → repo Settings → Collaborators
  and teams → Add people。**加完不會立刻生效**，對方帳號要自己接受邀請才算數
  （`gh api user/repository_invitations` 列出待接受清單，`gh api --method PATCH
  user/repository_invitations/<id>` 接受；組織邀請則是 `gh api --method PATCH
  user/memberships/orgs/<org> -f state=active`）。
- repo 目前**沒有**轉移到 `Intpure22`，如果之後要做，是 repo Settings → Danger Zone →
  Transfer ownership，屬於還沒做的事，不是已經做完的。

## 分享/公開前檢查清單

README.md 已經有完整版，這裡只提醒：**這個 repo 平常設 private**，同事要 clone 前才暫時
轉 public，下載完記得改回來（`gh repo edit intpure/intpure-course-video-postprod
--visibility private`）。2026-09-04 發現的時候是 public 狀態（上次分享後忘記改回去），
之後每次開放前都要記得檢查、關閉時也要記得檢查。

## 架構重點

- `app.py`：純 stdlib `http.server`，`ThreadingHTTPServer`。自訂 `_serve_static()` 支援
  HTTP Range（含 `bytes=-N` 後綴範圍請求，處理 moov atom 在檔尾的邊界情況——一般錄影軟體
  輸出的原始檔常見這種結構，沒處理會讓 `<video>` 卡在 `readyState=0` 永遠載入不出來）。
- `dashboard.html`：側邊選單＋詳情頁版型，側邊選單用真的百分比進度條。全域工作佇列狀態列
  （2026-09-04 新增）：`start_job()` 用 `dedupe_key` 防止同一階段被連點疊加成重複工作
  （去重檢查跟建立工作**必須在同一段鎖裡**，分兩段鎖中間會有 race condition，2026-09-04
  code review 抓到過），`MAX_QUEUED_JOBS = 3` 是既有的佇列上限（滿了直接拒絕，不是排隊
  等），跟去重機制是互補、不是取代關係。所有非 exempt 的 POST 端點統一用
  `_is_safe_episode()`（`^[A-Za-z0-9_-]+$`）擋路徑穿越，新增不帶 `episode` 參數的端點
  （例如 `/api/queue_cancel`）記得加進 `_episode_exempt` 清單，不然會被誤擋
  （2026-09-04 踩過這個坑）。
- `caption_studio.html`（不是 `caption_editor.html`）：校對文字／調整字幕位置寬度（拖拉
  字幕框，來自原 `picker/index.html`）／套用字幕燒錄三個功能合併在同一頁。右側 icon-only
  直排按鈕。可自訂快捷鍵設定面板（`⌨️`，localStorage `caption_studio_keymap_v1`，用兩格
  下拉選單設定不用按鍵錄製；Ctrl+Z 復原／Ctrl+S 暫存是固定按鍵不能改）。每日首次自動彈窗
  的使用說明（`caption_studio_usage_hint_v1`，可勾不再提醒）。2026-09-04 新增：影片預覽
  框可**橫向**拖曳縮放（`resize:horizontal` + `aspect-ratio:16/9` 讓高度自動跟著算，
  **不能改成 `resize:both`**——這頁有字幕位置拖拉功能，`.stage` 的 `clientWidth`/
  `clientHeight` 被拿去算字幕框的像素位置換算，如果框變成非 16:9 會讓換算出現誤差）；
  版面切換（垂直／左右並排，`caption_studio_layout_v1`，圖示按鈕在右側 icon 列最下面）。
- 樣式參數（`MarginV`/`MarginL`/`MarginR`/`Spacing`/`Fontsize`/`Outline`）都是相對
  `PLAY_RES_X=1920`／`PLAY_RES_Y=1080` 算比例，不是絕對像素，跟 `.stage` 實際渲染尺寸
  無關——這是可以自由縮放預覽框不影響燒出來的字幕位置的根本原因。
- 品牌片頭/片尾管理：`brands/<代號>/`，`06_bumper_concat.py --brand <代號>` 指定套用。
  多客戶/多系列共用一套工具的機制，不用改程式碼，新增客戶只要複製資料夾改名。

## 已知缺口（誠實列出，不要假裝沒有）

- 儀表板沒有單集刪除功能（`local-cli-workspace` 那份本機版有做，這邊沒有，也沒有
  `_is_safe_episode` 防護可以參考——如果要移植過去記得順便補這層防護）。
- 佇列取消目前只能取消「還在排隊、還沒開始跑」的工作，正在跑的 ffmpeg/whisper 子行程
  沒有安全中止機制。
- README 裡「同事安裝三步驟」目前只在這台開發機器上實測過完整流程跑通，還沒有同事在
  自己電腦上真的走過一輪（字型/防毒軟體攔截等環境差異風險未知）。

## 存檔 SOP

改完程式碼後：
1. `git status` 確認改動範圍，只 `add` 明確相關的檔案，不要 `-A`。
2. commit message 用 `feat:`/`fix:`/`chore:` 前綴 + 中文簡述。
3. `git push origin main` 前記得 `git fetch origin main` 確認沒有落後（多人共用的 repo，
   容易被別的 session 搶先推過）。
4. push 完用 `gh api repos/intpure/intpure-course-video-postprod/commits/main` 核對
   遠端真的收到，不要只看本機 push 指令沒報錯就當作完成。
