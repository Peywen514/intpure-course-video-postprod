"""字幕位置/寬度/字距 拖拉調整工具 — 本機 HTTP server。

從專案根目錄起 server（讓網頁能用相對路徑抓 input/ 影片檔跟 work/<episode>/transcript.json），
並提供一個 /api/save 端點，把調整好的數值寫成 work/<episode>/style_override.json。
"""

import json
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import CAPTION_STYLE, WORK_DIR  # noqa: E402


class PickerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def log_message(self, fmt, *args):
        pass  # 安靜一點，不要洗畫面

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/defaults":
            qs = parse_qs(parsed.query)
            episode = qs.get("episode", [""])[0]
            self._send_json(self._load_state(episode))
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/save":
            qs = parse_qs(parsed.query)
            episode = qs.get("episode", [""])[0]
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")

            out = {
                "MarginV": body.get("MarginV"),
                "MarginL": body.get("MarginL"),
                "MarginR": body.get("MarginR"),
                "Spacing": body.get("Spacing"),
            }
            episode_dir = WORK_DIR / episode
            episode_dir.mkdir(parents=True, exist_ok=True)
            (episode_dir / "style_override.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"[picker] 已儲存 {episode}: {out}")
            self._send_json({"ok": True})
            return
        self.send_error(404)

    def _load_state(self, episode):
        override_path = WORK_DIR / episode / "style_override.json"
        transcript_path = WORK_DIR / episode / "transcript.json"
        state = {
            "defaults": {
                "MarginV": CAPTION_STYLE["MarginV"],
                "MarginL": CAPTION_STYLE["MarginL"],
                "MarginR": CAPTION_STYLE["MarginR"],
                "Spacing": CAPTION_STYLE["Spacing"],
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

    def _send_json(self, obj):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run(episode, video_relpath, port=8765, open_browser=True):
    server = ThreadingHTTPServer(("127.0.0.1", port), PickerHandler)
    url = f"http://127.0.0.1:{port}/picker/index.html?episode={episode}&video={video_relpath}"
    print(f"[picker] server 啟動: {url}")
    print("[picker] 調整完按網頁上的「儲存」按鈕即可寫入 style_override.json")
    print("[picker] 按 Ctrl+C 結束")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[picker] 結束")
        server.shutdown()
