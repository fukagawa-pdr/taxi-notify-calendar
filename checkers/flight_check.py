#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新千歳空港・夜間の到着遅延チェッカー（機能②）
北海道エアポート公式の today.json を取得し、
「NIGHT_START 以降に千歳着 かつ 遅延/欠航」の便だけ抽出する。
"""
import json, urllib.request, ssl, sys
try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl.create_default_context()

DOM  = "https://www.hokkaido-airports.com/api/v1/new-chitose/static/fis/domestic/today.json"
INTL = "https://www.hokkaido-airports.com/api/v1/new-chitose/static/fis/international/today.json"

NIGHT_START = "22:00"     # これ以降に千歳着の便だけ対象
DELAY_MIN_THRESHOLD = 20  # 何分以上の遅れで通知するか（誤検知を避けるため20分）
BAD_KEYWORDS = ["欠航", "条件付", "引返", "目的地変更", "見合", "遅延"]

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20, context=_SSL) as r:
        return json.load(r)

def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

def delay_minutes(st, et):
    if not et:
        return 0
    d = to_min(et) - to_min(st)
    if d < -180:            # 日付跨ぎ (例 23:50 -> 00:20)
        d += 24 * 60
    return d

def check(debug=False, today=None):
    """today: "YYYY-MM-DD"。指定するとその日の便だけを対象にする（日付跨ぎの誤検知防止）"""
    alerts = []
    night = to_min(NIGHT_START)
    for url, kind in ((DOM, "国内"), (INTL, "国際")):
        try:
            data = fetch(url)
        except Exception as e:
            print(f"[warn] {kind}線 取得失敗: {e}", file=sys.stderr)
            continue
        night_arrivals = 0
        for it in data.get("items", []):
            if it.get("DA") != "A":
                continue                       # 到着便のみ
            if today and it.get("SYMD") and it["SYMD"] != today:
                continue                       # 当日の便のみ（0時以降に翌日便を拾わない）
            st = it.get("ST")
            if not st:
                continue
            et = it.get("ET_AT")
            # 定刻 or 実際の到着見込み のどちらかが NIGHT_START 以降なら対象。
            # 「21:30定刻 → 遅れて23:00着」を取りこぼさないため（旧実装は定刻だけで判定していた）
            eff = max(to_min(st), to_min(et) if et else 0)
            if eff < night:
                continue
            night_arrivals += 1
            a = (it.get("Airline") or [{}])[0]
            remark = a.get("Remark") or ""
            dmin = delay_minutes(st, et)
            bad = [k for k in BAD_KEYWORDS if k in remark]
            if dmin >= DELAY_MIN_THRESHOLD or bad:
                status = "／".join(bad) if bad else f"遅延 {dmin}分"
                alerts.append({
                    "id": str(it.get("NO")), "flight": a.get("Flight"),
                    "from": a.get("AreaName"), "st": st, "et": et,
                    "delay": dmin, "status": status, "kind": kind,
                })
        if debug:
            print(f"[debug] {kind}線: {NIGHT_START}以降の到着便 {night_arrivals}件 / updated={data.get('updated')}")
    return alerts

def format_msg(a):
    et = f" → {a['et']}" if a["et"] else ""
    return (f"✈️ 千歳 到着{a['status']}\n"
            f"[{a['kind']}] {a['flight']} {a['from']}→千歳\n"
            f"定刻 {a['st']}{et}")

if __name__ == "__main__":
    debug = "--debug" in sys.argv
    al = check(debug=debug)
    if not al:
        print(f"該当なし（{NIGHT_START}以降着の遅延/欠航は今のところ無し）")
    for a in al:
        print("-" * 30)
        print(format_msg(a))
