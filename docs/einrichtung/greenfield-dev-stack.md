# Greenfield Dev-Stack (1.24.c)

Lokaler Container-Stack im Zustand **nach Ersteinrichtung** — Abnahme-Infrastruktur für Hauskonfigurator und Backtesting auf dem Dev-PC. Kein Schreibzugriff auf produktive Loxone nötig; getrennt von pytest-Fixtures und von Silent-/Simuliert-Stacks (Backlog **7g**).

## Voraussetzungen

- Docker Desktop (Windows) oder Docker Engine
- Projekt-Checkout mit `docker-compose-greenfield.yml`

## Stack starten (leerer Zustand)

```powershell
mkdir greenfield\config, greenfield\runtime
docker compose -f docker-compose-greenfield.yml up -d --build
```

Persistente Daten liegen nur unter `greenfield/config/` und `greenfield/runtime/` — der normale Dev-Stack (`docker-compose.yml` mit `./config` und `./runtime`) bleibt unberührt.

| Service | Container | Host-Port |
|---------|-----------|-----------|
| Worker | `earnie-greenfield-worker` | — |
| UI | `earnie-greenfield-ui` | **8502** → 8501 |

Im Browser: `http://localhost:8502`

## Ablauf Ersteinrichtung

1. **Bootstrap** — Entrypoint legt fehlende Dateien an (`python -m scripts.bootstrap_runtime`, siehe [Container](container.md)). `config.json` und die Planungs-Dateien starten **minimal** (leere Kataloge, keine Earnie-Beispieldaten).
2. **UI: Loxone-Zugang** — Formular aus [`ui/setup_dotenv.py`](../../ui/setup_dotenv.py); Platzhalter in `config/.env` reichen nicht.
3. **Dummy-Zugangsdaten** — Für Greenfield ohne echte Miniserver-Anbindung z. B. IP `192.168.178.99`, beliebiger Benutzer/Passwort eintragen und **Speichern**.
4. **Planungs-Konfiguration** — Navigationsabschnitte **Planung** (Hauskonfigurator, nach Freischaltung Szenarieneditor) und **Echtzeit-Umgebung** (Live-Konfiguration). Im Hauskonfigurator: **Hausprofil**, **PV-Anlage**, **Batterien**. Im Szenarieneditor: Szenarien. In der Echtzeit-Umgebung: Live-Szenario wählen (`live_scenario_id`) und Entitäts-Referenzen speichern. Sidebar zeigt fehlende Schritte. Während der Planung erscheint **kein** Config-Drift-Hinweis zu `flexible_consumers` aus `config.example.json`.
5. **Scenario-Exploration** — Nach vollständiger Planungs-Konfiguration erscheint die Scenario-Exploration-Seite.
6. **Worker** — `earnie-greenfield-worker` läuft weiter; Loxone-Startup-Prüfung ist deaktiviert (`EARNIE_VERIFY_LOXONE_ON_START=0`).

## Checkliste — erwartete Dateien nach erstem Start

Nach `up` (vor manueller Ersteinrichtung) sollten u. a. vorhanden sein:

| Pfad | Erwartung |
|------|-----------|
| `greenfield/config/config.json` | Aus `config.minimal.json` — leere `batteries`/`pv_systems`/`flexible_consumers`, `live_scenario_id: live`, Platzhalter-Loxone |
| `greenfield/config/config.example.json` | Vollständiges Referenzbeispiel (Earnie) — nur zum Nachschlagen |
| `greenfield/config/.env` | Aus `.env.example` (Platzhalter → Setup-Seite) |
| `greenfield/runtime/local_settings.json` | z. B. `{"loxone_silent_mode": false}` |
| `greenfield/runtime/cons_data_hourly.csv` | Nur CSV-Header, keine Messzeilen |
| `greenfield/config/house_profiles.json` | `profiles: []` |
| `greenfield/config/tariffs.json` | Katalog aus `tariffs.example.json` (mehrere Import-/Export-Tarife zur Auswahl) |
| `greenfield/config/backtesting_scenarios.json` | Mindestens Live-Szenario `live` (aus `backtesting_scenarios.minimal.json`) |

Weitere Bootstrap-Dateien (Tarife, `deviation_rules.json`, leere Profil-CSVs, Log) siehe `runtime_store/bootstrap.py`.

Nach **Speichern** in der Ersteinrichtung:

| Prüfung | Erwartung |
|---------|-----------|
| `greenfield/config/.env` | Echte IPv4 + Benutzer + Passwort (keine Platzhalter) |
| UI | Nur Hauskonfigurator + Live-Konfiguration (Echtzeit-Umgebung); Sidebar-Hinweis zu fehlenden Schritten |
| Worker-Log | `greenfield/runtime/earnie.log` — kein Abbruch wegen fehlender `.env` |

```powershell
docker compose -f docker-compose-greenfield.yml logs -f optimizer-worker
```

## Manuelle Abnahme (1.24.e)

Mit abgeschlossener Ersteinrichtung und vollständiger Planungs-Konfiguration:

1. **Hauskonfigurator** — Tabs Hausprofil (thermischer Verbraucher „Haus Wärme“, auto-IDs), PV, Batterien; Grundlast-Vorschau prüfen.
2. **Szenarieneditor** — Szenario pflegen.
3. **Echtzeit-Umgebung** — Live-Szenario und Entitäts-Referenzen speichern.
4. **Scenario-Exploration** — Seite erscheint nach Freischaltung; Planung starten.

`EARNIE_UI_MODES=sunset2sunset,scenario_exploration` — Sunset-2-Sunset ist seit **1.26.0 P0** für Live-Pfad-Smoke freigeschaltet (zusammen mit Scenario-Exploration). In `docker-compose-greenfield.yml` gesetzt.

## Abnahme Live-Pfad (1.26.0 P0 / 2.0 P2)

Ziel: Greenfield nutzt **`live_scenario_id`** + Live-Szenario in `backtesting_scenarios.json` (Entitäts-Referenzen, keine flachen PV-/Batterie-/Tarif-Duplikate in `config.json`). Live-Optimierung und Scenario-Exploration nutzen dieselbe Auflösungslogik.

**Voraussetzung:** Ab **1.26.0 P2** nutzt `_load_dynamic_params()` dieselbe Auflösung wie Scenario-Exploration; ab **2.0 P2** entfällt `runtime_settings` in `config.json`.

### Checkliste (nach 2.0 P2)

| Schritt | Prüfung | Erwartung |
|---------|---------|-----------|
| 1. Config | `greenfield/config/config.json` | `live_scenario_id: live`, **kein** Block `runtime_settings` |
| 2. Live-Szenario | `greenfield/config/backtesting_scenarios.json` → Szenario `live` | Entitäts-IDs: `battery_id`, `import_tariff_id`, `export_tariff_id`, `house_profile_id`, optional `pv_system_id` — Geo/Zeitzone aus `house_profiles.json` |
| 3. Entitäts-Auflösung | Echtzeit-Umgebung → Live-Konfiguration | JSON mit aufgelösten PV-, Batterie- und Tarifparametern aus `batteries[]`, `pv_systems[]`, `tariffs.json` |
| 3. Live-Zyklus | `docker compose -f docker-compose-greenfield.yml logs -f optimizer-worker` | `main.py` durchläuft mindestens einen Optimierungszyklus ohne Config-Fehler |
| 4. UI Sunset-2-Sunset | Seite **Cockpit** | Aufgelöste Werte (PV kWp, Batterie, Einspeisevergütung) **read-only** auf **Live-Konfiguration** — keine Sidebar-Edits |
| 5. Scenario-Exploration-Parität | Gleiche Tarif-IDs, gleiches Zeitfenster | Import/Export-cent/kWh identisch zu Live (Detail-Paritätstest folgt in **1.26.0 P3**) |

```powershell
docker compose -f docker-compose-greenfield.yml up -d --build
docker compose -f docker-compose-greenfield.yml logs -f optimizer-worker
```

Bei lokalem venv (Port **8511**): VS Code Compound **„main.py + Streamlit (Greenfield :8511)“** — Worker + UI mit `greenfield/config` + `greenfield/runtime`. Alternativ nur UI: „Streamlit app.py (LOKAL, Greenfield :8511)“.

## Stack zurücksetzen

Komplett neu (alle Greenfield-Daten löschen):

```powershell
docker compose -f docker-compose-greenfield.yml down
Remove-Item -Recurse -Force greenfield\config, greenfield\runtime
mkdir greenfield\config, greenfield\runtime
docker compose -f docker-compose-greenfield.yml up -d --build
```

## Automatisierter Smoke-Test

### Ohne Docker (pytest)

```powershell
.venv\Scripts\python.exe -m pytest tests/test_greenfield_bootstrap.py tests/test_setup_readiness.py tests/test_navigation_setup.py tests/test_planning_editors.py tests/test_config_drift.py -q
```

Prüft Bootstrap auf leerem Verzeichnis und den Übergang Setup → konfigurierte `.env`.

### Docker-Stack (Earnie rename / Greenfield)

Vorbereiten (Verzeichnisse anlegen):

```powershell
.venv\Scripts\python.exe -m scripts.smoke_greenfield_docker --prepare-only
```

Vollständiger Smoke-Test (build, start, Bootstrap-Dateien, Worker-Log, UI :8502):

```powershell
.venv\Scripts\python.exe -m scripts.smoke_greenfield_docker
```

**Voraussetzung:** `version.py` muss gültige SemVer enthalten (z. B. `2.0.0`) — Werte wie `2.0.0 (wip)` brechen den Docker-Build ab.

Komplett neu (Volumes leeren):

```powershell
.venv\Scripts\python.exe -m scripts.smoke_greenfield_docker --reset
```

Schnellerer Lauf ohne Image-Rebuild:

```powershell
.venv\Scripts\python.exe -m scripts.smoke_greenfield_docker --no-build
```

**Erwartung bei Erfolg:** Container `earnie-greenfield-worker` und `earnie-greenfield-ui` running; Bootstrap-Dateien unter `greenfield/`; Worker-Log mit „Earnie Live-Abfrage gestartet“ (Loxone-Zugriff schlägt mit Dummy-`.env` erwartbar fehl); Streamlit antwortet auf `http://localhost:8502/`.

Hilfs-Tests (ohne Docker): `tests/test_smoke_greenfield_docker.py`.

## Abgrenzung

Port-Übersicht aller Stacks: [streamlit-ports.md](../referenz/streamlit-ports.md).

| Stack | Zweck |
|-------|--------|
| **Greenfield** (diese Datei) | Ersteinrichtung, leere Volumes, Port 8502 |
| `docker-compose.yml` | Lokaler Dev mit bestehendem `config/` + `runtime/` |
| **7g Silent** | Prod-Loxone lesen, `loxone_silent_mode` |
| **7g Simuliert** | Synthetisches Haus (nach Loxone-Simulator) |
