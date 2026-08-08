from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fallback_guard  # noqa: E402


class FallbackGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 8, 9, 40, tzinfo=timezone.utc)

    def test_manual_and_cloudflare_dispatches_always_run(self) -> None:
        fresh = self.now - timedelta(minutes=1)
        for event_name in ("workflow_dispatch", "push"):
            self.assertTrue(
                fallback_guard.fallback_is_needed(event_name, fresh, self.now)
            )

    def test_scheduled_fallback_skips_a_fresh_snapshot(self) -> None:
        updated_at = self.now - timedelta(minutes=10)
        self.assertFalse(
            fallback_guard.fallback_is_needed("schedule", updated_at, self.now)
        )

    def test_scheduled_fallback_runs_for_a_stale_snapshot(self) -> None:
        updated_at = self.now - timedelta(minutes=40)
        self.assertTrue(
            fallback_guard.fallback_is_needed("schedule", updated_at, self.now)
        )

    def test_scheduled_fallback_runs_when_timestamp_is_unavailable(self) -> None:
        self.assertTrue(
            fallback_guard.fallback_is_needed("schedule", None, self.now)
        )

    def test_future_timestamp_runs_to_repair_clock_or_data_errors(self) -> None:
        updated_at = self.now + timedelta(minutes=1)
        self.assertTrue(
            fallback_guard.fallback_is_needed("schedule", updated_at, self.now)
        )


if __name__ == "__main__":
    unittest.main()
