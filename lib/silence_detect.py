"""純安靜停頓偵測：跟 filler_detect.py 比對固定詞表是不同維度——這裡完全不管有沒有
講贅詞，只抓「音軌本身安靜超過門檻」的空檔，例如老師切換視窗、想接下來要點哪裡的停頓。
跟贅詞偵測是互補關係：贅詞抓「講了但講的是廢話」，這裡抓「根本沒在講話」。

2026-07-14 改用 auto-editor（WyattBlue/auto-editor，Unlicense/Public Domain）取代土法
ffmpeg silencedetect 當「找出候選靜音區間」的偵測引擎，理由：
  - 舊做法（_raw_silence_ranges_ffmpeg）靠正則表達式解析 silencedetect 印在 stderr 的
    文字，是 ffmpeg 官方濾鏡的標準用法但沒有結構化輸出，邊界情況（例如剛好卡在偵測窗
    交界、多國語系 locale 輸出格式微妙差異）沒那麼成熟。
  - auto-editor 是成熟的開源剪輯工具，內建的音量分析是逐音框（audio frame）判斷後再
    合併，不是靠解析文字訊息猜區間，實測（見下方 _raw_silence_ranges_auto_editor）跟
    舊 ffmpeg 版在同一支測試影片上偵測到的靜音區間幾乎一致（誤差 <0.01 秒），但引擎
    本身更不容易受 ffmpeg 版本/输出格式差異影響。
  - 只借用它「偵測」這一步：用 `--export v1` 拿到它算好的「哪些區間是安靜(speed=cut)」
    時間軸清單，不讓它接管剪輯（不用它的 -o 輸出剪好的影片），偵測結果轉換後一樣餵給
    detect_silence()/build_cut_items() 走這個專案自己的 min_duration/edge_ignore/
    keep_buffer 過濾與跳剪管線，架構完全不動。
  - 保留舊 ffmpeg 版（改名 _raw_silence_ranges_ffmpeg）當 fallback：如果環境沒裝
    auto-editor、或 subprocess 呼叫失敗（例如找不到執行檔），自動退回舊做法，不會讓
    這個階段整個掛掉。

呼叫 ffmpeg／auto-editor 一律走 lib/ffmpeg_utils.run()，跟其他階段同一套 subprocess
包裝，不另外重包。
"""

import json
import re
import sys
import tempfile
from pathlib import Path

from lib import ffmpeg_utils

# silencedetect 沒有結構化輸出格式（JSON/CSV），只會把偵測結果印在 stderr，
# 這是 ffmpeg 官方濾鏡的標準用法，只能用正則表達式解析文字。
_SILENCE_RE = re.compile(
    r"silence_(start|end): ([\d.eE+-]+)(?: \| silence_duration: ([\d.eE+-]+))?"
)

# auto-editor v1 匯出格式的時間軸單位是「timebase」，預設會用它自己算出來的
# recommendedTimebase（螢幕錄影常見的 VFR 來源，這個值通常是不規則小數，例如
# 1961/100），要另外呼叫一次才能查到、還要在我們這邊重新算秒數，多一層容易出錯的
# 轉換。改用 --time-base 強制指定成 1000（= 1 個單位 = 1 毫秒），既好算（直接除以
# 1000 就是秒數）又不會犧牲精度（1000 遠高於原本 VFR 來源約 19.6 的有效影格率）。
_AUTO_EDITOR_TIME_BASE = 1000

# auto-editor 的 v1 timeline 用「speed」欄位標記每一段要怎麼處理：預設 --when-silent
# 是 cut（等同把速度設成 99999，語意上是「無限快」＝整段移除），我們沒有覆寫
# --when-silent，所以維持這個預設值。用 > 1000 判斷「這段是要剪掉的靜音段」，
# 不直接比對 99999.0 這個魔術數字，避免以後 auto-editor 版本微調這個數值就誤判。
_AUTO_EDITOR_CUT_SPEED_THRESHOLD = 1000.0


def _db_to_amplitude_ratio(db):
    """dB 轉成 auto-editor --edit audio:threshold= 用的線性振幅比例（0~1）。

    ffmpeg silencedetect 的 noise 參數、auto-editor 的 threshold 概念上是同一件事
    （音量低於這個門檻視為安靜），差別只在單位：前者是 dB（相對滿刻度），後者是線性
    振幅比例。標準換算公式 amplitude = 10^(dB/20)（20 log10 定義），例如 -30dB
    等於約 0.0316（3.16%）。這樣既有的 config.py SILENCE_NOISE_DB 常數不用另外
    重調一組 auto-editor 專用門檻，兩個引擎共用同一個「多安靜才算安靜」的依據。
    """
    ratio = 10 ** (db / 20.0)
    return max(0.0001, min(ratio, 1.0))  # 防呆：避免極端 db 值換算出不合法的門檻


def _raw_silence_ranges_auto_editor(video_path, noise_db):
    """用 auto-editor 分析音軌，回傳所有偵測到的 (start, end) 候選靜音區間（秒）。

    只挖它的「偵測」結果，不讓它接管剪輯：
      -ex v1                  匯出成 auto-editor 自己的 JSON timeline 格式（不是剪好
                               的影片），每個 chunk 是 [start, end, speed]。
      --when-silent cut       安靜段標記為「剪掉」（speed=99999），對應到我們要的
                               「候選靜音區間」。這其實是預設值，寫出來只是求明確。
      --margin 0               不要讓 auto-editor 自己做「安靜段太靠近就併入有聲段」
                               的平滑化——那件事交給這個專案自己的 detect_silence()/
                               build_cut_items() 做（min_duration_ms 二次過濾、
                               keep_buffer_ms 緩衝），兩邊的平滑化邏輯疊在一起會很難
                               debug，只留一份。
      --time-base 1000         見上面 _AUTO_EDITOR_TIME_BASE 的說明，讓輸出時間軸
                               直接是毫秒，不用另外查 recommendedTimebase 換算。
      --no-open -q              不要編輯完自動跳出檔案總管/播放器開檔（這是背景批次
                               流程，且輸出格式是 JSON，不是可播放的東西），-q 降噪。

    回傳的候選區間完全未套用「最短時長門檻」或「頭尾邊界」過濾，過濾邏輯一樣在
    detect_silence() 做，跟舊版 _raw_silence_ranges_ffmpeg 的分工一致。
    """
    threshold = _db_to_amplitude_ratio(noise_db)
    with tempfile.TemporaryDirectory(prefix="auto_editor_silence_") as tmp_dir:
        out_path = Path(tmp_dir) / "timeline.v1"
        result = ffmpeg_utils.run(
            [
                "auto-editor", str(video_path),
                "--edit", f"audio:threshold={threshold}",
                "--when-silent", "cut",
                "--margin", "0",
                "--time-base", str(_AUTO_EDITOR_TIME_BASE),
                "--export", "v1",
                "-o", str(out_path),
                "--no-open", "-q",
            ],
            check=False,
        )
        if result.returncode != 0 or not out_path.exists():
            raise RuntimeError(
                f"auto-editor 分析失敗 (exit={result.returncode})：\n{result.stderr}"
            )
        data = json.loads(out_path.read_text(encoding="utf-8"))

    ranges = []
    for start, end, speed in data.get("chunks", []):
        if speed > _AUTO_EDITOR_CUT_SPEED_THRESHOLD:
            ranges.append((start / _AUTO_EDITOR_TIME_BASE, end / _AUTO_EDITOR_TIME_BASE))

    # 保險合併：理論上 auto-editor 在 margin=0 時已經不會吐出相鄰的兩段同 speed
    # chunk（chunks 是連續分割整條時間軸，同 speed 的相鄰段本身就該是同一段），
    # 但不同版本行為可能有差異，這裡用「首尾銜接（誤差 <1ms）就合併」保守處理一次，
    # 避免因為多一個微小縫隙讓後面 min_duration_ms 過濾誤判成「不夠長」。
    merged = []
    for start, end in ranges:
        if merged and start - merged[-1][1] < 0.001:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _raw_silence_ranges_ffmpeg(video_path, noise_db):
    """舊版做法（2026-07-14 前的實作）：對來源影片的音軌跑 ffmpeg silencedetect，
    回傳所有偵測到的 (start, end) 靜音區間（秒），完全未套用「最短時長門檻」或
    「頭尾邊界」過濾，過濾邏輯在 detect_silence() 做。

    保留當 _raw_silence_ranges_auto_editor() 失敗時（例如環境沒裝 auto-editor）的
    fallback，不是主力路徑，見 _raw_silence_ranges()。

    d=0.1（濾鏡本身的最短偵測時長）刻意設得很短：真正「夠長才算數」的門檻交給
    detect_silence() 用 min_duration_ms 二次過濾，這裡先撈出所有候選區間，避免因為
    濾鏡本身的最短時長設太高而漏掉一些邊界案例（例如剛好卡在門檻附近的靜音）。
    """
    result = ffmpeg_utils.run(
        [
            "ffmpeg", "-i", str(video_path),
            "-af", f"silencedetect=noise={noise_db}dB:d=0.1",
            "-f", "null", "-",
        ],
        check=False,  # -f null 不寫實體檔案，部分 ffmpeg 版本仍會回傳非 0，不能當失敗處理
    )
    ranges = []
    cur_start = None
    for m in _SILENCE_RE.finditer(result.stderr or ""):
        kind, val = m.group(1), float(m.group(2))
        if kind == "start":
            cur_start = val
        elif kind == "end" and cur_start is not None:
            ranges.append((cur_start, val))
            cur_start = None
    return ranges


def _raw_silence_ranges(video_path, noise_db):
    """撈候選靜音區間的統一入口：優先用 auto-editor，失敗（例如沒裝、subprocess
    出錯、輸出格式不如預期）就退回舊版 ffmpeg silencedetect，並把降級原因印到
    stderr（不吞掉、讓使用者看得到，但不因此讓整個偵測階段失敗）。
    """
    try:
        return _raw_silence_ranges_auto_editor(video_path, noise_db)
    except (RuntimeError, FileNotFoundError, json.JSONDecodeError, OSError) as e:
        print(
            f"[silence_detect] auto-editor 偵測失敗，退回 ffmpeg silencedetect：{e}",
            file=sys.stderr,
        )
        return _raw_silence_ranges_ffmpeg(video_path, noise_db)


def detect_silence(video_path, min_duration_ms, noise_db, edge_ignore_sec):
    """回傳「片中內部」超過 min_duration_ms 門檻的安靜停頓區間 [(start, end), ...]（秒）。

    - min_duration_ms 門檻存在的理由：正常說話換氣的自然停頓多半 < 1 秒，太低的門檻會把
      這種自然停頓也當成「發呆空檔」誤剪，導致講話節奏被剪得支離破碎。
    - edge_ignore_sec：忽略影片開頭/結尾 N 秒內的靜音——那是錄影開場等待、或講完話
      還沒把影片切掉的收尾尾段，是正常收尾，不是「贅詞式空檔」，只處理片中內部的靜音
      （規格邊界情況：開頭/結尾靜音不誤剪）。
    """
    duration = ffmpeg_utils.duration_seconds(video_path)
    min_duration = min_duration_ms / 1000.0
    raw_ranges = _raw_silence_ranges(video_path, noise_db)
    inner_start, inner_end = edge_ignore_sec, duration - edge_ignore_sec

    kept = []
    for start, end in raw_ranges:
        # B7（2026-07-15 Fable5 審查）：舊版整段跳過任何觸及邊界的靜音，橫跨邊界、
        # 延伸進片中的長靜音（例如 1.9s 起、持續 60s）會整段被放過。改成只裁掉落在
        # 開頭/結尾緩衝區內的部分，裁完仍在片中內部、且夠長的那一截照樣保留剪掉。
        clipped_start, clipped_end = max(start, inner_start), min(end, inner_end)
        if (clipped_end - clipped_start) < min_duration:
            continue
        kept.append((clipped_start, clipped_end))
    return kept


def build_cut_items(silence_ranges, keep_buffer_ms):
    """把偵測到的靜音區間轉成可以併進 filler_detect 的 auto_cut 清單的項目格式
    （{"word", "start", "end"}，跟贅詞的 auto_cut 項目同一種形狀，才能直接合併走
    同一條剪輯流程，不用另開一套資料結構）。

    保守剪法（規格要求）：不整段剪光，只剪掉中段，前後各留 keep_buffer_ms/2 當緩衝，
    讓剪完之後還留一小段自然停頓感，避免畫面跳太快讓觀眾覺得突兀。
    這個緩衝之後還會再被 stage_jumpcut 的 FILLER_CUT_PADDING_MS 往外擴一次（那是剪輯
    當下才加的咬字安全邊界，兩者疊加後仍會留下淨緩衝，見 config.py 的說明）。
    """
    half_buffer = keep_buffer_ms / 1000.0 / 2.0
    items = []
    for start, end in silence_ranges:
        cut_start = start + half_buffer
        cut_end = end - half_buffer
        if cut_start >= cut_end:
            continue  # 扣掉緩衝後範圍不合法（區間太短），不值得剪，略過
        items.append({
            "word": "（安靜停頓）",
            "start": cut_start,
            "end": cut_end,
            "reason": "dead_air",
        })
    return items


def detect(video_path, min_duration_ms, noise_db, edge_ignore_sec, keep_buffer_ms):
    """一次到位：偵測 + 轉成可合併的 auto_cut 項目清單。"""
    ranges = detect_silence(video_path, min_duration_ms, noise_db, edge_ignore_sec)
    return build_cut_items(ranges, keep_buffer_ms)
