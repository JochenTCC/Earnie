# Loxone Signals and the Earnie Library

## Motivation

This page is the **one** user reference for Earnie's Loxone integration:

1. **Library setup** — installing the Virtual-HTTP-In/Out templates from `share/loxone/templates/` in Loxone Config, EFM meters, the Earnie dead-man fallback, and the Loxone import into the house profile.
2. **Signal contract** — which Merker **titles** and EHAL roles (`ehal_bindings`) belong together (default names from `greenfield_device_map.json` / recipes).

Without stable titles and bindings, Earnie can neither reliably read nor control the plant. HTTP access and operation: [Loxone Integration](../einrichtung/loxone-anbindung.md). Mapping UI: [EHAL-Com](../ui/ehal-com.md). Templates README: [`share/loxone/templates/README.md`](../../share/loxone/templates/README.md).

**Terminology (Smarthome Merker):** The **address** (a string, e.g. `Earnie_Waermepumpe_Freigabe`) is a *Smarthome Merker*. The **role** is the EHAL field name (`sens_ess_soc`, `flex.{slug}.sens_power_act`, …) in `ehal_bindings`. Don't confuse this with chart markers or `earnie_role` (Known/Controlled/Manual).

In the docs, the canonical template/import path is called **Default** (formerly often "Greenfield"). The file `share/loxone/greenfield_device_map.json` keeps its filename.

---

## Pattern B Overview

| Direction        | Building block                          | Role                                                                        |
| ----------------- | --------------------------------------- | --------------------------------------------------------------------------- |
| Earnie → Loxone | **Virtual HTTP In** (`VI_Earnie_*.xml`) | Earnie polls status/setpoints/enables into **named Merker** (`Earnie_`*)   |
| Loxone → Earnie | **Virtual Out** (`VO_Earnie_*.xml`)     | optional push (telemetry); Core still reads `/jdev/sps/io/{Name}`          |
| Meter          | EFM / Meter                             | grid/PV/battery/flex **power** preferably via the EFM designation          |


Earnie Core writes and reads the same Merker names on the Miniserver. The library adds the **Loxone-side** HTTP mirroring and enables an **Earnie-dead** fallback in Config (see below).

**Virtual Inputs** = Earnie→Loxone (`set_*` / enables / setpoints, heartbeat) via `GET http://<Earnie>:8541/ehal/loxone/status.json` (daemon HTTP; `heartbeat_ts` = Unix now, setpoints from the last `loxone_sent`).

**Virtual Outputs** = optional Loxone→Earnie push of `sens_*` / `get_*` / flex power (placeholder URLs). Core still writes/reads `/jdev/sps/io/{name}`.

**Enable Cmds (0/1) must be analog:** the VI templates have `Analog="true"` set. In Config, do **not** select "as digital input" / digital mode — otherwise the input briefly pulses to `1` on **every** poll, even when `status.json` permanently returns `0`. Sticky 0/1 only comes from the `\v` value in analog mode.

### Three Layers (Title / Check / VO Path)


| Layer                                  | Where                     | Flex example                                             | EV example                                                |
| --------------------------------------- | -------------------------- | --------------------------------------------------------- | ------------------------------------------------------------ |
| **Miniserver title**                   | Cmd title (jdev / import) | `Earnie_Verbraucher_Waschmaschine_Freigabe`               | `Earnie_EAuto_Garage_Soll_A`                                |
| **Virtual-Input check / status JSON**  | Virtual In check pattern  | `flex.{hk_id}.Earnie_Verbraucher_Freigabe`                | `ev.{ev_id}.Earnie_EAuto_Soll_A`                            |
| **Virtual-Output command when on**     | Virtual Out URL           | `/ehal/loxone/telemetry/flex.{hk_id}.sens_power_act/\v`   | `/ehal/loxone/telemetry/ev.{ev_id}.sens_evcs_soc_act/\v`    |


`{hk_id}` / `{ev_id}` = house profile entity `id` (snake_case). Templates leave the placeholders in place — replace them in Config.

---

## Library Setup

<a id="library-setup"></a>

After installing them in Loxone Config, the **Loxone import** on [EHAL-Com](../ui/ehal-com.md) / in the house configurator produces typed house-profile entities and Merker bindings.

### 1. Copy Templates into Loxone Config

Copy only the `.xml` files (not `README.md`, and don't nest a whole folder tree as a subfolder).

#### VirtualIn

Source: `share/loxone/templates/VirtualIn/`


| File                      | Content (short)                     |
| ------------------------- | ------------------------------------ |
| `VI_Earnie_Plant.xml`     | Heartbeat + ESS design-C1 setpoints |
| `VI_Earnie_Heatpump.xml`  | `Earnie_Waermepumpe_Freigabe`       |
| `VI_Earnie_EV.xml`        | EV target current / mode            |
| `VI_Earnie_Consumer.xml`  | generic enable + target_kW          |
| `VI_Earnie_Pool.xml`      | pool / filter enable                |


Target folder (one of the existing Config paths; create the folder if needed):

- `%ProgramData%\Loxone\Loxone Config\<Version>\Template\VirtualIn\`
- or `Documents\Loxone\Loxone Config\Templates\VirtualIn\`

#### VirtualOut

Source: `share/loxone/templates/VirtualOut/`


| File                      | Content (short)                                             |
| ------------------------- | ------------------------------------------------------------ |
| `VO_Earnie_Status.xml`    | optional alive / `Earnie_Request_Optimize` (port **8541**)  |
| `VO_Earnie_Plant.xml`     | plant `sens_*`, outside temperature                         |
| `VO_Earnie_EV.xml`        | EV telemetry                                                 |
| `VO_Earnie_Heatpump.xml`  | `Earnie_Waermepumpe_Leistung`                                |
| `VO_Earnie_Consumer.xml`  | flex power                                                   |
| `VO_Earnie_Pool.xml`      | pool telemetry                                                |


Target: the corresponding `VirtualOut` folder.

Then **restart Loxone Config**. The templates appear under Peripherals / Device Templates (Virtual In / Virtual Out).

### 2. Set the Earnie Address

In every inserted Virtual In/Out, replace the `EARNIE_HOST` placeholder with Earnie's LAN IP or hostname. UI/Streamlit typically uses port **8501**; the **daemon HTTP** (Virtual In status, `Earnie_Request_Optimize` / alive) uses port **8541** (`system.ehal_loxone_http_port`). See [Streamlit Ports](streamlit-ports.md).

Example Virtual In address (Pattern B status JSON):

`http://192.168.178.10:8541/ehal/loxone/status.json`

Virtual Out address **status / request optimize**:

`http://192.168.178.10:8541`

Other telemetry VO drafts may still carry `:8501` as a placeholder until those endpoints exist.

Adjust the polling / Cmd check pattern to match the JSON keys (plant: `set_ess_*` / `heartbeat_ts`; flex/EV: `flex.{hk_id}.…` / `ev.{ev_id}.…`). Stable **titles** remain the contract for Core and the default import.

### 3. Insert Devices and Keep the Merker Names

1. Insert the matching template once per role (or multiple times for multiple flex consumers).
2. Do not rename Cmd **titles** arbitrarily — they must match [`greenfield_device_map.json`](../../share/loxone/greenfield_device_map.json) and the tables below.
3. **Multiple flex consumers / EVs:** titles follow a prefix + instance-ID scheme; the VI check and VO path use `{hk_id}` / `{ev_id}` (see [naming convention](#multiple-flex-consumers-naming-convention)).
4. Save/load the program on the Miniserver.

### 4. Meters and Energy Flow Monitor (EFM)

The templates contain **no** meter hardware. Still, meter blocks in use are also imported. For that to work, in Loxone Config:

1. Create or keep a meter with a **unique, stable designation**.
2. Assign the meter to the **Energy Flow Monitor** (grid / PV / battery / loads).
3. Don't use residual/remainder nodes as a separate flex consumer (the import skips typical remainder labels).

Power Merker (`Earnie_Netzleistung`, `Earnie_PV_Leistung`, …) **may** come from the EFM; the Virtual Output Cmds remain an optional name catalog. Earnie prefers the EFM designation in the binding when available.

Manual follow-up: EHAL-Com → **Energy Flow Monitor → Consumers**.

**EV ready-by time:** the Loxone import binds **AlarmClock** blocks to `get_evcs_ready_by_time` on the EV entity that already has meter/power bindings — same convention as the meter designation, no Virtual-Out text.

Earnie reads **SpecialState10** (`nextEntryTime`) via `/jdev/sps/io/{name}/all` (Unix = value + 1230768000); output **Tna** remains a text backup.

### 5. Earnie Dead-Man Fallback (in Loxone Config)

<a id="earnie-dead-fallback-in-loxone-config"></a>

Goal: if Earnie is unreachable or the Virtual In is no longer being updated, the Miniserver must **ignore** Earnie's last setpoints and run local rules instead.

Recommended approach (logic blocks in Config, no Earnie code):

1. **Watchdog** on `Earnie_Heartbeat` (Unix timestamp from `VI_Earnie_Plant`): age = now − heartbeat (or "value unchanged for x seconds").
2. Choose a threshold (e.g. 2–3× the Virtual In polling time, typically ≥ 90 s at a 30 s poll).
3. When the **dead-man fallback is triggered**:
   - Set `Earnie_Steuerbefehl` / ESS mode locally to **automatic** (`0`) or the plant's safe ESS rules
   - Set flex **enables** (`Earnie_*_Freigabe`) to `0` (blocked) or known emergency logic
   - Stop taking EV setpoints from the Earnie Merker
4. When **Earnie is "alive"**: pass the Earnie Merker through to actuators/program as intended.

Earnie Core stays unchanged on the Miniserver IOs; the fallback is **only** Config logic around the Merker.

### 6. Loxone Import into Earnie

Prerequisite: Earnie templates are installed in Loxone Config and each consumer has a meter block (EFM); credentials are entered on **Smarthome-Backend → Anbindung**. The import button only becomes active once the Miniserver is reachable.

1. **Daemon Control → Smarthome-Backend**: once Loxone is connected, the **Loxone Import** section appears below the connection summary — on first setup, **No — continue manually** is shown on the same row as the import button.
2. Earnie loads `LoxAPP3.json`, probes `Earnie_*` via HTTP (also prefix+slug, case-insensitive), creates typed entities, and binds in EFM meters.
3. Check the signal mapping on **EHAL-Com** ([Loxone Structure → EHAL Mapping](../ui/ehal-com.md#loxone-structure--ehal-mapping)); follow up on parameters (kWh, schedules, living area, …) in the **House Configurator**.

### Library Checklist

- [ ] `VI_` / `VO_` XMLs copied into the Config template folders, Config restarted
- [ ] `EARNIE_HOST` set; devices inserted; titles stable
- [ ] Multiple consumers / EVs: slug titles + check/VO `{hk_id}` / `{ev_id}` (if used)
- [ ] Meters on the EFM with unique designations
- [ ] Program saved on the Miniserver
- [ ] Optional: heartbeat watchdog + fallback programmed
- [ ] Smarthome-Backend: Loxone import → check mapping on EHAL-Com → parameters in the house profile

---

## HTTP Marker Probe (for Binding and Import)

The template Cmd titles are **known** (`greenfield_device_map.json`). Earnie can check them via `GET /jdev/sps/io/{Name}` **without** the blocks needing to be present in the Loxone app visualization:


| `LL.Code` | Meaning for the import                                                                                    |
| --------- | ----------------------------------------------------------------------------------------------------------- |
| `200`     | name present and readable                                                                                    |
| `403`     | name known on the Miniserver, not readable for the user (common with Virtual HTTP In) — counts as **present** |
| `404`     | name unknown / not uploaded                                                                                   |


Default import: LoxAPP3 names **union** probe hits. EFM meters still come from `LoxAPP3.json`.

## Multiple Flex Consumers (Naming Convention)

<a id="multiple-flex-consumers-naming-convention"></a>

One template `VI_Earnie_Consumer` / `VO_Earnie_Consumer` covers **one** consumer. Miniserver designations must be unique. The house-profile `id` (lowercase, snake_case, e.g. `waschmaschine`) is the canonical **entity slug** (`{hk_id}`).


| Signal   | Merker title (1st / additional)                                       | VI check / VO path                                |
| -------- | ----------------------------------------------------------------------- | --------------------------------------------------- |
| Power    | `Earnie_Verbraucher_Leistung` → `Earnie_Verbraucher_<Slug>_Leistung`   | VO: `flex.{hk_id}.sens_power_act`                  |
| Enable   | `Earnie_Verbraucher_Freigabe` → `…_<Slug>_Freigabe`                    | Check: `flex.{hk_id}.Earnie_Verbraucher_Freigabe`  |
| Target kW| `Earnie_Verbraucher_Ziel_kW` → `…_<Slug>_Ziel_kW`                      | Check: `flex.{hk_id}.Earnie_Verbraucher_Ziel_kW`   |


**Example washing machine** (`id` = `waschmaschine`):

- Title: `Earnie_Verbraucher_Waschmaschine_Leistung`
- VO command when on: `/ehal/loxone/telemetry/flex.waschmaschine.sens_power_act/\v`
- VI check (enable): `"flex.waschmaschine.Earnie_Verbraucher_Freigabe":\v` (title stays `Earnie_Verbraucher_Waschmaschine_Freigabe`)
- EHAL-Com binding: `flex.{hk_id}.sens_power_act` → title (for `zaehler_<slug>`: wire slug without `zaehler_`)

`<Slug>` **in the Merker:** short, stable token (e.g. `Waschmaschine`). `{hk_id}`: same consumer as in the house profile.

## Multiple EVs (Naming Convention)

Analogous: prefix `Earnie_EAuto_`, entity `id` = `{ev_id}` (e.g. `eauto`, `garage`).


| Signal            | Merker title (1st / additional)                       | VI check / VO path                       |
| ------------------ | -------------------------------------------------------- | ------------------------------------------ |
| Target A          | `Earnie_EAuto_Soll_A` → `Earnie_EAuto_<Slug>_Soll_A`     | Check: `ev.{ev_id}.Earnie_EAuto_Soll_A`   |
| Mode              | `Earnie_EAuto_Modus` → `…_<Slug>_Modus`                  | Check: `ev.{ev_id}.Earnie_EAuto_Modus`    |
| Power             | `Earnie_EAuto_Leistung` → `…_<Slug>_Leistung`            | VO: `ev.{ev_id}.sens_evcs_active_power`   |
| additional sens/get | `Earnie_EAuto_*` → `…_<Slug>_*`                         | VO: `ev.{ev_id}.<ehal_field>`             |


Heat pump: titles `Earnie_Waermepumpe_Leistung` / `Earnie_Waermepumpe_Freigabe`; VO/check with `flex.{hk_id}` (default `id` `wp_heating`). Pool: `flex.pool.sens_power_act` resp. `{hk_id}`.

**Import:** the default matches **case-insensitive** exact template names and **prefix+slug** (e.g. `Earnie_Verbraucher_Waschmaschine_Leistung` → consumer `waschmaschine`; `Earnie_EAuto_Garage_Soll_A` → EV `garage`). Bindings keep the Miniserver spelling.

In Config: insert template → set Cmd titles + VO path `{id}` → save to the Miniserver.

Checking all configured signals:

```powershell
.venv\Scripts\python.exe -m scripts.verify_loxone_setup
.venv\Scripts\python.exe -m scripts.verify_swimspa_filter_live
```

---

## Role ↔ Entity (Overview)


| Entity / area                                                          | Storage location                              | Typical EHAL fields / roles                                                                                                                               |
| ------------------------------------------------------------------------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Plant (battery, PV, grid, control command, house load, outside temp.)   | `house_profiles.json` → `plant.ehal_bindings` | `sens_ess_soc`, `sens_pv_production_active`, `sens_ess_power`, `sens_grid_power_active`, `sens_temperature_outside`, `sens_power_consumers`, `set_ess_*` |
| Request Optimize (ad hoc)                                               | Loxone VO → daemon HTTP                       | `Earnie_Request_Optimize` on port `system.ehal_loxone_http_port` (default **8541**)                                                                       |
| Heat pump / Flex / Thermal                                              | `consumers[].ehal_bindings`                   | `flex.{slug}.sens_power_act`, `flex.{slug}.set_enable`, `flex.{slug}.set_power_setpoint`                                                                  |
| EV (`ev`)                                                                | `consumers[].ehal_bindings`                   | `sens_evcs_*`, `get_evcs_*`, `set_evcs_*`                                                                                                                  |
| Pool / SwimSpa                                                           | `consumers[].ehal_bindings` + filter entity   | see default `Earnie_Pool_*` / EHAL-Com §C.6                                                                                                                |


Editing in the UI: **only** under **Daemon Control → EHAL-Com → Loxone Structure → EHAL Mapping** (choose an entity). The House Configurator no longer edits Merker addresses.

## Core Signals (`plant.ehal_bindings`)

Default names (2.4.n). Grid/PV/battery **power** preferably via the EFM meter designation.


| EHAL field                       | Direction | Default name                                   | Value / unit                                                                            |
| ---------------------------------- | --------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| `sens_ess_soc`                    | Read      | `Earnie_Batterie_SoC`                            | Battery SoC, %                                                                             |
| `sens_pv_production_active`       | Read      | `Earnie_PV_Leistung` (or EFM production)         | PV power, kW                                                                                |
| `sens_ess_power`                  | Read      | `Earnie_Batterie_Leistung` (or EFM storage)      | Battery; EHAL: + discharge                                                                  |
| `sens_grid_power_active`          | Read      | `Earnie_Netzleistung` (or EFM grid)              | Grid: + import, kW                                                                          |
| `sens_power_consumers`            | Read      | (optional)                                        | House load; otherwise derived                                                               |
| `sens_temperature_outside`        | Read      | `Earnie_Aussentemperatur`                        | Outside temperature °C (house-wide; heat pump/pool)                                        |
| `set_ess_active_power`            | Write     | `Earnie_Batterie_Sollleistung`                   | Forced power, kW; `+` discharge, `−` charge                                                 |
| `set_ess_charge_power_limit`      | Write     | `Earnie_LadeLeistungs-Limit`                     | Max. charge power (true limit)                                                              |
| `set_ess_discharge_power_limit`   | Write     | `Earnie_EntladeLeistungs-Limit`                  | Max. discharge power (true limit)                                                           |
| `set_ess_mode`                    | Write     | `Earnie_Steuerbefehl`                            | Sticky: always write; `0` = automatic (ignore setpoint power); OpenEMS ignores it           |
| *(watchdog)*                       | Read      | `Earnie_Heartbeat`                               | Pattern B; not an EHAL field                                                                |


Legacy role names (`soc_name`, `pv_power_name`, …) in `loxone_blocks` have been removed — only `plant.ehal_bindings` with §C field names.

**Sticky Merker:** Loxone keeps the last written value. Automatic is `set_ess_mode = 0` — Config must not apply the setpoint power in mode 0, even if `Earnie_Batterie_Sollleistung` still holds an old value.

## Flexible Consumers — `ehal_bindings` on the Consumer

The control signal definitions live in the active house profile (`house_profiles.json`). Merker are under `ehal_bindings` with EHAL field names. Existing profiles without bindings: `python -m scripts.migrate_ehal_bindings --path <house_profiles.json> [--config <config.json>]`.

### Flex / Thermal (Stub `flex.*`)


| EHAL field                        | Direction | Default / example                                                                          | Value       |
| ------------------------------------ | --------- | ---------------------------------------------------------------------------------------------- | ------------ |
| `flex.{slug}.sens_power_act`       | Read      | Heat pump: `Earnie_Waermepumpe_Leistung`; generic: `Earnie_Verbraucher_Leistung`; or EFM load  | kW or 0/1   |
| `flex.{slug}.set_enable`           | Write     | Heat pump: `Earnie_Waermepumpe_Freigabe`; generic: `Earnie_Verbraucher_Freigabe`               | `0`/`1`     |
| `flex.{slug}.set_power_setpoint`   | Write     | `Earnie_Verbraucher_Ziel_kW` (optional)                                                        | kW setpoint |


Pool enables: default `Earnie_Pool_Freigabe` / `Earnie_Pool_Filter_Freigabe` in `ehal_bindings`.

### EV (Prefix `Earnie_EAuto_`)


| EHAL field                  | Direction | Default name                                                                                            | Value                                                                                                                                                                                                              |
| ------------------------------ | --------- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sens_evcs_active_power`     | Read      | `Earnie_EAuto_Leistung` (or EFM load; dual `flex.{slug}.sens_power_act`)                                   | kW                                                                                                                                                                                                                  |
| `sens_evcs_connected`        | Read      | `Earnie_EAuto_Angeschlossen`                                                                                | `1` = connected                                                                                                                                                                                                    |
| `sens_evcs_soc_act`          | Read      | `Earnie_EAuto_SOC`                                                                                          | Current SOC, %                                                                                                                                                                                                    |
| `sens_evcs_bat_capacity`     | Read      | `Earnie_EAuto_Kapazitaet`                                                                                   | kWh                                                                                                                                                                                                                |
| `get_evcs_nominal_current`   | Read      | `Earnie_EAuto_MaxStrom`                                                                                     | A                                                                                                                                                                                                                  |
| `get_evcs_ready_by_time`     | Read      | AlarmClock **designation** (e.g. `Ladewecker` / `Wecker_Smart`; import merges onto the EV with the meter) | **SpecialState10** (`nextEntryTime`, Loxone seconds since 2009-01-01 → Unix `+ 1230768000`) via `/jdev/sps/io/{name}/all`. Backup: output **Tna** (text, e.g. `Morgen, 11:00`). No Virtual-Out string.          |
| `get_evcs_limit_soc`         | Read      | `Earnie_EAuto_LimitSOC`                                                                                     | Target charge SOC %                                                                                                                                                                                               |
| `get_evcs_soc_min_immediate` | Read      | `Earnie_EAuto_SOCMinSofort`                                                                                 | ASAP minimum SOC %; ≤0 or empty = inactive; capped at the limit SOC                                                                                                                                               |
| `set_evcs_max_current`       | Write     | `Earnie_EAuto_Soll_A`                                                                                       | Target/max current A                                                                                                                                                                                              |
| `set_evcs_mode`              | Write     | `Earnie_EAuto_Modus`                                                                                        | `off`=0                                                                                                                                                                                                            |


Also required field `min_power_kw` on the consumer. Pool filter: house-profile consumer `pool_filter` with EHAL roles (`get_filter_remaining_hours` among others) under `ehal_bindings`. Default prefix `Earnie_Pool_*` / `Earnie_Pool_Filter_*` (see [ehal-com.md](../ui/ehal-com.md) §C.6). EV mode: only `set_evcs_mode` (`Earnie_EAuto_Modus`) — no writing of `pv_follow` / immediate command Merker.

## Request Optimize (Ad Hoc Runs)

Ad hoc optimization runs in `main.py` (between quarter hours) via Loxone → Earnie HTTP.


| Element                          | Meaning                                                                                    |
| ----------------------------------- | ---------------------------------------------------------------------------------------------- |
| Virtual Out                        | template `share/loxone/templates/VirtualOut/VO_Earnie_Status.xml`                             |
| Address                            | `http://EARNIE_HOST:8541` (port = `system.ehal_loxone_http_port`, default **8541**)           |
| Cmd `Earnie_Request_Optimize`      | `POST /ehal/loxone/request_optimize` — wakes the daemon before the next quarter hour          |
| Cmd `Earnie_Push_Alive` / Alive    | `GET /ehal/loxone/alive` — reachability check                                                  |


Compose production stacks publish container port **8541** (see [Streamlit Ports](streamlit-ports.md)).

## Example Mapping


| Consumer (`id`)   | Control (write)                                            | Power (read)                                                    |
| ------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------- |
| `swimspa` / pool    | `flex.{slug}.set_enable` → `Earnie_Pool_Freigabe`              | `flex.{slug}.sens_power_act` → `Earnie_Pool_P_act`                  |
| `ev`                | `set_evcs_max_current` / `set_evcs_mode`                       | `sens_evcs_*` / `flex.{slug}.sens_power_act`                        |
| `wp_heating`        | `flex.{slug}.set_enable` → `Earnie_Waermepumpe_Freigabe`       | `flex.{slug}.sens_power_act` → `Earnie_Waermepumpe_Leistung`        |


## Reading vs. Writing in `main.py`


| Phase        | Action                                             |
| ------------- | ---------------------------------------------------- |
| Read in      | SOC, powers, PV, flex inputs, EV status              |
| Optimization | MILP over the planning horizon (15-min slots; `dt_h = 0.25`) |
| Write        | ESS limits / mode, enables / EV current per 15-min write cycle |


The app **reads** the same live values for display; it only **writes** control values in live mode. Merker mapping: [EHAL-Com](../ui/ehal-com.md).

Further details: [Loxone Integration](../einrichtung/loxone-anbindung.md) · [Abbreviations](abbreviations.md).
