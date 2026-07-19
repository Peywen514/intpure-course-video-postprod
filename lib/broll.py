"""動態 B-Roll 生成：不是生成式 AI 產生全新畫面，而是拿字幕文字當關鍵字，去 Pexels
（免費圖庫影片 API）搜尋既有素材下載回來——手法參考自開源專案 AI-B-roll
（github.com/Anil-matcha/AI-B-roll，MIT License，只借「用逐字稿關鍵字查免費圖庫」這個
概念，未複製其程式碼）。

為什麼不接生成式 API（Stable Diffusion/Runway 之類）：那類引擎會持續產生真正的使用費用；
Pexels 授權查證過允許商業用途（見 THIRD_PARTY_NOTICES.md），成本模型是近乎零成本的
搜尋+下載，課程影片常見的通用場景 B-Roll（城市空拍、辦公室畫面等）用真實素材庫搜尋
反而更實用、更便宜。

架構跟 lib/pipeline.stage_broll_plan 分兩階段：使用者手動標記「這段需要補 B-Roll」
的時間點（機器不猜，人工標記——B-Roll 需求本來就是主觀判斷），工具讀那些標記 + 對應
時間範圍內的字幕文字組出搜尋關鍵字，去 Pexels 搜尋下載，不燒錄進影片、只是把素材放進
work/<episode>/broll/，使用者自己決定要不要剪進去。
"""

import json
import shutil
import urllib.error
import urllib.parse
import urllib.request

_PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"


class BRollError(RuntimeError):
    pass


def build_plan(markers, events):
    """markers: [{"start": float, "end": float, "note": str}, ...]（使用者手動標記）。
    events: [(start, end, text), ...]（跟 lib/pipeline._base_events 同格式的字幕斷句）。

    回傳規劃清單：每個標記配上重疊時間範圍內的字幕文字，當作 Pexels 搜尋關鍵字的起點
    （使用者之後可以自己改寫 suggested_prompt 再送進 generate_assets）。
    """
    plan = []
    for marker in markers:
        overlapping_text = " ".join(
            text for start, end, text in events
            if start < marker["end"] and end > marker["start"]
        )
        plan.append({
            "start": marker["start"],
            "end": marker["end"],
            "note": marker.get("note", ""),
            "suggested_prompt": overlapping_text,
            "engine": None,  # 尚未實際搜尋下載，generate_assets 跑過之後才會填入 "pexels"
        })
    return plan


def _call_pexels(prompt, api_key, dest_dir):
    """用 prompt 當關鍵字查 Pexels Video API，挑最接近 1920x1080 的畫質檔案下載到
    dest_dir，回傳素材資訊（含 Pexels 影片頁面連結，供之後在說明欄/致謝名單附上——
    Pexels API 使用條款要求顯著連結回 Pexels，這是內容授權之外的額外規定，見
    THIRD_PARTY_NOTICES.md）。
    """
    query = urllib.parse.quote(prompt)
    req = urllib.request.Request(
        f"{_PEXELS_SEARCH_URL}?query={query}&per_page=1&orientation=landscape",
        headers={"Authorization": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise BRollError(f"Pexels API 回應錯誤（HTTP {e.code}）：{detail}") from e
    except urllib.error.URLError as e:
        raise BRollError(f"Pexels API 連線失敗：{e.reason}") from e

    videos = body.get("videos", [])
    if not videos:
        raise BRollError(f"Pexels 找不到符合「{prompt}」的素材，換個描述再試")

    video = videos[0]
    files = video.get("video_files", [])
    if not files:
        raise BRollError(f"Pexels 影片 {video.get('id')} 沒有可下載的檔案")
    best = min(files, key=lambda f: abs((f.get("width") or 0) - 1920))

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"pexels_{video['id']}.mp4"

    result = {
        "path": str(dest_path),
        "source": "pexels",
        "pexels_video_id": video["id"],
        "pexels_url": video.get("url"),
    }
    if dest_path.exists():
        # 重跑不整批重新下載：這支素材已經下載過（同一個 Pexels 影片 id 檔名固定）。
        return result

    try:
        # urlretrieve 無 timeout 會無限掛住；改用 urlopen 顯式帶 timeout。
        with urllib.request.urlopen(best["link"], timeout=60) as resp, open(dest_path, "wb") as f:
            shutil.copyfileobj(resp, f)
    except urllib.error.URLError as e:
        raise BRollError(f"Pexels 素材下載失敗：{e.reason}") from e

    return result


_ENGINES = {"pexels": _call_pexels}


def generate_assets(plan, engine, dest_dir, api_key):
    """實際呼叫引擎搜尋下載素材。plan: build_plan() 的輸出（可先手動編輯 suggested_prompt
    再傳進來）。跳過 suggested_prompt 是空字串的項目（沒有對應字幕文字可當關鍵字，交給
    使用者自己補一句描述）。

    回傳跟 plan 對應、多了下載結果欄位的清單；每個項目仍保留 start/end/note，方便呼叫端
    對應回原本標記的時間點。
    """
    if engine not in _ENGINES:
        raise BRollError(f"不支援的 B-Roll 引擎：{engine}（目前已註冊：{', '.join(_ENGINES) or '無'}）")
    if not api_key:
        raise BRollError("缺少 Pexels API 金鑰，請設定環境變數 PEXELS_API_KEY")

    results = []
    for item in plan:
        prompt = item.get("suggested_prompt", "").strip()
        if not prompt:
            results.append({**item, "skipped": True, "reason": "沒有對應字幕文字可當搜尋關鍵字"})
            continue
        try:
            asset = _ENGINES[engine](prompt, api_key, dest_dir)
            results.append({**item, "engine": engine, **asset})
        except BRollError as e:
            # B4（2026-07-15 Fable5 審查）：單項失敗（例如查無結果）不能讓整批中止，
            # 否則前面已下載的項目連同這份 broll_assets.json 都不會落檔。
            results.append({**item, "skipped": True, "error": str(e)})
    return results
