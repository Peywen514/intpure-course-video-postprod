"""統一儀表板：列出 input/ 裡的集數與各階段完成狀態，用按鈕觸發轉錄/字幕位置調整/
字幕匹配/贅詞偵測與確認/跳剪/片頭尾套用。取代逐一手動下指令跑 01~06_*.py 的操作方式。

用法: python app.py [port，預設 8080]
"""

import json
import os
import queue
import re
import shutil
import sys
import threading
import uuid
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# HTML5 <video> 標籤載入大檔案時，瀏覽器一律會先送 Range 請求（只要 metadata/開頭幾段）
# 才能正常填 duration、支援拖拉進度條跳轉。Python 內建 SimpleHTTPRequestHandler 完全不
# 支援 Range（收到 Range header 一樣回整包 200），大一點的影片（測過 27MB 的課程影片）
# <video> 就會卡在 readyState=0 動不了——字幕校對頁面的「跟播捲動」看起來沒作用，
# 根本原因是影片自己就沒真的載入/播放，不是 JS 邏輯的問題。
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_STATIC_CHUNK = 1024 * 1024

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import (  # noqa: E402
    BRANDS_DIR,
    CAPTION_STYLE,
    DEFAULT_BRAND,
    INPUT_DIR,
    OUTPUT_DIR,
    TRANSLATE_TARGET_LANGS,
    WORK_DIR,
)
from lib.pipeline import (  # noqa: E402
    clear_all,
    confirm_cuts,
    get_caption_events,
    list_episodes,
    save_caption_corrections,
    save_caption_segments,
    save_manual_cuts,
    stage_bumper,
    stage_captions,
    stage_filler_detect,
    stage_jumpcut,
    stage_qa,
    stage_transcribe,
    stage_translate,
    save_broll_markers,
    stage_broll_plan,
    stage_broll_generate,
)

JOBS = {}
JOBS_LOCK = threading.Lock()

# 全部工作一律排隊、一次只跑一個：stage_transcribe 共用一個全域 faster-whisper
# 模型物件（見 lib/whisper_transcribe.py），沒驗證過並發呼叫是否安全；其他階段
# 雖然只是各自獨立的 ffmpeg subprocess，但同時開多支只會全部搶 CPU 編碼資源，
# 一起序列化處理最單純也最不會出錯。
JOB_QUEUE = queue.Queue()
JOB_ORDER_LOCK = threading.Lock()
JOB_ORDER = []  # 依排隊順序的 job_id，最前面那個是正在跑或即將跑的
MAX_QUEUED_JOBS = 3  # 公司 OA 機器規格有限，同時排隊工作數上限，超過要請使用者等前面跑完


def start_job(fn, *args, **kwargs):
    """回傳 job_id；佇列（含正在跑的那個）已達 MAX_QUEUED_JOBS 上限時回傳 None。"""
    with JOB_ORDER_LOCK:
        if len(JOB_ORDER) >= MAX_QUEUED_JOBS:
            return None
        job_id = uuid.uuid4().hex[:8]
        JOB_ORDER.append(job_id)
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "queued", "message": "", "result": None}
    JOB_QUEUE.put((job_id, fn, args, kwargs))
    return job_id


def _job_worker_loop():
    while True:
        job_id, fn, args, kwargs = JOB_QUEUE.get()
        with JOBS_LOCK:
            JOBS[job_id] = {"status": "running", "message": "", "result": None}
        try:
            result = fn(*args, **kwargs)
            with JOBS_LOCK:
                JOBS[job_id] = {"status": "done", "message": "完成", "result": result}
        except Exception as e:  # noqa: BLE001
            with JOBS_LOCK:
                JOBS[job_id] = {"status": "error", "message": str(e), "result": None}
        with JOB_ORDER_LOCK:
            if job_id in JOB_ORDER:
                JOB_ORDER.remove(job_id)
        JOB_QUEUE.task_done()


threading.Thread(target=_job_worker_loop, daemon=True).start()


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def log_message(self, fmt, *args):
        pass

    # ---------- GET ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/":
            self.path = "/dashboard.html"
            return self._serve_static()

        if parsed.path == "/api/episodes":
            return self._send_json(list_episodes())

        if parsed.path == "/api/config":  # 儀表板依這份清單動態產生每個語言的翻譯按鈕
            return self._send_json({"translate_langs": TRANSLATE_TARGET_LANGS})

        if parsed.path == "/api/brands":  # 片頭/片尾品牌清單，套用片頭尾時選版本用
            brands = []
            if BRANDS_DIR.exists():
                for d in sorted(BRANDS_DIR.iterdir()):
                    if d.is_dir():
                        brands.append({
                            "name": d.name,
                            "has_intro": (d / "intro.mp4").exists(),
                            "has_outro": (d / "outro.mp4").exists(),
                        })
            return self._send_json(brands)

        if parsed.path == "/api/job":
            job_id = qs.get("id", [""])[0]
            with JOBS_LOCK:
                job = dict(JOBS.get(job_id, {"status": "unknown"}))
            if job.get("status") == "queued":
                with JOB_ORDER_LOCK:
                    job["position"] = JOB_ORDER.index(job_id) if job_id in JOB_ORDER else 0
            return self._send_json(job)

        if parsed.path == "/api/filler":
            episode = qs.get("episode", [""])[0]
            review_path = WORK_DIR / episode / "filler_review.json"
            approved_path = WORK_DIR / episode / "approved_cuts.json"
            jumpcut_path = OUTPUT_DIR / f"{episode}_jumpcut.mp4"
            out = (
                json.loads(review_path.read_text(encoding="utf-8"))
                if review_path.exists()
                else {"auto_cut": [], "flagged": []}
            )
            out["detected"] = review_path.exists()
            out["approved"] = (
                json.loads(approved_path.read_text(encoding="utf-8")) if approved_path.exists() else []
            )
            out["jumpcut_applied"] = jumpcut_path.exists()
            return self._send_json(out)

        if parsed.path == "/api/qa":  # ⑧ 品質檢查結果（qa_report.json，沒有就回空殼）
            episode = qs.get("episode", [""])[0]
            report_path = WORK_DIR / episode / "qa_report.json"
            if report_path.exists():
                return self._send_json(json.loads(report_path.read_text(encoding="utf-8")))
            return self._send_json({"contact_sheet": None, "suspects": []})

        if parsed.path == "/api/defaults":  # picker 工具用
            episode = qs.get("episode", [""])[0]
            return self._send_json(self._picker_state(episode))

        if parsed.path == "/api/events":  # 字幕校對頁面用
            episode = qs.get("episode", [""])[0]
            try:
                events = get_caption_events(episode)
            except FileNotFoundError as e:
                return self._send_json({"error": str(e)}, status=400)
            corrections_path = WORK_DIR / episode / "caption_corrections.json"
            corrections = {}
            if corrections_path.exists():
                corrections = json.loads(corrections_path.read_text(encoding="utf-8"))
            manual_cuts_path = WORK_DIR / episode / "manual_cuts.json"
            manual_cuts = []
            if manual_cuts_path.exists():
                manual_cuts = json.loads(manual_cuts_path.read_text(encoding="utf-8"))
            return self._send_json({"events": events, "corrections": corrections, "manual_cuts": manual_cuts})

        return self._serve_static()

    def _serve_static(self):
        """靜態檔案（HTML/JS/影片/圖片）：自己讀檔回應，支援 HTTP Range，取代
        SimpleHTTPRequestHandler 預設行為（不支援 Range，大檔案 <video> 會卡死）。
        找不到檔案（含目錄列表這種非檔案情況）退回原本的 super().do_GET() 處理。
        """
        file_path = self.translate_path(self.path)
        if not os.path.isfile(file_path):
            return super().do_GET()

        file_size = os.path.getsize(file_path)
        content_type = self.guess_type(file_path)
        range_header = self.headers.get("Range")

        if range_header:
            m = _RANGE_RE.match(range_header)
            if not m:
                return super().do_GET()  # 格式看不懂的 Range，交回預設行為保底
            start_str, end_str = m.group(1), m.group(2)
            if start_str == "" and end_str != "":
                # 後綴範圍 bytes=-N：「檔案最後 N bytes」，不是「從 0 到 N」。
                # 瀏覽器找不到檔頭的 moov box（這個專案的影片常見 moov 寫在檔尾，錄影軟體
                # 輸出的原始檔多半沒做 faststart）時，就是靠這種請求去抓檔尾 metadata，
                # 這裡如果誤判成從頭開始就會一直抓不到 moov，<video> 永遠卡在 readyState=0。
                suffix_len = int(end_str)
                start = max(0, file_size - suffix_len)
                end = file_size - 1
            else:
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else file_size - 1
                end = min(end, file_size - 1)
            if start > end or start >= file_size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.end_headers()
                return
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            self.end_headers()
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(_STATIC_CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(_STATIC_CHUNK)
                if not chunk:
                    break
                self.wfile.write(chunk)

    # ---------- POST ----------
    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        episode = qs.get("episode", [""])[0]

        if parsed.path == "/api/run/transcribe":
            return self._start_job_response(stage_transcribe, episode)

        if parsed.path == "/api/run/captions":
            return self._start_job_response(stage_captions, episode)

        if parsed.path == "/api/run/filler_detect":
            return self._start_job_response(stage_filler_detect, episode)

        if parsed.path == "/api/run/jumpcut":
            return self._start_job_response(stage_jumpcut, episode)

        if parsed.path == "/api/run/bumper":
            brand = qs.get("brand", [DEFAULT_BRAND])[0]
            return self._start_job_response(stage_bumper, episode, brand)

        if parsed.path == "/api/run/qa":  # ⑧ 品質檢查：一樣走 start_job 進佇列排隊
            return self._start_job_response(stage_qa, episode)

        if parsed.path == "/api/run/translate":  # ⑨ 字幕翻譯，lang 沒帶就用第一個設定值
            lang = qs.get("lang", [TRANSLATE_TARGET_LANGS[0]])[0]
            return self._start_job_response(stage_translate, episode, lang)

        # B-Roll 規劃階段（尚未接生成引擎、尚無儀表板 UI，先開 API 供之後的標記工具呼叫）
        if parsed.path == "/api/broll/save_markers":
            body = self._read_json_body()
            save_broll_markers(episode, body.get("markers", []))
            return self._send_json({"ok": True})

        if parsed.path == "/api/run/broll_plan":
            return self._start_job_response(stage_broll_plan, episode)

        if parsed.path == "/api/run/broll_generate":  # 實際去 Pexels 搜尋下載素材
            return self._start_job_response(stage_broll_generate, episode)

        if parsed.path == "/api/filler/confirm":
            body = self._read_json_body()
            approved = confirm_cuts(episode, body.get("approve", []))
            return self._send_json({"ok": True, "approved": len(approved)})

        if parsed.path == "/api/captions/save":  # 字幕校對頁面存修正（舊版，僅逐行改字未分句/合併時使用）
            body = self._read_json_body()
            save_caption_corrections(episode, body.get("corrections", {}))
            return self._send_json({"ok": True})

        if parsed.path == "/api/captions/save_segments":  # 字幕校對頁面存完整斷句（含分句/合併調整）
            body = self._read_json_body()
            save_caption_segments(episode, body.get("segments", []))
            return self._send_json({"ok": True})

        if parsed.path == "/api/captions/save_manual_cuts":  # 字幕校對頁面存手動框選的贅詞/口誤剪除清單
            body = self._read_json_body()
            save_manual_cuts(episode, body.get("cuts", []))
            return self._send_json({"ok": True})

        if parsed.path == "/api/clear_all":  # 清空 input/output/work，重新測試用
            with JOB_ORDER_LOCK:
                busy = len(JOB_ORDER) > 0
            if busy:
                return self._send_json({"error": "還有工作在跑/排隊中，等它結束再清除"}, status=409)
            clear_all()
            return self._send_json({"ok": True})

        if parsed.path == "/api/upload":  # 上傳原始影片到 input/
            filename = qs.get("filename", [""])[0]
            return self._handle_upload(filename)

        if parsed.path == "/api/brands/import_path":  # 從本機路徑複製片頭/片尾到 brands/<brand>/
            body = self._read_json_body()
            return self._handle_brand_import(
                body.get("brand", ""), body.get("kind", ""), body.get("source_path", "")
            )

        if parsed.path == "/api/save":  # picker 工具存 style_override.json
            body = self._read_json_body()
            # 只寫呼叫方實際有帶的欄位；舊版 picker/index.html 沒有 Fontsize 欄位，
            # 若照樣寫 null 進檔案，merge_style 會把 Fontsize 疊成 None，燒字幕時 ffmpeg 會噴錯。
            out = {
                k: body[k]
                for k in ("MarginV", "MarginL", "MarginR", "Spacing", "Fontsize")
                if k in body
            }
            episode_dir = WORK_DIR / episode
            episode_dir.mkdir(parents=True, exist_ok=True)
            (episode_dir / "style_override.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return self._send_json({"ok": True})

        self.send_error(404)

    def _handle_upload(self, filename):
        # 只取檔名部分，防止路徑穿越（../ 之類）；只允許常見影片副檔名
        safe_name = Path(filename).name
        if not safe_name or Path(safe_name).suffix.lower() not in {".mp4", ".mov", ".mkv", ".avi", ".m4v"}:
            return self._send_json({"error": "檔名或格式不支援"}, status=400)

        INPUT_DIR.mkdir(parents=True, exist_ok=True)
        dest = INPUT_DIR / safe_name

        length = int(self.headers.get("Content-Length", 0))
        remaining = length
        chunk_size = 1024 * 1024  # 1MB，串流寫檔避免大檔案整包吃進記憶體
        with open(dest, "wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(chunk_size, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)

        return self._send_json({"ok": True, "filename": safe_name, "size": length})

    def _handle_brand_import(self, brand, kind, source_path):
        # 這是純本機工具（server 只綁 127.0.0.1，沒有帳號驗證），跟其他階段一樣預設
        # 呼叫方是本人；brand 一樣只取檔名部分防路徑穿越，跟 _handle_upload 同一套做法。
        safe_brand = Path(brand).name.strip()
        if not safe_brand or kind not in ("intro", "outro"):
            return self._send_json({"error": "品牌名稱或類型不正確"}, status=400)

        # Windows「複製路徑」對檔案會自動加上一組雙引號，直接貼進輸入框會讓路徑字串
        # 多出頭尾的 " 字元、比對不到真實檔案，先剝掉頭尾引號再判斷。
        cleaned_path = source_path.strip().strip('"').strip("'")
        src = Path(cleaned_path)
        if src.is_dir():
            return self._send_json({
                "error": f"這是資料夾路徑，不是影片檔案：{cleaned_path}\n"
                         "請貼資料夾裡「實際那支影片檔」的完整路徑（要包含檔名跟副檔名，例如 "
                         f"{cleaned_path}\\outro.mp4），不是資料夾本身。"
            }, status=400)
        if not src.is_file():
            return self._send_json({"error": f"找不到檔案：{cleaned_path}"}, status=400)
        if src.suffix.lower() not in {".mp4", ".mov", ".mkv", ".avi", ".m4v"}:
            return self._send_json({"error": "檔案格式不支援"}, status=400)

        brand_dir = BRANDS_DIR / safe_brand
        brand_dir.mkdir(parents=True, exist_ok=True)
        dest = brand_dir / f"{kind}.mp4"
        shutil.copy2(src, dest)
        return self._send_json({"ok": True, "brand": safe_brand, "kind": kind})

    # ---------- helpers ----------
    def _picker_state(self, episode):
        override_path = WORK_DIR / episode / "style_override.json"
        transcript_path = WORK_DIR / episode / "transcript.json"
        state = {
            "defaults": {
                "MarginV": CAPTION_STYLE["MarginV"],
                "MarginL": CAPTION_STYLE["MarginL"],
                "MarginR": CAPTION_STYLE["MarginR"],
                "Spacing": CAPTION_STYLE["Spacing"],
                "Fontsize": CAPTION_STYLE["Fontsize"],
            },
            "override": None,
            "words": [],
        }
        if override_path.exists():
            state["override"] = json.loads(override_path.read_text(encoding="utf-8"))
        if transcript_path.exists():
            data = json.loads(transcript_path.read_text(encoding="utf-8"))
            state["words"] = data.get("words", [])
        return state

    def _start_job_response(self, fn, *args, **kwargs):
        job_id = start_job(fn, *args, **kwargs)
        if job_id is None:
            return self._send_json(
                {"error": f"目前已有 {MAX_QUEUED_JOBS} 個工作在排隊/執行中，等前面跑完再試"},
                status=409,
            )
        return self._send_json({"job_id": job_id})

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def _send_json(self, obj, status=200):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    url = f"http://127.0.0.1:{port}/"
    print(f"[app] 儀表板啟動: {url}")
    print("[app] 按 Ctrl+C 結束")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[app] 結束")
        server.shutdown()


if __name__ == "__main__":
    main()
