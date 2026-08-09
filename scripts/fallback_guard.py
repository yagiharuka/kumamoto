#!/usr/bin/env python3
"""Run a delayed fallback only when its target primary refresh is missing."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "news.json"
MAX_CLOCK_SKEW = timedelta(minutes=5)


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


def load_updated_at(path: Path = SNAPSHOT_PATH) -> datetime | None:
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parse_utc(snapshot.get("updated_at")) if isinstance(snapshot, dict) else None


def fallback_is_needed(
    event_name: str,
    updated_at: datetime | None,
    now: datetime,
    schedule: str | None = None,
) -> bool:
    if event_name != "schedule":
        return True
    if updated_at is None:
        return True
    now = now.astimezone(timezone.utc)
    if updated_at > now + MAX_CLOCK_SKEW:
        return True
    target = target_primary_time(schedule, now)
    if target is None:
        return True
    return updated_at < target


def target_primary_time(schedule: str | None, now: datetime) -> datetime | None:
    """Return the primary :00 or :30 slot assigned to this fallback."""
    now = now.astimezone(timezone.utc)
    if schedule == "10 * * * *":
        target = now.replace(minute=0, second=0, microsecond=0)
        if now.minute < 10:
            target -= timedelta(hours=1)
        return target
    if schedule == "40 * * * *":
        target = now.replace(minute=30, second=0, microsecond=0)
        if now.minute < 40:
            target -= timedelta(hours=1)
        return target
    return None


def write_output(should_run: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"should_run={'true' if should_run else 'false'}\n")


def main() -> int:
    event_name = os.environ.get("FALLBACK_EVENT_NAME", "workflow_dispatch")
    schedule = os.environ.get("FALLBACK_SCHEDULE")
    now = datetime.now(timezone.utc)
    updated_at = load_updated_at()
    target = target_primary_time(schedule, now) if event_name == "schedule" else None
    should_run = fallback_is_needed(event_name, updated_at, now, schedule)
    write_output(should_run)

    if event_name != "schedule":
        print("Primary or manual trigger: collection will run.")
    elif should_run:
        target_text = "unknown" if target is None else target.isoformat()
        print(f"Target primary slot is missing ({target_text}); fallback will run.")
    else:
        print(
            "Target primary slot is already covered "
            f"({target.isoformat()}); fallback is skipped."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
