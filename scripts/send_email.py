#!/usr/bin/env python3
"""Send an hourly email only when previously unnotified articles exist."""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / ".work" / "update_result.json"
NEWS_PATH = ROOT / "data" / "news.json"
STATE_PATH = ROOT / "data" / "email_state.json"
SITE_URL = "https://yagiharuka.github.io/kumamoto/"
CATEGORY_LABELS = {
    "aeon": "イオン爆発",
    "power": "停電・電源車",
    "paper": "日本製紙・八代工場",
}


def load_result() -> dict[str, Any]:
    try:
        return json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {
            "status": "failed",
            "run_at_jst": "時刻不明",
            "error": f"更新結果を読み取れませんでした: {error}",
        }


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def format_jst(value: Any) -> str:
    parsed = parse_utc(value)
    if parsed is None:
        return "日時不明"
    return parsed.astimezone(ZoneInfo("Asia/Tokyo")).strftime(
        "%Y/%m/%d %H:%M JST"
    )


def category_text(item: dict[str, Any]) -> str:
    category_ids = item.get("category_ids")
    if not isinstance(category_ids, list) or not category_ids:
        category_ids = ["aeon"]
    return "・".join(
        CATEGORY_LABELS.get(category_id, str(category_id))
        for category_id in category_ids
    )


def primary_category(item: dict[str, Any]) -> str:
    category_ids = item.get("category_ids")
    if not isinstance(category_ids, list) or not category_ids:
        return "aeon"
    for category_id in CATEGORY_LABELS:
        if category_id in category_ids:
            return category_id
    return str(category_ids[0])


def group_items_by_category(
    items: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        category_id = primary_category(item)
        grouped.setdefault(category_id, []).append(item)
    ordered_ids = [
        *[category_id for category_id in CATEGORY_LABELS if category_id in grouped],
        *[category_id for category_id in grouped if category_id not in CATEGORY_LABELS],
    ]
    return [(category_id, grouped[category_id]) for category_id in ordered_ids]


def select_unnotified_items(
    items: list[dict[str, Any]],
    after: datetime,
    through: datetime,
) -> list[dict[str, Any]]:
    selected = []
    for item in items:
        first_seen = parse_utc(item.get("first_seen"))
        published_at = parse_utc(item.get("published_at"))
        if (
            first_seen is not None
            and published_at is not None
            and after < first_seen <= through
            and after < published_at <= through
        ):
            selected.append(item)
    return sorted(
        selected,
        key=lambda item: parse_utc(item.get("published_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def build_message(result: dict[str, Any], sender: str, recipient: str) -> EmailMessage:
    status = result.get("status")
    run_at = result.get("run_at_jst", "時刻不明")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient

    if status != "ok":
        message["Subject"] = f"【熊本イオン報道】更新失敗（{run_at}）"
        body = [
            "熊本地震報道ウォッチの定期更新に失敗しました。",
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
        message["Subject"] = f"【熊本イオン報道】新着{new_count}件（{run_at}）"
        body = [
            "熊本地震報道ウォッチを更新しました。",
            "",
            f"実行時刻: {run_at}",
            f"今回の新着: {new_count}件",
            f"掲載総数: {total_count}件",
            f"公開ページ: {SITE_URL}",
        ]
        if new_items:
            body.extend(["", "新着記事"])
            index = 1
            for category_id, category_items in group_items_by_category(new_items):
                label = CATEGORY_LABELS.get(category_id, category_id)
                body.extend(["", f"■ {label}（{len(category_items)}件）"])
                for item in category_items:
                    body.extend(
                        [
                            "",
                            f"{index}. [{category_text(item)}｜{item['source']}] {item['title']}",
                            f"   公開: {format_jst(item.get('published_at'))}",
                            f"   {item['url']}",
                        ]
                    )
                    index += 1
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
    result = load_result()
    if result.get("status") != "ok":
        print("::warning::Email skipped: the collection did not succeed.")
        return 0

    run_at = parse_utc(result.get("run_at"))
    if run_at is None:
        print("::warning::Email skipped: collection time is invalid.")
        return 0

    state = load_json(STATE_PATH, {"schema_version": 1})
    last_checked = parse_utc(state.get("last_checked_at"))
    if last_checked is None or last_checked >= run_at:
        last_checked = run_at - timedelta(hours=1)

    news = load_json(NEWS_PATH, {"items": []})
    items = news.get("items") if isinstance(news.get("items"), list) else []
    new_items = select_unnotified_items(items, last_checked, run_at)
    state_update = {
        "schema_version": 1,
        "last_checked_at": iso_utc(run_at),
        "last_sent_at": state.get("last_sent_at"),
    }

    if not new_items:
        atomic_write_json(STATE_PATH, state_update)
        print("Email skipped: no unnotified articles from the past hour.")
        return 0

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
    result = {
        **result,
        "new_count": len(new_items),
        "new_items": new_items,
    }
    message = build_message(result, sender, recipient)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
        smtp.login(username, password)
        smtp.send_message(message)
    state_update["last_sent_at"] = iso_utc(run_at)
    atomic_write_json(STATE_PATH, state_update)
    print(f"Update email sent to {recipient}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"email failed: {error}", file=sys.stderr)
        raise
