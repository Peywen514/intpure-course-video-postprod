"""ffmpeg/ffprobe 共用包裝。假設 ffmpeg/ffprobe 已在系統 PATH 上（見 README 環境需求）。"""

import json
import subprocess


def run(args, check=True, cwd=None):
    """跑一個 ffmpeg/ffprobe 命令，args 不含執行檔名本身（例如 ["ffmpeg", "-y", ...]）。"""
    result = subprocess.run(
        args, capture_output=True, encoding="utf-8", errors="replace", cwd=cwd
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr}"
        )
    return result


def probe(path):
    """回傳 ffprobe 的 JSON 結果（streams + format）。"""
    result = run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ]
    )
    return json.loads(result.stdout)


def duration_seconds(path):
    data = probe(path)
    return float(data["format"]["duration"])


def video_stream(path):
    data = probe(path)
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            return s
    return None
