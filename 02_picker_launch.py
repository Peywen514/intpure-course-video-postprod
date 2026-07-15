"""Phase 1b：啟動字幕位置/寬度/字距拖拉調整工具。

用法: python 02_picker_launch.py <集數，例如 1-1> [port，預設 8765]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import INPUT_DIR
from picker.serve import run


def find_input_video(episode):
    candidates = list(INPUT_DIR.glob(f"{episode}-*")) + list(INPUT_DIR.glob(f"{episode}.*"))
    if not candidates:
        raise FileNotFoundError(f"找不到集數 {episode} 對應的 input 影片")
    return candidates[0]


def main():
    if len(sys.argv) < 2:
        print("用法: python 02_picker_launch.py <集數> [port]")
        sys.exit(1)

    episode = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765

    video_path = find_input_video(episode)
    video_relpath = f"input/{video_path.name}"

    run(episode, video_relpath, port=port)


if __name__ == "__main__":
    main()
