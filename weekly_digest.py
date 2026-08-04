#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""週間イベントダイジェスト。
毎週日曜夜に「翌 月〜日」のイベントをカレンダー形式でLINE送信する。
範囲は環境変数 DIGEST_FROM / DIGEST_TO（YYYY-MM-DD）または引数 --from/--to で上書き可。
"""
import os, sys, json, pathlib
from datetime import datetime, timezone, timedelta, date

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import notify

JST = timezone(timedelta(hours=9))
EVENTS = ROOT / "events.json"
WD = ["月", "火", "水", "木", "金", "土", "日"]

def load_events():
    try:
        return json.loads(EVENTS.read_text("utf-8"))
    except Exception:
        return []

def arg(flag):
    a = sys.argv
    return a[a.index(flag) + 1] if flag in a and a.index(flag) + 1 < len(a) else None

def upcoming_week(now):
    """翌 月曜〜日曜（今日が月曜ならその週）"""
    wd = now.weekday()                      # 月=0 … 日=6
    mon = now.date() if wd == 0 else now.date() + timedelta(days=(7 - wd) % 7)
    return mon, mon + timedelta(days=6)

def build_message(d_from, d_to, events):
    span = "今週" if (d_to - d_from).days >= 5 else "直近"
    head = f"🗓 {span}のイベント（{d_from.month}/{d_from.day}〜{d_to.month}/{d_to.day}）"
    lines = [head, ""]
    by_date = {}
    for e in events:
        by_date.setdefault(e.get("date"), []).append(e)
    d = d_from
    total = 0
    while d <= d_to:
        iso = d.isoformat()
        lines.append(f"▼ {d.month}/{d.day}({WD[d.weekday()]})")
        evs = sorted(by_date.get(iso, []), key=lambda e: e.get("start", ""))
        if not evs:
            lines.append("　（予定なし）")
        for e in evs:
            total += 1
            t = e.get("start", "")
            lines.append(f"　{t} {e['title']}")
            if e.get("venue"):
                lines.append(f"　　📍{e['venue']}")
            if e.get("note"):
                lines.append(f"　　💡{e['note']}")
        d += timedelta(days=1)
    lines.append("")
    lines.append("🚕 終了時間帯は先回りで待機を。" if total else "🚕 大きめのイベントは今のところ無し。")
    return "\n".join(lines)

def main():
    now = datetime.now(JST)
    f = arg("--from") or os.environ.get("DIGEST_FROM") or ""
    t = arg("--to") or os.environ.get("DIGEST_TO") or ""
    if f.strip() and t.strip():
        d_from = date.fromisoformat(f.strip())
        d_to = date.fromisoformat(t.strip())
    else:
        d_from, d_to = upcoming_week(now)
    text = build_message(d_from, d_to, load_events())
    if "--send" in sys.argv:
        ok = notify.send(text)
        print("digest sent:", ok)
    else:
        print(text)

if __name__ == "__main__":
    main()
