# タクシー通知カレンダー 🚕

北海道の夜間交通（新千歳空港の到着遅延・JR/地下鉄の運行状況）とイベント情報を自動で監視し、LINEに通知するツール。

## 何を通知するか
| 機能 | 内容 | データ源 |
|---|---|---|
| ② 千歳 到着遅延 | 22時以降に新千歳着の便が **20分以上遅延／欠航** したら通知 | 北海道エアポート公式 today.json |
| ③ 列車遅延 | JR北海道・地下鉄・市電が **平常運転でなくなったら** 通知 | Yahoo!運行情報(北海道) |
| ① 夕方イベント | コンサート/野球/ライブ等の **開始90分前** にリマインド | events.json（手動キュレーション） |

- 稼働時間：**JST 16:00〜01:59** に10分おきチェック
- 同じ遅延を繰り返し送らない（state.json で重複防止／日付が変わると自動リセット）

## 仕組み
```
GitHub Actions（無料・夜間だけ10分おき）
  └ run.py … flight_check / train_check / events を見て、新規だけ通知
      └ notify.py … LINE公式アカウントへブロードキャスト → 友だち登録した自分のLINEに届く
```
自作iOSアプリもサーバーも不要。受け皿は既存のLINE。

---

## セットアップ（初回だけ・全部無料）

### 1. LINEの受け皿を作る（Messaging API）
1. https://developers.line.biz/ に **LINEアカウントでログイン**
2. 「プロバイダー」を新規作成（名前は何でも可）
3. その中に **Messaging API** チャンネルを新規作成（名前：例「タクシー通知」）
4. チャンネルの **「Messaging API設定」** タブ →
   - 一番下の **チャネルアクセストークン（長期）** を「発行」してコピー（あとで使う）
   - 表示されるQRコードを **自分のスマホのLINEで読み、友だち追加**（これで通知が自分に届く）
5. 「応答設定」で **応答メッセージ＝オフ／あいさつメッセージ＝任意**（無くてOK）

> 無料枠は月200通まで。夜の遅延通知なら十分。足りなくなったら「1日1回まとめ送信」に変更可。

### 2. GitHubに置いて自動実行させる
1. https://github.com でアカウント作成（無料）
2. **Private** リポジトリを作り、このフォルダ一式をpush
   （`git init` 済み。あとは `git remote add origin <URL>` → `git push -u origin main` だけ）
3. リポジトリの **Settings → Secrets and variables → Actions → New repository secret**
   - Name：`LINE_CHANNEL_TOKEN`
   - Secret：手順1でコピーしたトークン
4. **Actions** タブを開いて有効化 → `taxi-watch` → **Run workflow** で手動テスト
   → LINEに通知が来れば完成。あとは毎晩自動で回る。

> GitHubの無料cronは、60日間リポジトリに動きが無いと自動停止する。月1回でも何かpushすれば継続。

---

## イベントの登録（機能①）
`events.json` に配列で追記（形式は `events.sample.json` 参照）。
```json
{ "id":"一意のID", "date":"2026-07-25", "start":"18:30",
  "remind_at":"21:00", "title":"公演名", "venue":"会場", "note":"メモ（任意）" }
```
- `remind_at`（任意）：通知を出したい時刻。**野球や花火など「終了後」に需要が来る**ものはここに終了ごろの時刻を入れる。省略時は開始90分前に通知。
- ※ 毎週の主要イベント（札幌ドーム／エスコン／Zepp／花火 等）は担当が更新予定。

## 週間ダイジェスト（毎週日曜21時）
`weekly-digest` ワークフローが、翌週（月〜日）のイベントをカレンダー形式でLINEに送る。
- 手動テスト：Actions → **weekly-digest** → Run workflow → `from`/`to` に日付（例 2026-07-25〜2026-07-26）を入れて実行。
- 範囲を空欄にすると「翌週の月〜日」を送信。

## 手元での動作確認
```bash
pip install -r requirements.txt
python3 run.py --dry-run --force   # 送信せず内容だけ表示
python3 checkers/flight_check.py --debug
python3 checkers/train_check.py --debug
python3 notify.py                  # LINE_CHANNEL_TOKEN を設定していれば実際にテスト送信
```

## 調整できる主な値
- `checkers/flight_check.py`：`NIGHT_START`(21:00) / `DELAY_MIN_THRESHOLD`(20分)
- `run.py`：`ACTIVE_HOURS`(稼働時間帯) / `EVENT_REMIND_MIN`(90分前)

## 列車の遅延検知について（2026-09-29 改修）

⚠️ **Yahoo!運行情報は「遅延の対象が終列車の場合」は配信しない**（公式ヘルプに明記）。
他にも「1本のみに影響する場合」は配信されず、掲載基準は首都圏JR以外は30分以上。
つまり**終電の遅れは仕様上ぜったいに流れてこない**ため、一度も通知が鳴らなかった。

代わりに **JR北海道の一次データ（列車単位）＋札幌市営地下鉄** を直接見る方式に変更。
- JR: `webunkou/json/senku/senku_{01,02,03,04}.json` の `today.unkyuTrains` / `chienTrains`
- 地下鉄: `operationstatus.city.sapporo.jp/unkojoho/top.html`（南北・東西・東豊）

**通知は終電帯（23:00〜翌2:00発）に限定**（本人指示）。昼間の特急運休などは通知しない。

監視時間は **JST 16:00〜翌05:00**（本人が朝5時退勤のため）。
終電は地下鉄すすきの発 0:12/0:14、大通発 0:15〜0:19。旧設定(24時終了)では
ちょうど終電が乱れる瞬間に監視が切れていた。
早朝は快速エアポート始発(札幌5:50発)より前の空港送りを拾うため4時台まで見る。

※ JR・地下鉄とも公式に外部公開されたAPIではなくサイト内部のエンドポイント。
   個人の需要把握用途に留め、2分間隔より短く叩かないこと。
