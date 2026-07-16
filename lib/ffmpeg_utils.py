"""ffmpeg/ffprobe 共用包裝。假設 ffmpeg/ffprobe 已在系統 PATH 上（見 README 環境需求）。"""

import json
import subprocess


def escape_filter_path(path):
    """把一個檔案系統路徑轉成可以塞進 ffmpeg filtergraph 選項值（例如 ass filter 的
    fontsdir=、filename=）的安全字串。

    ffmpeg filtergraph 語法把冒號當 key=value 的分隔符、反斜線當跳脫字元，Windows
    路徑（磁碟機代號冒號 + 反斜線目錄分隔）兩種都會踩到。查過官方文件（filtergraph
    escaping 有兩層：filter 選項值本身一層、外層 filter 描述再一層）、也用這台機器
    的真實中文路徑實測過，結論：反斜線先換成斜線（Windows 路徑用斜線一樣合法），
    磁碟機冒號要跳脫成「兩個反斜線 + 冒號」（\\\\:）才會被正確解析成一個完整值，
    只跳脫一次（\\:）或用單引號包起來實測都會解析失敗（"No option name near..."）。
    """
    return str(path).replace("\\", "/").replace(":", "\\\\:")


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
