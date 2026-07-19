"""煙霧測試：驗證 2026-07-19 修的 B2/B3/B4/B7 五處邏輯（B6 是純前端，人工開瀏覽器驗）。
不是完整測試框架，assert-based，跑法：python test_bugfixes_2026-07-19.py
"""

import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from lib import broll, pipeline, silence_detect, translate, whisper_transcribe
import app


def test_b2_filler_stripped_before_grouping(tmp_path):
    work_dir = tmp_path / "2-11"
    work_dir.mkdir()
    words = [
        {"word": "這", "start": 0.0, "end": 0.1, "prob": 1.0},
        {"word": "個", "start": 0.1, "end": 0.2, "prob": 1.0},
        {"word": "呃", "start": 0.2, "end": 0.3, "prob": 1.0},
        {"word": "重點", "start": 0.3, "end": 0.5, "prob": 1.0},
    ]
    (work_dir / "transcript.json").write_text(
        json.dumps({"duration": 1.0, "language": "zh", "segments": [], "words": words}),
        encoding="utf-8",
    )
    old_work_dir = pipeline.WORK_DIR
    pipeline.WORK_DIR = tmp_path
    try:
        events = pipeline._base_events("2-11")
    finally:
        pipeline.WORK_DIR = old_work_dir
    full_text = "".join(t for _, _, t in events)
    assert "呃" not in full_text, f"贅詞應已從字幕文字剔除，實際: {full_text!r}"
    assert "這個重點" in full_text
    print("B2 OK: filler token stripped from caption text ->", full_text)


def test_b3_translate_batches_over_128():
    calls = []

    def fake_engine(texts, target_lang, source_lang, api_key):
        calls.append(len(texts))
        return [f"[{t}]" for t in texts]

    old_engines = dict(translate._ENGINES)
    translate._ENGINES["fake"] = fake_engine
    try:
        texts = [f"line{i}" for i in range(250)]
        result = translate.translate_texts(texts, "en", "zh-TW", "fake", "key")
    finally:
        translate._ENGINES.clear()
        translate._ENGINES.update(old_engines)

    assert calls == [100, 100, 50], f"應分成 100/100/50 三批，實際: {calls}"
    assert len(result) == 250 and result[0] == "[line0]" and result[249] == "[line249]"
    print("B3 OK: 250 texts split into batches", calls)


def test_b4_broll_single_item_failure_does_not_abort_batch():
    def fake_engine(prompt, api_key, dest_dir):
        if prompt == "bad":
            raise broll.BRollError("找不到素材")
        return {"path": str(dest_dir / f"{prompt}.mp4"), "source": "fake"}

    old_engines = dict(broll._ENGINES)
    broll._ENGINES["fake"] = fake_engine
    try:
        plan = [
            {"start": 0, "end": 1, "suggested_prompt": "good1"},
            {"start": 1, "end": 2, "suggested_prompt": "bad"},
            {"start": 2, "end": 3, "suggested_prompt": "good2"},
        ]
        results = broll.generate_assets(plan, "fake", Path("/tmp/broll_test"), "key")
    finally:
        broll._ENGINES.clear()
        broll._ENGINES.update(old_engines)

    assert len(results) == 3, "單項失敗不該讓其餘項目消失"
    assert results[1]["skipped"] is True and "error" in results[1]
    assert results[0].get("path") and results[2].get("path")
    print("B4 OK: batch survives one failing item ->", [r.get("skipped") for r in results])


def test_b7_silence_edge_crossing_range_gets_clipped():
    def fake_raw_ranges(video_path, noise_db):
        # 跨越邊界的長靜音：1.9s 起、持續到 61.9s（edge_ignore=2.0，duration=100）
        return [(1.9, 61.9)]

    old_raw = silence_detect._raw_silence_ranges
    old_duration_fn = silence_detect.ffmpeg_utils.duration_seconds
    silence_detect._raw_silence_ranges = fake_raw_ranges
    silence_detect.ffmpeg_utils.duration_seconds = lambda video_path: 100.0
    try:
        kept = silence_detect.detect_silence(
            Path("fake.mp4"), min_duration_ms=1500, noise_db=-30, edge_ignore_sec=2.0
        )
    finally:
        silence_detect._raw_silence_ranges = old_raw
        silence_detect.ffmpeg_utils.duration_seconds = old_duration_fn

    assert kept == [(2.0, 61.9)], f"應裁掉邊界內的 0.1 秒，保留片中那段，實際: {kept}"
    print("B7 OK: edge-crossing silence clipped instead of dropped ->", kept)


def test_b7_safe_episode_rejects_traversal():
    assert app._is_safe_episode("2-11")
    assert not app._is_safe_episode("../../etc")
    assert not app._is_safe_episode("2-11/../../secret")
    assert not app._is_safe_episode("")
    print("B7 OK: _is_safe_episode rejects path traversal")


def test_b7_find_input_video_filters_non_video_extensions(tmp_path):
    (tmp_path / "2-11.txt").write_text("not a video")
    (tmp_path / "2-11-raw.mp4").write_bytes(b"fake")
    old_input_dir = pipeline.INPUT_DIR
    pipeline.INPUT_DIR = tmp_path
    try:
        found = pipeline.find_input_video("2-11")
    finally:
        pipeline.INPUT_DIR = old_input_dir
    assert found.name == "2-11-raw.mp4", f"應跳過 .txt，選到 .mp4，實際: {found}"
    print("B7 OK: find_input_video skips non-video files ->", found.name)


def test_b7_whisper_cache_hit_and_mismatch(tmp_path):
    out_json = tmp_path / "transcript.json"
    out_json.write_text(
        json.dumps({
            "duration": 10.0, "language": "zh", "model_size": "medium",
            "initial_prompt": "hint", "segments": [], "words": [],
        }),
        encoding="utf-8",
    )
    # 參數相符 -> 直接回傳快取，不呼叫 _get_model
    old_get_model = whisper_transcribe._get_model
    whisper_transcribe._get_model = lambda *a, **k: (_ for _ in ()).throw(AssertionError("不該重轉"))
    try:
        result = whisper_transcribe.transcribe(Path("fake.mp4"), out_json, model_size="medium", initial_prompt="hint")
    finally:
        whisper_transcribe._get_model = old_get_model
    assert result["model_size"] == "medium"

    # model_size 不同 -> 應該重轉（呼叫 _get_model）
    called = {}

    class _FakeModel:
        def transcribe(self, *a, **k):
            called["hit"] = True
            return types.SimpleNamespace(segments=[])

    whisper_transcribe._get_model = lambda *a, **k: _FakeModel()
    old_duration_fn = whisper_transcribe.ffmpeg_utils.duration_seconds
    whisper_transcribe.ffmpeg_utils.duration_seconds = lambda video_path: 10.0
    try:
        whisper_transcribe.transcribe(Path("fake.mp4"), out_json, model_size="large", initial_prompt="hint")
    finally:
        whisper_transcribe._get_model = old_get_model
        whisper_transcribe.ffmpeg_utils.duration_seconds = old_duration_fn
    assert called.get("hit"), "model_size 不符時應該重新轉錄，不能沿用舊快取"
    print("B7 OK: whisper cache respects model_size/initial_prompt")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d1:
        test_b2_filler_stripped_before_grouping(Path(d1))
    test_b3_translate_batches_over_128()
    test_b4_broll_single_item_failure_does_not_abort_batch()
    test_b7_silence_edge_crossing_range_gets_clipped()
    test_b7_safe_episode_rejects_traversal()
    with tempfile.TemporaryDirectory() as d2:
        test_b7_find_input_video_filters_non_video_extensions(Path(d2))
    with tempfile.TemporaryDirectory() as d3:
        test_b7_whisper_cache_hit_and_mismatch(Path(d3))
    print("\nALL SMOKE TESTS PASSED")
