#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""見張り役の本体。
夜間だけ ①イベント ②千歳の到着遅延 ③列車遅延 を見て、
「前回から新しく発生・変化したものだけ」をまとめてLINE通知する。

■ 2026-08-01 改修（本人指示）
  ・稼働は JST 16:00〜23:59。**24時以降は通知しない**（深夜に鳴らない）
  ・遅延は即時性が命 → 5分おきに巡回（旧10分）
  ・同じ遅延を何度も送らない。1件につき原則1回だけ。
    例外＝「遅延→欠航」への悪化、または遅れ幅が前回通知から30分以上さらに拡大したとき
  ・イベントは1週間前にも予告（ライブ/野球/花火など）。当日の直前リマインドは従来どおり
"""
import json, os, sys, pathlib
from datetime import datetime, timezone, timedelta, date

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from checkers import flight_check, train_check
import notify

JST = timezone(timedelta(hours=9))
STATE = ROOT / "state.json"
EVENTS = ROOT / "events.json"

ACTIVE_HOURS = set(range(16, 24)) | {0, 1, 2, 3, 4}   # JST 16:00〜翌04:59。
# ⚠️ 深夜帯を含めるのが重要。終電（地下鉄0:12〜0:19）が乱れるのは旧設定(24時終了)の
#    直後で構造的に検知できなかった。本人は朝5時退勤なので4時台までを対象にする
#    （早朝の空港送り＝快速エアポート始発5:50より前の客を拾うため）。
EVENT_REMIND_MIN = 90               # 当日リマインド：開始の何分前か
ADVANCE_DAYS = 7                    # 事前予告：何日前に出すか
ADVANCE_HOUR = 20                   # 事前予告を出す時刻（JST）
ESCALATE_MIN = 30                   # 遅れがこれ以上さらに拡大したら再通知
# 事前予告の対象。category 未指定でもタイトルにこの語が入っていれば対象にする
ADVANCE_KEYWORDS = ("ライブ", "LIVE", "コンサート", "野球", "ファイターズ", "花火",
                    "フェス", "公演", "ツアー")


def load_state():
    try:
        return json.loads(STATE.read_text("utf-8"))
    except Exception:
        return {}


def save_state(s):
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), "utf-8")


def load_events():
    """events.json（公開） ＋ 環境変数 EVENTS_PRIVATE（非公開）を合わせて読む。
    人に見せたくない予定は、GitHubのSecretに EVENTS_PRIVATE として同じ形式のJSONを入れる。
    リポジトリを公開しても、そちらの中身は公開されない。"""
    evs = []
    try:
        evs += json.loads(EVENTS.read_text("utf-8"))
    except Exception:
        pass
    raw = os.environ.get("EVENTS_PRIVATE", "").strip()
    if raw:
        try:
            evs += json.loads(raw)
        except Exception as e:
            print(f"[warn] EVENTS_PRIVATE の形式が不正です: {e}", file=sys.stderr)
    return evs


def is_advance_target(ev):
    """1週間前の予告を出す対象か。ライブ・野球・花火などが該当。"""
    if ev.get("advance") is False:
        return False
    if ev.get("advance") is True or ev.get("category"):
        return True
    t = ev.get("title", "")
    return any(k in t for k in ADVANCE_KEYWORDS)


def run(dry=False, force=False):
    now = datetime.now(JST)
    if not force and now.hour not in ACTIVE_HOURS:
        print(f"[skip] {now:%H:%M} は稼働時間外（16時〜翌4時台のみ）")
        return
    today = now.strftime("%Y-%m-%d")
    # 夜勤は日付をまたぐ。午前6時を境に「同じ勤務日」とみなすことで、
    # 0時を過ぎた瞬間に重複防止の記録が消えて再通知される事故を防ぐ。
    # 空港便も、前日23:50発の便が0:30に着くケースを拾えるようになる。
    shift_day = (now - timedelta(hours=6)).strftime("%Y-%m-%d")

    st = load_state()
    # 日次でリセットするのは遅延の記録だけ。事前予告の送信済みフラグは持ち越す
    sent_advance = st.get("sent_advance", {})
    if st.get("date") != shift_day:
        st = {"date": shift_day, "flights": {}, "trains": {}, "events": {}}
    st.setdefault("flights", {})
    st.setdefault("trains", {})
    st.setdefault("events", {})
    st["sent_advance"] = sent_advance

    msgs = []

    # ② 千歳 到着遅延 -----------------------------------------------------
    for a in flight_check.check(today=shift_day):
        prev = st["flights"].get(a["id"])
        cancelled = "欠航" in a["status"]
        if not isinstance(prev, dict):
            prev = None                                   # 旧形式(文字列)の記録は初回扱い
        if prev is None:
            send = True                                   # 初回だけ送る
        else:
            # 同じ遅延の再送はしない。悪化したときだけ送る
            worse_cancel = cancelled and not prev.get("cancelled")
            worse_delay = a["delay"] - prev.get("delay", 0) >= ESCALATE_MIN
            send = worse_cancel or worse_delay
        if send:
            msgs.append(flight_check.format_msg(a))
        st["flights"][a["id"]] = {"delay": a["delay"], "cancelled": cancelled}

    # ③ 列車の遅延・運休（JR北海道の列車単位データ＋札幌市営地下鉄）--------
    # 旧実装はYahoo!運行情報を見ていたが、Yahoo!は仕様上「終電の遅延」を配信しない。
    # そのため一度も鳴らなかった。JR北海道の一次データに切り替えて列車単位で拾う。
    for a in train_check.check():
        if a["id"] in st["trains"]:
            continue                                      # 同じ列車の同じ状況は1回だけ
        st["trains"][a["id"]] = True
        msgs.append(train_check.format_msg(a))

    # ① イベント ---------------------------------------------------------
    def hm(s):
        h, m = map(int, s.split(":"))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)

    for ev in load_events():
        d = ev.get("date")
        if not d:
            continue

        # (a) 1週間前の事前予告（ライブ・野球・花火など）
        if is_advance_target(ev) and not sent_advance.get(ev["id"]):
            try:
                ev_date = date.fromisoformat(d)
            except Exception:
                ev_date = None
            if ev_date:
                days_left = (ev_date - now.date()).days
                # 予告日(7日前)を過ぎて登録された場合も、当日より前なら取りこぼさず出す
                if 0 < days_left <= ADVANCE_DAYS and now.hour >= ADVANCE_HOUR:
                    sent_advance[ev["id"]] = True
                    venue = f"\n📍{ev.get('venue','')}" if ev.get("venue") else ""
                    note = f"\n{ev['note']}" if ev.get("note") else ""
                    msgs.append(
                        f"🗓 【{days_left}日後】{ev['title']}\n"
                        f"{d} {ev.get('start','')}〜{venue}{note}\n"
                        f"🚕 シフトの調整を検討")

        # (b) 当日の直前リマインド
        if d != today or not ev.get("start"):
            continue
        try:
            start = hm(ev["start"])
            if ev.get("remind_at"):
                notify_from = hm(ev["remind_at"])
                notify_until = notify_from + timedelta(minutes=90)
            else:
                notify_from = start - timedelta(minutes=EVENT_REMIND_MIN)
                notify_until = start
        except Exception:
            continue
        if notify_from <= now <= notify_until and not st["events"].get(ev["id"]):
            st["events"][ev["id"]] = True
            venue = f"📍{ev.get('venue','')} " if ev.get("venue") else ""
            note = f"\n{ev['note']}" if ev.get("note") else ""
            msgs.append(f"📅 イベント: {ev['title']}\n{venue}{ev['start']}〜{note}\n"
                        f"🚕 タクシー需要に備えを")

    # 送信 ---------------------------------------------------------------
    if msgs:
        text = "\n\n".join(msgs)
        if dry:
            print("[DRY-RUN] 送信内容:\n" + text)
        else:
            notify.send(text)
    else:
        print(f"[{now:%H:%M}] 通知なし（遅延・イベントとも該当なし）")

    if not dry:
        save_state(st)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        now = datetime.now(JST)
        ok = notify.send(
            "✅ 自動実行テスト成功\n"
            f"クラウドからの通知が正常です（{now:%m/%d %H:%M}）。\n"
            "夜間(16〜24時)に千歳の到着遅延・列車遅延・イベントを自動通知します🚕")
        print("selftest sent:", ok)
    run(dry="--dry-run" in sys.argv, force="--force" in sys.argv)
