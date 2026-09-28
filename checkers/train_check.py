#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列車の遅延・運休チェッカー（JR北海道 + 札幌市営地下鉄）

■ なぜYahoo!運行情報をやめたか（2026-09-04 改修）
Yahoo!路線情報のヘルプに、配信されない条件として次が明記されている:
  ・「当該列車1本のみ影響する場合」
  ・「遅延の対象が終列車の場合」
  ・掲載基準は首都圏JR以外は「30分以上の遅延」
つまり **終電の遅れは仕様上ぜったいに流れてこない**。
タクシー的に一番おいしい「終電が乱れて駅に人が溢れる」を、
旧実装は構造的に検知できていなかった（実際に一度も鳴っていない）。

■ 代わりに使うもの
1) JR北海道が自社サイトの裏で使っているJSON。**列車単位**で
   「どの列車が・どこ発何時・どこ着何時・どういう状況か」が取れる。
   例) {"name":"普通列車","haEki":"室蘭","haTime":"21:27",
        "toEki":"長万部","toTime":"23:18","jokyo":"部分運休 (東室蘭～長万部 間)"}
2) 札幌市営地下鉄の運行情報。路線単位だが、すすきの・大通の
   終電後needsに直結する南北線を含む3路線がHTML1本で取れる。

※ どちらも公式に外部公開されたAPIではなく、サイトが内部で使っている
   エンドポイント。個人の需要把握用途に留め、短間隔で叩かないこと。
"""
import json, re, ssl, sys, urllib.request

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl.create_default_context()

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

# 札幌近郊の線区だけ見る（道東・道北まで拾うとタクシーに関係ない通知が増える）
JR_SENKU = {
    "01": "特急列車",
    "02": "快速エアポート",
    "03": "函館・千歳線",
    "04": "学園都市線",
}
JR_URL = "https://www3.jrhokkaido.co.jp/webunkou/json/senku/senku_{}.json"
SUBWAY_URL = "https://operationstatus.city.sapporo.jp/unkojoho/top.html"

# これ以降に発車する列車を「終電帯」とみなす。
# 正確な終電時刻表を持たなくても、23時以降＝最終近辺という近似で実用上足りる。
LATE_FROM_MIN = 23 * 60
LATE_UNTIL_MIN = 2 * 60      # 翌2:00まで（0時台の列車も終電帯として扱う）


def _get(url, as_json=True):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20, context=_SSL) as r:
        raw = r.read().decode("utf-8", "replace").lstrip("﻿")
    return json.loads(raw) if as_json else raw


def _hhmm_to_min(s):
    m = re.match(r"^(\d{1,2}):(\d{2})$", (s or "").strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def is_late_train(hatime):
    """その列車が「終電帯」に入っているか。"""
    v = _hhmm_to_min(hatime)
    if v is None:
        return False
    return v >= LATE_FROM_MIN or v < LATE_UNTIL_MIN


def check_jr(debug=False):
    alerts = []
    for code, label in JR_SENKU.items():
        try:
            d = _get(JR_URL.format(code))
        except Exception as e:
            print(f"[warn] JR {label} 取得失敗: {e}", file=sys.stderr)
            continue
        today = d.get("today") or {}
        for key, kind in (("unkyuTrains", "運休"), ("chienTrains", "遅延")):
            trains = today.get(key) or []
            if debug:
                print(f"[debug] JR {label} {kind}: {len(trains)}件")
            for t in trains:
                ha, to = t.get("haTime", ""), t.get("toTime", "")
                late = is_late_train(ha)
                alerts.append({
                    "id": f"jr:{code}:{kind}:{t.get('name','')}:{t.get('haEki','')}:{ha}",
                    "src": "jr", "line": label, "kind": kind,
                    "train": t.get("name", "列車"),
                    "ha_eki": t.get("haEki", ""), "ha_time": ha,
                    "to_eki": t.get("toEki", ""), "to_time": to,
                    "status": (t.get("jokyo") or kind).strip(),
                    "late": late,
                })
    return alerts


SUBWAY_RE = re.compile(
    r'tc_line"[^>]*>([^<]+)<.*?tc_mark\s+(status_\w+).*?tc_text"[^>]*>([^<]+)<', re.S)


def check_subway(debug=False):
    alerts = []
    try:
        html = _get(SUBWAY_URL, as_json=False)
    except Exception as e:
        print(f"[warn] 地下鉄 取得失敗: {e}", file=sys.stderr)
        return alerts
    found = SUBWAY_RE.findall(html)
    if debug:
        for line, mark, text in found:
            print(f"[debug] 地下鉄 {line}: {mark} / {text.strip()}")
    for line, mark, text in found:
        text = text.strip()
        if mark == "status_o" or "平常" in text:
            continue                     # 平常運転はスルー
        alerts.append({
            "id": f"subway:{line}:{text}",
            "src": "subway", "line": f"地下鉄{line}", "kind": "運行情報",
            "status": text, "late": False,
        })
    return alerts


def check(debug=False, late_only=True):
    """既定は late_only=True。
    本人の指示（2026-09-29）で「電車は終電のみでいい」。昼間の特急運休などは
    タクシー需要に結びつかないので通知しない。地下鉄は路線単位でしか状態が
    取れないため、終電帯の判定ができない代わりに常に対象とする。"""
    alerts = check_jr(debug=debug) + check_subway(debug=debug)
    if late_only:
        alerts = [a for a in alerts if a.get("late") or a["src"] == "subway"]
    return alerts


def format_msg(a):
    if a["src"] == "subway":
        return (f"🚇 {a['line']}：{a['status']}\n"
                f"🚕 駅周辺でタクシー需要↑")
    mark = "🌙 終電帯" if a.get("late") else "🚆"
    区間 = ""
    if a.get("ha_eki"):
        区間 = f"\n{a['ha_eki']} {a['ha_time']} → {a.get('to_eki','')} {a.get('to_time','')}".rstrip()
    tail = "\n🚕 駅に人が滞留 → 今すぐ駅へ" if a.get("late") else "\n🚕 タクシー需要↑の可能性"
    return f"{mark} [{a['line']}] {a['train']} {a['kind']}{区間}\n{a['status']}{tail}"


if __name__ == "__main__":
    debug = "--debug" in sys.argv
    late = "--late" in sys.argv
    al = check(debug=debug, late_only=late)
    if not al:
        print("該当なし（札幌近郊のJR・地下鉄は平常）")
    for a in al:
        print("-" * 34)
        print(format_msg(a))
