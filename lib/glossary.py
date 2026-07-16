"""錯字詞庫：累積使用者在字幕校對頁面做過的修正，自動套用到未來的轉錄結果，
並提示（不是重新訓練）語音辨識模型常見詞彙。

老實說明這不是「AI 自我學習」——沒有重新訓練模型，純粹是「記錄你修正過的詞 → 之後
自動找同樣的錯字直接換掉 + 把常見詞彙塞進 Whisper 的 initial_prompt 提示」。
效果類似（同樣的錯字之後不用再修一次），但機制是查表替換，不是模型真的變聰明。
"""

import difflib
import json
from pathlib import Path

GLOSSARY_PATH = Path(__file__).resolve().parent.parent / "corrections_glossary.json"


def load_glossary():
    if GLOSSARY_PATH.exists():
        return json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    return {}


def _save_glossary(glossary):
    GLOSSARY_PATH.write_text(
        json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def extract_diffs(original, corrected):
    """比對兩行文字，抓出實際被替換掉的片段，忽略沒變的部分。"""
    sm = difflib.SequenceMatcher(None, original, corrected)
    diffs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            wrong = original[i1:i2]
            right = corrected[j1:j2]
            if wrong and right and wrong != right:
                diffs.append((wrong, right))
    return diffs


def record_correction(original, corrected):
    """比對一行原文跟校正後文字，把差異片段記進詞庫（累加次數）。"""
    diffs = extract_diffs(original, corrected)
    if not diffs:
        return
    glossary = load_glossary()
    for wrong, right in diffs:
        entry = glossary.get(wrong)
        if entry:
            entry["count"] += 1
            entry["correct"] = right  # 用最新一次校正結果覆蓋
        else:
            glossary[wrong] = {"correct": right, "count": 1}
    _save_glossary(glossary)


def apply_glossary(text):
    """把文字裡已知的錯字片段換成校正後的版本。長片段優先比對，避免短片段先命中蓋掉長片段。

    只用於「已經斷好句、單行文字」的場合（例如校對頁面顯示個別調整過的一行）。
    正式產字幕走的是 apply_glossary_to_words（見下）——這個逐行版本有已知限制：
    如果錯字片段跨越了斷句邊界（一行結尾、下一行開頭各占一半），逐行比對永遠湊不出
    完整片段，修正不會生效。這正是 apply_glossary_to_words 要解決的問題。
    """
    glossary = load_glossary()
    if not glossary:
        return text
    for wrong in sorted(glossary, key=len, reverse=True):
        if wrong in text:
            text = text.replace(wrong, glossary[wrong]["correct"])
    return text


def _merge_term(ws, pattern, replacement):
    """在 ws（word dict 清單）裡找出所有完整出現 pattern 的片段，合併成一個 word
    （文字換成 replacement、時間範圍取被合併片段的頭尾）。pattern != replacement 時
    是錯字修正（見 apply_glossary_to_words）；pattern == replacement 時是「純合併、
    文字不變」，用於保護已知複合詞不被斷句腰斬（見 merge_protected_terms）——
    兩種用途共用同一套合併機制，差別只在傳入的 replacement 是不是同一個字串。
    """
    if not pattern:
        return ws
    search_from = 0
    guard = 0
    while guard < 200:  # 防呆：避免 replacement 本身又含 pattern 造成無限迴圈
        guard += 1
        joined = "".join(w["word"] for w in ws)
        hit = joined.find(pattern, search_from)
        if hit == -1:
            break

        # 找出被 [hit, hit+len(pattern)) 這段字元範圍覆蓋到的 word 索引範圍 [w1, w2]
        cursor = 0
        w1 = w2 = None
        for wi, w in enumerate(ws):
            wlen = len(w["word"])
            if w1 is None and cursor + wlen > hit:
                w1 = wi
            if cursor + wlen >= hit + len(pattern):
                w2 = wi
                break
            cursor += wlen
        if w1 is None or w2 is None:
            break  # 理論上不會發生（joined 是 ws 拼出來的），保守起見還是擋一下

        merged = {
            "word": replacement,
            "start": ws[w1]["start"],
            "end": ws[w2]["end"],
        }
        ws = ws[:w1] + [merged] + ws[w2 + 1 :]
        search_from = hit + len(replacement)
    return ws


def apply_glossary_to_words(words):
    """詞庫修正的字級（word-level）版本：在 group_words() 斷句「之前」，對整段逐字稿
    的完整拼接文字做已知錯字替換，取代舊版「斷句後對每行文字」的做法。

    為什麼要搬到這裡（bug 修正核心）：詞庫裡的錯字片段可能橫跨未來的斷句邊界
    （例如一行結尾是「雲」、下一行開頭是「端」）。斷句後才逐行套用 apply_glossary，
    兩行分開比對永遠湊不出完整的「雲端」子字串，修正就永遠不會生效。改成在斷句前
    對整段連續文字做替換，一段完整的多字詞就算未來會被斷句切開也吃得到。

    做法（手法借鏡 video-autopilot-kit word_captions.py 的 apply_fixes_to_words，
    資料結構是我們自己的 {word,start,end} dict，不是抄它的程式碼）：把整段逐字
    詞清單拼成一條文字，用長片段優先的 substring 比對找出命中範圍，命中範圍對應
    到的原始 word dict 們合併成一個新的 word（word=修正後文字、start=範圍內第一個
    字的 start、end=範圍內最後一個字的 end）。這樣即使修正後文字長度跟原本字數
    不一樣，這個合併後 word 的時間範圍仍然精確對應原始逐字時間戳涵蓋的區間，
    後面 group_words 斷句、算行時間時不會跑掉。

    words: [{"word": str, "start": float, "end": float}, ...]（whisper 逐字結果）。
    回傳：結構相同的新 list（不修改傳入的原始 list/dict）。
    """
    glossary = load_glossary()
    if not glossary:
        return [dict(w) for w in words]

    ws = [dict(w) for w in words]
    for wrong in sorted(glossary, key=len, reverse=True):
        correct = glossary[wrong]["correct"]
        ws = _merge_term(ws, wrong, correct)
    return ws


def learned_multichar_terms():
    """corrections_glossary.json 裡長度 >1 的正確詞。供斷句保護用（NEVER_SPLIT_TERMS
    的動態延伸，見 lib/ass_builder.py 的 _unsplittable_terms 與下面的
    merge_protected_terms），避免使用者手動在 config.py 重複登記已經校對過的複合詞。
    單字元修正（例如「藍」→「欄」）不需要保護，一個字不會有「從中間腰斬」的問題。
    """
    return [v["correct"] for v in load_glossary().values() if len(v["correct"]) > 1]


def merge_protected_terms(words, terms):
    """把 words 裡完整出現的 terms（例如 config.NEVER_SPLIT_TERMS + learned_multichar_terms()）
    合併成單一 token——文字不變，純粹讓這些已知複合詞在 group_words() 眼裡變成不可分割
    的單位。

    為什麼需要這一步：group_words() 逐字掃描時，判斷「這個斷點合不合格」只看得到即將
    加入的下一個 token；如果一個複合詞被 Whisper 拆成很細碎的單字 token，斷點檢查在
    腰斬詞的當下可能還沒讀到詞的後半段，就誤判成合格斷點（見 lib/ass_builder.py 開頭
    的已知限制說明）。跟 apply_glossary_to_words 一樣先把整段話合併好，group_words()
    看到的就已經是不可分割的單一 token，不用靠斷點檢查臨場判斷夠不夠準。

    呼叫順序建議在 apply_glossary_to_words 之後（見 lib/pipeline.py _base_events）：
    先修正錯字（產生的複合詞已經是單一 token），再合併其餘已知複合詞，語意上先修正
    再保護，也避免兩步處理到同一段文字時互相干擾。
    """
    ws = [dict(w) for w in words]
    for term in sorted({t for t in terms if len(t) > 1}, key=len, reverse=True):
        ws = _merge_term(ws, term, term)
    return ws


def get_prompt_hint(max_terms=30):
    """回傳給 Whisper initial_prompt 用的常見詞彙提示字串（依修正次數排序取前幾個）。"""
    glossary = load_glossary()
    if not glossary:
        return None
    terms = sorted(glossary.values(), key=lambda v: -v["count"])
    words = [t["correct"] for t in terms[:max_terms]]
    return "、".join(words) if words else None
