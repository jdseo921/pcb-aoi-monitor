"""Times: stored in UTC as ISO 8601 with an offset, shown in local time (REQ-SET-017, ADR 0004).

Every stored time looks like 2026-10-01T05:05:00+00:00, so records from any station sort and compare as
text and never depend on the station's clock settings. Screens show the same instant in the local time
zone, 24-hour, ISO date: 2026-10-01 14:05:00.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

SHOWN = "%Y-%m-%d %H:%M:%S"


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def to_local(stored: str) -> str:
    """A stored time as the user sees it. A time without an offset (v0.1 data) is shown as it was written."""
    t = datetime.fromisoformat(stored)
    return stored.replace("T", " ") if t.tzinfo is None else t.astimezone().strftime(SHOWN)


def local_day_bounds_utc(date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    """Local calendar dates (YYYY-MM-DD) as stored-time bounds: from the start of `date_from` (inclusive) to
    the start of the day after `date_to` (exclusive), both in UTC."""

    def start_of(day: str, days_later: int = 0) -> str:
        local = (datetime.fromisoformat(day) + timedelta(days=days_later)).astimezone()  # naive = local time
        return local.astimezone(UTC).isoformat(timespec="seconds")

    return (start_of(date_from) if date_from else None, start_of(date_to, 1) if date_to else None)


def local_date() -> str:
    """Today's local date, for folder names an operator reads (results/2026-10-01/)."""
    return datetime.now().strftime("%Y-%m-%d")
