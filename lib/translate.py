"""字幕翻譯：把已校對好的中文字幕（跟 stage_captions/stage_qa 同一份 _base_events 斷句
結果）逐句丟給翻譯引擎，輸出跟原文同一組時間碼的 .srt——只換文字，不燒錄進影片，呼應
docs/handbook_同類產品比較_HelloIrene.md「同一組時間碼，換一種語言就好，時間碼零位移」
的需求描述。

引擎選擇見 config.py TRANSLATE_ENGINE 旁的說明（Google Cloud Translation API，因為
DeepL API Free 已經停止開放新申請）。要加新引擎：在 _ENGINES 註冊一個 _call_xxx(texts,
target_lang, source_lang, api_key) -> list[str]，回傳順序要跟傳入的 texts 一致。
"""

import json
import urllib.error
import urllib.request

_GOOGLE_API_URL = "https://translation.googleapis.com/language/translate/v2"


class TranslateError(RuntimeError):
    pass


def _call_google(texts, target_lang, source_lang, api_key):
    payload = json.dumps({
        "q": texts,
        "target": target_lang,
        "source": source_lang,
        "format": "text",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{_GOOGLE_API_URL}?key={api_key}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise TranslateError(f"Google Translate API 回應錯誤（HTTP {e.code}）：{detail}") from e
    except urllib.error.URLError as e:
        raise TranslateError(f"Google Translate API 連線失敗：{e.reason}") from e
    return [item["translatedText"] for item in body["data"]["translations"]]


_ENGINES = {"google": _call_google}


def translate_texts(texts, target_lang, source_lang, engine, api_key):
    """texts: 要翻譯的文字清單，保持順序。回傳翻譯後的文字清單，順序、長度都跟輸入一致。
    空字串（理論上不該出現在斷句結果裡，但保守處理）直接跳過，不送進 API，避免部分
    引擎對空字串報錯。
    """
    if not api_key:
        raise TranslateError("缺少翻譯 API 金鑰，請設定環境變數 GOOGLE_TRANSLATE_API_KEY")
    if engine not in _ENGINES:
        raise TranslateError(f"不支援的翻譯引擎：{engine}（目前只有：{', '.join(_ENGINES)}）")

    non_empty = [i for i, t in enumerate(texts) if t.strip()]
    if not non_empty:
        return list(texts)

    translated = _ENGINES[engine]([texts[i] for i in non_empty], target_lang, source_lang, api_key)

    result = list(texts)
    for idx, t in zip(non_empty, translated):
        result[idx] = t
    return result


def _srt_timestamp(seconds):
    total_ms = round(seconds * 1000)
    hours, total_ms = divmod(total_ms, 3600_000)
    minutes, total_ms = divmod(total_ms, 60_000)
    secs, ms = divmod(total_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt(events, translated_texts):
    """events: [(start, end, original_text), ...]（跟 lib/ass_builder.py 吃的斷句格式一致）。
    translated_texts: 跟 events 一一對應、順序一致的翻譯後文字。回傳 SRT 檔內容字串。
    """
    lines = []
    for i, ((start, end, _original), text) in enumerate(zip(events, translated_texts), start=1):
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)
