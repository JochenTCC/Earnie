# Loxone-Signale und Earnie-Library

## Motivation

Diese Seite ist die **eine** Anwender-Referenz für die Loxone-Anbindung von Earnie:

1. **Library einrichten** — Virtual-HTTP-In/Out-Vorlagen aus `share/loxone/templates/` in Loxone Config, EFM-Zähler, Earnie-Totmann-Fallback und Loxone-Import ins Hausprofil.
2. **Signal-Vertrag** — welche Merker-**Titles** und EHAL-Rollen (`ehal_bindings`) zusammengehören (Default-Namen aus `greenfield_device_map.json` / Recipes).

Ohne stabile Titles und Bindings kann Earnie die Anlage weder zuverlässig lesen noch steuern. HTTP-Zugang und Betrieb: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md). Mapping-UI: [EHAL-Com](../ui/ehal-com.md). Templates-README: [`share/loxone/templates/README.md`](../../share/loxone/templates/README.md).

**Begriffsklärung (Smarthome-Merker):** Die **Adresse** (Zeichenkette, z. B. `Earnie_Waermepumpe_Freigabe`) ist ein *Smarthome-Merker*. Die **Rolle** ist der EHAL-Feldname (`sens_ess_soc`, `flex.{slug}.sens_power_act`, …) in `ehal_bindings`. Nicht verwechseln mit Chart-Markern oder `earnie_role` (Bekannt/Gesteuert/Manuell).

In der Doku heißt der kanonische Vorlagen-/Import-Pfad **Default** (früher oft „Greenfield“). Die Datei `share/loxone/greenfield_device_map.json` behält ihren Dateinamen.

---

## Überblick Pattern B

| Richtung        | Baustein                                | Rolle                                                                       |
| --------------- | --------------------------------------- | --------------------------------------------------------------------------- |
| Earnie → Loxone | **Virtual HTTP In** (`VI_Earnie_*.xml`) | Earnie pollt Status/Sollwerte/Freigaben in **benannte Merker** (`Earnie_`*) |
| Loxone → Earnie | **Virtual Out** (`VO_Earnie_*.xml`)     | optionaler Push (Telemetrie); Core liest weiterhin `/jdev/sps/io/{Name}`    |
| Zähler          | EFM / Meter                             | Netz/PV/Batterie-/Flex-**Leistung** bevorzugt über EFM-Bezeichnung          |


Earnie Core schreibt und liest dieselben Merker-Namen am Miniserver. Die Library ergänzt die **Loxone-seitige** HTTP-Spiegelung und ermöglicht einen **Earnie-tot**-Fallback in Config (siehe unten).

**Virtual Inputs** = Earnie→Loxone (`set_*` / Freigaben / Sollwerte, Heartbeat) über `GET http://<Earnie>:8541/ehal/loxone/status.json` (Daemon-HTTP; `heartbeat_ts` = Unix-Jetztzeit, Sollwerte aus dem letzten `loxone_sent`).

**Virtual Outputs** = optional Loxone→Earnie Push von `sens_*` / `get_*` / Flex-Leistung (Platzhalter-URLs). Core schreibt/liest weiterhin `/jdev/sps/io/{name}`.

**Freigabe-Cmds (0/1) müssen analog sein:** In den VI-Templates ist `Analog="true"` gesetzt. In Config **nicht** „Als digitalen Eingang“ / Digital-Modus wählen — sonst pulst der Eingang bei **jedem** Poll kurz auf `1`, auch wenn `status.json` dauerhaft `0` liefert. Sticky 0/1 kommt nur im Analog-Modus aus dem `\v`-Wert.

### Drei Schichten (Title / Check / VO-Pfad)


| Schicht                               | Wo                        | Beispiel Flex                                           | Beispiel EV                                              |
| ------------------------------------- | ------------------------- | ------------------------------------------------------- | -------------------------------------------------------- |
| **Miniserver-Title**                  | Cmd Title (jdev / Import) | `Earnie_Verbraucher_Waschmaschine_Freigabe`             | `Earnie_EAuto_Garage_Soll_A`                             |
| **Virtual-Input Check / Status-JSON** | Virtual In Check-Muster   | `flex.{hk_id}.Earnie_Verbraucher_Freigabe`              | `ev.{ev_id}.Earnie_EAuto_Soll_A`                         |
| **Virtual-Output Befehl bei Ein**     | Virtual Out URL           | `/ehal/loxone/telemetry/flex.{hk_id}.sens_power_act/\v` | `/ehal/loxone/telemetry/ev.{ev_id}.sens_evcs_soc_act/\v` |


`{hk_id}` / `{ev_id}` = Hausprofil-Entity-`id` (snake_case). Templates lassen die Platzhalter stehen — in Config ersetzen.

---

## Library einrichten

<a id="library-einrichten"></a>

Nach dem Einbau in Loxone Config liefert der **Loxone-Import** auf [EHAL-Com](../ui/ehal-com.md) / im Hauskonfigurator typisierte Hausprofil-Entities und Merker-Bindings.

### 1. Vorlagen in Loxone Config kopieren

Nur die `.xml`-Dateien kopieren (nicht `README.md`, keinen ganzen Ordnerbaum als Unterordner verschachteln).

#### VirtualIn

Quelle: `share/loxone/templates/VirtualIn/`


| Datei                    | Inhalt (Kurz)                       |
| ------------------------ | ----------------------------------- |
| `VI_Earnie_Plant.xml`    | Heartbeat + ESS Design-C1-Sollwerte |
| `VI_Earnie_Heatpump.xml` | `Earnie_Waermepumpe_Freigabe`       |
| `VI_Earnie_EV.xml`       | E-Auto Sollstrom / Modus            |
| `VI_Earnie_Consumer.xml` | generische Freigabe + Ziel_kW       |
| `VI_Earnie_Pool.xml`     | Pool- / Filter-Freigabe             |


Zielordner (eines der vorhandenen Config-Pfade; Ordner ggf. anlegen):

- `%ProgramData%\Loxone\Loxone Config\<Version>\Template\VirtualIn\`
- oder `Documents\Loxone\Loxone Config\Templates\VirtualIn\`

#### VirtualOut

Quelle: `share/loxone/templates/VirtualOut/`


| Datei                    | Inhalt (Kurz)                                              |
| ------------------------ | ---------------------------------------------------------- |
| `VO_Earnie_Status.xml`   | optional alive / `Earnie_Request_Optimize` (Port **8541**) |
| `VO_Earnie_Plant.xml`    | Plant `sens_*`, Außentemperatur                            |
| `VO_Earnie_EV.xml`       | EV-Telemetrie                                              |
| `VO_Earnie_Heatpump.xml` | `Earnie_Waermepumpe_Leistung`                              |
| `VO_Earnie_Consumer.xml` | Flex-Leistung                                              |
| `VO_Earnie_Pool.xml`     | Pool-Telemetrie                                            |


Ziel: entsprechender Ordner `VirtualOut`.

Danach **Loxone Config neu starten**. Die Vorlagen erscheinen unter Peripherie / Device Templates (Virtual In / Virtual Out).

### 2. Earnie-Adresse setzen

In jedem eingefügten Virtual-In/Out den Platzhalter `EARNIE_HOST` durch die LAN-IP bzw. den Hostnamen von Earnie ersetzen. UI/Streamlit typisch Port **8501**; **Daemon-HTTP** (Virtual In Status, `Earnie_Request_Optimize` / Alive) nutzt Port **8541** (`system.ehal_loxone_http_port`). Siehe [Streamlit-Ports](streamlit-ports.md).

Beispiel Virtual In Address (Pattern B Status-JSON):

`http://192.168.178.10:8541/ehal/loxone/status.json`

Virtual Out Address **Status / Request Optimize**:

`http://192.168.178.10:8541`

Andere Telemetrie-VO-Drafts können noch `:8501` als Platzhalter tragen, bis die Endpunkte existieren.

Polling / Cmd-Check-Muster an die JSON-Keys anpassen (Plant: `set_ess_*` / `heartbeat_ts`; Flex/EV: `flex.{hk_id}.…` / `ev.{ev_id}.…`). Stabile **Titles** bleiben der Vertrag für Core und Default-Import.

### 3. Geräte einfügen und Merker belassen

1. Pro Rolle die passende Vorlage einmal (oder mehrfach bei mehreren Flex-Verbrauchern) einfügen.
2. Cmd-**Titles** nicht willkürlich umbenennen — sie müssen zu [`greenfield_device_map.json`](../../share/loxone/greenfield_device_map.json) und den Tabellen unten passen.
3. **Mehrere Flex-Verbraucher / E-Autos:** Titles nach Schema Prefix+Instanz-ID; VI-Check und VO-Pfad mit `{hk_id}` / `{ev_id}` (siehe [Namenskonvention](#mehrere-flex-verbraucher-namenskonvention)).
4. Programm auf den Miniserver speichern / laden.

### 4. Zähler und Energieflussmonitor (EFM)

Die Templates enthalten **keine** Zähler-Hardware. Dennoch werden verwendete Zähler-Bausteine mit importiert. Damit das funktioniert, in der Loxone Config:

1. Zähler mit **eindeutiger, stabiler Bezeichnung** anlegen bzw. belassen.
2. Zähler dem **Energieflussmonitor** zuordnen (Netz / PV / Batterie / Lasten).
3. Residual-/Rest-Knoten nicht als eigener Flex-Verbraucher verwenden (Import überspringt typische Rest-Labels).

Leistungs-Merker (`Earnie_Netzleistung`, `Earnie_PV_Leistung`, …) **dürfen** vom EFM kommen; die Virtual-Output-Cmds bleiben optionaler Namenskatalog. Earnie bevorzugt die EFM-Bezeichnung im Binding, wenn vorhanden.

Manuelle Nacharbeit: EHAL-Com → **Energieflussmonitor → Verbraucher**.

**E-Auto FertigUm:** Loxone-Import bindet **Wecker**-Bausteine an `get_evcs_ready_by_time` auf dem EV-Entity, das bereits Zähler-/Leistungs-Bindings hat — gleiche Konvention wie Zähler-Bezeichnung, kein Virtual-Out-Text.

Earnie liest **SpecialState10** (`nextEntryTime`) über `/jdev/sps/io/{name}/all` (Unix = Wert + 1230768000); Ausgang **Tna** bleibt Text-Backup.

### 5. Earnie-Totmann-Schaltungs-Fallback (in Loxone Config)

<a id="earnie-tot-fallback-in-loxone-config"></a>

Ziel: Wenn Earnie nicht erreichbar ist oder Virtual In nicht mehr aktualisiert wird, muss der Miniserver die letzten **Earnie-Sollwerte ignorieren** und lokale Regeln fahren.

Empfohlener Ablauf (Logikbausteine in Config, kein Earnie-Code):

1. **Watchdog** auf `Earnie_Heartbeat` (Unix-Zeitstempel aus `VI_Earnie_Plant`): Alter = jetzt − Heartbeat (bzw. „Wert seit x Sekunden unverändert“).
2. Schwelle wählen (z. B. 2–3× PollingTime der Virtual In, typisch ≥ 90 s bei 30 s Poll).
3. Bei **aktivierter Totmann-Schaltung**:
   - `Earnie_Steuerbefehl` / ESS-Modus lokal auf **Automatik** (`0`) bzw. sichere ESS-Regeln der Anlage setzen
   - Flex-**Freigaben** (`Earnie_*_Freigabe`) auf `0` (gesperrt) oder bekannte Notfall-Logik
   - E-Auto-Sollwerte nicht mehr aus Earnie-Merker übernehmen
4. Wenn **Earnie „lebt“**: Earnie-Merker wie vorgesehen an Aktorik / Programm weiterreichen.

Earnie Core bleibt unverändert auf Miniserver-IOs; der Fallback ist **nur** Config-Logik um die Merker herum.

### 6. Loxone-Import in Earnie

Voraussetzung: Earnie-Templates in der Loxone Config und pro Verbraucher ein Zählerbaustein (EFM); Zugangsdaten unter **EHAL-Com → Anbindung**. Der Import-Button ist erst aktiv, wenn der Miniserver erreichbar ist.

1. **Hauskonfigurator → Hausprofil**: Kapitel **Loxone-Import** oberhalb von **Verbraucher** — bei Erstsetup steht **Nein — manuell fortfahren** in derselben Zeile wie der Import-Button.
2. Earnie lädt `LoxAPP3.json`, prüft `Earnie_*` per HTTP-Probe (auch Prefix+Slug, case-insensitive), legt typisierte Entities an und bindet EFM-Zähler mit ein.
3. Signal-Zuordnung auf **EHAL-Com** prüfen ([Loxone Struktur → EHAL Mapping](../ui/ehal-com.md#loxone-struktur--ehal-mapping)); Parameter (kWh, Fahrpläne, Wohnfläche, …) im **Hauskonfigurator** nachziehen.

### Checkliste Library

- [ ] `VI_` / `VO_` XMLs in Config-Template-Ordner kopiert, Config neu gestartet
- [ ] `EARNIE_HOST` gesetzt; Geräte eingefügt; Titles stabil
- [ ] Mehrfach-Verbraucher / E-Autos: Slug-Titles + Check/VO `{hk_id}` / `{ev_id}` (falls genutzt)
- [ ] Zähler am EFM mit eindeutigen Bezeichnungen
- [ ] Programm auf Miniserver
- [ ] Optional: Heartbeat-Watchdog + Fallback programmiert
- [ ] Hauskonfigurator: Loxone-Import → Mapping auf EHAL-Com prüfen → Parameter im Hausprofil

---

## HTTP-Marker-Probe (für Binding und Import)

Die Template-Cmd-Titel sind **bekannt** (`greenfield_device_map.json`). Earnie kann sie per `GET /jdev/sps/io/{Name}` prüfen, **ohne** dass die Bausteine in der Loxone-App-Visualisierung stehen müssen:


| `LL.Code` | Bedeutung für den Import                                                                                          |
| --------- | ----------------------------------------------------------------------------------------------------------------- |
| `200`     | Name vorhanden und lesbar                                                                                         |
| `403`     | Name auf dem Miniserver bekannt, für den User nicht lesbar (häufig bei Virtual HTTP In) — zählt als **vorhanden** |
| `404`     | Name unbekannt / nicht hochgeladen                                                                                |


Default-Import: LoxAPP3-Namen **union** Probe-Treffer. EFM-Zähler weiterhin aus `LoxAPP3.json`.

## Mehrere Flex-Verbraucher (Namenskonvention)

<a id="mehrere-flex-verbraucher-namenskonvention"></a>

Ein Template `VI_Earnie_Consumer` / `VO_Earnie_Consumer` deckt **einen** Verbraucher ab. Miniserver-Bezeichnungen müssen eindeutig sein. Der Hausprofil-`id` (klein, snake_case, z. B. `waschmaschine`) ist der kanonische **Entity-Slug** (`{hk_id}`).


| Signal   | Merker-Title (1. / weitere)                                          | VI Check / VO-Pfad                                |
| -------- | -------------------------------------------------------------------- | ------------------------------------------------- |
| Leistung | `Earnie_Verbraucher_Leistung` → `Earnie_Verbraucher_<Slug>_Leistung` | VO: `flex.{hk_id}.sens_power_act`                 |
| Freigabe | `Earnie_Verbraucher_Freigabe` → `…_<Slug>_Freigabe`                  | Check: `flex.{hk_id}.Earnie_Verbraucher_Freigabe` |
| Ziel kW  | `Earnie_Verbraucher_Ziel_kW` → `…_<Slug>_Ziel_kW`                    | Check: `flex.{hk_id}.Earnie_Verbraucher_Ziel_kW`  |


**Beispiel Waschmaschine** (`id` = `waschmaschine`):

- Title: `Earnie_Verbraucher_Waschmaschine_Leistung`
- VO Befehl bei Ein: `/ehal/loxone/telemetry/flex.waschmaschine.sens_power_act/\v`
- VI Check (Freigabe): `"flex.waschmaschine.Earnie_Verbraucher_Freigabe":\v` (Title bleibt `Earnie_Verbraucher_Waschmaschine_Freigabe`)
- EHAL-Com Binding: `flex.{hk_id}.sens_power_act` → Title (bei `zaehler_<slug>`: Wire-Slug ohne `zaehler_`)

`<Slug>` **im Merker:** kurzer stabiler Token (z. B. `Waschmaschine`). `{hk_id}`: gleicher Consumer wie im Hausprofil.

## Mehrere E-Autos (Namenskonvention)

Analog: Prefix `Earnie_EAuto_`, Entity-`id` = `{ev_id}` (z. B. `eauto`, `garage`).


| Signal           | Merker-Title (1. / weitere)                          | VI Check / VO-Pfad                      |
| ---------------- | ---------------------------------------------------- | --------------------------------------- |
| Soll A           | `Earnie_EAuto_Soll_A` → `Earnie_EAuto_<Slug>_Soll_A` | Check: `ev.{ev_id}.Earnie_EAuto_Soll_A` |
| Modus            | `Earnie_EAuto_Modus` → `…_<Slug>_Modus`              | Check: `ev.{ev_id}.Earnie_EAuto_Modus`  |
| Leistung         | `Earnie_EAuto_Leistung` → `…_<Slug>_Leistung`        | VO: `ev.{ev_id}.sens_evcs_active_power` |
| weitere sens/get | `Earnie_EAuto_*` → `…_<Slug>_*`                      | VO: `ev.{ev_id}.<ehal_field>`           |


Wärmepumpe: Titles `Earnie_Waermepumpe_Leistung` / `Earnie_Waermepumpe_Freigabe`; VO/Check mit `flex.{hk_id}` (Default-`id` `wp_heating`). Pool: `flex.pool.sens_power_act` bzw. `{hk_id}`.

**Import:** Default matcht **case-insensitive** exakte Template-Namen und **Prefix+Slug** (z. B. `Earnie_Verbraucher_Waschmaschine_Leistung` → Consumer `waschmaschine`; `Earnie_EAuto_Garage_Soll_A` → EV `garage`). Bindings behalten die Miniserver-Schreibweise.

In Config: Template einfügen → Cmd-Titles + VO-Pfad `{id}` setzen → auf Miniserver speichern.

Prüfung aller konfigurierten Signale:

```powershell
.venv\Scripts\python.exe -m scripts.verify_loxone_setup
.venv\Scripts\python.exe -m scripts.verify_swimspa_filter_live
```

---

## Rolle ↔ Entity (Überblick)


| Entity / Bereich                                                     | Speicherort                                   | Typische EHAL-Felder / Rollen                                                                                                                            |
| -------------------------------------------------------------------- | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Anlage (Batterie, PV, Netz, Steuerbefehl, Hauslast, Außentemperatur) | `house_profiles.json` → `plant.ehal_bindings` | `sens_ess_soc`, `sens_pv_production_active`, `sens_ess_power`, `sens_grid_power_active`, `sens_temperature_outside`, `sens_power_consumers`, `set_ess_*` |
| Request Optimize (außerplanmäßig)                                    | Loxone VO → Daemon-HTTP                       | `Earnie_Request_Optimize` auf Port `system.ehal_loxone_http_port` (Standard **8541**)                                                                    |
| Wärmepumpe / Flex / Thermal                                          | `consumers[].ehal_bindings`                   | `flex.{slug}.sens_power_act`, `flex.{slug}.set_enable`, `flex.{slug}.set_power_setpoint`                                                                 |
| E-Auto (`ev`)                                                        | `consumers[].ehal_bindings`                   | `sens_evcs_*`, `get_evcs_*`, `set_evcs_*`                                                                                                                |
| Pool / SwimSpa                                                       | `consumers[].ehal_bindings` + Filter-Entity   | siehe Default `Earnie_Pool_*` / EHAL-Com §C.6                                                                                                            |


Bearbeitung in der UI: **nur** unter **Daemon Control → EHAL-Com → Loxone Struktur → EHAL Mapping** (Entity wählen). Der Hauskonfigurator editiert keine Merker-Adressen mehr.

## Zentrale Signale (`plant.ehal_bindings`)

Default-Namen (2.4.n). Netz/PV/Batterie-**Leistung** bevorzugt über EFM-Zähler-Bezeichnung.


| EHAL-Feld                       | Richtung  | Default-Name                                  | Wert / Einheit                                                                        |
| ------------------------------- | --------- | --------------------------------------------- | ------------------------------------------------------------------------------------- |
| `sens_ess_soc`                  | Lesen     | `Earnie_Batterie_SoC`                         | Batterie-SOC, %                                                                       |
| `sens_pv_production_active`     | Lesen     | `Earnie_PV_Leistung` (oder EFM Production)    | PV-Leistung, kW                                                                       |
| `sens_ess_power`                | Lesen     | `Earnie_Batterie_Leistung` (oder EFM Storage) | Batterie; EHAL: +Entladung                                                            |
| `sens_grid_power_active`        | Lesen     | `Earnie_Netzleistung` (oder EFM Grid)         | Netz: +Bezug, kW                                                                      |
| `sens_power_consumers`          | Lesen     | (optional)                                    | Hauslast; sonst Ableitung                                                             |
| `sens_temperature_outside`      | Lesen     | `Earnie_Aussentemperatur`                     | Außentemperatur °C (hausweit; WP/Pool)                                                |
| `set_ess_active_power`          | Schreiben | `Earnie_Batterie_Sollleistung`                | Forced Leistung, kW; `+` Entladung, `−` Ladung                                        |
| `set_ess_charge_power_limit`    | Schreiben | `Earnie_LadeLeistungs-Limit`                  | Max. Ladeleistung (echte Grenze)                                                      |
| `set_ess_discharge_power_limit` | Schreiben | `Earnie_EntladeLeistungs-Limit`               | Max. Entladeleistung (echte Grenze)                                                   |
| `set_ess_mode`                  | Schreiben | `Earnie_Steuerbefehl`                         | Sticky: immer schreiben; `0` = Automatik (Sollleistung ignorieren); OpenEMS ignoriert |
| *(Watchdog)*                    | Lesen     | `Earnie_Heartbeat`                            | Pattern B; kein EHAL-Feld                                                             |


Legacy-Rollenamen (`soc_name`, `pv_power_name`, …) in `loxone_blocks` sind entfernt — nur `plant.ehal_bindings` mit §C-Feldnamen.

**Sticky Merker:** Loxone behält den zuletzt geschriebenen Wert. Automatik ist `set_ess_mode = 0` — Config darf Sollleistung bei Modus 0 nicht anwenden, auch wenn `Earnie_Batterie_Sollleistung` noch einen alten Wert hält.

## Flexible Verbraucher — `ehal_bindings` am Consumer

Die Definition der Steuerungssignale steht im aktiven Hausprofil (`house_profiles.json`). Merker liegen unter `ehal_bindings` mit EHAL-Feldnamen. Bestehende Profile ohne Bindings: `python -m scripts.migrate_ehal_bindings --path <house_profiles.json> [--config <config.json>]`.

### Flex / Thermal (Stub `flex.*`)


| EHAL-Feld                        | Richtung  | Default / Beispiel                                                                       | Wert        |
| -------------------------------- | --------- | ---------------------------------------------------------------------------------------- | ----------- |
| `flex.{slug}.sens_power_act`     | Lesen     | WP: `Earnie_Waermepumpe_Leistung`; Generic: `Earnie_Verbraucher_Leistung`; oder EFM Load | kW oder 0/1 |
| `flex.{slug}.set_enable`         | Schreiben | WP: `Earnie_Waermepumpe_Freigabe`; Generic: `Earnie_Verbraucher_Freigabe`                | `0`/`1`     |
| `flex.{slug}.set_power_setpoint` | Schreiben | `Earnie_Verbraucher_Ziel_kW` (optional)                                                  | kW-Sollwert |


Pool-Freigaben: Default `Earnie_Pool_Freigabe` / `Earnie_Pool_Filter_Freigabe` in `ehal_bindings`.

### E-Auto (Prefix `Earnie_EAuto_`)


| EHAL-Feld                  | Richtung  | Default-Name                                                                                      | Wert                                                                                                                                                                                                      |
| -------------------------- | --------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sens_evcs_active_power`   | Lesen     | `Earnie_EAuto_Leistung` (oder EFM Load; dual `flex.{slug}.sens_power_act`)                        | kW                                                                                                                                                                                                        |
| `sens_evcs_connected`      | Lesen     | `Earnie_EAuto_Angeschlossen`                                                                      | `1` = angeschlossen                                                                                                                                                                                       |
| `sens_evcs_soc_act`        | Lesen     | `Earnie_EAuto_SOC`                                                                                | Aktueller SOC, %                                                                                                                                                                                          |
| `sens_evcs_bat_capacity`   | Lesen     | `Earnie_EAuto_Kapazitaet`                                                                         | kWh                                                                                                                                                                                                       |
| `get_evcs_nominal_current` | Lesen     | `Earnie_EAuto_MaxStrom`                                                                           | A                                                                                                                                                                                                         |
| `get_evcs_ready_by_time`   | Lesen     | AlarmClock-**Bezeichnung** (z. B. `Ladewecker` / `Wecker_Smart`; Import merged auf EV mit Zähler) | **SpecialState10** (`nextEntryTime`, Loxone-Sekunden seit 01.01.2009 → Unix `+ 1230768000`) via `/jdev/sps/io/{name}/all`. Backup: Ausgang **Tna** (Text z. B. `Morgen, 11:00`). Kein Virtual-Out-String. |
| `get_evcs_limit_soc`       | Lesen     | `Earnie_EAuto_LimitSOC`                                                                           | Ladeziel-SOC %                                                                                                                                                                                            |
| `set_evcs_max_current`     | Schreiben | `Earnie_EAuto_Soll_A`                                                                             | Soll-/Maxstrom A                                                                                                                                                                                          |
| `set_evcs_mode`            | Schreiben | `Earnie_EAuto_Modus`                                                                              | `off`=0                                                                                                                                                                                                   |


Zusätzlich Pflichtfeld `min_power_kw` am Verbraucher. Pool-Filter: Hausprofil-Verbraucher `pool_filter` mit EHAL-Rollen (`get_filter_remaining_hours` u. a.) unter `ehal_bindings`. Default-Prefix `Earnie_Pool_*` / `Earnie_Pool_Filter_*` (siehe [ehal-com.md](../ui/ehal-com.md) §C.6). EV-Modus: nur `set_evcs_mode` (`Earnie_EAuto_Modus`) — kein Schreiben von `pv_follow` / Sofort-Command-Merkern.

## Request Optimize (außerplanmäßige Läufe)

Außerplanmäßige Optimierungsläufe in `main.py` (zwischen den Viertelstunden) über Loxone → Earnie HTTP.


| Element                         | Bedeutung                                                                              |
| ------------------------------- | -------------------------------------------------------------------------------------- |
| Virtual Out                     | Vorlage `share/loxone/templates/VirtualOut/VO_Earnie_Status.xml`                       |
| Address                         | `http://EARNIE_HOST:8541` (Port = `system.ehal_loxone_http_port`, Standard **8541**)   |
| Cmd `Earnie_Request_Optimize`   | `POST /ehal/loxone/request_optimize` — weckt den Daemon vor der nächsten Viertelstunde |
| Cmd `Earnie_Push_Alive` / Alive | `GET /ehal/loxone/alive` — Erreichbarkeitscheck                                        |


Compose-Produktiv-Stacks veröffentlichen den Container-Port **8541** (siehe [Streamlit-Ports](streamlit-ports.md)).

## Beispiel-Mapping


| Verbraucher (`id`) | Steuerung (Schreiben)                                    | Leistung (Lesen)                                             |
| ------------------ | -------------------------------------------------------- | ------------------------------------------------------------ |
| `swimspa` / Pool   | `flex.{slug}.set_enable` → `Earnie_Pool_Freigabe`        | `flex.{slug}.sens_power_act` → `Earnie_Pool_P_act`           |
| `ev`               | `set_evcs_max_current` / `set_evcs_mode`                 | `sens_evcs_*` / `flex.{slug}.sens_power_act`                 |
| `wp_heating`       | `flex.{slug}.set_enable` → `Earnie_Waermepumpe_Freigabe` | `flex.{slug}.sens_power_act` → `Earnie_Waermepumpe_Leistung` |


## Lesen vs. Schreiben in `main.py`


| Phase       | Aktion                                           |
| ----------- | ------------------------------------------------ |
| Einlesen    | SOC, Leistungen, PV, Flex-Inputs, E-Auto-Status  |
| Optimierung | MILP über 24 h (15-Min-Slots intern)             |
| Schreiben   | ESS-Limits / Modus, Freigaben / EV-Strom je Slot |


Die App **liest** dieselben Live-Werte für Anzeige; **schreibt** Steuerwerte nur im Live-Modus. Merker-Zuordnung: [EHAL-Com](../ui/ehal-com.md).

Weitere Details: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md) · [Abkürzungen](abkuerzungen.md).
