# Betrieb

## Zwei Einstiegspunkte

| Komponente | Befehl | Rolle |
|------------|--------|-------|
| **Produktiv-Daemon** | `python main.py` | Liest Loxone, optimiert, schreibt Steuerwerte — läuft dauerhaft |
| **Streamlit-App** | `python -m scripts.run_streamlit` | Cockpit, Simulation, Debugging — optional parallel |

Nur `main.py` steuert die Anlage. Die App **simuliert** den 24-Stunden-Horizont und zeigt den letzten Produktiv-Durchlauf an; sie überschreibt keine Loxone-Ausgänge (außer Sidebar-Parameter, die in `config.json` geschrieben werden).

## Optimierungs-Takt

- Auslösung an **Viertelstunden-Grenzen** (`:00`, `:15`, `:30`, `:45`)
- Zusätzlich **sofort**, wenn ein konfigurierter **Event-Trigger** (`system.event_triggers`) seinen Wert ändert
- `system.event_trigger_enabled` (Standard `true`): Event-Trigger ein/aus
- `system.event_poll_interval_sec` (Standard `60`): Abfrageintervall für `event_triggers` zwischen den regulären Läufen
- `system.event_triggers`: Liste der Loxone-Signale (binary/text) – siehe `config.schema.json`
- `system.loop_timeout` in `config.json`: maximale Wartezeit zwischen Durchläufen in Sekunden (Standard 900 = 15 Min.)
- Die App aktualisiert die Live-Simulation ca. **1 Minute nach** dem Viertelstunden-Wechsel, damit `main.py` zuerst laufen kann

Countdown und letzter Lauf werden unten in der App angezeigt (siehe [Charts & Panels](../ui/charts.md)).

## Laufzeitdateien (`runtime/`)

Standardverzeichnis: `runtime/` (überschreibbar mit `EARNIE_RUNTIME_DIR`, Legacy: `ENERGY_OPTIMIZER_RUNTIME_DIR`).

| Datei | Inhalt |
|-------|--------|
| `cons_data_hourly.csv` | Stündliche Verbrauchs- und PV-Basis (von `main.py` gepflegt) |
| `flexible_consumers_state.json` | Tagesenergie je Flex-Verbraucher |
| `pv_counter_state.json` | PV-Zählerstand für Stunden-Delta |
| `cons_data_pending.json` | Pending-Puffer für cons_data-Samples |
| `consumption_profiles.csv` | Berechnete Grundlast-Profile |
| `earnie.log` | Rotierendes Python-Log |
| `optimizer_run_state.json` | Letzter erfolgreicher `main.py`-Durchlauf (SoC, Modus, Soll-Leistungen, Flex-Soll) |
| `optimization_history.jsonl` | Historie aller Produktiv-Durchläufe (eine Zeile JSON pro Lauf) |
| `live_optimization_debug.json` | Debug-Snapshot der App-Simulation (Sunset-2-Sunset) |

Die App liest diese Dateien **read-only** für Panels und Abgleich.

## Umgebungsvariablen (optional)

| Variable | Wirkung |
|----------|---------|
| `EARNIE_CONFIG_PATH` | Pfad zur `config.json` (Standard: `config/config.json`, Legacy: `config.json` im Root). Legacy-Alias: `ENERGY_OPTIMIZER_CONFIG_PATH`. |
| `EARNIE_RUNTIME_DIR` | Anderes Verzeichnis für Laufzeitdaten |
| `EARNIE_UI_MODES` | Kommagetrennt: `sunset2sunset`, `scenario_exploration` — schränkt sichtbare App-Modi ein (Prod: `sunset2sunset,scenario_exploration`; siehe [Betriebsmodi](../ui/betriebsmodi.md)) |
| `EARNIE_UI_STREAMLIT_PORT` | TCP-Port für Streamlit (überschreibt `ui.streamlit_port`; siehe [Streamlit-Ports](../referenz/streamlit-ports.md)) |

Streamlit-Port-Übersicht (Stacks, Plattformen): [streamlit-ports.md](../referenz/streamlit-ports.md).

## Typische Betriebsfehler

- **Zwei `main.py`-Instanzen:** Steuerwerte können sich gegenseitig überschreiben — nur eine Produktiv-Instanz betreiben.
- **App zeigt alte Werte:** `optimizer_run_state.json` fehlt oder `main.py` läuft nicht — Kopfzeile im Sankey „Energiefluss (Live)“ prüfen.
- **Keine aWATTar-Preise:** Simulation bricht in der App mit Fehlermeldung ab; Netzwerk oder API prüfen.
