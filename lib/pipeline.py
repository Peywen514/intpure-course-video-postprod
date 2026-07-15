"""各階段的共用邏輯，供 CLI 腳本（01/03/04/05/06_*.py）與 app.py 儀表板共用呼叫。
不含互動輸入（confirm_cuts 直接吃 approve 名單，CLI 的互動問答留在 04b_confirm_review.py）。
"""

import json
import os
import shutil
from pathlib import Path

from config import (
    BRANDS_DIR,
    BROLL_ENGINE,
    CAPTION_STYLE,
    DEFAULT_BRAND,
    ENCODE_PRESET,
    FILLER_AUTO_CUT,
    FILLER_CUT_PADDING_MS,
    FILLER_FLAG_ONLY,
    INPUT_DIR,
    OUTPUT_DIR,
    PLAY_RES_X,
    PLAY_RES_Y,
    SILENCE_EDGE_IGNORE_SEC,
    SILENCE_KEEP_BUFFER_MS,
    SILENCE_MIN_DURATION_MS,
    SILENCE_NOISE_DB,
    TRANSLATE_ENGINE,
    TRANSLATE_SOURCE_LANG,
    WORK_DIR,
)
from lib import broll, ffmpeg_utils, glossary, quality_check, timeline, translate
from lib.ass_builder import build_ass, group_words, merge_style
from lib.filler_detect import detect
from lib.silence_detect import detect as detect_silence_cuts
from lib.whisper_transcribe import transcribe


def episode_name_from_filename(filename):
    stem = Path(filename).stem
    parts = stem.split("-")
    if len(parts) >= 2 and parts[0].isdigit():
        return f"{parts[0]}-{parts[1]}"
    return stem


def find_input_video(episode):
    candidates = list(INPUT_DIR.glob(f"{episode}-*")) + list(INPUT_DIR.glob(f"{episode}.*"))
    if not candidates:
        raise FileNotFoundError(f"找不到集數 {episode} 對應的 input 影片")
    return candidates[0]


def list_episodes():
    """掃 input/ 底下的影片，回傳每集的名稱與各階段完成狀態。"""
    episodes = {}
    for f in sorted(INPUT_DIR.glob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        ep = episode_name_from_filename(f.name)
        episodes.setdefault(ep, {"episode": ep, "video": f.name})

    result = []
    for ep, info in sorted(episodes.items()):
        work_dir = WORK_DIR / ep
        info["transcribed"] = (work_dir / "transcript.json").exists()
        info["style_adjusted"] = (work_dir / "style_override.json").exists()
        info["caption_reviewed"] = (
            (work_dir / "caption_corrections.json").exists()
            or (work_dir / "segments_override.json").exists()
        )
        info["captioned"] = (OUTPUT_DIR / f"{ep}_captioned.mp4").exists()
        info["filler_detected"] = (work_dir / "filler_review.json").exists()
        info["filler_confirmed"] = (work_dir / "approved_cuts.json").exists()
        info["jumpcut"] = (OUTPUT_DIR / f"{ep}_jumpcut.mp4").exists()
        info["final"] = (OUTPUT_DIR / f"{ep}_final.mp4").exists()
        info["qa_done"] = (work_dir / "qa_report.json").exists()
        # 翻譯完成的語言清單（檔名 <ep>_<lang>.srt），依實際存在的檔案反推，不是依
        # config.TRANSLATE_TARGET_LANGS 猜——這樣就算之後清單改了，舊集數已翻好的
        # 語言狀態也不會顯示錯。
        info["translated_langs"] = sorted(
            p.stem[len(ep) + 1:] for p in OUTPUT_DIR.glob(f"{ep}_*.srt")
        )
        if info["filler_detected"]:
            review = json.loads((work_dir / "filler_review.json").read_text(encoding="utf-8"))
            info["auto_cut_count"] = len(review.get("auto_cut", []))
            info["flagged_count"] = len(review.get("flagged", []))
        else:
            info["auto_cut_count"] = 0
            info["flagged_count"] = 0
        result.append(info)
    return result


def clear_all():
    """清空 input/、output/、work/ 底下所有內容，重新測試用。brands/ 品牌素材不受影響。
    連原始上傳影片一起刪，是不可逆動作，呼叫前務必在畫面上跟使用者二次確認。"""
    for d in (INPUT_DIR, OUTPUT_DIR, WORK_DIR):
        if d.exists():
            for child in d.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        d.mkdir(parents=True, exist_ok=True)


def stage_transcribe(episode, video_filename=None, model_size="medium"):
    video_path = INPUT_DIR / video_filename if video_filename else find_input_video(episode)
    out_json = WORK_DIR / episode / "transcript.json"
    prompt_hint = glossary.get_prompt_hint()
    result = transcribe(video_path, out_json, model_size=model_size, initial_prompt=prompt_hint)
    return {
        "duration": result["duration"],
        "words": len(result["words"]),
        "segments": len(result["segments"]),
        "transcript_path": str(out_json),
        "glossary_hint_used": prompt_hint,
    }


def _base_events(episode):
    """優先讀使用者在校對頁面存過的完整斷句（含分句/合併調整），沒有的話才用
    group_words 自動斷句。

    詞庫（已知常見錯字）修正的套用時機是「斷句之前」，對逐字資料操作
    （glossary.apply_glossary_to_words），不是舊版「斷句後對每行文字」——
    這樣詞庫裡跨越斷句邊界的多字詞修正也能生效，見 lib/glossary.py 開頭的說明。"""
    work_dir = WORK_DIR / episode
    segments_path = work_dir / "segments_override.json"
    if segments_path.exists():
        segments = json.loads(segments_path.read_text(encoding="utf-8"))
        return [(s["start"], s["end"], s["text"]) for s in segments]

    transcript_path = work_dir / "transcript.json"
    if not transcript_path.exists():
        raise FileNotFoundError(f"找不到 {transcript_path}，先跑轉錄")
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    fixed_words = glossary.apply_glossary_to_words(transcript["words"])
    return group_words(fixed_words)


def get_caption_events(episode):
    """回傳斷句分行後的字幕事件清單（給校對頁面顯示用，跟 stage_captions 用的是同一份斷句邏輯）。"""
    events = _base_events(episode)
    return [{"index": i, "start": s, "end": e, "text": t} for i, (s, e, t) in enumerate(events)]


def save_caption_corrections(episode, corrections):
    """corrections: {"<index>": "校正後文字", ...}。
    同時把「詞庫套用後的文字」跟「這次校正後的文字」的差異記進詞庫，供未來自動套用/提示轉錄。
    """
    base_events = _base_events(episode)
    for idx_str, corrected_text in corrections.items():
        idx = int(idx_str)
        if 0 <= idx < len(base_events):
            glossary.record_correction(base_events[idx][2], corrected_text)

    work_dir = WORK_DIR / episode
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "caption_corrections.json").write_text(
        json.dumps(corrections, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def save_caption_segments(episode, segments):
    """segments: [{"start": float, "end": float, "text": str}, ...]，依時間排序的完整字幕清單，
    校對頁面做過分句/合併調整後存這份「完整快照」取代原本純文字校正機制（分句/合併後原本的
    index 對不上，逐行 diff 沒有意義）。存過之後 _base_events 一律以這份為準，不再重跑
    group_words 自動斷句。

    只有「句數沒變」時才嘗試把文字差異記進詞庫（分句/合併後無法可靠對應回原句，略過學習）。
    """
    segments = sorted(segments, key=lambda s: s["start"])
    base_events = _base_events(episode)
    if len(base_events) == len(segments):
        for (_, _, original_text), seg in zip(base_events, segments):
            if seg["text"] != original_text:
                glossary.record_correction(original_text, seg["text"])

    work_dir = WORK_DIR / episode
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "segments_override.json").write_text(
        json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def stage_captions(episode, video_filename=None):
    work_dir = WORK_DIR / episode
    override_path = work_dir / "style_override.json"
    corrections_path = work_dir / "caption_corrections.json"
    segments_override_path = work_dir / "segments_override.json"
    ass_path = work_dir / "captions.ass"

    video_path = INPUT_DIR / video_filename if video_filename else find_input_video(episode)

    override = None
    if override_path.exists():
        override = json.loads(override_path.read_text(encoding="utf-8"))

    style = merge_style(CAPTION_STYLE, override)
    events = _base_events(episode)

    # segments_override 已經是最終文字（含分句/合併），不用再套一次舊版逐行校正；
    # 只有還停留在舊機制（沒分過句、只存過 caption_corrections.json）的集數才套用。
    if not segments_override_path.exists() and corrections_path.exists():
        corrections = json.loads(corrections_path.read_text(encoding="utf-8"))
        events = [
            (s, e, corrections.get(str(i), t))
            for i, (s, e, t) in enumerate(events)
        ]

    ass_content = build_ass(events, style, play_res=(PLAY_RES_X, PLAY_RES_Y))
    ass_path.write_text(ass_content, encoding="utf-8")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{episode}_captioned.mp4"

    ffmpeg_utils.run(
        [
            "ffmpeg", "-y", "-i", str(video_path.resolve()),
            "-vf", f"ass={ass_path.name}",
            "-c:a", "copy",
            str(out_path.resolve()),
        ],
        cwd=str(ass_path.parent),
    )
    return {
        "output": str(out_path),
        "events": len(events),
        "style_override_used": override is not None,
        "corrections_used": segments_override_path.exists() or corrections_path.exists(),
    }


def stage_filler_detect(episode):
    work_dir = WORK_DIR / episode
    transcript_path = work_dir / "transcript.json"
    if not transcript_path.exists():
        raise FileNotFoundError(f"找不到 {transcript_path}，先跑轉錄")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    words = transcript["words"]
    result = detect(words, FILLER_AUTO_CUT, FILLER_FLAG_ONLY)

    # 純安靜停頓偵測（跟上面的固定詞表比對是互補維度）：對來源影片的音軌跑
    # ffmpeg silencedetect，找出「沒講贅詞、但單純沉默」的空檔，併入 auto_cut——
    # 跟贅詞的 auto_cut 同等級不需要人工確認（單純安靜沒有贅詞那種誤判詞義的風險），
    # 但剪法保守（見 silence_detect.build_cut_items 的緩衝邏輯）。
    # 找不到原始影片（例如只殘留轉錄結果）就略過，不影響贅詞偵測本身的結果。
    try:
        video_path = find_input_video(episode)
    except FileNotFoundError:
        video_path = None
    if video_path is not None:
        silence_items = detect_silence_cuts(
            video_path,
            SILENCE_MIN_DURATION_MS,
            SILENCE_NOISE_DB,
            SILENCE_EDGE_IGNORE_SEC,
            SILENCE_KEEP_BUFFER_MS,
        )
        result["auto_cut"].extend(silence_items)
        result["auto_cut"].sort(key=lambda x: x["start"])

    out_path = work_dir / "filler_review.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def confirm_cuts(episode, approve_indices):
    """approve_indices: flagged 清單裡要核准剪除的編號（0-indexed）。"""
    work_dir = WORK_DIR / episode
    review_path = work_dir / "filler_review.json"
    if not review_path.exists():
        raise FileNotFoundError(f"找不到 {review_path}，先跑贅詞偵測")

    review = json.loads(review_path.read_text(encoding="utf-8"))
    flagged = review["flagged"]
    approved = [flagged[i] for i in approve_indices if 0 <= i < len(flagged)]

    approved_path = work_dir / "approved_cuts.json"
    approved_path.write_text(json.dumps(approved, ensure_ascii=False, indent=2), encoding="utf-8")
    return approved


def save_manual_cuts(episode, cuts):
    """cuts: [{"start": float, "end": float, "word": str}, ...]——字幕校對頁面上，使用者
    自己聽出來的贅詞/口誤（例如講錯字自己重講一次），在文字框裡框選那段文字後標記要剪掉。

    這跟 filler_review.json 的固定詞表偵測、silence_detect 的純安靜停頓偵測是第三個
    互補維度：前兩者是規則能自動抓的，這個是「使用者耳朵聽出來、規則抓不到」的個案
    （例如語意重複但不是贅詞清單裡的詞）。時間範圍是用選取文字在該句字幕總長度裡的
    字元位置比例，反推回該句的時間範圍算出來的（跟 caption_editor.html 的分句邏輯
    同一種手法），不是逐字對時間軸精確比對，會有一定誤差，但配合跳剪本身的
    padding/緩衝機制，實務上夠用。

    視為跟固定詞表贅詞同等級的高信心自動剪（使用者已經親耳確認要剪，不需要再人工複核
    一次），_load_cut_ranges() 會一併讀取進跳剪清單。
    """
    work_dir = WORK_DIR / episode
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "manual_cuts.json").write_text(
        json.dumps(cuts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_cut_ranges(work_dir):
    review_path = work_dir / "filler_review.json"
    approved_path = work_dir / "approved_cuts.json"
    manual_path = work_dir / "manual_cuts.json"
    ranges = []
    if review_path.exists():
        review = json.loads(review_path.read_text(encoding="utf-8"))
        ranges.extend((item["start"], item["end"]) for item in review.get("auto_cut", []))
    if approved_path.exists():
        approved = json.loads(approved_path.read_text(encoding="utf-8"))
        ranges.extend((item["start"], item["end"]) for item in approved)
    if manual_path.exists():
        manual = json.loads(manual_path.read_text(encoding="utf-8"))
        ranges.extend((item["start"], item["end"]) for item in manual)
    return ranges


def _apply_padding_and_merge(ranges, padding_ms, duration):
    padding = padding_ms / 1000.0
    padded = [(max(0, s - padding), min(duration, e + padding)) for s, e in ranges]
    padded.sort()
    merged = []
    for s, e in padded:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _complement_ranges(cut_ranges, duration):
    keep = []
    cursor = 0.0
    for s, e in cut_ranges:
        if s > cursor:
            keep.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < duration:
        keep.append((cursor, duration))
    return keep


def _build_filter_complex(keep_ranges):
    parts = []
    labels = []
    for i, (s, e) in enumerate(keep_ranges):
        labels.append((f"[v{i}]", f"[a{i}]"))
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
    concat_inputs = "".join(v + a for v, a in labels)
    parts.append(f"{concat_inputs}concat=n={len(keep_ranges)}:v=1:a=1[outv][outa]")
    return ";".join(parts)


def stage_jumpcut(episode, video_filename=None):
    """預設接在字幕匹配之後：如果 output/<episode>_captioned.mp4 已存在就以它為來源
    （字幕是逐格燒錄畫進畫面的，剪掉整段區間不影響剩下片段的字幕正確性，時間軸跟原始轉錄
    一致，所以直接在已匹配字幕的版本上跳剪是安全的），沒有的話才退回用原始檔——但退回時
    會在回傳結果帶 warning，不再靜默處理（2026-07-15 Fable5 審查 B5：先前完全沒有提示，
    使用者若先按⑥再按④會拿到一支無字幕的跳剪版，且後續⑦也會優先選中它，全程零警告）。
    """
    work_dir = WORK_DIR / episode
    warning = None
    if video_filename:
        video_path = INPUT_DIR / video_filename
        used_captioned = False
    else:
        captioned_path = OUTPUT_DIR / f"{episode}_captioned.mp4"
        if captioned_path.exists():
            video_path = captioned_path
            used_captioned = True
        else:
            video_path = find_input_video(episode)
            used_captioned = False
            warning = (
                "找不到已匹配字幕的版本（output/{ep}_captioned.mp4），這次跳剪是直接剪"
                "原始檔，產出的影片不含字幕。建議先跑④匹配字幕再跑這步。"
            ).format(ep=episode)

    cut_ranges = _load_cut_ranges(work_dir)
    if not cut_ranges:
        return {"skipped": True, "reason": "沒有任何要剪的區間（可能還沒跑偵測贅詞，或偵測完沒有任何自動剪/已核准的項目）"}

    duration = ffmpeg_utils.duration_seconds(video_path)
    cut_ranges = _apply_padding_and_merge(cut_ranges, FILLER_CUT_PADDING_MS, duration)
    keep_ranges = _complement_ranges(cut_ranges, duration)
    filter_complex = _build_filter_complex(keep_ranges)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{episode}_jumpcut.mp4"

    ffmpeg_utils.run(
        [
            "ffmpeg", "-y", "-i", str(video_path.resolve()),
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", ENCODE_PRESET["video_codec"],
            "-pix_fmt", ENCODE_PRESET["pix_fmt"],
            "-c:a", ENCODE_PRESET["audio_codec"],
            "-ar", str(ENCODE_PRESET["audio_rate"]),
            "-ac", str(ENCODE_PRESET["audio_channels"]),
            str(out_path.resolve()),
        ]
    )
    new_duration = ffmpeg_utils.duration_seconds(out_path)
    total_cut = sum(e - s for s, e in cut_ranges)

    # 時間軸重映射（B1）：keep_ranges 落檔給 stage_translate／stage_qa 用，讓它們對
    # jumpcut/final 版本算出來的字幕時間，能對應到「剪過之後」的實際時間軸，而不是
    # 一律沿用原始未剪的轉錄時間。
    work_dir.mkdir(parents=True, exist_ok=True)
    timeline.save_jumpcut_map(work_dir, keep_ranges)
    (work_dir / "jumpcut_source.json").write_text(
        json.dumps({"used_captioned": used_captioned}, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "skipped": False,
        "output": str(out_path),
        "cut_ranges": len(cut_ranges),
        "total_cut_seconds": total_cut,
        "old_duration": duration,
        "new_duration": new_duration,
        "warning": warning,
    }


def stage_bumper(episode, brand=DEFAULT_BRAND, video_filename=None):
    brand_dir = BRANDS_DIR / brand
    intro_path = brand_dir / "intro.mp4"
    outro_path = brand_dir / "outro.mp4"
    if not intro_path.exists() or not outro_path.exists():
        raise FileNotFoundError(f"找不到品牌素材：{intro_path} 或 {outro_path}")

    work_dir = WORK_DIR / episode
    warning = None
    if video_filename:
        video_path = INPUT_DIR / video_filename
    else:
        # 明確優先順序（不依賴檔名字母序）：跳剪版 > 字幕版 > 原始檔
        for suffix in ("jumpcut", "captioned"):
            candidate = OUTPUT_DIR / f"{episode}_{suffix}.mp4"
            if candidate.exists():
                video_path = candidate
                break
        else:
            video_path = find_input_video(episode)
            suffix = "raw"

        # B5：跳剪版可能是在字幕匹配之前、直接剪原始檔做出來的（stage_jumpcut 找不到
        # captioned.mp4 時的退回路徑）——這種情況下片頭尾套的是無字幕版本，過去完全
        # 沒有提示，靜默產出「沒有字幕的 final」。
        if suffix == "jumpcut":
            marker_path = work_dir / "jumpcut_source.json"
            if marker_path.exists():
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                if not marker.get("used_captioned", True):
                    warning = (
                        "套用片頭尾用的跳剪版本，是在字幕匹配之前做的，不含字幕。"
                        "建議重跑④匹配字幕→⑥套用跳剪→⑦套用片頭尾。"
                    )
        elif suffix == "raw":
            warning = "找不到字幕版或跳剪版輸出，這次片頭尾是直接套在原始檔上，不含字幕、也沒剪除贅詞。"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{episode}_final.mp4"

    filter_complex = (
        "[0:v]setpts=PTS-STARTPTS[v0];[0:a]asetpts=PTS-STARTPTS[a0];"
        "[1:v]setpts=PTS-STARTPTS[v1];[1:a]asetpts=PTS-STARTPTS[a1];"
        "[2:v]setpts=PTS-STARTPTS[v2];[2:a]asetpts=PTS-STARTPTS[a2];"
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[outv][outa]"
    )
    ffmpeg_utils.run(
        [
            "ffmpeg", "-y",
            "-i", str(intro_path.resolve()),
            "-i", str(video_path.resolve()),
            "-i", str(outro_path.resolve()),
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", ENCODE_PRESET["video_codec"],
            "-pix_fmt", ENCODE_PRESET["pix_fmt"],
            "-c:a", ENCODE_PRESET["audio_codec"],
            "-ar", str(ENCODE_PRESET["audio_rate"]),
            "-ac", str(ENCODE_PRESET["audio_channels"]),
            str(out_path.resolve()),
        ]
    )

    # 時間軸重映射（B1）：final 版比來源檔多了一段片頭時長的位移，落檔給
    # stage_translate／stage_qa 用來把時間軸換算到 final 上。
    intro_duration = ffmpeg_utils.duration_seconds(intro_path)
    work_dir.mkdir(parents=True, exist_ok=True)
    timeline.save_bumper_offset(work_dir, intro_duration)

    return {"output": str(out_path), "source": str(video_path), "warning": warning}


def stage_qa(episode):
    """輸出自動 QA：取代/補強 verify_frames.py 完全手動抽幀的驗收方式。

    對「最終要交付的那支輸出檔」跑三項機械化輔助檢查：
      - contact sheet：全片均勻抽幀拼成一張總覽圖，人一次看完，不用一張一張開檔案
        （見 lib/quality_check.build_contact_sheet()）。
      - 字幕對準抽驗：字幕時間 vs 這支影片實際偵測到的靜音區間，抓出「大部分時間
        都落在靜音裡」的可疑字幕清單（見 lib/quality_check.check_caption_sync()）。
        這是輕量代理指標，不是逐字語音辨識驗證，函式的 docstring 都有講清楚
        這個限制。
      - 畫幅比警示：偵測輸出影片實際畫幅比是否明顯偏離字幕樣式調校用的 16:9（見
        lib/quality_check.check_aspect_ratio()），只回報不裁切，符合就不寫進報告
        （`aspect_ratio_warning` 是 `None`），偏離才寫進去讓儀表板顯示警示。

    來源檔優先順序：_final.mp4（最終交付版，片頭尾都套完）> _jumpcut.mp4（跳剪後，
    還沒套片頭尾）> _captioned.mp4（只燒了字幕）——跟 stage_bumper() 挑來源檔的
    優先順序邏輯一致，都是「越後面階段的產出越優先」。三個都沒有就代表這集還沒跑到
    任何有意義的輸出，直接丟錯誤訊息，不要生出一份空洞的 QA 報告誤導使用者。

    字幕事件用 _base_events(episode)——跟 stage_captions() 燒錄用的是同一份斷句
    結果，但那份是「原始未剪時間軸」；若來源是 jumpcut/final（剪過／接過片頭），
    先用 timeline.remap_events() 轉成該輸出檔實際的時間軸再拿去比對，否則對
    final/jumpcut 的比對會系統性失真（2026-07-15 Fable5 審查 B1：跳剪壓縮時間軸、
    片頭平移時間軸，過去這裡一律沿用原始時間軸，比對結果不可信）。找不到轉錄
    結果（連字幕都還沒排過）就只做 contact sheet，caption sync 那段略過（沒有字幕
    事件可比對，比對了也沒意義）。
    """
    output_path = None
    source_stage = None
    for suffix in ("final", "jumpcut", "captioned"):
        candidate = OUTPUT_DIR / f"{episode}_{suffix}.mp4"
        if candidate.exists():
            output_path = candidate
            source_stage = suffix
            break
    if output_path is None:
        raise FileNotFoundError(
            f"找不到集數 {episode} 的任何輸出版本（_final.mp4 / _jumpcut.mp4 / "
            f"_captioned.mp4 都不存在），請先跑過字幕匹配或後續階段再做品質檢查"
        )

    work_dir = WORK_DIR / episode
    work_dir.mkdir(parents=True, exist_ok=True)
    contact_sheet_path = work_dir / "qa_contact_sheet.jpg"
    sheet_info = quality_check.build_contact_sheet(output_path, contact_sheet_path)

    dropped_events = 0
    try:
        events = _base_events(episode)
        events, dropped_events = timeline.remap_events(events, source_stage, work_dir)
    except FileNotFoundError:
        events = None

    if events is not None:
        sync_result = quality_check.check_caption_sync(output_path, events)
    else:
        sync_result = {"suspects": [], "checked": 0, "silence_ranges": 0, "threshold": None}

    aspect_result = quality_check.check_aspect_ratio(output_path, PLAY_RES_X, PLAY_RES_Y)

    report = {
        "episode": episode,
        "source_video": str(output_path),
        "source_stage": source_stage,
        "contact_sheet": str(contact_sheet_path),
        "contact_sheet_frames": sheet_info["frames"],
        "contact_sheet_grid": f"{sheet_info['cols']}x{sheet_info['rows']}",
        "caption_sync_checked": sync_result["checked"],
        "caption_sync_threshold": sync_result["threshold"],
        "caption_sync_dropped_events": dropped_events,
        "suspects": sync_result["suspects"],
        "aspect_ratio_warning": aspect_result if aspect_result.get("matches") is False else None,
    }
    report_path = work_dir / "qa_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def stage_translate(episode, target_lang):
    """字幕翻譯：讀跟 stage_captions/stage_qa 同一份斷句結果（_base_events，已含校對過的
    文字），逐句丟給翻譯引擎，輸出 output/<episode>_<target_lang>.srt。

    時間碼對應「目前這集最新的輸出版本」（final > jumpcut > captioned，跟 stage_qa/
    stage_bumper 選來源檔同一套優先序）——若已跑過跳剪／套過片頭，先用
    timeline.remap_events() 把時間軸轉成該輸出檔實際的時間軸，不再一律沿用原始未剪
    的轉錄時間（2026-07-15 Fable5 審查 B1：舊版一律用原始時間軸，SRT 掛到剪過的
    final/jumpcut 版本上會整段漂移）。只換文字，不燒錄進影片（讓使用者自己決定要
    不要在剪輯軟體/其他平台掛上）。

    需要環境變數 GOOGLE_TRANSLATE_API_KEY（見 config.py TRANSLATE_ENGINE 旁的說明）。
    """
    work_dir = WORK_DIR / episode
    source_stage = None
    for suffix in ("final", "jumpcut", "captioned"):
        if (OUTPUT_DIR / f"{episode}_{suffix}.mp4").exists():
            source_stage = suffix
            break
    if source_stage is None:
        raise FileNotFoundError(
            f"找不到集數 {episode} 的任何輸出版本，請先跑過字幕匹配（④）再翻譯"
        )

    events = _base_events(episode)
    events, dropped = timeline.remap_events(events, source_stage, work_dir)

    texts = [t for _, _, t in events]
    api_key = os.environ.get("GOOGLE_TRANSLATE_API_KEY")
    translated_texts = translate.translate_texts(
        texts,
        target_lang,
        source_lang=TRANSLATE_SOURCE_LANG,
        engine=TRANSLATE_ENGINE,
        api_key=api_key,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{episode}_{target_lang}.srt"
    out_path.write_text(translate.build_srt(events, translated_texts), encoding="utf-8")

    warning = None
    if dropped:
        warning = f"{dropped} 句字幕的時間點落在跳剪剪掉的區間裡，已從這份翻譯字幕移除（避免時間碼錯位）。"

    return {
        "output": str(out_path),
        "target_lang": target_lang,
        "events": len(events),
        "source_stage": source_stage,
        "dropped_events": dropped,
        "warning": warning,
    }


def save_broll_markers(episode, markers):
    """markers: [{"start": float, "end": float, "note": str}, ...]——使用者手動標記
    「這段需要補 B-Roll」的時間點，跟 save_manual_cuts 同樣「機器不猜，人工標記」的精神。
    """
    work_dir = WORK_DIR / episode
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "broll_markers.json").write_text(
        json.dumps(markers, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def stage_broll_plan(episode):
    """規劃階段：讀使用者標記的 B-Roll 需求時間點 + 對應字幕文字，組出建議 prompt，
    存成 work/<episode>/broll_plan.json。不呼叫任何生成式 API（見 lib/broll.py 開頭說明）。
    """
    work_dir = WORK_DIR / episode
    markers_path = work_dir / "broll_markers.json"
    if not markers_path.exists():
        raise FileNotFoundError(f"找不到 {markers_path}，還沒標記過需要 B-Roll 的時間點")

    markers = json.loads(markers_path.read_text(encoding="utf-8"))
    events = _base_events(episode)
    plan = broll.build_plan(markers, events)

    plan_path = work_dir / "broll_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"output": str(plan_path), "markers": len(markers)}


def stage_broll_generate(episode):
    """讀 stage_broll_plan 產出的 broll_plan.json，逐項去 Pexels 搜尋下載素材到
    work/<episode>/broll/，不燒錄進影片、只是把素材準備好，使用者自己決定要不要剪進去。
    需要環境變數 PEXELS_API_KEY（見 config.py BROLL_ENGINE 旁的說明）。
    """
    work_dir = WORK_DIR / episode
    plan_path = work_dir / "broll_plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(f"找不到 {plan_path}，先跑 B-Roll 規劃階段")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    api_key = os.environ.get("PEXELS_API_KEY")
    dest_dir = work_dir / "broll"
    results = broll.generate_assets(plan, BROLL_ENGINE, dest_dir, api_key)

    assets_path = work_dir / "broll_assets.json"
    assets_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    downloaded = sum(1 for r in results if not r.get("skipped"))
    return {"output": str(assets_path), "downloaded": downloaded, "skipped": len(results) - downloaded}
