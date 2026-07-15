"""Phase 2b：套用贅詞跳剪。只吃兩個來源：
- work/<episode>/filler_review.json 的 auto_cut（高信心，不需人工確認）
- work/<episode>/approved_cuts.json（4b 確認關卡同意的項目；不存在就當空清單）
filler_review.json 的 flagged 但未經 approved_cuts.json 核准的項目，這裡不會被讀到。

用法: python 05_jumpcut.py <集數> [來源影片檔名，預設用 input/ 裡對應集數的原始檔]
輸出 output/<集數>_jumpcut.mp4
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.pipeline import stage_jumpcut


def main():
    if len(sys.argv) < 2:
        print("用法: python 05_jumpcut.py <集數> [來源影片檔名]")
        sys.exit(1)

    episode = sys.argv[1]
    video_filename = sys.argv[2] if len(sys.argv) > 2 else None

    result = stage_jumpcut(episode, video_filename=video_filename)

    if result["skipped"]:
        print(f"{result['reason']}，不需要跳剪。")
        return

    print(f"剪除 {result['cut_ranges']} 個區間，共 {result['total_cut_seconds']:.2f}s")
    print(f"完成: {result['output']}")
    print(f"原始時長 {result['old_duration']:.2f}s -> 剪後 {result['new_duration']:.2f}s")


if __name__ == "__main__":
    main()
