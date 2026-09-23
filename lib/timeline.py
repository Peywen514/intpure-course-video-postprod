"""時間軸重映射：跳剪會壓縮時間軸（剪掉的區間消失，後面內容往前移）、片頭尾套用會
把整段影片往後平移一個片頭長度——這兩層轉換過去只套用在剪片本身（stage_jumpcut／
stage_bumper 產生的 mp4），沒有留下映射資訊給其他讀「原始轉錄時間軸」的階段用
（stage_translate 的字幕時間碼、stage_qa 的字幕對準比對），導致這兩階段對 final/
jumpcut 版本算出來的時間是錯的（2026-07-15 Fable5 審查 B1）。

這裡把 stage_jumpcut 算出的 keep_ranges、stage_bumper 的片頭時長落檔，
remap_events() 依「這次是對著哪個來源檔（captioned/jumpcut/final）算時間」
把事件時間轉成該檔案實際的時間軸。
"""

import json


def save_jumpcut_map(work_dir, keep_ranges):
    (work_dir / "jumpcut_map.json").write_text(
        json.dumps({"keep_ranges": keep_ranges}, ensure_ascii=False), encoding="utf-8"
    )


def _load_jumpcut_map(work_dir):
    path = work_dir / "jumpcut_map.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return [tuple(r) for r in data["keep_ranges"]]


def save_bumper_offset(work_dir, intro_duration):
    (work_dir / "bumper_offset.json").write_text(
        json.dumps({"intro_duration": intro_duration}, ensure_ascii=False), encoding="utf-8"
    )


def load_bumper_offset(work_dir):
    """讀回 save_bumper_offset() 存的片頭秒數，沒存過（還沒套過片頭）回 0.0。

    公開函式（原本是 remap_events() 內部私用，2026-09-10 因 stage_qa 的漏剪停頓
    檢查也需要片頭秒數才第二個呼叫端出現，改成公開，不重複寫一份讀檔邏輯）。
    """
    path = work_dir / "bumper_offset.json"
    if not path.exists():
        return 0.0
    return json.loads(path.read_text(encoding="utf-8"))["intro_duration"]


def remap_time(t, keep_ranges):
    """把原始（未剪）時間軸上的時間點 t，轉成跳剪後（壓縮過的）時間軸上的對應時間。
    t 落在被剪掉的空隙裡回傳 None。keep_ranges 須為依 start 排序、互不重疊的
    [(s, e), ...]（stage_jumpcut 的 _complement_ranges 輸出即符合此形狀）。
    """
    cursor = 0.0
    for s, e in keep_ranges:
        if t < s:
            return None
        if t <= e:
            return cursor + (t - s)
        cursor += e - s
    return None


def remap_events(events, source_stage, work_dir):
    """依 source_stage（"captioned" / "jumpcut" / "final"）把 events 的原始時間軸
    轉成該來源檔實際的時間軸；captioned 沒剪過、沒接片頭，原樣回傳。

    events: [(start, end, text), ...]。整句落在跳剪剪掉的區間、或跨越剪點導致頭尾
    對不上的事件會被捨棄（寧可漏掉一句不精確的，不要留一句時間錯的字幕）。

    回傳 (new_events, dropped_count)。
    """
    if source_stage == "captioned":
        return events, 0

    keep_ranges = _load_jumpcut_map(work_dir)
    offset = load_bumper_offset(work_dir) if source_stage == "final" else 0.0

    if keep_ranges is None:
        # 沒有 jumpcut_map.json：這集根本沒真的跑過跳剪（例如 jumpcut.mp4 是直接
        # 剪原始檔、或使用者手動指定了 video_filename），時間軸沒被壓縮，只需要
        # 套片頭位移。
        if offset == 0.0:
            return events, 0
        return [(s + offset, e + offset, t) for s, e, t in events], 0

    new_events = []
    dropped = 0
    for start, end, text in events:
        new_start = remap_time(start, keep_ranges)
        new_end = remap_time(end, keep_ranges)
        if new_start is None or new_end is None or new_end <= new_start:
            dropped += 1
            continue
        new_events.append((new_start + offset, new_end + offset, text))
    return new_events, dropped


if __name__ == "__main__":
    # 原始時間軸 0-30s，剪掉 10-15s（第 5 秒的贅詞），keep_ranges = [(0,10), (15,30)]。
    keep = [(0.0, 10.0), (15.0, 30.0)]
    assert remap_time(5.0, keep) == 5.0          # 剪點之前，原封不動
    assert remap_time(20.0, keep) == 15.0         # 剪點之後，往前推 5 秒（剪掉的長度）
    assert remap_time(12.0, keep) is None          # 落在被剪掉的區間裡

    events = [(2.0, 4.0, "保留"), (11.0, 13.0, "被剪掉"), (18.0, 20.0, "剪後片段")]
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        save_jumpcut_map(work_dir, keep)
        remapped, dropped = remap_events(events, "jumpcut", work_dir)
        assert dropped == 1
        assert remapped == [(2.0, 4.0, "保留"), (13.0, 15.0, "剪後片段")]

        save_bumper_offset(work_dir, 8.0)  # 片頭 8 秒
        remapped_final, dropped_final = remap_events(events, "final", work_dir)
        assert dropped_final == 1
        assert remapped_final == [(10.0, 12.0, "保留"), (21.0, 23.0, "剪後片段")]

        # captioned 版沒剪過、沒接片頭，原樣回傳
        remapped_cap, dropped_cap = remap_events(events, "captioned", work_dir)
        assert dropped_cap == 0 and remapped_cap == events

    print("lib/timeline.py 自我檢查通過")
