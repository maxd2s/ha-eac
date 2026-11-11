# Data model and statistics

## Data flow

```text
Official EAC DSO HTTPS API
  → constrained async client + pinned upstream models
  → account coordinator (serial requests, 30-minute default poll)
      → service point → physical meter → latest channel sensors
      → external Recorder statistics → Energy Dashboard / charts
```

The runtime uses the upstream parser, not a headless browser or subprocess. There is no local server, telemetry endpoint, or outgoing notification service in the integration.

## Whole-meter mapping

| Portal channel | Continuous series |
|---|---|
| S-KWH-24H | Grid import |
| S-KWH-NET-IMP-MMTR | Grid import |
| S-KWH-EXP | Grid export |
| S-KWH-NET-EXP-MMTR | Grid export |
| S-KWH-NORMAL | Original peak register only |
| S-KWH-OFFPEAK | Original off-peak register only |

The continuous series is keyed by service point and physical meter serial. A channel/configuration change on the same serial can therefore continue the same register history. This assumes cumulative values remain comparable. Replacement meters stay separate. Unknown channels are never automatically merged into grid totals.

Net history pairs import and export at **exact matching measurement timestamps** before assigning observations to hours. Missing export is not assumed zero. Net register differences can be negative. Net is an energy balance, not a monetary balance; the integration has no tariff or solar-credit settlement engine.

## Timestamps and aggregation

Offset-free portal timestamps are interpreted as **Asia/Nicosia**; explicit UTC offsets are respected. This matches the current portal interpretation but cannot resolve ambiguous offset-free readings during the repeated autumn DST hour. Verify against your own portal exports before relying on precise time-band billing.

Continuous grid series subtract one microsecond from a measurement timestamp before rounding down to its UTC hour. A register reading at midnight therefore belongs to the hour closing the previous day. Use the correct HA time zone for daily/monthly chart boundaries.

Original per-channel statistics retain the older convention: round the measurement timestamp down to its starting UTC hour. They remain for compatibility and inspection; they can appear one day later than continuous grid statistics for midnight readings. Do not combine the two representations in one energy total.

Recorder receives absolute cumulative `sum` values, not individual interval consumption. Chart changes are differences between register observations; the initial absolute value is not consumption since installation of this integration. At least two observations are needed for a difference. Duplicate hours keep the last observation. NaN, infinity and negative cumulative register values are excluded from statistics.

Daily register observations cannot reconstruct when consumption happened within the day. Missing dates are not interpolated: later differences can cover several days. Original peak/off-peak register differences may differ slightly from the total because of register precision/rounding.

## Freshness

Each sensor has its own `measured_at` attribute. Meter-wide diagnostic timestamps use the newest available reading across all channels. They can show a recent load profile while daily import/export registers remain older. `Data lag` is calculated at fetch time; it does not tick between polls. A successful poll can return unchanged data.

## Today so far — provisional

Meters exposing both `KWH-30MIN-LP-IMP` and `KWH-30MIN-LP-EXP` receive three
additional sensors: **Today import provisional**, **Today export provisional**,
and **Today net provisional**. They sum interval energy from matching, valid
half-hour timestamps on the current Cyprus day. Both sides use exactly the
same intervals. No matching readings means unknown, not zero. These values
are grid energy, not total household consumption or total solar generation.

The provisional view interprets portal timestamps as **interval ends**, with
00:00 closing the previous day. This convention is an explicit assumption for
the undocumented load-profile endpoint, not a billing guarantee. Offset-free
DST ambiguity has the same limitation described above. Coverage counts use
real elapsed UTC half-hours across 23/25-hour Cyprus days.

Each refresh rebuilds from the already-fetched window, so repeated requests,
restarts and corrections cannot accumulate duplicate energy. No additional API
calls are made. Unmatched, negative, nonfinite, future and off-grid readings
are excluded. The sensors expose paired/expected interval counts, internal gap
count and `data_through`. Totals after gaps include received intervals only.
They clear at the first minute tick of a new Cyprus day even if polling fails.

These sensors have **no state class** and never write to the canonical daily
register statistics. Only the net sensor includes the bounded `points` graph
payload (up to 50 half-hours); that attribute is excluded from Recorder.
This is a current-day preview, not a long-term interval archive.

Optional dependency-free dashboard card: see [dashboard/README.md](../dashboard/README.md).

## Limitations

- No automatic cumulative reset/rollover correction or stitching across physical meter replacements.
- No historical half-hour load-profile statistics; latest snapshots and a current-day provisional view are available.
- No solar generation or total household consumption estimate from grid export alone.
- A retired-meter snapshot is cached in memory until reload; later upstream corrections may require a reload or explicit history import.
- Historical imports are bounded to 3,650 days and 10 minutes per account. Recorder queueing is asynchronous and not transactional across an import.
- Portal errors or omitted channels can make affected entities unavailable; a successful account refresh does not imply every channel was delivered.
- Statistic IDs and device labels include meter/service-point identifiers. Treat database backups and diagnostic screenshots as private.

## Cached interval insights and tariffs (0.5.0)

The account coordinator keeps a per-meter, per-direction cache in HA storage,
separate from Recorder's cumulative register statistics. Retention is configurable
from 7 to 90 Cyprus calendar days (default 30, including today's partial day).
The first poll seeds this window through the existing 14-day request chunking.
Subsequent polls reuse the configured rolling fetch window; restart gaps and
increased retention trigger bounded backfill. Meter configuration dates restrict
requests and prevent mixing channels outside their valid periods.

Import and export are independently available. Missing export never becomes zero.
Explicitly returned corrections replace existing intervals; invalid returned values
remove those intervals. Missing rows do not erase previously received cached values.
Older provider corrections outside the regular fetch window may remain until the
cache is rebuilt or the window is expanded. Retention expires old samples. History
is private to the local HA storage and is not a permanent interval archive.

Half-hour timestamps retain the documented interval-end assumption. Profile graphs
show **average kW = interval kWh × 2**, not instantaneous demand. Missing intervals
break lines. Coverage is received intervals divided by elapsed intervals in the
retained window; a recent installation or configuration gap can reduce it.

**Overnight baseline** is the median of each complete configured night's average
grid-import power. Only windows with every half-hour present and whose end is in
the past contribute. This includes overnight EV charging/heating and is not a
measurement of appliance standby load or whole-house demand. UTC stepping handles
23/25-hour DST days; offset-free ambiguous autumn timestamps remain unresolved.
**Highest demand** is the highest observed half-hour average, not a fuse-sizing peak.
**Surplus profile** averages exported power by local half-hour slot and reports its
sample count. It includes observed zeros, excludes missing samples, and is not a
forecast or total PV generation.

Tariff identifiers are read from the authenticated DSO consumption report, at most
once per active meter per 24 hours. Only the code, source and retrieval time are
stored; report HTML and personal report fields are discarded. Codes and prices are
never inferred from meter model, account identity or channel names. A missing or
changed report format leaves the code unknown (or retains the previous code with
its original retrieval date). No tariff-price/settlement engine is included.

`eac_cyprus/profile_meters` and `eac_cyprus/profile` are authenticated read-only HA
WebSocket commands. They return only meters whose Profile coverage entity the user
may read. Responses are served from memory; they cannot trigger DSO requests or
retrieve another account by supplying a service-point identifier. Interval arrays
are not stored in entity attributes or Recorder. The standalone card contains no
account-specific identifiers or external libraries.
