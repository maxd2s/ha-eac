# Security, compatibility and performance review

Review date: 2026-11-11. Upstream base: `SantaFox/ha-eac@c783990a811e99b6cd67cd5e9f8498dbaab67c62`. Fork: `maxd2s/ha-eac`, branch `harden-modernize-eac`, component version 0.4.0.

## Scope and result

Reviewed the integration, the Python source of its pinned `eac-dso-portal==0.2.1` dependency, its deployment helper, and CI configuration. The PyPI wheel SHA-256 was `0fcdbc2bf3581ddce54f0adaa579a85318cb12b536ed5d57e02127d354c8c0f8` and matched PyPI metadata. No obvious unrelated network endpoints, telemetry, dynamic code execution, or malicious persistence were found in the reviewed runtime code. This is a scoped code review, not an independent penetration test or a guarantee of safety.

No production HA files were changed, no live DSO credentials were used, and no portal history was imported during the review. Installation remains a separate approval step.

## Findings and changes

| Finding | Preconditions / impact | Resolution |
|---|---|---|
| Configurable portal origin accepted HTTP and arbitrary hosts | An administrator could accidentally send the portal password to the wrong server. This is not an unauthenticated remote exploit. | Removed the URL field; adapter rejects every origin except the official HTTPS portal, including legacy stored custom origins. |
| Login followed redirects | A malicious or compromised endpoint could redirect a credential-bearing POST. | All redirects refused; certificate verification remains enabled. |
| Error response bodies included in exceptions | Server-provided private/account data could reach logs. | Generic status-only exceptions; no error bodies read; unexpected config-flow errors do not log a traceback or payload. Routine import logs no longer include account/meter identifiers. |
| Requests relied on session defaults and unbounded JSON reads | Slow/large responses could retain resources. | 30 s total / 10 s connect / 20 s read deadline; 2 MiB decoded response limit; 180 s polling deadline. |
| Concurrent login/expired-token refresh | Parallel callers could duplicate logins and race session tokens. | Serial transport with an async lock; only one 401 refresh/retry per request. HTTP 429 cooldown uses Retry-After, bounded to 60 s–24 h. |
| Invalid credentials surfaced as transient polling failures | No normal credential recovery flow. | ConfigEntryAuthFailed and tested reauthentication preserving entity/statistic identity. Credential changes reload via the update listener; unchanged credentials also restart the entry. |
| Deep-history import retained whole date ranges and allowed overlapping calls | Large accounts consume more memory and duplicate portal requests. | Sequential 14-day batches, boundary deduplication, a per-account operation lock, duplicate-import rejection, admin-only action, and a 10-minute import deadline. Partial failures no longer produce a success notification. |
| Old statistics/device/lifecycle API use | HA compatibility warnings and future breakage. | mean_type/unit_class metadata, via_device_id, ConfigEntry-aware coordinator and update-listener reload handling. |
| Unknown channel fallback referenced missing `_label` | New channel types could crash setup. | Use the shared channel-label fallback. |
| Reactive/apparent energy labeled with power units; delayed power advertised live statistics | Incorrect units and time attribution. | Preserve kVAh/kvarh; no auto-recorded measurement statistics on delayed power snapshots. |
| Offset-free timestamps treated as UTC | Daily samples shifted by Cyprus UTC offset. | Interpret naive timestamps as Asia/Nicosia; preserve explicit offsets; tests cover winter/summer. This assumption follows upstream source comments and still requires comparison with a live export. |
| Duplicate/unordered/NaN/infinite readings accepted | Recorder errors or polluted statistics. | Sort, collapse observations to one per UTC hour, and reject nonfinite/negative cumulative values. |
| SMB helper put password in process arguments and masked failures | Local process listings exposed the password; upload failure could be reported as success. | Owner-only temporary authentication file, cleanup trap, newline rejection, and retained exit status. The optional `.env` remains a trusted local shell file and must never be loaded from an untrusted source. |
| Mutable GitHub Action references and no test/security workflow | Unreviewed action changes and regressions could be missed. | Immutable action revisions, contents-read permission, regression tests, exact-version smoke check, source/dependency scanners and formatting checks. |

## Validation evidence

- **62 tests pass** on HA 2026.10.4 / Python 3.14 using pytest-homeassistant-custom-component 0.13.375. Tests cover hostile origins/redirects, bounded bodies/retries, credential redaction, rate limiting, simultaneous requests, admin authorization, duplicate imports, lock cleanup, reauthentication, units, timezone handling, and normal entity lifecycle.
- **HA 2026.11.1 smoke check passes** against the real core in a disposable configuration and SQLite database: config flow, sensor setup, actual statistics rows, repeated-import idempotency, credential update/reload, unload and service removal. The portal is synthetic; no production connection is made. The old pytest helper cannot run on 2026.11.1 because its internal logger imports changed; this is why the exact-version test is separate.
- **Bandit: zero reported findings** in the final integration source. One documented B105 suppression covers the literal config key `password`, not a credential.
- **pip-audit: no known vulnerabilities** for the ten resolved runtime dependency versions listed in `audit/runtime-resolved.txt`, as queried on the review date. This does not audit all packages in the user's HA installation, the operating system, or future dependency resolutions.
- Ruff code/import checks and formatting, shell syntax, and whitespace checks pass. Raw machine-readable scanner reports and concise test evidence are in `audit/`.

## Performance interpretation

The improvements bound work rather than claim an unmeasured speedup. A synthetic import test verifies that each request covers at most 14 days, each response is imported before the next batch, and duplicate boundary readings are not counted twice. Previously the library accumulated all chunks before returning them to the importer. Request count is not reduced: it remains sequential and respectful of portal limits. Six-hour polling stays the default.

The response byte cap limits what this adapter retains; it is not a complete defense against every HTTP decompression or parser resource attack. Recorder queueing and Home Assistant itself also consume memory. There is no real-account latency, CPU or memory benchmark yet.

## Remaining limits before relying on the data

1. Validate live login, channel mapping, data delay and at least one bill/export comparison after installation. The portal API is undocumented and may change.
2. Validate naive timestamp semantics against an actual portal export, especially around DST. Ambiguous offset-free timestamps cannot distinguish the repeated autumn hour. Daily cumulative counters do not provide true hourly consumption; interval history remains outside this fork's scope.
3. Cumulative reset/rollover correction and stitching totals across replacement meters are not implemented. Distinct meters remain separate devices/statistic series.
4. A very long import can exceed the 10-minute deadline. Already queued rows remain; rerunning is idempotent but currently starts from the original date rather than a persisted checkpoint. Database enqueue success is not a transactional guarantee that every row was durably committed.
5. HA stores integration credentials in its normal config-entry storage. Protect HA access and backups; this fork does not provide an additional secret vault. Administrator/system-triggered imports are allowed, non-admin user-triggered imports are denied.
6. The client adapter deliberately overrides transport internals of pinned library 0.2.1. Review and rerun tests before changing that dependency. Updating from upstream would overwrite fork-specific fixes.

## Reproduce

See README test commands and `.github/workflows/validate.yml`. `scripts/smoke_ha.py` uses temporary storage and a synthetic portal. Review the entire fork diff before installing; keep upstream LICENSE attribution intact.
