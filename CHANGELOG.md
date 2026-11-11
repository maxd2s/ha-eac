# Changelog

## 0.5.1

- Add a responsive, dependency-free Solar & grid dashboard combining balances, period charts, surplus-export patterns, demand, tariff and meter details.
- Discover register statistic identifiers through the existing permission-scoped profile API; no account-specific dashboard configuration is required.
- Add shared day/week/month/year controls, line/bar charts, explicit missing-data states, bounded frontend caching and stale-response protection.

## 0.5.0

- Add per-account, per-meter interval caches and authenticated, entity-permission-scoped profile access. Default retention is 30 calendar days; 7–90 days are configurable.
- Add typical overnight demand, highest half-hour demand, profile coverage and DSO-reported tariff sensors. Overnight hours are configurable; tariff codes are discovered and cached without storing report contents.
- Add an account-independent insights dashboard with automatic meter discovery, historical/day charts and average surplus export by half-hour. Import-only accounts and unavailable channels are handled without inventing zero readings.
- Keep cumulative daily/monthly register statistics separate and unchanged.


## 0.4.3

- Add current-day provisional import/export/net sensors from matching half-hour readings, with coverage and gap diagnostics. Reuse existing requests; keep register statistics unchanged.
- Add an optional dependency-free Today so far dashboard card with cumulative import/export lines, totals and missing-data indicators.
- Bound chart payloads to one Cyprus day and exclude them from Recorder history.


## 0.4.2 — 2026-11-11 (initial public beta)

- Restrict adapter requests to supported portal routes; reject invalid bearer-token header characters, deeply nested JSON and non-standard JSON constants.
- Sanitize failures from the upstream response parser before they can reach HA error reporting.
- Include operation-lock waits in polling/history deadlines.
- Process full-history import/export pairs per 14-day window instead of retaining a whole meter lifetime; cap all import dates to the last 3,650 days and the present.
- Normalize latest-reading comparisons to UTC; omit nonfinite cumulative sensor attributes and name net import/export channels clearly.
- Refresh security tests, dependency auditing and documentation. Correct freshness explanations and prevent double-counting in Energy Dashboard instructions.

## 0.4.1 — 2026-11-11

- Add continuous physical-meter import/export/net statistics across supported portal channel changes.
- Attribute midnight grid-register readings to the preceding day; preserve original per-channel series for compatibility.
- Set default polling to 30 minutes.

## 0.4.0 — 2026-11-11

- Constrain portal origin, redirects, response sizes, retry count and request timeouts.
- Add rate-limit cooldown, credential reauthentication, admin-only bounded history import and lifecycle fixes.
- Modernize Recorder metadata for HA 2026.10/11, correct channel units, and add security/regression CI.

Earlier versions originate in SantaFox/ha-eac; see Git history and LICENSE.
