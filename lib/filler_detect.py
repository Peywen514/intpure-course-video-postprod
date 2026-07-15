"""贅詞偵測：在逐字 token 清單裡找固定詞表，容錯處理「詞可能被切成多個 token」
（實測 faster-whisper 中文詞有時整詞成一個 token，如「這個」，有時會拆成單字）。
"""

CONTEXT_WINDOW = 5  # 前後各抓幾個 token 當上下文


def find_phrase_matches(words, phrase):
    """在 words（逐字 token 清單）裡找 phrase（例如 "那個"），
    回傳 [(start_idx, end_idx, start_time, end_time), ...]，end_idx 為最後一個 token 的 index（含）。
    容錯：phrase 可能剛好對應一個 token，也可能橫跨多個 token 拼起來才等於 phrase。
    """
    matches = []
    i = 0
    n = len(words)
    while i < n:
        acc = ""
        j = i
        while j < n and len(acc) < len(phrase):
            acc += words[j]["word"]
            j += 1
        if acc == phrase:
            matches.append((i, j - 1, words[i]["start"], words[j - 1]["end"]))
            i = j  # 跳過已匹配的 token，避免重疊
        else:
            i += 1
    return matches


def context_text(words, start_idx, end_idx, window=CONTEXT_WINDOW):
    before = "".join(w["word"] for w in words[max(0, start_idx - window):start_idx])
    after = "".join(w["word"] for w in words[end_idx + 1:end_idx + 1 + window])
    return before, after


def detect(words, auto_cut_phrases, flag_only_phrases):
    """回傳 {"auto_cut": [...], "flagged": [...]}"""
    auto_cut = []
    for phrase in auto_cut_phrases:
        for start_idx, end_idx, start_t, end_t in find_phrase_matches(words, phrase):
            auto_cut.append({"word": phrase, "start": start_t, "end": end_t})

    flagged = []
    for phrase in flag_only_phrases:
        for start_idx, end_idx, start_t, end_t in find_phrase_matches(words, phrase):
            before, after = context_text(words, start_idx, end_idx)
            flagged.append(
                {
                    "word": phrase,
                    "start": start_t,
                    "end": end_t,
                    "context_before": before,
                    "context_after": after,
                    "reason": "ambiguous_filler",
                }
            )

    auto_cut.sort(key=lambda x: x["start"])
    flagged.sort(key=lambda x: x["start"])
    return {"auto_cut": auto_cut, "flagged": flagged}
