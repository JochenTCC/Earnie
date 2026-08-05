# EHAL-Com (Anbindung & Debug)

Die Seite **EHAL-Com** unter **Daemon Control** ist die zentrale Stelle für Smarthome-Anbindung und Live-Debug: **Loxone**, **Home Assistant (EHAL)** oder **OpenEMS**. Sie zeigt Live-Lesen / Live-Schreiben des letzten Produktiv-Laufs von `main.py`. Loxone-Bindings werden **entity-zentriert** unter **Loxone Struktur → EHAL Mapping** gepflegt. Außerplanmäßige Optimierung läuft über Loxone VO **`Earnie_Request_Optimize`** (Daemon-HTTP, Port `system.ehal_loxone_http_port`, Standard **8541**) — nicht mehr über Merker-Event-Trigger.

## Aufruf

1. Streamlit starten: `python -m scripts.run_streamlit`
2. Navigation: **Daemon Control → EHAL-Com**

Zugangsdaten werden **nicht** mehr in der Sidebar erfasst, sondern unter **Anbindung** auf dieser Seite (oder in der Ersteinrichtung beim ersten Start).

## Anbindung

Oben wählen Sie das **Smarthome-Backend**:


| Backend        | Speicherung                                   | Formular                                            |
| -------------- | --------------------------------------------- | --------------------------------------------------- |
| Loxone         | `config/.env` (`LOXONE_IP` / `USER` / `PASS`) | Miniserver-IP, Benutzer, Passwort                   |
| Home Assistant | `config.json` → `ehal.ha`                     | URL, Long-Lived Token; darunter Entity→EHAL-Mapping |
| OpenEMS        | `config.json` → `ehal.openems`                | Base-URL, Benutzer, Passwort, ESS-/EVCS-Komponenten |


`ehal.backend` steuert den Live-Pfad in `main.py` (Loxone-HTTP vs. EHAL-REST). Welche Backend-Wahl wann sinnvoll ist: [Adapter wählen](../einrichtung/adapter-wahl.md).

## B) EHAL-Wire (Felder, Einheiten, Signale)

Kurze Übersicht der **kanonischen EHAL-Wire-Felder** (gleich `docs/ui/ehal-com.md` §C; Ziel nach Backlog **2.4.j**). Adapter liefern/erzeugen diese Namen zwischen Hub und Earnie Core.


| Kategorie             | Feld                            | Required | Einheit / Sign-Konvention                                                                              |
| --------------------- | ------------------------------- | -------- | ------------------------------------------------------------------------------------------------------ |
| Envelope              | `schema_version`                | ja       | integer; Wire-Version (**3** = Design C1 `set_ess_active_power`)                                       |
| Envelope              | `ts`                            | ja       | ISO-8601 Timestamp **mit Zeitzone** (bevorzugt UTC)                                                    |
| Envelope              | `adapter_id`                    | ja       | stabile Adapter-ID (z. B. `openems-lab`, `ha-home`)                                                    |
| Telemetrie            | `sens_grid_power_active`        | ja       | **W**; `+` = Netz **Bezug**, `-` = **Einspeisung**                                                     |
| Telemetrie            | `sens_pv_production_active`     | ja       | **W**; >= 0                                                                                            |
| Telemetrie            | `sens_ess_soc`                  | ja       | **%**; 0…100                                                                                           |
| Telemetrie (optional) | `sens_ess_power`                | nein     | **W**; ESS Vorzeichen **OpenEMS-aligned**: `+` = **Entladung**, `-` = **Ladung**                       |
| Telemetrie (optional) | `sens_evcs_active_power`        | nein     | **W**; >= 0 (bei Idle i. d. R. 0)                                                                      |
| Telemetrie (optional) | `sens_power_consumers`          | nein     | **W**; Hauslast; Merker wenn gemappt, sonst aus Netz/PV/ESS ableiten                                   |
| Setpoints (Force)     | `set_ess_active_power`          | nein*    | **W**; signed; `+` = Entladung, `-` = Ladung; bei Automatik weglassen                                  |
| Setpoints (Limits)    | `set_ess_charge_power_limit`    | nein*    | **W**; nicht-negativer Betrag (echte Max. Ladeleistung)                                                |
| Setpoints (Limits)    | `set_ess_discharge_power_limit` | nein*    | **W**; nicht-negativer Betrag (echte Max. Entladeleistung)                                             |
| Setpoints (Limits)    | `set_evcs_max_current`          | nein*    | **A**; nicht-negativer Betrag (EV-Lade-Soll-/Maxstrom)                                                 |
| Setpoints (Modus)     | `set_ess_mode`                  | nein*    | Sticky-Backend: immer mitschreiben; **0 = Automatik** (auch bei alter Sollleistung); OpenEMS ignoriert |
| Setpoints (erweitert) | `set_evcs_mode`                 | nein*    | Enum: `off` | `pv` | `now` (Loxone-Merker: 0 / 1 / 2)                                                  |
| Capability Flags      | `supports_ess_write`            | ja       | boolean; ESS-Setpoints dürfen geschrieben werden                                                       |
| Capability Flags      | `supports_evcs_current`         | ja       | boolean; `set_evcs_max_current` darf geschrieben werden                                                |


Ein Setpoint-Dokument muss **mindestens eins** der Setpoint-Felder enthalten. Weggelassene Felder bedeuten in der Regel: **„unverändert lassen“** (Partial Updates sind erlaubt). **Ausnahme sticky Backends (Loxone/HA):** Merker behalten den letzten Wert — Automatik ist `set_ess_mode = 0`, nicht „Sollleistung weggelassen“. Vollständige Geräterollen inkl. `get_`* / weiterer `sens_evcs_`*: siehe §C.

## C) Kombinierte Feldliste: EHAL, OpenEMS, evcc, Victron, Loxone

Die folgenden Tabellen kombinieren je **Geräterolle**:

- die vorhandenen **EHAL-Felder**
- die aktuell verwendeten **OpenEMS-Kanäle**
- die zugehörigen **evcc-Attribute** (YAML-Sicht, nicht HA-`entity_id`)
- **Victron GX / EVCS** über Modbus-TCP (Unit-ID **100** = `com.victronenergy.system`; EVCS-Register ab **5000** am Charger)
- die vorhandenen **Loxone-Felder** inklusive **Loxone-Extras**

Gleiche fachliche Inhalte stehen in **derselben Zeile**. Wenn es für eine Seite aktuell **kein Matching** gibt, bleibt die Zelle leer.

Spalte **Art:** **Messwert** = gelesen (Telemetrie), **Steuerwert** = geschrieben (Setpoint / Freigabe), **Capability** = Adapter-Fähigkeit (kein Live-Kanal).

Quellen Victron: [GX Modbus-TCP Manual](https://www.victronenergy.com/live/ccgx:modbustcp_faq), [ESS Mode 2/3](https://www.victronenergy.com/live/ess:ess_mode_2_and_3), [EVCS Modbus-Registerliste v3.8](https://www.victronenergy.com/upload/documents/EVCS-Modbus-TCP-register-list-v3.8.xlsx), HA-Mapping-Beispiel [ha-modbus-manager Victron EVCS](https://github.com/TCzerny/ha-modbus-manager/blob/main/docs/README_victron_ev_charging_station.md).

### C.1 Inverter (Netz / PV)


| Bereich / Bedeutung     | Art      | EHAL Value Name             | OpenEMS                      | evcc (YAML-Attribut) | Victron GX / EVCS (Modbus)                                                                                          | Loxone / Loxone-Extra                                  |
| ----------------------- | -------- | --------------------------- | ---------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Netzleistung            | Messwert | `sens_grid_power_active`    | `_sum/GridActivePower`       | `meters.grid.power`  | Unit 100 Reg. **820–822** (`grid_power_l`*, W; `+` = Bezug, `−` = Einspeisung); alternativ Grid-Meter **2600–2602** | `grid_power_name`                                      |
| PV-Produktion           | Messwert | `sens_pv_production_active` | `_sum/ProductionActivePower` | `meters.pv.power`    | Unit 100 Reg. **850** (DC-PV, W) bzw. AC-PV **808–813**; für Gesamt oft Summe DC+AC                                 | `pv_power_name` / `plant.ehal_bindings`                |
| Leistung an Verbraucher | Messwert | `sens_power_consumers`      |                              |                      |                                                                                                                     | `ehal_bindings.sens_power_consumers` (sonst Ableitung) |
| Außentemperatur         | Messwert | `sens_temperature_outside`  |                              |                      |                                                                                                                     | `Earnie_Aussentemperatur` / `plant.ehal_bindings`      |




### C.2 ESS (Batterie)


| Bereich / Bedeutung            | Art        | EHAL Value Name                                  | OpenEMS                                       | evcc (YAML-Attribut)           | Victron GX / EVCS (Modbus)                                                                                              | Loxone / Loxone-Extra                                       |
| ------------------------------ | ---------- | ------------------------------------------------ | --------------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Batterie-SoC                   | Messwert   | `sens_ess_soc`                                   | `ess0/Soc` oder `_sum/EssSoc`                 | `meters.battery.soc`           | Unit 100 Reg. **843** (`battery_soc`, %)                                                                                | `soc_name`                                                  |
| Batterieleistung               | Messwert   | `sens_ess_power`                                 | `ess0/ActivePower` oder `_sum/EssActivePower` | `meters.battery.power`         | Unit 100 Reg. **842** (W; Victron: `+` = Laden, `−` = Entladen → für EHAL **Vorzeichen invertieren**)                   | `battery_power_name`                                        |
| ESS Sollleistung schreiben     | Steuerwert | `set_ess_active_power`                           | `ess0/SetActivePowerEquals`                   |                                | (gerätabhängig; nicht evcc Preis-Limit)                                                                                 | `target_active_power_name` / `Earnie_Batterie_Sollleistung` |
| ESS Ladegrenze schreiben       | Steuerwert | `set_ess_charge_power_limit`                     | `ess0/SetActivePowerGreaterOrEquals`          |                                | ESS Mode 2 Unit 100 Reg. **2705** (`system_max_charge_current`, A) bzw. Ein/Aus **2701** (kein 1:1-W-Limit wie OpenEMS) | `target_charge_power_name`                                  |
| ESS Entladegrenze schreiben    | Steuerwert | `set_ess_discharge_power_limit`                  | `ess0/SetActivePowerLessOrEquals`             |                                | ESS Mode 2 Unit 100 Reg. **2704** (`ess_max_discharge_power`, W)                                                        | `target_discharge_power_name`                               |
| Steuerbefehl Batterie / Huawei | Steuerwert | `set_ess_mode (0 = automatik / 1 / Zwangsladen)` | *(ignoriert)*                                 |                                | Siehe ESS Mode 2/3 ESS Schreibfähigkeit                                                                                 | `control_cmd_name`                                          |
| ESS-Schreibfähigkeit           | Capability | `supports_ess_write`                             | abgeleitete Adapter-Capability                | abgeleitete Adapter-Capability | ESS Mode 2/3 (Reg. **2700+** / Mode-3 VE.Bus-Setpoints); siehe ESS Mode 2/3 Manual                                      | aus active/charge/discharge Merker ableitbar                |




### C.3 EVCS (Wallbox / EV)


| Bereich / Bedeutung            | Art         | EHAL Value Name                                              | OpenEMS                                      | evcc (YAML-Attribut)             | Victron GX / EVCS (Modbus)                                          | Loxone / Loxone-Extra                                         |
| ------------------------------ | ----------- | ------------------------------------------------------------ | -------------------------------------------- | -------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------- |
| Wallbox-Ladeleistung           | Messwert    | `sens_evcs_active_power`                                     | `evcs0/ActivePower` oder `evcs0/ChargePower` | `chargers.wallbox.power`         | EVCS Reg. **5014** (`Power`, W); optional Phasen **5011–5013**      | `Earnie_EAuto_Leistung` / EFM Load / `ehal_bindings`          |
| EV angeschlossen               | Messwert    | `sens_evcs_connected`                                        |                                              | binary_sensor.evcc_lab_connected | EVCS Reg. **5015** Status `> 0` bzw. Binary `EV Connected`          | `charging_schedule.loxone.plugged_in_name`                    |
| EV Ist-SOC                     | Messwert    | `sens_evcs_soc_act`                                          |                                              | sensor.evcc_lab_vehicle_soc      | (AC-EVCS liefert i. d. R. keinen Fahrzeug-SoC)                      | `charging_schedule.loxone.actual_soc_name`                    |
| EV Nennstrom (lesbar)          | Eingabewert | `get_evcs_nominal_current`                                   |                                              |                                  | EVCS Reg. **5017** Max. Ladestrom (A; Leistung = f(A, Phasen, V))   | ersetzt `charging_schedule.loxone.nominal_power_kw_name`      |
| EV Batteriekapazität           | Messwert    | `sens_evcs_bat_capacity`                                     |                                              | sensor.evcc_battery_capacity     |                                                                     | `charging_schedule.loxone.battery_capacity_kwh_name`          |
| Wallbox-Maxstrom schreiben     | Steuerwert  | `set_evcs_max_current`                                       | `evcs0/SetChargePowerLimit` (A→W im Adapter) | `chargers.wallbox.maxcurrent`    | EVCS Reg. **5016** (`Charging Current Setpoint`, A)                 | `ehal_bindings.set_evcs_max_current` (EHAL-Com)               |
| EV Lademodus                   | Steuerwert  | `set_evcs_mode` (`off=0` / `pv=1` / `now=2` / `minpv` = n/a) |                                              |                                  |                                                                     |                                                               |
| EV Deadline / FertigUm         | Eingabewert | `get_evcs_ready_by_time`                                     |                                              |                                  |                                                                     | AlarmClock-Bezeichnung; SpecialState10 via `/all` (Tna-Text Backup) |
| EVCS-Schreibfähigkeit          | Capability  | `supports_evcs_current`                                      | abgeleitete Adapter-Capability               | abgeleitete Adapter-Capability   | ja (u. a. **5016**, **5010** Enable, **5009** Mode)                 | wenn Maxstrom-/Strom-Merker gemappt                           |
| SOC Ladeziel                   | Eingabewert | `get_evcs_limit_soc`                                         |                                              | number.evcc_lab_limit_soc        |                                                                     | `Earnie_EAuto_LimitSOC` / `ehal_bindings.get_evcs_limit_soc`  |




### C.4 Andere Verbraucher (Stub)

Noch **keine** first-class M1-EHAL-Felder. Live läuft über Hausprofil-Flex-Merker (`loxone_inputs` / `loxone_outputs`). Rollen-Vorlage: `share/ehal/roles/consumer.json`. **Wärmepumpe** → [C.5](#c5-wärmepumpe-stub); **Pool / SwimSpa** → [C.6](#c6-pool--swimspa-stub).

`flex.` ist ein **Rollen-Namespace**. Binding- und Live-Keys folgen Pattern B: `flex.{slug}.sens_power_act` / `set_enable` / `set_power_setpoint`. Live zeigt `{id}:flex.{slug}.…`. Bei Zähler-Ids `zaehler_<slug>` ist der Wire-Slug ohne Prefix (Beispiel: `zaehler_trockner:flex.trockner.sens_power_act`). Legacy-Stubs `flex.power_name` / `flex.enable_name` / `flex.power_setpoint_name` werden beim Laden migriert.

**Pattern B VO-Push-Pfad:** `/ehal/loxone/telemetry/flex.{slug}.sens_power_act/\v` (Freigabe/Soll `flex.{slug}.set_enable` / `flex.{slug}.set_power_setpoint`). Merker-Title bleibt `Earnie_Verbraucher_…`. Siehe [Loxone-Signale — Mehrere Flex-Verbraucher](../referenz/loxone-signale.md).


| Bereich / Bedeutung     | Art        | EHAL Value Name (Stub)           | OpenEMS | evcc (YAML-Attribut) | Victron GX / EVCS (Modbus) | Loxone / Loxone-Extra                       |
| ----------------------- | ---------- | -------------------------------- | ------- | -------------------- | -------------------------- | ------------------------------------------- |
| Flex Leistung / Zustand | Messwert   | `flex.{slug}.sens_power_act`     |         |                      |                            | `Earnie_Verbraucher_Leistung` oder EFM Load |
| Flex Freigabe           | Steuerwert | `flex.{slug}.set_enable`         |         |                      |                            | `Earnie_Verbraucher_Freigabe`               |
| Flex Leistungs-Sollwert | Steuerwert | `flex.{slug}.set_power_setpoint` |         |                      |                            | `Earnie_Verbraucher_Ziel_kW`                |




### C.5 Wärmepumpe (Stub)

Rollen-Vorlage: `share/ehal/roles/heatpump.json`. Greenfield-Prefix `Earnie_Waermepumpe_*` (Legacy `Earnie_WP_*`). Live typisch als `thermal_annual`-Consumer (z. B. `wp_heating`).


| Bereich / Bedeutung    | Art        | EHAL Value Name (Stub / Wire) | OpenEMS | evcc | Victron | Loxone / Loxone-Extra                                                                          |
| ---------------------- | ---------- | ----------------------------- | ------- | ---- | ------- | ---------------------------------------------------------------------------------------------- |
| WP Leistung            | Messwert   | `flex.{slug}.sens_power_act`  |         |      |         | `Earnie_Waermepumpe_Leistung` oder EFM Load                                                    |
| WP Freigabe / SG-Ready | Steuerwert | `flex.{slug}.set_enable`      |         |      |         | `Earnie_Waermepumpe_Freigabe`                                                                  |


Hinweise: Pattern B — VI = Freigabe von Earnie (`flex.{hk_id}.…` im Check); VO = optional Push `flex.{hk_id}.sens_power_act`. Außentemperatur nur auf Plant (`sens_temperature_outside`, siehe C.1) — nicht auf WP-VO. Kein Ziel-kW-Merker in dieser Greenfield-Runde.

### C.6 Pool / SwimSpa (Stub)

Deckt die **heute für SwimSpa genutzten** Signale (Heizung + Filter) ab. Zwei Live-Entities: Wärme (`daily_target_source: thermal`) und Filter (`loxone_remaining_hours`). Greenfield-Prefix `Earnie_Pool_`* / `Earnie_Pool_Filter_`* (Legacy z. B. `Earnie_SwimSpa_*` / Homie bleibt in Prod gültig). Spec Filter: [swimspa-filter.md](../spec/swimspa-filter.md). Recipe: `share/loxone/recipes/pool.json`.


| Bereich / Bedeutung       | Art         | EHAL Value Name (Stub)                   | OpenEMS | evcc | Victron | Loxone / Loxone-Extra                                           |
| ------------------------- | ----------- | ---------------------------------------- | ------- | ---- | ------- | --------------------------------------------------------------- |
| Pool Gesamtleistung       | Messwert    | `flex.{slug}.sens_power_act`             |         |      |         | `Earnie_Pool_P_act` oder EFM Load (Fall B: Heizung+Filter+Jets) |
| Pool Heiz-Freigabe        | Steuerwert  | `flex.{slug}.set_enable`                 |         |      |         | `Earnie_Pool_Freigabe`                                          |
| Pool Ist-Temperatur       | Messwert    | `sens_temperature_water`                 |         |      |         | `Earnie_Pool_Temp_Ist`                                          |
| Pool Soll-Temperatur      | Eingabewert | `get_temperature_water_setpoint`         |         |      |         | `Earnie_Pool_Temp_Soll`                                         |
| Temperatur-Toleranz       | Eingabewert | `get_temperature_tolerance_c`            |         |      |         | `Earnie_Pool_Temp_Toleranz`                                     |
| Heizung aktiv             | Messwert    | `sens_heating_active`                    |         |      |         | `Earnie_Pool_Heizung_aktiv`                                     |
| Filter Sollstunden        | Eingabewert | `get_filter_remaining_hours`             |         |      |         | `Earnie_Pool_Filter_Sollstunden`                                |
| Filter Freigabe           | Steuerwert  | `flex.{slug}.set_enable` (Filter-Entity) |         |      |         | `Earnie_Pool_Filter_Freigabe`                                   |
| Filter läuft (Binär)      | Messwert    | `sens_filter_active`                     |         |      |         | `Earnie_Pool_Filter_aktiv`                                      |
| Native Filter-Startstunde | Eingabewert | `get_filter_native_start_hour`           |         |      |         | `Earnie_Pool_Filter_NativeStart`                                |
| Native Filter-Dauer       | Eingabewert | `get_filter_native_duration_hours`       |         |      |         | `Earnie_Pool_Filter_NativeDauer`                                |


Hinweise: Außentemperatur nur Plant (`sens_temperature_outside`, siehe C.1). Chart zieht Filterleistung ggf. über `subtract_consumer_ids` ab (kein EHAL-Feld). Pattern B: `VI_Earnie_Pool` (Freigaben), `VO_Earnie_Pool` (Telemetrie). **VI Check** = bare `Earnie_Pool_Freigabe` / `Earnie_Pool_Filter_Freigabe` (wie Title); `status.json` mappt auch Legacy-Merker (`Ernie_Swimspa_*_Freigabe`) auf diese Keys.

**EHAL-Com Mapping:** Filter-Felder (`get_filter_remaining_hours`, `flex.pool_filter.sens_power_act`, `sens_filter_active`, native Start/Dauer, Freigabe) werden auf dem Hausprofil-Verbraucher **`pool_filter`** unter `ehal_bindings` gemappt. Ohne `pool_filter` gibt es keine Filter-MILP und keine synthetische Filter-Entity. Ohne Mapping bleibt der Filter inaktiv (kein Hard-Default auf `Ernie_Swimspa_Filter_Sollstunden`).

## Live-Cockpit noch gesperrt (Greenfield)

Nach abgeschlossener Planungs-Konfiguration erscheint **Szenario-Explorer**, aber **Live-Cockpit** bleibt ausgeblendet, solange die Anbindung für den Live-Betrieb nicht vollständig ist. Nutzen Sie **Anbindung**, **Live-Lesen** und die Verbindungstests auf dieser Seite.

## Bereiche der Seite



### Statusleiste

Die Statusleiste kombiniert **Silent-/Loud-Modus** mit dem Zustand des **Optimierer-Dienstes** (`main.py`):

- **Silent-Modus / Dienst läuft:** Optimierer läuft, schreibt aber keine Steuerwerte an den Hub.
- **Silent-Modus / Dienst gestoppt:** Optimierer läuft nicht.
- **Loud-Modus / Dienst läuft:** Optimierer läuft und sendet Daten an den Hub.
- **Loud-Modus / Dienst gestoppt:** Optimierer läuft nicht — daher werden keine Daten gesendet.
- **Letzter main.py-Lauf:** Zeitstempel und Alter (unabhängig von der Statusleiste).



### Live-Lesen

Nur `**sens_***` und `**get_***` (Messwerte / Eingaben). Die Tabelle listet **alle** erwarteten EHAL-Felder (Anlage + Verbraucher); ohne Binding bleibt die Mapping-Spalte leer und Status **Kein Mapping**. Spalten überall:


| Spalte | Bedeutung |
| --- | --- |
| EHAL-Feld | Kanonischer EHAL-Name (bei Verbrauchern `{id}:{feld}`) |
| Mapping auf Loxone / Home Assistant / OpenEMS | Adresse im gewählten Backend (Loxone-Merker, HA-`entity_id`, OpenEMS-Kanal); Spaltentitel je nach Backend; leer wenn noch nicht gemappt |
| Wert | Live-Wert |
| Status | OK / Warnung / Fehler / Kein Mapping |
| Detail | Fehlertext (bei OK leer) |
| Zuletzt gelesen | Zeitstempel der Abfrage |


**Loxone:** periodisches Lesen der konfigurierten Merker (Tabelle + **Smarthome-Merker testen**). Anlagen-Felder: `sens_ess_soc`, `sens_pv_production_active`, `sens_ess_power`, `sens_grid_power_active`, optional `sens_power_consumers`, `sens_temperature_outside` (`plant.ehal_bindings`). **Verbraucher** (aus Flex-Liste und Hausprofil mit Merker): EV → `{id}:sens_evcs_`* / `{id}:get_evcs_`*; andere mit Leistung →* `{id}:flex.{slug}.sens_power_act`*. Kein PV-Zähler, keine* `set_` / Freigaben. `get_evcs_ready_by_time`**:** Binding = AlarmClock-Bezeichnung (wie Zähler); Lesen von **SpecialState10** (`nextEntryTime`) über `/jdev/sps/io/{name}/all`, Backup **Tna**-Text. Numerische Counter (Loxone-Epoche seit 2009-01-01) werden in Unix umgerechnet und in der Spalte **Wert** lokal lesbar angezeigt (`YYYY-MM-DD HH:MM:SS (unix …)`).

**HA / OpenEMS:** EHAL-Telemetrie über REST (nur `sens_`* / `get_`* in der Tabelle; Verbindungstest zeigt ggf. das volle JSON inkl. Envelope). Mapping = Entity bzw. Kanal; abgeleitete Hauslast: `—(abgeleitet)`. Optional Caption Live-Leistung in kW.

Einheiten und Vorzeichen: siehe §B. Vollständige Rollen-Matrix: §C.

### Live-Schreiben

`**set_***` (Anlage / EV) sowie Flex-**Freigabe** / Sollwert (`{id}:flex.{slug}.set_enable`, optional `set_power_setpoint`). Die Tabelle listet **alle** erwarteten Schreibfelder; Werte/Erfolg kommen aus dem letzten `main.py`-Lauf (`runtime/optimizer_run_state.json`), ungemappte Zeilen haben eine leere Mapping-Spalte. Gleiche Identitäts-Spalten:


| Spalte | Bedeutung |
| --- | --- |
| EHAL-Feld | `set_*` bzw. `{id}:flex.{slug}.set_enable` (Freigabe) |
| Mapping auf Loxone / Home Assistant / OpenEMS | Merker / HA-Entity / OpenEMS-Schreibkanal; Spaltentitel je nach Backend; leer wenn noch nicht gemappt |
| Wert | Geschriebener Sollwert |
| Erfolg | Ja / Nein |
| Gesendet um | Zeitstempel |
| Meldung | Fehlertext bzw. Silent-Hinweis |


- **Loxone:** Trace `loxone_writes` (IO-Name wird auf EHAL-Feld zurückgeführt); Silent: geplante Sollwerte aus `loxone_sent` mit Status „Nicht gesendet“.
- **HA / OpenEMS:** `ehal_writes` (Feld, Wert, Erfolg, Zeit, Meldung); Fehlerbanner aus `runtime/ehal_write_error.json`.



### HA Entity → EHAL Mapping

Nur bei Backend **Home Assistant**: Entities scannen, Telemetrie-/Setpoint-Felder zuweisen, speichern. Die Felder sind nach **Geräterollen** gruppiert (Netz / PV / Batterie / Wallbox; Vorlagen unter `share/ehal/roles/`).

- Überblick / HITL: [Home Assistant + evcc](../einrichtung/ha-evcc.md) (Abschnitt *Wenn marq24 / evcc bereits in HA verbunden ist*)
- Lab-Abnahme inkl. Stub-Werte und Tabelle: [HA-Lab Spec §5.1](../spec/ha-lab-setup.md#51-after-marq24-ha-evcc-is-connected-lab-follow-up)



### Loxone Struktur → EHAL Mapping

Nur bei Backend **Loxone**: Entity-zentrierter Assistent (Backlog **2.4.k**, Struktur-Scan aus **2.4.f**). Entities = **Anlage (Plant)** + Verbraucher aus dem **Live-Hausprofil** (gleiches Shape wie Earnie-Entities). Mapping-Zeilen: `{entity}.{ehal_field}` → Merkername; Felder nach Geräterollen / §C (inkl. EV `set_evcs_max_current` / `get_evcs_limit_soc`, optional `sens_power_consumers`, C.4 `flex.`*).

Library-Vorlagen und Earnie-tot-Fallback: [Earnie-Loxone-Library](../einrichtung/loxone-earnie-library.md).

1. **HTTP-Probe** — bekannte Greenfield-/Template-Namen und bereits gemappte Merker (`greenfield_device_map.json` + Prefix+Slug) über `/jdev/sps/io/{Name}` prüfen (`LL.Code` 200 oder 403 = vorhanden, 404 = fehlt). Gefundene Namen füllen die Mapping-Dropdowns. Manuell hinzugefügte Merker werden bei der nächsten Probe mitgeprüft. (Loxone MCP und Ollama-KI bleiben im Code für spätere Re-Integration, sind auf der Oberfläche derzeit nicht angeboten.)
2. **Loxone-Import** (im **Hauskonfigurator**, oberhalb von Verbraucher) — legt typisierte Plant-/Verbraucher-Entities und `ehal_bindings` aus Merker+EFM an (Prefix+Slug case-insensitive). Zähler-Bezeichnung ohne führendes „Zähler“/„Zaehler“ und ohne EFM-„Verbraucher N:“ als Label/Id; gleiche physische Geräte (z. B. Pool↔Swimspa, E-Auto↔Wallbox/smart) werden zusammengeführt, EFM-Leistung bevorzugt auf den typisierten Verbraucher. Danach hier die Signal-Zuordnung prüfen. Vorher Library/Merker auf dem Miniserver: [Earnie-Loxone-Library](../einrichtung/loxone-earnie-library.md).
3. **Neuer Merker im Feld-Dropdown** — In jedem EHAL-Feld-Select kann ein noch unbekannter Merkername eingetippt werden (`accept_new_options`). Es erscheint eine Bestätigung (**Neuer Merker?**): bei **Ja** wird der Name in die Merker-Liste aufgenommen, dem Feld in `house_profiles.json` zugeordnet und optional per HTTP-Probe geprüft (vorhanden / 404); bei **Nein** bleibt das Feld ungemappt. Leere Eingaben zählen nicht.
4. **Human-in-the-Loop** — Entity wählen, EHAL-Felder zuweisen (Select-Label: **Bedeutung** plus EHAL-Value-Name, z. B. `Netzleistung (sens_grid_power_active)`). Die Merker-Adresse kommt aus dem Binding des gewählten Feldes.
5. **Speichern** — **Mapping speichern** schreibt alle sichtbaren Feld-Zuordnungen der gewählten Entity nach `plant.ehal_bindings` / `consumers[].ehal_bindings` in `house_profiles.json`. Einzelne neue Merker werden bereits bei der Bestätigung (Schritt 3) für dieses Feld persistiert. Beim ersten Migrate/Save werden Legacy-Merker-Trigger-Keys und Anlagen-Rollen aus `loxone_blocks` entfernt (leeres `loxone_blocks` entfällt).

**Energieflussmonitor → Verbraucher:** Expander **Zähler importieren** lädt Zähler aus `LoxAPP3.json` (EFM-Baum + orphan Meter), schlägt generische Verbraucher vor (Label/Id ohne führendes „Zähler“) und kann optional `flex.{slug}.sens_power_act` auf die Zähler-Bezeichnung setzen. Treffer auf bestehende typisierte Verbraucher (Merker) werden gematcht statt dupliziert. CSV-Export bleibt manuell; `flex.{slug}.set_enable` / `set_power_setpoint` nicht vom Zähler. Spec: [efm-auto-sync-2.4.l](../spec/efm-auto-sync-2.4.l.md). Manueller Blueprint: Plan `energieflussmonitor_hausprofil_blueprint_a`.

Bindings werden **nicht** mehr im Hauskonfigurator unter „Smarthome-Merker“ editiert — nur noch hier auf EHAL-Com. Siehe [Loxone-Signale](../referenz/loxone-signale.md).

## Silent-Modus vs. Loud-Modus


|                           | Silent-Modus                        | Loud-Modus                  |
| ------------------------- | ----------------------------------- | --------------------------- |
| Lesen                     | Immer aktiv (auch auf dieser Seite) | Immer aktiv                 |
| Schreiben durch `main.py` | Nein                                | Ja (nur wenn Dienst läuft)  |
| Schreib-Tabelle           | Nur Sollwerte                       | Wert + Erfolg + Zeitstempel |
| Typischer Einsatz         | Tests, paralleler Legacy-Betrieb    | Produktiv nach Cutover      |


Silent-Modus: `runtime/local_settings.json` → `"loxone_silent_mode"` (Priorität vor `system.loxone_silent_mode`). Standard ohne Datei: **Silent an**. Die Statusleiste zeigt zusätzlich, ob der Optimierer-Dienst gerade läuft; ohne laufenden Dienst werden im Loud-Modus keine Daten gesendet.

## Cutover-Checkliste

1. **Anbindung** gespeichert und Backend gewählt
2. **Live-Lesen:** `sens_`* / `get_`* mit Status **OK**
3. **Live-Schreiben:** alle `set_`*-Einträge **Erfolg = Ja** (Silent zuvor deaktivieren)
4. **Cockpit / Sankey:** Soll-Werte passen zu Live ([Charts & Panels](charts.md))



## Siehe auch

- [Loxone-Anbindung](../einrichtung/loxone-anbindung.md)
- [Home Assistant + evcc](../einrichtung/ha-evcc.md)
- [OpenEMS-Lab](../einrichtung/openems-lab.md)
- [Loxone-Signale](../referenz/loxone-signale.md)
- [Betrieb](../einrichtung/betrieb.md)
- Victron: [GX Modbus-TCP](https://www.victronenergy.com/live/ccgx:modbustcp_faq), [ESS Mode 2/3](https://www.victronenergy.com/live/ess:ess_mode_2_and_3), [EVCS Modbus-Registerliste](https://www.victronenergy.com/upload/documents/EVCS-Modbus-TCP-register-list-v3.8.xlsx)
- CLI (Loxone): `python -m scripts.verify_loxone_setup`

