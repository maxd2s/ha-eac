# Today so far card

1. Install integration 0.4.3 or later and reload it. Both half-hour import and
   export channels must be available on the meter configuration.
2. Copy `eac-today-card.js` to `/config/www/eac-today-card.js`.
3. Add `/local/eac-today-card.js?v=0.4.3` as a JavaScript module in dashboard resources.
4. Add a manual card using your **Today net provisional** entity:

```yaml
type: custom:eac-today-card
entity: sensor.your_meter_today_net_provisional
```

No chart libraries or external/CDN requests. Colours use the HA theme. The
lines show cumulative energy in received, paired intervals, at measurement
times rather than fetch times. Hover a point for its time and cumulative kWh.
Internal missing intervals break the lines. Totals exclude those gaps; neither
missing nor not-yet-delivered data is treated as zero. Midnight clearing and
stale-day checks prevent yesterday from being shown as today.

This card is optional and installed separately from the integration. Existing
Energy Dashboard configuration and daily/monthly statistics remain unchanged.
See [the data documentation](../docs/DATA.md) for timestamp assumptions.

## Selected-period balance card

`solar-balance-card.js` is an optional wrapper around Home Assistant's native
Energy grid balance card. Install it as a module resource, then configure:

```yaml
type: custom:solar-balance-card
provisional_entity: sensor.your_meter_today_net_provisional
import_statistic: eac_cyprus:your_service_meter_your_serial_import
export_statistic: eac_cyprus:your_service_meter_your_serial_export
```

Place an `energy-date-selection` card in the same view. When selecting today
alone, the balance uses the provisional sensor and labels its data-through
time. Historical and multi-day selections keep the native register calculation.
Missing statistics display “No data yet”; actual measured zeros remain zeros.
Today's provisional amount is never added to monthly register totals.

This wrapper depends on the native card's `_data` shape and equation elements.
If the data shape is unavailable it shows a waiting message; if the native
markup changes, it displays the original card. It uses the existing Energy
collection plus one cached Recorder request for the seven-day export average,
with no extra DSO requests. The source file includes no account identifiers.
