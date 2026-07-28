from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import collect  # noqa: E402


def rss_item(
    *,
    title: str = "イオンモール熊本で爆発 - 時事通信",
    source: str = "時事通信",
    link: str = "https://news.google.com/rss/articles/example",
    published: str = "Tue, 28 Jul 2026 12:00:00 GMT",
    description: str = "熊本県嘉島町のイオンモール熊本",
) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
<title>{title}</title>
<link>{link}</link>
<guid>{link}</guid>
<pubDate>{published}</pubDate>
<description>{description}</description>
<source url="https://www.jiji.com/">${source}</source>
</item></channel></rss>""".replace("$", "").encode()


class OutletTests(unittest.TestCase):
    def test_all_aliases_resolve_exactly(self) -> None:
        for outlet in collect.OUTLETS:
            for alias in outlet.aliases:
                self.assertEqual(collect.resolve_outlet(alias), outlet)

    def test_unapproved_sources_are_rejected(self) -> None:
        for label in ("NHK", "共同通信", "TBS NEWS DIG", "Yahoo!ニュース", ""):
            self.assertIsNone(collect.resolve_outlet(label))
        self.assertIsNone(collect.resolve_outlet("時事通信を引用した別媒体"))


class ParsingTests(unittest.TestCase):
    def test_parse_and_strip_exact_source_suffix(self) -> None:
        records = collect.parse_rss(rss_item())
        item = collect.to_item(records[0], datetime(2026, 7, 28, tzinfo=timezone.utc))
        self.assertIsNotNone(item)
        self.assertEqual(item["title"], "イオンモール熊本で爆発")
        self.assertEqual(item["source"], "時事通信")

    def test_inner_hyphen_is_preserved(self) -> None:
        raw = "熊本 - 嘉島のイオンモールで救助 - 時事通信"
        self.assertEqual(
            collect.clean_title(raw, "時事通信"),
            "熊本 - 嘉島のイオンモールで救助",
        )

    def test_missing_source_is_rejected(self) -> None:
        records = collect.parse_rss(rss_item(source=""))
        self.assertIsNone(
            collect.to_item(records[0], datetime(2026, 7, 28, tzinfo=timezone.utc))
        )

    def test_dates_normalize_to_utc(self) -> None:
        parsed = collect.parse_published_at("Tue, 28 Jul 2026 21:00:00 +0900")
        self.assertEqual(collect.iso_utc(parsed), "2026-07-28T12:00:00Z")

    def test_invalid_date_is_rejected(self) -> None:
        records = collect.parse_rss(rss_item(published="not-a-date"))
        self.assertIsNone(
            collect.to_item(records[0], datetime(2026, 7, 28, tzinfo=timezone.utc))
        )

    def test_uki_is_excluded_but_kumamoto_is_kept(self) -> None:
        self.assertFalse(
            collect.is_target_report(
                "イオンモール宇城でイベント", "熊本県内の買い物情報"
            )
        )
        self.assertFalse(
            collect.is_target_report("AEON MALL UKI update", "local information")
        )
        self.assertTrue(
            collect.is_target_report(
                "イオンモール熊本で救助続く", "熊本県嘉島町"
            )
        )
        self.assertTrue(
            collect.is_target_report(
                "宇城市でも被害", "嘉島町のイオンモール熊本で救助"
            )
        )

    def test_malformed_xml_raises(self) -> None:
        with self.assertRaises(collect.CollectionError):
            collect.parse_rss(b"<rss><broken>")

    def test_feed_url_contains_japanese_locale(self) -> None:
        url = collect.build_feed_url("熊本 イオン 爆発")
        self.assertIn("hl=ja", url)
        self.assertIn("gl=JP", url)
        self.assertIn("ceid=JP%3Aja", url)
        self.assertIn("%E7%86%8A%E6%9C%AC", url)


class MergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = "2026-07-28T12:00:00Z"

    def item(
        self,
        article_id: str,
        source_id: str = "jiji",
        source: str = "時事通信",
        title: str = "イオンモール熊本で救助",
        url: str | None = None,
    ) -> dict:
        return {
            "id": article_id,
            "title": title,
            "source": source,
            "source_id": source_id,
            "source_group": "通信社" if source_id == "jiji" else "全国紙",
            "published_at": self.now,
            "url": url or f"https://example.com/{article_id}",
            "first_seen": self.now,
            "focus": ["救助・安否"],
        }

    def test_duplicate_link_is_one_new_item(self) -> None:
        candidate = self.item("one")
        merged, new_items = collect.merge_items([], [candidate, dict(candidate)])
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(new_items), 1)

    def test_same_source_and_title_deduplicates_different_links(self) -> None:
        first = self.item("one")
        second = self.item("two")
        merged, new_items = collect.merge_items([], [first, second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(new_items), 1)

    def test_same_title_from_different_sources_is_two_items(self) -> None:
        first = self.item("one")
        second = self.item(
            "two", source_id="mainichi", source="毎日新聞", title=first["title"]
        )
        merged, new_items = collect.merge_items([], [first, second])
        self.assertEqual(len(merged), 2)
        self.assertEqual(len(new_items), 2)

    def test_existing_link_with_changed_title_is_not_new(self) -> None:
        existing = self.item("one", title="旧見出し")
        changed = self.item("different-id", title="新見出し", url=existing["url"])
        merged, new_items = collect.merge_items([existing], [changed])
        self.assertEqual(new_items, [])
        self.assertEqual(merged[0]["id"], "one")
        self.assertEqual(merged[0]["first_seen"], self.now)
        self.assertEqual(merged[0]["title"], "新見出し")

    def test_existing_history_is_preserved(self) -> None:
        old = self.item("old", title="以前の記事")
        new = self.item("new", title="新しい記事")
        merged, new_items = collect.merge_items([old], [new])
        self.assertEqual({item["id"] for item in merged}, {"old", "new"})
        self.assertEqual([item["id"] for item in new_items], ["new"])


class StorageTests(unittest.TestCase):
    def test_corrupt_history_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "news.json"
            path.write_text("{bad json", encoding="utf-8")
            with self.assertRaises(collect.CollectionError):
                collect.load_snapshot(path)

    def test_atomic_write_is_valid_json_with_terminal_newline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "news.json"
            payload = collect.empty_snapshot()
            collect.atomic_write(path, collect.serialized(payload))
            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.endswith("\n"))
            self.assertEqual(json.loads(content)["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
