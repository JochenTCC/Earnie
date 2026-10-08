---
name: ehal-live-lesen
description: >-
  When a new EHAL value (sens_*/get_*/flex.*.sens_* read field) is born, add it
  immediately to the Live-Lesen check path so EHAL-Com does not show Kein Mapping
  for a mapped field. Use when adding or renaming EHAL fields, Pattern B
  bindings, role templates, Loxone VO telemetry, HA entity maps, house_config
  ehal_bindings constants, marker_resolve helpers, THERMAL_*_LIVE_READ_FIELDS,
  PLANT_LIVE_READ_FIELDS, EV/FILTER live-read tuples, or collect_read_checks /
  expected_live_read_fields.
---

# EHAL Live-Lesen — New Field Checklist

**Rule:** whenever a new EHAL **read** value is born, wire Live-Lesen in the **same change**. Mapping UI / recipe / VO alone is not enough — otherwise EHAL-Com shows **Kein Mapping** with an empty Mapping column.

Write fields (`set_*` / flex enable/setpoint) go to Live-Schreiben, not this checklist.

## Same-change checklist

Copy and tick:

```
New EHAL read field:
- [ ] marker_resolve helper (settings/ehal_marker_resolve.py) if Loxone Merker pull
- [ ] Pattern B key on plant or consumer (house_config/ehal_bindings.py constants / fields_for_*)
- [ ] expected row list (integrations/ehal_debug_mapping.py):
      PLANT_LIVE_READ_FIELDS | EV_* | FILTER_* | THERMAL_* | THERMAL_ANNUAL_* |
      or expected_live_read_fields() branch for the entity kind
- [ ] Loxone collect_read_checks (integrations/loxone_connectivity.py):
      _append_*_read_checks + _consumer_has_live_read_marker (+ detector if new kind)
- [ ] HA Live path if backend reads it (aggregate / adapter / ha_pattern_b_live_mapping)
- [ ] Test: collect_read_checks (or HA telemetry rows) includes qualified ID → Merker/entity
- [ ] Docs: docs/ui/ehal-com.md §C + docs/referenz/loxone-signals.md if operator-visible
```

## Where rows come from

| Layer | Loxone | HA / OpenEMS |
|-------|--------|--------------|
| Expected fields (table pad) | `expected_live_read_fields(network_backend=False)` | same / `network_backend=True` for OpenEMS plant set |
| Actual Mapping + Wert | `collect_read_checks()` → `build_read_rows` | adapter `read_telemetry` + mapping dict → `build_telemetry_rows` |

If a field is only in `expected_live_read_fields` but missing from `collect_read_checks` (Loxone), status is always **Kein Mapping**.

## Label convention (Live-Lesen = Push-Inbox)

Use `live_read_consumer_field(consumer, field_key)` → `qualified_consumer_id` (same as Push-Inbox `EHAL-ID`).

- Plant: bare field (`sens_temperature_outside`)
- Battery: `ess.{id}.{kind}`
- Consumer flex power: `consumer.{slug}.sens_power_act` (or `heatpump.*` / `pool.*` by type)
- Consumer domain: e.g. `heatpump.waermepumpe.sens_temperature_heat_storage`, `pool.swimspa.sens_temperature_water`
- EV: `evcs.{id}.*` / `ev.{id}.*` by field kind
- Live-Schreiben still uses `{consumer_id}:{field}` (out of scope for this checklist)

## Reference pattern

Heat storage (`thermal_annual`): `THERMAL_ANNUAL_LIVE_READ_FIELDS` + `_append_thermal_annual_read_checks` + `_is_thermal_annual_consumer` — mirror Pool `THERMAL_LIVE_READ_FIELDS` / `_append_thermal_read_checks`.
