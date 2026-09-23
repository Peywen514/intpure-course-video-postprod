"""煙霧測試：驗證 2026-09-10 新增的螢幕錄影隱私清理功能（Feature 1）核心邏輯。
assert-based，全程 mock 掉 ffmpeg 呼叫（不需要真的裝 ffmpeg 也能跑）。
跑法：python test_privacy_clean_2026-09-10.py
"""

import os
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import pipeline


def test_find_input_video_prefers_privacy_clean(tmp_path):
    input_dir = tmp_path / "input"
    work_dir = tmp_path / "work"
    input_dir.mkdir()
    (input_dir / "2-11-raw.mp4").write_bytes(b"fake raw")

    old_input_dir, old_work_dir = pipeline.INPUT_DIR, pipeline.WORK_DIR
    pipeline.INPUT_DIR, pipeline.WORK_DIR = input_dir, work_dir
    try:
        # 還沒跑過隱私清理 -> 退回原始檔
        found = pipeline.find_input_video("2-11")
        assert found.name == "2-11-raw.mp4"

        # 跑過隱私清理 -> 優先用它
        clean_dir = work_dir / "2-11"
        clean_dir.mkdir(parents=True)
        (clean_dir / "privacy_clean.mp4").write_bytes(b"fake clean")
        found = pipeline.find_input_video("2-11")
        assert found.name == "privacy_clean.mp4"
    finally:
        pipeline.INPUT_DIR, pipeline.WORK_DIR = old_input_dir, old_work_dir
    print("find_input_video OK: 優先回傳 privacy_clean.mp4 ->", found)


def test_stage_privacy_clean_finds_raw_not_its_own_output(tmp_path):
    input_dir = tmp_path / "input"
    work_dir = tmp_path / "work"
    input_dir.mkdir()
    (input_dir / "2-11-raw.mp4").write_bytes(b"fake raw")
    clean_dir = work_dir / "2-11"
    clean_dir.mkdir(parents=True)
    # 模擬「已經跑過一次」的狀態，驗證重跑不會拿自己的輸出當來源
    (clean_dir / "privacy_clean.mp4").write_bytes(b"stale clean output")

    captured = {}

    def fake_run(args, check=True):
        captured["args"] = args
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)

    old_input_dir, old_work_dir = pipeline.INPUT_DIR, pipeline.WORK_DIR
    old_run = pipeline.ffmpeg_utils.run
    old_video_stream = pipeline.ffmpeg_utils.video_stream
    pipeline.INPUT_DIR, pipeline.WORK_DIR = input_dir, work_dir
    pipeline.ffmpeg_utils.run = fake_run
    pipeline.ffmpeg_utils.video_stream = lambda path: {"width": 1920, "height": 1080}
    try:
        result = pipeline.stage_privacy_clean("2-11", crop={"top": 40})
    finally:
        pipeline.INPUT_DIR, pipeline.WORK_DIR = old_input_dir, old_work_dir
        pipeline.ffmpeg_utils.run = old_run
        pipeline.ffmpeg_utils.video_stream = old_video_stream

    assert "2-11-raw.mp4" in result["source"], f"應該找原始檔而不是自己的舊輸出，實際: {result['source']}"
    in_idx = captured["args"].index("-i")
    assert "2-11-raw.mp4" in captured["args"][in_idx + 1]
    vf = captured["args"][captured["args"].index("-vf") + 1]
    assert vf == "crop=1920:1040:0:40,pad=1920:1080:0:40:black", f"crop+pad 濾鏡字串不符: {vf}"
    assert "-c:a" in captured["args"] and captured["args"][captured["args"].index("-c:a") + 1] == "copy"
    print("stage_privacy_clean OK: 找原始檔＋crop+pad補回原尺寸 ->", vf)


def test_stage_privacy_clean_rejects_all_zero_crop():
    try:
        pipeline.stage_privacy_clean("2-11", crop={"top": 0, "bottom": 0})
        raised = False
    except ValueError:
        raised = True
    assert raised, "四邊都是 0 應該直接報錯，不該默默跑一次沒意義的 ffmpeg"
    print("stage_privacy_clean OK: 四邊皆 0 時拒絕執行")


def test_stale_privacy_warning_only_fires_when_clean_is_newer(tmp_path):
    work_dir = tmp_path / "work"
    ep_dir = work_dir / "2-11"
    ep_dir.mkdir(parents=True)
    candidate = ep_dir / "captioned.mp4"
    candidate.write_bytes(b"fake captioned")

    old_work_dir = pipeline.WORK_DIR
    pipeline.WORK_DIR = work_dir
    try:
        # 沒有 privacy_clean.mp4 -> 不示警
        assert pipeline._stale_privacy_warning("2-11", candidate) is None

        # privacy_clean.mp4 比 candidate 舊 -> candidate 仍是乾淨的，不示警
        clean = ep_dir / "privacy_clean.mp4"
        clean.write_bytes(b"fake clean")
        os.utime(clean, (time.time() - 100, time.time() - 100))
        assert pipeline._stale_privacy_warning("2-11", candidate) is None

        # privacy_clean.mp4 比 candidate 新 -> candidate 是清理前產生的，該示警
        os.utime(clean, (time.time() + 100, time.time() + 100))
        warning = pipeline._stale_privacy_warning("2-11", candidate)
        assert warning is not None and "captioned.mp4" in warning
    finally:
        pipeline.WORK_DIR = old_work_dir
    print("_stale_privacy_warning OK: 只在 privacy_clean 比既有輸出新時示警 ->", warning)


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d1:
        test_find_input_video_prefers_privacy_clean(Path(d1))
    with tempfile.TemporaryDirectory() as d2:
        test_stage_privacy_clean_finds_raw_not_its_own_output(Path(d2))
    test_stage_privacy_clean_rejects_all_zero_crop()
    with tempfile.TemporaryDirectory() as d3:
        test_stale_privacy_warning_only_fires_when_clean_is_newer(Path(d3))

    print("\nALL SMOKE TESTS PASSED")
