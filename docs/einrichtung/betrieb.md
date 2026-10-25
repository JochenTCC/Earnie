# Betrieb

Diese Seite beschreibt, was nach einem Update passiert, wie Optimierer-Dienst und App zusammenarbeiten und welche Laufzeitdateien entstehen.

## Update und Migration

Earnie entwickelt sein **Datenmodell** laufend weiter, also die Form, in der Haus, Komponenten, Szenarien und Signale in den Konfigurationsdateien stehen. Damit Ihre individuelle Konfiguration nach einem Update weiter passt, bringt Earnie sie mit dem **Migrations-Assistenten** automatisch auf den neuesten Stand des Datenmodells:

- **Keine Handarbeit:** Sie müssen die Konfigurationsdateien nicht selbst umschreiben. Ihre Einstellungen, Ihr Haus und Ihre Szenarien bleiben erhalten.
- **Nachvollziehbar:** Der Assistent zeigt vorher, was sich ändert, und fragt nach, wo eine Entscheidung nötig ist.
- **Sicher:** Vor jeder Änderung legt Earnie ein Backup an.

So läuft die neue Version direkt mit Ihrer bisherigen Konfiguration weiter.

Nach einem Image- oder Add-on-Update startet der Assistent, wenn sich die Form der Pack-Dateien ändert (strukturelle Schritte). Davon zu unterscheiden sind fehlende Keys in `config.json` nach einem Upgrade: Dort fehlen nur neue Einstellungsfelder (siehe [Container → Config-Updates](container.md#config-updates-nach-programm-upgrade)). Eine Ausnahme bildet der Block `scenario_explorer_conf`: Fehlende Einträge dort ergänzt die Migration selbst (siehe unten).

### Ablauf

1. Earnie startet im **Migrationsmodus**. Verfügbar ist nur der Assistent (plus Log/Debug), **kein** normaler Hauskonfigurator und **kein** Auto-Start von `main.py`.
2. Der Assistent zeigt einen Hinweis (inkl. letzter laufender Version), die ausstehenden Schritte und JSON-Diffs. Ggf. stellt er Fragen und nennt manuelle To-dos außerhalb von Earnie.
3. **Backup anlegen und migrieren** legt zuerst ein Backup an, schreibt danach die neuen JSON-Dateien und zeigt den Report.
4. **Weiter zur App** lädt die normale UI. Der Optimierer-Dienst startet nur, wenn der Auto-Start aktiv ist, und zwar sofort nach erfolgreicher Migration (die Berichtsseite zeigt PID oder Fehler); sonst lässt er sich unter **Optimierer-Dienst** starten. Schlägt der Start fehl, bleibt die Migration gültig: Dienst unter **Optimierer-Dienst** starten oder den Container neu starten, bis dahin antwortet der EHAL-Port nicht.

Bringt eine Version neue Schritte mit, informieren die Release Notes vorab darüber (Abschnitt **Migration**).

Ein Schritt schreibt Verbraucher-Bindings von Legacy-`flex.{Kennung}.*` auf die typisierten Schlüssel `consumer.` / `heatpump.` / `pool.` um (gleiche Form wie Signalliste und `status.json`). Bei widersprüchlichen Merkernamen blockiert die Migration mit Hinweis auf den betroffenen Verbraucher.

Ein weiterer Schritt entfernt das flache Anlagen-PV-Mapping (`plant.ehal_bindings.sens_pv_production_active`). Bei genau einem netzgekoppelten Wechselrichter mit PV wird die Merker-/Entity-Adresse auf `inv.{id}.sens_inv_power_pv` übernommen; bei mehreren Wechselrichtern blockiert die Migration mit Hinweis, die WR-PV-Mappings manuell zu setzen.

Ein weiterer Schritt ergänzt fehlende Einträge unter `scenario_explorer_conf` in `config.json` mit den Standardwerten aus der mitgelieferten `config.example.json`, z. B. `season_mirror_to_last_month` oder `export_price_series`. Vorhandene Einträge bleiben unverändert.

### Loxone: alte Merkernamen behalten oder leeren

Beim Wechsel von Datenmodell 3 (offizielle 2.6) auf 4 fragt der Assistent bei Loxone-Installationen, ob die alten **Merkernamen** in den Bindungen erhalten bleiben sollen. Earnie braucht sie nicht mehr: Lesen läuft per Push mit der EHAL-ID, Schreiben über `status.json` mit der EHAL-ID.

- **Behalten:** Die Namen bleiben stehen. Im VI/VO-Export der Signalliste (**Daemon Control → EHAL-Com → Signalliste**) erscheinen sie in der Spalte **„Bisheriger Name“**. Damit lassen sich die betroffenen Stellen in der Loxone Config leicht finden.
- **Leeren:** Die Bindungen bleiben aktiv (Schlüssel mit leerem Wert), nur die Namen verschwinden – wie bei einer Neueinrichtung.

Die Frage kommt nur einmal (beim Wechsel 3 → 4). In beiden Fällen müssen die virtuellen Ein-/Ausgänge in der Loxone Config auf die neuen Titel umgestellt werden; der Assistent zeigt das als manuellen Schritt. Home Assistant und OpenEMS sind nicht betroffen, denn dort sind die Werte Entity-IDs.

### Backup

Vor dem Schreiben legt Earnie ein Verzeichnis an:

`{config}/backups/pre-migration-dm<von>-dm<nach>-<UTC-Zeitstempel>/`

Darin liegen die alten Pack-JSON, `manifest.json` (Earnie-Version, from/to, Schritt-IDs) und nach dem Lauf `report.json`. **Alle** Backups bleiben liegen; Earnie löscht sie nicht. Nicht mehr benötigte Ordner unter `backups/` lassen sich manuell entfernen.

| Kanal | Config-Wurzel | Backup-Pfad |
| --- | --- | --- |
| **Docker** (Synology, Proxmox, …) | Host `earnie_env/config/` → Container `/app/config` | `earnie_env/config/backups/pre-migration-…/`, siehe [Container](container.md) |
| **LoxBerry** | `…/data/plugins/earnie/earnie_env/config/` | `…/earnie_env/config/backups/pre-migration-…/`, siehe [LoxBerry-Plugin](loxberry-plugin.md) |
| **HA-Add-on** | Container `/config/` (= Host `addon_configs/…_earnie/` bzw. `_earnie_prerelease`) | `/config/backups/pre-migration-…/`. Gehört zu den HA-Backups des Add-ons; siehe [Home-Assistant-Add-on](homeassistant-addon.md) |

Es gibt **kein** automatisches Downgrade. Eine ältere Earnie-Version lehnt ein neueres Datenmodell ab. Der Rückweg führt über das manuelle Zurückkopieren des Backup-Ordners.

### Support-CLI

Für Entwicklung und Support gibt es dieselbe Kette wie im Assistenten auch auf der Kommandozeile:

```powershell
python -m scripts.migrate_config --config-dir PATH --dry-run
python -m scripts.migrate_config --config-dir PATH
```

Pflichtfragen (z. B. Loxone-Merkernamen, alte HA-Vorzeichen) beantwortet die CLI über eine JSON-Datei: `--answers answers.json` mit z. B. `{"loxone_binding_names.keep": "Behalten"}` (oder `"Leeren"`) bzw. `{"ha_sign.remove": "Entfernen"}` (oder `"Behalten"`). Ohne Antwort bricht der Lauf ab, bevor etwas geschrieben wird.

### Wann die Migration blockiert

- **Datenmodell 1 oder 2:** zu alt. Support kontaktieren oder neu einrichten; eine automatische Kette gibt es nicht.
- **Earnie-Pack-Datei ohne `earnie_data_model`:** Die Version ist unbekannt. Earnie rät sie nicht und trägt sie auch nicht stillschweigend nach. Ausgenommen ist `grid_fees.json`, bis die Tarifverwaltung mit dem Tarif-Editor kommt.

## Einstiegspunkte


| Komponente           | Befehl                            | Rolle                                                                                         |
| -------------------- | --------------------------------- | --------------------------------------------------------------------------------------------- |
| **Streamlit-App**    | `python -m scripts.run_streamlit` | Cockpit, Konfiguration und Analyse sowie Steuerung des Optimierer-Dienstes.                   |
| **Produktiv-Daemon** | `python main.py`                  | Liest Telemetrie über EHAL, optimiert und schreibt Steuerwerte. Läuft dauerhaft, auch als Kindprozess der Streamlit-App. |


Nur `main.py` steuert die Anlage im Produktivbetrieb (Schreibvorgänge über EHAL). Die App **zeigt** den berechneten 24–48-Stunden-Horizont (`live_optimization_debug.json`). Unter **Daemon Control → Optimierer-Dienst** kann sie den Daemon starten, stoppen und neu starten. Vor dem Start prüft Earnie `runtime/main.lock`, um eine bereits laufende Instanz zu erkennen.

### Sichere Sollwerte und Silent / Loud

- **Sichere Sollwerte beim Start:** Beim Daemon-Start schreibt Earnie **einmal** sichere Sollwerte (ESS Automatik / Freigabe und EVCS aus), bevor der erste Optimierungslauf beginnt. Das gilt für alle EHAL-Backends (Loxone, HA, OpenEMS).
- **Silent:** Im Silent-Modus entfällt dieser Schreibvorgang.
- **Umschalten:** Silent / Loud wird unter **Daemon Control → Optimierer-Dienst** umgestellt und in `runtime/local_settings.json` → `silent_mode` gespeichert. Ein Neustart von `main.py` ist dafür nicht nötig.
- **Überspringen:** Mit `EARNIE_SKIP_SAFE_SETPOINTS_ON_START=1` entfallen die sicheren Sollwerte beim Start.

### Dienst-Log

Unter **Optimierer-Dienst → Dienst-Log** zeigt die App das Ende (Tail) von `runtime/earnie.log` in einem Expander.

- **Aktualisierung:** Die Anzeige aktualisiert sich automatisch alle 10 Sekunden. **Aktualisieren** oben und unten am Log lädt sofort neu.
- **Navigation:** Unten daneben führt **Gehe nach Oben** zurück zum Anfang des Log-Bereichs.
- **Filter:** Log-Level (`INFO` / `WARNING` / …) sind filterbar; Standard ist INFO und höher.
- **Trennstreifen:** Bei jedem erfolgreichen Start von `main.py` schreibt Earnie einen klaren Trennstreifen (Separator) mit PID und Version in `earnie.log`. So lassen sich Läufe leichter unterscheiden.
- **Startausgabe:** Startet die UI den Daemon (`EARNIE_AUTO_START_MAIN` oder Neustart-Button), landet die echte stdout/stderr-Ausgabe in `runtime/main_stdio.log` (nicht `DEVNULL`). Das hilft bei Startfehlern, bevor die Protokollierung in die Log-Datei beginnt. Das Python-Logging geht dann nur in `earnie.log`; `main_stdio.log` spiegelt die Konsolen-Ausgabe des Loggings nicht.
- **Rotation:** Bei jedem Start von `main.py` durch die App rotiert Earnie `main_stdio.log` bei ≥ 5 MiB oder Monatswechsel (max. 12 Archive `main_stdio.log.YYYY-MM-DD_HH-MM-SS`).

### Docker oder lokal

**Docker (empfohlen):** Alles läuft in einem Container (`earnie-productive` in den Synology-/LoxBerry-/Proxmox-Compose-Dateien; Dev-Stack: `earnie`). Die UI startet `main.py` automatisch, wenn `EARNIE_AUTO_START_MAIN=1` gesetzt ist (Standard in den Compose-Dateien).

**Lokal (venv / VS Code):** `main.py` und Streamlit können getrennt laufen. Der Auto-Start ist aus, solange `EARNIE_AUTO_START_MAIN` nicht auf `1` steht. So bleibt `main.py` beim Debugging unter eigener Kontrolle.

Die Konfiguration schreiben die Seiten **Hauskonfigurator**, **Szenarienkonfigurator** und **Manuelle Geräte**. Wo hausbezogene Daten lokal bzw. in einem privaten Repo liegen, beschreibt [Private Haus-Config](private-env.md).

## Optimierungs-Takt

- **Viertelstunden-Grenzen:** Ein Lauf startet an jeder Viertelstunden-Grenze (`:00`, `:15`, `:30`, `:45`).
- **Sofort auf Anfrage:** Zusätzlich startet ein Lauf sofort, wenn das Loxone Virtual Out **`Earnie_Request_Optimize`** den HTTP-Dienst des Daemons aufruft (`POST /ehal/loxone/request_optimize`).
- **Port:** `system.ehal_http_port` in `config.json` bzw. `EARNIE_EHAL_HTTP_PORT` (Standard **8541**; alte Namen `system.ehal_loxone_http_port` / `EARNIE_EHAL_LOXONE_HTTP_PORT` gelten weiter). Vorlage `VO_Earnie_Status.xml` → `http://EARNIE_HOST:8541`.
- **Link-Nachweis (Hub → Earnie):** Ein wiederholendes Heartbeat-VO `Push_Earnie_Heartbeat` ruft `GET /ehal/telemetry/heartbeat_smarthome/<v>` auf.
- **Status für Virtual In:** Der Status je Entität liegt am selben Port unter `GET /ehal/loxone/status.json`.
- **Maximale Wartezeit:** `system.loop_timeout` in `config.json` legt die maximale Wartezeit zwischen Durchläufen in Sekunden fest (Standard 900 = 15 Min.).
- **Cockpit-Aktualisierung:** Die App lädt den Cockpit-Snapshot nach dem Viertelstunden-Wechsel, sobald `main.py` den aktuellen Slot abgeschlossen hat (typisch wenige Sekunden).

Countdown und letzter Lauf erscheinen unten in der App (siehe [Charts & Panels](../ui/charts.md)).

## Laufzeitdateien (`runtime/`)

Standardverzeichnis: `earnie_env/runtime/`. Es lässt sich mit `EARNIE_RUNTIME_PATH` überschreiben oder wird aus `EARNIE_ENV_PATH` abgeleitet.


| Datei                           | Inhalt                                                                                       |
| ------------------------------- | -------------------------------------------------------------------------------------------- |
| `cons_data.csv`          | Stündliche Verbrauchs- und PV-Basis (von `main.py` gepflegt).                                |
| `flexible_consumers_state.json` | Tagesenergie je Flex-Verbraucher.                                                            |
| `pv_counter_state.json`         | PV-Zählerstand für das Stunden-Delta.                                                        |
| `power_interval_sampler_state.json` | Zwischenpuffer der Leistungsproben (≤ 60 s) für Viertelstunden-Mittel im Produktiv-Log. Optional mit Energie-Ankern (`energy_anchors`): Aus Loxone-Zählern (ΔkWh) wird die mittlere Slot-Leistung berechnet. |
| `cons_data_pending.json`        | Puffer für noch ausstehende `cons_data`-Messwerte (Samples).                                 |
| `consumption_profiles.csv`      | Berechnete Grundlast-Profile.                                                                |
| `earnie.log`                    | Rotierendes Python-Log von `main.py` (absoluter Pfad). Rotation monatlich, max. 12 Archive `earnie.log.YYYY-MM-DD_HH-MM-SS`. |
| `main_stdio.log`                | stdout/stderr des per UI/Auto-Start gestarteten `main.py`, zur Diagnose bei Startfehlern. Rotation bei jedem Start durch die App: ≥ 5 MiB oder Monatswechsel, max. 12 Archive `main_stdio.log.YYYY-MM-DD_HH-MM-SS`. Das Logging geht nur in `earnie.log`. |
| `main.lock` / `main.pid`        | Sperre gegen eine zweite Instanz des Produktiv-Daemons. `main.lock` wird gehalten; die PID steht zusätzlich in `main.pid` (für Status/Stop unter Windows). |
| `optimizer_run_state.json`      | Letzter erfolgreicher `main.py`-Durchlauf (SoC, Modus, Soll-Leistungen, Flex-Soll).          |
| `optimization_history.jsonl`    | Historie aller Produktiv-Durchläufe, eine Zeile JSON pro Lauf. Monatlich rotiert, max. 12 Archive. Enthält u. a. `consumption_snapshot`, optional `closed_interval`. |
| `live_optimization_debug.json`  | Anzeige-Snapshot des Optimierungs-Horizonts (von `main.py` geschrieben, von der App gelesen). |
| `live_day_ahead_<zone>.json` | Cache der letzten erfolgreichen Live-Day-Ahead-Serie (QH; Zone z. B. `AT`; `source` ENTSO-E oder Energy-Charts). Live nutzt ihn statt eines erneuten API-Abrufs bzw. vor dem aWATTar-Fallback. |
| `local_settings.json`           | Lokale Betriebseinstellungen, z. B. `silent_mode` (auch über die Seite **Optimierer-Dienst**), `chart_debug_capture_enabled` und die Cycle-Recorder-Schlüssel `recorder_enabled` / `recorder_retention_days`. |
| `recorder/`                     | Cycle-Recorder-Ringpuffer (`cycles_YYYY-MM-DD.jsonl.gz`, Config-Snapshots unter `configs/`). Enthält Lastprofile für die Regression; bleibt lokal und ist standardmäßig an. |
| `timing/`                       | Optional: Phasen-Zeiten des Live-Zyklus (`cycles.jsonl`). Nur bei `EARNIE_CYCLE_TIMING=1`. |
| `profile/`                      | Optional: `cProfile`-Dumps (`cycle_*.prof`, `*_top30.txt`). Nur bei `EARNIE_CYCLE_PROFILE=1`, und nur kurz aktiv lassen. |
| `appliance_schedules.json`      | Geplante Laufzeiten manueller Geräte.                                                        |
| `powerstation_reserves.json`    | Reserve-Zustand virtueller/physischer Powerstations (stored/target kWh, Trigger).            |
| `backtesting_log.json`          | Ergebnis von Szenario-Explorer / `run_backtesting`.                                          |
| `usage_ping.json`               | Zustimmung und Zustand der optionalen Nutzungsstatistik (siehe [Nutzungsstatistik](#nutzungsstatistik)). |
| `feature_reviews.json`          | Zustand der einmaligen Feedback-Abfrage (gesendet oder abgebrochen, siehe [Feedback zum Szenario-Explorer](#feedback-zum-szenario-explorer)). |


Die App liest diese Dateien **read-only** für Panels und Abgleich.

### Live-Zyklus-Profiling (optional)

Earnie kann die Phasen-Zeiten und optional Aufruf-Profile des Optimierungszyklus (`main.py`) aufzeichnen. Daraus lässt sich ablesen, wo ein Lauf Zeit verliert. **Standard: aus** (kein Zusatzaufwand, keine Dateien).

| Variable | Wirkung |
| -------- | ------- |
| `EARNIE_CYCLE_TIMING=1` | Pro Zyklus eine Zeile in `runtime/timing/cycles.jsonl` plus eine INFO-Zeile in `earnie.log`. Phasen: `prices_matrix`, `ehal_read`, `prepare`, `milp_live`, `writes`, `savings`, ggf. `savings_*`, `persist`, `total`. |
| `EARNIE_CYCLE_PROFILE=1` | Zusätzlich `cProfile` → `runtime/profile/cycle_<slot>.prof` und Top-30-Text. **Nur 1–2 Zyklen** laufen lassen, danach die Variable entfernen. |

Lokale Auswertung (nach dem Kopieren von `timing/` von der NAS):

```powershell
python -m scripts.summarize_cycle_timing earnie_env/runtime/timing/cycles.jsonl
```

Einmaliger Test auf der NAS (lokales Image, Compose-Env): siehe [Container – Live-Zyklus-Profiling (NAS-Einmal-Test)](container.md#live-zyklus-profiling-nas-einmal-test).

### Zyklus-Pünktlichkeit und Vorlauf (immer aktiv)

Earnie schreibt die Sollwerte für eine Viertelstunde genau zu deren Beginn, **nie früher**. Das sind die Zeitpunkte `hh:00`, `:15`, `:30` und `:45`, also der Takt der 15-Minuten-Strompreise. Dafür startet der reguläre Optimierungslauf etwas vor dem Takt (**Vorlauf**). Er rechnet schon für die kommende Viertelstunde und wartet mit dem Schreiben bis zum Takt.

- **Vorlauf automatisch:** Earnie misst, wie lange die Läufe bis zum fertigen Plan brauchen. Als Vorlauf dient der **Median** der letzten 96 regulären Läufe (ein Tag).
  - Der erste Lauf nach einem Prozessstart (`cold_start`) zählt nicht mit. Er enthält den Import und das Nachladen des Stromarchivs.
  - So ist der Plan im Mittel möglichst genau zum Takt fertig. Ist er lange vorher fertig, wären die zugrunde liegenden Messwerte alt. Ist er erst danach fertig, laufen so lange die alten Sollwerte weiter.
- **Grenzen:** Der Vorlauf beträgt mindestens **15 s** und höchstens **90 s**. Der Lauf startet also frühestens 90 s und spätestens 15 s vor dem Takt. Ohne Messwerte (neue Hardware, < 8 Läufe) gilt 60 s.
- **Warnungen in `earnie.log`:**
  - *„Vorlauf-Schätzung … > 90 s — Start wird nicht weiter vorverlegt“*: Die Läufe sind auf dieser Hardware zu langsam. Sollwerte kommen dann oft zu spät.
  - *„Plan für … s nach dem Takt fertig (> 90 s)“*: Ein einzelner Lauf war mehr als 90 s zu spät. Kürzere Verspätungen stehen mit demselben Text nur als Info im Log.
- **Ohne Vorlauf** laufen:
  - der erste Lauf nach dem Start,
  - außerplanmäßige Läufe (`Earnie_Request_Optimize`), die sofort schreiben,
  - der Betrieb mit `EARNIE_EARLY_START=off` (siehe [Umgebungsvariablen](#umgebungsvariablen-optional)).

  Ein `Earnie_Request_Optimize` während der Wartezeit bis zum Takt wird direkt danach ausgeführt.
- **Vorladen (Prefetch):** Direkt nach jedem Lauf lädt Earnie in der Wartezeit die langsamen Internet-Daten für den nächsten Lauf vor. Dazu gehören Day-Ahead-Preise, Wetterdaten für die Preisprognose, Außentemperatur und Kollektor-Einstrahlung (Open-Meteo).
  - Der nächste Lauf findet die Daten dann im Zwischenspeicher und ist schneller fertig.
  - In `earnie.log` steht dazu je Lauf eine Zeile `Prefetch für 13:00: … in … s` (oder „alles aus dem Cache“).
  - Schlägt das Vorladen fehl, holt der Lauf die Daten wie bisher selbst.
  - Die PV-Prognose (forecast.solar) wird wegen des Abruflimits nicht vorgeladen.
- **Aktueller Zustand:** Ladestand und Leistung liest Earnie zu Beginn des Laufs, also höchstens 90 s vor dem Takt. Der Zustand wird nicht auf den Takt hochgerechnet; der Unterschied ist bei so kurzer Zeit vernachlässigbar.

Jeder Optimierungslauf protokolliert, ob die Pünktlichkeit gelingt. Das geschieht unabhängig vom optionalen Profiling oben:

- **`earnie.log`:** eine Zeile pro regulärem Lauf, z. B.
  `Pünktlichkeit: Tick 13:00 | Vorlauf 15 s | Weckzeit +0 s | Start +0 s | Plan fertig -2 s | Sollwerte +0 s | Dauer 17 s | 24 h: 80/96 pünktlich, P95 +9 s | 7 d: …`
  - *Tick* = Viertelstunde, für die der Lauf rechnet. *Vorlauf* = wie viel früher der Lauf gestartet wurde.
  - *Weckzeit* / *Start* = wann die Warteschleife geendet bzw. der Lauf begonnen hat, relativ zum geplanten Start (Tick minus Vorlauf).
  - *Plan fertig* = wann der Plan stand, relativ zum Tick. Negativ heißt, der Plan hat auf den Tick gewartet; positiv heißt, er war zu spät.
  - *Sollwerte* = wann die Befehle an das Smarthome-Backend gingen, relativ zum Tick.
  - *pünktlich* = Sollwerte spätestens 2 s nach dem Tick. Nicht in Quote und P95 enthalten sind außerplanmäßige Läufe und Läufe ohne geplanten Takt (erster Lauf nach dem Start, `EARNIE_EARLY_START=off`, verpasster Takt). Diese Läufe bleiben in der Datei; `on_time` ist dort leer.
  - *Ereignisse* nennt bekannte langsame Schritte des Laufs: `cold_start` (erster Lauf nach Start), `pv_forecast_fetch`, `weather_fetch`, `price_feature_refresh`, `day_ahead_fetch` (Abruf aus dem Netz statt Cache).
- **`runtime/cycle_stats.jsonl`:** dieselben Werte als eine JSON-Zeile pro Lauf (rollierend 7 Tage). Außerdem stehen dort Horizontlänge, Earnie-Version und eine Plattform-Kennung (CPU, Python, Solver). Daraus berechnet Earnie den Vorlauf; Läufe auf anderer Hardware zählen nicht mit.

Eine Einstellung ist nicht nötig; die Datei bleibt lokal. Voraussetzung ist eine per NTP synchronisierte Systemuhr (bei NAS/Docker Standard).

**Systemuhr-Prüfung:** Takt und Pünktlichkeitslog richten sich nach der Systemuhr. Geht sie falsch, merkt das Log das nicht. Earnie schätzt deshalb die Abweichung:

- **Quelle:** das `Date`-Feld der Antworten, die Earnie ohnehin von Internet-Diensten bekommt (Strompreise, Wetter, PV-Prognose). Es gibt keine zusätzlichen Abrufe; Geräte im Heimnetz zählen nicht.
- **Warnung:** Weicht die Uhr um mehr als 2 s ab, steht in `earnie.log` höchstens stündlich eine Warnung *„Systemuhr geht ca. … s vor/nach … Zeitsynchronisation (NTP) des Hosts prüfen“*.
- **Schätzwert:** Er steht je Lauf als `clock_skew_sec` in `runtime/cycle_stats.jsonl`. Positiv heißt, die Systemuhr geht nach. Das Feld bleibt leer, solange weniger als 3 Antworten vorliegen.
- **Genauigkeit:** etwa ±0,5–1 s.

<a id="cycle-recorder-regression-r-rec"></a>

### Cycle-Recorder

Earnie speichert die Eingaben jedes Optimierungszyklus in einem lokalen Ringpuffer unter `runtime/recorder/`. Die Dateien enthalten **Lastprofile**, bleiben lokal und werden nicht hochgeladen.

- **Standard:** an. Abschalten mit `recorder_enabled: false` in `runtime/local_settings.json`.
- **Aufbewahrung:** `recorder_retention_days` (Standard 7 Tage).
- **Debug-Dump:** Ein Debug-Dump (siehe unten) enthält das aktuelle Recorder-Fenster und sollte nur an den Maintainer gehen.

### Log- und Historiendateien

Betriebsstatus der wichtigsten Log-, Historien- und Debug-Dateien (Review 2026-06):


| Datei                                | Status                         | Hinweis                                                       |
| ------------------------------------ | ------------------------------ | ------------------------------------------------------------- |
| `optimization_history.jsonl`         | **kanonisch**                  | Produktiv-Historie, eine JSON-Zeile pro Optimierungslauf. Monatlich rotiert, max. 12 Archive `optimization_history.jsonl.YYYY-MM-DD_HH-MM-SS`. |
| `earnie.log`                         | **aktiv**                      | Rotierendes Python-Log von `main.py` (monatlich, max. 12 Archive). |
| `main_stdio.log`                     | **aktiv**                      | stdout/stderr bei UI-/Auto-Start. Rotation beim Spawn (≥ 5 MiB oder Monat, max. 12 Archive). |
| `optimizer_run_state.json`           | **aktiv**                      | Letzter erfolgreicher `main.py`-Durchlauf.                    |
| `live_optimization_debug.json`       | **aktiv**                      | Anzeige-Snapshot des Optimierungs-Horizonts für die Streamlit-App. |
| `cycle_stats.jsonl`                  | **aktiv**                      | Dauer, Vorlauf und Pünktlichkeit je Optimierungslauf (rollierend 7 Tage), siehe [Zyklus-Pünktlichkeit und Vorlauf](#zyklus-pünktlichkeit-und-vorlauf-immer-aktiv). |
| `backtesting_log.json`               | **nur Dev/Backtesting**        | Ergebnis des Szenario-Explorers; nicht für die Produktiv-NAS gedacht. |


## Umgebungsvariablen (optional)


| Variable                                | Wirkung                                                                                                                                                                                                                              |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `EARNIE_ENV_PATH`                       | Wurzelverzeichnis für Persistenz (Standard: `earnie_env`). Daraus leiten sich `…/config` und `…/runtime` ab, sofern nicht separat gesetzt. |
| `EARNIE_CONFIG_PATH`                    | Pfad zum **Config-Verzeichnis** (Standard: `earnie_env/config`; ältere Ordner: `config/`). Enthält `config.json`, Sidecars, `.env` und `uploads/`. Ältere Setups mit Pfad zur `config.json`-Datei werden weiterhin akzeptiert. |
| `EARNIE_RUNTIME_PATH`                   | Verzeichnis für Laufzeitdaten (Standard: `earnie_env/runtime`; ältere Ordner: `runtime`). |
| `EARNIE_EARLY_START`                    | `on` (Standard, auch wenn nicht gesetzt) oder `off`. Bei `on` starten reguläre Läufe 15–90 s vor dem Viertelstundentakt und schreiben die Sollwerte genau zum Takt. Bei `off` startet der Lauf erst zum Takt und schreibt, sobald er fertig ist. Andere Werte führen zu einem Fehler beim Start. Siehe [Zyklus-Pünktlichkeit und Vorlauf](#zyklus-pünktlichkeit-und-vorlauf-immer-aktiv). |
| `EARNIE_UI_MODES`                       | Kommagetrennt: `sunset2sunset` (Monitor, Manuelle Geräte), `scenario_explorer`, `live_environment` (Smarthome-Backend, EHAL-Com, Optimierer-Dienst, Analyse Verbrauch & Kosten), `price_forecast`. Ohne Variable gilt `sunset2sunset,scenario_explorer,live_environment` (`price_forecast` nur bei `ui.price_forecast_page_enabled=true`). Die Compose-Dateien für den Produktivbetrieb setzen oft `sunset2sunset,live_environment`, die Cloud `scenario_explorer`. Siehe [Betriebsmodi](../ui/betriebsmodi.md). |
| `EARNIE_UI_STREAMLIT_PORT`              | TCP-Port für Streamlit (überschreibt `ui.streamlit_port`; siehe [Streamlit-Ports](../dev/streamlit-ports.md)).                                                                                                                  |
| `EARNIE_EHAL_HTTP_PORT`                 | TCP-Port für den Daemon-HTTP (`Earnie_Request_Optimize` / Telemetry inkl. Heartbeat / `status.json`). Überschreibt `system.ehal_http_port`; Standard **8541**. Alter Name `EARNIE_EHAL_LOXONE_HTTP_PORT` gilt weiter.                  |
| `EARNIE_UI_CHART_DEBUG_CAPTURE_ENABLED` | `1` = Button „Debug-Dump speichern“ im Cockpit (überschreibt `ui.chart_debug_capture_enabled`; ZIP unter `runtime/chart_debug/`). |
| `EARNIE_AUTO_START_MAIN`                | `1` = beim Start von `scripts.run_streamlit` automatisch `main.py` starten, falls es nicht schon läuft (Docker-Compose setzt das). Ohne Variable bzw. lokal: aus.                                                                     |
| `EARNIE_OFFLINE`                        | `1` = keine Loxone-/Live-Verbindung erforderlich. Der Bootstrap füllt leere Entitäts-IDs im Live-Szenario aus den Katalogen. Sinnvoll für die Streamlit Community Cloud. |
| `EARNIE_OPEN_METEO_CACHE_PATH`          | Verzeichnis für den Open-Meteo-Klimacache (Standard: `data/cache/open_meteo_utc`; das frühere `data/cache/open_meteo` wird nicht mehr gelesen und kann gelöscht werden). Vor allem für Tests und Container mit eigenem Cache-Volume. |
| `EARNIE_OPEN_METEO_AS_OF`               | Pinnt den letzten Archivtag des Open-Meteo-Klimacaches (ISO-Datum, z. B. `2026-10-22`). Der Cache-Schlüssel des laufenden Jahres bleibt dann stabil – für eingefrorene Offline-Läufe. Ein Datum nach dem tatsächlich letzten Archivtag oder ein ungültiges Format bricht mit Fehler ab. |
| `EARNIE_CLOUD_DEMO`                     | `1` = Betrieb in der Streamlit Community Cloud. Pro Browser-Sitzung gibt es einen leeren Greenfield-Workspace (Temp-Verzeichnis), Start im Hauskonfigurator und einen Willkommenshinweis. Einen Offline-Demo-Seed gibt es nicht. Typisch zusammen mit `EARNIE_OFFLINE=1`. |
| `EARNIE_USAGE_PING`                     | `off` = Kill-Switch: Es wird **nichts** gesendet, auch wenn die Zustimmung in der UI eingeschaltet ist. Andere Werte bzw. nicht gesetzt: Kill-Switch aus, die Zustimmung steuert. Siehe [Nutzungsstatistik](#nutzungsstatistik). |


Streamlit-Port-Übersicht (Stacks, Plattformen): [streamlit-ports.md](../dev/streamlit-ports.md).

## Nutzungsstatistik

Ab Version 2.7 kann Earnie optional und anonym melden, dass eine Installation aktiv ist (Versionszähler). So sehen wir, wie viele Installationen pro Tag aktiv sind. Es gibt keine Nutzungsanalyse, kein Feature-Tracking und kein Fehlerreporting. Wenn Sie zustimmen, unterstützen Sie damit die Weiterentwicklung von Earnie – vielen Dank!

**Zustimmung (drei Zustände):** noch nicht gefragt (`unset`), zugestimmt (`on`) oder abgelehnt (`off`). Gesendet wird nur bei `on`.

- Beim ersten Öffnen des **Szenario-Explorers** erscheint ein Dialog (ohne `scenario_explorer` in `EARNIE_UI_MODES`: beim **Szenarienkonfigurator**).
- Unter **Daemon Control → Optimierer-Dienst** können Sie die Zustimmung jederzeit umschalten.
- Unter **Was wird gesendet?** sehen Sie die exakte JSON-Vorschau.
- Der Endpunkt ist fest in der App hinterlegt (`https://cloudserver.earnie-hems.com/ping`).
- Ein fehlgeschlagener Ping hat **keinen Einfluss** auf die Optimierung.

**Was wird gesendet** (feste Feldliste, sonst nichts):

| Feld | Bedeutung |
| ---- | --------- |
| `v` | Schema-Version: `1`, bzw. `2`, sobald `points` mitgesendet wird. |
| `id` | Zufällige Installations-ID (UUIDv4). Sie entsteht erst bei Zustimmung und wird bei Widerruf gelöscht. |
| `app_version` | Earnie-Versionsstring. |
| `context` | Installationskontext: `loxberry`, `homeassistant_addon` oder `manual`. |
| `stage` | Höchster erreichter Meilenstein: `explorer` (Szenario-Explorer bzw. Fallback Szenarienkonfigurator) bzw. `live` (erster erfolgreicher Live-Zyklus). |
| `points` | Nur im Live-Betrieb: Summe der **Earnie-Points** der Live-Anlage (ganze Zahl, siehe [Earnie-Points](#earnie-points)). |
| `points_v` | Nur zusammen mit `points`: Version der Berechnungsregel (aktuell `1`). |

**Nicht** gesendet werden u. a. Preise, Orte, Gerätenamen, Konfigurationsinhalte, Hardware-Fingerprint und Einzelwerte der Anlage (nur die Punktesumme).

Wer bereits zugestimmt hat, wird wegen `points` nicht erneut gefragt. Die exakte JSON-Vorschau unter **Was wird gesendet?** zeigt jederzeit, was gesendet wird. Möchten Sie das nicht, können Sie die Nutzungsstatistik jederzeit abschalten (siehe unten).

### Earnie-Points

Die Earnie-Points sind eine grobe Größenkennzahl **einer Anlage** (ein Standort). Earnie berechnet sie aus dem **Live-Szenario**, nicht aus Szenarien des Szenarienkonfigurators. Die Seite **Optimierer-Dienst** zeigt sie unter **Earnie-Points dieser Anlage** mit Aufschlüsselung an. Zweck der Earnie-Points ist zukünftig die Zuordnung zu möglichen Abo-Tarifen. Derzeit ist das rein informativ und bei selbst verwalteten Installationen fallen auch keine Kosten an. Fehlen Angaben im Live-Szenario, zeigt Earnie den Grund an und sendet keine Punkte.

**Abschalten:**

1. **UI:** Den Schalter **Anonyme Nutzungsstatistik senden** unter **Optimierer-Dienst** ausschalten.
2. **Kill-Switch:** Umgebungsvariable `EARNIE_USAGE_PING=off` setzen (überschreibt die UI).
3. **Home-Assistant-Add-on:** Die optionale Option `usage_ping` (`true`/`false`) spiegelt die Zustimmung, wenn sie gesetzt ist. Ohne die Option bleibt der bestehende Zustand unverändert.

Lokal liegt der Zustand in `runtime/usage_ping.json`.

### Datenschutz

- **Rechtsgrundlage:** Einwilligung (Art. 6 Abs. 1 lit. a DSGVO), dokumentiert mit dem Zustimmungsdatum.
- **IP-Adresse / User-Agent:** Der Empfänger speichert sie **nicht** (kein Access-Log für diese Route). Beim Transport ist die IP-Adresse trotzdem ein personenbezogenes Datum; deshalb steht dieser Hinweis hier.
- **Speicherung serverseitig:** Die Installations-ID wird mit einem täglich wechselnden Salt gehasht. Gespeichert werden nur Tageszähler, es gibt also keine geräteübergreifende Profilbildung über Tage. Die Earnie-Points gehen nur als Verteilung ein (Histogramm der Punktesummen pro Tag), nicht als Wert je Installation.
- **Earnie-Points:** eine grobe abgeleitete Zahl ohne Konfigurationsinhalte. Aus ihr lässt sich die Anlage nicht zurückrechnen; sie dient nur der Statistik (keine Lizenz- oder Abrechnungsprüfung).
- **Hosting:** Der Zähler-Endpunkt läuft auf einem gemieteten VPS bei **hosttech** in der **EU**. Mit dem Hoster besteht ein **Auftragsverarbeitungsvertrag (AV)**.

### Feedback zum Szenario-Explorer

Wurde in einer Sitzung eine Simulation im **Szenario-Explorer** gestartet, kann beim Verlassen der Seite einmalig ein kurzer Feedback-Dialog erscheinen. Ihre Bewertung hilft uns, den Szenario-Explorer verständlicher zu machen – vielen Dank!

- **Inhalt:** Drei Fragen mit 1 bis 5 Sternen und ein optionaler Kommentar (max. 500 Zeichen).
- **Was wird gesendet:** nur die Sternebewertungen, der Kommentar und die Earnie-Version. Konfiguration, Zugangsdaten, Geräte-, Preis- und Standortdaten werden nicht gesendet.
- **Einmalig:** Nach **Senden** oder **Abbrechen** fragt Earnie auf dieser Installation nicht erneut. Der Zustand liegt in `runtime/feature_reviews.json`. In der Streamlit Community Cloud (`EARNIE_CLOUD_DEMO=1`) liegt `runtime/` im temporären Workspace der Browser-Sitzung. Dort gilt „einmalig“ deshalb nur pro Sitzung; in einer neuen Sitzung kann der Dialog wieder erscheinen.
- **Endpunkt:** fest in der App hinterlegt (`https://cloudserver.earnie-hems.com/review`). Schlägt das Senden fehl, zeigt der Dialog eine Fehlermeldung; die Optimierung ist nicht betroffen.

## Debug-Dump

Ein Debug-Dump hilft, Anzeige- oder Optimierungsprobleme nachzuvollziehen, ohne die Produktivdateien erneut zu durchsuchen. Aktiviert wird er über `ui.chart_debug_capture_enabled`, `local_settings.json` oder die Umgebungsvariable (siehe [Umgebungsvariablen](#umgebungsvariablen-optional)).

Ablauf im Live-Cockpit:

1. „Debug-Dump speichern“ anklicken.
2. Im Dialog optional Titel/Symptom eintragen.
3. „ZIP erstellen“ wählen (nur speichern) oder „ZIP erstellen und herunterladen“ (speichern und Browser-Download in einem Schritt).

Ein Dump enthält immer die volle Optimierungshistorie und die aktiven Inputs. Die Chart-Daten der Oberfläche (UI-Payload) schreibt Earnie mit, wenn die Live-Anzeige (Display-Bundle) vorhanden ist. Sonst enthält der Dump nur Historie und Inputs; die UI weist darauf hin.

| Inhalt | Pflicht / optional |
| ------ | ------------------ |
| `runtime/optimization_history.jsonl` | Pflicht (vollständig) |
| `optimizer_run_state.json`, `live_optimization_debug.json`, `flexible_consumers_state.json`, `pv_counter_state.json`, `powerstation_reserves.json` | Optional, falls vorhanden |
| `recorder/` (Cycle-Recorder-Ringpuffer inkl. Config-Snapshots) | Optional. Fenster = Retention (Default 7 Tage); enthält Lastprofile. |
| `manifest.chart` | Optional (nur mit Live-Anzeige) |
| `manifest.recorder` | Optional (`from` / `to` / `cycle_count` / `config_hashes`) |
| Titel / Symptom | Optional (`manifest.meta`) |

> **Datenschutz:** Das ZIP kann Lastprofile aus dem Cycle-Recorder enthalten – so viele Tage, wie `recorder_retention_days` vorgibt (Standard 7). Es nur an den Maintainer weitergeben und nicht in öffentliche Issues hochladen. Recorder abschalten: `recorder_enabled: false` in `local_settings.json` (siehe [Cycle-Recorder](#cycle-recorder-regression-r-rec)).

Gemeinsam in jedem ZIP:

- **`manifest.json`:** `schema_version: 3`, `dump_type: debug`, App-Version, Env-Overrides, aufgelöste Pfade; optional `chart`, immer `meta` (Titel/Symptom/case_id).
- **`inputs/*`:** aktive `config.json`, Sidecars, optional Preis-Modell und `cons_data.csv`.
- **`README.txt`:** Kurzbeschreibung der Struktur.

Dateiname: `debug_dump_YYYYMMDD_HHMMSS.zip` unter `runtime/chart_debug/` (oder `ui.chart_debug_capture_dir`).

### Replay (teilautomatisch)

```bash
python -m scripts.replay_debug_dump path/to/debug_dump_….zip
python -m scripts.replay_debug_dump path/to/debug_dump_….zip --html-out /tmp/chart1.html
```

Das Skript prüft die Pflichtdateien und führt einen Smoke-Pfad aus. Es parst die Historie und baut bei vorhandenem `chart.display_rows` zusätzlich Chart 1 neu auf. Akzeptiert werden nur Dumps mit `schema_version: 3` und `dump_type: debug`.

## Typische Betriebsfehler

- **App zeigt alte Werte:** `optimizer_run_state.json` fehlt oder `main.py` läuft nicht. Kopfzeile im Sankey „Energiefluss (Live)“ prüfen.
- **Keine aWATTar-Preise:** Die Simulation bricht in der App mit einer Fehlermeldung ab. Netzwerk oder API prüfen.
- **Nur Migrations-Assistent nach Update:** Die Config muss angepasst werden, siehe [Update und Migration](#update-und-migration). `main.py` startet erst danach.
