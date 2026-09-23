# -*- coding: utf-8 -*-
"""輸出自動 QA：取代/補強 verify_frames.py 目前完全手動（人工一張一張抽幀存 jpg
再自己打開看）的驗收方式。

動機：這個專案曾經真的發生過事故——pipeline 邏輯改壞過一次，導致「完整版」最終輸出
完全沒有字幕燒錄成功，是靠人工手動抽幀才發現的。手動抽幀很慢，也容易漏看（尤其是
只抽片頭片尾附近幾張、沒抽到出問題的中段）。

這裡提供三種機械化的輔助檢查：
  - build_contact_sheet()：全片均勻抽幀，直接用 ffmpeg 濾鏡一次拼成一張網格總覽圖，
    人一次看完整支影片的縮圖，不用像 verify_frames.py 那樣開好幾個檔案。
  - check_caption_sync()：拿字幕事件清單跟同一支影片的靜音偵測結果比對，抓出「這句
    字幕顯示的時間範圍，有一大部分都落在偵測到的靜音區間」的可疑字幕，列成待人工
    複查清單。
  - check_aspect_ratio()：偵測輸出影片實際畫幅比是否明顯偏離字幕樣式調校用的預設
    16:9（見 config.PLAY_RES_X/Y），只回報不裁切——目前所有素材都是 1920x1080，
    這是「先防未然」用的輕量警示，不是完整的裁切/信箱化功能。

⚠️ 三個函式都只是「機械化輔助線索」，不是絕對判定：
  - contact sheet 只是把畫面縮圖化方便人眼一次掃過，仍然需要人工看過那張圖才算數，
    不會自動判斷「有沒有問題」。
  - check_caption_sync() 完全依賴 ffmpeg silencedetect 的音量門檻，安靜偵測本身就
    可能有誤差（音量忽大忽小、環境噪音、BGM 蓋過人聲…），列出的可疑項目只代表「值得
    人工重點複查」，不是「這句字幕確定對不準」，也不是逐字語音辨識比對（那個等級的
    驗證工作量太大，這裡刻意不做）。
  - check_aspect_ratio() 只比對畫幅比數字，偵測到偏離不代表字幕一定跑版到不能看，
    只是提醒「這支素材跟預設假設不同，值得打開輸出檔案親眼確認一下」。

呼叫 ffmpeg 一律走 lib/ffmpeg_utils.run()（跟其他階段同一套包裝），靜音偵測直接
重用 lib/silence_detect.py 現成的 detect_silence()，不重新寫一套。

2026-09-10 新增三項（跟開源同類工具比對後補的缺口，見 memory course-video-postprod-tool）：
  - check_dead_air()：對最終輸出檔重跑一次跳剪用的靜音偵測，抓「已經剪過但還留著」
    的長停頓，跟 stage_filler_detect 找候選跳剪點是同一套引擎。
  - check_loudness()：ffmpeg loudnorm 單通分析模式量響度，只在 True Peak 超標時
    警示（見函式說明，這裡不對 LUFS 偏差示警）。
  - detect_flash()：downsample 後量逐幀平均亮度變化，抓亮度驟變。這三項一樣是
    「機械化輔助線索」，不是絕對判定，跟上面三個既有檢查同一個定位。
"""

import json
import re
from pathlib import Path

from config import (
    QA_ASPECT_RATIO_TOLERANCE,
    QA_CAPTION_SYNC_OVERLAP_THRESHOLD,
    QA_CONTACT_SHEET_CELL_H,
    QA_CONTACT_SHEET_CELL_W,
    QA_CONTACT_SHEET_COLS,
    QA_CONTACT_SHEET_EDGE_SKIP_RATIO,
    QA_CONTACT_SHEET_FRAMES,
    QA_CONTACT_SHEET_ROWS,
    QA_FLASH_LUMA_DELTA_THRESHOLD,
    QA_FLASH_MERGE_GAP_SEC,
    QA_FLASH_SAMPLE_FPS,
    QA_LOUDNESS_TARGET_LUFS,
    QA_LOUDNESS_TP_WARN_DBTP,
    QA_SYNC_SILENCE_EDGE_IGNORE_SEC,
    QA_SYNC_SILENCE_MIN_DURATION_MS,
    QA_SYNC_SILENCE_NOISE_DB,
    SILENCE_EDGE_IGNORE_SEC,
    SILENCE_MIN_DURATION_MS,
    SILENCE_NOISE_DB,
)
from lib import ffmpeg_utils
from lib.silence_detect import detect_silence


def build_contact_sheet(
    video_path,
    out_path,
    frames=QA_CONTACT_SHEET_FRAMES,
    cols=QA_CONTACT_SHEET_COLS,
    rows=QA_CONTACT_SHEET_ROWS,
    cell_width=QA_CONTACT_SHEET_CELL_W,
    cell_height=QA_CONTACT_SHEET_CELL_H,
    edge_skip_ratio=QA_CONTACT_SHEET_EDGE_SKIP_RATIO,
):
    """全片均勻抽 `frames` 張幀，用 ffmpeg 濾鏡一次拼成一張 cols x rows 的網格總覽圖
    存到 out_path，不依賴 Pillow 之類專案目前沒用過的套件，純靠 ffmpeg 濾鏡鏈完成
    （fps 均勻取樣 → scale+pad 統一每格大小 → tile 拼圖），一次 ffmpeg 呼叫搞定。

    跳過頭尾各 edge_skip_ratio（沿用 verify_frames.py 既有邏輯）：避免抽到片頭/
    片尾常見的黑幀或品牌轉場，那不是要驗收的教學內容本身。

    回傳 dict：實際用了幾張、幾欄幾列、抽幀間隔秒數，方便呼叫端記進 qa_report.json。
    """
    if cols * rows < frames:
        # 網格容量比要求的張數小，最多只能放 cols*rows 張，多的抽了也拼不進圖裡
        frames = cols * rows

    duration = ffmpeg_utils.duration_seconds(video_path)
    skip = duration * edge_skip_ratio
    start = skip
    end = max(start + 0.1, duration - skip)
    usable = max(end - start, 0.1)
    # 至少 0.1 秒：避免影片太短（例如測試用的幾秒鐘素材）算出 interval<=0 讓 fps 濾鏡出錯
    interval = max(usable / frames, 0.1)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    vf = (
        f"fps=1/{interval:.4f},"
        f"scale={cell_width}:{cell_height}:force_original_aspect_ratio=decrease,"
        f"pad={cell_width}:{cell_height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"tile={cols}x{rows}"
    )
    ffmpeg_utils.run(
        [
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}",
            "-i", str(video_path),
            "-t", f"{usable:.3f}",
            "-vf", vf,
            "-frames:v", "1",
            "-q:v", "2",
            str(out_path),
        ]
    )
    return {
        "path": str(out_path),
        "frames": frames,
        "cols": cols,
        "rows": rows,
        "interval_seconds": round(interval, 3),
    }


def check_aspect_ratio(video_path, expected_width, expected_height, tolerance=QA_ASPECT_RATIO_TOLERANCE):
    """畫幅比警示（輕量防呆，不裁切、不擋流程）：字幕樣式（Fontsize/Outline/Margin）
    是照 config.PLAY_RES_X/Y（目前 16:9）調校的。ASS 字幕本身有解析度無關設計——
    PlayResX/PlayResY 會被 ffmpeg `ass` 濾鏡等比例縮放對應到實際影片畫面，所以「解析度
    不同但畫幅比一樣」（例如 1280x720 vs 1920x1080，都是 16:9）不會跑版，不需要處理。
    只有「畫幅比本身不同」（例如 4:3 螢幕錄影、超寬螢幕）才會讓 X/Y 縮放比例不一致，
    造成字幕位置/字型被非等比拉伸——這裡只負責偵測並回報，實際的裁切/信箱化處理
    刻意先不做（尚未有真實素材遇到這個情況，等真的發生再決定裁切策略）。

    回傳 dict，`matches=False` 代表畫幅比明顯偏離，呼叫端（stage_qa）會把這個結果
    放進 qa_report.json 給使用者在儀表板上看到警示。
    """
    stream = ffmpeg_utils.video_stream(video_path)
    if stream is None or not stream.get("width") or not stream.get("height"):
        return {"matches": None, "reason": "找不到視訊軌解析度資訊，略過畫幅比檢查"}

    actual_width, actual_height = stream["width"], stream["height"]
    actual_ratio = actual_width / actual_height
    expected_ratio = expected_width / expected_height
    matches = abs(actual_ratio - expected_ratio) / expected_ratio <= tolerance

    return {
        "matches": matches,
        "actual_width": actual_width,
        "actual_height": actual_height,
        "actual_ratio": round(actual_ratio, 4),
        "expected_width": expected_width,
        "expected_height": expected_height,
        "expected_ratio": round(expected_ratio, 4),
    }


def _range_overlap_seconds(a_start, a_end, b_start, b_end):
    """兩個時間區間的重疊秒數（沒重疊回 0，不會是負數）。"""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def check_caption_sync(
    video_path,
    events,
    min_duration_ms=QA_SYNC_SILENCE_MIN_DURATION_MS,
    noise_db=QA_SYNC_SILENCE_NOISE_DB,
    edge_ignore_sec=QA_SYNC_SILENCE_EDGE_IGNORE_SEC,
    overlap_threshold=QA_CAPTION_SYNC_OVERLAP_THRESHOLD,
):
    """字幕對準抽驗：每一句字幕的時間範圍，跟 `video_path` 實際偵測到的靜音區間
    （直接重用 lib/silence_detect.detect_silence()，不重新寫一套）比對重疊比例。

    events：[(start, end, text), ...] 格式（跟 lib/pipeline._base_events() 回傳的
    字幕事件清單同一種形狀）。

    如果一句字幕的時間範圍裡，有 >= overlap_threshold（預設 70%）都落在偵測到的
    靜音區間內，代表這句字幕很可能燒在沒人在講話的畫面上，是潛在的時間軸沒對準的
    警訊，列進回傳的 suspects 清單。

    ⚠️ 這只是輔助人工判斷的線索，不是絕對判定失敗：
    silencedetect 本身是音量門檻判斷，不是逐字語音辨識，老師講話音量忽大忽小、
    環境底噪、字幕正常的些微提早/延後顯示，都可能讓這個比例出現誤差。suspects
    清單是「值得人工重點複查」，不是「確定有問題」。
    """
    silence_ranges = detect_silence(video_path, min_duration_ms, noise_db, edge_ignore_sec)

    suspects = []
    for i, (start, end, text) in enumerate(events):
        caption_dur = end - start
        if caption_dur <= 0:
            continue  # 異常的零長度/負長度字幕事件，跳過不列入比對
        overlap = sum(
            _range_overlap_seconds(start, end, s, e) for s, e in silence_ranges
        )
        ratio = overlap / caption_dur
        if ratio >= overlap_threshold:
            suspects.append(
                {
                    "index": i,
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "text": text,
                    "silence_overlap_ratio": round(ratio, 2),
                }
            )

    return {
        "suspects": suspects,
        "checked": len(events),
        "silence_ranges": len(silence_ranges),
        "threshold": overlap_threshold,
    }


def check_dead_air(
    video_path,
    start_ignore_sec=0.0,
    min_duration_ms=SILENCE_MIN_DURATION_MS,
    noise_db=SILENCE_NOISE_DB,
    tail_ignore_sec=SILENCE_EDGE_IGNORE_SEC,
):
    """漏剪停頓檢查：對「最終輸出檔」重跑一次跳剪用的同一套靜音偵測引擎
    （detect_silence()，直接重用不重寫），找出還留在成片裡、超過跳剪門檻的安靜
    停頓——正常情況下這些應該早就被 stage_jumpcut 剪掉，出現在這裡代表這集還沒
    真的跑過跳剪，或跳剪後又有新的停頓被接進來。

    start_ignore_sec：忽略片頭時長（bumper 開場本來就安靜，不是漏剪），只有來源
    是 final 版本時，呼叫端（stage_qa）算好片頭秒數傳進來，其餘情況傳 0。
    tail_ignore_sec 沿用跳剪本身的邊界緩衝常數，收尾正常的等待/收尾靜音不算漏剪。
    """
    duration = ffmpeg_utils.duration_seconds(video_path)
    raw_ranges = detect_silence(video_path, min_duration_ms, noise_db, edge_ignore_sec=0.0)
    inner_start, inner_end = start_ignore_sec, duration - tail_ignore_sec
    min_duration = min_duration_ms / 1000.0

    gaps = []
    for start, end in raw_ranges:
        clipped_start, clipped_end = max(start, inner_start), min(end, inner_end)
        if (clipped_end - clipped_start) < min_duration:
            continue
        gaps.append({
            "start": round(clipped_start, 2),
            "end": round(clipped_end, 2),
            "duration": round(clipped_end - clipped_start, 2),
        })

    return {"gaps": gaps, "count": len(gaps), "min_duration_ms": min_duration_ms}


_LOUDNORM_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def check_loudness(video_path, target_lufs=QA_LOUDNESS_TARGET_LUFS, tp_warn_dbtp=QA_LOUDNESS_TP_WARN_DBTP):
    """響度量測：ffmpeg loudnorm 濾鏡單通分析模式（不是兩通響度正規化，這個專案
    沒有做響度正規化，這裡只量測不改動音訊），量出 Integrated Loudness（LUFS）
    跟 True Peak（dBTP）。

    只在 True Peak 超過 tp_warn_dbtp 時示警，不對「LUFS 離 target 多遠」下警示：
    這個專案從未做過響度正規化，量出來的 LUFS 幾乎必然偏離 target，若照 LUFS 偏差
    示警，等於每一集都跳警告，變成狼來了沒人看；True Peak 超標才是真的會在部分
    播放裝置造成削波爆音的具體風險，值得示警。
    """
    result = ffmpeg_utils.run(
        [
            "ffmpeg", "-i", str(video_path),
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", "-",
        ],
        check=False,  # -f null 不寫實體檔，部分 ffmpeg 版本仍會回傳非 0，不能當失敗處理
    )
    # loudnorm 的 JSON 摘要印在 stderr 的最後一段（前面還有一般 log），取最後一個
    # 大括號區塊即可，不用逐行解析。
    matches = _LOUDNORM_JSON_RE.findall(result.stderr or "")
    if not matches:
        return {"measured": False, "reason": "無法解析 ffmpeg loudnorm 輸出"}

    data = json.loads(matches[-1])
    true_peak = float(data["input_tp"])
    return {
        "measured": True,
        "integrated_lufs": float(data["input_i"]),
        "true_peak_dbtp": true_peak,
        "target_lufs": target_lufs,
        "true_peak_warning": true_peak > tp_warn_dbtp,
        "true_peak_limit": tp_warn_dbtp,
    }


_YAVG_RE = re.compile(r"lavfi\.signalstats\.YAVG=([\d.]+)")


def detect_flash(
    video_path,
    sample_fps=QA_FLASH_SAMPLE_FPS,
    luma_delta_threshold=QA_FLASH_LUMA_DELTA_THRESHOLD,
    merge_gap_sec=QA_FLASH_MERGE_GAP_SEC,
):
    """閃爍/爆閃偵測：先降到 sample_fps 張/秒（全片用原始 fps 逐幀分析對 CPU-only
    機器太慢），用 signalstats 濾鏡量每一取樣幀的平均亮度（YAVG，0-255），相鄰
    取樣點亮度差超過門檻視為一次閃爍，merge_gap_sec 內的相鄰事件合併成一次。

    ⚠️ 螢幕錄影課程影片天生有大量正常的高亮度變化（切視窗、捲頁、彈出對話框），
    這跟真正需要示警的爆閃/頻閃很難靠簡單門檻完全分開——門檻刻意設寬，且整個
    檢查可以用 config.QA_FLASH_ENABLED 關掉；第一次真實素材跑出來若誤報太多，
    直接關掉這項比死磕調門檻划算。
    """
    result = ffmpeg_utils.run(
        [
            "ffmpeg", "-i", str(video_path),
            "-vf", f"fps={sample_fps},signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
            "-f", "null", "-",
        ],
        check=False,
    )
    text = (result.stdout or "") + (result.stderr or "")
    yavgs = [float(m.group(1)) for m in _YAVG_RE.finditer(text)]
    interval = 1.0 / sample_fps

    events = []
    for i in range(1, len(yavgs)):
        delta = abs(yavgs[i] - yavgs[i - 1])
        if delta >= luma_delta_threshold:
            events.append({"time": round(i * interval, 2), "luma_delta": round(delta, 1)})

    merged = []
    for e in events:
        if merged and e["time"] - merged[-1]["time"] <= merge_gap_sec:
            merged[-1]["luma_delta"] = max(merged[-1]["luma_delta"], e["luma_delta"])
        else:
            merged.append(dict(e))

    return {"events": merged, "count": len(merged), "sample_fps": sample_fps, "threshold": luma_delta_threshold}
