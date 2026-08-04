#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""常駐ループ監視。
GitHubの定期実行(cron)は起動が数十分ずれることがあるため、
「起動を何度も頼む」のではなく「一度起動して、中で数分おきに見張り続ける」方式にする。
起動が多少遅れても、動き出した後の検知はPOLL_SECONDS間隔（既定2分）で安定する。

環境変数:
  POLL_SECONDS … 何秒おきに見るか（既定 120）
  LOOP_END     … 何時まで見張るか JST "HH:MM"（既定 00:00＝24時で終了）
  MAX_MINUTES  … 保険の上限（既定 300分。GitHubのジョブ上限6時間より短く）
"""
import os, sys, time, pathlib
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import run as runner

JST = timezone(timedelta(hours=9))
POLL = int(os.environ.get("POLL_SECONDS", "120"))
LOOP_END = os.environ.get("LOOP_END", "00:00").strip() or "00:00"
MAX_MINUTES = int(os.environ.get("MAX_MINUTES", "300"))

def log(m):
    print(f"[{datetime.now(JST):%m/%d %H:%M:%S}] {m}", flush=True)

def end_time(now):
    h, m = map(int, LOOP_END.split(":"))
    end = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if end <= now:                       # 終了時刻が過ぎていれば翌日の同時刻
        end += timedelta(days=1)
    hard = now + timedelta(minutes=MAX_MINUTES)
    return min(end, hard)

def main():
    now = datetime.now(JST)
    if now.hour not in runner.ACTIVE_HOURS:
        # 起動が大きく遅れて時間外に始まった場合は、誤った時刻に鳴らさず即終了する
        log(f"稼働時間外のため何もせず終了（{now:%H:%M} / 稼働は16:00〜23:59）")
        return
    end = end_time(now)
    log(f"監視開始（{POLL}秒おき / {end:%m-%d %H:%M} まで）")
    n = 0
    while True:
        now = datetime.now(JST)
        if now >= end:
            break
        if now.hour not in runner.ACTIVE_HOURS:
            log("24時になったので監視を終了します")
            break
        n += 1
        try:
            runner.run(force=True)       # 時間帯の制御はこのループが持つ
        except Exception as e:            # 一時的な通信エラー等で止めない
            log(f"[warn] チェック失敗（次回に継続）: {e}")
        # 終了時刻を跨がないように待つ
        remain = (end - datetime.now(JST)).total_seconds()
        if remain <= 0:
            break
        time.sleep(min(POLL, remain))
    log(f"監視終了（{n}回チェック）")

if __name__ == "__main__":
    main()
