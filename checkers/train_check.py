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
        # 行く駅が出せない（札幌から遠い所だけの）乱れは通知しない。一晩4通の枠を無駄にしないため
        alerts = [a for a in alerts if a["src"] == "subway" or where_to_go(a)[0]]
    return alerts


# ---- 「どの駅へ行けばいいか」を出すための駅の位置関係（2026-10-17 本人の要望） ----
# 札幌駅から見てどちら側にあるか。W=小樽方面 / E=岩見沢・千歳方面 / N=学園都市線
# 側が違う2駅を結ぶ列車は札幌駅を通る＝札幌駅で待っている客がいる。
_SIDE = {}
for _side, _names in {
    "W": "桑園 琴似 発寒中央 発寒 稲積公園 手稲 稲穂 星置 ほしみ 銭函 朝里 小樽築港 南小樽 小樽 塩谷 蘭島 余市 仁木 然別 銀山 小沢 倶知安",
    "E": "苗穂 白石 厚別 森林公園 大麻 野幌 高砂 江別 豊幌 幌向 上幌向 岩見沢 峰延 光珠内 美唄 茶志内 奈井江 豊沼 砂川 滝川 深川 旭川 "
         "平和 新札幌 上野幌 北広島 島松 恵み野 恵庭 サッポロビール庭園 長都 千歳 南千歳 新千歳空港 植苗 沼ノ端 苫小牧 登別 東室蘭 室蘭 帯広 釧路 函館",
    "N": "八軒 新川 新琴似 太平 百合が原 篠路 拓北 あいの里教育大 あいの里公園 ロイズタウン 太美 石狩当別 北海道医療大学",
}.items():
    for _n in _names.split():
        _SIDE[_n] = _side

# 札幌から車で行ける範囲（ここに無い駅で止まった客は遠すぎて狙えない）
_NEAR = set("札幌 桑園 琴似 発寒中央 発寒 稲積公園 手稲 稲穂 星置 ほしみ 銭函 苗穂 白石 厚別 森林公園 大麻 野幌 高砂 江別 "
            "平和 新札幌 上野幌 北広島 八軒 新川 新琴似 太平 百合が原 篠路 拓北 あいの里教育大 あいの里公園".split())

# 札幌駅からのおおよその道のり（km）。10km以上が遠距離、40km以上が超遠距離
_KM = {"手稲": 12, "稲穂": 14, "星置": 16, "ほしみ": 17, "銭函": 22, "小樽築港": 33, "南小樽": 35, "小樽": 37, "余市": 58,
       "新札幌": 10, "上野幌": 14, "北広島": 20, "島松": 25, "恵み野": 28, "恵庭": 30, "長都": 35, "千歳": 38, "南千歳": 42,
       "新千歳空港": 45, "苫小牧": 60, "野幌": 17, "高砂": 19, "江別": 21, "幌向": 32, "岩見沢": 43,
       "あいの里教育大": 15, "あいの里公園": 16, "太美": 22, "石狩当別": 25, "北海道医療大学": 28}

# 地下鉄が乱れた時に客が溢れる乗換駅
_SUBWAY_HUBS = {"南北線": "さっぽろ・大通・すすきの", "東西線": "大通・バスセンター前・新さっぽろ",
                "東豊線": "さっぽろ・大通・福住"}


def _side(eki):
    return "S" if eki in ("札幌", "さっぽろ") else _SIDE.get(eki)


def _dest(eki, frm="札幌"):
    """行き先と、乗せる駅からのおおよその距離。同じ側の駅どうしは札幌からの距離の差で近似"""
    to_km = _KM.get(eki)
    if to_km is None:
        return f"{eki}方面"
    if _side(frm) == "S":
        km = to_km
    elif frm in _KM and _side(frm) == _side(eki):
        km = abs(to_km - _KM[frm])
    else:
        return f"{eki}方面"
    tag = "超遠距離" if km >= 40 else ("遠距離" if km >= 10 else "近距離")
    return f"{eki}方面（{frm}駅から約{km}km・{tag}）"


def where_to_go(a):
    """(行く駅, 客の行き先) を返す。狙えない時は (None, 理由)"""
    ha, to, st = a.get("ha_eki", ""), a.get("to_eki", ""), a.get("status", "")
    # 部分運休「(東室蘭～長万部 間)」→ 手前の駅で降ろされた客が残る
    m = re.search(r"[（(]\s*(\S+?)\s*[～~〜]\s*(\S+?)\s*間", st)
    if m and "運休" in st:
        stop = m.group(1)
        if stop in _NEAR or _side(stop) == "S":
            return (f"{stop}駅", _dest(to, stop))
        return (None, f"{stop}駅で運転打ち切り（札幌からは遠い）")
    sh, so = _side(ha), _side(to)
    # 札幌発 or 札幌をまたぐ列車 → 札幌駅で待っている客が諦めてタクシーへ
    if sh == "S" or (sh and so and sh != so):
        return ("札幌駅", _dest(to, "札幌"))
    # 札幌を通らない列車 → 発車駅が近ければそこ
    if ha in _NEAR:
        return (f"{ha}駅", _dest(to, ha))
    return (None, "札幌を通らない列車（札幌からは遠い）")


def format_msg(a):
    if a["src"] == "subway":
        line = a["line"].replace("地下鉄", "")
        hub = next((v for k, v in _SUBWAY_HUBS.items() if k in line), None)
        go = f"\n📍行く駅：{hub}" if hub else ""
        return f"🚇 {a['line']}：{a['status']}{go}\n🚕 地下鉄を諦めた客がタクシーへ"
    mark = "🌙 終電帯" if a.get("late") else "🚆"
    区間 = ""
    if a.get("ha_eki"):
        区間 = f"\n{a['ha_eki']} {a['ha_time']} → {a.get('to_eki','')} {a.get('to_time','')}".rstrip()
    go, dest = where_to_go(a)
    if go:
        tail = f"\n📍行く駅：{go}\n👤客の行き先：{dest}"
    else:
        tail = f"\n（{dest}。様子見でOK）"
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
