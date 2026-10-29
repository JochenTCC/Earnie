# Device detection — grid per-phase push logging (NILM stage 0, dev)

Status: dev only, not public. Data acquisition for device detection (NILM stage 0): the
hub pushes the grid meter's per-phase values, Earnie writes every push with its arrival
time to a daily JSONL file. The optimizer does not read these values.

## Activation

UI mode key `device_detection` in `EARNIE_UI_MODES` (put it into `config/.env`; UI and
daemon both load it), for example:

```text
EARNIE_UI_MODES=sunset2sunset,scenario_explorer,live_environment,device_detection
```

Without the variable, the default mode set never contains the key, so the log is off.
The key has no page of its own. `device_detection` alone keeps the default page
(`sunset2sunset`). Gate: `runtime_store.env_vars.is_device_detection_enabled()`.

The inbox accepts the IDs regardless of the gate (they match the `grid.meter.sens_*`
pattern); only the time-series log is gated.

## EHAL fields

Exchanged as `grid.meter.<kind>` (`ehal/grid_phase_fields.py`, listed in
`ehal.qualified_ids.GRID_KINDS`). Hub conversion in `share/ehal/roles/grid_phases.json`
(role status `dev`), deliberately not in `grid.json`, so `ehal.signal_catalog` does not
offer them in the mapping UI.

| Kind | EHAL unit | Loxone unit | Sign | Huawei SUN2000 register |
|---|---|---|---|---|
| `sens_grid_voltage_l1/_l2/_l3` | V | V | — | 37101 / 37103 / 37105 (gain 10) |
| `sens_grid_current_l1/_l2/_l3` | A | A | as delivered by the meter (not verified) | 37107 / 37109 / 37111 (gain 100) |
| `sens_grid_power_active_l1/_l2/_l3` | W | kW | `+` = import, like `sens_grid_power_active` | 37132 / 37134 / 37136 (`+` = export → invert in Loxone) |
| `sens_grid_power_reactive` | var | kvar | as delivered by the meter (not verified) | 37115 |
| `sens_grid_power_factor` | — | — | as delivered by the meter (not verified) | 37117 (INT16, gain 1000) |

The total `grid.meter.sens_grid_power_active` (register 37113, already a regular
binding) is logged alongside, for the stage 0 check Σ phases ≈ total.

## Log format

`runtime/grid_phase_log/YYYY-MM-DD.jsonl` (UTC date), one line per push:

```json
{"ts":"2026-10-29T08:15:03.412+00:00","id":"grid.meter.sens_grid_voltage_l1","v":231.4}
```

`v` is the value as pushed, in hub units (Loxone: kW / kvar). Convert with
`ehal.field_registry.apply_loxone_read(v, loxone_spec(kind))`. A push that does not parse
is written with `"v": null` and the `"raw"` text. No retention: files stay until removed
by hand (roughly 10–20 MB per day at a 5 s poll). Write errors are logged and never reach
the push listener.

## Shadow: export from the Prod feed

A Shadow client has no live push listener, so it never writes this log, even with
`device_detection` set. The Prod feed recorder keeps every VO push anyway
(`shadow_feed/feed-YYYY-MM-DD.jsonl`, key `loxone:io:<id>`, retention
`shadow_feed_retention_days`, default 14). Convert it into the log format:

```text
python -m scripts.export_grid_phase_log --feed-dir <prod config>/shadow_feed \
    --out-dir <runtime>/grid_phase_log [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--overwrite]
```

Differences to the live log: `ts` has second resolution. Once per cycle, the recorder also
mirrors the whole push inbox into the feed. The export drops a row as such a snapshot when
it repeats the previous raw value of that ID less than half the ID's median push interval
later (`--keep-snapshots` keeps all rows; the dropped count is printed per day). Existing
day files are only replaced with `--overwrite`; today's feed file is still growing, so
re-run with `--overwrite` later.

## Loxone

VO template: `python -m scripts.pilot_vo_template_gen --grid-phases --host <earnie-ip>
--out-dir <dir> [--env-file <config/.env>]` writes `VO_Earnie_Netz_Phasen.xml` (one analog
`Push_grid_meter_<kind>` command per field, repeat 10 s; the own setup runs 5 s). Connect each VI to its VO
command. The VI must already deliver the Loxone units in the table above.

## Open

- Verify signs of current, reactive power and power factor on the own SUN2000.
- Stage 1 reader (resampling to a 10 s grid, EHAL conversion) and retention.
- Public release: move the fields into `grid.json` / mapping catalog, user docs.
