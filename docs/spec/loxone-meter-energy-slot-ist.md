# Loxone Meter energy for slot Ist (ΔkWh)

**Status:** investigation complete — **Go** for Loxone-only side channel  
**Date:** 2026-09-15  
**Related:** [`efm-auto-sync-2.4.l.md`](efm-auto-sync-2.4.l.md), backlog **2.+1** energy counters / HA later under Improvements for HA-binding

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
5. Battery / flex / house / baseload stay on sample means. Tag `ist_power_source`.

## Out of scope

- HA / OpenEMS energy entities (later backlog under Improvements for HA-binding).
- Extending EHAL telemetry schema with cumulative kWh.
- Battery / flex on counters.
