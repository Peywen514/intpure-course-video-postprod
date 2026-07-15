"""Phase 1c：字幕生成 + 匹配。

用法: python 03_captions.py <集數，例如 1-1> [來源影片檔名，預設沿用 01 轉錄時的原始檔]
讀 work/<集數>/transcript.json + work/<集數>/style_override.json（若存在）
輸出 work/<集數>/captions.ass 與 output/<集數>_captioned.mp4
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.pipeline import stage_captions


def main():
    if len(sys.argv) < 2:
        print("用法: python 03_captions.py <集數> [來源影片檔名]")
        sys.exit(1)

    episode = sys.argv[1]
    video_filename = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"[1/1] 匹配字幕 {episode}")
    if video_filename is None:
        print("（沒有 style_override.json 就用 config.py 預設樣式，有的話會套用）")
    result = stage_captions(episode, video_filename=video_filename)

    print(f"事件數: {result['events']}　套用 style_override: {result['style_override_used']}")
    print(f"完成: {result['output']}")


if __name__ == "__main__":
    main()
