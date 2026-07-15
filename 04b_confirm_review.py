"""Phase 2a.2：把 flagged（模糊詞）清單彙整呈現，問「是否確認剪除」，
經明確同意才寫進 work/<episode>/approved_cuts.json。沒過這關的項目永遠不會被剪。

三種用法：
1. 純檢視（不寫檔，安全預設）：
   python 04b_confirm_review.py <集數>
2. 互動逐筆確認（終端機跑，y/n/a=all/q=quit）：
   python 04b_confirm_review.py <集數> --interactive
3. 已經（例如透過對話）跟使用者確認過，直接指定要核准的項目編號（0-indexed，對應 flagged 清單順序）：
   python 04b_confirm_review.py <集數> --approve 0,2
   python 04b_confirm_review.py <集數> --approve-all
   python 04b_confirm_review.py <集數> --approve-none
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import WORK_DIR
from lib.pipeline import confirm_cuts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("episode")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--approve", default=None, help="逗號分隔的 flagged 清單編號")
    parser.add_argument("--approve-all", action="store_true")
    parser.add_argument("--approve-none", action="store_true")
    args = parser.parse_args()

    work_dir = WORK_DIR / args.episode
    review_path = work_dir / "filler_review.json"

    if not review_path.exists():
        print(f"找不到 {review_path}，先跑 04_filler_detect.py")
        sys.exit(1)

    review = json.loads(review_path.read_text(encoding="utf-8"))
    flagged = review["flagged"]

    if not flagged:
        print("沒有模糊詞待確認。")
        confirm_cuts(args.episode, [])
        return

    print(f"共 {len(flagged)} 筆模糊詞待確認是否剪除：\n")
    for idx, item in enumerate(flagged):
        print(f"  [{idx}] {item['start']:.2f}s  "
              f"{item['context_before']}【{item['word']}】{item['context_after']}")

    approved_indices = None

    if args.approve_all:
        approved_indices = list(range(len(flagged)))
    elif args.approve_none:
        approved_indices = []
    elif args.approve is not None:
        approved_indices = [int(x) for x in args.approve.split(",") if x.strip() != ""]
    elif args.interactive:
        approved_indices = []
        print("\n逐筆確認是否剪除（y=剪 / n=不剪 / a=全部剪 / q=其餘都不剪並結束）：")
        for idx, item in enumerate(flagged):
            while True:
                ans = input(f"  [{idx}] 【{item['word']}】剪除？(y/n/a/q): ").strip().lower()
                if ans == "y":
                    approved_indices.append(idx)
                    break
                if ans == "n":
                    break
                if ans == "a":
                    approved_indices.extend(range(idx, len(flagged)))
                    break
                if ans == "q":
                    break
                print("    請輸入 y/n/a/q")
            if ans == "q":
                break
    else:
        print("\n（未指定 --interactive / --approve / --approve-all / --approve-none，"
              "本次只是檢視，沒有寫入 approved_cuts.json。是否確認剪除？請明確指定上述其中一種方式。）")
        return

    approved = confirm_cuts(args.episode, approved_indices)
    print(f"\n已確認剪除 {len(approved)}/{len(flagged)} 筆，寫入 {work_dir / 'approved_cuts.json'}")


if __name__ == "__main__":
    main()
