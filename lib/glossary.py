"""錯字詞庫：累積使用者在字幕校對頁面做過的修正，自動套用到未來的轉錄結果，
並提示（不是重新訓練）語音辨識模型常見詞彙。

老實說明這不是「AI 自我學習」——沒有重新訓練模型，純粹是「記錄你修正過的詞 → 之後
自動找同樣的錯字直接換掉 + 把常見詞彙塞進 Whisper 的 initial_prompt 提示」。
效果類似（同樣的錯字之後不用再修一次），但機制是查表替換，不是模型真的變聰明。
"""

import difflib
import json
import re
from pathlib import Path

GLOSSARY_PATH = Path(__file__).resolve().parent.parent / "corrections_glossary.json"

_CONTAINS_DIGITS_OR_PUNCT_RE = re.compile(
    r"[\d\s\W\._、，。！？；：,!\?\-\+\=\*\/\(\)\[\]\{\}\<\>]", re.UNICODE
)

_COMMON_STOP_CHARS = set("的的了是在就會這那個一我你他成與和及也都要能改被把讓用給由各條個圖來助即")


def load_glossary():
    if GLOSSARY_PATH.exists():
        return json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    return {}


def _save_glossary(glossary):
    GLOSSARY_PATH.write_text(
        json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _is_valid_term_pair(wrong, right):
    """檢查是否為合法的專有名詞/詞彙修正對。

    防範單字元替換（如「一」→「1」、「3」→「會」）、標點、數字或整句重寫造成的全域亂套用。
    """
    if not wrong or not right:
        return False
    wrong = wrong.strip()
    right = right.strip()
    if wrong == right:
        return False

    # 長度必須在 2 到 8 個字之間（避免單字元誤換，也避免長句重寫）
    if len(wrong) < 2 or len(right) < 2:
        return False
    if len(wrong) > 8 or len(right) > 8:
        return False

    # 不能包含數字、標點符號或空白
    if _CONTAINS_DIGITS_OR_PUNCT_RE.search(wrong) or _CONTAINS_DIGITS_OR_PUNCT_RE.search(right):
        return False

    is_wrong_ascii = wrong.isalnum() and wrong.isascii()
    is_right_ascii = right.isalnum() and right.isascii()

    if is_wrong_ascii or is_right_ascii:
        # 包含英文/縮寫的專有名詞對（如 ISO -> Excel）
        if not wrong.isalnum() or not right.isalnum():
            return False
        return True

    # 中文對中文的錯別字/同音字/專有名詞修正：音節數與字數必須相等，且不能全由虛詞組成
    if len(wrong) != len(right):
        return False
    if all(c in _COMMON_STOP_CHARS for c in wrong) or all(c in _COMMON_STOP_CHARS for c in right):
        return False

    return True



def extract_diffs(original, corrected):
    """比對兩行文字，抓出實際被替換掉的片段，忽略沒變的部分與單字元/標點雜訊。"""
    sm = difflib.SequenceMatcher(None, original, corrected)
    diffs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            wrong = original[i1:i2]
            right = corrected[j1:j2]
            if _is_valid_term_pair(wrong, right):
                diffs.append((wrong.strip(), right.strip()))
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
    """把文字裡已知的錯字片段換成校正後的版本。長片段優先比對。

    僅套用合法的多字元專有名詞修正，排除歷史單字元與標點雜訊。
    """
    glossary = load_glossary()
    if not glossary:
        return text
    valid_rules = [
        (wrong, glossary[wrong]["correct"])
        for wrong in glossary
        if _is_valid_term_pair(wrong, glossary[wrong]["correct"])
    ]
    for wrong, correct in sorted(valid_rules, key=lambda x: len(x[0]), reverse=True):
        if wrong in text:
            text = text.replace(wrong, correct)
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
    的完整拼接文字做已知錯字替換。

    僅套用合法的多字元專有名詞修正，防止單字元替換破壞正常轉錄結果。
    """
    glossary = load_glossary()
    if not glossary:
        return [dict(w) for w in words]

    valid_rules = [
        (wrong, glossary[wrong]["correct"])
        for wrong in glossary
        if _is_valid_term_pair(wrong, glossary[wrong]["correct"])
    ]

    ws = [dict(w) for w in words]
    for wrong, correct in sorted(valid_rules, key=lambda x: len(x[0]), reverse=True):
        ws = _merge_term(ws, wrong, correct)
    return ws


def learned_multichar_terms():
    """corrections_glossary.json 裡合法的繁體中文/專有名詞複合詞。供斷句保護用。"""
    glossary = load_glossary()
    terms = []
    for k, v in glossary.items():
        correct = v["correct"]
        if _is_valid_term_pair(k, correct):
            terms.append(correct)
    return terms


def merge_protected_terms(words, terms):
    """把 words 裡完整出現的 terms（例如 config.NEVER_SPLIT_TERMS + learned_multichar_terms()）
    合併成單一 token——文字不變，純粹讓這些已知複合詞在 group_words() 眼裡變成不可分割
    的單位。
    """
    ws = [dict(w) for w in words]
    for term in sorted({t for t in terms if len(t) > 1}, key=len, reverse=True):
        ws = _merge_term(ws, term, term)
    return ws


def get_prompt_hint(max_terms=20):
    """回傳給 Whisper initial_prompt 用的提示字串。

    結構化引導 Whisper 使用繁體中文進行轉錄，並帶入校對累積的正確專有名詞。
    """
    glossary = load_glossary()
    words = []
    if glossary:
        valid_entries = [
            v for k, v in glossary.items()
            if _is_valid_term_pair(k, v["correct"])
        ]
        terms = sorted(valid_entries, key=lambda v: -v["count"])
        seen = set()
        for t in terms[:max_terms]:
            w = t["correct"]
            if w not in seen:
                seen.add(w)
                words.append(w)

    base_prompt = "這是一段繁體中文的課程與影音剪輯教學影片，請統一使用繁體中文標點與術語。"
    if words:
        return f"{base_prompt}常見專有名詞包含：{'、'.join(words)}。"
    return base_prompt

