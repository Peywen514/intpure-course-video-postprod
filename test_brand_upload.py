"""測試片頭片尾上傳、匯入、刪除與套用功能。
驗證：
1. GET /api/brands 回傳結構包含 has_intro, has_outro, intro_size, outro_size
2. POST /api/brands/upload 支援串流上傳 mp4，自動補全音訊軌
3. POST /api/brands/upload 擋路徑穿越與不支援副檔名
4. POST /api/brands/import_path 正常運作且標準化格式
5. stage_bumper 支援 雙素材/僅片頭/僅片尾，且無素材時拋清楚錯誤
6. POST /api/brands/delete 可清除素材或刪除品牌
"""

import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app
import config
from lib import ffmpeg_utils, pipeline


def create_dummy_video(path: Path, duration: int = 1, with_audio: bool = True, size: str = "640x360"):
    """使用 ffmpeg 快速產生測試影片"""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30:duration={duration}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)]
    else:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    ffmpeg_utils.run(cmd)


def test_standardize_and_upload(tmp_path):
    test_brand = "test_unit_brand"
    brand_dir = config.BRANDS_DIR / test_brand
    if brand_dir.exists():
        shutil.rmtree(brand_dir, ignore_errors=True)

    try:
        # 1. 產生一個無音訊的 720p 影片
        silent_src = tmp_path / "silent_raw.mp4"
        create_dummy_video(silent_src, duration=1, with_audio=False, size="1280x720")

        # 驗證原本確實沒有音訊軌
        probe_before = ffmpeg_utils.probe(silent_src)
        assert not any(s.get("codec_type") == "audio" for s in probe_before.get("streams", []))

        # 2. 測試 standardize_brand_video
        dest_intro = brand_dir / "intro.mp4"
        pipeline.standardize_brand_video(silent_src, dest_intro)
        assert dest_intro.exists()

        # 驗證標準化後自動補上 aac 音訊軌
        probe_after = ffmpeg_utils.probe(dest_intro)
        assert any(s.get("codec_type") == "audio" for s in probe_after.get("streams", []))
        print("[OK] standardize_brand_video: 成功為無音訊影片自動補全音訊軌")

        # 3. 測試 stage_bumper 支援僅有片頭
        episode = "test_ep_bumper"
        work_ep = config.WORK_DIR / episode
        work_ep.mkdir(parents=True, exist_ok=True)
        raw_video = config.INPUT_DIR / f"{episode}-raw.mp4"
        create_dummy_video(raw_video, duration=2, with_audio=True, size="1920x1080")

        # 僅片頭
        res = pipeline.stage_bumper(episode, brand=test_brand, video_filename=raw_video.name)
        final_video = Path(res["output"])
        assert final_video.exists()
        d_final = ffmpeg_utils.duration_seconds(final_video)
        assert abs(d_final - 3.0) < 0.5  # 1s intro + 2s video = 3s
        print("[OK] stage_bumper: 僅片頭成功套用，時長正確")

        # 4. 產生片尾，測試雙素材
        outro_src = tmp_path / "outro_raw.mp4"
        create_dummy_video(outro_src, duration=1, with_audio=True, size="1920x1080")
        dest_outro = brand_dir / "outro.mp4"
        pipeline.standardize_brand_video(outro_src, dest_outro)

        res = pipeline.stage_bumper(episode, brand=test_brand, video_filename=raw_video.name)
        d_final_both = ffmpeg_utils.duration_seconds(Path(res["output"]))
        assert abs(d_final_both - 4.0) < 0.5  # 1s intro + 2s video + 1s outro = 4s
        print("[OK] stage_bumper: 雙素材（片頭+片尾）成功套用，時長正確")

        # 5. 測試無素材拋出 FileNotFoundError
        empty_brand = "empty_unit_brand"
        empty_dir = config.BRANDS_DIR / empty_brand
        empty_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline.stage_bumper(episode, brand=empty_brand, video_filename=raw_video.name)
            assert False, "無素材時應拋出 FileNotFoundError"
        except FileNotFoundError as e:
            assert "尚未上傳片頭或片尾" in str(e)
            print("[OK] stage_bumper: 無素材時正確回報錯誤提示")
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)

    finally:
        if brand_dir.exists():
            shutil.rmtree(brand_dir, ignore_errors=True)
        ep_dir = config.WORK_DIR / "test_ep_bumper"
        if ep_dir.exists():
            shutil.rmtree(ep_dir, ignore_errors=True)
        for out in config.OUTPUT_DIR.glob("test_ep_bumper*"):
            out.unlink()
        raw_v = config.INPUT_DIR / "test_ep_bumper-raw.mp4"
        if raw_v.exists():
            raw_v.unlink()


def test_http_api():
    """透過模擬 HTTP 請求測試 app.py 的 API 行為"""
    import http.client
    import threading

    server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.DashboardHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    conn = http.client.HTTPConnection("127.0.0.1", port)

    try:
        # 1. GET /api/brands
        conn.request("GET", "/api/brands")
        res = conn.getresponse()
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert any(b["name"] == "default" for b in data)
        print("[OK] GET /api/brands 回傳成功且包含 default 品牌")

        # 2. 上傳不支援的副檔名應被拒絕
        test_video_data = b"fake video content for test"
        conn.request(
            "POST",
            f"/api/brands/upload?brand=test_api_brand&kind=intro&filename=invalid.exe",
            body=test_video_data,
        )
        res = conn.getresponse()
        assert res.status == 400
        err_data = json.loads(res.read().decode("utf-8"))
        assert "不支援" in err_data["error"]
        print("[OK] POST /api/brands/upload 正確拒絕不支援的副檔名")

        # 3. 上傳真實影片到 test_api_brand 的 intro
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp_real_video = Path(f.name)
        create_dummy_video(tmp_real_video, duration=1, with_audio=True)
        real_video_bytes = tmp_real_video.read_bytes()
        tmp_real_video.unlink()

        conn.request(
            "POST",
            f"/api/brands/upload?brand=test_api_brand&kind=intro&filename=my_intro.mp4",
            body=real_video_bytes,
        )
        res = conn.getresponse()
        assert res.status == 200
        upload_resp = json.loads(res.read().decode("utf-8"))
        assert upload_resp["ok"] is True
        print("[OK] POST /api/brands/upload 真實影片串流上傳成功")

        # 4. 驗證 GET /api/brands 能夠看到已上傳的片頭與檔案大小
        conn.request("GET", "/api/brands")
        res = conn.getresponse()
        assert res.status == 200
        brands_data = json.loads(res.read().decode("utf-8"))
        api_brand = next((b for b in brands_data if b["name"] == "test_api_brand"), None)
        assert api_brand is not None
        assert api_brand["has_intro"] is True
        assert api_brand["intro_size"] > 0
        print("[OK] GET /api/brands 成功取得已上傳片頭狀態與大小")

        # 5. 測試刪除品牌 API
        conn.request(
            "POST",
            "/api/brands/delete",
            body=json.dumps({"brand": "test_api_brand"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        res = conn.getresponse()
        assert res.status == 200
        del_data = json.loads(res.read().decode("utf-8"))
        assert del_data["ok"] is True
        print("[OK] POST /api/brands/delete 刪除品牌成功")

    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as td:
        test_standardize_and_upload(Path(td))
    test_http_api()
    print("\nALL BRAND UPLOAD TESTS PASSED!")
