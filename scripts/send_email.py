#!/usr/bin/env python3
"""Send a concise email after each scheduled news refresh."""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / ".work" / "update_result.json"
SITE_URL = "https://yagiharuka.github.io/kumamoto/"


def load_result() -> dict[str, Any]:
    try:
        return json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {
            "status": "failed",
            "run_at_jst": "時刻不明",
            "error": f"更新結果を読み取れませんでした: {error}",
        }


def build_message(result: dict[str, Any], sender: str, recipient: str) -> EmailMessage:
    status = result.get("status")
    run_at = result.get("run_at_jst", "時刻不明")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient

    if status != "ok":
        message["Subject"] = f"【熊本イオン報道】更新失敗（{run_at}）"
        body = [
            "熊本イオン報道ウォッチの定期更新に失敗しました。",
            "",
            f"実行時刻: {run_at}",
            f"エラー: {result.get('error', '詳細不明')}",
            "",
            f"公開ページ: {SITE_URL}",
        ]
    else:
        new_items = result.get("new_items", [])
        new_count = int(result.get("new_count", 0))
        total_count = int(result.get("total_count", 0))
        first_run = bool(result.get("first_run"))
        if first_run:
            state = "監視開始"
        elif new_count:
            state = f"新着{new_count}件"
        else:
            state = "新着なし"
        message["Subject"] = f"【熊本イオン報道】{state}（{run_at}）"
        body = [
            "熊本イオン報道ウォッチを更新しました。",
            "",
            f"実行時刻: {run_at}",
            f"今回の新着: {new_count}件",
            f"掲載総数: {total_count}件",
            f"公開ページ: {SITE_URL}",
        ]
        if new_items:
            body.extend(["", "新着記事"])
            for index, item in enumerate(new_items[:25], start=1):
                body.extend(
                    [
                        "",
                        f"{index}. [{item['source']}] {item['title']}",
                        f"   公開: {item['published_at']}",
                        f"   {item['url']}",
                    ]
                )
            if len(new_items) > 25:
                body.extend(["", f"ほか {len(new_items) - 25}件は公開ページで確認できます。"])
        warnings = result.get("warnings") or []
        if warnings:
            body.extend(["", f"取得警告: {len(warnings)}件（一部媒体の検索が遅延した可能性があります）"])

    body.extend(
        [
            "",
            "※見出し・媒体名・公開時刻・リンクのみを掲載しています。",
            "※災害対応の公式情報ではありません。",
        ]
    )
    message.set_content("\n".join(body))
    return message


def main() -> int:
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_APP_PASSWORD", "").strip()
    recipient = os.environ.get("ALERT_EMAIL_TO", "").strip()
    sender = os.environ.get("SMTP_FROM", "").strip() or username
    if not username or not password or not recipient:
        print(
            "::warning::Email skipped: configure SMTP_USERNAME, "
            "SMTP_APP_PASSWORD, and ALERT_EMAIL_TO repository secrets."
        )
        return 0

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.environ.get("SMTP_PORT", "465"))
    result = load_result()
    message = build_message(result, sender, recipient)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
        smtp.login(username, password)
        smtp.send_message(message)
    print(f"Update email sent to {recipient}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"email failed: {error}", file=sys.stderr)
        raise
