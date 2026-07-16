"""逐字時間戳 -> 斷句分行 -> ASS 字幕檔。

斷句分行邏輯（改寫自 video-autopilot-kit word_captions.py 的手法概念，非複製其程式碼）：
依「詞間停頓夠長」或「單行字數超過上限」兩個條件切斷句，讓字幕行不會過長也不會在
講者換氣的地方被硬接在一起。

在這兩個硬條件之上，另外做斷點品質控管（見 _eligible_break）：硬斷點如果會腰斬
「不能斷開的詞」（config.NEVER_SPLIT_TERMS 手動登記的 + corrections_glossary.json
裡使用者校對學到、長度 > 1 的正確詞，見 _unsplittable_terms）、讓下一行以虛詞開頭、
或把連接詞留在行尾，就往前回溯找上一個「合格」的斷點；回溯不到（例如整段話中間
完全沒有空隙可退）就 fallback 維持原本的硬斷，不讓斷句因為找不到完美斷點而失敗或丟例外。
"""

from config import CONNECTIVE_WORDS, HEAD_DANGLER_CHARS, NEVER_SPLIT_TERMS
from lib.glossary import load_glossary


def _unsplittable_terms():
    """「不能從中間腰斬」的詞：config.NEVER_SPLIT_TERMS（複合詞/專有名詞）+ CONNECTIVE_WORDS
    （連接詞本身也不該被斷句從中間切開，例如「所以」不能斷成「所」|「以」，否則回溯找斷點
    時，為了不把連接詞留在行尾，反而把連接詞自己切成兩半，比原本的硬斷還糟）。

    再加上 corrections_glossary.json 裡使用者校對過、長度 > 1 的正確詞——多字修正結果
    代表系統已經「認得」這是一個完整詞，理當跟 NEVER_SPLIT_TERMS 一樣受保護，不用使用者
    在 config.py 重複手動登記一次；單一字元的修正（例如「藍」→「欄」）不需要保護，一個字
    不會有「從中間腰斬」的問題。刻意不快取、每次呼叫都重新讀檔：glossary 檔案很小，
    group_words() 一個集數只呼叫一次，沒必要為了效能犧牲「校對完下一次產字幕就生效」。
    """
    learned = [v["correct"] for v in load_glossary().values() if len(v["correct"]) > 1]
    return list(NEVER_SPLIT_TERMS) + list(CONNECTIVE_WORDS) + learned


def _splits_unsplittable_term(left_text, right_text, unsplittable_terms):
    """判斷斷點是不是剛好卡在 unsplittable_terms 裡某個詞的中間：詞的前半段落在
    斷點左邊文字的尾端、後半段落在斷點右邊文字的開頭，兩段都非空才算腰斬。"""
    for term in unsplittable_terms:
        for p in range(1, len(term)):
            prefix, suffix = term[:p], term[p:]
            if left_text.endswith(prefix) and right_text.startswith(suffix):
                return True
    return False


def _eligible_break(left_text, right_text, unsplittable_terms):
    """斷點兩側文字（左邊到斷點為止、右邊從斷點開始）是否「合格」：
    不腰斬複合詞/連接詞本身、下一行不以虛詞開頭、完整的連接詞不留在行尾。"""
    if not left_text or not right_text:
        return False
    if _splits_unsplittable_term(left_text, right_text, unsplittable_terms):
        return False
    if right_text[0] in HEAD_DANGLER_CHARS:
        return False
    if any(left_text.endswith(word) for word in CONNECTIVE_WORDS):
        return False
    return True


def group_words(words, max_chars=24, max_gap=0.6):
    """把逐字 {word,start,end} 清單分組成字幕行 [(start, end, text), ...]。

    注意：詞庫修正（glossary）要在呼叫這個函式「之前」對逐字資料做好（見
    lib/glossary.py 的 apply_glossary_to_words），這裡只負責斷句，不做文字修正——
    避免修正跟斷句的責任混在一起，兩者可以獨立測試。
    """
    events = []
    buf = []  # 目前正在累積、還沒斷句的 word dict 清單
    unsplittable_terms = _unsplittable_terms()  # 每個集數呼叫一次，讀當下最新的 glossary

    def _text(ws):
        return "".join(w["word"] for w in ws)

    def flush(upto=None):
        """upto=None 表示整個 buf 都收進這一行；upto=k 表示只收 buf[:k+1]，
        剩下的 buf[k+1:] 留著繼續累積（回溯斷點用）。"""
        nonlocal buf
        take = buf if upto is None else buf[: upto + 1]
        rest = [] if upto is None else buf[upto + 1 :]
        if take:
            text = _text(take).strip()
            if text:  # 純空白/無內容的斷句（例如呼吸音token）不產生字幕事件
                events.append((take[0]["start"], take[-1]["end"], text))
        buf = rest

    def _break_ok(k, pending_text):
        """buf[k] 與 buf[k+1] 之間的斷點是否合格。pending_text 是即將接在 buf[k+1:]
        後面的下一個字（還沒 append 進 buf，但 flush(k) 之後一定會緊接著加進去）——
        沒把它算進 right_text 的話，backtrack 檢查腰斬詞時只看得到 buf 目前剩下的
        半截，會漏掉「詞的後半段其實是下一個還沒進 buf 的字」這種情況。"""
        left_text = _text(buf[: k + 1])
        right_text = _text(buf[k + 1 :]) + pending_text
        return _eligible_break(left_text, right_text, unsplittable_terms)

    def _backtrack(pending_text):
        """從目前 buf 尾端往回找一個合格斷點的索引 k（buf[k]|buf[k+1] 是斷點）。
        找不到回傳 None，呼叫端會 fallback 維持原本的硬斷，不讓斷句失敗。"""
        for k in range(len(buf) - 2, -1, -1):
            if _break_ok(k, pending_text):
                return k
        return None

    for w in words:
        word_text = w["word"]
        if not word_text or not word_text.strip():
            continue

        gap = (w["start"] - buf[-1]["end"]) if buf else 0
        line_len = len(_text(buf)) + len(word_text)

        if buf and (gap > max_gap or line_len > max_chars):
            # 硬斷點就卡在 buf 最後一個字跟即將加入的 w 之間，先看這個位置本身合不合格。
            if _eligible_break(_text(buf), word_text, unsplittable_terms):
                flush()
            else:
                k = _backtrack(word_text)
                if k is not None:
                    flush(k)
                else:
                    flush()  # 找不到更合適的斷點，fallback 維持原本的硬斷

        buf.append(w)

    flush()
    return events


def _ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _style_line(style):
    fields = [
        "Name", "Fontname", "Fontsize", "PrimaryColour", "OutlineColour",
        "BackColour", "Bold", "Italic", "Underline", "StrikeOut",
        "ScaleX", "ScaleY", "Spacing", "Angle", "BorderStyle", "Outline",
        "Shadow", "Alignment", "MarginL", "MarginR", "MarginV", "Encoding",
    ]
    values = ",".join(str(style[f]) for f in fields)
    return f"Style: {values}"


def build_ass(events, style, play_res=(1920, 1080)):
    """events: [(start, end, text), ...] -> 回傳 .ass 檔內容字串。"""
    res_x, res_y = play_res
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {res_x}\n"
        f"PlayResY: {res_y}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{_style_line(style)}\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = []
    for start, end, text in events:
        text = text.replace("\n", "\\N")
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style['Name']},,0,0,0,,{text}"
        )

    return header + "\n".join(lines) + "\n"


def merge_style(defaults, override=None):
    """把 style_override.json（若存在）疊在 config 預設值上。"""
    merged = dict(defaults)
    if override:
        for key in ("MarginV", "MarginL", "MarginR", "Spacing", "Fontsize"):
            if key in override:
                merged[key] = override[key]
    return merged
