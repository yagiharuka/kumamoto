# Kumamoto News Watch

熊本地震に関する「イオン爆発」と「停電・電源車」の報道を、
国内主要紙・NHK・熊本日日新聞・時事通信から集約するサイトです。

- 公開ページ: <https://yagiharuka.github.io/kumamoto/>
- 更新: Cloudflare Cronから30分ごと
- カテゴリ: イオン爆発、停電・電源車
- 対象: 朝日新聞、読売新聞、毎日新聞、産経新聞、日本経済新聞、NHK、
  熊本日日新聞、時事通信
- 掲載内容: 見出し、媒体名、公開時刻、元記事リンクのみ

記事本文や画像は転載しません。Google News RSSを記事発見のために利用し、
媒体名が許可リストと厳密に一致する記事だけを保存します。

## メール通知の設定

毎時の新着メール通知を受け取るには、リポジトリの
`Settings` → `Secrets and variables` → `Actions` に次のRepository secretsを
登録します。

- `SMTP_USERNAME`: 送信元Gmailアドレス
- `SMTP_APP_PASSWORD`: 送信元Googleアカウントのアプリパスワード
- `ALERT_EMAIL_TO`: 通知先メールアドレス

メールは直前1時間に未通知の新着記事がある場合だけ送信されます。
新着がない場合やサイト内ボタンからの更新では送信しません。
秘密情報はリポジトリには保存しません。

## GitHub Pagesの設定

最初の1回だけ、`Settings` → `Pages` → `Build and deployment` の
`Source` を `GitHub Actions` に設定してください。その後は
`.github/workflows/update.yml` が収集・公開を自動で行います。

## ローカル確認

```bash
python -m unittest discover -s tests -v
python scripts/collect.py
python -m http.server 8000 --directory docs
```
