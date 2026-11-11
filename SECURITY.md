# Security policy

## Scope

This is an unofficial Home Assistant custom integration. It runs with the privileges of Home Assistant Core, not in a sandbox. Review the code and its pinned dependencies before installation. The maintained code is on `main`; published versions are tagged; see the version in `manifest.json` and the [review](SECURITY_REVIEW.md). No independent certification or guarantee is claimed.

## Network and credentials

- The portal origin is fixed to `https://meterreading-dso.eac.com.cy` with normal TLS verification. HTTP, custom origins and redirects are refused.
- Only the implemented portal API routes are permitted by the adapter.
- Passwords are sent only for login. The bearer token stays in memory; it is not deliberately persisted by this integration.
- HA stores the email/password in standard config-entry storage. This integration does not encrypt that storage separately. Protect administrative access, the configuration directory and backups.
- Generic runtime errors omit response bodies and parser error details. Avoid HTTP debug tracing, which is outside this integration's logging controls.
- Sensor labels, service responses, statistics and HA backups contain account/meter information even though normal logs omit it.

## Resource controls

Responses have a 2 MiB decoded-body retention limit; requests have a 30-second deadline. Each account serializes requests and reauthenticates at most once after a 401. HTTP 429 establishes a 60-second to 24-hour local cooldown. TLS/HTTP parsing and decompression also allocate memory, so this is not an absolute process memory cap.

Polling has a 180-second deadline including lock wait. The admin-only history action has a 600-second deadline per account, a 3,650-day history bound and 14-day processing windows. Multiple accounts are processed sequentially. System-triggered HA automations can run admin services; protect access to automation configuration too.

## Reporting vulnerabilities

Use GitHub's **Report a vulnerability** option on the fork if private reporting is enabled. Otherwise contact the repository owner through an available private channel before sharing exploit details. Do not post credentials, tokens, live account identifiers, raw portal responses, configuration archives or private energy history in a public issue.

Include the affected commit/version, HA version, impact, and a reproduction using synthetic inputs. Ordinary bugs with fully redacted examples can use the public issue tracker.

## Development and deployment

Keep `.env`, HA tokens, deployment authentication files and live data outside Git. `.env` used by the optional SMB helper is executable shell configuration: only source a file you created and trust. Never run it from an untrusted checkout. CI uses synthetic fixtures, read-only repository permissions and pinned action revisions; no production credentials are needed.

A dependency scanner reports known advisories, not all vulnerabilities. Recheck dependencies and the transport overrides whenever upgrading `eac-dso-portal` or HA.
