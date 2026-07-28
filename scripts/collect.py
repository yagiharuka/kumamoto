#!/usr/bin/env python3
"""Collect strictly allow-listed coverage of the Kumamoto AEON incident.

The collector uses Google News RSS only as a discovery index. It persists
headlines, publisher attribution, publication time, and the article link; it
does not scrape or republish article bodies.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PATH = ROOT / "data" / "news.json"
PUBLIC_PATH = ROOT / "docs" / "data" / "news.json"
RESULT_PATH = ROOT / ".work" / "update_result.json"

QUERY = "熊本 イオン 爆発"
INCIDENT_START = datetime(2026, 7, 27, tzinfo=timezone.utc)
CADENCE_MINUTES = 30
MAX_RESPONSE_BYTES = 6 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 18
RETRY_DELAYS_SECONDS = (1, 3)
USER_AGENT = "KumamotoAeonNewsWatch/1.0 (+https://github.com/yagiharuka/kumamoto)"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


@dataclass(frozen=True)
class Outlet:
    id: str
    name: str
    group: str
    aliases: tuple[str, ...]
    domain: str


OUTLETS = (
    Outlet(
        "asahi",
        "朝日新聞",
        "全国紙",
        ("朝日新聞", "朝日新聞デジタル"),
        "asahi.com",
    ),
    Outlet(
        "yomiuri",
        "読売新聞",
        "全国紙",
        ("読売新聞", "読売新聞オンライン"),
        "yomiuri.co.jp",
    ),
    Outlet(
        "mainichi",
        "毎日新聞",
        "全国紙",
        ("毎日新聞",),
        "mainichi.jp",
    ),
    Outlet(
        "sankei",
        "産経新聞",
        "全国紙",
        ("産経新聞", "産経ニュース"),
        "sankei.com",
    ),
    Outlet(
        "nikkei",
        "日本経済新聞",
        "全国紙",
        ("日本経済新聞", "日本経済新聞 電子版"),
        "nikkei.com",
    ),
    Outlet(
        "kumanichi",
        "熊本日日新聞",
        "地元紙",
        ("熊本日日新聞", "熊本日日新聞社"),
        "kumanichi.com",
    ),
    Outlet(
        "jiji",
        "時事通信",
        "通信社",
        ("時事通信", "時事ドットコム", "時事通信ニュース", "JIJI.COM"),
        "jiji.com",
    ),
)

OUTLETS_BY_ALIAS = {
    unicodedata.normalize("NFKC", alias).strip(): outlet
    for outlet in OUTLETS
    for alias in outlet.aliases
}

BROAD_QUERIES = (
    '"イオンモール熊本" after:2026-07-27',
    "熊本 イオン 爆発 after:2026-07-27",
)


class CollectionError(RuntimeError):
    """Raised when a run cannot safely produce an updated snapshot."""


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def normalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    filtered_query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(("utm_", "gclid", "fbclid"))
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/") or "/",
            urlencode(filtered_query),
            "",
        )
    )


def title_fingerprint(source_id: str, title: str) -> str:
    normalized = normalize_text(title).lower()
    normalized = re.sub(r"^【[^】]+】", "", normalized)
    normalized = re.sub(r"[\s\"'「」『』【】［］（）()、。・…：:！？!?／/\\\-—–]", "", normalized)
    return f"{source_id}:{normalized}"


def build_feed_url(query: str) -> str:
    return f"{GOOGLE_NEWS_RSS}?{urlencode({'q': query, 'hl': 'ja', 'gl': 'JP', 'ceid': 'JP:ja'})}"


def _read_response(response: Any) -> bytes:
    declared_length = response.headers.get("Content-Length")
    if declared_length and int(declared_length) > MAX_RESPONSE_BYTES:
        raise CollectionError("RSS response exceeded the size limit")
    payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise CollectionError("RSS response exceeded the size limit")
    return payload


def fetch_bytes(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8",
            "User-Agent": USER_AGENT,
        },
    )
    attempts = len(RETRY_DELAYS_SECONDS) + 1
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                if getattr(response, "status", 200) != 200:
                    raise CollectionError(f"RSS returned HTTP {response.status}")
                return _read_response(response)
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or 500 <= error.code < 600
            if not retryable or attempt == attempts - 1:
                break
        except (TimeoutError, URLError, OSError, CollectionError) as error:
            last_error = error
            if attempt == attempts - 1:
                break

        time.sleep(RETRY_DELAYS_SECONDS[attempt])

    raise CollectionError(f"RSS fetch failed: {last_error}") from last_error


def element_text(parent: ElementTree.Element, tag: str) -> str:
    node = parent.find(tag)
    return normalize_text(node.text or "") if node is not None else ""


def strip_markup(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(value))
    return normalize_text(without_tags)


def parse_rss(payload: bytes) -> list[dict[str, str]]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise CollectionError(f"invalid RSS XML: {error}") from error

    if root.tag.lower().split("}")[-1] != "rss":
        raise CollectionError("response was not an RSS document")

    records: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        source_node = item.find("source")
        records.append(
            {
                "title": element_text(item, "title"),
                "link": element_text(item, "link"),
                "guid": element_text(item, "guid"),
                "pub_date": element_text(item, "pubDate"),
                "source": normalize_text(source_node.text or "")
                if source_node is not None
                else "",
                "description": strip_markup(element_text(item, "description")),
            }
        )
    return records


def resolve_outlet(source_label: str) -> Outlet | None:
    return OUTLETS_BY_ALIAS.get(normalize_text(source_label))


def clean_title(raw_title: str, source_label: str) -> str:
    title = normalize_text(raw_title)
    suffix = f" - {normalize_text(source_label)}"
    if title.endswith(suffix):
        title = title[: -len(suffix)]
    return normalize_text(title)


def parse_published_at(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def has_uki_reference(value: str) -> bool:
    normalized = normalize_text(value)
    if "イオンモール宇城" in normalized:
        return True
    romanized = normalized.upper()
    return bool(
        re.search(r"(?:AEON.{0,18}UKI|UKI.{0,18}AEON)", romanized, re.IGNORECASE)
        or re.search(r"(?:イオン.{0,18}宇城|宇城.{0,18}イオン)", normalized)
    )


def is_target_report(title: str, description: str) -> bool:
    combined = normalize_text(f"{title} {description}")
    explicit_target = "イオンモール熊本" in combined or "イオン熊本" in combined
    if has_uki_reference(combined) and not explicit_target:
        return False
    if explicit_target:
        return True
    return bool(
        ("イオン" in combined or "AEON" in combined.upper())
        and re.search(r"(熊本|嘉島)", combined)
    )


def focus_from_title(title: str) -> list[str]:
    tags: list[str] = []
    rules = (
        (r"(原因|ガス|検証)", "原因・検証"),
        (r"(救助|安否|閉じ込|下敷き|搬送|けが|死者|不明)", "救助・安否"),
        (r"(避難|来店客|従業員)", "避難状況"),
        (r"(証言|地響き|ドーン|爆発音|白煙|煙)", "目撃証言"),
        (r"(崩落|崩壊|損壊|爆発)", "現場状況"),
    )
    for pattern, label in rules:
        if re.search(pattern, title):
            tags.append(label)
    return tags[:3]


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_item(record: dict[str, str], seen_at: datetime) -> dict[str, Any] | None:
    source_label = record["source"]
    outlet = resolve_outlet(source_label)
    published = parse_published_at(record["pub_date"])
    link = record["link"].strip()
    title = clean_title(record["title"], source_label)
    parsed_link = urlsplit(link)

    if (
        not outlet
        or not title
        or not published
        or published < INCIDENT_START
        or parsed_link.scheme not in {"http", "https"}
        or not parsed_link.netloc
        or not is_target_report(title, record["description"])
    ):
        return None

    identity = record["guid"] or normalize_url(link)
    article_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return {
        "id": article_id,
        "title": title,
        "source": outlet.name,
        "source_id": outlet.id,
        "source_group": outlet.group,
        "published_at": iso_utc(published),
        "url": link,
        "first_seen": iso_utc(seen_at),
        "focus": focus_from_title(title),
    }


def fetch_query(query: str) -> tuple[str, list[dict[str, str]]]:
    return query, parse_rss(fetch_bytes(build_feed_url(query)))


def fetch_queries(
    queries: Iterable[str],
) -> tuple[list[dict[str, str]], list[str], int]:
    query_list = list(dict.fromkeys(queries))
    records: list[dict[str, str]] = []
    warnings: list[str] = []
    success_count = 0

    with ThreadPoolExecutor(max_workers=min(8, len(query_list) or 1)) as executor:
        futures = {executor.submit(fetch_query, query): query for query in query_list}
        for future in as_completed(futures):
            query = futures[future]
            try:
                _, result = future.result()
            except Exception as error:  # A partial feed outage should not erase history.
                warnings.append(f"{query}: {error}")
            else:
                success_count += 1
                records.extend(result)
    return records, warnings, success_count


def collect_candidates(now: datetime) -> tuple[list[dict[str, Any]], list[str]]:
    raw_records, warnings, broad_successes = fetch_queries(BROAD_QUERIES)
    if broad_successes == 0:
        raise CollectionError("all primary RSS queries failed")

    candidates = [
        item
        for item in (to_item(record, now) for record in raw_records)
        if item is not None
    ]
    present_sources = {item["source_id"] for item in candidates}
    missing_outlets = [outlet for outlet in OUTLETS if outlet.id not in present_sources]
    supplements = [
        f'"イオンモール熊本" after:2026-07-27 site:{outlet.domain}'
        for outlet in missing_outlets
    ]
    supplemental_records, supplemental_warnings, _ = fetch_queries(supplements)
    warnings.extend(supplemental_warnings)
    candidates.extend(
        item
        for item in (to_item(record, now) for record in supplemental_records)
        if item is not None
    )
    return candidates, warnings


def tracked_sources() -> list[dict[str, str]]:
    return [
        {"id": outlet.id, "name": outlet.name, "group": outlet.group}
        for outlet in OUTLETS
    ]


def empty_snapshot() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "updated_at": None,
        "updated_at_jst": None,
        "query": QUERY,
        "cadence_minutes": CADENCE_MINUTES,
        "article_count": 0,
        "source_count": 0,
        "tracked_sources": tracked_sources(),
        "source_counts": {},
        "items": [],
    }


REQUIRED_ITEM_KEYS = {
    "id",
    "title",
    "source",
    "source_id",
    "source_group",
    "published_at",
    "url",
    "first_seen",
    "focus",
}


def load_snapshot(path: Path = ARCHIVE_PATH) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return empty_snapshot(), True
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CollectionError(f"could not read existing history: {error}") from error

    if snapshot.get("schema_version") != 1 or not isinstance(snapshot.get("items"), list):
        raise CollectionError("existing history has an unsupported schema")
    for item in snapshot["items"]:
        if not isinstance(item, dict) or not REQUIRED_ITEM_KEYS.issubset(item):
            raise CollectionError("existing history contains an invalid item")
    return snapshot, False


def merge_items(
    existing_items: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged = [dict(item) for item in existing_items]
    url_index = {normalize_url(item["url"]): index for index, item in enumerate(merged)}
    title_index = {
        title_fingerprint(item["source_id"], item["title"]): index
        for index, item in enumerate(merged)
    }
    new_items: list[dict[str, Any]] = []

    candidates = sorted(
        candidates,
        key=lambda item: (
            item["published_at"],
            item["source"],
            item["title"],
            item["url"],
        ),
        reverse=True,
    )
    for candidate in candidates:
        url_key = normalize_url(candidate["url"])
        title_key = title_fingerprint(candidate["source_id"], candidate["title"])
        existing_index = url_index.get(url_key)
        if existing_index is None:
            existing_index = title_index.get(title_key)

        if existing_index is not None:
            previous = merged[existing_index]
            refreshed = {**previous, **candidate}
            refreshed["id"] = previous["id"]
            refreshed["first_seen"] = previous["first_seen"]
            merged[existing_index] = refreshed
            url_index[normalize_url(refreshed["url"])] = existing_index
            title_index[
                title_fingerprint(refreshed["source_id"], refreshed["title"])
            ] = existing_index
            continue

        merged.append(candidate)
        index = len(merged) - 1
        url_index[url_key] = index
        title_index[title_key] = index
        new_items.append(candidate)

    merged.sort(
        key=lambda item: (
            item["published_at"],
            item["source"],
            item["title"],
            item["url"],
        ),
        reverse=True,
    )
    new_items.sort(key=lambda item: item["published_at"], reverse=True)
    return merged, new_items


def make_snapshot(items: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item["source_id"]] = counts.get(item["source_id"], 0) + 1
    from zoneinfo import ZoneInfo

    jst = now.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M JST")
    return {
        "schema_version": 1,
        "updated_at": iso_utc(now),
        "updated_at_jst": jst,
        "query": QUERY,
        "cadence_minutes": CADENCE_MINUTES,
        "article_count": len(items),
        "source_count": len(counts),
        "tracked_sources": tracked_sources(),
        "source_counts": counts,
        "items": items,
    }


def serialized(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def write_result(result: dict[str, Any]) -> None:
    atomic_write(RESULT_PATH, serialized(result))


def main() -> int:
    now = datetime.now(timezone.utc)
    try:
        previous, first_run = load_snapshot()
        candidates, warnings = collect_candidates(now)
        merged, new_items = merge_items(previous["items"], candidates)
        snapshot = make_snapshot(merged, now)
        content = serialized(snapshot)
        atomic_write(ARCHIVE_PATH, content)
        atomic_write(PUBLIC_PATH, content)
        write_result(
            {
                "status": "ok",
                "run_at": iso_utc(now),
                "run_at_jst": snapshot["updated_at_jst"],
                "first_run": first_run,
                "new_count": len(new_items),
                "total_count": len(merged),
                "new_items": new_items,
                "warnings": warnings,
            }
        )
        print(
            f"Collected {len(candidates)} candidates; "
            f"{len(new_items)} new; {len(merged)} total."
        )
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0
    except Exception as error:
        from zoneinfo import ZoneInfo

        write_result(
            {
                "status": "failed",
                "run_at": iso_utc(now),
                "run_at_jst": now.astimezone(ZoneInfo("Asia/Tokyo")).strftime(
                    "%Y/%m/%d %H:%M JST"
                ),
                "error": str(error),
            }
        )
        print(f"collection failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
