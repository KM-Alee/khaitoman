"""UTC instants for storage, Asia/Karachi local crop dates (T3.2)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

PKT = ZoneInfo("Asia/Karachi")


def require_aware(dt: datetime, name: str = "instant") -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must carry a UTC offset; naive timestamps are ambiguous")
    return dt


def to_utc(dt: datetime) -> datetime:
    return require_aware(dt).astimezone(timezone.utc)


def parse_instant(text: str) -> datetime:
    """Parse an ISO instant that must include an offset or Z."""
    return to_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))


def local_crop_date(dt: datetime) -> date:
    return require_aware(dt).astimezone(PKT).date()


def iso_week(d: date) -> tuple[int, int]:
    y, w, _ = d.isocalendar()
    return y, w
