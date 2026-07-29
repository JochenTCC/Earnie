# EHAL-Com (Anbindung & Debug)

Die Seite **EHAL-Com** unter **Daemon Control** ist die zentrale Stelle für Smarthome-Anbindung und Live-Debug: **Loxone**, **Home Assistant (EHAL)** oder **OpenEMS**. Sie zeigt Live-Lesen / Live-Schreiben des letzten Produktiv-Laufs von `main.py`. Loxone-Bindings und Event-Trigger werden **entity-zentriert** unter **Loxone Struktur → EHAL Mapping** gepflegt (nicht mehr als getrennte Anlagen-Merker-/Trigger-Formulare).

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


| Kategorie             | Feld                            | Required | Einheit / Sign-Konvention                                                        |
| --------------------- | ------------------------------- | -------- | -------------------------------------------------------------------------------- |
| Envelope              | `schema_version`                | ja       | integer; Wire-Version (M1 historisch `1`; `sens_*`-Freeze in **2.4.j**)          |
| Envelope              | `ts`                            | ja       | ISO-8601 Timestamp **mit Zeitzone** (bevorzugt UTC)                              |
| Envelope              | `adapter_id`                    | ja       | stabile Adapter-ID (z. B. `openems-lab`, `ha-home`)                              |
| Telemetrie            | `sens_grid_power_active`        | ja       | **W**; `+` = Netz **Bezug**, `-` = **Einspeisung**                               |
| Telemetrie            | `sens_pv_production_active`     | ja       | **W**; >= 0                                                                      |
| Telemetrie            | `sens_ess_soc`                  | ja       | **%**; 0…100                                                                     |
| Telemetrie (optional) | `sens_ess_power`                | nein     | **W**; ESS Vorzeichen **OpenEMS-aligned**: `+` = **Entladung**, `-` = **Ladung** |
| Telemetrie (optional) | `sens_evcs_active_power`        | nein     | **W**; >= 0 (bei Idle i. d. R. 0)                                                |
| Telemetrie (optional) | `sens_power_consumers`          | nein     | **W**; Hauslast; Merker wenn gemappt, sonst aus Netz/PV/ESS ableiten             |
| Setpoints (Limits)    | `set_ess_charge_power_limit`    | nein*    | **W**; nicht-negativer Betrag (Max. Ladeleistung)                                |
| Setpoints (Limits)    | `set_ess_discharge_power_limit` | nein*    | **W**; nicht-negativer Betrag (Max. Entladeleistung)                             |
| Setpoints (Limits)    | `set_evcs_max_current`          | nein*    | **A**; nicht-negativer Betrag (EV-Lade-Soll-/Maxstrom)                           |
| Setpoints (erweitert) | `set_ess_mode`                  | nein*    | ESS-Modus / Steuerbefehl (z. B. Huawei)                                          |
| Setpoints (erweitert) | `set_evcs_mode`                 | nein*    | Enum: `pv`                                                                       |
| Capability Flags      | `supports_ess_write`            | ja       | boolean; ESS-Limit-Setpoints dürfen geschrieben werden                           |
| Capability Flags      | `supports_evcs_current`         | ja       | boolean; `set_evcs_max_current` darf geschrieben werden                          |


 Ein Setpoint-Dokument muss **mindestens eins** der Setpoint-Felder enthalten. Omitted Felder bedeuten in der Regel: **„unverändert lassen“** (Partial Updates sind erlaubt). Vollständige Geräterollen inkl. `get_`* / weiterer `sens_evcs_`*: siehe §C.

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
| PV-Produktion           | Messwert | `sens_pv_production_active` | `_sum/ProductionActivePower` | `meters.pv.power`    | Unit 100 Reg. **850** (DC-PV, W) bzw. AC-PV **808–813**; für Gesamt oft Summe DC+AC                                 | `pv_power_name`                                        |
| PV-Zähler kumuliert     | Messwert | TO BE REMOVED               |                              |                      |                                                                                                                     | `pv_counter_name`                                      |
| Leistung an Verbraucher | Messwert | `sens_power_consumers`      |                              |                      |                                                                                                                     | `ehal_bindings.sens_power_consumers` (sonst Ableitung) |




### C.2 ESS (Batterie)


| Bereich / Bedeutung            | Art        | EHAL Value Name                 | OpenEMS                                       | evcc (YAML-Attribut)           | Victron GX / EVCS (Modbus)                                                                                              | Loxone / Loxone-Extra                                                    |
| ------------------------------ | ---------- | ------------------------------- | --------------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Batterie-SoC                   | Messwert   | `sens_ess_soc`                  | `ess0/Soc` oder `_sum/EssSoc`                 | `meters.battery.soc`           | Unit 100 Reg. **843** (`battery_soc`, %)                                                                                | `soc_name`                                                               |
| Batterieleistung               | Messwert   | `sens_ess_power`                | `ess0/ActivePower` oder `_sum/EssActivePower` | `meters.battery.power`         | Unit 100 Reg. **842** (W; Victron: `+` = Laden, `−` = Entladen → für EHAL **Vorzeichen invertieren**)                   | `battery_power_name`                                                     |
| ESS Ladegrenze schreiben       | Steuerwert | `set_ess_charge_power_limit`    | `ess0/SetActivePowerGreaterOrEquals`          |                                | ESS Mode 2 Unit 100 Reg. **2705** (`system_max_charge_current`, A) bzw. Ein/Aus **2701** (kein 1:1-W-Limit wie OpenEMS) | `target_charge_power_name`                                               |
| ESS Entladegrenze schreiben    | Steuerwert | `set_ess_discharge_power_limit` | `ess0/SetActivePowerLessOrEquals`             |                                | ESS Mode 2 Unit 100 Reg. **2704** (`ess_max_discharge_power`, W)                                                        | `target_discharge_power_name`                                            |
| Ziel-SoC ESS                   | Steuerwert | TO BE REMOVED                   |                                               |                                |                                                                                                                         | `target_soc_name`                                                        |
| Steuerbefehl Batterie / Huawei | Steuerwert | `set_ess_mode`                  |                                               |                                | Siehe ESS Mode 2/3 ESS Schreibfähigkeit                                                                                 | `control_cmd_name`                                                       |
| ESS-Schreibfähigkeit           | Capability | `supports_ess_write`            | abgeleitete Adapter-Capability                | abgeleitete Adapter-Capability | ESS Mode 2/3 (Reg. **2700+** / Mode-3 VE.Bus-Setpoints); siehe ESS Mode 2/3 Manual                                      | aus `target_charge_power_name` / `target_discharge_power_name` ableitbar |




### C.3 EVCS (Wallbox / EV)


| Bereich / Bedeutung            | Art         | EHAL Value Name            | OpenEMS                                      | evcc (YAML-Attribut)             | Victron GX / EVCS (Modbus)                                          | Loxone / Loxone-Extra                                      |
| ------------------------------ | ----------- | -------------------------- | -------------------------------------------- | -------------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------- |
| Wallbox-Ladeleistung           | Messwert    | `sens_evcs_active_power`   | `evcs0/ActivePower` oder `evcs0/ChargePower` | `chargers.wallbox.power`         | EVCS Reg. **5014** (`Power`, W); optional Phasen **5011–5013**      | `loxone_inputs.power_name` (EV-Hausprofil)                 |
| EV angeschlossen               | Messwert    | `sens_evcs_connected`      |                                              | binary_sensor.evcc_lab_connected | EVCS Reg. **5015** Status `> 0` bzw. Binary `EV Connected`          | `charging_schedule.loxone.plugged_in_name`                 |
| EV Rest-SOC bei Anschluss      | Messwert    | TO BE REMOVED              |                                              |                                  |                                                                     | `charging_schedule.loxone.soc_at_plug_in_name`             |
| EV Ist-SOC                     | Messwert    | `sens_evcs_soc_act`        |                                              | sensor.evcc_lab_vehicle_soc      | (AC-EVCS liefert i. d. R. keinen Fahrzeug-SoC)                      | `charging_schedule.loxone.actual_soc_name`                 |
| EV Nennstrom (lesbar)          | Eingabewert | `get_evcs_nominal_current` |                                              |                                  | EVCS Reg. **5017** Max. Ladestrom (A; Leistung = f(A, Phasen, V))   | ersetzt `charging_schedule.loxone.nominal_power_kw_name`   |
| EV Nennleistung / Max-Leistung | Messwert    | TO BE REMOVED              |                                              |                                  | (ersetzt durch `get_evcs_nominal_current`)                          | `charging_schedule.loxone.nominal_power_kw_name`           |
| EV Batteriekapazität           | Messwert    | `sens_evcs_bat_capacity`   |                                              | sensor.evcc_battery_capacity     |                                                                     | `charging_schedule.loxone.battery_capacity_kwh_name`       |
| EV Restzeit Sofortladen        | Messwert    | TO BE REMOVED              |                                              |                                  | EVCS Reg. **5019** Session-Zeit (s; kumuliert, kein Rest-Countdown) | `charging_schedule.loxone.charge_immediate_remaining_name` |
| Wallbox-Maxstrom schreiben     | Steuerwert  | `set_evcs_max_current`     | `evcs0/SetChargePowerLimit` (A→W im Adapter) | `chargers.wallbox.maxcurrent`    | EVCS Reg. **5016** (`Charging Current Setpoint`, A)                 | `ehal_bindings.set_evcs_max_current` (EHAL-Com)            |
| EV Lademodus                   | Steuerwert  | `set_evcs_mode` (`pv`      | `now                                         | off                              | minpv`)                                                             |                                                            |
| EV Deadline / FertigUm         | Eingabewert | `get_evcs_ready_by_time`   |                                              |                                  |                                                                     | `ehal_bindings.get_evcs_ready_by_time`                     |
| EVCS-Schreibfähigkeit          | Capability  | `supports_evcs_current`    | abgeleitete Adapter-Capability               | abgeleitete Adapter-Capability   | ja (u. a. **5016**, **5010** Enable, **5009** Mode)                 | wenn Maxstrom-/Strom-Merker gemappt                        |
| SOC Ladeziel                   | Eingabewert | `get_evcs_limit_soc`       |                                              | number.evcc_lab_limit_soc        |                                                                     | `ehal_bindings.get_evcs_limit_soc` (EHAL-Com)              |




### C.4 Andere Verbraucher (Stub)

Noch **keine** first-class M1-EHAL-Felder. Live läuft über Hausprofil-Flex-Merker (`loxone_inputs` / `loxone_outputs`). Rollen-Vorlagen: `share/ehal/roles/consumer.json`, `share/ehal/roles/heatpump.json`.


| Bereich / Bedeutung     | Art        | EHAL Value Name (Stub)     | OpenEMS | evcc (YAML-Attribut) | Victron GX / EVCS (Modbus) | Loxone / Loxone-Extra                                      |
| ----------------------- | ---------- | -------------------------- | ------- | -------------------- | -------------------------- | ---------------------------------------------------------- |
| Flex Leistung / Zustand | Messwert   | `flex.power_name`          |         |                      |                            | `loxone_inputs.power_name` (Flex- / Thermal-Verbraucher)   |
| Flex Freigabe           | Steuerwert | `flex.enable_name`         |         |                      |                            | `loxone_outputs.enable_name` (z. B. SG-Ready / Freigabe)   |
| Flex Leistungs-Sollwert | Steuerwert | `flex.power_setpoint_name` |         |                      |                            | `loxone_outputs.power_setpoint_name` (kW; nicht M1-EVCS-A) |




## Live-Cockpit noch gesperrt (Greenfield)

Nach abgeschlossener Planungs-Konfiguration erscheint **Szenario-Explorer**, aber **Live-Cockpit** bleibt ausgeblendet, solange die Anbindung für den Live-Betrieb nicht vollständig ist. Nutzen Sie **Anbindung**, **Live-Lesen** und die Verbindungstests auf dieser Seite.

## Bereiche der Seite



### Statusleiste

- **Silent-Modus:** Steuerwerte werden nicht an den Hub geschrieben; nur Sollwerte.
- **Live-Modus / HA-EHAL / OpenEMS-EHAL:** `main.py` sendet an den gewählten Hub.
- **Letzter main.py-Lauf:** Zeitstempel und Alter.



### Live-Lesen

Nur `**sens_***` und `**get_***` (Messwerte / Eingaben). Die Tabelle listet **alle** erwarteten EHAL-Felder (Anlage + Verbraucher); ohne Binding bleibt **Mapping** leer und Status **Kein Mapping**. Spalten überall:


| Spalte          | Bedeutung                                                                                                 |
| --------------- | --------------------------------------------------------------------------------------------------------- |
| EHAL-Feld       | Kanonischer EHAL-Name (bei Verbrauchern `{id}:{feld}`)                                                    |
| Mapping         | Adresse im gewählten Backend (Loxone-Merker, HA-`entity_id`, OpenEMS-Kanal); leer wenn noch nicht gemappt |
| Wert            | Live-Wert                                                                                                 |
| Status          | OK / Warnung / Fehler / Kein Mapping                                                                      |
| Detail          | Fehlertext (bei OK leer)                                                                                  |
| Zuletzt gelesen | Zeitstempel der Abfrage                                                                                   |


**Loxone:** periodisches Lesen der konfigurierten Merker (Tabelle + **Smarthome-Merker testen**). Anlagen-Felder: `sens_ess_soc`, `sens_pv_production_active`, `sens_ess_power`, `sens_grid_power_active`, optional `sens_power_consumers`. **Verbraucher** (aus Flex-Liste und Hausprofil mit Merker): EV → `{id}:sens_evcs_`* / `{id}:get_evcs_`*; andere mit Leistung → `{id}:flex.power_name`. Kein PV-Zähler, keine `set_*` / Freigaben.

**HA / OpenEMS:** EHAL-Telemetrie über REST (nur `sens_`* / `get_`* in der Tabelle; Verbindungstest zeigt ggf. das volle JSON inkl. Envelope). Mapping = Entity bzw. Kanal; abgeleitete Hauslast: `—(abgeleitet)`. Optional Caption Live-Leistung in kW.

Einheiten und Vorzeichen: siehe §B. Vollständige Rollen-Matrix: §C.

### Live-Schreiben

Nur `**set_***`. Die Tabelle listet **alle** erwarteten Setpoint-Felder; Werte/Erfolg kommen aus dem letzten `main.py`-Lauf (`runtime/optimizer_run_state.json`), ungemappte Zeilen haben leeres **Mapping**. Gleiche Identitäts-Spalten:


| Spalte      | Bedeutung                                                               |
| ----------- | ----------------------------------------------------------------------- |
| EHAL-Feld   | `set_*` (ggf. `{id}:set_…` bei EV)                                      |
| Mapping     | Merker / HA-Entity / OpenEMS-Schreibkanal; leer wenn noch nicht gemappt |
| Wert        | Geschriebener Sollwert                                                  |
| Erfolg      | Ja / Nein                                                               |
| Gesendet um | Zeitstempel                                                             |
| Meldung     | Fehlertext bzw. Silent-Hinweis                                          |


- **Loxone:** Trace `loxone_writes` (IO-Name wird auf `set_`* zurückgeführt); Silent: geplante Sollwerte aus `loxone_sent` mit Status „Nicht gesendet“.
- **HA / OpenEMS:** `ehal_writes` (Feld, Wert, Erfolg, Zeit, Meldung); Fehlerbanner aus `runtime/ehal_write_error.json`.



### HA Entity → EHAL Mapping

Nur bei Backend **Home Assistant**: Entities scannen, Telemetrie-/Setpoint-Felder zuweisen, speichern. Die Felder sind nach **Geräterollen** gruppiert (Netz / PV / Batterie / Wallbox; Vorlagen unter `share/ehal/roles/`).

- Überblick / HITL: [Home Assistant + evcc](../einrichtung/ha-evcc.md) (Abschnitt *Wenn marq24 / evcc bereits in HA verbunden ist*)
- Lab-Abnahme inkl. Stub-Werte und Tabelle: [HA-Lab Spec §5.1](../spec/ha-lab-setup.md#51-after-marq24-ha-evcc-is-connected-lab-follow-up)



### Loxone Struktur → EHAL Mapping

Nur bei Backend **Loxone**: Entity-zentrierter Assistent (Backlog **2.4.k**, Struktur-Scan aus **2.4.f**). Entities = **Anlage (Plant)** + Verbraucher aus dem **Live-Hausprofil** (gleiches Shape wie Earnie-Entities). Mapping-Zeilen: `{entity}.{ehal_field}` → Merkername; Felder nach Geräterollen / §C (inkl. EV `set_evcs_max_current` / `get_evcs_limit_soc`, optional `sens_power_consumers`, C.4 `flex.`*).

1. **Alle Quellen testen** — Research-Vergleich (noch keine feste Produktions-Quelle): **LoxAPP3.json** und optional **Loxone MCP 17.1** (Base-URL). Die frühere HTTP-Probe bereits konfigurierter Merker entfällt. Bei `connect.loxonecloud.com/…/mcp`: unauthentifizierter GET (307→Relay), danach **headless OAuth 2.1** mit `LOXONE_USER`/`LOXONE_PASS`, dann Namensauflösung über MCP-Tools. Mapping-Dropdowns standardmäßig **Union**.
2. **Optional KI-Vorschlag** — lokales [Ollama](https://ollama.com/) (`http://127.0.0.1:11434`, Modell z. B. `llama3.2`). Ollama ist **nicht** im Earnie-Container / LoxBerry-Plugin enthalten.
3. **Human-in-the-Loop** — Entity wählen, EHAL-Felder zuweisen (Select-Label: **Bedeutung** plus EHAL-Value-Name, z. B. `Netzleistung (sens_grid_power_active)`); darunter **Event-Trigger** je Entity (`id`, `ehal_field`, `signal_type`, `on_change`, `label`). Die Merker-Adresse kommt aus dem Binding des gewählten Feldes.
4. **Speichern** — schreibt `plant.ehal_bindings` / `consumers[].ehal_bindings` sowie `event_triggers` in `house_profiles.json`. Beim ersten Migrate/Save werden `system.event_triggers` geleert und Anlagen-Rollen aus `loxone_blocks` entfernt (FTP-/Log-Schlüssel bleiben).

**Energieflussmonitor → Hausprofil (Interpretation C):** Auto-Sync = Backlog **2.4.l**. Manueller Blueprint: siehe Plan `energieflussmonitor_hausprofil_blueprint_a` im Repo.

Bindings werden **nicht** mehr im Hauskonfigurator unter „Smarthome-Merker“ editiert — nur noch hier auf EHAL-Com. Siehe [Loxone-Signale](../referenz/loxone-signale.md).

## Silent-Modus vs. Live-Modus


|                           | Silent-Modus                        | Live-Modus                  |
| ------------------------- | ----------------------------------- | --------------------------- |
| Lesen                     | Immer aktiv (auch auf dieser Seite) | Immer aktiv                 |
| Schreiben durch `main.py` | Nein                                | Ja                          |
| Schreib-Tabelle           | Nur Sollwerte                       | Wert + Erfolg + Zeitstempel |
| Typischer Einsatz         | Tests, paralleler Legacy-Betrieb    | Produktiv nach Cutover      |


Silent-Modus: `runtime/local_settings.json` → `"loxone_silent_mode"` (Priorität vor `system.loxone_silent_mode`). Standard ohne Datei: **Silent an**.

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

