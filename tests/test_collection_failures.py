from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import collect  # noqa: E402


class FetchFailureTests(unittest.TestCase):
    def test_transport_exception_type_is_retained(self) -> None:
        for error, expected in (
            (TimeoutError(), "TimeoutError"),
            (URLError("DNS lookup failed"), "URLError"),
            (HTTPError("https://news.google.com/rss/search", 403, "Forbidden", {}, None), "HTTPError"),
            (HTTPError("https://news.google.com/rss/search", 429, "Too Many Requests", {}, None), "HTTPError"),
        ):
            with self.subTest(error=expected, message=str(error)):
                with patch("collect.urlopen", side_effect=error), patch("collect.time.sleep"):
                    with self.assertRaises(collect.CollectionError) as caught:
                        collect.fetch_bytes("https://news.google.com/rss/search")
                self.assertIn(expected, str(caught.exception))
                self.assertIs(caught.exception.__cause__, error)
                if isinstance(error, HTTPError):
                    self.assertIn(str(error.code), str(caught.exception))

    def test_forbidden_is_not_retried(self) -> None:
        error = HTTPError("https://news.google.com/rss/search", 403, "Forbidden", {}, None)
        with patch("collect.urlopen", side_effect=error) as mocked_open, patch("collect.time.sleep") as sleep:
            with self.assertRaises(collect.CollectionError):
                collect.fetch_bytes("https://news.google.com/rss/search")
        self.assertEqual(mocked_open.call_count, 1)
        sleep.assert_not_called()

    def test_existing_retry_limit_is_unchanged(self) -> None:
        with patch("collect.urlopen", side_effect=TimeoutError()) as mocked_open, patch("collect.time.sleep") as sleep:
            with self.assertRaises(collect.CollectionError):
                collect.fetch_bytes("https://news.google.com/rss/search")
        self.assertEqual(mocked_open.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 3])


class CollectionFailureTests(unittest.TestCase):
    now = datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)

    def test_typed_parse_error_keeps_query_context(self) -> None:
        with patch("collect.fetch_bytes", return_value=b"<rss><broken>"):
            records, warnings, successes = collect.fetch_queries(["query-a"])
        self.assertEqual(records, [])
        self.assertEqual(successes, 0)
        self.assertEqual(len(warnings), 1)
        self.assertIn("query-a: CollectionError: invalid RSS XML", warnings[0])

    def test_valid_empty_rss_is_successful(self) -> None:
        with patch("collect.fetch_bytes", return_value=b"<rss><channel /></rss>"):
            records, warnings, successes = collect.fetch_queries(["query-a"])
        self.assertEqual((records, warnings, successes), ([], [], 1))

    def test_category_keeps_underlying_diagnostics(self) -> None:
        detail = "query-a: CollectionError: RSS fetch failed (TimeoutError): "
        with patch("collect.fetch_queries", return_value=([], [detail], 0)) as mocked_fetch:
            with self.assertRaises(collect.CollectionError) as caught:
                collect.collect_category(collect.CATEGORIES[0], self.now)
        self.assertIn(collect.CATEGORIES[0].name, str(caught.exception))
        self.assertEqual(caught.exception.diagnostics, (detail,))
        self.assertEqual(mocked_fetch.call_count, 1)

    def test_total_failure_keeps_every_category_and_query_cause(self) -> None:
        error = collect.CollectionError("RSS fetch failed (HTTPError): HTTP Error 429: Too Many Requests")
        with patch("collect.fetch_query", side_effect=error):
            with self.assertRaises(collect.CollectionError) as caught:
                collect.collect_candidates(self.now)
        self.assertEqual(str(caught.exception), "all category RSS queries failed")
        diagnostics = "\n".join(caught.exception.diagnostics)
        for category in collect.CATEGORIES:
            self.assertIn(category.name, diagnostics)
            for query in category.broad_queries:
                self.assertIn(query, diagnostics)
        self.assertEqual(diagnostics.count("HTTP Error 429"), 6)

    def test_partial_outage_retains_diagnostics_without_losing_successes(self) -> None:
        detail = "query-a: CollectionError: RSS fetch failed (TimeoutError): "
        failure = collect.CollectionError("category unavailable", diagnostics=[detail])
        candidate = {"id": "kept"}
        with patch("collect.collect_category", side_effect=[failure, ([candidate], []), ([], [])]):
            candidates, warnings = collect.collect_candidates(self.now)
        self.assertEqual(candidates, [candidate])
        self.assertEqual(warnings, ["category unavailable", detail])

    def test_main_preserves_both_snapshots_and_reports_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "data" / "news.json"
            public = root / "docs" / "data" / "news.json"
            result = root / ".work" / "update_result.json"
            snapshot = collect.empty_snapshot()
            snapshot["updated_at"] = "2026-10-12T01:01:49Z"
            content = collect.serialized(snapshot)
            collect.atomic_write(archive, content)
            collect.atomic_write(public, content)
            collect.atomic_write(result, '{"status": "ok"}\n')
            load_snapshot = collect.load_snapshot
            stderr = io.StringIO()
            error = collect.CollectionError("RSS fetch failed (HTTPError): HTTP Error 503: Service Unavailable")
            with (
                patch("collect.ARCHIVE_PATH", archive),
                patch("collect.PUBLIC_PATH", public),
                patch("collect.RESULT_PATH", result),
                patch("collect.load_snapshot", side_effect=lambda: load_snapshot(archive)),
                patch("collect.fetch_query", side_effect=error),
                redirect_stderr(stderr),
                redirect_stdout(io.StringIO()),
            ):
                status = collect.main()
            self.assertEqual(status, 1)
            self.assertEqual(archive.read_bytes(), content.encode("utf-8"))
            self.assertEqual(public.read_bytes(), content.encode("utf-8"))
            failure_result = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(failure_result["status"], "failed")
            self.assertEqual(failure_result["error"], "all category RSS queries failed")
            self.assertEqual(len(failure_result["warnings"]), 9)
            self.assertIn("HTTP Error 503", stderr.getvalue())
            for query in collect.CATEGORIES[0].broad_queries:
                self.assertIn(query, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
