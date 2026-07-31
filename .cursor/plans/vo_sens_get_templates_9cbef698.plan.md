---
name: VO sens get templates
overview: Pattern B VO/VI for plant, EV, heatpump, generic flex; ehal-com C.5 Wärmepumpe (incl. sens_temperature_outside) and C.6 Pool from current SwimSpa signals; Zähler notes for power Merkers.
todos:
  - id: vo-plant
    content: "VO_Earnie_Plant.xml: grid/PV/ESS sens_* + Earnie_Aussentemperatur (sens_temperature_outside)"
    status: completed
  - id: vo-ev
    content: VO_Earnie_EV.xml + map/recipe LimitSOC + P_act ↔ sens_evcs_active_power
    status: completed
  - id: vo-vi-flex
    content: VO/VI Heatpump + Consumer; VO outside temp on Plant; EFM notes
    status: completed
  - id: docs-c5-c6
    content: ehal-com C.5 (+ Aussentemp) + C.6 Pool from SwimSpa; narrow C.4; README + loxone-signale
    status: completed
isProject: false
---

# VO / VI templates + ehal-com C.5 / C.6

## Decision (locked)

**Option 1 — push VO** for telemetry; **VI** for Freigabe / Sollwerte. Placeholder `http://EARNIE_HOST:8501/ehal/loxone/telemetry/<ehal_field>/<v>`. Core still pulls `/jdev/sps/io/{name}`.

**Out of scope:** Earnie HTTP ingest; renaming live code keys `flex.power_name` (docs may show aliases).

## Plant + EV VO

| File | Cmd Title | EHAL field |
|------|-----------|------------|
| `VO_Earnie_Plant.xml` | `Earnie_Netzleistung` | `sens_grid_power_active` |
| | `Earnie_PV_Leistung` | `sens_pv_production_active` |
| | `Earnie_Batterie_SoC` | `sens_ess_soc` |
| | `Earnie_Batterie_Leistung` | `sens_ess_power` |
| | `Earnie_Aussentemperatur` | `sens_temperature_outside` |
| `VO_Earnie_EV.xml` | `Earnie_EAuto_Angeschlossen` | `sens_evcs_connected` |
| | `Earnie_EAuto_P_act` | `sens_evcs_active_power` |
| | `Earnie_EAuto_SOC` | `sens_evcs_soc_act` |
| | `Earnie_EAuto_Kapazitaet` | `sens_evcs_bat_capacity` |
| | `Earnie_EAuto_MaxStrom` | `get_evcs_nominal_current` |
| | `Earnie_EAuto_LimitSOC` | `get_evcs_limit_soc` |
| | `Earnie_EAuto_FertigUm` | `get_evcs_ready_by_time` |

Add `Earnie_Aussentemperatur` / `sens_temperature_outside` to [`greenfield_device_map.json`](share/loxone/greenfield_device_map.json) (plant). Sync EV `LimitSOC` + `P_act` as before. Keep `VO_Earnie_Status.xml`.

**Zähler:** Netz/PV/Batterie_Leistung (+ EV/WP/Verbraucher Leistung) may be EFM — keep VO cmds; prefer EFM Bezeichnung in bindings when present.

## Heatpump + generic consumer VO/VI

| Direction | File | Titles |
|-----------|------|--------|
| VI | `VI_Earnie_Heatpump.xml` | `Earnie_WP_Freigabe` (keep) |
| VI | `VI_Earnie_Consumer.xml` | `Earnie_Verbraucher_Freigabe`, `Earnie_Verbraucher_Ziel_kW` (keep) |
| VO | `VO_Earnie_Heatpump.xml` | `Earnie_WP_P_act` |
| VO | `VO_Earnie_Consumer.xml` | `Earnie_Verbraucher_Leistung` |

`sens_temperature_outside` lives on **Plant VO** (house-wide), documented in C.5 (and C.6) as shared Merker — not duplicated on WP VO.

## Docs — C.5 Wärmepumpe (Stub)

Narrow **C.4** to generic flex only. Add **C.5** in [`docs/ui/ehal-com.md`](docs/ui/ehal-com.md):

| Bereich | Art | EHAL (Stub / wire) | Loxone |
|---------|-----|--------------------|--------|
| WP Leistung | Messwert | `flex.sens_power_act` (Key: `flex.power_name`) | `Earnie_WP_P_act` oder EFM Load |
| WP Freigabe | Steuerwert | `flex.set_enable` (Key: `flex.enable_name`) | `Earnie_WP_Freigabe` |
| Außentemperatur | Messwert | `sens_temperature_outside` | `Earnie_Aussentemperatur` (hausweit; heute oft `thermal_control.loxone.ambient_temp_name`) |

Notes: `flex.` = Rollen-Namespace; Entity z. B. `wp_heating`; Pattern B VI Freigabe / VO Leistung; Aussentemp shared with Pool (C.6); no `Earnie_WP_Ziel_kW` this pass.

## Docs — C.6 Pool (Stub) — proposal from current SwimSpa

Add **### C.6 Pool / SwimSpa (Stub)** covering **all signals currently used** for SwimSpa heating + filter (refs: [`docs/spec/swimspa-filter.md`](docs/spec/swimspa-filter.md), [`THERMAL_CONTROL_LOXONE_FIELDS`](ui/smarthome_marker_fields.py), [`loxone-signale.md`](docs/referenz/loxone-signale.md)). Still stub / profile bindings — not M1 first-class wire except where EHAL names already exist.

Two Live entities today: `swimspa` (thermal heat) + `swimspa_filter` (remaining hours). Greenfield Merker prefix proposal: **`Earnie_Pool_*`** / **`Earnie_Pool_Filter_*`** (map from legacy `Earnie_SwimSpa_*` / `Ernie_Swimspa_*` / Homie names).

### C.6 proposed table

| Bereich | Art | Proposed EHAL name | Today (SwimSpa / config) | Proposed Loxone Merker |
|---------|-----|--------------------|--------------------------|-------------------------|
| Pool Gesamtleistung | Messwert | `flex.sens_power_act` | `flex.power_name` → `Earnie_Swim-Spa-P_act` (Heizung+Filter+Jets) | `Earnie_Pool_P_act` (oder EFM Load) |
| Pool Heiz-Freigabe | Steuerwert | `flex.set_enable` | `Earnie_SwimSpa_Freigabe` | `Earnie_Pool_Freigabe` |
| Pool Ist-Temperatur | Messwert | `sens_temperature_water` | `thermal_control.loxone.actual_temp_name` | `Earnie_Pool_Temp_Ist` |
| Pool Soll-Temperatur | Eingabe | `get_temperature_water_setpoint` | `setpoint_temp_name` | `Earnie_Pool_Temp_Soll` |
| Außentemperatur | Messwert | `sens_temperature_outside` | `ambient_temp_name` | `Earnie_Aussentemperatur` (shared C.5) |
| Temperatur-Toleranz | Eingabe | `get_temperature_tolerance_c` | `tolerance_c_name` | `Earnie_Pool_Temp_Toleranz` |
| Heizung aktiv | Messwert | `sens_heating_active` | `heating_active_name` / `homie_bwa_spa_heating` | `Earnie_Pool_Heizung_aktiv` |
| Filter Sollstunden | Eingabe | `get_filter_remaining_hours` | `loxone_target_hours_name` / `Ernie_Swimspa_Filter_Sollstunden` | `Earnie_Pool_Filter_Sollstunden` |
| Filter Freigabe | Steuerwert | `flex.set_enable` (Filter-Entity) | `Earnie_Swimspa_Filter_Freigabe` | `Earnie_Pool_Filter_Freigabe` |
| Filter läuft (Binär) | Messwert | `sens_filter_active` | `alternate_binary_power_name` / Homie filter | `Earnie_Pool_Filter_aktiv` |
| Native Filter-Startstunde | Eingabe | `get_filter_native_start_hour` | `filter_schedule.loxone.native_start_hour_name` | `Earnie_Pool_Filter_NativeStart` |
| Native Filter-Dauer | Eingabe | `get_filter_native_duration_hours` | `native_duration_hours_name` / Homie duration | `Earnie_Pool_Filter_NativeDauer` |

Notes under C.6:

- Fall B: one power Merker for total draw; chart subtracts filter via `subtract_consumer_ids` (not an EHAL field)
- Two HK entities: heat (`daily_target_source: thermal`) + filter (`loxone_remaining_hours`)
- Pattern B this pass: **docs + greenfield map/recipe rows** for Pool names; **draft** `VI_Earnie_Pool.xml` (Freigaben) + `VO_Earnie_Pool.xml` (temps, power, filter telemetry) optional but **include** so library matches C.6 — Filter Freigabe on VI; heating Freigabe on VI; telemetry on VO
- Do not require Homie-specific names in greenfield; Homie remains prod example only

## README + referenz

Update templates README (all VO/VI files including Pool if added). `loxone-signale.md`: Pattern B; EV LimitSOC; Aussentemp; Pool greenfield names; Zähler notes.

No `version.py` bump; **2.4.n** open.

## Consistency

Frozen Titles `Earnie_*` only. No `Ernie_*` in new drafts.
