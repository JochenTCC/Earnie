# Loxone Meter energy for slot Ist (ΔkWh)

**Status:** investigation complete — **Go** for Loxone Meter side channel; **Go** for HA plant energy entities (**2.6.c**)  
**Date:** 2026-09-15 (HA section 2026-09-23)  
**Related:** [`efm-auto-sync-2.4.l.md`](efm-auto-sync-2.4.l.md), backlog **2.6.c** (HA plant), **2.+1** flex counters (Loxone done)

## Verdict

| Capability | Result | Notes |
| --- | --- | --- |
| Meter energy states in LoxAPP3 | **Go** | Real dump (`tests/fixtures/loxapp3_greenfield.json`): uni Meter has `states.total`; bidirectional Grid has `total` + `totalNeg`. Formats `%.1fkWh`. |
| Same control as power binding | **Go** | EFM already binds plant power to Meter **name** (`/jdev/sps/io/{name}` → `actual` kW). Energy is another state of that control — no second HITL field. |
| Live read path | **Go (HTTP `/all`)** | Same pattern as AlarmClock `SpecialState10`: `GET /jdev/sps/io/{Meter.name}/all`, parse LL entries with `name` `total` / `totalNeg`. Official Structure File lists these as Meter states; WebSocket is the App path, Earnie stays on HTTP like existing power/AlarmClock reads. |
| EHAL wire change | **No** | Keep telemetry power-only (2.4.j). Interval energy for Ist is a Loxone-adapter + sampler overlay. |
| Grid sign | **Go** | `total` = consumption (Bezug); `totalNeg` = delivery (Einspeisung). Net slot energy = Δtotal − ΔtotalNeg → avg `grid_kw` with EHAL sign (+ import). |
| Reset / wrap | **Fallback** | Negative channel Δ → reject counter for that channel, keep sample mean. |

## IO recipe

1. Resolve Meter name from plant power binding (`sens_pv_production_active` / `sens_grid_power_active`) or `plant.loxone_meter_energy`.
2. `GET /jdev/sps/io/{name}/all` → LL object.
3. Walk LL values; for dict items with `name` ∈ {`total`, `totalNeg`} **or HTTP Meter abbreviations** `Mr` (uni total), `Mrc`/`Mrd` (bipolar consumption/delivery) parse `value` (strip kWh via existing Loxone numeric parser). Power-only Merker (e.g. `Earnie_*`) are not enough — set `plant.loxone_meter_energy` to the real Meter control names when EHAL power bindings point at Merker.
4. At QH open + close: store readings; on `finalize_closed_interval` set `*_energy_kwh` from ΔE and `*_kw = ΔE / 0.25` when usable.
5. Plant channels without usable ΔE, battery, house, baseload, Merker-only flex, and shared-meter primaries (`subtract_consumer_ids`) stay on sample means. Tag `ist_power_source` (`flex` is a per-consumer-id map: `counter` | `mean`).

## Flex consumers (2.+1)

1. Resolve Meter name from `consumer.loxone_meter_energy` or power binding (`flex.{slug}.sens_power_act` / EVCS / `loxone_inputs.power_name`).
2. Skip counter overlay when `loxone_inputs.subtract_consumer_ids` is set (composite meter; live power already peels subtracted loads).
3. At QH open + close: anchor flex readings under `energy_anchors.open.flex`; on `finalize_closed_interval` set `flex_kw[id] = ΔE / 0.25` when usable.
4. Greenfield / Loxone-Import (`merge_efm`) writes `loxone_meter_energy` when binding `flex.*.sens_power_act` to a Meter.

## Out of scope

- OpenEMS energy entities (no side channel yet).
- Extending EHAL telemetry schema with cumulative kWh.
- Battery on counters; HA flex energy entities; shared-meter ΔE peel beyond sample mean.

## HA plant energy entities (2.6.c)

Separate optional maps in flat `ehal.ha.entities` (not on the power entity):

| Field | Role |
| --- | --- |
| `sens_pv_energy` | PV cumulative kWh (`total_increasing`) → channel `pv.total` |
| `sens_grid_energy_import` | Grid import kWh → `grid.total` |
| `sens_grid_energy_export` | Grid export kWh → `grid.total_neg` |

Reader: `integrations/ha_meter_energy.py`. Same sampler anchors / `overlay_counter_on_closed` / `*_kw = ΔE / 0.25` as Loxone. Mock bench: `house_sim` advances these counters via ∫P·Δt.
