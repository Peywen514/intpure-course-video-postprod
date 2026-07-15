"""Phase 1a：語音辨識轉逐字時間戳。

用法: python 01_transcribe.py <input 資料夾下的檔名，例如 1-1-未上字幕.mp4> [集數名稱，預設抓檔名數字部分]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.pipeline import episode_name_from_filename, stage_transcribe


def main():
    if len(sys.argv) < 2:
        print("用法: python 01_transcribe.py <檔名> [集數名稱]")
        sys.exit(1)

    filename = sys.argv[1]
    episode = sys.argv[2] if len(sys.argv) > 2 else episode_name_from_filename(filename)

    print(f"[1/1] 轉錄 {filename} -> work/{episode}/transcript.json")
    result = stage_transcribe(episode, video_filename=filename)

    print(f"完成。時長={result['duration']:.1f}s 詞數={result['words']} 分段數={result['segments']}")
    print(f"輸出: {result['transcript_path']}")


if __name__ == "__main__":
    main()
