from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import send_email  # noqa: E402


class HourlyEmailTests(unittest.TestCase):
    def test_category_text_supports_power_articles(self) -> None:
        self.assertEqual(
            send_email.category_text({"category_ids": ["power"]}),
            "停電・電源車",
        )

    def test_category_text_supports_paper_mill_articles(self) -> None:
        self.assertEqual(
            send_email.category_text({"category_ids": ["paper"]}),
            "日本製紙・八代工場",
        )

    def test_formats_article_time_in_jst(self) -> None:
        self.assertEqual(
            send_email.format_jst("2026-07-28T15:00:00Z"),
            "2026/07/29 00:00 JST",
        )

    def test_invalid_article_time_has_fallback(self) -> None:
        self.assertEqual(send_email.format_jst("not-a-date"), "日時不明")

    def test_selects_only_items_after_last_check(self) -> None:
        after = datetime(2026, 7, 28, 14, 0, tzinfo=timezone.utc)
        through = datetime(2026, 7, 28, 15, 0, tzinfo=timezone.utc)
        items = [
            {
                "id": "old",
                "first_seen": "2026-07-28T14:00:00Z",
                "published_at": "2026-07-28T13:59:00Z",
            },
            {
                "id": "new",
                "first_seen": "2026-07-28T14:30:00Z",
                "published_at": "2026-07-28T14:29:00Z",
            },
            {
                "id": "future",
                "first_seen": "2026-07-28T15:00:01Z",
                "published_at": "2026-07-28T15:00:01Z",
            },
        ]

        selected = send_email.select_unnotified_items(items, after, through)

        self.assertEqual([item["id"] for item in selected], ["new"])

    def test_invalid_first_seen_is_ignored(self) -> None:
        after = datetime(2026, 7, 28, 14, 0, tzinfo=timezone.utc)
        through = datetime(2026, 7, 28, 15, 0, tzinfo=timezone.utc)

        selected = send_email.select_unnotified_items(
            [{"id": "bad", "first_seen": "not-a-date"}],
            after,
            through,
        )

        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
