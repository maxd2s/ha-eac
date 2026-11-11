# Changelog

## 0.4.2 — 2026-11-11

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
