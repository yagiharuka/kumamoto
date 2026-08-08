#!/usr/bin/env python3
"""Run a delayed GitHub fallback only when the primary refresh is stale."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "news.json"
MAX_FRESH_AGE = timedelta(minutes=25)


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
) -> bool:
    if event_name != "schedule":
        return True
    if updated_at is None:
        return True
    age = now.astimezone(timezone.utc) - updated_at
    return age < timedelta(0) or age > MAX_FRESH_AGE


def write_output(should_run: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"should_run={'true' if should_run else 'false'}\n")


def main() -> int:
    event_name = os.environ.get("FALLBACK_EVENT_NAME", "workflow_dispatch")
    now = datetime.now(timezone.utc)
    updated_at = load_updated_at()
    should_run = fallback_is_needed(event_name, updated_at, now)
    write_output(should_run)

    if event_name != "schedule":
        print("Primary or manual trigger: collection will run.")
    elif should_run:
        age = "unknown" if updated_at is None else str(now - updated_at).split(".")[0]
        print(f"Snapshot is stale (age: {age}); fallback collection will run.")
    else:
        age = str(now - updated_at).split(".")[0]
        print(f"Snapshot is fresh (age: {age}); fallback collection is skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
