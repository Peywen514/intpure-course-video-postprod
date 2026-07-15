"""Phase 2a：贅詞偵測。讀 transcript.json，不重跑轉錄。

用法: python 04_filler_detect.py <集數>
輸出 work/<集數>/filler_review.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.pipeline import stage_filler_detect


def main():
    if len(sys.argv) < 2:
        print("用法: python 04_filler_detect.py <集數>")
        sys.exit(1)

    episode = sys.argv[1]
    result = stage_filler_detect(episode)

    print(f"高信心自動剪：{len(result['auto_cut'])} 筆")
    for item in result["auto_cut"]:
        print(f"  [{item['start']:.2f}-{item['end']:.2f}] {item['word']}")

    print(f"\n模糊詞待確認：{len(result['flagged'])} 筆")
    for item in result["flagged"]:
        print(f"  [{item['start']:.2f}-{item['end']:.2f}] "
              f"{item['context_before']}【{item['word']}】{item['context_after']}")

    print(f"\n下一步：python 04b_confirm_review.py {episode}")


if __name__ == "__main__":
    main()
