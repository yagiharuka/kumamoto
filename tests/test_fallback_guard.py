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
        self.now = datetime(2026, 8, 8, 9, 59, tzinfo=timezone.utc)

    def test_manual_and_push_dispatches_always_run(self) -> None:
        fresh = self.now - timedelta(minutes=1)
        for event_name in ("workflow_dispatch", "push"):
            self.assertTrue(
                fallback_guard.fallback_is_needed(event_name, fresh, self.now)
            )

    def test_duplicate_cloudflare_dispatch_skips_covered_current_slot(self) -> None:
        now = self.now.replace(minute=31)
        updated_at = now.replace(second=5)
        self.assertFalse(
            fallback_guard.fallback_is_needed(
                "workflow_dispatch",
                updated_at,
                now,
                trigger="cloudflare-cron",
            )
        )

    def test_cloudflare_dispatch_runs_when_current_slot_is_missing(self) -> None:
        now = self.now.replace(minute=31)
        updated_at = now.replace(minute=29)
        self.assertTrue(
            fallback_guard.fallback_is_needed(
                "workflow_dispatch",
                updated_at,
                now,
                trigger="cloudflare-cron",
            )
        )

    def test_cloudflare_dispatch_runs_when_timestamp_is_in_the_future(self) -> None:
        updated_at = self.now + timedelta(minutes=6)
        self.assertTrue(
            fallback_guard.fallback_is_needed(
                "workflow_dispatch",
                updated_at,
                self.now,
                trigger="cloudflare-cron",
            )
        )

    def test_current_primary_time_selects_the_active_half_hour(self) -> None:
        at_top = self.now.replace(minute=29)
        at_half = self.now.replace(minute=31)
        self.assertEqual(
            fallback_guard.current_primary_time(at_top),
            at_top.replace(minute=0, second=0, microsecond=0),
        )
        self.assertEqual(
            fallback_guard.current_primary_time(at_half),
            at_half.replace(minute=30, second=0, microsecond=0),
        )

    def test_delayed_40_minute_fallback_skips_completed_30_minute_slot(self) -> None:
        updated_at = self.now.replace(minute=31)
        self.assertFalse(
            fallback_guard.fallback_is_needed(
                "schedule", updated_at, self.now, "40 * * * *"
            )
        )

    def test_delayed_40_minute_fallback_runs_when_30_minute_slot_is_missing(self) -> None:
        updated_at = self.now.replace(minute=1)
        self.assertTrue(
            fallback_guard.fallback_is_needed(
                "schedule", updated_at, self.now, "40 * * * *"
            )
        )

    def test_10_minute_fallback_targets_the_top_of_the_hour(self) -> None:
        now = self.now.replace(minute=16)
        target = fallback_guard.target_primary_time("10 * * * *", now)
        self.assertEqual(target, now.replace(minute=0, second=0, microsecond=0))

    def test_fallback_delayed_into_next_hour_keeps_previous_target(self) -> None:
        now = self.now.replace(hour=10, minute=2)
        target = fallback_guard.target_primary_time("40 * * * *", now)
        self.assertEqual(
            target,
            now.replace(hour=9, minute=30, second=0, microsecond=0),
        )

    def test_scheduled_fallback_runs_when_timestamp_is_unavailable(self) -> None:
        self.assertTrue(
            fallback_guard.fallback_is_needed(
                "schedule", None, self.now, "40 * * * *"
            )
        )

    def test_future_timestamp_runs_to_repair_clock_or_data_errors(self) -> None:
        updated_at = self.now + timedelta(minutes=6)
        self.assertTrue(
            fallback_guard.fallback_is_needed(
                "schedule", updated_at, self.now, "40 * * * *"
            )
        )

    def test_unknown_schedule_fails_safe_and_runs(self) -> None:
        self.assertTrue(
            fallback_guard.fallback_is_needed(
                "schedule", self.now, self.now, "unknown"
            )
        )


if __name__ == "__main__":
    unittest.main()
