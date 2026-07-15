"""Phase 3：套用片頭/片尾。多案共用：--brand 指定要套用哪個客戶的品牌素材，
實際素材路徑固定為 brands/<brand>/intro.mp4、brands/<brand>/outro.mp4。

用法: python 06_bumper_concat.py <集數> [--brand default] [來源影片檔名]
輸出 output/<集數>_final.mp4
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import DEFAULT_BRAND
from lib.pipeline import stage_bumper


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("episode")
    parser.add_argument("--brand", default=DEFAULT_BRAND)
    parser.add_argument("video", nargs="?", default=None)
    args = parser.parse_args()

    result = stage_bumper(args.episode, brand=args.brand, video_filename=args.video)

    print(f"來源: {result['source']}")
    print(f"完成: {result['output']}")


if __name__ == "__main__":
    main()
