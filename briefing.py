#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""今夜の狙い目（夕方16:30に1通だけ送るブリーフィング）。

「何時に・どこへ行くと遠距離（10km以上）を引きやすいか」を時刻順に並べる。
材料:
  ・その日のイベント／学会（events.json ＋ EVENTS_PRIVATE。翌朝6時前の予定も含める）
  ・エスコンの試合（公式JSON。ナイターなら終了後の札幌方面）
  ・千歳空港の22時以降の到着便数
  ・天気（気象庁。雨・雪の夜はタクシーが足りなくなる）
  ・曜日と時間帯ごとの決まった狙い目（下の FIXED。外部の実データが無いので仮説）
本人の乗車記録が貯まったら FIXED を実データで置き換えていく。

単体で試す: python briefing.py [YYYY-MM-DD]
"""
import json, sys, urllib.request, ssl
from datetime import datetime, timezone, timedelta, date

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl.create_default_context()

JST = timezone(timedelta(hours=9))
WD = "月火水木金土日"

ESCON = "https://data.hkdballpark.com/json/esconfield_games.json"
JMA = "https://www.jma.go.jp/bosai/forecast/data/forecast/016000.json"   # 石狩・空知・後志
JMA_AREA = "016010"                                                       # 石狩地方（札幌）
HOLIDAYS = "https://holidays-jp.github.io/api/v1/date.json"
CTS_DOM = "https://www.hokkaido-airports.com/api/v1/new-chitose/static/fis/domestic/today.json"
CTS_INTL = "https://www.hokkaido-airports.com/api/v1/new-chitose/static/fis/international/today.json"

# 曜日と時間帯ごとの決まった狙い目。days は該当する曜日（0=月）、"eve" は翌日が休み（金土・祝前日）の夜だけ
FIXED = [
    # すすきの全般のような「当たり前の需要」は書かない（本人指示 2026-10-17）。
    # 店や建物の前など、ピンポイントで言える場所だけをここに置く。
    {"time": "4:00〜5:00", "days": "all",
     "text": "札幌駅周辺の大型ホテル（JRタワーホテル日航・京王プラザなど）→ 新千歳空港\n  始発便の客。JRは5:50まで無い／定額11,000円〜"},
]


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (taxi-notify-calendar)",
                                               "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
        return json.load(r)


def _hm(s):
    h, m = map(int, s.split(":"))
    return h * 60 + m


def _sort_key(t):
    """"23:00〜翌1:00" などを夕方→深夜の順に並べるためのキー（0〜5時台は翌日扱い）"""
    try:
        m = _hm(t.split("〜")[0].replace("翌", ""))
    except Exception:
        return 9999
    return m + 24 * 60 if m < 6 * 60 else m


def _clock(s):
    """"04:30" → "4:30"（固定の狙い目と表記をそろえる）"""
    h, m = s.split(":")
    return f"{int(h)}:{m}"


def is_day_off(d, holidays):
    return d.weekday() >= 5 or d.isoformat() in holidays


def weather_line(today):
    """今夜の天気と降水確率。雨・雪なら需要増の一言を付ける"""
    try:
        d = _get(JMA)[0]["timeSeries"]
    except Exception as e:
        print(f"[warn] 天気の取得失敗: {e}", file=sys.stderr)
        return None
    text = ""
    ts0 = d[0]
    area0 = next((a for a in ts0["areas"] if a["area"]["code"] == JMA_AREA), None)
    if area0:
        for t, w in zip(ts0["timeDefines"], area0["weathers"]):
            if t.startswith(today.isoformat()):
                text = w.replace("　", " ")
                break
    ts1 = d[1]
    area1 = next((a for a in ts1["areas"] if a["area"]["code"] == JMA_AREA), None)
    pops = []
    if area1:
        tomorrow = (today + timedelta(days=1)).isoformat()
        for t, p in zip(ts1["timeDefines"], area1["pops"]):
            if t.startswith(f"{today.isoformat()}T18") or t.startswith(f"{tomorrow}T00"):
                if p != "":
                    pops.append(int(p))
    pop = max(pops) if pops else None
    if not text and pop is None:
        return None
    s = f"🌦 {text or '天気不明'}"
    if pop is not None:
        s += f"（夜の降水確率 {pop}%）"
    wet = ("雪" in text) or ("雨" in text and (pop or 0) >= 50)
    if wet:
        s += "\n→ 雨・雪の夜は歩く人が乗る。どこも需要増"
    return s


def escon_lines(today, events_today):
    if any("エスコン" in (e.get("venue", "") + e.get("title", "")) for e in events_today):
        return []                                   # events.json 側にあれば二重に出さない
    try:
        games = _get(ESCON)
    except Exception as e:
        print(f"[warn] エスコン日程の取得失敗: {e}", file=sys.stderr)
        return []
    out = []
    for g in games:
        if g.get("gameDate") != today.isoformat() or not g.get("gameTime"):
            continue
        start = _hm(g["gameTime"])
        end = start + 3 * 60                         # 試合はだいたい3時間
        vs = g.get("visitorTeamName") or ""
        t = f"{end // 60}:{end % 60:02d}〜{end // 60 + 1}:{end % 60:02d}"
        out.append((t, f"エスコン（{vs}戦の終了）→ 札幌方面 約20km・深夜なら8,000円台"))
    return out


def flight_line(today):
    n, last = 0, None
    for url in (CTS_DOM, CTS_INTL):
        try:
            data = _get(url)
        except Exception:
            continue
        for it in data.get("items", []):
            if it.get("DA") != "A" or it.get("SYMD", today.isoformat()) != today.isoformat():
                continue
            st = it.get("ST")
            if st and _hm(st) >= 22 * 60:
                n += 1
                if last is None or _hm(st) > _hm(last):
                    last = st
    if not n:
        return None
    return f"✈ 千歳 22時以降の到着予定 {n}便（最終 {last}）。遅れたら別途すぐ知らせます"


def event_lines(today, events):
    """今日の夕方〜夜のイベントと、翌朝6時前の予定（学会翌朝の空港行きなど）"""
    tomorrow = (today + timedelta(days=1)).isoformat()
    out = []
    for e in events:
        d, start = e.get("date"), e.get("start")
        if not start:
            continue
        if d == today.isoformat():
            pass
        elif d == tomorrow and _hm(start) < 6 * 60:
            pass
        else:
            continue
        venue = e.get("venue", "")
        place = venue.split("（")[0] if venue else ""
        if e.get("remind_at") and e["remind_at"] != start:
            # ライブ等は始まりより終わりが稼ぎ時。remind_at を終演前後の目安として出す
            t = f"{_clock(e['remind_at'])}〜"
            game = " vs " in e["title"] or "VS" in e["title"]
            txt = (f"{e['title']}（{start}試合開始）の試合終了前後｜{place}" if game
                   else f"{e['title']}（{start}開演）の終演前後｜{place}")
        else:
            t, txt = f"{_clock(start)}〜", f"{e['title']}｜{place}"
        out.append((t, txt))
    return out


def build(now=None, events=None):
    now = now or datetime.now(JST)
    # 0〜5時台に呼ばれた場合も「今夜」は前日の夕方から始まる勤務として扱う
    today = (now - timedelta(hours=6)).date()
    events = events or []
    try:
        holidays = _get(HOLIDAYS)
    except Exception:
        holidays = {}
    eve = is_day_off(today + timedelta(days=1), holidays)

    items = []
    todays_events = [e for e in events if e.get("date") == today.isoformat()]
    items += event_lines(today, events)
    items += escon_lines(today, todays_events)
    for f in FIXED:
        if f["days"] == "eve" and not eve:
            continue
        items.append((f["time"], f["text"]))
    items.sort(key=lambda x: _sort_key(x[0]))

    head = f"🎯 今夜の狙い目 {today:%-m/%-d}（{WD[today.weekday()]}）"
    if eve:
        head += " 明日休みの人が多い夜"
    lines = [head]
    w = weather_line(today)
    if w:
        lines.append(w)
    if today.month == 12:
        lines.append("🍻 忘年会シーズン：週末の深夜は特に足りない")
    lines.append("")
    for t, txt in items:
        lines.append(f"▶ {t}\n  {txt}")
    fl = flight_line(today)
    if fl:
        lines.append("")
        lines.append(fl)
    return "\n".join(lines)


if __name__ == "__main__":
    import run
    now = datetime.now(JST)
    if len(sys.argv) > 1:
        d = date.fromisoformat(sys.argv[1])
        now = datetime(d.year, d.month, d.day, 16, 30, tzinfo=JST)
    print(build(now, run.load_events()))
