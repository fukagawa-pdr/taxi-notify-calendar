#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北海道・列車遅延チェッカー（機能③）
Yahoo!運行情報(北海道)を取得し「平常運転でない」路線を抽出する。
JR北海道・札幌市営地下鉄・市電・道南いさりび鉄道までまとめて拾える。
"""
import urllib.request, re, ssl, sys
try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl.create_default_context()

URL = "https://transit.yahoo.co.jp/diainfo/area/2"

# 各路線の行は  <tr><td><a href="/diainfo/ID/SUB">路線名</a></td><td>状態</td><td>詳細</td></tr>
ROW_RE = re.compile(
    r'<tr>\s*<td>\s*<a href="/diainfo/\d+/\d+"[^>]*>([^<]+)</a>\s*</td>'
    r'\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>', re.S)

def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20, context=_SSL) as r:
        return r.read().decode("utf-8", "replace")

def strip(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def check(debug=False):
    h = fetch()
    rows = ROW_RE.findall(h)   # (路線名, 状態, 詳細)
    alerts, lines = [], []
    for name, status, detail in rows:
        name, status, detail = name.strip(), strip(status), strip(detail)
        lines.append((name, status, detail))
        if status != "平常運転":       # 平常以外はすべて拾う（取りこぼし防止）
            alerts.append({"line": name, "status": status, "detail": detail})
    if debug:
        print(f"[debug] 取得路線 {len(lines)}件:")
        for n, st, dt in lines:
            print(f"   {'平常' if st == '平常運転' else '⚠'} {n} … {st} / {dt}")
    return alerts

def format_msg(a):
    detail = f"\n{a['detail']}" if a.get("detail") and "ありません" not in a["detail"] else ""
    return f"🚆 {a['line']}：{a['status']}{detail}\n🚕 タクシー需要↑の可能性"

if __name__ == "__main__":
    debug = "--debug" in sys.argv
    al = check(debug=debug)
    if not al:
        print("該当なし（北海道の主要路線は平常運転）")
    for a in al:
        print("-" * 30)
        print(format_msg(a))
