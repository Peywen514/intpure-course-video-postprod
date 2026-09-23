"""煙霧測試：驗證 2026-09-10 新增的三項 QA 檢查（漏剪停頓/響度/閃爍）核心邏輯。
不是完整測試框架，assert-based，全程 mock 掉 ffmpeg 呼叫（不需要真的裝 ffmpeg 也能跑
這支測試；真實 ffmpeg 輸出格式已用 lib/pipeline.py stage_qa('2-11') 對真實素材跑過一次
驗證過，見 memory course-video-postprod-tool 2026-09-10 段）。
跑法：python test_qa_expansion_2026-09-10.py
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import quality_check


def test_check_dead_air_clips_asymmetric_start_and_tail():
    def fake_detect_silence(video_path, min_duration_ms, noise_db, edge_ignore_sec):
        assert edge_ignore_sec == 0.0, "check_dead_air 應自己做非對稱裁切，不靠 detect_silence 的對稱 edge_ignore"
        return [(1.0, 2.5), (3.0, 4.83), (169.5, 172.1)]

    old_detect = quality_check.detect_silence
    old_duration_fn = quality_check.ffmpeg_utils.duration_seconds
    quality_check.detect_silence = fake_detect_silence
    quality_check.ffmpeg_utils.duration_seconds = lambda video_path: 172.1
    try:
        result = quality_check.check_dead_air(
            Path("fake.mp4"), start_ignore_sec=3.002, min_duration_ms=1500, tail_ignore_sec=2.0
        )
    finally:
        quality_check.detect_silence = old_detect
        quality_check.ffmpeg_utils.duration_seconds = old_duration_fn

    assert result["gaps"] == [{"start": 3.0, "end": 4.83, "duration": 1.83}], (
        f"片頭前那段跟片尾裁掉後太短的那段都該被丟掉，只留片頭剛結束那個 1.83s 缺口，實際: {result['gaps']}"
    )
    print("dead_air OK: start/tail 非對稱裁切正確 ->", result["gaps"])


def test_check_loudness_only_warns_on_true_peak():
    fake_json = (
        '{\n\t"input_i" : "-21.67",\n\t"input_tp" : "%s",\n'
        '\t"input_lra" : "5.20",\n\t"input_thresh" : "-31.80"\n}\n'
    )

    def fake_run(args, check=True):
        tp = "-4.59" if "quiet.mp4" in args[2] else "-0.50"
        return types.SimpleNamespace(stdout="", stderr="banner text\n" + fake_json % tp, returncode=0)

    old_run = quality_check.ffmpeg_utils.run
    quality_check.ffmpeg_utils.run = fake_run
    try:
        quiet = quality_check.check_loudness(Path("quiet.mp4"))
        loud = quality_check.check_loudness(Path("clipping.mp4"))
    finally:
        quality_check.ffmpeg_utils.run = old_run

    assert quiet["measured"] and quiet["integrated_lufs"] == -21.67 and quiet["true_peak_dbtp"] == -4.59
    assert quiet["true_peak_warning"] is False, "True Peak -4.59 沒超標，不該示警"
    assert loud["true_peak_warning"] is True, "True Peak -0.50 超過 -1.0 上限，該示警"
    print("loudness OK: 只在 True Peak 超標時示警 ->", quiet, loud)


def test_detect_flash_merges_events_within_gap():
    yavgs = [100, 100, 100, 170, 175, 100, 100, 100, 100, 100]
    fake_stdout = "\n".join(f"lavfi.signalstats.YAVG={v:.6f}" for v in yavgs)

    def fake_run(args, check=True):
        return types.SimpleNamespace(stdout=fake_stdout, stderr="", returncode=0)

    old_run = quality_check.ffmpeg_utils.run
    quality_check.ffmpeg_utils.run = fake_run
    try:
        result = quality_check.detect_flash(
            Path("fake.mp4"), sample_fps=5, luma_delta_threshold=60, merge_gap_sec=1.0
        )
    finally:
        quality_check.ffmpeg_utils.run = old_run

    assert result["count"] == 1, f"0.4 秒內的兩次驟變應合併成一次閃爍事件，實際: {result['events']}"
    assert result["events"][0]["luma_delta"] == 75.0
    print("flash OK: 相鄰驟變合併成一次事件 ->", result["events"])


if __name__ == "__main__":
    test_check_dead_air_clips_asymmetric_start_and_tail()
    test_check_loudness_only_warns_on_true_peak()
    test_detect_flash_merges_events_within_gap()
    print("\nALL SMOKE TESTS PASSED")
