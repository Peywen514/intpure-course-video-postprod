"""煙霧測試：2026-07-21 whisper 幻覺標記補層（只標記不刪除，見 lib/whisper_transcribe.py
flagged_ranges 的說明與 memory course-video-postprod-tool.md 07-20/07-21 段）。
assert-based，跑法：python test_hallucination_flag_2026-07-21.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import pipeline, whisper_transcribe


def test_flagged_ranges_filters_by_threshold():
    transcript = {
        "segments": [
            {"start": 0.0, "end": 2.0, "no_speech_prob": 0.02},
            {"start": 2.0, "end": 5.0, "no_speech_prob": 0.91},
            {"start": 5.0, "end": 8.0, "no_speech_prob": None},
            {"start": 8.0, "end": 9.0},  # 舊快取缺欄位，視同沒有值
        ]
    }
    ranges = whisper_transcribe.flagged_ranges(transcript)
    assert ranges == [(2.0, 5.0)], f"只有超過預設閾值 0.8 的那段該被標記，實際: {ranges}"

    ranges_loose = whisper_transcribe.flagged_ranges(transcript, threshold=0.01)
    assert ranges_loose == [(0.0, 2.0), (2.0, 5.0)], f"降低閾值應多抓到一段: {ranges_loose}"
    print("OK: flagged_ranges 依閾值篩選，忽略缺欄位/None ->", ranges)


def test_get_caption_events_marks_overlap(tmp_path):
    work_dir = tmp_path / "2-11"
    work_dir.mkdir()
    (work_dir / "transcript.json").write_text(
        json.dumps({
            "duration": 10.0, "language": "zh", "words": [],
            "segments": [
                {"start": 0.0, "end": 3.0, "text": "正常語音", "no_speech_prob": 0.03},
                {"start": 3.0, "end": 6.0, "text": "疑似雜訊", "no_speech_prob": 0.85},
            ],
        }),
        encoding="utf-8",
    )
    (work_dir / "segments_override.json").write_text(
        json.dumps([
            {"start": 0.0, "end": 2.5, "text": "第一句"},
            {"start": 3.2, "end": 5.0, "text": "第二句"},
        ]),
        encoding="utf-8",
    )
    old_work_dir = pipeline.WORK_DIR
    pipeline.WORK_DIR = tmp_path
    try:
        events = pipeline.get_caption_events("2-11")
    finally:
        pipeline.WORK_DIR = old_work_dir

    assert events[0]["suspected_hallucination"] is False, "第一句時間沒重疊到疑似段落"
    assert events[1]["suspected_hallucination"] is True, "第二句落在 no_speech_prob>0.8 的區間內"
    print("OK: get_caption_events 依時間重疊標記 suspected_hallucination ->",
          [e["suspected_hallucination"] for e in events])


def test_get_caption_events_missing_transcript_does_not_crash(tmp_path):
    work_dir = tmp_path / "2-11"
    work_dir.mkdir()
    (work_dir / "segments_override.json").write_text(
        json.dumps([{"start": 0.0, "end": 1.0, "text": "句子"}]), encoding="utf-8",
    )
    old_work_dir = pipeline.WORK_DIR
    pipeline.WORK_DIR = tmp_path
    try:
        events = pipeline.get_caption_events("2-11")
    finally:
        pipeline.WORK_DIR = old_work_dir
    assert events[0]["suspected_hallucination"] is False, "缺 transcript.json 時不該當機，一律不標記"
    print("OK: 缺 transcript.json 時 get_caption_events 不當機，不標記")


if __name__ == "__main__":
    import tempfile

    test_flagged_ranges_filters_by_threshold()
    with tempfile.TemporaryDirectory() as d1:
        test_get_caption_events_marks_overlap(Path(d1))
    with tempfile.TemporaryDirectory() as d2:
        test_get_caption_events_missing_transcript_does_not_crash(Path(d2))
    print("\nALL SMOKE TESTS PASSED")
