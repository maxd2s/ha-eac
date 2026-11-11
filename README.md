# EAC Cyprus for Home Assistant

Read your Cyprus EAC DSO meter account in Home Assistant, with delayed import/export history for the Energy Dashboard. This is an unofficial custom integration, not an EAC product.

This fork of [SantaFox/ha-eac](https://github.com/SantaFox/ha-eac) adds constrained HTTPS transport, reauthentication, bounded history imports, and continuous statistics across channel changes on the same meter. It uses the pinned [`eac-dso-portal`](https://github.com/SantaFox/eac-dso-portal) parser. Upstream attribution and the MIT license are retained.

Version **0.5.0** adds configurable interval insights and DSO-reported tariff codes to the public beta. See the [changelog](CHANGELOG.md) and documented data limitations before relying on it for billing comparisons.

## Requirements

- Home Assistant Core **2026.10.4 or newer**; see [validation evidence](SECURITY_REVIEW.md) for versions actually tested.
- An account at <https://meterreading-dso.eac.com.cy> with accessible meter data. This is the DSO portal account, which may differ from your EAC billing login.
- Outbound HTTPS access to that portal and Home Assistant's Recorder integration.
- No meter reader hardware, local MQTT broker, browser automation, or HACS dependency is required.

## Installation

### HACS

Add `https://github.com/maxd2s/ha-eac` as a custom repository of type **Integration**, install **EAC Distribution Web Portal**, and restart Home Assistant. HACS installs the repository's published/default revision: changes on an unmerged development branch are not automatically included.

### Manual or development branch

1. Download or check out the desired release/branch of this repository.
2. Copy only `custom_components/eac_cyprus/` to `<HA config>/custom_components/eac_cyprus/`.
3. Restart Home Assistant.
4. Open **Settings → Devices & services → Add integration → EAC Distribution Web Portal**.
5. Enter your DSO email and password in Home Assistant. Do not put them in source code, dashboard YAML, or GitHub issues.

Back up Home Assistant before upgrading. See [development and deployment](docs/DEVELOPMENT.md) for verification and rollback.

## What appears in Home Assistant

Each service point is a parent device; each physical meter is a child device. Meters and channels discovered in subsequent polls are added automatically. Retired meters retain statistics and, where available, their final snapshot.

| Sensor | Meaning |
|---|---|
| Grid energy imported / Energy total (24h) | Cumulative electricity drawn from the grid, kWh |
| Grid energy exported / Energy exported | Cumulative electricity sent to the grid, kWh |
| Energy peak / off-peak tariff | Cumulative tariff registers; these are portions of import, not extra consumption |
| Profile coverage / typical overnight demand / highest half-hour demand | Configurable cached interval insights; no inferred zero values |
| Tariff code | Identifier from the DSO report, with retrieval time; no hardcoded prices |
| Today import/export/net provisional | Sum of matching half-hour readings for today, with coverage and gaps; optional [dashboard card](dashboard/README.md) |
| Power import/export (30-min average) | Latest available interval energy divided by half an hour, in kW; not instantaneous power |
| Data measured at | Newest measurement timestamp across the meter's channels |
| Data received at | Snapshot fetch time, including polls that return unchanged readings |
| Data lag | Age of the newest measurement at fetch time; updated when polling runs |
| Data stale | Whether that newest measurement exceeds your configured age threshold |

Reactive/apparent energy and unrecognised channels are disabled by default. Available channels depend on the meter and portal configuration.

**Export is not solar generation.** Solar used directly in your home does not cross the grid meter. Total solar generation and total household consumption require inverter or additional meter data.

## How delayed data works

The DSO publishes channels on different schedules. Half-hour load profiles may be several hours behind; cumulative registers may only update daily or later. There is no guaranteed universal 2–3 day delay. Polling more frequently cannot make the DSO publish sooner.

The meter-wide freshness sensors describe the **newest channel**, so they do not establish the freshness of every export/import register. Inspect each channel's `measured_at` attribute for its own measurement timestamp. A recent HA `last_updated` timestamp only says when HA received or changed the entity state.

Cumulative sensors intentionally have **no `state_class`**. Historical energy is stored as external statistics at measurement times, avoiding the mistake of recording old consumption as usage at the time HA fetched it.

## Configure the Energy Dashboard

Under **Settings → Dashboards → Energy**, select these external statistics:

- **Grid consumption:** `<meter serial> Grid import`.
- **Return to grid:** `<meter serial> Grid export`.

For custom charts, `<meter serial> Net grid energy` is import minus export: positive changes mean net imports, negative changes mean net exports.

**Do not add peak/off-peak registers alongside total import**, and do not add both an original per-channel series and its continuous grid equivalent. That counts the same energy twice. Net energy is for balance charts, not the Energy Dashboard's consumption input.

The continuous statistic IDs are:

```text
eac_cyprus:<service-point>_meter_<serial>_import
eac_cyprus:<service-point>_meter_<serial>_export
eac_cyprus:<service-point>_meter_<serial>_net
```

The serial is normalized for HA statistic IDs. These are statistics, not sensor entity IDs. Find them in **Developer Tools → Statistics** or a Statistics graph card. If a grid series is unavailable, inspect the channel mapping in [data semantics](docs/DATA.md); never guess that an unknown register means total import.

## Import older history

Regular polling retrieves a rolling window. For older data, an administrator can run **Developer Tools → Actions → `eac_cyprus.import_full_history`** once.

The action processes active service points and their available active/retired meters. It imports cumulative kWh channels in 14-day windows, bounded to the last **3,650 days** and a **10-minute deadline per account**, including lock wait. It does not import historical half-hour power profiles.

A summary means rows were queued for Recorder, not that a database transaction was fully committed. If interrupted, imported rows remain. Rerunning replaces matching statistic rows rather than duplicating them, but starts again from the beginning; there is no saved resume cursor.

## Options

Open the integration's **Configure** option:

| Setting | Default | Allowed values |
|---|---:|---|
| Poll interval | 30 minutes | 30 min, 1 h, 3 h, 6 h, 12 h, 24 h |
| Rolling history | 14 days | 1–60 days |
| Stale threshold | 4 days | 1–30 days |

Longer polling intervals reduce portal traffic. Requests are sequential, reuse the authenticated session, and respect rate-limit cooldowns. The 4-day stale threshold is conservative, not a delivery-time guarantee.

## Troubleshooting

- **Authentication required:** use HA's reauthentication prompt. Updating the password preserves your entry and statistic IDs.
- **Cannot connect / temporarily unavailable:** check portal availability and network access; rate limits pause requests. Do not repeatedly retry or run history imports.
- **Export unchanged today:** inspect the export sensor's `measured_at`; daily cumulative values may lag behind the load-profile channel.
- **Daily spike after missing days:** the next register difference can cover the whole gap. The integration does not invent missing daily values.
- **Unexpected totals after a meter reset:** reset/rollover compensation is not implemented. Compare the raw registers and see [data limitations](docs/DATA.md).
- **No history after installation:** wait for a successful refresh, then run the history action and allow Recorder to finish processing.

## Security and contributing

Credentials are stored in HA's standard config-entry storage. Treat HA access and backups as sensitive. The runtime contacts only the official HTTPS DSO origin; redirects and custom origins are rejected. This is a read-only portal integration and does not control the meter or change your electricity contract.

- [Security policy](SECURITY.md): boundaries, reporting and secret handling.
- [Security review](SECURITY_REVIEW.md): findings, test evidence and remaining risks.
- [Data semantics](docs/DATA.md): channels, dates, net energy and limitations.
- [Development](docs/DEVELOPMENT.md): reproducible tests, CI and deployment.
- [Changelog](CHANGELOG.md).

Report fork transport/integration issues here; parser changes may also require coordination with the upstream library. Include versions and a redacted error description, never passwords, JWTs, account details, or raw portal exports.

## License

[MIT](LICENSE).
