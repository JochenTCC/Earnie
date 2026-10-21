# EHAL-Com (Connection & Debug)

The **EHAL-Com** page under **Daemon Control** is the place for live connectivity checks and debugging of the active smarthome backend: **Loxone**, **Home Assistant (EHAL)**, or **OpenEMS**.

- It shows live reads (**Live-Lesen**) and the writes of the last production run of `main.py` (**Live-Schreiben**).
- The **Signalliste** is the binding UI for **all** backends: qualified EHAL IDs, Pflicht / optional / aktiviert, match status, and SB-specific export (Loxone VO/VI ZIP; HA YAML package). There is no separate HA entity-mapping chapter.
- Binding keys on `plant` / consumers / batteries / inverters are activation flags (empty values — Earnie stores no Loxone Merker names and no HA `entity_id`s).
- An ad hoc optimization run is triggered by the Virtual Output `Earnie_Request_Optimize`, which calls `POST /ehal/loxone/request_optimize` on the daemon HTTP listener. The port is `system.ehal_loxone_http_port` (default **8541**; the environment variable `EARNIE_EHAL_LOXONE_HTTP_PORT` takes precedence). The receipt ID `request_optimize` appears on the **Signalliste** and in **Live-Lesen**, so you can verify that the hub reached Earnie.

Table and button labels on the page are German. This document uses the German label where a UI element is named, with an English gloss on first use.

## Access

1. Start Streamlit: `python -m scripts.run_streamlit`
2. Navigation: **Daemon Control → EHAL-Com**

The page is hidden until a smarthome backend has been chosen on **Smarthome-Backend**. The **Live-Cockpit** pages (Monitor, Manuelle Geräte) additionally stay locked until the connection for live operation is complete and correct. EHAL-Com shows a notice while they are locked.

<a id="connection"></a>

## A) Connection

The **smarthome backend** itself is picked on [Smarthome-Backend](smarthome-backend.md) (discovery, selection, and the **Anbindung** credentials). EHAL-Com does not check or edit credentials. It shows live read/write and the contract UI for whichever backend is active:


| Backend        | Storage                                       | Contract UI on this page                                 |
| -------------- | --------------------------------------------- | ------------------------------------------------------ |
| Loxone         | `config/.env` (`LOXONE_IP` / `USER` / `PASS`) | **Signalliste** (qualified IDs · Pflicht/aktiviert · match · VO/VI export) |
| Home Assistant | no credentials in Earnie (HA calls Earnie); optional `sign` / `boolean_invert` in `config.json` → `ehal.ha` (no `transport` — push-only) | **Signalliste** + **HA YAML-Paket** download (`ENTITY_*` · periodic push · `status.json`) |
| OpenEMS        | `config.json` → `ehal.openems`                | **Signalliste** (credentials on Smarthome-Backend) |


`ehal.backend` controls the live path in `main.py` (Loxone HTTP vs. EHAL REST). Which backend choice makes sense when: [Choose Smarthome-Backend](../einrichtung/smarthome-backend-wahl.md).

## B) EHAL Wire (Fields, Units, Signals)

Overview of the **canonical EHAL wire fields** (the per-role matrix is in §C below). Adapters produce and consume these names between the hub and Earnie Core.


| Category               | Field                            | Required | Unit / sign convention                                                                                    |
| ------------------------ | ---------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------- |
| Envelope                | `schema_version`                  | yes      | integer; wire version (**4** = `set_ess_source_select`; plant-flat SoC retired without a wire bump; **3** = forced setpoint `set_ess_active_power`) |
| Envelope                | `ts`                               | yes      | ISO-8601 timestamp **with timezone** (UTC preferred)                                                          |
| Envelope                | `adapter_id`                       | yes      | stable adapter ID (e.g. `openems-lab`, `earnie-hems`)                                                             |
| Telemetry               | `sens_grid_power_active`           | yes      | **W**; `+` = grid **import**, `-` = **export**                                                                 |
| Live / binding          | `ess.{id}.sens_ess_soc`            | Live yes | **%**; 0…100; not on the plant telemetry document                                                              |
| Telemetry               | `sens_ess_power`                   | no*      | **W**; ESS sign **OpenEMS-aligned**: `+` = **discharge**, `-` = **charge**; *required per grid-tied house battery as `ess.{id}.sens_ess_power` (plant value is derived), optional otherwise |
| Telemetry (optional)    | `sens_evcs_active_power`           | no       | **W**; >= 0 (typically 0 when idle)                                                                            |
| Telemetry (optional)    | `sens_power_consumers`             | no       | **W**; house load; from a mapped hub channel if present, otherwise derived from grid/PV/ESS                  |
| Telemetry (optional)    | `get_grid_export_power_limit`      | no       | **W**; inbound max export from grid/HEMS (magnitude ≥ 0; negative/absent or ≥ 1 000 000 W = no cap) |
| Telemetry (optional)    | `get_ess_soc_min`                  | no       | **%**; discharge cut-off SoC (device config; MILP when `limits_from_live`)                          |
| Telemetry (optional)    | `get_ess_soc_max`                  | no       | **%**; charge cut-off SoC (device config; MILP when `limits_from_live`)                             |
| Telemetry (optional)    | `get_ess_max_charge_power`         | no       | **W**; device max charge power magnitude                                                           |
| Telemetry (optional)    | `get_ess_max_discharge_power`      | no       | **W**; device max discharge power magnitude                                                        |
| Telemetry (optional)    | `inv.{id}.sens_inv_power_ac`       | no       | **W**; per inverter; `+` = feeds the AC bus                                                        |
| Live / binding          | `inv.{id}.sens_inv_power_pv`       | yes*     | **W**; ≥ 0; *required when the inverter has attached PV; plant AC PV is derived (not on telemetry doc) |
| Telemetry (optional)    | `pv.{id}.sens_pv_production_active` | no      | **W**; ≥ 0; optional per-PV-system DC power on `pv_systems[].ehal_bindings`                                         |
| Telemetry (optional)    | `inv.{id}.get_inv_max_ac_power`    | no       | **W**; device AC rating magnitude                                                                  |
| Telemetry (optional)    | `inv.{id}.get_inv_max_pv_power`    | no       | **W**; DC/MPPT limit magnitude                                                                     |
| Setpoints (force)       | `set_ess_active_power`             | no*      | **W**; signed; OpenEMS-aligned: `+` = **discharge**, `−` = **charge**; omit for automatic mode (see [sign convention for `set_ess_active_power`](#sign-set_ess_active_power)) |
| Setpoints (limits)      | `set_ess_charge_power_limit`       | no*      | **W**; non-negative amount (true max. charge power)                                                            |
| Setpoints (limits)      | `set_ess_discharge_power_limit`    | no*      | **W**; non-negative amount (true max. discharge power)                                                         |
| Setpoints (limits)      | `set_grid_export_power_limit`      | no*      | **W**; non-negative max grid export (magnitude, like ESS limits); `0` = no export; unconstrained = plant maximum (per grid-tied inverter; fallback 1 000 000 W)  |
| Setpoints (limits)      | `inv.{id}.set_inv_ac_power_limit`  | no*      | **W**; max AC output of this inverter (magnitude ≥ 0); Live curtailment when plant `p_pv_curtail` > 0, else sticky rating |
| Setpoints (limits)      | `set_evcs_max_current`             | no*      | **A**; non-negative amount (EV charging target/max current)                                                    |
| Setpoints (mode)        | `set_ess_mode`                     | no*      | Sticky backend: always write; **0 = automatic**; battery only (export caps via `set_grid_export_power_limit`); OpenEMS ignores it |
| Setpoints (source)      | `ess.<id>.set_ess_source_select`   | no*      | **0** = grid pass-through, **1** = battery island; entity-scoped on physical `standby_backup` only; omit for house ESS / plant |
| Setpoints (extended)    | `set_evcs_mode`                    | no*      | Enum: `off` \| `pv` \| `now`                                                                                    |
| Capability flags        | `supports_ess_write`               | yes      | boolean; ESS setpoints may be written                                                                          |
| Capability flags        | `supports_evcs_current`            | yes      | boolean; `set_evcs_max_current` may be written                                                                  |
| Capability flags        | `supports_ess_source_select`       | no       | boolean; entity-scoped Quellenwahl (`ess.<id>.set_ess_source_select`) may be written                                 |
| Capability flags        | `supports_inv_power_limit`         | no       | boolean; `inv.{id}.set_inv_ac_power_limit` may be written                                                     |


A setpoint document must contain **at least one** of the setpoint fields. Omitted fields generally mean **"leave unchanged"** (partial updates are allowed). **Exception for sticky hubs (HA/Loxone):** sticky channels keep the last value — automatic is `set_ess_mode = 0`, not "setpoint power omitted". Full device roles including `get_*` / additional `sens_evcs_*` / `ess.{id}.*` / `inv.{id}.*`: see §C.

<a id="sign-set_ess_active_power"></a>

### Sign Convention for `set_ess_active_power`

This field is the **forced setpoint** for ESS active power. Unit on the EHAL wire: **watts**. Sign as with `sens_ess_power` (**OpenEMS-aligned**):

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

**Loxone live vs. setpoint:** when **reading** `sens_ess_power`, the adapter only converts kW → W; Loxone live already uses `+` = discharge like EHAL. When **writing** `set_ess_active_power`, only **W → kW** is converted; the sign stays EHAL (`+` = discharge). Config must therefore not invert the setpoint again.

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

### C.1 Plant (Grid / PV sum)

<a id="c1-inverter-grid-pv"></a>


| Area / meaning          | Type          | EHAL value name              | OpenEMS                       | evcc (YAML attribute) | Victron GX / EVCS (Modbus)                                                                                          | Loxone / Loxone extra                                   |
| -------------------------- | --------------- | ------------------------------ | -------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Grid power               | Measurement   | `sens_grid_power_active`      | `_sum/GridActivePower`          | `meters.grid.power`     | Unit 100 reg. **820–822** (`grid_power_l`*, W; `+` = import, `−` = export); alternatively grid meter **2600–2602**  | `grid_power_name`                                           |
| PV production            | Measurement   | `sens_pv_production_active`   | `_sum/ProductionActivePower`    | `meters.pv.power`       | Unit 100 reg. **850** (DC PV, W) resp. AC PV **808–813**; total is often the sum of DC+AC                          | `pv_power_name` / `plant.ehal_bindings` (plant sum; per-inverter values in [C.7](#c7-inverter-per-device)) |
| Power to consumers        | Measurement   | `sens_power_consumers`        |                                   |                          |                                                                                                                       | `ehal_bindings.sens_power_consumers` (otherwise derived)    |
| Outside temperature       | Measurement   | `sens_temperature_outside`    |                                   |                          |                                                                                                                       | `Earnie_Aussentemperatur` / `plant.ehal_bindings`           |
| Absent / holiday          | Measurement   | `sens_absent_mode`            |                                   |                          |                                                                                                                       | `Earnie_Abwesend` / `plant.ehal_bindings` (0/1; OR with HK) |




### C.2 ESS (Battery)

**Multi-ESS / per-battery mapping:** In EHAL-Com each mappable battery is its own entity (house batteries and **physical** powerstations). **Virtual** powerstations are omitted — they inherit the house ESS and have no EHAL bindings. Bindings are stored on `components.json` → `batteries[].ehal_bindings` as entity-scoped `ess.{slug}.sens_ess_soc` / `set_ess_*` / `get_ess_*` (slug = battery id). Quellenwahl is `ess.{slug}.set_ess_source_select` on physical `role: standby_backup` only (not on plant or house ESS). The plant row keeps grid/PV/load/export. Plant-flat `sens_ess_soc` is retired (no wire-version bump) — SoC is entity-scoped only; bare push `/ehal/telemetry/sens_ess_soc/…` is rejected. Multi-ESS Loxone Merker titles use slug infix `Earnie_Batterie_<Slug>_…`.

A battery belongs to an inverter via `batteries[].inverter_id`. `batteries[].kind` (topology) no longer exists; `inverters[].ac_connection` (`grid_tied` | `island`) replaces it. `island` means bus participation only (feeds attached loads, not the house AC bus) — not “off the grid”; AC input may be grid-fed.


| Area / meaning                  | Type          | EHAL value name                                              | OpenEMS                                       | evcc (YAML attribute)          | Victron GX / EVCS (Modbus)                                                                                              | Loxone / Loxone extra                                        |
| ---------------------------------- | --------------- | ---------------------------------------------------------------- | --------------------------------------------- | --------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Battery SoC                      | Measurement   | `ess.{id}.sens_ess_soc`                                          | `ess0/Soc` or `_sum/EssSoc`                   | `meters.battery.soc`             | Unit 100 reg. **843** (`battery_soc`, %)                                                                                | `soc_name` / `batteries[].ehal_bindings`                         |
| Battery power                    | Measurement   | `sens_ess_power`                                                 | `ess0/ActivePower` or `_sum/EssActivePower`   | `meters.battery.power`           | Unit 100 reg. **842** (W; Victron: `+` = charging, `−` = discharging → **invert sign** for EHAL)                        | `battery_power_name`                                              |
| ESS SOC-Min (device cut-off)     | Input value   | `get_ess_soc_min`                                                | *(optional / absent)*                         |                                    | Huawei LUNA **47082** (U16, gain 10)                                                                                    | `Earnie_Batterie_SOC_Min`                                  |
| ESS SOC-Max (device cut-off)     | Input value   | `get_ess_soc_max`                                                | *(optional / absent)*                         |                                    | Huawei LUNA **47081** (U16, gain 10)                                                                                    | `Earnie_Batterie_SOC_Max`                                  |
| ESS max charge power (device)    | Input value   | `get_ess_max_charge_power`                                       | *(optional / absent)*                         |                                    | Huawei LUNA **47075** (U32 W); HA: often same `number` as charge limit                                                  | `Earnie_Batterie_Max_Ladeleistung` kW → EHAL W           |
| ESS max discharge power (device)| Input value   | `get_ess_max_discharge_power`                                    | *(optional / absent)*                         |                                    | Huawei LUNA **47077** (U32 W); HA: often same `number` as discharge limit                                               | `Earnie_Batterie_Max_Entladeleistung` kW → EHAL W        |
| Write ESS setpoint power         | Control value | `set_ess_active_power` (**W**; `+` discharge, `−` charge)       | `ess0/SetActivePowerEquals` (same sign, W)    |                                    | (device-dependent; Victron measurement often `+` charging → invert; not the evcc price limit)                          | `target_active_power_name` / `Earnie_Batterie_Sollleistung` (kW, **same** EHAL sign) |
| Write ESS charge limit           | Control value | `set_ess_charge_power_limit`                                     | `ess0/SetActivePowerGreaterOrEquals`          |                                    | ESS mode 2 unit 100 reg. **2705** (`system_max_charge_current`, A) resp. on/off **2701** (no 1:1 W limit like OpenEMS)  | `target_charge_power_name`                                        |
| Write ESS discharge limit        | Control value | `set_ess_discharge_power_limit`                                  | `ess0/SetActivePowerLessOrEquals`             |                                    | ESS mode 2 unit 100 reg. **2704** (`ess_max_discharge_power`, W)                                                        | `target_discharge_power_name`                                     |
| Control command battery / Huawei | Control value | `set_ess_mode (0 = automatic / 1 = forced charge / 2 = forced discharge)` | *(ignored)*                          |                                    | See ESS mode 2/3 ESS write capability                                                                                   | `control_cmd_name`                                                 |
| ESS write capability             | Capability    | `supports_ess_write`                                             | derived adapter capability                    | derived adapter capability        | ESS mode 2/3 (reg. **2700+** / mode 3 VE.Bus setpoints); see ESS Mode 2/3 Manual                                        | derivable from active/charge/discharge Merker                     |
| Huawei force (optional)          | Plant config  | `plant.ha_ess_force` (`driver: huawei_solar`, `device_id`, `duration_min`) | — | `huawei_solar.forcible_charge` / `forcible_discharge` / `stop_forcible_charge` | Elevate permissions in the integration; use when no `set_ess_active_power` entity exists | — |

**Battery `control` vs mapping:** If `components.json` → `batteries[].control` is `full` but neither `set_ess_active_power` nor `ha_ess_force` is configured (or `limits_only` without both limit entities), EHAL-Com shows a warning. `read_only` needs no ESS write functions.




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

Stored consumer bindings use typed namespaces (`consumer.{slug}.*`, `heatpump.*`, `pool.*`). Role stubs (`flex.sens_power_act` / `flex.set_enable`) expand to those keys on import/save. Legacy entity-scoped `flex.{slug}.*` is still accepted on dual-read until the config migration rekeys them. **Live-Lesen** shows the same qualified IDs. For meter IDs `zaehler_<slug>`, the Kennung has no prefix (example: `consumer.trockner.sens_power_act`).

**VO push telemetry:** Loxone Virtual Outputs call `GET /ehal/telemetry/<qualified-EHAL-ID>/<v>` on the daemon port (default **8541**), with optional token via `?t=`, header, or address prefix `/t/<token>`. When `EARNIE_PUSH_TOKEN` (alias `EARNIE_PILOT_PUSH_TOKEN`) is set, the token is required; when unset, Earnie accepts open LAN push. All pushable `sens_*` / `get_*` fields — including meter energy counters (`sens_pv_energy`, `grid.meter.sens_grid_energy_*`, `consumer.*.sens_energy_*`, `ess.*.sens_ess_energy_charge` / `_discharge`) — read from the push inbox (no Merker poll, no Meter `/all`). Battery library template: `VO_Earnie_Battery.xml` (or generated `VO_Earnie_Batterie_*.xml`). **Writes** are push-only via `status.json` under qualified Check keys; the legacy Merker Check keys are no longer published. See [Loxone Signals](../referenz/loxone-signals.md).


| Area / meaning        | Type          | EHAL value name (stub)             | OpenEMS | evcc (YAML attribute) | Victron GX / EVCS (Modbus) | Loxone / Loxone extra                        |
| ------------------------ | --------------- | ------------------------------------- | ------- | ------------------------ | ----------------------------- | ------------------------------------------------ |
| Flex power / state      | Measurement   | `consumer.{slug}.sens_power_act`     |         |                           |                                | `Earnie_Verbraucher_Leistung` or EFM load        |
| Flex consumer active    | Measurement   | `consumer.{slug}.sens_consumer_active` |       |                           |                                | `Earnie_Verbraucher_<Slug>_Aktiv` (digital 0/1; reserve release) |
| Flex enable             | Control value | `consumer.{slug}.set_enable`         |         |                           |                                | `Earnie_Verbraucher_Freigabe`                     |




### C.5 Heat Pump (Stub)

Role template: `share/ehal/roles/heatpump.json`. Greenfield prefix `Earnie_Waermepumpe_*`. In live operation typically a `thermal_annual` consumer (e.g. `wp_heating`).


| Area / meaning              | Type          | EHAL value name (stub / wire) | OpenEMS | evcc | Victron | HA / Loxone |
| ------------------------------ | --------------- | -------------------------------- | ------- | ---- | ------- | ----------------------------------------------- |
| Heat pump power               | Measurement   | `heatpump.{slug}.sens_power_act` |        |      |         | HA power entity / `Earnie_Waermepumpe_Leistung` or EFM |
| Heat pump enable / SG-Ready   | Control value | `heatpump.{slug}.set_enable`    |         |      |         | HA switch/input_boolean / `Earnie_Waermepumpe_Freigabe` |
| Heat storage `T_eq`           | Measurement   | `sens_temperature_heat_storage` |         |      |         | HA °C sensor / `Earnie_Waermespeicher_Temp_eq` |
| Heat storage `T_low`          | Measurement   | `sens_temperature_heat_storage_low` |     |      |         | HA °C sensor (bottom) / `Earnie_Waermespeicher_Temp_low` |


Notes: entity-scoped — VI = enable from Earnie (`flex.{hk_id}.…` in the check); VO = optional push `flex.{hk_id}.sens_power_act` plus store temps. Outside temperature only on the plant (`sens_temperature_outside`, see C.1) — not on the heat-pump VO. There is no target-kW Merker for the heat pump. Recipe: `share/loxone/recipes/heatpump.json`; VO: `VO_Earnie_Heatpump.xml`.

**Heat storage:** stratified tanks must expose energy-equivalent `T_eq` (volume-weighted mean) as `sens_temperature_heat_storage`, plus raw bottom sensor `T_low` as `sens_temperature_heat_storage_low`. Do not bind a single top-layer sensor as the RC state. On HA, map two temperature entities onto those EHAL fields on the `thermal_annual` consumer (same entity-scoped mapping as Loxone). Operator guide: [waermespeicher-schichtung-teq.md](../konfiguration/waermespeicher-schichtung-teq.md); physics in [thermals-p2.md](../dev/done/thermals-p2.md).

### C.6 Pool / SwimSpa (Stub)

Covers heating + filter. Two live entities: heat (`daily_target_source: thermal`) and filter (`loxone_remaining_hours`). Greenfield prefix `Earnie_Pool_*` / `Earnie_Pool_Filter_*`. Filter spec: [swimspa-filter.md](../dev/done/swimspa-filter.md). Recipe: `share/loxone/recipes/pool.json`.


| Area / meaning              | Type          | EHAL value name (stub)                     | OpenEMS | evcc | Victron | Loxone / Loxone extra                                             |
| -------------------------------- | --------------- | ---------------------------------------------- | ------- | ---- | ------- | ---------------------------------------------------------------- |
| Pool total power               | Measurement   | `pool.{slug}.sens_power_act`                  |         |      |         | `Earnie_Pool_P_act` or EFM load (case B: heating+filter+jets)     |
| Pool heating enable             | Control value | `pool.{slug}.set_enable`                       |         |      |         | `Earnie_Pool_Freigabe`                                             |
| Pool current temperature        | Measurement   | `sens_temperature_water`                       |         |      |         | `Earnie_Pool_Temp_Ist`                                              |
| Pool target temperature         | Input value   | `get_temperature_water_setpoint`               |         |      |         | `Earnie_Pool_Temp_Soll`                                             |
| Temperature tolerance           | Input value   | `get_temperature_tolerance_c`                  |         |      |         | `Earnie_Pool_Temp_Toleranz`                                         |
| Heating active                  | Measurement   | `sens_heating_active`                          |         |      |         | `Earnie_Pool_Heizung_aktiv`                                         |
| Filter target hours             | Input value   | `get_filter_remaining_hours`                   |         |      |         | `Earnie_Pool_Filter_Sollstunden`                                    |
| Filter enable                   | Control value | `pool.{slug}.set_enable` (filter entity)       |         |      |         | `Earnie_Pool_Filter_Freigabe`                                       |
| Filter running (binary)         | Measurement   | `sens_filter_active`                           |         |      |         | `Earnie_Pool_Filter_aktiv`                                          |
| Native filter start hour        | Input value   | `get_filter_native_start_hour`                 |         |      |         | `Earnie_Pool_Filter_NativeStart`                                    |
| Native filter duration          | Input value   | `get_filter_native_duration_hours`             |         |      |         | `Earnie_Pool_Filter_NativeDauer`                                    |


Notes: outside temperature only on the plant (`sens_temperature_outside`, see C.1). The chart may subtract filter power via `subtract_consumer_ids` (not an EHAL field). entity-scoped: `VI_Earnie_Pool_v2` (enables), `VO_Earnie_Pool` (telemetry). **VI Check / Pilot:** qualified IDs (`pool.{slug}.set_enable`, `pool.pool_filter.set_enable`, …); library `VI_Earnie_*_v2.xml` or `python -m scripts.pilot_vi_template_gen`. `status.json` publishes qualified Check keys only.

**EHAL-Com mapping:** filter fields (`get_filter_remaining_hours`, `pool.pool_filter.sens_power_act`, `sens_filter_active`, native start/duration, enable) are mapped on the house-profile consumer `pool_filter` under `ehal_bindings`. Without `pool_filter` there is no filter MILP and no synthetic filter entity. Without a mapping, the filter stays inactive.

### C.7 Inverter (per device)

<a id="c7-inverter-per-device"></a>

Bindings live on `inverters[].ehal_bindings` as entity-scoped `inv.{id}.*` (id = inverter Kennung). Optional; role template `share/ehal/roles/inverter.json`. Built-in inverters (`owned_by`) share a physical device with an ESS: map both Kennungen to that device's entities. Optional per-PV-system power: `pv.{id}.sens_pv_production_active` on `pv_systems[].ehal_bindings`. See also [Inverter topology](../referenz/ehal.md#inverter-topology-inverters-27l) in `ehal.md`.


| Area / meaning | Type | EHAL value name | OpenEMS | evcc | Victron GX | Loxone / Loxone extra |
| --- | --- | --- | --- | --- | --- | --- |
| Inverter AC power | Measurement | `inv.{id}.sens_inv_power_ac` | `ess0/ActivePower` / PV-inverter `…/ActivePower` | | TBD | `Earnie_WR_Leistung_AC` *(name TBD)* |
| Inverter PV input power | Measurement | `inv.{id}.sens_inv_power_pv` | `charger0/ActualPower` | | TBD | `Earnie_WR_Leistung_PV` *(TBD)* |
| Inverter max AC power (device) | Input value | `inv.{id}.get_inv_max_ac_power` | `ess0/MaxApparentPower` | | | `Earnie_WR_Max_AC` *(TBD)* |
| Inverter max PV input (device) | Input value | `inv.{id}.get_inv_max_pv_power` | *(optional / absent)* | | | `Earnie_WR_Max_PV` *(TBD)* |
| Write inverter AC limit | Control value | `inv.{id}.set_inv_ac_power_limit` | PV-inverter `…/ActivePowerLimit` | | | `Earnie_WR_Limit_AC` *(TBD)* |
| Inverter limit write capability | Capability | `supports_inv_power_limit` | derived adapter capability | derived | | derivable from mapped limit Merker |

Inverter `control` vs mapping: `full` needs `set_inv_ac_power_limit`; `limits_only` / `read_only` need no inverter write. EHAL-Com warns like for ESS. Curtailment write: lower limit only when plant `p_pv_curtail[t0] > 0` (allocated by PV forecast); otherwise write rating to release sticky backends.

<a id="ehal-com"></a>

## Page Sections

Top to bottom, the page shows:

1. The path of the active configuration, the Live-Cockpit lock notice (while it applies), and the result of the **live topology check**. A rejected topology appears as the error `Live-Topologie abgelehnt: …`; an unreadable one as a warning.
2. **Live-Lesen** (Live Read) and **Live-Schreiben** (Live Write), including the **Schreibtest** expander.
3. For Home Assistant: **HA Push-Carrier** / **YAML-Paket** download.
4. **Signalliste** (all backends) — contract table and export.

### Optimizer service and write mode

EHAL-Com has no status bar of its own. Write mode and service state live on **Optimierer-Dienst** (same navigation section):

- **Silent-Modus** toggle (section *Schreibzugriffe*): when on, the optimizer does not write setpoints to the hub.
- **Status**, **PID**, **Lock**, and **Letzter Optimierungslauf**: state of the optimizer service (`main.py`) and the age of its last run.

Setpoints reach the hub only in **Loud mode while the service is running**. Loud mode with a stopped service writes nothing. EHAL-Com shows the outcome of the last run: **Live-Schreiben** reports `Silent-Modus beim letzten Lauf …` when that run was silent. On Loxone, a caption at the top shows when the Miniserver last called Earnie (`Letzter Aufruf vom Miniserver`).

### Live Read

Only `sens_*` and `get_*` (measurements / inputs). The table lists **all** expected EHAL fields (plant + batteries + inverters + consumers); without a binding **and** without a usable push resolve, Status is **Kein Mapping** (no mapping). Live tables group by role label (including **Wechselrichter** for `inv.{id}.*`). Columns:

| Column (UI label)      | Meaning |
| ---------------------- | ------- |
| `EHAL-Feld` (EHAL field) | Exchange EHAL ID (qualified where that is the wire form). |
| `Wert` (value)         | Hub/raw side (Loxone push/check value with hub unit when known). Same header on HA/OpenEMS: filled only when reverse conversion is possible, else `—`. |
| `Wert (EHAL)`          | Value in EHAL units (Loxone: after role-registry conversion; HA push: already canonical on the wire). `—` when no conversion path exists. |
| `Status`               | `OK`, `Warnung`, error states, or `Kein Mapping`. For push backends also push-state strings (`0 angenommen (verstummt)`, `0 (gehalten)`, `Zuletzt bekannt (gehalten)`, …). |
| `Detail`               | Error text (empty when OK); optional empty rows may show a fallback hint. |
| `Zuletzt gelesen` (last read) | Timestamp of the query; for push rows the inbox `last_ts` (local clock) is preferred when available. |

**Units:** from role `loxone` / `openems` blocks in `share/ehal/roles/*.json` (HA: EHAL wire units; conversion happens in the carrier YAML Jinja) — not hard-coded in the UI. Every value cell shows its unit as a suffix when known.

**Row colours (additive; Status stays authoritative):** black/default = mandatory fresh OK; gray = optional; blue = cached held; yellow = outdated/assumed/warning; red = no mapping or read error.


**Loxone:**

- **Source:** pushable `sens_*` / `get_*` come from the VO inbox. An empty Merker with a present binding key still reads via the qualified EHAL ID (push-only).
- **Kein Mapping** means unbound only — not “value is 0”.
- **Freshness:** a last-known value within 5 minutes counts as **OK** (`Zuletzt bekannt …`). A missing push, or a last-known value older than 5 minutes, shows as **Warnung** in Live-Lesen and in the startup verify — not as a hard error.
- **Startup:** on `main.py` start, Earnie hydrates `runtime/loxone_push_inbox.json`, starts the VO HTTP listener, and waits for the push link (up to ~40 s when `EARNIE_PILOT_PUSH_TOKEN` is set). It then runs loxone-verify.
- **Grid meter:** rows are always `grid.meter.*`, never bare `sens_grid_*` / `get_grid_*`. Storage keys on `plant.ehal_bindings` may stay bare.
- **ESS:** when EHAL-mappable batteries exist, the rows are only `ess.<id>.*`; bare plant `sens_ess_*` / `get_ess_*` are omitted. Legacy single-ESS plants without entity-scoped batteries still show bare plant ESS rows.
- **Plant fields that stay bare:** `sens_pv_production_active`, optional `sens_power_consumers`, `sens_temperature_outside`, `sens_absent_mode`, and `sens_pv_energy` (until `pv.*` replaces it).
- **Consumers** use qualified EHAL IDs: EV → `evcs.{id}.*` / `ev.{id}.*`; flex power → `consumer.{slug}.sens_power_act` (or `heatpump.*` / `pool.*` by type); domain temperatures under the same namespace. No `set_*` fields or enables appear in Live-Lesen.
- **`get_evcs_ready_by_time`:** Analog VO numeric next-entry, or fresh Tna text (`Morgen, 07:00`).
- **Counters:** numeric counters (Loxone epoch since 2009-01-01) are converted to Unix time and shown in readable local form in the `Wert` column (`YYYY-MM-DD HH:MM:SS (unix …)`).

**HA:** Live read/write uses the same push inbox + `GET /ehal/status.json` as Loxone (no REST pull). Telemetry on the wire is canonical EHAL units (carrier converts in HA). Fill `ENTITY_*` in the downloaded YAML and keep the periodic push cadence (default 10 s) — see [push cadence](../referenz/loxone-signals.md#push-cadence-sb-neutral). Derived house load: `—(derived)`. Optional caption for live power in kW.

**OpenEMS:** Live-Lesen uses the OpenEMS adapter channels (`sens_*` / `get_*` in the table).

Units and signs: see §B. Full role matrix: §C.

### Live Write

`set_*` fields (plant / EV) as well as flex **enable** (`consumer|heatpump|pool.<slug>.set_enable`, `evcs.<id>.set_evcs_*`). The grid export write is `grid.meter.set_grid_export_power_limit`. With entity-scoped batteries, bare plant `set_ess_*` fields are omitted in favour of `ess.<id>.*` (source selection, *Quellenwahl* = `ess.<id>.set_ess_source_select`, on physical `standby_backup` only).

The table lists **all** expected write fields. Values and success come from the last `main.py` run (`runtime/optimizer_run_state.json`). Unmapped rows have an empty mapping column. Columns:

| Column (UI label)      | Meaning |
| ---------------------- | ------- |
| `EHAL-Feld` (EHAL field) | Qualified EHAL ID of the `set_*` field, for example `consumer.<slug>.set_enable`. |
| `Mapping auf Loxone` / `Mapping auf Home Assistant` / `Mapping auf OpenEMS` | Activation / channel column (title follows the active backend). For push backends the binding key may be present with an empty hub name; empty if not activated. |
| `Wert`                 | EHAL / internal setpoint (with EHAL unit). Loxone loud traces that store hub units are normalized here. |
| `Wert (Hub)`           | Value after conversion to hub units (what is published / mirrored). `—` when no conversion path exists. |
| `Erfolg` (success)     | `Ja` / `Nein`; Loxone rows can also show `Übersprungen` (skipped). |
| `Gesendet um` (sent at) | Timestamp. |
| `Meldung` (message)    | Error text or silent-mode note. |


- **Loxone:** trace `loxone_writes` (IO name is traced back to the EHAL field); silent: planned setpoints from `loxone_sent` with status "not sent".
- **HA:** setpoints published to `status.json` (qualified keys); Schreibtest success = published ledger + HA (or test client) fetched `status.json` (`published_fetched_at`). Error banner from `runtime/ehal_write_error.json`.
- **OpenEMS:** `ehal_writes` (field, value, success, time, message); error banner from `runtime/ehal_write_error.json`.

### Schreibtest

Under **Live-Schreiben**, the **Schreibtest** expander lists all activated write fields (plant, entity-scoped `ess.{slug}.set_*`, EV, flex enable). Enable **Senden** per row, set values, then write. Optional **Auto-Roundtrip**: for Loxone and HA, success = published into the ledger + hub `status.json` callback `fetched_at` (no Merker HTTP echo; true VO value-echo deferred).

**Preconditions**

- Silent mode **off** (same gate as the daemon). While silent mode is on, the buttons are disabled.
- Rows are all mapped Live-Schreiben fields, including `ess.<id>.set_ess_source_select`, `set_evcs_mode`, and flex `set_enable`.
- A confirmation dialog precedes every live write.

**Limits (useful / safe values)**

| Field | Range |
| ----- | ----- |
| `set_ess_charge_power_limit`, `set_ess_discharge_power_limit`, `set_inv_ac_power_limit` | `0 … max_power_kw` (sent as W on the wire) |
| `set_grid_export_power_limit` | `0 … 1 000 000` W (magnitude; `0` = no export; upper bound = the unconstrained value) |
| `set_evcs_max_current` | `0 … min(nominal current, 6 A)` (6 A when the nominal current is unknown) |
| `set_ess_mode` | `0` automatic / `1` charge / `2` discharge |
| `set_evcs_mode` | `off` / `pv` / `now` |
| `ess.<id>.set_ess_source_select` | `0` grid / `1` battery |
| flex `set_enable` | `0` off / `1` on |

**Force ESS power:** `set_ess_active_power` (also entity-scoped) is always listed. The row stays locked until the Force checkbox is ticked. Force unlocks **Senden** (default 100 W, hard limit ±200 W) and requires a **second** confirmation.

**Auto-Roundtrip** result:

| Result | Meaning |
| ------ | ------- |
| Pass | Write OK and the read-back matches (tolerance: absolute ≤ 1 or relative ≤ 1 %). |
| Partial | Write OK, but no readable read-back (for example OpenEMS without channel read-back). |
| Fail / write error | Mismatch or adapter error. |

After an Auto-Roundtrip, safe setpoints are always written (ESS automatic, EVCS 0 A). To do this manually, use the **Sicher wiederherstellen** button. Lab adapters are only flagged by a hint, not blocked.

### HA YAML package

Only with backend **Home Assistant**. Under **HA Push-Carrier**, download a YAML package generated from **activated** signals:

- Per read signal: `rest_command` + automation with **periodic** `time_pattern` (interval = `EARNIE_PILOT_PUSH_REPEAT_S`, default **10 s** — not only on state change).
- Heartbeat push; REST sensor on Earnie `status.json`; setpoint automations (`status.json` attribute → `number.set_value` on the target entity; re-applied at HA start and every push interval, but only written when the target differs by more than ~1 %, so a restart or a manual change is corrected without a write every 10 s; fields Earnie did not publish are ignored). After a write the automation re-checks the target after 5 s; if it still differs it logs a warning and pushes `hub_write_failed` (value 1) to Earnie. EHAL-Com then shows a red *Home Assistant meldet: … nicht angewendet* notice under Live-Schreiben (for 3 push intervals after the last report) and the daemon logs a warning at the next write — „Erfolg“ in Live-Schreiben only means *published*, not *applied*. This feedback does not degrade capabilities (the `write_error` schema is unchanged), including `ha_ess_force` where configured.
- Placeholders `ENTITY_*` only — replace them in HA with real `entity_id`s. Earnie never stores those names.
- Jinja converts entity units to canonical EHAL units before the push URL is called.

CLI equivalent: `python -m scripts.ha_carrier_yaml_gen --config-dir <config> --host <Earnie-host> --port 8541 --out earnie_ha_carrier.yaml`. Lab checklist: [HA Lab Spec](../dev/ha-lab-setup.md). Cadence / zero rule: [Loxone Signals](../referenz/loxone-signals.md#push-cadence-sb-neutral).

<a id="signalliste-loxone-contract"></a>

### Signalliste (signal contract)

Shown for **every** backend. This is the binding UI (replaces the former Loxone structure mapping and the HA entity-mapping chapter).

| Column | Meaning |
| ------ | ------- |
| Direction | Read (`sens_*` / `get_*`) or write (`set_*` / enables) |
| Qualified EHAL ID | Exchange form (`grid.meter.*`, `ess.{id}.*`, `consumer.` / `heatpump.` / `pool.` / `evcs.` / `ev.` / `inv.{id}.*`) |
| Meaning | Entity Bezeichnung + field label |
| Pflicht / aktiviert | Required vs optional; whether the binding key is present |
| Hub unit | Loxone only — expected hub unit from role `loxone` block (e.g. **kW**); omitted for HA |
| EHAL unit | EHAL wire unit from the registry (e.g. **W**); `—` if none |
| Required by | EHAL functions from `ehal/functions.py` that need the field |
| Match | Read = last received in the push inbox (age) / never; write = last hub fetch of `status.json` / never published |
| Export | Loxone: ZIP of VO + VI pilot templates + README; HA: use the **YAML-Paket** section (activated signals) |

Optional signals default off; toggle them in the Signalliste (on = add activation key, off = remove). Required signals are activated when a component is saved in the Hauskonfigurator. For a grid-tied house battery this includes `ess.{id}.sens_ess_power`; changing an inverter's `ac_connection` re-evaluates its batteries. Existing packs get the key through the configuration migration (`dm4.required_signal_activation`); regenerate the HA YAML package afterwards and map the new `ENTITY_ess_<id>_sens_ess_power` placeholder.

Always listed as **Pflicht** (not a binding, not in the optional-signals expander): `heartbeat_smarthome` (read / Hub→Earnie) and `heartbeat_earnie` (write / Earnie→Hub, Unix seconds). Control receipt `request_optimize` (VO cmd `Earnie_Request_Optimize` → daemon POST; age stays OK even when older than five minutes).

**Loxone import** (on **Smarthome-Backend**) still creates typed entities from Merker/EFM names but writes **empty** binding values (activation flags only). Clear existing Merker strings once with `python -m scripts.clear_loxone_binding_names_once --config-dir <config>`.

**EFM meters:** applied by **Smarthome-Backend → Loxone-Import** (`merge_efm`). That path activates energy push fields on `ehal_bindings` (`sens_pv_energy` / `sens_grid_energy_*` / consumer `sens_energy_total` mono only) so the daemon can derive slot Ist from VO-pushed counters (see [loxone-meter-energy-slot-ist](../dev/done/loxone-meter-energy-slot-ist.md)). Wire the matching energy VOs next to power. Spec: [EFM-Auto-Sync-Spezifikation](../dev/done/efm-auto-sync.md); SB page: [Smarthome-Backend](smarthome-backend.md). Library templates: [Loxone Signals](../referenz/loxone-signals.md#library-setup).

## Write push-only

Loud writes publish only to `status.json` under qualified EHAL IDs. Loxone VI and HA REST sensors / automations poll on the repeat interval (default **10 s**). Loxone VI templates must use `VI_Earnie_*_v2.xml` or the Pilot VI. The staged Loxone rollout checklist lives in [loxone-write-push-only-cutover](../dev/loxone-write-push-only-cutover.md).

## See Also

- [Smarthome-Backend](smarthome-backend.md)
- [Loxone Integration](../einrichtung/loxone-anbindung.md)
- [Home Assistant + evcc](../einrichtung/ha-evcc.md)
- [Loxone Signals](../referenz/loxone-signals.md)
- [Operation](../einrichtung/betrieb.md)
- Victron: [GX Modbus-TCP](https://www.victronenergy.com/live/ccgx:modbustcp_faq), [ESS Mode 2/3](https://www.victronenergy.com/live/ess:ess_mode_2_and_3), [EVCS Modbus register list](https://www.victronenergy.com/upload/documents/EVCS-Modbus-TCP-register-list-v3.8.xlsx)
- CLI (Loxone): `python -m scripts.verify_loxone_setup`
