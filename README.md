# Kumamoto AEON Watch

「熊本 イオン 爆発」に関する国内主要紙・熊本日日新聞・時事通信の
見出しを集約する、独立したニュース確認サイトです。

- 公開ページ: <https://yagiharuka.github.io/kumamoto/>
- 更新: GitHub Actionsで30分ごと（毎時7分・37分）
- 対象: 朝日新聞、読売新聞、毎日新聞、産経新聞、日本経済新聞、
  熊本日日新聞、時事通信
- 掲載内容: 見出し、媒体名、公開時刻、元記事リンクのみ

記事本文や画像は転載しません。Google News RSSを記事発見のために利用し、
媒体名が許可リストと厳密に一致する記事だけを保存します。

## メール通知の設定

30分ごとの実行結果をメールで受け取るには、リポジトリの
`Settings` → `Secrets and variables` → `Actions` に次のRepository secretsを
登録します。

- `SMTP_USERNAME`: 送信元Gmailアドレス
- `SMTP_APP_PASSWORD`: 送信元Googleアカウントのアプリパスワード
- `ALERT_EMAIL_TO`: 通知先メールアドレス

通知は新着の有無にかかわらず、スケジュール実行のたびに送信されます。
収集に失敗した場合も、失敗内容を通知します。秘密情報はリポジトリには
保存しません。

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
