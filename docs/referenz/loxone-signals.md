# Loxone signals and templates

> **Important:** Earnie generates the Virtual In and Virtual Out templates **individually from the current configuration** (house, components, enabled signals). The templates always come from the export on **Daemon Control → EHAL-Com → Signalliste**.

This page is the reference for connecting Earnie to Loxone. It covers two topics:

1. **Setup:** the [recommended procedure](#first-connection) for the first connection: EFM meters, Loxone import into the house profile, exporting the templates and loading them into Loxone Config, plus the Earnie dead-man fallback.
2. **Signal contract:** which Merker **names** and EHAL roles (`ehal_bindings`) belong together (default names from `greenfield_device_map.json` and the recipes).

Without stable names and bindings, Earnie can neither read nor control the installation reliably. Related pages:

- HTTP access and operation: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md) (German)
- Signal list and export: [EHAL-Com](../ui/ehal-com.md#signalliste-loxone-contract)

**Terms (smart home Merker):** The **address** (a string, e.g. `Earnie_Waermepumpe_Freigabe`) is a *smart home Merker*. The **role** is the EHAL field name (`sens_ess_soc`, `consumer.{slug}.sens_power_act`, …) in `ehal_bindings`. Do not confuse a Merker with chart markers or with `earnie_role` (Bekannt/Gesteuert/Manuell).

This page calls the import and naming scheme **Default**. The file `share/loxone/greenfield_device_map.json` keeps its name.

---

<a id="first-connection"></a>

## Recommended procedure for the first connection

When connecting Earnie to Loxone for the first time, this order works well:

1. **Prepare the meters in Loxone.** For every consumer Earnie should see, and for the grid, create one meter block with a unique, stable name and assign it to the **Energy Flow Monitor** (EFM) (see [Meters and Energy Flow Monitor](#efm-meters)). Earnie reads these meters during setup and derives an automatic configuration basis from them. The import does not create the grid meters as consumers, but they are the solid basis for the EHAL signals created later.
2. **Import the meters.** On **Daemon Control → Smarthome-Backend**, run the **Loxone-Import** (see [Loxone import in Earnie](#loxone-import)). Earnie creates the consumers in the house profile. Then add the parameters in the **Hauskonfigurator** (kWh, schedules, power ratings, …).
3. **Generate and integrate the templates.** Only when the scenario is fully set up and the signal contract is settled (Signalliste on EHAL-Com: required signals enabled, optional signals chosen), export the VI/VO templates and integrate them into Loxone (see [Setup, steps 3–6](#library-setup)). If the house, components or enabled signals change afterwards, export the templates again.

---

<a id="entity-scoped-overview"></a>

## Overview

| Direction       | Block                                   | Purpose                                                                                           |
| --------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Earnie → Loxone | **Virtual HTTP In** (`VI_Earnie_*.xml`) | Loxone polls Earnie's `status.json`; setpoints, enables and heartbeat land in the named VI Cmds   |
| Loxone → Earnie | **Virtual Out** (`VO_Earnie_*.xml`)     | Loxone sends telemetry to the Earnie inbox (qualified EHAL ID)                                    |
| Meters          | EFM / Meter                             | **Power** of grid, PV, battery and flexible consumers, preferably via the EFM name               |

In addition there is an **Earnie dead** fallback in Config (see [Earnie dead-man fallback](#earnie-dead-fallback-in-loxone-config)).

**Virtual Inputs (Earnie → Loxone):** The optimizer service delivers setpoints, enables and heartbeat via `GET http://<Earnie>:8541/ehal/loxone/status.json`. `heartbeat_earnie` is the current Unix time; the setpoints come from the setpoints sent last. `status.json` publishes qualified check keys only.

**Virtual Outputs (Loxone → Earnie):** Loxone sends `sens_*` / `get_*` / consumer power under qualified path IDs. Earnie reads these fields from the push inbox.

**Enable Cmds (0/1) must be analog.** The VI templates set `Analog="true"`. In Config, do **not** choose "as digital input" or the digital mode. In digital mode the input jumps to `1` briefly on **every** poll, even if `status.json` constantly returns `0`. A steady 0/1 only results from the value `\v` in analog mode.

### Three levels (name / check / VO path)

| Level                                  | Where                      | Flexible consumer example                                 | EV example                                                   |
| --------------------------------------- | -------------------------- | --------------------------------------------------------- | ------------------------------------------------------------ |
| **Merker name (Loxone import)**        | Control name on the Miniserver (LoxAPP3) | `Earnie_Verbraucher_Waschmaschine_Freigabe` | `Earnie_EAuto_Garage_Soll_A`                                |
| **Virtual Input check / status JSON**  | Check pattern on the Virtual In | `consumer.{hk_id}.set_enable` (heat pump/pool: `heatpump.` / `pool.`) | `evcs.{ev_id}.set_evcs_max_current` / `set_evcs_mode` |
| **Virtual Output command on**          | Virtual Out URL            | `/ehal/telemetry/consumer.{hk_id}.sens_power_act/<v.3>` (heat pump/pool: `heatpump.` / `pool.`) | `/ehal/telemetry/ev.{ev_id}.sens_evcs_soc_act/<v.1>` |

`{hk_id}` / `{ev_id}` is the `id` of the entity in the house profile (snake_case). In the exported templates these IDs are already filled in. The Cmd titles in the exported templates are derived from the qualified EHAL ID (e.g. VI title `consumer_waschmaschine_set_enable`, VO title `Push_consumer_waschmaschine_sens_power_act`). The `Earnie_*` names are the Merker / LoxAPP3 control names used by the Loxone import.

**Qualified checks.** `status.json` publishes qualified EHAL IDs:

- `consumer.{slug}.set_enable`, `heatpump.{slug}.set_enable`, `pool.{slug}.set_enable`
- `evcs.{slug}.set_evcs_max_current` / `set_evcs_mode`
- Plant ESS keys (without prefix) and `grid.meter.*`, including the write value `grid.meter.set_grid_export_power_limit`
- Power station `ess.{id}.set_*`

Plant bindings stay without prefix (`plant.ehal_bindings.set_grid_export_power_limit`).

---

## Setup

<a id="library-setup"></a>

### 1. Meters and Energy Flow Monitor (EFM)

<a id="efm-meters"></a>

The Loxone import takes over the meter blocks attached to the Energy Flow Monitor. In Loxone Config:

1. For every consumer Earnie should see, and for the grid, create or keep a meter with a **unique, stable name**.
2. Assign the meter to the **Energy Flow Monitor** (grid / PV / battery / consumer).
3. Do not use remainder/difference nodes as a separate flexible consumer. The import skips typical remainder names.

Power Merker (`Earnie_Netzleistung`, `Earnie_PV_Leistung`, …) **can** come from the EFM. Earnie prefers the EFM name in the binding when one exists.

**EV ready-by time.** The Loxone import binds **AlarmClock** blocks to `get_evcs_ready_by_time` of the EV entity that already has meter/power bindings (same convention as for the meter name). Optional analog VO: `/ehal/telemetry/ev.<id>.get_evcs_ready_by_time/<v>` (numeric next entry; the inbox also accepts short text in Tna style). Bound ready-by fields always use the push inbox.

### 2. Loxone import in Earnie

<a id="loxone-import"></a>

Prerequisites: every consumer has a meter block on the EFM (step 1), and the credentials are entered under **Smarthome-Backend → Zugangsdaten**. The import button becomes active only once the Miniserver is reachable.

1. On **Daemon Control → Smarthome-Backend**, the section **Loxone-Import** appears below the connection overview as soon as Loxone is connected. During initial setup, **Nein — manuell fortfahren** sits in the same row as the import button.
2. Earnie loads `LoxAPP3.json`, matches `Earnie_*` to the LoxAPP3 control names (exact or prefix + slug, case-insensitive), creates typed entities and binds the EFM meters.
3. Then complete the parameters (kWh, schedules, living area, …) in the **Hauskonfigurator** and finish setting up the scenario.
4. Check the signal contract on **EHAL-Com** ([Signalliste](../ui/ehal-com.md#signalliste-loxone-contract)): required signals enabled, optional signals chosen.

### 3. Export the templates

1. On **Daemon Control → EHAL-Com → Signalliste**, open the **Export** section (scenario and signal contract from step 2 are complete).
2. Choose the **scope**: **nur aktivierte** (default) or **alle (Pflicht + optional)**.
3. Check the **IP address of the device running Earnie** and the **HTTP port** (default **8541**, `system.ehal_http_port`). Earnie writes both directly into the templates.
4. **ZIP herunterladen (VO + VI + README)**.

The ZIP contains one template per device group, e.g. `VO_Earnie_Plant.xml`, `VO_Earnie_Batterie_<id>.xml`, `VO_Earnie_Wechselrichter_<id>.xml`, `VO_Earnie_Verbraucher.xml`, `VO_Earnie_Heartbeat.xml` and the matching `VI_Earnie_*.xml`. It always includes `VO_Earnie_Status.xml` with the optional `Earnie_Request_Optimize` (see [Request Optimize](#request-optimize)). It also contains the signal lists `Earnie-VO-Signalliste.csv` / `Earnie-VI-Signalliste.csv` (columns: file, Cmd title, EHAL ID, Merker name, type) and a short `README.txt`.

After changes to the house, components or enabled signals, download the export again and replace the changed templates in Loxone Config.

### 4. Copy the templates into Loxone Config

Copy only the `.xml` files into the template folders; the CSV files and `README.txt` stay outside.

- `VI_Earnie_*.xml` to `%ProgramData%\Loxone\Loxone Config\<Version>\Template\VirtualIn\` or `Documents\Loxone\Loxone Config\Templates\VirtualIn\`
- `VO_Earnie_*.xml` to the corresponding `VirtualOut` folder

Create the folders if needed. Then **restart Loxone Config**. The templates appear under Periphery / Device Templates (Virtual In / Virtual Out).

### 5. Earnie address and push token

Host and port are already in the exported templates. If Earnie's address changes, export the templates again or adjust the address in Config. The Streamlit UI typically uses port **8501**, the **daemon HTTP** (Virtual In status, telemetry, `Earnie_Request_Optimize`) port **8541**. See [Streamlit ports](../dev/streamlit-ports.md) (developer docs).

The VO addresses contain the placeholder `PUSH_TOKEN_HIER_ERSETZEN`. If `EARNIE_PUSH_TOKEN` is set, replace the placeholder with this value; otherwise remove the placeholder.

Example of a Virtual In address (status JSON):

`http://192.168.178.10:8541/ehal/loxone/status.json`

Virtual Out address for **Status / Request Optimize**:

`http://192.168.178.10:8541`

The telemetry VOs (`VO_Earnie_*`) also target the daemon port **8541**. The telemetry push works like this:

- **Receiver:** `/ehal/telemetry/<EHAL-ID>/<value>`. If `EARNIE_PUSH_TOKEN` (alias `EARNIE_PILOT_PUSH_TOKEN`) is set, the token must be sent along; without a token, Earnie accepts pushes without authentication (open LAN).
- **Inbox reading:** All pushable `sens_*` / `get_*` fields are read from the inbox (no Merker polling). This includes the **meter energy readings** of consumers (`consumer.<id>.sens_energy_total`) and batteries (`ess.<id>.sens_ess_energy_charge` / `_discharge`). Earnie computes the actual values per quarter hour from the power values (sampled every 30 s and averaged); meter readings refine them but are not required.
- **Repeat interval / zero rule:** see [Push cadence (Loxone and Home Assistant)](#push-cadence-sb-neutral).
- **Heartbeat:** The synthetic heartbeat VO is always push.
- **Ready-by time** (`ev.<id>.get_evcs_ready_by_time`): pushed as an analog VO. A numeric value for the next entry is preferred. Text in Tna style such as `Morgen, 07:00` is accepted while it is fresh and parsed by the optimizer.
- **Value placeholder:** A Virtual Output command uses `<v>` (in XML as `&lt;v&gt;`). `<v>` sends the value rounded to an integer, `<v.1>` to `<v.3>` send it with 1 to 3 decimal places. The templates set the decimal places to match the signal: power, energy and power factor `<v.3>`, grid current `<v.2>`; voltage, charge level, temperature and EV current `<v.1>`. Loxone does not replace more than 3 decimal places: `<v.4>` arrives as text and Earnie cannot read the value. `\v` is the placeholder for the Virtual **Input** check and arrives in an output as control character 0x0B.

<a id="push-cadence-sb-neutral"></a>

### Push cadence (Loxone and Home Assistant)

The same inbox rule applies to **Loxone** (VO repetition) and **Home Assistant** (YAML `time_pattern`):

| Rule | Behaviour |
| --- | --- |
| Minimum cadence | Push every read signal at least every `EARNIE_PUSH_REPEAT_S` seconds (alias `EARNIE_PILOT_PUSH_REPEAT_S`) (default **10**). Freshness limit in the inbox: typically 3 × the repeat interval. |
| Link / heartbeat | While the link is fresh (heartbeat or another non-zero analog value arrived recently), the zero assumption below applies. |
| Silent (power only) | If a **power signal** stays away longer than the freshness limit and the link is fresh, Earnie assumes **0**. Status in Live Read: `0 angenommen (verstummt)`. Never sent while the link is fresh: `0 angenommen (nie gesendet)`. |
| Silent (everything else) | Charge level, limits (`get_*`) and temperatures are **never** assumed to be 0. Earnie holds the last value for 5 minutes (`Zuletzt bekannt (gehalten)`), after that `Lesefehler` applies. Live Read and the Signalliste show the same as the optimizer's read path. |
| Energy meters | Cumulative kWh fields (`*energy*`) are **never** assumed to be 0. Stale or never received → no value (no slot actual from an invented zero). |
| Explicit 0 | A pushed value `0` counts as a held off (`0 (gehalten)`), not as "silent". For this, the Loxone templates send a **command off** with the value `0` for analog outputs (`/ehal/telemetry/<EHAL-ID>/0`). Without it, nothing arrives at value 0: an export limit of 0 kW, a maximum charge power of 0 or an outside temperature of 0.0 °C would then be unreadable. |

> **Note:** A HA automation that pushes only on state change reports a constant non-zero value as 0 after the cadence. Therefore push periodically – not only with a `state` trigger.

Adapt the polling or the Cmd check pattern to the JSON keys (plant: `set_ess_*` / `heartbeat_earnie`; flexible consumers: `consumer.{hk_id}.…` (heat pump `heatpump.…`, pool `pool.…`); EV: `evcs.{ev_id}.…`). Stable **names** remain the contract for Earnie and the Default import.

### 6. Insert and wire the devices

1. Insert each exported template once.
2. Connect the Virtual Output Cmds to the real measured values, the Virtual Input Cmds to the actuators or the program.
3. Do not change the Cmd titles, VI check and VO path of the exported templates; they are the contract with the Signalliste.
4. Save or load the program to the Miniserver.

### 7. Earnie dead-man fallback (in Loxone Config)

<a id="earnie-dead-fallback-in-loxone-config"></a>

Goal: If Earnie is unreachable or the Virtual In stops updating, the Miniserver should **ignore** Earnie's last setpoints and run local rules instead.

Recommended approach (logic blocks in Config, no Earnie code):

1. **Watchdog** on the heartbeat Cmd (`heartbeat_earnie` in `VI_Earnie_Heartbeat.xml`, `Earnie_Heartbeat` in the Default naming; Unix timestamp): age = now − heartbeat, or "value unchanged for x seconds".
2. **Threshold:** e.g. 2–3 × the polling time of the Virtual In, typically ≥ 30 s with a 10 s poll.
3. **When the fallback triggers:**
   - Set `Earnie_Steuerbefehl` / ESS mode locally to **automatic** (`0`) or apply the plant's safe ESS rules.
   - Set the consumer **enables** (`Earnie_*_Freigabe`) to `0` (blocked) or apply known emergency logic.
   - Set the heat pump's **SG Ready state** (`heatpump.<id>.set_sg_ready_state`, suggested Merker `Earnie_Waermepumpe_SG_Ready_Soll`) to `2` (normal operation). The controller then continues with its own setpoints.
   - Set the **storage charge target** (`heatpump.<id>.set_temperature_heat_storage_target`, suggested Merker `Earnie_Waermespeicher_Ladeziel`) to `0` (no target).
   - Stop taking EV setpoints from the Earnie Merker.
4. **When Earnie is reachable again:** Pass the Earnie Merker through to the actuators or the program as intended.

Earnie needs no change for this. The fallback is pure Config logic around the Merker.

### Checklist

- [ ] Meters for consumers and grid on the EFM with unique names
- [ ] Smarthome-Backend: Loxone import run, parameters completed in the Hauskonfigurator
- [ ] Signal contract checked on EHAL-Com (required signals enabled, optional ones chosen)
- [ ] Templates exported on EHAL-Com (host and port checked)
- [ ] `VI_` / `VO_` XMLs copied into the Config template folders, Config restarted
- [ ] Push token placeholder replaced or removed
- [ ] Devices inserted and wired; titles unchanged
- [ ] Program saved to the Miniserver
- [ ] Optional: heartbeat watchdog + fallback programmed

---

## Presence check (for binding and import)

The Default names are **known** (`greenfield_device_map.json`). Earnie checks them against the **LoxAPP3 control names** (`GET /data/LoxAPP3.json`): a signal counts as present if its name appears in `controls`, otherwise as missing. Names that are not visible in the Loxone app, and therefore not contained in LoxAPP3, are not recognized.

The Default import uses the LoxAPP3 names. EFM meters also come from `LoxAPP3.json`.

## Multiple flexible consumers (naming convention)

<a id="multiple-flex-consumers-naming-convention"></a>

Miniserver names must be unique. The `id` in the house profile (lower case, snake_case, e.g. `waschmaschine`) is the canonical **entity slug** (`{hk_id}`).

| Signal   | Merker name (first / further)                                           | VI check / VO path                                  |
| -------- | ----------------------------------------------------------------------- | --------------------------------------------------- |
| Power    | `Earnie_Verbraucher_Leistung` → `Earnie_Verbraucher_<Slug>_Leistung`   | VO: `consumer.{hk_id}.sens_power_act`              |
| Active   | `Earnie_Verbraucher_<Slug>_Aktiv` (ID required)                        | VO: `consumer.{hk_id}.sens_consumer_active` (0/1) |
| Enable   | `Earnie_Verbraucher_Freigabe` → `…_<Slug>_Freigabe`                    | Check: `consumer.{hk_id}.set_enable`               |

**Example washing machine** (`id` = `waschmaschine`):

- Merker name: `Earnie_Verbraucher_Waschmaschine_Leistung`
- VO command on: `/ehal/telemetry/consumer.waschmaschine.sens_power_act/<v.3>`
- VI check (enable): `"consumer.waschmaschine.set_enable":\v` (Cmd title in the template: `consumer_waschmaschine_set_enable`; the Merker is `Earnie_Verbraucher_Waschmaschine_Freigabe`)
- EHAL-Com binding: `consumer.{hk_id}.sens_power_act` → name (for `zaehler_<slug>`: ID without `zaehler_`). Two consumers of one house profile must therefore not be called `zaehler_<slug>` and `<slug>`: they would have the same ID, and Earnie rejects the house profile on load with a message naming both ids.

`<Slug>` **in the Merker:** a short, stable token (e.g. `Waschmaschine`). `{hk_id}`: the same consumer as in the house profile.

## Multiple EVs (naming convention)

Analogous: prefix `Earnie_EAuto_`, entity `id` = `{ev_id}` (e.g. `eauto`, `garage`).

| Signal            | Merker name (first / further)                            | VI check / VO path                         |
| ------------------ | -------------------------------------------------------- | ------------------------------------------ |
| Setpoint A        | `Earnie_EAuto_Soll_A` → `Earnie_EAuto_<Slug>_Soll_A`     | Check: `evcs.{ev_id}.set_evcs_max_current` |
| Mode              | `Earnie_EAuto_Modus` → `…_<Slug>_Modus`                  | Check: `evcs.{ev_id}.set_evcs_mode`        |
| Power             | `Earnie_EAuto_Leistung` → `…_<Slug>_Leistung`            | VO: `evcs.{ev_id}.sens_evcs_active_power`  |
| further sens/get  | `Earnie_EAuto_*` → `…_<Slug>_*`                          | VO `ev.{ev_id}.…` (vehicle values) or `evcs.{ev_id}.…` (charge point values) |

**Heat pump:**

- Merker names: `Earnie_Waermepumpe_Leistung` / `Earnie_Waermepumpe_Freigabe`.
- Storage temperatures: `Earnie_Waermespeicher_Temp_eq` / `Earnie_Waermespeicher_Temp_low`.
- Paths: VO `heatpump.{hk_id}.sens_power_act`, VI check `heatpump.{hk_id}.set_enable` (default `id` `wp_heating`).

**Pool:** VO `pool.{hk_id}.sens_power_act`, VI check `pool.{hk_id}.set_enable`.

**Import:** The Default import matches Default names **case-insensitively**, either exactly or as **prefix + slug**. Examples: `Earnie_Verbraucher_Waschmaschine_Leistung` → consumer `waschmaschine`; `Earnie_EAuto_Garage_Soll_A` → EV `garage`. Bindings keep the Miniserver's spelling.

All configured signals can be checked like this:

```powershell
.venv\Scripts\python.exe -m scripts.verify_loxone_setup
.venv\Scripts\python.exe -m scripts.verify_swimspa_filter_live
```

---

## Role ↔ entity (overview)

| Entity / area                                                            | Stored in                                      | Typical EHAL fields / roles                                                                                                                                  |
| ------------------------------------------------------------------------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Plant (grid, house load, outside temp., absence; ESS power/setpoints via the primary battery)   | `house_profiles.json` → `plant.ehal_bindings` | `sens_ess_power`, `sens_grid_power_active`, `sens_temperature_outside`, `sens_absent_mode`, `sens_power_consumers` (SoC: `batteries[].ehal_bindings` → `ess.{slug}.sens_ess_soc`) |
| Inverter (PV power, AC power, limits)                                    | `components.json` → `inverters[].ehal_bindings` | `inv.{id}.sens_inv_power_pv` (required as soon as PV is connected to the inverter; Merker `Earnie_PV_Leistung`), `inv.{id}.sens_inv_power_ac`. Earnie derives the plant PV power from it. |
| PV array (optional)                                                      | `components.json` → `pv_systems[].ehal_bindings` | `pv.{id}.sens_pv_production_active` (DC power per PV array; replaces a missing value at the inverter only if all arrays on it are mapped) |
| Request Optimize (ad hoc)                                                | Loxone VO → daemon HTTP                        | `Earnie_Request_Optimize` on port `system.ehal_http_port` (default **8541**)                                                                                 |
| Heat pump / flexible / thermal                                           | `consumers[].ehal_bindings`                    | `consumer|heatpump|pool.{slug}.sens_power_act`, `….set_enable`                                                                                               |
| EV (`ev`)                                                                | `consumers[].ehal_bindings`                    | `sens_evcs_*`, `get_evcs_*`, `set_evcs_*`                                                                                                                    |
| Pool                                                                     | `consumers[].ehal_bindings` + filter entity    | see Default `Earnie_Pool_*` / [EHAL-Com, section C.6 Pool](../ui/ehal-com.md#c6-pool--swimspa-stub)                                                         |

In the UI, editing happens **only** under **Daemon Control → EHAL-Com → Signalliste** (and the related mapping sections).

## Core signals (`plant.ehal_bindings`)

Default names. Grid and battery **power** preferably via the EFM meter name. PV power comes per inverter (`inv.{id}.sens_inv_power_pv`, see table above), not via `plant.ehal_bindings`.

| EHAL field                         | Direction | Default name                                     | Value / unit                                                                               |
| ---------------------------------- | --------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| `ess.{slug}.sens_ess_soc`         | Read      | `Earnie_Batterie_SoC` / `Earnie_Batterie_<Slug>_SoC` | Battery SoC, % (per entity; not plant-wide)                                          |
| `sens_ess_power`                  | Read      | `Earnie_Batterie_Leistung` (or EFM storage)      | Battery kW; **+ discharge**, − charge (as in EHAL, no inversion)                            |
| `sens_grid_power_active`          | Read      | `Earnie_Netzleistung` (or EFM grid)              | Grid: + import, kW                                                                          |
| `get_grid_export_power_limit`     | Read      | `Earnie_Netz_Einspeisegrenze_In` (optional)      | Maximum export limit from Loxone, kW (EHAL: W)                                              |
| `get_ess_soc_min`                 | Read      | `Earnie_Batterie_SOC_Min` (optional)             | Discharge cut-off SoC %; used in planning when the battery takes its limits live (`limits_from_live`) |
| `get_ess_soc_max`                 | Read      | `Earnie_Batterie_SOC_Max` (optional)             | Charge cut-off SoC %                                                                        |
| `get_ess_max_charge_power`        | Read      | `Earnie_Batterie_Max_Ladeleistung` (optional)    | Maximum charge power of the device (Loxone kW → EHAL W)                                     |
| `get_ess_max_discharge_power`     | Read      | `Earnie_Batterie_Max_Entladeleistung` (optional) | Maximum discharge power of the device (Loxone kW → EHAL W). Static device values only, **never** feed back `Earnie_EntladeLeistungs-Limit`: a 0 read back blocks the battery permanently |
| `sens_power_consumers`            | Read      | (optional)                                       | House load; otherwise derived                                                               |
| `sens_temperature_outside`        | Read      | `Earnie_Aussentemperatur`                        | Outside temperature °C (house-wide; heat pump/pool)                                         |
| `sens_absent_mode`                | Read      | `Earnie_Abwesend`                                | House absent / holiday mode 0/1 (OR with house profile `absent_mode`)                       |
| `set_ess_active_power`            | Write     | `Earnie_Batterie_Sollleistung`                   | Forced power, kW; `+` discharge, `−` charge                                                 |
| `set_ess_charge_power_limit`      | Write     | `Earnie_LadeLeistungs-Limit`                     | Max. charge power (real limit)                                                              |
| `set_ess_discharge_power_limit`   | Write     | `Earnie_EntladeLeistungs-Limit`                  | Max. discharge power (real limit)                                                           |
| `set_ess_mode`                    | Write     | `Earnie_Steuerbefehl`                            | Sticky: always written; `0` = automatic; battery only; ignored by OpenEMS                   |
| `set_ess_target_soc`              | Write     | `Earnie_Ziel_SOC`                                | Optional, % (0–100): discharge block = actual SoC; force charge/discharge = planned SoC at slot end, plus the buffer when force charging, minus the buffer when force discharging (1 % + ¼ of the slot's planned SoC change); automatic = 99; only if mapped |
| `ess.<id>.set_ess_source_select`  | Write     | `Earnie_Speicher_Quellenwahl` (assign manually to the standby battery) | physical `standby_backup` only; `0` = grid pass-through, `1` = pure battery island operation (capability `supports_ess_source_select`); not at plant level |
| `set_grid_export_power_limit`     | Write     | `Earnie_EinspeiseLeistungs-Limit`                | Max. export kW (magnitude ≥ 0); `0` = no export; unlimited = PV kWp + max. battery discharge kW |
| *(Watchdog)*                       | Read      | `Earnie_Heartbeat`                               | Per entity; no EHAL field                                                                   |

The bindings live in `plant.ehal_bindings` with the EHAL field names above (see [EHAL contract](ehal.md)).

**Sticky Merker.** Loxone keeps the last written value.

- **Automatic mode:** `set_ess_mode = 0` means automatic. In mode 0, Config must not apply the setpoint power, even if `Earnie_Batterie_Sollleistung` still holds a previous value.
- **Export throttling:** `set_grid_export_power_limit`, like the charge/discharge limits, is a non-negative magnitude in kW. Config throttles grid feed-in to `min(limit, inverter power)`. `0` means no export (feed-in block).
- **Unlimited export:** written as the plant maximum, i.e. the PV kWp sum plus the **sum** of the maximum discharge kW of every selected battery that can be force-discharged (`control = full`). If this value is unknown, `1000` kW is written.
- **Multiple ESS:** Merker names use the slug infix `Earnie_Batterie_<Slug>_…`. The per-entity binding keys are `ess.{slug}.sens_ess_soc` / `set_ess_*` in `batteries[].ehal_bindings`.
- **`set_ess_mode`** (`Earnie_Steuerbefehl`) applies to the battery only and never signals export throttling.

## Flexible consumers: `ehal_bindings` on the consumer

The signal definitions are in the active house profile (`house_profiles.json`). The Merker are under `ehal_bindings`, keyed by EHAL field name.

### Flexible / thermal (typed namespaces)

| EHAL field                           | Direction | Default / example                                                                              | Value       |
| ------------------------------------ | --------- | ---------------------------------------------------------------------------------------------- | ----------- |
| `consumer|heatpump|pool.{slug}.sens_power_act` | Read | Heat pump: `Earnie_Waermepumpe_Leistung`; generic: `Earnie_Verbraucher_Leistung`; or EFM load | kW or 0/1 |
| `consumer.{slug}.sens_consumer_active` | Read | Generic: `Earnie_Verbraucher_<Slug>_Aktiv` (digital; OR trigger of the reserve enable)    | `0`/`1`     |
| `consumer|heatpump|pool.{slug}.set_enable` | Write | Heat pump: `Earnie_Waermepumpe_Freigabe`; generic: `Earnie_Verbraucher_Freigabe`     | `0`/`1`     |

> **Note:** Storage and transfer keys are the same: `consumer.` / `heatpump.` / `pool.` by consumer type.

Pool enables: Default `Earnie_Pool_Freigabe` / `Earnie_Pool_Filter_Freigabe` in `ehal_bindings`.

**Heat storage actual values (live):** on the consumer `thermal_annual`:

| EHAL field | Meaning | Default Merker |
| --- | --- | --- |
| `sens_temperature_heat_storage` | Energy equivalent `T_eq` (°C) | `Earnie_Waermespeicher_Temp_eq` |
| `sens_temperature_heat_storage_low` | Lowest immersion sensor `T_low` (°C): hint to switch the heat pump on when the bottom is cold | `Earnie_Waermespeicher_Temp_low` |

For stratified storage, `T_eq` must be the energy-equivalent (volume-weighted) mean, not the top sensor alone. Instructions: [waermespeicher-schichtung-teq.md](../konfiguration/waermespeicher-schichtung-teq.md) (German).

**Heating feedback signals (live, optional, read only):** also on the consumer `thermal_annual`. Wire ID `heatpump.{slug}.<field>`. Meaning and effect: [Rückmeldesignale der Heizung](../konfiguration/flexible-verbraucher.md#haus-wärme-rückmeldesignale) (German).

| EHAL field | Value | Default Merker |
| --- | --- | --- |
| `get_temperature_heat_storage_setpoint` | °C, current storage setpoint of the controller | `Earnie_Waermespeicher_Soll` |
| `get_temperature_heat_storage_tolerance` | K, band below the setpoint without heat demand | `Earnie_Waermespeicher_Toleranz` |
| `get_temperature_heat_storage_max` | °C, highest permitted storage temperature | `Earnie_Waermespeicher_Temp_max` |
| `sens_temperature_heat_storage_top` | °C, top storage sensor | `Earnie_Waermespeicher_Temp_top` |
| `sens_operating_mode` | 0 off, 1 space heating, 2 hot water, 3 defrost, 4 blocked, 5 cooling, 6 fault | `Earnie_Waermepumpe_Betriebsart` |
| `sens_sg_ready_state` | 1–4 | `Earnie_Waermepumpe_SG_Ready` |
| `sens_heat_power` | kW (EHAL: W) | `Earnie_Waermepumpe_Waermeleistung` |
| `sens_temperature_source` | °C, source temperature while running, held while stopped (see below) | `Earnie_Waermepumpe_Temp_Quelle` |
| `sens_temperature_dhw` | °C | `Earnie_Warmwasser_Temp` |
| `get_temperature_dhw_min` | °C | `Earnie_Warmwasser_Temp_min` |
| `sens_temperature_room` | °C | `Earnie_Raum_Temp` |
| `get_temperature_room_setpoint` | °C | `Earnie_Raum_Temp_Soll` |

If setpoint and tolerance are both mapped, live planning uses the controller's storage band instead of `heat_storage.setpoint_c` / `tolerance_c`.

**Holding the source temperature:** The sensor in the brine or groundwater circuit shows the source only while the heat pump is running. `Earnie_Waermepumpe_Temp_Quelle` therefore does not get the raw sensor but a held value. Setup in Loxone Config:

1. **Running:** electrical power of the heat pump above a threshold (threshold switch), not the controller's demand.
2. **Settling time:** on-delay on "Running" (a few minutes, read from the plant's curves). Only after that does the sensor value count.
3. **Form the value:** mean of the sensor while "Running" is active after the settling time. Simpler variant: the current sensor value.
4. **Hold:** On the falling edge of "Running", take the value into an analog memory and hold it until the next valid run. The Merker sends the held value.

Earnie does not filter the value itself.

### EV (prefix `Earnie_EAuto_`)

| EHAL field                     | Direction | Default name                                                     | Value                                                                                                                                       |
| ------------------------------ | --------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `sens_evcs_active_power`       | Read      | `Earnie_EAuto_Leistung` (or EFM load)                            | kW                                                                                                                                          |
| `sens_evcs_connected`          | Read      | `Earnie_EAuto_Angeschlossen`                                     | `1` = connected                                                                                                                             |
| `sens_evcs_soc_act`            | Read      | `Earnie_EAuto_SOC`                                               | Current SOC, %                                                                                                                              |
| `sens_evcs_bat_capacity`       | Read      | `Earnie_EAuto_Kapazitaet`                                        | kWh                                                                                                                                         |
| `get_evcs_nominal_current`     | Read      | `Earnie_EAuto_MaxStrom`                                          | A                                                                                                                                           |
| `get_evcs_ready_by_time`       | Read      | AlarmClock name (e.g. `Ladewecker`); VO title `Push_ev_<id>_get_evcs_ready_by_time` | Push inbox: numeric analog VO value for the next entry preferred; Tna text (`Morgen, 07:00`) is accepted while it is fresh and parsed by the optimizer. |
| `get_evcs_limit_soc`           | Read      | `Earnie_EAuto_LimitSOC`                                          | Target charge SOC %                                                                                                                         |
| `get_evcs_soc_min_immediate`   | Read      | `Earnie_EAuto_SOCMinSofort`                                      | Immediate minimum SOC %; ≤0 or empty = inactive; capped at the limit SOC                                                                    |
| `set_evcs_max_current`         | Write     | `Earnie_EAuto_Soll_A`                                            | Setpoint/maximum current A                                                                                                                  |
| `set_evcs_mode`                | Write     | `Earnie_EAuto_Modus`                                             | `off`=0 / `pv`=1 / `now`=2                                                                                                                  |

Notes:

- The EV also needs the charge current `min_current_a` and `max_current_a` (see [E-Auto und Wallbox](../konfiguration/flexible-verbraucher.md#e-auto-und-wallbox-ladestrom) (German)).
- The **EV mode** is written only via `set_evcs_mode` (`Earnie_EAuto_Modus`). Earnie writes neither `pv_follow` nor immediate-command Merker.
- **Pool filter:** The house profile consumer `pool_filter` carries its EHAL roles (including `get_filter_remaining_hours`) under `ehal_bindings`. Default prefix: `Earnie_Pool_*` / `Earnie_Pool_Filter_*` (see [EHAL-Com, section C.6 Pool](../ui/ehal-com.md#c6-pool--swimspa-stub)).

<a id="request-optimize"></a>

## Request Optimize (ad hoc runs)

Ad hoc optimization runs of the optimizer service (between the quarter hours) are triggered via HTTP from Loxone to Earnie.

| Element                            | Meaning                                                                                        |
| ---------------------------------- | ---------------------------------------------------------------------------------------------- |
| Virtual Out                        | `VO_Earnie_Status.xml` from the export (always included)                                       |
| Address                            | `http://EARNIE_HOST:8541` (port = `system.ehal_http_port`, default **8541**)                   |
| Cmd `Earnie_Request_Optimize`      | Command on `/ehal/loxone/request_optimize` (`POST`, without push token). Connect the output to the trigger in Loxone, e.g. a push button or logic on a tariff or load change. Wakes the optimizer service before the next quarter hour; receive ID `request_optimize` in EHAL-Com **Signalliste** and **Live Read** |

The connection proof (hub → Earnie) is the repeating telemetry VO **`Push_Earnie_Heartbeat`** → `GET /ehal/telemetry/heartbeat_smarthome/<v>` from `VO_Earnie_Heartbeat.xml`.

Compose production stacks publish container port **8541** (see [Streamlit ports](../dev/streamlit-ports.md) (developer docs)).

## Example mapping

| Consumer (`id`)     | Control (write)                                                | Power (read)                                                         |
| ------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------- |
| `pool` / Pool       | `pool.{slug}.set_enable` → `Earnie_Pool_Freigabe`              | `pool.{slug}.sens_power_act` → `Earnie_Pool_P_act`                  |
| `ev`                | `evcs.{slug}.set_evcs_max_current` / `set_evcs_mode`           | `evcs.{slug}.sens_evcs_active_power`                                 |
| `wp_heating`        | `heatpump.{slug}.set_enable` → `Earnie_Waermepumpe_Freigabe`   | `heatpump.{slug}.sens_power_act` → `Earnie_Waermepumpe_Leistung`; `sens_temperature_heat_storage` / `_low` → `Earnie_Waermespeicher_Temp_eq` / `_low` |

## Reading and writing in the optimizer service

| Phase         | Action                                                       |
| ------------- | ------------------------------------------------------------ |
| Read          | SOC, power values, PV, flexible consumer inputs, EV status   |
| Optimization  | Optimization over the planning horizon (quarter hours)       |
| Write         | ESS limits / mode, enables / EV current per 15-min write cycle |

The app **reads** the same live values for display; it **writes** control values only in live mode. Merker mapping: [EHAL-Com](../ui/ehal-com.md).

Further details: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md) (German) · [Abbreviations](abbreviations.md).
