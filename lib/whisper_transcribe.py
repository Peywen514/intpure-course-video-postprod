"""逐字時間戳轉錄：stable-ts（jianfch/stable-ts，MIT）包 faster-whisper 後端，含磁碟快取
（同一支影片不重複跑轉錄）。

為什麼從原生 faster-whisper 換成 stable-ts，不只是「怎麼用」：

- 校對頁面的「✂分句」用播放頭時間切，「框選文字剪除贅詞」則是用選取文字在該句總長度裡的
  字元位置比例反推時間範圍——沒有更精準的逐字時間依據時只能用這種近似法。這兩個功能的精準度
  完全受限於逐字時間戳本身準不準；原生 faster-whisper 的詞級時間戳來自 cross-attention +
  DTW 一次性推算，遇到語速快、連續發音或背景雜訊時容易偏移。
- stable-ts 在同一次推論結果之上，用 VAD（可選 Silero VAD，這裡用 vad=True 開啟）偵測實際
  有聲/無聲區間，並用 token 機率變化反覆修正每個字的起訖時間（詳見其 non_whisper.transcribe_any
  → WhisperResult.adjust_by_silence 的後處理管線），時間戳精準度比原生輸出高，能讓分句/剪詞
  的時間範圍更準。
- stable-ts 用 stable_whisper.load_faster_whisper() 直接包住既有的 faster_whisper.WhisperModel，
  沿用同一顆 CTranslate2 模型與既有的 model_size/compute_type/device 設定，不需要像 WhisperX
  那樣另外掛一顆對齊模型；中文也不用額外找對齊模型（WhisperX 官方沒有中文對齊模型，這也是這次
  不選 WhisperX 的原因）。

注意：stable-ts 的靜音抑制/VAD 精修管線一定會用 ffmpeg CLI 重新讀一次音訊（見其
audio.utils.load_audio），這在本專案本來就是既有前提（README 已要求 ffmpeg/ffprobe 裝好並
加入 PATH），不是新增的依賴。
"""

import json
from pathlib import Path

from lib import ffmpeg_utils

_model = None


def _get_model(model_size="medium"):
    global _model
    if _model is None:
        import stable_whisper
        _model = stable_whisper.load_faster_whisper(model_size, device="cpu", compute_type="int8")
    return _model


def transcribe(video_path, out_json_path, model_size="medium", force=False, initial_prompt=None):
    """轉錄 video_path，寫出逐字時間戳 JSON 到 out_json_path。已存在且非 force 時直接讀快取回傳。

    initial_prompt：提示 Whisper 常見詞彙（例如累積詞庫裡常被校正成的正確詞），
    不是重新訓練模型，只是解碼時的上下文提示，能降低同樣術語重複被聽錯的機率。

    回傳格式（專案通用資料契約，pipeline.py / ass_builder.py / glossary.py 都吃這個格式，
    不可變動 key 名稱）：
    {"duration":.., "language":.., "segments":[{"start","end","text"}],
     "words":[{"word","start","end","prob"}]}
    """
    out_json_path = Path(out_json_path)
    if out_json_path.exists() and not force:
        cached = json.loads(out_json_path.read_text(encoding="utf-8"))
        # B7（2026-07-15 Fable5 審查）：舊版快取只看檔案存在，model_size/initial_prompt
        # 變了（詞庫累積成長後重跑）也照樣回舊結果。缺這兩個 key 的舊快取（本次修復前
        # 產生的）視為跟目前參數相容，不強迫重轉，只有明確記錄過、且對不上時才重轉。
        if cached.get("model_size", model_size) == model_size and cached.get(
            "initial_prompt", initial_prompt
        ) == initial_prompt:
            return cached

    language = "zh"
    model = _get_model(model_size)
    stable_result = model.transcribe(
        str(video_path),
        language=language,
        word_timestamps=True,
        vad_filter=True,  # faster-whisper 解碼前的靜音過濾（沿用原本設定）
        vad=True,  # stable-ts 自己的 Silero VAD 時間戳精修，是換用 stable-ts 的核心價值
        initial_prompt=initial_prompt,
        verbose=None,  # 不印逐句內容/進度條到 console，維持原本安靜的行為
    )

    words = []
    seg_list = []
    for seg in stable_result.segments:
        # stable-ts 回傳的 start/end 是 numpy.float64（numpy 底層雖可當一般 float 用，
        # 這裡明確轉型成原生 float，跟原本 faster-whisper 回傳的型別完全一致）。
        seg_list.append({"start": float(seg.start), "end": float(seg.end), "text": seg.text})
        if seg.words:
            for w in seg.words:
                words.append(
                    {
                        "word": w.word.strip(),
                        "start": float(w.start),
                        "end": float(w.end),
                        "prob": float(w.probability) if w.probability is not None else None,
                    }
                )

    result = {
        # 用 ffprobe 量到的實際媒體檔長度，語意對齊原本 faster-whisper info.duration
        # （stable-ts 的 WhisperResult.duration 是「最後一段結尾 - 第一段開頭」，掐頭去尾
        # 靜音後會比檔案實際長度短，不能直接拿來當這個欄位用）。
        "duration": ffmpeg_utils.duration_seconds(video_path),
        "language": language,
        "model_size": model_size,
        "initial_prompt": initial_prompt,
        "segments": seg_list,
        "words": words,
    }

    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
