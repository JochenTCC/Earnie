# Loxone Meter energy for slot Ist (ΔkWh)

**Status:** **Go** — live path is VO push into the inbox (**2.7.q Q6**, 2026-10-09). HA plant energy entities remain (**2.6.c**).  
**Related:** [`efm-auto-sync-2.4.l.md`](efm-auto-sync-2.4.l.md), backlog **2.7.q** Q6, **2.6.c** (HA plant)

## Verdict

| Capability | Result | Notes |
| --- | --- | --- |
| Meter energy states in LoxAPP3 | **Go** | Real dump (`tests/fixtures/loxapp3_greenfield.json`): uni Meter has `states.total`; bidirectional Grid has `total` + `totalNeg`. Formats `%.1fkWh`. |
| Same control as power binding | **Go (config)** | EFM still binds plant/consumer **power** to the Meter name. Energy is activated as separate EHAL push fields (no Merker `/all`). |
| Live read path | **Go (VO push)** | Loxone pushes cumulative kWh via Virtual Outputs to `/ehal/loxone/telemetry/<EHAL-ID>/<v>`. The QH sampler reads fresh inbox counters. HTTP `/jdev/sps/io/{Meter}/all` and profile key `loxone_meter_energy` are **retired**. |
| EHAL wire | **Push fields** | Plant reuses HA kinds; consumers add `sens_energy_total` only (mono — consumers cannot export); batteries add `sens_ess_energy_charge` / `sens_ess_energy_discharge` (bipolar; Pilot / `VO_Earnie_Battery`). |
| Grid sign | **Go** | Import = consumption; export = delivery. Net slot energy = Δimport − Δexport → avg `grid_kw` with EHAL sign (+ import). |
| Reset / wrap | **Fallback** | Negative channel Δ → reject counter for that channel, keep sample mean. |
| Stale / never received | **Fallback** | Counter older than 3 × VO repeat (or never pushed) → no overlay for that channel; sample-mean stays. **Never zero-assumed.** |

## Push IO recipe (Q6)

1. Activate energy fields on `plant.ehal_bindings` / `consumer.ehal_bindings` / `batteries[].ehal_bindings` (Merker name may be empty — push-only). Plant: `sens_pv_energy`, `sens_grid_energy_import`, `sens_grid_energy_export`. Consumer: `sens_energy_total` only (mono). Battery: `ess.{id}.sens_ess_energy_charge` + `sens_ess_energy_discharge` (bipolar Storage).
2. Configure VO Cmds (library `VO_Earnie_Plant.xml` / `VO_Earnie_Consumer.xml` / `VO_Earnie_Battery.xml`, or generated pilots) that push Meter `total` / `totalNeg` (grid/battery) or consumer Meter `total` to those qualified IDs with a Repeat (default 10 s).
3. At QH open + close: `read_push_counter` → store readings; on `finalize_closed_interval` set `*_energy_kwh` from ΔE and `*_kw = ΔE / 0.25` when usable.
4. Plant channels without usable ΔE, battery (slot overlay not yet wired), house, baseload, Merker-only flex, and shared-meter primaries (`subtract_consumer_ids`) stay on sample means. Tag `ist_power_source` (`flex` is a per-consumer-id map: `counter` | `mean`).

## Field map

| Channel | EHAL ID(s) | Reading shape |
| --- | --- | --- |
| PV | `sens_pv_energy` | `{total}` |
| Grid bipolar | `sens_grid_energy_import`, `sens_grid_energy_export` | `{total, total_neg}` |
| Consumer mono | `consumer.<id>.sens_energy_total` | `{total}` |
| Battery bipolar | `ess.<id>.sens_ess_energy_charge` + `…_discharge` | push IO ready; slot-Ist overlay deferred |

## Flex consumers

1. Skip counter overlay when `loxone_inputs.subtract_consumer_ids` is set (composite meter; live power already peels subtracted loads).
2. Greenfield / Loxone-Import (`merge_efm`) **activates** energy `ehal_bindings` keys when binding power to a Meter (no `loxone_meter_energy` side channel).

## Out of scope

- OpenEMS energy entities (no side channel yet).
- Averaging or integrating pushed **power** to invent energy.
- Battery slot-Ist ΔE overlay (VO push fields exist; sampler still uses power mean for ESS). HA flex energy entities; shared-meter ΔE peel beyond sample mean.

## HA plant energy entities (2.6.c / 2.6.g)

Unchanged separate optional maps on **`plant.ehal_bindings`**:

| Field | Role |
| --- | --- |
| `sens_pv_energy` | PV cumulative kWh (`total_increasing`) → channel `pv.total` |
| `sens_grid_energy_import` | Grid import kWh → `grid.total` |
| `sens_grid_energy_export` | Grid export kWh → `grid.total_neg` |

Reader: `integrations/ha_meter_energy.py`. Same sampler anchors / `overlay_counter_on_closed` / `*_kw = ΔE / 0.25` as Loxone push. Mock bench: `house_sim` advances these counters via ∫P·Δt.

## Retired (pre-Q6)

- `GET /jdev/sps/io/{Meter.name}/all` parse of `total` / `totalNeg` / `Mr` / `Mrc` / `Mrd`
- Profile side channel `plant.loxone_meter_energy` / `consumer.loxone_meter_energy`
