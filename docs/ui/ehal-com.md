# EHAL-Com (Connection & Debug)

The **EHAL-Com** page under **Daemon Control** is the central place for smarthome connectivity and live debugging: **Loxone**, **Home Assistant (EHAL)**, or **OpenEMS**. It shows live read/write from the last production run of `main.py`. Loxone bindings are maintained **entity-centric** under **Loxone Structure → EHAL Mapping**. Ad hoc optimization runs via the output to Earnie `Earnie_Request_Optimize` (daemon HTTP, port `system.ehal_loxone_http_port`, default **8541**).

## Access

1. Start Streamlit: `python -m scripts.run_streamlit`
2. Navigation: **Daemon Control → EHAL-Com**

## Connection

The **smarthome backend** itself is picked on [Smarthome-Backend](smarthome-backend.md) (discovery + selection); this page only shows/re-checks the credentials for whichever backend is already active:


| Backend        | Storage                                       | Form                                                 |
| -------------- | --------------------------------------------- | ------------------------------------------------------ |
| Loxone         | `config/.env` (`LOXONE_IP` / `USER` / `PASS`) | Miniserver IP, user, password                          |
| Home Assistant | `config.json` → `ehal.ha`                     | URL, long-lived token; entity→EHAL mapping below        |
| OpenEMS        | `config.json` → `ehal.openems`                | base URL, user, password, ESS/EVCS components          |


`ehal.backend` controls the live path in `main.py` (Loxone HTTP vs. EHAL REST). Which backend choice makes sense when: [Choose Adapter](../einrichtung/adapter-wahl.md).

## B) EHAL Wire (Fields, Units, Signals)

Short overview of the **canonical EHAL wire fields** (same as `docs/ui/ehal-com.md` §C; target per backlog **2.4.j**). Adapters produce/consume these names between the hub and Earnie Core.


| Category               | Field                            | Required | Unit / sign convention                                                                                    |
| ------------------------ | ---------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------- |
| Envelope                | `schema_version`                  | yes      | integer; wire version (**3** = design C1 `set_ess_active_power`)                                              |
| Envelope                | `ts`                               | yes      | ISO-8601 timestamp **with timezone** (UTC preferred)                                                          |
| Envelope                | `adapter_id`                       | yes      | stable adapter ID (e.g. `openems-lab`, `ha-home`)                                                             |
| Telemetry               | `sens_grid_power_active`           | yes      | **W**; `+` = grid **import**, `-` = **export**                                                                 |
| Telemetry               | `sens_pv_production_active`        | yes      | **W**; >= 0                                                                                                    |
| Telemetry               | `sens_ess_soc`                     | yes      | **%**; 0…100                                                                                                   |
| Telemetry (optional)    | `sens_ess_power`                   | no       | **W**; ESS sign **OpenEMS-aligned**: `+` = **discharge**, `-` = **charge**                                     |
| Telemetry (optional)    | `sens_evcs_active_power`           | no       | **W**; >= 0 (typically 0 when idle)                                                                            |
| Telemetry (optional)    | `sens_power_consumers`             | no       | **W**; house load; from a Merker if mapped, otherwise derived from grid/PV/ESS                                |
| Setpoints (force)       | `set_ess_active_power`             | no*      | **W**; signed; OpenEMS-aligned: `+` = **discharge**, `−` = **charge**; omit for automatic mode (see [sign convention for `set_ess_active_power`](#sign-set_ess_active_power)) |
| Setpoints (limits)      | `set_ess_charge_power_limit`       | no*      | **W**; non-negative amount (true max. charge power)                                                            |
| Setpoints (limits)      | `set_ess_discharge_power_limit`    | no*      | **W**; non-negative amount (true max. discharge power)                                                         |
| Setpoints (limits)      | `set_evcs_max_current`             | no*      | **A**; non-negative amount (EV charging target/max current)                                                    |
| Setpoints (mode)        | `set_ess_mode`                     | no*      | Sticky backend: always write; **0 = automatic** (even with an old setpoint power); OpenEMS ignores it          |
| Setpoints (extended)    | `set_evcs_mode`                    | no*      | Enum: `off`                                                                                                     |
| Capability flags        | `supports_ess_write`               | yes      | boolean; ESS setpoints may be written                                                                          |
| Capability flags        | `supports_evcs_current`            | yes      | boolean; `set_evcs_max_current` may be written                                                                  |


A setpoint document must contain **at least one** of the setpoint fields. Omitted fields generally mean **"leave unchanged"** (partial updates are allowed). **Exception for sticky backends (Loxone/HA):** the Merker keeps the last value — automatic is `set_ess_mode = 0`, not "setpoint power omitted". Full device roles including `get_`* / additional `sens_evcs_`*: see §C.

<a id="sign-set_ess_active_power"></a>

### Sign Convention for `set_ess_active_power`

This field is the **forced setpoint** for ESS active power (design C1). Unit on the EHAL wire: **watts**. Sign as with `sens_ess_power` (**OpenEMS-aligned**):

| Wire value (example)              | Meaning |
| ------------------------------------ | --------- |
| `set_ess_active_power = +2000`      | **Discharge** at 2 kW (battery → house / grid) |
| `set_ess_active_power = −1500`      | **Charge** at 1.5 kW (house / PV / grid → battery) |
| Field **omitted**                    | No force (automatic); OpenEMS then writes no `SetActivePowerEquals` |

**Do not confuse** this with the limit fields: `set_ess_charge_power_limit` and `set_ess_discharge_power_limit` are **non-negative amounts** (true maxima), not a sign for charge vs. discharge direction.

Adapters must translate hub-specific conventions to EHAL **at the boundary**. Most important differences:

| Backend | Wire / write | Note |
| ------- | ------------- | ----- |
| OpenEMS | `ess0/SetActivePowerEquals` | Same sign as EHAL (`+` discharge); value in **W** |
| Home Assistant | mapped entity | Value in **W**, EHAL sign; don't mix with evcc price limits |
| Loxone | `Earnie_Batterie_Sollleistung` | Adapter writes **kW**, **same sign** as EHAL (`+` discharge). Config/inverter must use the same sign. |
| Victron GX | device-dependent | Measurement channel reg. **842** is often `+` = charging — **invert** for EHAL. An ESS setpoint must be mapped per the respective ESS-mode-2/3 documentation. |

**Loxone live vs. setpoint:** when **reading** `sens_ess_power`, the adapter inverts Loxone live (`+` = charging) to EHAL (`+` = discharge). When **writing** `set_ess_active_power`, only **W → kW** is converted; the sign stays EHAL (`+` = discharge). Config must therefore not invert the setpoint again.

Sticky backends: an old setpoint stays in the Merker. Enable/automatic is `set_ess_mode = 0`, not "setpoint power = 0" or an omitted field alone.

## C) Combined Field List: EHAL, OpenEMS, evcc, Victron, Loxone

The following tables combine, per **device role**:

- the existing **EHAL fields**
- the currently used **OpenEMS channels**
- the corresponding **evcc attributes** (YAML view, not HA `entity_id`)
- **Victron GX / EVCS** via Modbus TCP (unit ID **100** = `com.victronenergy.system`; EVCS registers from **5000** on the charger)
- the existing **Loxone fields**, including **Loxone extras**

Matching content is on **the same row**. Where a side currently has **no match**, the cell stays empty.

Column **type:** **measurement** = read (telemetry), **control value** = written (setpoint / enable), **capability** = adapter capability (no live channel).

Victron sources: [GX Modbus-TCP Manual](https://www.victronenergy.com/live/ccgx:modbustcp_faq), [ESS Mode 2/3](https://www.victronenergy.com/live/ess:ess_mode_2_and_3), [EVCS Modbus register list v3.8](https://www.victronenergy.com/upload/documents/EVCS-Modbus-TCP-register-list-v3.8.xlsx), HA mapping example [ha-modbus-manager Victron EVCS](https://github.com/TCzerny/ha-modbus-manager/blob/main/docs/README_victron_ev_charging_station.md).

### C.1 Inverter (Grid / PV)


| Area / meaning          | Type          | EHAL value name              | OpenEMS                       | evcc (YAML attribute) | Victron GX / EVCS (Modbus)                                                                                          | Loxone / Loxone extra                                   |
| -------------------------- | --------------- | ------------------------------ | -------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Grid power               | Measurement   | `sens_grid_power_active`      | `_sum/GridActivePower`          | `meters.grid.power`     | Unit 100 reg. **820–822** (`grid_power_l`*, W; `+` = import, `−` = export); alternatively grid meter **2600–2602**  | `grid_power_name`                                           |
| PV production            | Measurement   | `sens_pv_production_active`   | `_sum/ProductionActivePower`    | `meters.pv.power`       | Unit 100 reg. **850** (DC PV, W) resp. AC PV **808–813**; total is often the sum of DC+AC                          | `pv_power_name` / `plant.ehal_bindings`                     |
| Power to consumers        | Measurement   | `sens_power_consumers`        |                                   |                          |                                                                                                                       | `ehal_bindings.sens_power_consumers` (otherwise derived)    |
| Outside temperature       | Measurement   | `sens_temperature_outside`    |                                   |                          |                                                                                                                       | `Earnie_Aussentemperatur` / `plant.ehal_bindings`           |




### C.2 ESS (Battery)


| Area / meaning                  | Type          | EHAL value name                                              | OpenEMS                                       | evcc (YAML attribute)          | Victron GX / EVCS (Modbus)                                                                                              | Loxone / Loxone extra                                        |
| ---------------------------------- | --------------- | ---------------------------------------------------------------- | --------------------------------------------- | --------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Battery SoC                      | Measurement   | `sens_ess_soc`                                                   | `ess0/Soc` or `_sum/EssSoc`                   | `meters.battery.soc`             | Unit 100 reg. **843** (`battery_soc`, %)                                                                                | `soc_name`                                                       |
| Battery power                    | Measurement   | `sens_ess_power`                                                 | `ess0/ActivePower` or `_sum/EssActivePower`   | `meters.battery.power`           | Unit 100 reg. **842** (W; Victron: `+` = charging, `−` = discharging → **invert sign** for EHAL)                        | `battery_power_name`                                              |
| Write ESS setpoint power         | Control value | `set_ess_active_power` (**W**; `+` discharge, `−` charge)       | `ess0/SetActivePowerEquals` (same sign, W)    |                                    | (device-dependent; Victron measurement often `+` charging → invert; not the evcc price limit)                          | `target_active_power_name` / `Earnie_Batterie_Sollleistung` (kW, **same** EHAL sign) |
| Write ESS charge limit           | Control value | `set_ess_charge_power_limit`                                     | `ess0/SetActivePowerGreaterOrEquals`          |                                    | ESS mode 2 unit 100 reg. **2705** (`system_max_charge_current`, A) resp. on/off **2701** (no 1:1 W limit like OpenEMS)  | `target_charge_power_name`                                        |
| Write ESS discharge limit        | Control value | `set_ess_discharge_power_limit`                                  | `ess0/SetActivePowerLessOrEquals`             |                                    | ESS mode 2 unit 100 reg. **2704** (`ess_max_discharge_power`, W)                                                        | `target_discharge_power_name`                                     |
| Control command battery / Huawei | Control value | `set_ess_mode (0 = automatic / 1 = forced charge / 2 = forced discharge)` | *(ignored)*                          |                                    | See ESS mode 2/3 ESS write capability                                                                                   | `control_cmd_name`                                                 |
| ESS write capability             | Capability    | `supports_ess_write`                                             | derived adapter capability                    | derived adapter capability        | ESS mode 2/3 (reg. **2700+** / mode 3 VE.Bus setpoints); see ESS Mode 2/3 Manual                                        | derivable from active/charge/discharge Merker                     |




### C.3 EVCS (Wallbox / EV)


| Area / meaning             | Type          | EHAL value name                                                | OpenEMS                                       | evcc (YAML attribute)             | Victron GX / EVCS (Modbus)                                          | Loxone / Loxone extra                                                 |
| ------------------------------ | --------------- | ------------------------------------------------------------------ | ---------------------------------------------- | -------------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------- |
| Wallbox charging power        | Measurement   | `sens_evcs_active_power`                                          | `evcs0/ActivePower` or `evcs0/ChargePower`     | `chargers.wallbox.power`              | EVCS reg. **5014** (`Power`, W); optional phases **5011–5013**    | `Earnie_EAuto_Leistung` / EFM load / `ehal_bindings`                    |
| EV connected                  | Measurement   | `sens_evcs_connected`                                              |                                                 | binary_sensor.evcc_lab_connected      | EVCS reg. **5015** status `> 0` resp. binary `EV Connected`       | `charging_schedule.loxone.plugged_in_name`                              |
| EV current SOC                | Measurement   | `sens_evcs_soc_act`                                                |                                                 | sensor.evcc_lab_vehicle_soc           | (AC EVCS typically doesn't provide a vehicle SoC)                  | `charging_schedule.loxone.actual_soc_name`                              |
| EV nominal current (readable) | Input value   | `get_evcs_nominal_current`                                         |                                                 |                                         | EVCS reg. **5017** max. charge current (A; power = f(A, phases, V)) | replaces `charging_schedule.loxone.nominal_power_kw_name`               |
| EV battery capacity           | Measurement   | `sens_evcs_bat_capacity`                                           |                                                 | sensor.evcc_battery_capacity          |                                                                     | `charging_schedule.loxone.battery_capacity_kwh_name`                    |
| Write wallbox max current     | Control value | `set_evcs_max_current`                                              | `evcs0/SetChargePowerLimit` (A→W in the adapter) | `chargers.wallbox.maxcurrent`         | EVCS reg. **5016** (`Charging Current Setpoint`, A)                | `ehal_bindings.set_evcs_max_current` (EHAL-Com)                         |
| EV charging mode              | Control value | `set_evcs_mode` (`off=0` / `pv=1` / `now=2` / `minpv` = n/a)       |                                                 |                                         |                                                                     |                                                                        |
| EV deadline / ready-by time   | Input value   | `get_evcs_ready_by_time`                                            |                                                 |                                         |                                                                     | AlarmClock designation; SpecialState10 via `/all` (Tna text backup)     |
| EVCS write capability         | Capability    | `supports_evcs_current`                                             | derived adapter capability                     | derived adapter capability             | yes (incl. **5016**, **5010** enable, **5009** mode)                | when a max current / current Merker is mapped                           |
| SOC charge target             | Input value   | `get_evcs_limit_soc`                                                |                                                 | number.evcc_lab_limit_soc              |                                                                     | `Earnie_EAuto_LimitSOC` / `ehal_bindings.get_evcs_limit_soc`             |
| SOC min immediate             | Input value   | `get_evcs_soc_min_immediate`                                        |                                                 |                                         |                                                                     | `Earnie_EAuto_SOCMinSofort` / `ehal_bindings.get_evcs_soc_min_immediate` (≤0 = inactive) |




### C.4 Other Consumers (Stub)

Live operation runs via house-profile flex Merker. Role template: `share/ehal/roles/consumer.json`. **Heat pump** → [C.5](#c5-heat-pump-stub); **Pool / SwimSpa** → [C.6](#c6-pool--swimspa-stub).

`flex.` is a **role namespace**. Binding and live keys follow pattern B: `flex.{slug}.sens_power_act` / `set_enable` / `set_power_setpoint`. Live shows `{id}:flex.{slug}.…`. For meter IDs `zaehler_<slug>`, the wire slug has no prefix (example: `zaehler_trockner:flex.trockner.sens_power_act`). Stubs like `flex.power_name` are no longer read (fail-fast).

**Pattern B VO push path:** `/ehal/loxone/telemetry/flex.{slug}.sens_power_act/\v` (enable/setpoint `flex.{slug}.set_enable` / `flex.{slug}.set_power_setpoint`). Merker title stays `Earnie_Verbraucher_…`. See [Loxone Signals — Multiple Flex Consumers](../referenz/loxone-signals.md).


| Area / meaning        | Type          | EHAL value name (stub)             | OpenEMS | evcc (YAML attribute) | Victron GX / EVCS (Modbus) | Loxone / Loxone extra                        |
| ------------------------ | --------------- | ------------------------------------- | ------- | ------------------------ | ----------------------------- | ------------------------------------------------ |
| Flex power / state      | Measurement   | `flex.{slug}.sens_power_act`         |         |                           |                                | `Earnie_Verbraucher_Leistung` or EFM load        |
| Flex enable             | Control value | `flex.{slug}.set_enable`             |         |                           |                                | `Earnie_Verbraucher_Freigabe`                     |
| Flex power setpoint     | Control value | `flex.{slug}.set_power_setpoint`     |         |                           |                                | `Earnie_Verbraucher_Ziel_kW`                      |




### C.5 Heat Pump (Stub)

Role template: `share/ehal/roles/heatpump.json`. Greenfield prefix `Earnie_Waermepumpe_*`. In live operation typically a `thermal_annual` consumer (e.g. `wp_heating`).


| Area / meaning              | Type          | EHAL value name (stub / wire) | OpenEMS | evcc | Victron | Loxone / Loxone extra                       |
| ------------------------------ | --------------- | -------------------------------- | ------- | ---- | ------- | ----------------------------------------------- |
| Heat pump power               | Measurement   | `flex.{slug}.sens_power_act`    |         |      |         | `Earnie_Waermepumpe_Leistung` or EFM load       |
| Heat pump enable / SG-Ready   | Control value | `flex.{slug}.set_enable`        |         |      |         | `Earnie_Waermepumpe_Freigabe`                    |


Notes: pattern B — VI = enable from Earnie (`flex.{hk_id}.…` in the check); VO = optional push `flex.{hk_id}.sens_power_act`. Outside temperature only on the plant (`sens_temperature_outside`, see C.1) — not on the heat-pump VO. No target-kW Merker in this Greenfield round.

### C.6 Pool / SwimSpa (Stub)

Covers heating + filter. Two live entities: heat (`daily_target_source: thermal`) and filter (`loxone_remaining_hours`). Greenfield prefix `Earnie_Pool_*` / `Earnie_Pool_Filter_*`. Filter spec: [swimspa-filter.md](../spec/swimspa-filter.md). Recipe: `share/loxone/recipes/pool.json`.


| Area / meaning              | Type          | EHAL value name (stub)                     | OpenEMS | evcc | Victron | Loxone / Loxone extra                                             |
| -------------------------------- | --------------- | ---------------------------------------------- | ------- | ---- | ------- | ---------------------------------------------------------------- |
| Pool total power               | Measurement   | `flex.{slug}.sens_power_act`                  |         |      |         | `Earnie_Pool_P_act` or EFM load (case B: heating+filter+jets)     |
| Pool heating enable             | Control value | `flex.{slug}.set_enable`                       |         |      |         | `Earnie_Pool_Freigabe`                                             |
| Pool current temperature        | Measurement   | `sens_temperature_water`                       |         |      |         | `Earnie_Pool_Temp_Ist`                                              |
| Pool target temperature         | Input value   | `get_temperature_water_setpoint`               |         |      |         | `Earnie_Pool_Temp_Soll`                                             |
| Temperature tolerance           | Input value   | `get_temperature_tolerance_c`                  |         |      |         | `Earnie_Pool_Temp_Toleranz`                                         |
| Heating active                  | Measurement   | `sens_heating_active`                          |         |      |         | `Earnie_Pool_Heizung_aktiv`                                         |
| Filter target hours             | Input value   | `get_filter_remaining_hours`                   |         |      |         | `Earnie_Pool_Filter_Sollstunden`                                    |
| Filter enable                   | Control value | `flex.{slug}.set_enable` (filter entity)       |         |      |         | `Earnie_Pool_Filter_Freigabe`                                       |
| Filter running (binary)         | Measurement   | `sens_filter_active`                           |         |      |         | `Earnie_Pool_Filter_aktiv`                                          |
| Native filter start hour        | Input value   | `get_filter_native_start_hour`                 |         |      |         | `Earnie_Pool_Filter_NativeStart`                                    |
| Native filter duration          | Input value   | `get_filter_native_duration_hours`             |         |      |         | `Earnie_Pool_Filter_NativeDauer`                                    |


Notes: outside temperature only on the plant (`sens_temperature_outside`, see C.1). The chart may subtract filter power via `subtract_consumer_ids` (not an EHAL field). Pattern B: `VI_Earnie_Pool` (enables), `VO_Earnie_Pool` (telemetry). **VI check** = bare `Earnie_Pool_Freigabe` / `Earnie_Pool_Filter_Freigabe` (same as title); `status.json` reads the same keys from the written enable title.

**EHAL-Com mapping:** filter fields (`get_filter_remaining_hours`, `flex.pool_filter.sens_power_act`, `sens_filter_active`, native start/duration, enable) are mapped on the house-profile consumer `pool_filter` under `ehal_bindings`. Without `pool_filter` there is no filter MILP and no synthetic filter entity. Without a mapping, the filter stays inactive.

## EHAL-Com

Once the planning configuration is complete, **Scenario Explorer** appears, but **EHAL-Com** stays hidden until the connection for live operation is fully set up. Use **Connection**, **Live Read**, and the connection tests on this page.

## Page Sections



### Status Bar

The status bar combines **silent/loud mode** with the state of the **optimizer service** (`main.py`):

- **Silent mode / service running:** the optimizer runs but does not write control values to the hub.
- **Silent mode / service stopped:** the optimizer is not running.
- **Loud mode / service running:** the optimizer runs and sends data to the hub.
- **Loud mode / service stopped:** the optimizer is not running — so no data is sent.
- **Last optimizer service run:** timestamp and age (independent of the status bar).



### Live Read

Only `**sens_***` and `**get_***` (measurements / inputs). The table lists **all** expected EHAL fields (plant + consumers); without a binding, the mapping column stays empty and the status is **No mapping**. Columns everywhere:


| Column                                            | Meaning                                                                                                                                    |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| EHAL field                                          | canonical EHAL name (for consumers `{id}:{field}`)                                                                                          |
| Mapping to Loxone / Home Assistant / OpenEMS       | address in the selected backend (Loxone Merker, HA `entity_id`, OpenEMS channel); column title depends on the backend; empty if not yet mapped |
| Value                                                | live value                                                                                                                                    |
| Status                                               | OK / warning / error / no mapping                                                                                                            |
| Detail                                               | error text (empty when OK)                                                                                                                    |
| Last read                                            | timestamp of the query                                                                                                                        |


**Loxone:** periodic reading of the configured Merker (table + **test smarthome Merker**). Plant fields: `sens_ess_soc`, `sens_pv_production_active`, `sens_ess_power`, `sens_grid_power_active`, optional `sens_power_consumers`, `sens_temperature_outside` (`plant.ehal_bindings`). **Consumers** (from the flex list and house profile with a Merker): EV → `{id}:sens_evcs_`* / `{id}:get_evcs_`*; others with power →* `{id}:flex.{slug}.sens_power_act`*. No PV meter, no* `set_` / enables. `get_evcs_ready_by_time`**:** binding = AlarmClock designation (like a meter); read from **SpecialState10** (`nextEntryTime`) via `/jdev/sps/io/{name}/all`, backup **Tna** text. Numeric counters (Loxone epoch since 2009-01-01) are converted to Unix and shown locally readable in the **Value** column (`YYYY-MM-DD HH:MM:SS (unix …)`).

**HA / OpenEMS:** EHAL telemetry via REST (only `sens_`* / `get_`* in the table; the connection test may show the full JSON including the envelope). Mapping = entity or channel; derived house load: `—(derived)`. Optional caption for live power in kW.

Units and signs: see §B. Full role matrix: §C.

### Live Write

`**set_***` (plant / EV) as well as flex **enable** / setpoint (`{id}:flex.{slug}.set_enable`, optionally `set_power_setpoint`). The table lists **all** expected write fields; values/success come from the last `main.py` run (`runtime/optimizer_run_state.json`); unmapped rows have an empty mapping column. Same identity columns:


| Column                                            | Meaning                                                                                       |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| EHAL field                                          | `set_*` resp. `{id}:flex.{slug}.set_enable` (enable)                                            |
| Mapping to Loxone / Home Assistant / OpenEMS       | Merker / HA entity / OpenEMS write channel; column title depends on the backend; empty if not yet mapped |
| Value                                                | written setpoint                                                                                  |
| Success                                              | yes / no                                                                                          |
| Sent at                                              | timestamp                                                                                          |
| Message                                              | error text or silent-mode note                                                                    |


- **Loxone:** trace `loxone_writes` (IO name is traced back to the EHAL field); silent: planned setpoints from `loxone_sent` with status "not sent".
- **HA / OpenEMS:** `ehal_writes` (field, value, success, time, message); error banner from `runtime/ehal_write_error.json`.



### HA Entity → EHAL Mapping

Only with backend **Home Assistant**: scan entities, assign telemetry/setpoint fields, save. The fields are grouped by **device role** (grid / PV / battery / wallbox; templates under `share/ehal/roles/`).

- Overview / HITL: [Home Assistant + evcc](../einrichtung/ha-evcc.md) (section *If marq24 / evcc is already connected in HA*)
- Lab acceptance including stub values and table: [HA Lab Spec §5.1](../spec/ha-lab-setup.md#51-after-marq24-ha-evcc-is-connected-lab-follow-up)



### Loxone Structure → EHAL Mapping

Only with backend **Loxone**: entity-centric wizard (backlog **2.4.k**, structure scan from **2.4.f**). Entities = **plant** + consumers from the **live house profile** (same shape as Earnie entities). Mapping rows: `{entity}.{ehal_field}` → Merker name; fields grouped by device role / §C (incl. EV `set_evcs_max_current` / `get_evcs_limit_soc`, optional `sens_power_consumers`, C.4 `flex.`*).

Library templates and the Earnie-dead fallback: [Loxone Signals and the Earnie Library](../referenz/loxone-signals.md#library-setup).

1. **HTTP probe** — checks known Greenfield/template names and already mapped Merker (`greenfield_device_map.json` + prefix+slug) via `/jdev/sps/io/{Name}` (`LL.Code` 200 or 403 = present, 404 = missing). Found names fill the mapping dropdowns. Manually added Merker are checked on the next probe as well. (Loxone MCP and the Ollama AI remain in the code for later re-integration; they are currently not offered in the UI.)
2. **Loxone import** (on **Smarthome-Backend**, once connected) — creates typed plant/consumer entities and `ehal_bindings` from Merker+EFM (prefix+slug, case-insensitive). Meter designation without a leading "Zähler"/"Zaehler" and without EFM's "Verbraucher N:" as label/id; the same physical devices (e.g. pool↔swimspa, EV↔wallbox/smart) are merged, with EFM power preferred on the typed consumer. Afterward, check the signal mapping here. Beforehand, set up the library/Merker on the Miniserver: [Loxone Signals and the Earnie Library](../referenz/loxone-signals.md#library-setup).
3. **New Merker in the field dropdown** — in every EHAL field select, a still-unknown Merker name can be typed in (`accept_new_options`). A confirmation appears (**New Merker?**): choosing **yes** adds the name to the Merker list, assigns it to the field in `house_profiles.json`, and optionally checks it via HTTP probe (present / 404); choosing **no** leaves the field unmapped. Empty input doesn't count.
4. **Human-in-the-loop** — choose an entity, assign EHAL fields (select label: **meaning** plus the EHAL value name, e.g. `Netzleistung (sens_grid_power_active)`). The Merker address comes from the binding of the chosen field.
5. **Save** — **Save mapping** writes all visible field assignments of the selected entity to `plant.ehal_bindings` / `consumers[].ehal_bindings` in `house_profiles.json`. Individual new Merker are already persisted for that field on confirmation (step 3). On the first migrate/save, legacy Merker trigger keys and plant roles are removed from `loxone_blocks` (an empty `loxone_blocks` is dropped).

**Energy Flow Monitor → Consumers:** the **import meters** expander loads meters from `LoxAPP3.json` (EFM tree + orphan meters), suggests generic consumers (label/id without a leading "Zähler"), and can optionally set `flex.{slug}.sens_power_act` to the meter designation. Matches against existing typed consumers (Merker) are matched instead of duplicated. CSV export stays manual; `flex.{slug}.set_enable` / `set_power_setpoint` are not set from the meter. Spec: [efm-auto-sync-2.4.l](../spec/efm-auto-sync-2.4.l.md). Manual blueprint: plan `energieflussmonitor_hausprofil_blueprint_a`.

Bindings are **no longer** edited in the House Configurator under "Smarthome Merker" — only here on EHAL-Com. See [Loxone Signals](../referenz/loxone-signals.md).

## Silent Mode vs. Loud Mode


|                            | Silent mode                          | Loud mode                     |
| ---------------------------- | --------------------------------------- | -------------------------------- |
| Read                        | always active (also on this page)      | always active                    |
| Write by `main.py`          | no                                       | yes (only when the service runs) |
| Write table                 | setpoints only                          | value + success + timestamp      |
| Typical use                 | testing, parallel legacy operation      | production after cutover         |


Silent mode: `runtime/local_settings.json` → `"loxone_silent_mode"` (takes priority over `system.loxone_silent_mode`). Default without a file: **silent on**. The status bar also shows whether the optimizer service is currently running; without a running service, loud mode sends no data.

## Cutover Checklist

1. **Backend** chosen on Smarthome-Backend, **Connection** credentials saved here
2. **Live Read:** `sens_`* / `get_`* with status **OK**
3. **Live Write:** all `set_`* entries **success = yes** (disable silent mode first)
4. **Cockpit / Sankey:** setpoints match live values ([Charts & Panels](charts.md))



## See Also

- [Loxone Integration](../einrichtung/loxone-anbindung.md)
- [Home Assistant + evcc](../einrichtung/ha-evcc.md)
- [OpenEMS Lab](../einrichtung/openems-lab.md)
- [Loxone Signals](../referenz/loxone-signals.md)
- [Operation](../einrichtung/betrieb.md)
- Victron: [GX Modbus-TCP](https://www.victronenergy.com/live/ccgx:modbustcp_faq), [ESS Mode 2/3](https://www.victronenergy.com/live/ess:ess_mode_2_and_3), [EVCS Modbus register list](https://www.victronenergy.com/upload/documents/EVCS-Modbus-TCP-register-list-v3.8.xlsx)
- CLI (Loxone): `python -m scripts.verify_loxone_setup`
