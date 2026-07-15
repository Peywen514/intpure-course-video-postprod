"""共用驗收工具：從任一 mp4 抽幀存成 PNG，供快速視覺驗收（不用整支播放）。

用法: python verify_frames.py <影片路徑> --n 12 --out work/<episode>/frames [--times 20,60,100]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import ffmpeg_utils


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--n", type=int, default=12)
    parser.add_argument("--out", default=None)
    parser.add_argument("--times", default=None, help="逗號分隔的時間點（秒），指定的話忽略 --n 均分")
    args = parser.parse_args()

    video_path = Path(args.video)
    out_dir = Path(args.out) if args.out else video_path.parent / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = ffmpeg_utils.duration_seconds(video_path)

    if args.times:
        timestamps = [float(t) for t in args.times.split(",")]
    else:
        # 跳過頭尾各 5%，避免抽到片頭黑幀
        start = duration * 0.05
        end = duration * 0.95
        step = (end - start) / max(1, args.n - 1)
        timestamps = [start + i * step for i in range(args.n)]

    for t in timestamps:
        out_path = out_dir / f"frame_{t:.1f}s.jpg"
        ffmpeg_utils.run(
            [
                "ffmpeg", "-y", "-ss", str(t), "-i", str(video_path),
                "-frames:v", "1", "-q:v", "2", str(out_path),
            ]
        )
        print(out_path)


if __name__ == "__main__":
    main()
