# EAC Cyprus — Home Assistant integration

This fork of [SantaFox/ha-eac](https://github.com/SantaFox/ha-eac) adds security hardening and Home Assistant 2026.10/11 compatibility. See [the security review](SECURITY_REVIEW.md) for scope, evidence, and remaining limitations. No live account validation has been performed for this revision.

Home Assistant integration for the EAC (Electricity Authority of Cyprus) Distribution Web Portal at `meterreading-dso.eac.com.cy`.

It pulls your electricity-meter readings into Home Assistant — the full history into the Energy Dashboard, plus live "latest known value" sensors and per-meter diagnostics. Built on the [`eac-dso-portal`](https://github.com/SantaFox/eac-dso-portal) Python client (also on [PyPI](https://pypi.org/project/eac-dso-portal/)).

## What you get

**One device per meter.** Each physical meter on your account is its own HA device, named by its serial and parented to the service point (the permanent supply contract at your address). When the DSO swaps the meter, the old device stays — with its final reading and full history — and the new meter appears automatically.

Per meter you get:

- **Per-channel "last value" sensors** — the most recent reading Home Assistant has for each channel:
  - `Energy total (24h)`, `Energy peak/off-peak tariff`, `Energy exported` — cumulative kWh (glance value; the *history* lives in statistics, see below).
  - `Power import/export (30-min average)` — the 30-minute load profile re-projected to average power (kW).
  - Reactive / apparent energy channels — created but disabled by default.
- **Diagnostics** — `Data measured at` (when the reading was taken), `Data received at` (when HA fetched it), `Data lag` (the age of the newest reading), and a `Data stale` problem sensor.

## "Now" vs "history": two separate things

The portal publishes with a **2–3 day lag**. Home Assistant's live sensor state is, by design, always "the value right now" — you can't backdate it — so a cumulative sensor showing a 3-day-old reading as "now" is a poor fit, and letting Home Assistant auto-compute long-term statistics off it would misdate your consumption. (This is exactly why Home Assistant's own utility integrations, like `opower`, publish delayed data as statistics rather than as a live sensor.)

So the integration splits the picture in two:

- **Sensors answer "what does HA know right now"** — the latest reading and the diagnostics above. Good for glance cards and automations. Cumulative kWh sensors deliberately carry **no `state_class`**, so Home Assistant does not auto-record misdated statistics for them.
- **External statistics answer "what actually happened, and when"** — the correct-dated long-term history, written straight to the statistics engine with the real reading dates. This is what the **Energy Dashboard** uses.

### Where to find the history

The statistics are named from the meter serial, e.g. `1281890 Energy total (24h)`. They are not entities (that is inherent to delayed-data statistics), so you view them via:

- **Energy Dashboard** → *Add consumption* → pick `<serial> Energy total (24h)` (and the two tariff series for a two-tariff plan, or `<serial> Energy exported` under Grid → Return to grid if you export energy).
- A **Statistics graph** card on any dashboard → pick the same series.
- **Developer Tools → Statistics** → lists them all.

## Load the full history

Regular polling only keeps a rolling window. To backfill everything the portal has — the current meter back to its install date, **and** any retired meters (e.g. an old meter's years of readings) — run the action once:

**Developer Tools → Actions → `eac_cyprus.import_full_history` → Run.**

It returns a per-channel summary and posts a notification after enqueueing the results. Administrator access is required. Imports use sequential 14-day windows, with one import at a time per account and a 10-minute deadline. An interrupted import reports an error; existing rows remain and rerunning is idempotent. You are prompted to run it once on first setup.

## Configuration

Settings → Devices & Services → the EAC tile → three-dot menu → **Configure**:

- **Polling interval** — 30 min … 24 h (default 6 h). The portal updates daily, so more often rarely helps.
- **History window (days)** — how far back each poll fetches (default 14). This is the rolling window; deep history comes from the import action above.
- **Data-stale threshold (days)** — how long without a fresh reading before `Data stale` flags (default 4, i.e. a bit beyond the normal 2–3 day lag).

## Install

### HACS

Add this repository as a **Custom repository** (HACS → three-dot menu → Custom repositories → `https://github.com/maxd2s/ha-eac`, category *Integration*), then install "EAC Distribution Web Portal" and restart Home Assistant.

### Manual

1. Copy `custom_components/eac_cyprus/` into your HA config's `custom_components/` folder (e.g. via the Samba add-on at `\\<HA-IP>\config\custom_components\`).
2. Restart Home Assistant.
3. Settings → Devices & Services → Add Integration → search **EAC Distribution Web Portal**.
4. Enter the email and password you use at `meterreading-dso.eac.com.cy`.

## Design notes

**Device = meter.** A service point (12-digit `spId`) is the permanent supply contract at an address; meters are the hardware and get swapped over time. Modelling each meter as its own device (parented to the service point via `via_device`) means a retired meter keeps its own history and final reading instead of vanishing or getting tangled with the replacement.

**Meter swaps.** The new meter's device and channels appear on the next refresh; the retired meter's sensors go unavailable but its statistics stay frozen and intact. Each meter's statistics are correct on their own. What is **not** yet stitched automatically is a single continuous lifetime total *spanning* a swap — the old and new meters expose different channels — that's on the roadmap.

**No `state_class` on cumulative sensors.** With a 2–3 day publish lag, Home Assistant's auto-recorder would compute statistics off the "latest known value" and misdate consumption. Instead there is no `state_class` (nothing is auto-computed) and the real long-term series is written as external statistics with correct dates — the same approach Home Assistant core uses for delayed utility data.

## Development

Depends on the [`eac-dso-portal`](https://github.com/SantaFox/eac-dso-portal) library — bug reports about HTTP/parsing belong there; HA-side issues (sensors, config flow, devices, statistics) belong here. `scripts/deploy_smb.sh` pushes the integration to a Samba share for local testing (connection details in a gitignored `.env`).

## License

MIT


## Fork transport and lifecycle changes

- Credentials go only to `https://meterreading-dso.eac.com.cy`; custom origins and redirects are refused. TLS certificate verification stays enabled.
- Each request has a 30-second total deadline and a 2 MiB decoded response limit. A rejected token is refreshed at most once per request; concurrent requests share one login.
- HTTP 429 creates a local cooldown (at least 60 seconds, `Retry-After` respected up to 24 hours). No busy retry loop or parallel portal requests.
- Error responses and credentials are excluded from exception messages. Portal/account identifiers were removed from normal import logs.
- Invalid credentials open HA's reauthentication flow. Credential changes reload the entry; polling changes update the coordinator without a full HA restart.
- Statistics declare `mean_type` and `unit_class`. Unsorted/duplicate-hour readings are normalized; nonfinite or negative cumulative readings are rejected.
- Offset-free timestamps are interpreted as Cyprus civil time, including DST; explicit offsets are preserved. This follows the upstream code's description and needs verification against a live portal export before relying on time-of-day totals.
- Delayed power snapshots do not advertise live measurement statistics. Unknown channels no longer crash setup; apparent/reactive energy keeps energy units.

## Tests

Python 3.14, isolated environment:

```sh
python -m pip install -r requirements-test.txt
python scripts/run_tests.py -q
```

The current HA test-helper release pins HA 2026.10.4. A separate smoke check uses the actual HA 2026.11.1 core, a disposable configuration and SQLite database, and a synthetic portal client:

```sh
python -m pip install homeassistant==2026.11.1
python scripts/smoke_ha.py
```

The smoke check verifies config flow, entities, actual statistic storage, repeat-import idempotency, reauthentication/reload, and service cleanup. It never connects to a production Home Assistant or uses real DSO credentials. GitHub Actions runs both paths with read-only repository permissions and pinned action revisions.
