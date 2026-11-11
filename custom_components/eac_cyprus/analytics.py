"""Bounded per-meter interval cache and account-independent energy insights."""

from __future__ import annotations

import math
from datetime import UTC, datetime, time, timedelta
from statistics import median

from .time import PORTAL_TIME_ZONE, as_utc

DEFAULT_PROFILE_DAYS = 30
DEFAULT_NIGHT_START = 0
DEFAULT_NIGHT_END = 6
CONF_PROFILE_DAYS = "profile_days"
CONF_NIGHT_START = "night_start_hour"
CONF_NIGHT_END = "night_end_hour"


def window_start(now: datetime, days: int) -> datetime:
    date = now.astimezone(PORTAL_TIME_ZONE).date() - timedelta(days=days - 1)
    return datetime.combine(date, time(), PORTAL_TIME_ZONE).astimezone(UTC)


def merge_profile(cache: dict, direction: str, readings, start, end, now, days):
    """Replace explicitly returned timestamps; absent rows remain gaps, not zero."""
    cutoff = window_start(now, days)
    values = cache.setdefault(direction, {})
    for reading in readings:
        stamp = as_utc(reading.dt)
        if stamp is None or not max(start, cutoff) < stamp <= min(end, now):
            continue
        if stamp.timestamp() % 1800:
            continue
        key = str(int(stamp.timestamp()))
        if math.isfinite(reading.value) and reading.value >= 0:
            values[key] = reading.value
        else:
            values.pop(key, None)
    for key in list(values):
        if not cutoff.timestamp() < int(key) <= now.timestamp():
            del values[key]


def profile_insights(
    cache: dict, now: datetime, days: int, night_start: int, night_end: int
):
    """Keep independent direction coverage; never assume absent exports are zero."""
    cutoff = window_start(now, days)
    channels = {}
    for direction in ("import", "export"):
        channels[direction] = {
            int(key): value
            for key, value in cache.get(direction, {}).items()
            if cutoff.timestamp() < int(key) <= now.timestamp()
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0
        }
    incoming, outgoing = channels["import"], channels["export"]
    stamps = sorted(incoming.keys() | outgoing.keys())
    points = [
        [stamp * 1000, incoming.get(stamp), outgoing.get(stamp)] for stamp in stamps
    ]
    expected = max(0, int((now - cutoff).total_seconds() // 1800))
    paired = incoming.keys() & outgoing.keys()
    peak_stamp = max(incoming, key=incoming.get) if incoming else None
    # Only complete configured night windows contribute. UTC stepping handles DST.
    nights = []
    date = cutoff.astimezone(PORTAL_TIME_ZONE).date()
    today = now.astimezone(PORTAL_TIME_ZONE).date()
    while date <= today:
        start = datetime.combine(date, time(night_start), PORTAL_TIME_ZONE).astimezone(
            UTC
        )
        end_date = date + timedelta(days=night_end <= night_start)
        end = datetime.combine(end_date, time(night_end), PORTAL_TIME_ZONE).astimezone(
            UTC
        )
        if start >= cutoff and end <= now:
            times = list(
                range(int(start.timestamp()) + 1800, int(end.timestamp()) + 1, 1800)
            )
            if times and all(t in incoming for t in times):
                nights.append(math.fsum(incoming[t] for t in times) / (len(times) / 2))
        date += timedelta(days=1)
    # Typical surplus by local half-hour of day. Include explicit zero exports,
    # exclude missing data and retain sample counts (including repeated DST slots).
    slots = [[] for _ in range(48)]
    for stamp, value in outgoing.items():
        local_start = datetime.fromtimestamp(stamp - 1800, UTC).astimezone(
            PORTAL_TIME_ZONE
        )
        slots[local_start.hour * 2 + local_start.minute // 30].append(value)
    surplus = [
        [i, math.fsum(v) / len(v) * 2 if v else None, len(v)]
        for i, v in enumerate(slots)
    ]
    return {
        "window_days": days,
        "window_start": cutoff.isoformat(),
        "time_zone": "Asia/Nicosia",
        "timestamp_convention": "interval_end",
        "expected_intervals": expected,
        "import_intervals": len(incoming),
        "export_intervals": len(outgoing),
        "paired_intervals": len(paired),
        "import_coverage_percent": round(100 * len(incoming) / expected, 1)
        if expected
        else None,
        "export_coverage_percent": round(100 * len(outgoing) / expected, 1)
        if expected
        else None,
        "data_through": datetime.fromtimestamp(stamps[-1], UTC).isoformat()
        if stamps
        else None,
        "peak_import_kw": incoming[peak_stamp] * 2 if peak_stamp else None,
        "peak_import_at": datetime.fromtimestamp(peak_stamp, UTC).isoformat()
        if peak_stamp
        else None,
        "overnight_baseline_kw": median(nights) if nights else None,
        "complete_nights": len(nights),
        "night_start_hour": night_start,
        "night_end_hour": night_end,
        "points": points,
        "surplus_by_half_hour": surplus,
    }
