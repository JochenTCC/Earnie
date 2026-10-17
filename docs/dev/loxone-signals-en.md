> **Note:** English reference copy. The German user doc [docs/referenz/loxone-signals.md](../referenz/loxone-signals.md) is authoritative for end users; keep both in sync when facts change.

# Loxone Signals and the Earnie Library

## Motivation

This page is the single reference for Earnie's Loxone integration. It covers two topics:

1. **Library setup:** installing the Virtual HTTP In/Out templates from `share/loxone/templates/` in Loxone Config, EFM meters, the Earnie dead-man fallback, and the Loxone import into the house profile.
2. **Signal contract:** which Merker **titles** and EHAL roles (`ehal_bindings`) belong together (default names from `greenfield_device_map.json` and the recipes).

Without stable titles and bindings, Earnie can neither read nor control the plant reliably. Related pages:

- HTTP access and operation: [Loxone Integration](../einrichtung/loxone-anbindung.md)
- Mapping UI: [EHAL-Com](../ui/ehal-com.md)
- Template files and generators: [`share/loxone/templates/README.md`](../../share/loxone/templates/README.md)

**Terminology (Smarthome Merker):** The **address** (a string, e.g. `Earnie_Waermepumpe_Freigabe`) is a *Smarthome Merker*. The **role** is the EHAL field name (`sens_ess_soc`, `flex.{slug}.sens_power_act`, …) in `ehal_bindings`. Do not confuse a Merker with chart markers or with `earnie_role` (Known/Controlled/Manual).

This page calls the canonical template/import path **Default** (formerly often "Greenfield"). The file `share/loxone/greenfield_device_map.json` keeps its filename.

---

<a id="entity-scoped-overview"></a>

## Overview

| Direction       | Building block                          | Role                                                                                              |
| --------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Earnie → Loxone | **Virtual HTTP In** (`VI_Earnie_*.xml`) | Loxone polls Earnie's `status.json`; setpoints, enables and heartbeat land in the named VI Cmds (`Earnie_*`) |
| Loxone → Earnie | **Virtual Out** (`VO_Earnie_*.xml`)     | Loxone pushes telemetry into the Earnie inbox (qualified EHAL ID); no Merker poll for bound `sens_*` / `get_*` |
| Meter           | EFM / Meter                             | Grid, PV, battery and flex **power**, preferably via the EFM designation                          |

The library adds the **Loxone-side** HTTP mirroring and an **Earnie-dead** fallback in Config (see [Earnie Dead-Man Fallback](#earnie-dead-fallback-in-loxone-config)).

**Virtual Inputs (Earnie → Loxone):** Setpoints, enables and the heartbeat are served by the daemon via `GET http://<Earnie>:8541/ehal/loxone/status.json`. `heartbeat_ts` is the current Unix time; setpoints come from the publish ledger (`loxone_sent`). Writes are **push-only**: Earnie does not call `/dev/sps/io/<Merker>/<value>` for cycle setpoints. `status.json` publishes qualified Check keys only.

**Virtual Outputs (Loxone → Earnie):** Loxone pushes `sens_*` / `get_*` / flex power under qualified path IDs. Core reads those fields from the push inbox.

**Enable Cmds (0/1) must be analog.** The VI templates set `Analog="true"`. Do **not** select "as digital input" / digital mode in Config. In digital mode the input briefly pulses to `1` on **every** poll, even when `status.json` permanently returns `0`. A sticky 0/1 only results from the `\v` value in analog mode.

### Three Layers (Title / Check / VO Path)


| Layer                                  | Where                     | Flex example                                             | EV example                                                |
| --------------------------------------- | -------------------------- | --------------------------------------------------------- | ------------------------------------------------------------ |
| **Miniserver title**                   | Cmd title (jdev / import) | `Earnie_Verbraucher_Waschmaschine_Freigabe`               | `Earnie_EAuto_Garage_Soll_A`                                |
| **Virtual-Input check / status JSON**  | Virtual In check pattern  | `consumer.{hk_id}.set_enable` (heatpump/pool: `heatpump.` / `pool.`) | `evcs.{ev_id}.set_evcs_max_current` / `set_evcs_mode` |
| **Virtual-Output command when on**     | Virtual Out URL           | `/ehal/telemetry/flex.{hk_id}.sens_power_act/<v>`   | `/ehal/telemetry/ev.{ev_id}.sens_evcs_soc_act/<v>`    |


`{hk_id}` / `{ev_id}` is the house-profile entity `id` (snake_case). The templates leave the placeholders in place; replace them in Config.

**Qualified Checks only.** `status.json` publishes qualified EHAL IDs:

- `consumer.{slug}.set_enable`, `heatpump.{slug}.set_enable`, `pool.{slug}.set_enable`
- `evcs.{slug}.set_evcs_max_current` / `set_evcs_mode`
- plant ESS keys (bare) and `grid.meter.*`, including the write `grid.meter.set_grid_export_power_limit`
- powerstation `ess.{id}.set_*`

Legacy Merker Check keys are no longer emitted alongside the qualified ones, so VI templates must use the qualified keys (`VI_Earnie_*_v2.xml` or Pilot VI). Plant bindings stay bare (`plant.ehal_bindings.set_grid_export_power_limit`).

**VI v2 and Pilot templates.** The library templates `VI_Earnie_*_v2.xml` use the qualified Check keys (titles = ID / field name; placeholders `{hk_id}` / `{ev_id}`). For a live config with real Kennungen, generate Pilot templates:

```powershell
python -m scripts.pilot_vi_template_gen --config-dir … --host … --out-dir …   # → VI_Pilot_*.xml
python -m scripts.pilot_vo_template_gen --config-dir … --host … --out-dir …   # → VO_Pilot_*.xml
```

VO Pilot titles derive from the qualified ID (`Push_<id>`, dots replaced by `_`). Further options: [`share/loxone/templates/README.md`](../../share/loxone/templates/README.md). Write cutover steps: [`docs/ui/ehal-com.md`](../ui/ehal-com.md) § Write push-only.

---

## Library Setup

<a id="library-setup"></a>

Once the templates are installed in Loxone Config, the **Loxone import** (see [step 6](#6-loxone-import-into-earnie)) produces typed house-profile entities and Merker bindings.

### 1. Copy Templates into Loxone Config

Copy only the `.xml` files into the template folders. Do not copy `README.md`, and do not nest a whole folder tree as a subfolder.

#### VirtualIn

Source: `share/loxone/templates/VirtualIn/`


| File | Content (short) |
| ---- | --------------- |
| `VI_Earnie_Plant_v2.xml` | Heartbeat + ESS (field-name Titles) |
| `VI_Earnie_Heatpump_v2.xml` | `heatpump.{hk_id}.set_enable` |
| `VI_Earnie_EV_v2.xml` | `evcs.*.set_evcs_*` |
| `VI_Earnie_Consumer_v2.xml` | `consumer.{hk_id}.set_enable` |
| `VI_Earnie_Pool_v2.xml` | `pool.*.set_enable` |

For a config with real Kennungen, generate `VI_Pilot_*.xml` instead (see above).

Target folder (use one of the existing Config paths; create the folder if needed):

- `%ProgramData%\Loxone\Loxone Config\<Version>\Template\VirtualIn\`
- or `Documents\Loxone\Loxone Config\Templates\VirtualIn\`

#### VirtualOut

Source: `share/loxone/templates/VirtualOut/`


| File                      | Content (short)                                             |
| ------------------------- | ------------------------------------------------------------ |
| `VO_Earnie_Status.xml`    | optional `Earnie_Request_Optimize` (port **8541**)  |
| `VO_Earnie_Plant.xml`     | `grid.meter.*` (power, import/export energy, export limit), PV, outside temperature, absent mode |
| `VO_Earnie_Battery.xml`   | battery / ESS telemetry and cut-offs (`ess.{slug}.*`: SoC, power, energy, `get_ess_*`) |
| `VO_Earnie_EV.xml`        | EV telemetry                                                 |
| `VO_Earnie_Heatpump.xml`  | `Earnie_Waermepumpe_Leistung`, `Earnie_Waermespeicher_Temp_eq`, `Earnie_Waermespeicher_Temp_low` |
| `VO_Earnie_Consumer.xml`  | flex power                                                   |
| `VO_Earnie_Pool.xml`      | pool telemetry                                                |


Target: the corresponding `VirtualOut` folder.

Then **restart Loxone Config**. The templates appear under Peripherals / Device Templates (Virtual In / Virtual Out).

### 2. Set the Earnie Address

In every inserted Virtual In/Out, replace the `EARNIE_HOST` placeholder with Earnie's LAN IP or hostname. The Streamlit UI typically uses port **8501**. The **daemon HTTP** (Virtual In status, `Earnie_Request_Optimize`, telemetry heartbeat) uses port **8541** (`system.ehal_loxone_http_port`). See [Streamlit Ports](streamlit-ports.md).

Example Virtual In address (status JSON):

`http://192.168.178.10:8541/ehal/loxone/status.json`

Virtual Out address for **status / request optimize**:

`http://192.168.178.10:8541`

Telemetry VOs (`VO_Earnie_*` except `Status`) also target the daemon port **8541**. Telemetry push works as follows:

- **Receiver:** `/ehal/telemetry/<EHAL-ID>/<value>` (alias `/ehal/loxone/telemetry/…` for existing VOs). It accepts pushes only when `EARNIE_PILOT_PUSH_TOKEN` is set.
- **Inbox reads:** all pushable `sens_*` / `get_*` fields are read from the inbox (no Merker poll). This includes the **meter energy** counters `sens_pv_energy`, `sens_grid_energy_import` / `_export` and `consumer.<id>.sens_energy_total`.
- **Repeat interval:** recommended **10 s** (`EARNIE_PILOT_PUSH_REPEAT_S`, default 10).
- **Stale energy values** (older than 3 × repeat) are not assumed to be zero. Slot Ist keeps the sample mean for that channel.
- **Heartbeat:** the synthetic heartbeat VO is always push.
- **FertigUm** (`ev.<id>.get_evcs_ready_by_time`): pushed as an Analog VO. A numeric next-entry value is preferred. Tna-style text such as `Morgen, 07:00` is accepted while fresh and parsed by the optimizer.
- **Value placeholder:** a Virtual Output command uses `<v>` (written `&lt;v&gt;` in the XML). `\v` is the Virtual **Input** check placeholder and arrives as the control character 0x0B in an output.

Adjust the polling / Cmd check pattern to match the JSON keys (plant: `set_ess_*` / `heartbeat_ts`; flex: `consumer.{hk_id}.…` (heat pump `heatpump.…`, pool `pool.…`); EV: `evcs.{ev_id}.…`). Stable **titles** remain the contract for Core and the Default import.

### 3. Insert Devices and Keep the Merker Names

1. Insert the matching template once per role (or multiple times for multiple flex consumers).
2. Do not rename Cmd **titles** arbitrarily — they must match [`greenfield_device_map.json`](../../share/loxone/greenfield_device_map.json) and the tables below.
3. **Multiple flex consumers / EVs:** titles follow a prefix + instance-ID scheme; the VI check and VO path use `{hk_id}` / `{ev_id}` (see [naming convention](#multiple-flex-consumers-naming-convention)).
4. Save/load the program on the Miniserver.

### 4. Meters and Energy Flow Monitor (EFM)

The templates contain **no** meter hardware, but the import also picks up the meter blocks in use. In Loxone Config:

1. Create or keep a meter with a **unique, stable designation**.
2. Assign the meter to the **Energy Flow Monitor** (grid / PV / battery / loads).
3. Do not use residual/remainder nodes as a separate flex consumer. The import skips typical remainder labels.

Power Merker (`Earnie_Netzleistung`, `Earnie_PV_Leistung`, …) **may** come from the EFM; the Virtual Output Cmds remain an optional name catalog. Earnie prefers the EFM designation in the binding when available.

After **Smarthome-Backend → Loxone-Import**, check the signal mapping on EHAL-Com (**Signalliste**).

**EV ready-by time.** The Loxone import binds **AlarmClock** blocks to `get_evcs_ready_by_time` on the EV entity that already has meter/power bindings (same convention as the meter designation). Optional Analog VO: `/ehal/telemetry/ev.<id>.get_evcs_ready_by_time/<v>` (numeric next-entry; the inbox also accepts short Tna-style text). Bound FertigUm fields always use the push inbox; the former SpecialState10 / `/all` Merker poll is retired.

### 5. Earnie Dead-Man Fallback (in Loxone Config)

<a id="earnie-dead-fallback-in-loxone-config"></a>

Goal: if Earnie is unreachable or the Virtual In is no longer updated, the Miniserver must **ignore** Earnie's last setpoints and run local rules instead.

Recommended approach (logic blocks in Config, no Earnie code):

1. **Watchdog** on the heartbeat Cmd (`heartbeat_ts` in `VI_Earnie_Plant_v2.xml`, `Earnie_Heartbeat` in the Default naming; Unix timestamp): age = now − heartbeat, or "value unchanged for x seconds".
2. **Threshold:** e.g. 2–3 × the Virtual In polling time, typically ≥ 30 s at a 10 s poll.
3. **When the dead-man fallback triggers:**
   - Set `Earnie_Steuerbefehl` / ESS mode locally to **automatic** (`0`), or apply the plant's safe ESS rules.
   - Set flex **enables** (`Earnie_*_Freigabe`) to `0` (blocked), or apply known emergency logic.
   - Stop taking EV setpoints from the Earnie Merker.
4. **When Earnie is alive again:** pass the Earnie Merker through to the actuators/program as intended.

Earnie Core needs no change for this. The fallback is Config logic around the Merker only.

### 6. Loxone Import into Earnie

Prerequisites: the Earnie templates are installed in Loxone Config, each consumer has a meter block (EFM), and the credentials are entered on **Smarthome-Backend → Anbindung**. The import button becomes active only once the Miniserver is reachable.

1. On **Daemon Control → Smarthome-Backend**, the **Loxone Import** section appears below the connection summary once Loxone is connected. On first setup, **No — continue manually** appears on the same row as the import button.
2. Earnie loads `LoxAPP3.json`, classifies `Earnie_*` against the LoxAPP3 control names (exact or prefix + slug, case-insensitive), creates typed entities, and binds the EFM meters.
3. Check the signal mapping on **EHAL-Com** ([Signalliste](../ui/ehal-com.md#signalliste-loxone-contract)). Follow up on parameters (kWh, schedules, living area, …) in the **House Configurator**.

### Library Checklist

- [ ] `VI_` / `VO_` XMLs copied into the Config template folders, Config restarted
- [ ] `EARNIE_HOST` set; devices inserted; titles stable
- [ ] Multiple consumers / EVs: slug titles + check/VO `{hk_id}` / `{ev_id}` (if used)
- [ ] Meters on the EFM with unique designations
- [ ] Program saved on the Miniserver
- [ ] Optional: heartbeat watchdog + fallback programmed
- [ ] Smarthome-Backend: Loxone import → check mapping on EHAL-Com → parameters in the house profile

---

## Presence check (for Binding and Import)

The template Cmd titles are **known** (`greenfield_device_map.json`). Earnie checks them against the **LoxAPP3 control names** (`GET /data/LoxAPP3.json`): a signal counts as present if its name (Bezeichnung) appears in `controls`, otherwise as missing. Titles that are not visible in the Loxone app, and are therefore absent from LoxAPP3, are not detected. A discovery inbox for unknown push IDs is planned.

The Default import uses the LoxAPP3 names. EFM meters also come from `LoxAPP3.json`.

## Multiple Flex Consumers (Naming Convention)

<a id="multiple-flex-consumers-naming-convention"></a>

One template `VI_Earnie_Consumer` / `VO_Earnie_Consumer` covers **one** consumer. Miniserver designations must be unique. The house-profile `id` (lowercase, snake_case, e.g. `waschmaschine`) is the canonical **entity slug** (`{hk_id}`).


| Signal   | Merker title (1st / additional)                                       | VI check / VO path                                |
| -------- | ----------------------------------------------------------------------- | --------------------------------------------------- |
| Power    | `Earnie_Verbraucher_Leistung` → `Earnie_Verbraucher_<Slug>_Leistung`   | VO: `flex.{hk_id}.sens_power_act`                  |
| Active   | `Earnie_Verbraucher_<Slug>_Aktiv` (Kennung required)                   | VO: `consumer.{hk_id}.sens_consumer_active` (0/1) |
| Enable   | `Earnie_Verbraucher_Freigabe` → `…_<Slug>_Freigabe`                    | Check: `consumer.{hk_id}.set_enable`               |


**Example washing machine** (`id` = `waschmaschine`):

- Title: `Earnie_Verbraucher_Waschmaschine_Leistung`
- VO command when on: `/ehal/telemetry/flex.waschmaschine.sens_power_act/<v>`
- VI check (enable): `"consumer.waschmaschine.set_enable":\v` (title stays `Earnie_Verbraucher_Waschmaschine_Freigabe`)
- EHAL-Com binding: `flex.{hk_id}.sens_power_act` → title (for `zaehler_<slug>`: wire slug without `zaehler_`)

`<Slug>` **in the Merker:** short, stable token (e.g. `Waschmaschine`). `{hk_id}`: same consumer as in the house profile.

## Multiple EVs (Naming Convention)

Analogous: prefix `Earnie_EAuto_`, entity `id` = `{ev_id}` (e.g. `eauto`, `garage`).


| Signal            | Merker title (1st / additional)                       | VI check / VO path                       |
| ------------------ | -------------------------------------------------------- | ------------------------------------------ |
| Target A          | `Earnie_EAuto_Soll_A` → `Earnie_EAuto_<Slug>_Soll_A`     | Check: `evcs.{ev_id}.set_evcs_max_current` |
| Mode              | `Earnie_EAuto_Modus` → `…_<Slug>_Modus`                  | Check: `evcs.{ev_id}.set_evcs_mode`        |
| Power             | `Earnie_EAuto_Leistung` → `…_<Slug>_Leistung`            | VO: `ev.{ev_id}.sens_evcs_active_power`   |
| additional sens/get | `Earnie_EAuto_*` → `…_<Slug>_*`                         | VO: `ev.{ev_id}.<ehal_field>`             |


**Heat pump:**

- Titles: `Earnie_Waermepumpe_Leistung` / `Earnie_Waermepumpe_Freigabe`.
- Store temperatures: `Earnie_Waermespeicher_Temp_eq` / `Earnie_Waermespeicher_Temp_low`.
- Paths: VO `flex.{hk_id}.sens_power_act`, VI check `heatpump.{hk_id}.set_enable` (default `id` `wp_heating`).

**Pool:** VO `flex.pool.sens_power_act` (or `flex.{hk_id}.sens_power_act`), VI check `pool.{hk_id}.set_enable`.

**Import:** the Default import matches template names **case-insensitively**, either exactly or as **prefix + slug**. Examples: `Earnie_Verbraucher_Waschmaschine_Leistung` → consumer `waschmaschine`; `Earnie_EAuto_Garage_Soll_A` → EV `garage`. Bindings keep the Miniserver spelling.

In Config: insert the template, set the Cmd titles and the VI check / VO path `{id}`, then save to the Miniserver.

To check all configured signals:

```powershell
.venv\Scripts\python.exe -m scripts.verify_loxone_setup
.venv\Scripts\python.exe -m scripts.verify_swimspa_filter_live
```

---

## Role ↔ Entity (Overview)


| Entity / area                                                          | Storage location                              | Typical EHAL fields / roles                                                                                                                               |
| ------------------------------------------------------------------------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Plant (PV, grid, house load, outside temp., absent; ESS power/setpoints via primary battery)   | `house_profiles.json` → `plant.ehal_bindings` | `sens_pv_production_active`, `sens_ess_power`, `sens_grid_power_active`, `sens_temperature_outside`, `sens_absent_mode`, `sens_power_consumers` (SoC: `batteries[].ehal_bindings` → `ess.{slug}.sens_ess_soc`) |
| Request Optimize (ad hoc)                                               | Loxone VO → daemon HTTP                       | `Earnie_Request_Optimize` on port `system.ehal_loxone_http_port` (default **8541**)                                                                       |
| Heat pump / Flex / Thermal                                              | `consumers[].ehal_bindings`                   | `flex.{slug}.sens_power_act`, `flex.{slug}.set_enable`                                                                                                  |
| EV (`ev`)                                                                | `consumers[].ehal_bindings`                   | `sens_evcs_*`, `get_evcs_*`, `set_evcs_*`                                                                                                                  |
| Pool / SwimSpa                                                           | `consumers[].ehal_bindings` + filter entity   | see default `Earnie_Pool_*` / EHAL-Com, section Pool / SwimSpa                                                                                                                |


Editing in the UI: **only** under **Daemon Control → EHAL-Com → Signalliste** (and related mapping sections). The House Configurator no longer edits Merker addresses.

## Core Signals (`plant.ehal_bindings`)

Default names. Grid/PV/battery **power** preferably via the EFM meter designation.


| EHAL field                       | Direction | Default name                                   | Value / unit                                                                            |
| ---------------------------------- | --------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| `ess.{slug}.sens_ess_soc`         | Read      | `Earnie_Batterie_SoC` / `Earnie_Batterie_<Slug>_SoC` | Battery SoC, % (entity-scoped; not plant-flat)                                          |
| `sens_pv_production_active`       | Read      | `Earnie_PV_Leistung` (or EFM production)         | PV power, kW                                                                                |
| `sens_ess_power`                  | Read      | `Earnie_Batterie_Leistung` (or EFM storage)      | Battery kW; **+ discharge**, − charge (same as EHAL, no inversion)                          |
| `sens_grid_power_active`          | Read      | `Earnie_Netzleistung` (or EFM grid)              | Grid: + import, kW                                                                          |
| `get_grid_export_power_limit`     | Read      | `Earnie_Netz_Einspeisegrenze_In` (optional)      | Max export limit read from Loxone, kW (EHAL: W)                                     |
| `get_ess_soc_min`                 | Read      | `Earnie_Batterie_SOC_Min` (optional)             | Discharge cut-off SoC %; MILP when `limits_from_live`                               |
| `get_ess_soc_max`                 | Read      | `Earnie_Batterie_SOC_Max` (optional)             | Charge cut-off SoC %                                                                |
| `get_ess_max_charge_power`        | Read      | `Earnie_Batterie_Max_Ladeleistung` (optional)    | Device max charge (Loxone kW → EHAL W)                                              |
| `get_ess_max_discharge_power`     | Read      | `Earnie_Batterie_Max_Entladeleistung` (optional) | Device max discharge (Loxone kW → EHAL W)                                           |
| `sens_power_consumers`            | Read      | (optional)                                        | House load; otherwise derived                                                               |
| `sens_temperature_outside`        | Read      | `Earnie_Aussentemperatur`                        | Outside temperature °C (house-wide; heat pump/pool)                                        |
| `sens_absent_mode`                | Read      | `Earnie_Abwesend`                                | House absent / holiday mode 0/1 (OR with HK `absent_mode`)                                 |
| `set_ess_active_power`            | Write     | `Earnie_Batterie_Sollleistung`                   | Forced power, kW; `+` discharge, `−` charge                                                 |
| `set_ess_charge_power_limit`      | Write     | `Earnie_LadeLeistungs-Limit`                     | Max. charge power (true limit)                                                              |
| `set_ess_discharge_power_limit`   | Write     | `Earnie_EntladeLeistungs-Limit`                  | Max. discharge power (true limit)                                                           |
| `set_ess_mode`                    | Write     | `Earnie_Steuerbefehl`                            | Sticky: always write; `0` = automatic; battery only; OpenEMS ignores                        |
| `ess.<id>.set_ess_source_select`  | Write     | Pattern-B Merker (e.g. legacy `Earnie_Speicher_Quellenwahl`) | physical `standby_backup` only; `0` = grid pass-through, `1` = battery-only island (capability `supports_ess_source_select`); not on plant |
| `set_grid_export_power_limit`     | Write     | `Earnie_EinspeiseLeistungs-Limit`                | Max export kW (magnitude ≥ 0); `0` = no export; unconstrained = PV kWp + max battery discharge kW |
| *(watchdog)*                       | Read      | `Earnie_Heartbeat`                               | entity-scoped; not an EHAL field                                                                |


The legacy role names (`soc_name`, `pv_power_name`, …) in `loxone_blocks` have been removed. Only `plant.ehal_bindings` with the EHAL field names above are used (see [EHAL contract](../referenz/ehal.md)).

**Sticky Merker.** Loxone keeps the last written value.

- **Automatic mode:** `set_ess_mode = 0` means automatic. In mode 0, Config must not apply the setpoint power, even if `Earnie_Batterie_Sollleistung` still holds an old value.
- **Export curtailment:** `set_grid_export_power_limit` is a non-negative magnitude in kW, like the charge/discharge limits. Config curtails grid feed-in to `min(limit, inverter rating)`. `0` means no export (Einspeisesperre).
- **Unconstrained export:** written as the plant maximum, i.e. the PV kWp sum plus the **sum** of the max discharge kW of every selected force-dischargeable battery (`control = full`). If this is unknown, `1000` kW is written.
- **Multi-ESS:** Merker titles use the slug infix `Earnie_Batterie_<Slug>_…`. The entity-scoped binding keys are `ess.{slug}.sens_ess_soc` / `set_ess_*` on `batteries[].ehal_bindings`.
- **`set_ess_mode`** (`Earnie_Steuerbefehl`) is battery-only and never signals export curtailment.

## Flexible Consumers — `ehal_bindings` on the Consumer

The signal definitions live in the active house profile (`house_profiles.json`). The Merker are stored under `ehal_bindings`, keyed by EHAL field name. For existing profiles without bindings, run:

```powershell
python -m scripts.migrate_ehal_bindings --path <house_profiles.json> [--config <config.json>]
```

### Flex / Thermal (Stub `flex.*`)


| EHAL field                        | Direction | Default / example                                                                          | Value       |
| ------------------------------------ | --------- | ---------------------------------------------------------------------------------------------- | ------------ |
| `flex.{slug}.sens_power_act`       | Read      | Heat pump: `Earnie_Waermepumpe_Leistung`; generic: `Earnie_Verbraucher_Leistung`; or EFM load  | kW or 0/1   |
| `consumer.{slug}.sens_consumer_active` | Read  | Generic: `Earnie_Verbraucher_<Slug>_Aktiv` (digital; reserve release OR-trigger). Storage binding may still use `flex.{slug}.sens_consumer_active`. | `0`/`1` |
| `flex.{slug}.set_enable`           | Write     | Heat pump: `Earnie_Waermepumpe_Freigabe`; generic: `Earnie_Verbraucher_Freigabe`               | `0`/`1`     |


Pool enables: default `Earnie_Pool_Freigabe` / `Earnie_Pool_Filter_Freigabe` in `ehal_bindings`.

**Heat storage Ist (Live):** on the `thermal_annual` consumer:

| EHAL field | Meaning | Default Merker |
| --- | --- | --- |
| `sens_temperature_heat_storage` | Energy-equivalent `T_eq` (°C) | `Earnie_Waermespeicher_Temp_eq` |
| `sens_temperature_heat_storage_low` | Lowest immersion sensor `T_low` (°C) — WP-on hint when bottom is cold | `Earnie_Waermespeicher_Temp_low` |

For stratified tanks `T_eq` must be the energy-equivalent mean (volume-weighted), not the top sensor alone. Guide: [waermespeicher-schichtung-teq.md](../konfiguration/waermespeicher-schichtung-teq.md).

### EV (Prefix `Earnie_EAuto_`)


| EHAL field                  | Direction | Default name                                                                                            | Value                                                                                                                                                                                                              |
| ------------------------------ | --------- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sens_evcs_active_power`     | Read      | `Earnie_EAuto_Leistung` (or EFM load; dual `flex.{slug}.sens_power_act`)                                   | kW                                                                                                                                                                                                                  |
| `sens_evcs_connected`        | Read      | `Earnie_EAuto_Angeschlossen`                                                                                | `1` = connected                                                                                                                                                                                                    |
| `sens_evcs_soc_act`          | Read      | `Earnie_EAuto_SOC`                                                                                          | Current SOC, %                                                                                                                                                                                                    |
| `sens_evcs_bat_capacity`     | Read      | `Earnie_EAuto_Kapazitaet`                                                                                   | kWh                                                                                                                                                                                                                |
| `get_evcs_nominal_current`   | Read      | `Earnie_EAuto_MaxStrom`                                                                                     | A                                                                                                                                                                                                                  |
| `get_evcs_ready_by_time`     | Read      | AlarmClock **designation** (legacy); VO Title `Earnie_EAuto_FertigUm` | Push inbox: Analog VO numeric next-entry preferred; Tna text (`Morgen, 07:00`) accepted while fresh and parsed by the optimizer. |
| `get_evcs_limit_soc`         | Read      | `Earnie_EAuto_LimitSOC`                                                                                     | Target charge SOC %                                                                                                                                                                                               |
| `get_evcs_soc_min_immediate` | Read      | `Earnie_EAuto_SOCMinSofort`                                                                                 | ASAP minimum SOC %; ≤0 or empty = inactive; capped at the limit SOC                                                                                                                                               |
| `set_evcs_max_current`       | Write     | `Earnie_EAuto_Soll_A`                                                                                       | Target/max current A                                                                                                                                                                                              |
| `set_evcs_mode`              | Write     | `Earnie_EAuto_Modus`                                                                                        | `off`=0 / `pv`=1 / `now`=2                                                                                                                                                                                         |


Notes:

- The EV consumer also requires the field `min_power_kw`.
- **EV mode** is written only through `set_evcs_mode` (`Earnie_EAuto_Modus`). Earnie does not write `pv_follow` or immediate-command Merker.
- **Pool filter:** the house-profile consumer `pool_filter` carries its EHAL roles (among others `get_filter_remaining_hours`) under `ehal_bindings`. Default prefix: `Earnie_Pool_*` / `Earnie_Pool_Filter_*` (see [ehal-com.md](../ui/ehal-com.md), section Pool / SwimSpa).

## Request Optimize (Ad Hoc Runs)

Ad hoc optimization runs in `main.py` (between quarter hours) via Loxone → Earnie HTTP.


| Element                          | Meaning                                                                                    |
| ----------------------------------- | ---------------------------------------------------------------------------------------------- |
| Virtual Out                        | template `share/loxone/templates/VirtualOut/VO_Earnie_Status.xml`                             |
| Address                            | `http://EARNIE_HOST:8541` (port = `system.ehal_loxone_http_port`, default **8541**)           |
| Cmd `Earnie_Request_Optimize`      | `POST /ehal/loxone/request_optimize` — wakes the daemon before the next quarter hour; receipt ID `request_optimize` in EHAL-Com **Signalliste** and **Live-Lesen** |

Link proof (hub → Earnie) is the repeating telemetry VO **`Push_Earnie_Heartbeat`** → `GET /ehal/telemetry/heartbeat/<v>`, not a Status cmd. Existing Configs that still contain the obsolete **`Earnie_Push_Alive`** / `GET /ehal/loxone/alive` command should delete it; the endpoint returns 404.


Compose production stacks publish container port **8541** (see [Streamlit Ports](streamlit-ports.md)).

## Example Mapping


| Consumer (`id`)   | Control (write)                                            | Power (read)                                                    |
| ------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------- |
| `swimspa` / pool    | `flex.{slug}.set_enable` → `Earnie_Pool_Freigabe`              | `flex.{slug}.sens_power_act` → `Earnie_Pool_P_act`                  |
| `ev`                | `set_evcs_max_current` / `set_evcs_mode`                       | `sens_evcs_*` / `flex.{slug}.sens_power_act`                        |
| `wp_heating`        | `flex.{slug}.set_enable` → `Earnie_Waermepumpe_Freigabe`       | `flex.{slug}.sens_power_act` → `Earnie_Waermepumpe_Leistung`; `sens_temperature_heat_storage` / `_low` → `Earnie_Waermespeicher_Temp_eq` / `_low` |


## Reading vs. Writing in `main.py`


| Phase        | Action                                             |
| ------------- | ---------------------------------------------------- |
| Read         | SOC, powers, PV, flex inputs, EV status              |
| Optimization | MILP over the planning horizon (15-min slots; `dt_h = 0.25`) |
| Write        | ESS limits / mode, enables / EV current per 15-min write cycle |


The app **reads** the same live values for display; it only **writes** control values in live mode. Merker mapping: [EHAL-Com](../ui/ehal-com.md).

Further details: [Loxone Integration](../einrichtung/loxone-anbindung.md) · [Abbreviations](../referenz/abbreviations.md).
