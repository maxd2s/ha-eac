"""Bounded, paired half-hour estimates for the current Cyprus day only."""

from __future__ import annotations

import math
from datetime import UTC, datetime, time, timedelta

from eac_dso_portal import Reading

from .time import PORTAL_TIME_ZONE, as_utc

INTERVAL_DIRECTIONS = {
    "KWH-30MIN-LP-IMP": "import",
    "KWH-30MIN-LP-EXP": "export",
}


def today_profile(
    imports: tuple[Reading, ...], exports: tuple[Reading, ...], now: datetime
) -> dict:
    """Pair interval-end timestamps; missing or invalid data is never zero.

    Rebuild from the fetched window on every poll: no accumulating duplicates
    across refreshes or restarts. UTC arithmetic preserves real DST intervals.
    Midnight closes yesterday; future and off-grid observations are excluded.
    """
    now = as_utc(now)
    date = now.astimezone(PORTAL_TIME_ZONE).date()
    start = datetime.combine(date, time(), PORTAL_TIME_ZONE).astimezone(UTC)
    expected = int((now - start).total_seconds() // 1800)

    def index(readings):
        values = {}
        for r in readings:
            stamp = as_utc(r.dt)
            if stamp is None or not start < stamp <= now:
                continue
            if (stamp - start).total_seconds() % 1800:
                continue
            # Last duplicate wins, including an invalid replacement.
            values[stamp] = r.value if math.isfinite(r.value) and r.value >= 0 else None
        return {stamp: value for stamp, value in values.items() if value is not None}

    incoming, outgoing = index(imports), index(exports)
    stamps = sorted(incoming.keys() & outgoing.keys())
    points = [[stamp.isoformat(), incoming[stamp], outgoing[stamp]] for stamp in stamps]
    latest = stamps[-1] if stamps else None
    through = int((latest - start).total_seconds() // 1800) if latest else 0
    return {
        "date": date.isoformat(),
        "time_zone": "Asia/Nicosia",
        "provisional": True,
        "timestamp_convention": "interval_end",
        "interval_minutes": 30,
        "import_kwh": math.fsum(incoming[s] for s in stamps) if stamps else None,
        "export_kwh": math.fsum(outgoing[s] for s in stamps) if stamps else None,
        "paired_intervals": len(stamps),
        "expected_intervals": expected,
        "missing_intervals": expected - len(stamps),
        "gaps_before_latest": through - len(stamps),
        "data_through": latest.isoformat() if latest else None,
        "day_start": start.isoformat(),
        "day_hours": (
            datetime.combine(
                date + timedelta(days=1), time(), PORTAL_TIME_ZONE
            ).astimezone(UTC)
            - start
        ).total_seconds()
        / 3600,
        "points": points,
    }
