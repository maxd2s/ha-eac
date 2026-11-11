"""Portal timestamps without an offset represent Cyprus local civil time."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

PORTAL_TIME_ZONE = ZoneInfo("Asia/Nicosia")


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=PORTAL_TIME_ZONE)
    return value.astimezone(UTC)
