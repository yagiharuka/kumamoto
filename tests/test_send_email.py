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

    def test_late_discovered_old_article_is_not_emailed(self) -> None:
        after = datetime(2026, 7, 29, 13, 0, tzinfo=timezone.utc)
        through = datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc)

        selected = send_email.select_unnotified_items(
            [
                {
                    "id": "late-backfill",
                    "first_seen": "2026-07-29T13:39:00Z",
                    "published_at": "2026-07-28T08:09:00Z",
                }
            ],
            after,
            through,
        )

        self.assertEqual(selected, [])

    def test_email_groups_all_categories_and_does_not_truncate(self) -> None:
        items = []
        for index in range(30):
            category_id = "aeon"
            if index == 28:
                category_id = "power"
            elif index == 29:
                category_id = "paper"
            items.append(
                {
                    "category_ids": [category_id],
                    "source": "NHK",
                    "title": f"記事{index + 1}",
                    "published_at": "2026-07-29T00:00:00Z",
                    "url": f"https://example.com/{index + 1}",
                }
            )

        message = send_email.build_message(
            {
                "status": "ok",
                "run_at_jst": "2026/07/29 10:00 JST",
                "new_count": len(items),
                "total_count": 200,
                "new_items": items,
            },
            "sender@example.com",
            "recipient@example.com",
        )
        body = message.get_content()

        self.assertIn("【熊本イオン報道】", str(message["Subject"]))
        self.assertIn("■ イオン爆発（28件）", body)
        self.assertIn("■ 停電・電源車（1件）", body)
        self.assertIn("■ 日本製紙・八代工場（1件）", body)
        self.assertIn("30. [日本製紙・八代工場｜NHK] 記事30", body)
        self.assertNotIn("ほか 5件", body)


if __name__ == "__main__":
    unittest.main()
