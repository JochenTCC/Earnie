# Betrieb

## Zwei Einstiegspunkte


| Komponente           | Befehl                            | Rolle                                                                               |
| -------------------- | --------------------------------- | ----------------------------------------------------------------------------------- |
| **Produktiv-Daemon** | `python main.py`                  | Liest Loxone, optimiert, schreibt Steuerwerte — läuft dauerhaft                     |
| **Streamlit-App**    | `python -m scripts.run_streamlit` | Cockpit, Anzeige der letzten Optimierung von main.py, Debugging — optional parallel |


Nur `main.py` steuert die Anlage. Die App **zeigt** den von `main.py` berechneten 24-48 Stunden-Horizont an (persistiert in `live_optimization_debug.json`); sie überschreibt keine Loxone-Ausgänge. Konfiguration wird über die Planungs- und Echtzeit-Seiten geschrieben (Hauskonfigurator, Live-Konfiguration, Manuelle Geräte).

## Optimierungs-Takt

- Auslösung an **Viertelstunden-Grenzen** (`:00`, `:15`, `:30`, `:45`)
- Zusätzlich **sofort**, wenn ein konfigurierter **Event-Trigger** (`system.event_triggers`) seinen Wert ändert
- `system.event_trigger_enabled` (Standard `true`): Event-Trigger ein/aus
- `system.event_poll_interval_sec` (Standard `60`): Abfrageintervall für `event_triggers` zwischen den regulären Läufen
- `system.event_triggers`: Liste der Loxone-Signale (binary/text) – siehe `config.schema.json`
- `system.loop_timeout` in `config.json`: maximale Wartezeit zwischen Durchläufen in Sekunden (Standard 900 = 15 Min.)
- Die App lädt den Cockpit-Snapshot nach dem Viertelstunden-Wechsel, sobald `main.py` den aktuellen Slot abgeschlossen hat (typisch wenige Sekunden)

Countdown und letzter Lauf werden unten in der App angezeigt (siehe [Charts & Panels](../ui/charts.md)).

## Laufzeitdateien (`runtime/`)

Standardverzeichnis: `runtime/` (überschreibbar mit `EARNIE_RUNTIME_DIR`, Legacy: `ENERGY_OPTIMIZER_RUNTIME_DIR`).


| Datei                           | Inhalt                                                                                       |
| ------------------------------- | -------------------------------------------------------------------------------------------- |
| `cons_data_hourly.csv`          | Stündliche Verbrauchs- und PV-Basis (von `main.py` gepflegt)                                 |
| `flexible_consumers_state.json` | Tagesenergie je Flex-Verbraucher                                                             |
| `pv_counter_state.json`         | PV-Zählerstand für Stunden-Delta                                                             |
| `cons_data_pending.json`        | Pending-Puffer für cons_data-Samples                                                         |
| `consumption_profiles.csv`      | Berechnete Grundlast-Profile                                                                 |
| `earnie.log`                    | Rotierendes Python-Log von main.py                                                           |
| `optimizer_run_state.json`      | Letzter erfolgreicher `main.py`-Durchlauf (SoC, Modus, Soll-Leistungen, Flex-Soll)           |
| `optimization_history.jsonl`    | Historie aller Produktiv-Durchläufe (eine Zeile JSON pro Lauf)                               |
| `live_optimization_debug.json`  | Anzeige-Snapshot des Optimierungs-Horizonts (von `main.py` geschrieben, von der App gelesen) |
| `local_settings.json`           | Lokale Betriebseinstellungen (z. B. `loxone_silent_mode`, `chart_debug_capture_enabled`)     |
| `appliance_schedules.json`      | Geplante Laufzeiten manueller Geräte                                                         |
| `backtesting_log.json`          | Ergebnis von Szenario-Explorer / `run_backtesting`                                        |


Die App liest diese Dateien **read-only** für Panels und Abgleich.

### Log- und Historiendateien

Betriebsstatus der wichtigsten Log-, Historien- und Debug-Dateien (Review 2026-06):


| Datei                                | Status                         | Hinweis                                                       |
| ------------------------------------ | ------------------------------ | ------------------------------------------------------------- |
| `optimization_history.jsonl`         | **kanonisch**                  | Produktiv-Historie (eine JSON-Zeile pro Optimierungslauf)     |
| `earnie.log`                         | **aktiv**                      | Rotierendes Python-Log von `main.py` (5×5 MB, 5 Archive)      |
| `optimizer_run_state.json`           | **aktiv**                      | Letzter erfolgreicher `main.py`-Durchlauf                     |
| `live_optimization_debug.json`       | **aktiv**                      | 24h-Anzeige-Snapshot für die Streamlit-App                    |
| `system_history_log.csv`             | **Legacy, nur Lesen**          | Archivieren, sobald `optimization_history.jsonl` ausreicht    |
| `pv_accuracy_log.csv`                | **Lesen aktiv, Schreiben aus** | Bestehende Einträge noch lesbar; Neuschreiben deaktiviert     |
| `backtesting_log.json`               | **nur Dev/Backtesting**        | Ergebnis von Szenario-Explorer — nicht für Produktiv-NAS   |


## Umgebungsvariablen (optional)


| Variable                                | Wirkung                                                                                                                                                                                                                              |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `EARNIE_CONFIG_PATH`                    | Pfad zur `config.json` (Standard: `config/config.json`, Legacy: `config.json` im Root). Legacy-Alias: `ENERGY_OPTIMIZER_CONFIG_PATH`.                                                                                                |
| `EARNIE_RUNTIME_DIR`                    | Anderes Verzeichnis für Laufzeitdaten                                                                                                                                                                                                |
| `EARNIE_UI_MODES`                       | Kommagetrennt: `sunset2sunset`, `scenario_explorer` — schränkt sichtbare Analyse-Seiten ein (Prod: `sunset2sunset,scenario_explorer`; siehe [Betriebsmodi](../ui/betriebsmodi.md)). Legacy-Alias: `ENERGY_OPTIMIZER_UI_MODES`. |
| `EARNIE_UI_STREAMLIT_PORT`              | TCP-Port für Streamlit (überschreibt `ui.streamlit_port`; siehe [Streamlit-Ports](../referenz/streamlit-ports.md))                                                                                                                   |
| `EARNIE_UI_CHART_DEBUG_CAPTURE_ENABLED` | `1` = Button „Debug-Dump speichern“ im Cockpit (überschreibt `ui.chart_debug_capture_enabled`; ZIP unter `runtime/chart_debug/`). Legacy-Alias: `ENERGY_OPTIMIZER_UI_CHART_DEBUG_CAPTURE_ENABLED`.                                  |


Streamlit-Port-Übersicht (Stacks, Plattformen): [streamlit-ports.md](../referenz/streamlit-ports.md).

## Debug-Dump

Zum Nachvollziehen von Anzeige- oder Optimizer-Problemen ohne erneutes Durchsuchen der Produktivdateien. Aktivierung wie oben (`ui.chart_debug_capture_enabled`, `local_settings.json` oder Env-Variable). Im Live-Cockpit: „Debug-Dump speichern“ → Dialog mit optionalem Titel/Symptom → „ZIP erstellen“ (nur speichern) oder „ZIP erstellen und herunterladen“ (speichern und Browser-Download in einem Schritt).

Ein Dump enthält immer die volle Optimierungshistorie und die aktiven Inputs. Die Chart-UI-Payload wird mitgeschrieben, wenn die Live-Anzeige (Display-Bundle) vorhanden ist; sonst nur Historie/Inputs (Hinweis in der UI).

| Inhalt | Pflicht / optional |
| ------ | ------------------ |
| `runtime/optimization_history.jsonl` | Pflicht (vollständig) |
| `optimizer_run_state.json`, `live_optimization_debug.json`, `flexible_consumers_state.json`, `pv_counter_state.json` | Optional, falls vorhanden |
| `manifest.chart` | Optional (nur mit Live-Anzeige) |
| Titel / Symptom | Optional (`manifest.meta`) |

Gemeinsam in jedem ZIP:

- `manifest.json` — `schema_version: 3`, `dump_type: debug`, App-Version, Env-Overrides, aufgelöste Pfade; optional `chart`, immer `meta` (Titel/Symptom/case_id)
- `inputs/*` — aktive `config.json`, Sidecars, optional Preis-Modell und `cons_data_hourly.csv`
- `README.txt` — Kurzbeschreibung der Struktur

Dateiname: `debug_dump_YYYYMMDD_HHMMSS.zip` unter `runtime/chart_debug/` (oder `ui.chart_debug_capture_dir`). Alte ZIPs `debug_dump_chart_*` / `debug_dump_prod_*` (schema v1/v2) bleiben lesbar für Replay und Fixture-Promotion.

### Replay (teilautomatisch)

```bash
python -m scripts.replay_debug_dump path/to/debug_dump_….zip
python -m scripts.replay_debug_dump path/to/debug_dump_….zip --html-out /tmp/chart1.html
```

Prüft Pflichtdateien und führt einen Smoke-Pfad aus (Historie parsen; bei vorhandenem `chart.display_rows` zusätzlich Chart-1-Neuaufbau). Alte Chart-/Prod-Debug-ZIPs und `schema_version: 1` werden weiterhin erkannt.

### Prod-Dump als Regression-Fixture

Ein gespeichertes Debug-ZIP kann nach `tests/fixtures/prod_dumps/<id>/` übernommen werden:

```bash
python scripts/archive_prod_dump.py \
  --id mein_fall_2026-07-16 \
  --title "Kurzbeschreibung" \
  --symptom "Beobachtetes Fehlerbild" \
  --source runtime/chart_debug/debug_dump_….zip
```

Details: `tests/fixtures/prod_dumps/README.md`.

## Typische Betriebsfehler

- **App zeigt alte Werte:** `optimizer_run_state.json` fehlt oder `main.py` läuft nicht — Kopfzeile im Sankey „Energiefluss (Live)“ prüfen.
- **Keine aWATTar-Preise:** Simulation bricht in der App mit Fehlermeldung ab; Netzwerk oder API prüfen.

