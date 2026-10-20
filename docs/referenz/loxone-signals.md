# Loxone-Signale und Earnie-Library

## Motivation

Diese Seite ist die zentrale Referenz für die Loxone-Anbindung von Earnie. Sie behandelt zwei Themen:

1. **Library-Einrichtung:** Virtual-HTTP-In/Out-Vorlagen aus `share/loxone/templates/` in Loxone Config einspielen, EFM-Zähler, die Earnie-Dead-Man-Rückfallebene und den Loxone-Import ins Hausprofil.
2. **Signalvertrag:** Welche Merker-**Titel** und EHAL-Rollen (`ehal_bindings`) zusammengehören (Standardnamen aus `greenfield_device_map.json` und den Rezepten).

Ohne stabile Titel und Bindings kann Earnie die Anlage weder zuverlässig lesen noch steuern. Verwandte Seiten:

- HTTP-Zugriff und Betrieb: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md)
- Signalliste / Export: [EHAL-Com](../ui/ehal-com.md)
- Vorlagendateien und Generatoren: [`share/loxone/templates/README.md`](../../share/loxone/templates/README.md)

**Begriffe (Smarthome-Merker):** Die **Adresse** (ein String, z. B. `Earnie_Waermepumpe_Freigabe`) ist ein *Smarthome-Merker*. Die **Rolle** ist der EHAL-Feldname (`sens_ess_soc`, `flex.{slug}.sens_power_act`, …) in `ehal_bindings`. Ein Merker ist nicht zu verwechseln mit Chart-Markern oder mit `earnie_role` (Bekannt/Gesteuert/Manuell).

Diese Seite nennt den kanonischen Vorlagen- und Importweg **Default** (früher oft „Greenfield“). Die Datei `share/loxone/greenfield_device_map.json` behält ihren Namen.

---

<a id="entity-scoped-overview"></a>

## Überblick

| Richtung        | Baustein                                | Aufgabe                                                                                           |
| --------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Earnie → Loxone | **Virtual HTTP In** (`VI_Earnie_*.xml`) | Loxone fragt `status.json` von Earnie ab; Sollwerte, Freigaben und Heartbeat landen in den benannten VI-Cmds (`Earnie_*`) |
| Loxone → Earnie | **Virtual Out** (`VO_Earnie_*.xml`)     | Loxone sendet Telemetrie in die Earnie-Inbox (qualifizierte EHAL-ID); kein Merker-Poll für gebundene `sens_*` / `get_*` |
| Zähler          | EFM / Meter                             | **Leistung** von Netz, PV, Batterie und Flex, bevorzugt über die EFM-Bezeichnung                  |

Die Library ergänzt die **Loxone-seitige** HTTP-Spiegelung und eine **Earnie-tot**-Rückfallebene in Config (siehe [Earnie-Dead-Man-Rückfallebene](#earnie-dead-fallback-in-loxone-config)).

**Virtual Inputs (Earnie → Loxone):** Sollwerte, Freigaben und Heartbeat liefert der Daemon über `GET http://<Earnie>:8541/ehal/loxone/status.json`. `heartbeat_earnie` ist die aktuelle Unix-Zeit; die Sollwerte stammen aus dem Publish-Ledger (`loxone_sent`). Schreibzugriffe sind **Push-only**: Earnie ruft für Zyklus-Sollwerte nicht `/dev/sps/io/<Merker>/<Wert>` auf. `status.json` veröffentlicht ausschließlich qualifizierte Check-Schlüssel.

**Virtual Outputs (Loxone → Earnie):** Loxone sendet `sens_*` / `get_*` / Flex-Leistung unter qualifizierten Pfad-IDs. Der Core liest diese Felder aus der Push-Inbox.

**Freigabe-Cmds (0/1) müssen analog sein.** Die VI-Vorlagen setzen `Analog="true"`. In Config darf **nicht** „als Digitaleingang“ bzw. der Digitalmodus gewählt werden. Im Digitalmodus springt der Eingang bei **jedem** Poll kurz auf `1`, auch wenn `status.json` dauerhaft `0` liefert. Ein dauerhaftes 0/1 entsteht nur über den Wert `\v` im Analogmodus.

### Drei Ebenen (Titel / Check / VO-Pfad)

| Ebene                                  | Ort                       | Flex-Beispiel                                            | EV-Beispiel                                               |
| --------------------------------------- | -------------------------- | --------------------------------------------------------- | ------------------------------------------------------------ |
| **Miniserver-Titel**                   | Cmd-Titel (jdev / Import) | `Earnie_Verbraucher_Waschmaschine_Freigabe`               | `Earnie_EAuto_Garage_Soll_A`                                |
| **Virtual-Input-Check / Status-JSON**  | Check-Muster am Virtual In | `consumer.{hk_id}.set_enable` (Wärmepumpe/Pool: `heatpump.` / `pool.`) | `evcs.{ev_id}.set_evcs_max_current` / `set_evcs_mode` |
| **Virtual-Output-Befehl bei Ein**      | Virtual-Out-URL           | `/ehal/telemetry/flex.{hk_id}.sens_power_act/<v>`   | `/ehal/telemetry/ev.{ev_id}.sens_evcs_soc_act/<v>`    |

`{hk_id}` / `{ev_id}` ist die `id` der Entität im Hausprofil (snake_case). Die Vorlagen belassen die Platzhalter; sie werden in Config ersetzt.

**Nur qualifizierte Checks.** `status.json` veröffentlicht qualifizierte EHAL-IDs:

- `consumer.{slug}.set_enable`, `heatpump.{slug}.set_enable`, `pool.{slug}.set_enable`
- `evcs.{slug}.set_evcs_max_current` / `set_evcs_mode`
- Anlagen-ESS-Schlüssel (ohne Präfix) und `grid.meter.*`, darunter der Schreibwert `grid.meter.set_grid_export_power_limit`
- Powerstation `ess.{id}.set_*`

Die alten Merker-Check-Schlüssel werden nicht mehr zusätzlich zu den qualifizierten ausgegeben. Die VI-Vorlagen müssen daher die qualifizierten Schlüssel verwenden (`VI_Earnie_*_v2.xml` oder generierte `VI_Earnie_*.xml`). Anlagen-Bindings bleiben ohne Präfix (`plant.ehal_bindings.set_grid_export_power_limit`).

**VI-v2- und Export-Vorlagen.** Die Library-Vorlagen `VI_Earnie_*_v2.xml` nutzen die qualifizierten Check-Schlüssel (Titel = ID bzw. Feldname; Platzhalter `{hk_id}` / `{ev_id}`). Für eine Live-Config mit echten Kennungen lassen sich Vorlagen erzeugen:

```powershell
python -m scripts.pilot_vi_template_gen --config-dir … --host … --out-dir …   # → VI_Earnie_*.xml
python -m scripts.pilot_vo_template_gen --config-dir … --host … --out-dir …   # → VO_Earnie_*.xml
```

VO-Titel leiten sich aus der qualifizierten ID ab (`Push_<id>`, Punkte durch `_` ersetzt). Weitere Optionen: [`share/loxone/templates/README.md`](../../share/loxone/templates/README.md). Schritte zur Umstellung auf Push-only-Schreiben: [`docs/ui/ehal-com.md`](../ui/ehal-com.md) § Write push-only.

---

## Library-Einrichtung

<a id="library-setup"></a>

Sind die Vorlagen in Loxone Config installiert, erzeugt der **Loxone-Import** (siehe [Schritt 6](#6-loxone-import-into-earnie)) typisierte Hausprofil-Entitäten und Merker-Bindings.

### 1. Vorlagen in Loxone Config kopieren

Nur die `.xml`-Dateien in die Vorlagenordner kopieren. `README.md` bleibt draußen, und ein ganzer Ordnerbaum wird nicht als Unterordner eingefügt.

#### VirtualIn

Quelle: `share/loxone/templates/VirtualIn/`

| Datei | Inhalt (kurz) |
| ---- | --------------- |
| `VI_Earnie_Plant_v2.xml` | Heartbeat + ESS (Titel = Feldnamen) |
| `VI_Earnie_Heatpump_v2.xml` | `heatpump.{hk_id}.set_enable` |
| `VI_Earnie_EV_v2.xml` | `evcs.*.set_evcs_*` |
| `VI_Earnie_Consumer_v2.xml` | `consumer.{hk_id}.set_enable` |
| `VI_Earnie_Pool_v2.xml` | `pool.*.set_enable` |

Für eine Config mit echten Kennungen stattdessen `VI_Earnie_*.xml` erzeugen (siehe oben).

Zielordner (einen der vorhandenen Config-Pfade verwenden; Ordner bei Bedarf anlegen):

- `%ProgramData%\Loxone\Loxone Config\<Version>\Template\VirtualIn\`
- oder `Documents\Loxone\Loxone Config\Templates\VirtualIn\`

#### VirtualOut

Quelle: `share/loxone/templates/VirtualOut/`

| Datei                     | Inhalt (kurz)                                               |
| ------------------------- | ------------------------------------------------------------ |
| `VO_Earnie_Status.xml`    | optional `Earnie_Request_Optimize` (Port **8541**)  |
| `VO_Earnie_Plant.xml`     | `grid.meter.*` (Leistung, Import-/Export-Energie, Exportgrenze), PV, Außentemperatur, Abwesenheitsmodus |
| `VO_Earnie_Battery.xml`   | Batterie-/ESS-Telemetrie und Grenzen (`ess.{slug}.*`: SoC, Leistung, Energie, `get_ess_*`) |
| `VO_Earnie_EV.xml`        | EV-Telemetrie                                                |
| `VO_Earnie_Heatpump.xml`  | `Earnie_Waermepumpe_Leistung`, `Earnie_Waermespeicher_Temp_eq`, `Earnie_Waermespeicher_Temp_low` |
| `VO_Earnie_Consumer.xml`  | Flex-Leistung                                                |
| `VO_Earnie_Pool.xml`      | Pool-Telemetrie                                               |

Ziel: der jeweilige `VirtualOut`-Ordner.

Anschließend **Loxone Config neu starten**. Die Vorlagen erscheinen unter Peripherie / Gerätevorlagen (Virtual In / Virtual Out).

### 2. Earnie-Adresse setzen

In jedem eingefügten Virtual In/Out den Platzhalter `EARNIE_HOST` durch die LAN-IP oder den Hostnamen von Earnie ersetzen. Die Streamlit-Oberfläche nutzt typischerweise Port **8501**. Das **Daemon-HTTP** (Virtual-In-Status, `Earnie_Request_Optimize`, Telemetrie-Heartbeat) nutzt Port **8541** (`system.ehal_loxone_http_port`). Siehe [Streamlit-Ports](../dev/streamlit-ports.md).

Beispiel einer Virtual-In-Adresse (Status-JSON):

`http://192.168.178.10:8541/ehal/loxone/status.json`

Virtual-Out-Adresse für **Status / Request Optimize**:

`http://192.168.178.10:8541`

Auch Telemetrie-VOs (`VO_Earnie_*` außer `Status`) zielen auf den Daemon-Port **8541**. Der Telemetrie-Push arbeitet so:

- **Empfänger:** `/ehal/telemetry/<EHAL-ID>/<Wert>`. Ist `EARNIE_PUSH_TOKEN` (Alias `EARNIE_PILOT_PUSH_TOKEN`) gesetzt, muss der Token mitgeschickt werden; ohne gesetztes Token akzeptiert Earnie Pushes ohne Authentifizierung (offenes LAN).
- **Inbox-Lesen:** Alle pushbaren `sens_*` / `get_*`-Felder werden aus der Inbox gelesen (kein Merker-Poll). Dazu zählen die **Zähler-Energiestände** `sens_pv_energy`, `sens_grid_energy_import` / `_export` und `consumer.<id>.sens_energy_total`.
- **Wiederholintervall / Null-Regel:** siehe [Push-Takt (SB-neutral)](#push-cadence-sb-neutral).
- **Heartbeat:** Der synthetische Heartbeat-VO ist immer Push.
- **FertigUm** (`ev.<id>.get_evcs_ready_by_time`): wird als Analog-VO gepusht. Bevorzugt wird ein numerischer Wert für den nächsten Eintrag. Text im Tna-Stil wie `Morgen, 07:00` wird solange er frisch ist akzeptiert und vom Optimierer geparst.
- **Wert-Platzhalter:** Ein Virtual-Output-Befehl verwendet `<v>` (im XML als `&lt;v&gt;`). `\v` ist der Platzhalter für den Virtual-**Input**-Check und kommt in einem Output als Steuerzeichen 0x0B an.

<a id="push-cadence-sb-neutral"></a>

### Push-Takt (SB-neutral)

Dieselbe Inbox-Regel gilt für **Loxone** (VO-Wiederholung) und **Home Assistant** (YAML-`time_pattern`):

| Regel | Verhalten |
| --- | --- |
| Mindest-Takt | Jedes Lesesignal mindestens alle `EARNIE_PILOT_PUSH_REPEAT_S` Sekunden pushen (Standard **10**). Frischegrenze in der Inbox: typisch 3 × Wiederholintervall. |
| Link / Heartbeat | Solange die Verbindung frisch ist (Heartbeat oder ein anderer nicht-null Analogwert kürzlich angekommen), gilt die Null-Annahme unten. |
| Verstummt (Leistung u. a.) | Bleibt ein Signal länger als die Frischegrenze aus und der Link ist frisch, nimmt Earnie **0** an. Status in Live-Lesen: `0 angenommen (verstummt)` (`STATE_ZERO_ASSUMED_SILENT`). Nie gesendet bei frischem Link: `0 angenommen (nie gesendet)`. |
| Energiezähler | Kumulierte kWh-Felder (`*energy*`) werden **niemals** als 0 angenommen. Veraltet oder nie empfangen → kein Wert (kein Slot-Ist aus erfundener Null). |
| Explizite 0 | Ein gepushter Wert `0` gilt als gehaltenes Off (`0 (gehalten)`), nicht als „verstummt“. |

> **Hinweis:** Eine HA-Automation, die nur bei Zustandsänderung pusht, meldet einen konstanten Nicht-Null-Wert nach dem Takt als 0. Deshalb periodisch pushen – nicht nur `state` trigger.

Das Polling bzw. das Cmd-Check-Muster ist an die JSON-Schlüssel anzupassen (Anlage: `set_ess_*` / `heartbeat_earnie`; Flex: `consumer.{hk_id}.…` (Wärmepumpe `heatpump.…`, Pool `pool.…`); EV: `evcs.{ev_id}.…`). Stabile **Titel** bleiben der Vertrag für Core und den Default-Import.

### 3. Geräte einfügen und Merker-Namen beibehalten

1. Die passende Vorlage einmal je Rolle einfügen (bei mehreren Flex-Verbrauchern mehrfach).
2. Cmd-**Titel** nicht beliebig umbenennen. Sie müssen zu [`greenfield_device_map.json`](../../share/loxone/greenfield_device_map.json) und den folgenden Tabellen passen.
3. **Mehrere Flex-Verbraucher / EVs:** Die Titel folgen einem Schema aus Präfix + Instanz-ID. Das VI-Check-Muster und der VO-Pfad verwenden `{hk_id}` / `{ev_id}` (siehe [Namenskonvention](#multiple-flex-consumers-naming-convention)).
4. Programm auf dem Miniserver speichern bzw. laden.

### 4. Zähler und Energy Flow Monitor (EFM)

Die Vorlagen enthalten **keine** Zählerhardware, der Import übernimmt aber auch die verwendeten Zählerblöcke. In Loxone Config:

1. Einen Zähler mit **eindeutiger, stabiler Bezeichnung** anlegen bzw. beibehalten.
2. Den Zähler dem **Energy Flow Monitor** zuordnen (Netz / PV / Batterie / Verbraucher).
3. Rest-/Differenzknoten nicht als eigenen Flex-Verbraucher verwenden. Der Import überspringt typische Restbezeichnungen.

Leistungs-Merker (`Earnie_Netzleistung`, `Earnie_PV_Leistung`, …) **können** aus dem EFM stammen; die Virtual-Output-Cmds bleiben ein optionaler Namenskatalog. Earnie bevorzugt im Binding die EFM-Bezeichnung, sofern vorhanden.

Nach **Smarthome-Backend → Loxone-Import** das Signal-Mapping auf EHAL-Com prüfen (**Signalliste**).

**EV-Fertig-bis-Zeit.** Der Loxone-Import bindet **AlarmClock**-Blöcke an `get_evcs_ready_by_time` der EV-Entität, die bereits Zähler-/Leistungs-Bindings hat (gleiche Konvention wie bei der Zählerbezeichnung). Optionaler Analog-VO: `/ehal/telemetry/ev.<id>.get_evcs_ready_by_time/<v>` (numerischer nächster Eintrag; die Inbox akzeptiert auch kurzen Text im Tna-Stil). Gebundene FertigUm-Felder nutzen immer die Push-Inbox; der frühere Merker-Poll über SpecialState10 / `/all` entfällt.

### 5. Earnie-Dead-Man-Rückfallebene (in Loxone Config)

<a id="earnie-dead-fallback-in-loxone-config"></a>

Ziel: Ist Earnie nicht erreichbar oder wird das Virtual In nicht mehr aktualisiert, soll der Miniserver die letzten Sollwerte von Earnie **ignorieren** und stattdessen lokale Regeln ausführen.

Empfohlenes Vorgehen (Logikbausteine in Config, kein Earnie-Code):

1. **Watchdog** auf dem Heartbeat-Cmd (`heartbeat_earnie` in `VI_Earnie_Plant_v2.xml`, `Earnie_Heartbeat` in der Default-Benennung; Unix-Zeitstempel): Alter = jetzt − Heartbeat, oder „Wert seit x Sekunden unverändert“.
2. **Schwelle:** z. B. 2–3 × die Polling-Zeit des Virtual In, bei 10 s Poll typischerweise ≥ 30 s.
3. **Wenn die Rückfallebene auslöst:**
   - `Earnie_Steuerbefehl` / ESS-Modus lokal auf **Automatik** (`0`) setzen oder die sicheren ESS-Regeln der Anlage anwenden.
   - Flex-**Freigaben** (`Earnie_*_Freigabe`) auf `0` (gesperrt) setzen oder bekannte Notfalllogik anwenden.
   - Keine EV-Sollwerte mehr aus dem Earnie-Merker übernehmen.
4. **Wenn Earnie wieder erreichbar ist:** Die Earnie-Merker wie vorgesehen an Aktoren bzw. Programm durchreichen.

Der Earnie-Core braucht dafür keine Änderung. Die Rückfallebene ist reine Config-Logik rund um die Merker.

### 6. Loxone-Import in Earnie

<a id="6-loxone-import-into-earnie"></a>

Voraussetzungen: Die Earnie-Vorlagen sind in Loxone Config installiert, jeder Verbraucher hat einen Zählerblock (EFM), und die Zugangsdaten sind unter **Smarthome-Backend → Anbindung** eingetragen. Der Import-Button wird erst aktiv, sobald der Miniserver erreichbar ist.

1. Auf **Daemon Control → Smarthome-Backend** erscheint unterhalb der Verbindungsübersicht der Abschnitt **Loxone-Import**, sobald Loxone verbunden ist. Bei der Ersteinrichtung steht **Nein – manuell weiter** in derselben Zeile wie der Import-Button.
2. Earnie lädt `LoxAPP3.json`, ordnet `Earnie_*` den LoxAPP3-Control-Namen zu (exakt oder Präfix + Slug, ohne Beachtung der Groß-/Kleinschreibung), legt typisierte Entitäten an und bindet die EFM-Zähler.
3. Das Signal-Mapping auf **EHAL-Com** prüfen ([Signalliste](../ui/ehal-com.md#signalliste-loxone-contract)). Parameter (kWh, Zeitpläne, Wohnfläche, …) anschließend im **Hauskonfigurator** nachpflegen.

### Library-Checkliste

- [ ] `VI_`- / `VO_`-XMLs in die Config-Vorlagenordner kopiert, Config neu gestartet
- [ ] `EARNIE_HOST` gesetzt; Geräte eingefügt; Titel stabil
- [ ] Mehrere Verbraucher / EVs: Slug-Titel + Check/VO `{hk_id}` / `{ev_id}` (falls genutzt)
- [ ] Zähler am EFM mit eindeutigen Bezeichnungen
- [ ] Programm auf dem Miniserver gespeichert
- [ ] Optional: Heartbeat-Watchdog + Rückfallebene programmiert
- [ ] Smarthome-Backend: Loxone-Import → Mapping auf EHAL-Com prüfen → Parameter im Hausprofil

---

## Präsenzprüfung (für Binding und Import)

Die Cmd-Titel der Vorlagen sind **bekannt** (`greenfield_device_map.json`). Earnie prüft sie gegen die **LoxAPP3-Control-Namen** (`GET /data/LoxAPP3.json`): Ein Signal gilt als vorhanden, wenn sein Name (Bezeichnung) in `controls` auftaucht, sonst als fehlend. Titel, die in der Loxone-App nicht sichtbar und damit in LoxAPP3 nicht enthalten sind, werden nicht erkannt. Eine Discovery-Inbox für unbekannte Push-IDs ist geplant.

Der Default-Import nutzt die LoxAPP3-Namen. EFM-Zähler stammen ebenfalls aus `LoxAPP3.json`.

## Mehrere Flex-Verbraucher (Namenskonvention)

<a id="multiple-flex-consumers-naming-convention"></a>

Eine Vorlage `VI_Earnie_Consumer` / `VO_Earnie_Consumer` deckt **einen** Verbraucher ab. Miniserver-Bezeichnungen müssen eindeutig sein. Die `id` im Hausprofil (Kleinbuchstaben, snake_case, z. B. `waschmaschine`) ist der kanonische **Entity-Slug** (`{hk_id}`).

| Signal   | Merker-Titel (erster / weitere)                                       | VI-Check / VO-Pfad                                |
| -------- | ----------------------------------------------------------------------- | --------------------------------------------------- |
| Leistung | `Earnie_Verbraucher_Leistung` → `Earnie_Verbraucher_<Slug>_Leistung`   | VO: `flex.{hk_id}.sens_power_act`                  |
| Aktiv    | `Earnie_Verbraucher_<Slug>_Aktiv` (Kennung erforderlich)               | VO: `consumer.{hk_id}.sens_consumer_active` (0/1) |
| Freigabe | `Earnie_Verbraucher_Freigabe` → `…_<Slug>_Freigabe`                    | Check: `consumer.{hk_id}.set_enable`               |

**Beispiel Waschmaschine** (`id` = `waschmaschine`):

- Titel: `Earnie_Verbraucher_Waschmaschine_Leistung`
- VO-Befehl bei Ein: `/ehal/telemetry/flex.waschmaschine.sens_power_act/<v>`
- VI-Check (Freigabe): `"consumer.waschmaschine.set_enable":\v` (der Titel bleibt `Earnie_Verbraucher_Waschmaschine_Freigabe`)
- EHAL-Com-Binding: `consumer.{hk_id}.sens_power_act` → Titel (bei `zaehler_<slug>`: Kennung ohne `zaehler_`)

`<Slug>` **im Merker:** kurzer, stabiler Token (z. B. `Waschmaschine`). `{hk_id}`: derselbe Verbraucher wie im Hausprofil.

## Mehrere EVs (Namenskonvention)

Analog: Präfix `Earnie_EAuto_`, Entität `id` = `{ev_id}` (z. B. `eauto`, `garage`).

| Signal            | Merker-Titel (erster / weitere)                       | VI-Check / VO-Pfad                       |
| ------------------ | -------------------------------------------------------- | ------------------------------------------ |
| Soll A            | `Earnie_EAuto_Soll_A` → `Earnie_EAuto_<Slug>_Soll_A`     | Check: `evcs.{ev_id}.set_evcs_max_current` |
| Modus             | `Earnie_EAuto_Modus` → `…_<Slug>_Modus`                  | Check: `evcs.{ev_id}.set_evcs_mode`        |
| Leistung          | `Earnie_EAuto_Leistung` → `…_<Slug>_Leistung`            | VO: `ev.{ev_id}.sens_evcs_active_power`   |
| weitere sens/get  | `Earnie_EAuto_*` → `…_<Slug>_*`                          | VO: `ev.{ev_id}.<ehal_field>`             |

**Wärmepumpe:**

- Titel: `Earnie_Waermepumpe_Leistung` / `Earnie_Waermepumpe_Freigabe`.
- Speichertemperaturen: `Earnie_Waermespeicher_Temp_eq` / `Earnie_Waermespeicher_Temp_low`.
- Pfade: VO `flex.{hk_id}.sens_power_act`, VI-Check `heatpump.{hk_id}.set_enable` (Standard-`id` `wp_heating`).

**Pool:** VO `flex.pool.sens_power_act` (oder `flex.{hk_id}.sens_power_act`), VI-Check `pool.{hk_id}.set_enable`.

**Import:** Der Default-Import ordnet Vorlagennamen **ohne Beachtung der Groß-/Kleinschreibung** zu, entweder exakt oder als **Präfix + Slug**. Beispiele: `Earnie_Verbraucher_Waschmaschine_Leistung` → Verbraucher `waschmaschine`; `Earnie_EAuto_Garage_Soll_A` → EV `garage`. Bindings behalten die Schreibweise des Miniservers.

In Config: Vorlage einfügen, Cmd-Titel sowie VI-Check / VO-Pfad `{id}` setzen und anschließend auf dem Miniserver speichern.

Alle konfigurierten Signale lassen sich so prüfen:

```powershell
.venv\Scripts\python.exe -m scripts.verify_loxone_setup
.venv\Scripts\python.exe -m scripts.verify_swimspa_filter_live
```

---

## Rolle ↔ Entität (Überblick)

| Entität / Bereich                                                      | Speicherort                                   | Typische EHAL-Felder / Rollen                                                                                                                             |
| ------------------------------------------------------------------------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Anlage (PV, Netz, Hauslast, Außentemp., Abwesenheit; ESS-Leistung/Sollwerte über die primäre Batterie)   | `house_profiles.json` → `plant.ehal_bindings` | `sens_pv_production_active`, `sens_ess_power`, `sens_grid_power_active`, `sens_temperature_outside`, `sens_absent_mode`, `sens_power_consumers` (SoC: `batteries[].ehal_bindings` → `ess.{slug}.sens_ess_soc`) |
| Request Optimize (ad hoc)                                               | Loxone-VO → Daemon-HTTP                       | `Earnie_Request_Optimize` auf Port `system.ehal_loxone_http_port` (Standard **8541**)                                                                     |
| Wärmepumpe / Flex / Thermik                                             | `consumers[].ehal_bindings`                   | `consumer|heatpump|pool.{slug}.sens_power_act`, `….set_enable` (Legacy `flex.*` nur noch lesen)                                                         |
| EV (`ev`)                                                                | `consumers[].ehal_bindings`                   | `sens_evcs_*`, `get_evcs_*`, `set_evcs_*`                                                                                                                  |
| Pool / SwimSpa                                                           | `consumers[].ehal_bindings` + Filter-Entität  | siehe Default `Earnie_Pool_*` / EHAL-Com, Abschnitt Pool / SwimSpa                                                                                        |

Bearbeitet wird in der Oberfläche **ausschließlich** unter **Daemon Control → EHAL-Com → Signalliste** (und den zugehörigen Mapping-Abschnitten). Der Hauskonfigurator bearbeitet keine Merker-Adressen mehr.

## Kernsignale (`plant.ehal_bindings`)

Default-Namen. Netz-/PV-/Batterie-**Leistung** bevorzugt über die EFM-Zählerbezeichnung.

| EHAL-Feld                        | Richtung  | Default-Name                                   | Wert / Einheit                                                                          |
| ---------------------------------- | --------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| `ess.{slug}.sens_ess_soc`         | Lesen     | `Earnie_Batterie_SoC` / `Earnie_Batterie_<Slug>_SoC` | Batterie-SoC, % (Entity-bezogen; nicht anlagenweit)                                  |
| `sens_pv_production_active`       | Lesen     | `Earnie_PV_Leistung` (oder EFM-Erzeugung)        | PV-Leistung, kW                                                                             |
| `sens_ess_power`                  | Lesen     | `Earnie_Batterie_Leistung` (oder EFM-Speicher)   | Batterie kW; **+ Entladen**, − Laden (wie EHAL, keine Invertierung)                         |
| `sens_grid_power_active`          | Lesen     | `Earnie_Netzleistung` (oder EFM-Netz)            | Netz: + Bezug, kW                                                                           |
| `get_grid_export_power_limit`     | Lesen     | `Earnie_Netz_Einspeisegrenze_In` (optional)      | Maximale Exportgrenze aus Loxone, kW (EHAL: W)                                      |
| `get_ess_soc_min`                 | Lesen     | `Earnie_Batterie_SOC_Min` (optional)             | Entlade-Abschaltgrenze SoC %; MILP bei `limits_from_live`                           |
| `get_ess_soc_max`                 | Lesen     | `Earnie_Batterie_SOC_Max` (optional)             | Lade-Abschaltgrenze SoC %                                                           |
| `get_ess_max_charge_power`        | Lesen     | `Earnie_Batterie_Max_Ladeleistung` (optional)    | Maximale Ladeleistung des Geräts (Loxone kW → EHAL W)                               |
| `get_ess_max_discharge_power`     | Lesen     | `Earnie_Batterie_Max_Entladeleistung` (optional) | Maximale Entladeleistung des Geräts (Loxone kW → EHAL W)                            |
| `sens_power_consumers`            | Lesen     | (optional)                                        | Hauslast; sonst abgeleitet                                                                  |
| `sens_temperature_outside`        | Lesen     | `Earnie_Aussentemperatur`                        | Außentemperatur °C (hausweit; Wärmepumpe/Pool)                                             |
| `sens_absent_mode`                | Lesen     | `Earnie_Abwesend`                                | Haus abwesend / Urlaubsmodus 0/1 (ODER mit HK-`absent_mode`)                               |
| `set_ess_active_power`            | Schreiben | `Earnie_Batterie_Sollleistung`                   | Zwangsleistung, kW; `+` Entladen, `−` Laden                                                 |
| `set_ess_charge_power_limit`      | Schreiben | `Earnie_LadeLeistungs-Limit`                     | Max. Ladeleistung (echtes Limit)                                                            |
| `set_ess_discharge_power_limit`   | Schreiben | `Earnie_EntladeLeistungs-Limit`                  | Max. Entladeleistung (echtes Limit)                                                         |
| `set_ess_mode`                    | Schreiben | `Earnie_Steuerbefehl`                            | Sticky: immer schreiben; `0` = Automatik; nur Batterie; OpenEMS ignoriert                   |
| `ess.<id>.set_ess_source_select`  | Schreiben | Pattern-B-Merker (z. B. alt `Earnie_Speicher_Quellenwahl`) | nur physisches `standby_backup`; `0` = Netzdurchleitung, `1` = reiner Batterie-Inselbetrieb (Fähigkeit `supports_ess_source_select`); nicht auf Anlagenebene |
| `set_grid_export_power_limit`     | Schreiben | `Earnie_EinspeiseLeistungs-Limit`                | Max. Export kW (Betrag ≥ 0); `0` = kein Export; unbeschränkt = PV-kWp + max. Batterie-Entladung kW |
| *(Watchdog)*                       | Lesen     | `Earnie_Heartbeat`                               | Entity-bezogen; kein EHAL-Feld                                                              |

Die alten Rollennamen (`soc_name`, `pv_power_name`, …) in `loxone_blocks` sind entfernt. Verwendet werden nur noch `plant.ehal_bindings` mit den obigen EHAL-Feldnamen (siehe [EHAL-Vertrag](ehal.md)).

**Sticky-Merker.** Loxone behält den zuletzt geschriebenen Wert.

- **Automatikmodus:** `set_ess_mode = 0` bedeutet Automatik. In Modus 0 darf Config die Sollleistung nicht anwenden, auch wenn `Earnie_Batterie_Sollleistung` noch einen alten Wert enthält.
- **Exportdrosselung:** `set_grid_export_power_limit` ist wie die Lade-/Entladegrenzen ein nichtnegativer Betrag in kW. Config drosselt die Netzeinspeisung auf `min(Grenze, Wechselrichterleistung)`. `0` bedeutet kein Export (Einspeisesperre).
- **Unbeschränkter Export:** wird als Anlagenmaximum geschrieben, also PV-kWp-Summe plus die **Summe** der maximalen Entlade-kW jeder ausgewählten zwangsentladbaren Batterie (`control = full`). Ist dieser Wert unbekannt, wird `1000` kW geschrieben.
- **Mehrere ESS:** Merker-Titel verwenden den Slug-Infix `Earnie_Batterie_<Slug>_…`. Die Entity-bezogenen Binding-Schlüssel sind `ess.{slug}.sens_ess_soc` / `set_ess_*` in `batteries[].ehal_bindings`.
- **`set_ess_mode`** (`Earnie_Steuerbefehl`) gilt nur für die Batterie und signalisiert nie eine Exportdrosselung.

## Flexible Verbraucher: `ehal_bindings` am Verbraucher

Die Signaldefinitionen stehen im aktiven Hausprofil (`house_profiles.json`). Die Merker liegen unter `ehal_bindings`, geordnet nach EHAL-Feldname. Für bestehende Profile ohne Bindings:

```powershell
python -m scripts.migrate_ehal_bindings --path <house_profiles.json> [--config <config.json>]
```

### Flex / Thermik (typisierte Namespaces)

| EHAL-Feld                         | Richtung  | Default / Beispiel                                                                         | Wert        |
| ------------------------------------ | --------- | ---------------------------------------------------------------------------------------------- | ------------ |
| `consumer|heatpump|pool.{slug}.sens_power_act` | Lesen | Wärmepumpe: `Earnie_Waermepumpe_Leistung`; generisch: `Earnie_Verbraucher_Leistung`; oder EFM-Last | kW oder 0/1 |
| `consumer.{slug}.sens_consumer_active` | Lesen | Generisch: `Earnie_Verbraucher_<Slug>_Aktiv` (digital; ODER-Trigger der Reservefreigabe) | `0`/`1` |
| `consumer|heatpump|pool.{slug}.set_enable` | Schreiben | Wärmepumpe: `Earnie_Waermepumpe_Freigabe`; generisch: `Earnie_Verbraucher_Freigabe` | `0`/`1` |

> **Hinweis:** Speicher- und Wire-Schlüssel sind gleich (`consumer.` / `heatpump.` / `pool.` nach Verbrauchertyp). Legacy-`flex.{slug}.*` wird beim Config-Migrationsschritt umgeschrieben; bis dahin akzeptiert Earnie es noch beim Lesen.

Pool-Freigaben: Default `Earnie_Pool_Freigabe` / `Earnie_Pool_Filter_Freigabe` in `ehal_bindings`.

**Wärmespeicher-Ist (Live):** am Verbraucher `thermal_annual`:

| EHAL-Feld | Bedeutung | Default-Merker |
| --- | --- | --- |
| `sens_temperature_heat_storage` | Energieäquivalent `T_eq` (°C) | `Earnie_Waermespeicher_Temp_eq` |
| `sens_temperature_heat_storage_low` | Unterster Tauchfühler `T_low` (°C): Hinweis auf Wärmepumpe-ein, wenn der Boden kalt ist | `Earnie_Waermespeicher_Temp_low` |

Bei geschichteten Speichern muss `T_eq` der energieäquivalente (volumengewichtete) Mittelwert sein, nicht allein der obere Fühler. Anleitung: [waermespeicher-schichtung-teq.md](../konfiguration/waermespeicher-schichtung-teq.md).

### EV (Präfix `Earnie_EAuto_`)

| EHAL-Feld                   | Richtung  | Default-Name                                                                                            | Wert                                                                                                                                                                                                               |
| ------------------------------ | --------- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sens_evcs_active_power`     | Lesen     | `Earnie_EAuto_Leistung` (oder EFM-Last; dual `flex.{slug}.sens_power_act`)                                 | kW                                                                                                                                                                                                                  |
| `sens_evcs_connected`        | Lesen     | `Earnie_EAuto_Angeschlossen`                                                                                | `1` = angeschlossen                                                                                                                                                                                                |
| `sens_evcs_soc_act`          | Lesen     | `Earnie_EAuto_SOC`                                                                                          | Aktueller SOC, %                                                                                                                                                                                                  |
| `sens_evcs_bat_capacity`     | Lesen     | `Earnie_EAuto_Kapazitaet`                                                                                   | kWh                                                                                                                                                                                                                |
| `get_evcs_nominal_current`   | Lesen     | `Earnie_EAuto_MaxStrom`                                                                                     | A                                                                                                                                                                                                                  |
| `get_evcs_ready_by_time`     | Lesen     | AlarmClock-**Bezeichnung** (alt); VO-Titel `Earnie_EAuto_FertigUm` | Push-Inbox: numerischer Analog-VO-Wert für den nächsten Eintrag bevorzugt; Tna-Text (`Morgen, 07:00`) wird solange er frisch ist akzeptiert und vom Optimierer geparst. |
| `get_evcs_limit_soc`         | Lesen     | `Earnie_EAuto_LimitSOC`                                                                                     | Ziel-Lade-SOC %                                                                                                                                                                                                   |
| `get_evcs_soc_min_immediate` | Lesen     | `Earnie_EAuto_SOCMinSofort`                                                                                 | Sofort-Mindest-SOC %; ≤0 oder leer = inaktiv; auf den Limit-SOC begrenzt                                                                                                                                          |
| `set_evcs_max_current`       | Schreiben | `Earnie_EAuto_Soll_A`                                                                                       | Soll-/Maximalstrom A                                                                                                                                                                                              |
| `set_evcs_mode`              | Schreiben | `Earnie_EAuto_Modus`                                                                                        | `off`=0 / `pv`=1 / `now`=2                                                                                                                                                                                         |

Hinweise:

- Der EV-Verbraucher benötigt außerdem das Feld `min_power_kw`.
- Der **EV-Modus** wird ausschließlich über `set_evcs_mode` (`Earnie_EAuto_Modus`) geschrieben. Earnie schreibt weder `pv_follow` noch Sofortbefehl-Merker.
- **Poolfilter:** Der Hausprofil-Verbraucher `pool_filter` führt seine EHAL-Rollen (u. a. `get_filter_remaining_hours`) unter `ehal_bindings`. Standardpräfix: `Earnie_Pool_*` / `Earnie_Pool_Filter_*` (siehe [ehal-com.md](../ui/ehal-com.md), Abschnitt Pool / SwimSpa).

## Request Optimize (Ad-hoc-Läufe)

Ad-hoc-Optimierungsläufe in `main.py` (zwischen den Viertelstunden) laufen über HTTP von Loxone zu Earnie.

| Element                          | Bedeutung                                                                                  |
| ----------------------------------- | ---------------------------------------------------------------------------------------------- |
| Virtual Out                        | Vorlage `share/loxone/templates/VirtualOut/VO_Earnie_Status.xml`                              |
| Adresse                            | `http://EARNIE_HOST:8541` (Port = `system.ehal_loxone_http_port`, Standard **8541**)          |
| Cmd `Earnie_Request_Optimize`      | `POST /ehal/loxone/request_optimize`: weckt den Daemon vor der nächsten Viertelstunde; Empfangs-ID `request_optimize` in EHAL-Com **Signalliste** und **Live-Lesen** |

Der Verbindungsnachweis (Hub → Earnie) ist der sich wiederholende Telemetrie-VO **`Push_Earnie_Heartbeat`** → `GET /ehal/telemetry/heartbeat_smarthome/<v>`, kein Status-Cmd. Bestehende Configs, die noch das veraltete Cmd **`Earnie_Push_Alive`** / `GET /ehal/loxone/alive` enthalten, sollten es löschen; der Endpunkt liefert 404.

Compose-Produktivstacks veröffentlichen Container-Port **8541** (siehe [Streamlit-Ports](../dev/streamlit-ports.md)).

## Beispiel-Mapping

| Verbraucher (`id`) | Steuerung (Schreiben)                                      | Leistung (Lesen)                                                |
| ------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------- |
| `swimspa` / Pool    | `flex.{slug}.set_enable` → `Earnie_Pool_Freigabe`              | `flex.{slug}.sens_power_act` → `Earnie_Pool_P_act`                  |
| `ev`                | `set_evcs_max_current` / `set_evcs_mode`                       | `sens_evcs_*` / `flex.{slug}.sens_power_act`                        |
| `wp_heating`        | `flex.{slug}.set_enable` → `Earnie_Waermepumpe_Freigabe`       | `flex.{slug}.sens_power_act` → `Earnie_Waermepumpe_Leistung`; `sens_temperature_heat_storage` / `_low` → `Earnie_Waermespeicher_Temp_eq` / `_low` |

## Lesen und Schreiben in `main.py`

| Phase        | Aktion                                             |
| ------------- | ---------------------------------------------------- |
| Lesen        | SOC, Leistungen, PV, Flex-Eingänge, EV-Status        |
| Optimierung  | MILP über den Planungshorizont (15-Min-Slots; `dt_h = 0.25`) |
| Schreiben    | ESS-Grenzen / Modus, Freigaben / EV-Strom je 15-Min-Schreibzyklus |

Die App **liest** dieselben Live-Werte für die Anzeige; Steuerwerte **schreibt** sie nur im Live-Modus. Merker-Zuordnung: [EHAL-Com](../ui/ehal-com.md).

Weitere Details: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md) · [Abkürzungen](abbreviations.md).
