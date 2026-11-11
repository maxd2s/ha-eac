# Security, reliability and maintenance review

Reviewed **2026-11-11**, component **0.4.2**, fork `maxd2s/ha-eac`, release `v0.4.2`. Original upstream base: `SantaFox/ha-eac@c783990a811e99b6cd67cd5e9f8498dbaab67c62`.

## Result and scope

Reviewed runtime code, the installed source of pinned `eac-dso-portal==0.2.1`, config/reauth flows, statistics, history imports, the deployment helper, CI and documentation. The working tree included the previously deployed 0.4.1 continuous-grid changes; these were preserved and reviewed too.

No critical/high-severity vulnerability or unrelated telemetry/execution behavior was identified in this scoped review. Several privacy, availability and deployment reliability gaps were fixed below. This is a code review plus synthetic tests and known-advisory scans, not an independent penetration test, audit of EAC's servers, or guarantee of safety.

This revision was tested locally with synthetic portal responses and subsequently deployed to Home Assistant 2026.11.1. Post-restart validation confirmed the entry loaded, a live portal fetch succeeded, all ten checked meter entities were available, recent recorded statistics were preserved, dashboard/energy settings were unchanged, and no integration errors appeared in the checked logs. All 18 deployed files matched the reviewed hashes. No account identifiers or credentials are included in this report.

## New findings fixed in 0.4.2

| Finding | Impact and precondition | Change |
|---|---|---|
| Upstream model parsing could raise unsanitized errors | A malformed authenticated portal response could fail outside normal error handling or expose parser input in an error. No unauthenticated remote exploit demonstrated. | Client boundary sanitizes common parser failures; coordinator handles malformed model errors without response detail. |
| JSON/token validation incomplete | Unexpected server responses could contain non-standard constants, deeply nested containers or invalid authorization-header characters. | Reject NaN/Infinity constants and structures deeper than 32 containers; bound token length and reject whitespace/control/non-ASCII token characters. Existing 2 MiB response cap retained. |
| Paths built from portal identifiers were unrestricted | A malformed service-point identifier could address another route on the same trusted origin. | Full-match allowlist of supported API paths. Does not claim to mitigate a compromised HA administrator or server. |
| Deadlines started after lock acquisition | A poll/import waiting behind another operation could exceed its documented deadline. | Timeout now covers the operation-lock wait; cancellation/timeout regression tests verify cleanup. |
| Net-history pairing retained full lifetime readings | The continuous-grid change accumulated import/export observations until a meter's full history finished. | Pair and enqueue within each 14-day window; retain boundary samples only as needed for matching. |
| History bound only applied when install date was missing | Implausibly old/future dates could trigger excessive requests. | Clamp every import to the last 3,650 days and the present. |
| SMB process success did not prove individual commands succeeded | Interactive smbclient can exit zero after a failed upload, causing false success. | Detect command-level NT_STATUS failures, tolerate only existing-directory creation, clean temporary files, remove the password from the child environment and disable shell tracing. Tested with a fake smbclient. |
| Documentation could cause incorrect interpretation | Fixed delay claims, old polling defaults and adding tariff registers alongside total energy were misleading. | Rewrite installation/data/troubleshooting docs and English/Russian options text; explain per-channel freshness, duplicate-energy risks and solar limitations. |

Additional cleanup removes redundant conversions/exception blocks, compares latest readings in UTC, omits nonfinite cumulative attributes, names net-grid channels clearly, and assigns the fork's code-owner metadata to its maintainer.

## Existing protections retained

- Official HTTPS portal only, normal TLS verification, no redirects or arbitrary configured origins.
- Serial HTTP requests, 30-second request deadline, 2 MiB decoded response retention cap, bounded one-time token refresh and 60-second–24-hour rate-limit cooldown.
- Admin-only history action, no overlapping imports per account, and polling/import serialization.
- HA reauthentication without deleting entities/statistics; credential changes reload the entry.
- Generic normal error messages and identifier-free routine import logs.
- External statistics instead of auto-recorded delayed cumulative sensor totals; reject nonfinite/negative cumulative values and normalize duplicate hours.
- Pinned action revisions, read-only CI permissions; checkout credentials are no longer persisted and jobs have deadlines.

## Validation evidence

| Check | Result | Evidence |
|---|---|---|
| Regression suite, Python 3.14 / HA 2026.10.4 | **88 passed** | `audit/tests-ha-2026.10.4.txt` |
| Actual HA 2026.11.1 core + temporary SQLite, synthetic portal | **Passed**: setup, entities, stored statistics, repeated-import idempotency, reauth/reload, unload/service cleanup | `audit/smoke-ha-2026.11.1.json` |
| Bandit runtime source scan | **0 findings** | `audit/bandit.json` |
| pip-audit historical runtime snapshot | **0 known advisories**, 10 packages | `audit/dependency-audit.json`, `audit/runtime-resolved.txt` |
| pip-audit fresh resolution of manifest dependency | **0 known advisories**, 10 packages | `audit/dependency-audit-fresh.json` |
| Targeted credential-pattern scan | **0 matches** in 115 locally reachable historical blobs and current non-ignored files | `audit/secret-pattern-check.json` |
| Ruff checks/format, shell syntax, whitespace | Passed locally | Commands in `docs/DEVELOPMENT.md` |

The credential-pattern scan covers private-key headers, GitHub tokens, AWS access-key IDs, JWT-shaped tokens and credential-bearing HTTP URLs. It does not detect every possible password or certify an entire repository as secret-free. Test secrets and account fixtures are synthetic. Dependency scans cover the integration's resolved dependency tree, not the entire production HA installation or OS. Bandit's B105 suppression is only for the literal configuration key `password`.

CI repeats tests, source checks, snapshot and fresh dependency audits, and HACS/hassfest validation. A local result does not assert a remote workflow has passed; check the PR's current checks.

## Remaining limitations

1. HA stores credentials in normal config-entry storage; there is no additional vault. Protect administrative access and backups. A custom integration has HA Core privileges.
2. The DSO API is undocumented. HTTP parsing/decompression and JSON decoding allocate memory before some validations; the limits are not a process-wide memory guarantee. No production load/latency benchmark was performed.
3. History imports enqueue data asynchronously. Partial rows remain after cancellation, retries restart from the beginning, and a long account can still exceed 10 minutes. Inactive service points are skipped.
4. Naive timestamps are interpreted as Cyprus time. Ambiguous autumn DST times, cumulative counter resets and replacement-meter stitching remain unsupported. Verify billing calculations against the portal and your contract.
5. Meter-wide freshness follows the newest channel; cumulative export can be older than load-profile data. The integration does not provide real-time solar control or inverter generation.
6. SMB deployment copies files without backup, automatic restart, hash verification or obsolete-file deletion. `.env` is trusted executable shell configuration; use it only from a trusted checkout. Command-error detection is not a transactional upload guarantee.
7. The pinned client's internal transport methods are overridden. Review upstream changes and rerun validation before changing the dependency. Browser sessions, HA integrations outside this repo and external dashboards were outside this audit.

See [SECURITY.md](SECURITY.md) for disclosure guidance and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for reproducible checks and rollback.
