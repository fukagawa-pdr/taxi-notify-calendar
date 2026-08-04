#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通知の送り先アダプタ。
環境変数で送り先を切替える：
  LINE_CHANNEL_TOKEN … あればLINE公式アカウントへブロードキャスト（=友だち登録した本人に届く）
  NTFY_TOPIC         … あればntfyへ（LINEの予備・テスト用）
  どちらも無ければ画面出力だけ（ドライラン）
"""
import os, json, urllib.request, ssl, sys
try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl.create_default_context()

LINE_TOKEN = os.environ.get("LINE_CHANNEL_TOKEN", "").strip()
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

def _post(url, body, headers):
    data = json.dumps(body).encode("utf-8") if isinstance(body, (dict, list)) else body
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")

def send(text):
    """1通のテキストを通知。成功でTrue。"""
    if LINE_TOKEN:
        status, resp = _post(
            "https://api.line.me/v2/bot/message/broadcast",
            {"messages": [{"type": "text", "text": text[:4900]}]},
            {"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"})
        print(f"[LINE] HTTP {status} {resp[:200]}", file=sys.stderr)
        return status == 200
    if NTFY_TOPIC:
        status, _ = _post(f"https://ntfy.sh/{NTFY_TOPIC}",
                          text.encode("utf-8"),
                          {"Content-Type": "text/plain; charset=utf-8"})
        print(f"[ntfy] HTTP {status}", file=sys.stderr)
        return 200 <= status < 300
    print("＝＝＝ [ドライラン] 実際には送信していません ＝＝＝\n" + text + "\n＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝")
    return True

if __name__ == "__main__":
    send("🚕 タクシー通知カレンダー：テスト送信です。これが届けばLINE連携OK。")
