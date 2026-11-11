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

## Limitations

- No automatic cumulative reset/rollover correction or stitching across physical meter replacements.
- No historical half-hour load-profile statistics; those channels expose latest snapshots only.
- No solar generation or total household consumption estimate from grid export alone.
- A retired-meter snapshot is cached in memory until reload; later upstream corrections may require a reload or explicit history import.
- Historical imports are bounded to 3,650 days and 10 minutes per account. Recorder queueing is asynchronous and not transactional across an import.
- Portal errors or omitted channels can make affected entities unavailable; a successful account refresh does not imply every channel was delivered.
- Statistic IDs and device labels include meter/service-point identifiers. Treat database backups and diagnostic screenshots as private.
