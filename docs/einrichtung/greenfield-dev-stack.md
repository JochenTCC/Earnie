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
| Worker | `ernie-greenfield-worker` | — |
| UI | `ernie-greenfield-ui` | **8502** → 8501 |

Im Browser: `http://localhost:8502`

## Ablauf Ersteinrichtung

1. **Bootstrap** — Entrypoint legt fehlende Dateien an (`python -m scripts.bootstrap_runtime`, siehe [Container](container.md)). `config.json` und die Planungs-Dateien starten **minimal** (leere Kataloge, keine Ernie-Beispieldaten).
2. **UI: Loxone-Zugang** — Formular aus [`ui/setup_dotenv.py`](../../ui/setup_dotenv.py); Platzhalter in `config/.env` reichen nicht.
3. **Dummy-Zugangsdaten** — Für Greenfield ohne echte Miniserver-Anbindung z. B. IP `192.168.178.99`, beliebiger Benutzer/Passwort eintragen und **Speichern**.
4. **Planungs-Konfiguration** — **Hauskonfigurator**, **Konfiguration** und (nach Freischaltung) **Szenarieneditor** sind sichtbar. Im Hauskonfigurator (Tabs): thermisches **Hausprofil**, **PV-Anlage**, **Batterie** anlegen; unter **Tarife** Bezugs- und Einspeisetarif aus dem Katalog wählen (`tariffs.json` — neue Einträge nur manuell in der Datei). Im Szenarieneditor: Runtime-Szenario (Entitäts-IDs) speichern. Sidebar zeigt fehlende Schritte. Während der Planung erscheint **kein** Config-Drift-Hinweis zu `flexible_consumers` aus `config.example.json`.
5. **Backtesting** — Nach vollständiger Planungs-Konfiguration erscheint die Backtesting-Seite. Szenarieneditor folgt in einem späteren Schritt.
6. **Worker** — `ernie-greenfield-worker` läuft weiter; Loxone-Startup-Prüfung ist deaktiviert (`ENERGY_OPTIMIZER_VERIFY_LOXONE_ON_START=0`).

## Checkliste — erwartete Dateien nach erstem Start

Nach `up` (vor manueller Ersteinrichtung) sollten u. a. vorhanden sein:

| Pfad | Erwartung |
|------|-----------|
| `greenfield/config/config.json` | Aus `config.minimal.json` — leere `batteries`/`pv_systems`/`flexible_consumers`, ID-only `runtime_settings` (keine flachen PV-/Batterie-/Tarif-Duplikate), Platzhalter-Loxone |
| `greenfield/config/config.example.json` | Vollständiges Referenzbeispiel (Ernie) — nur zum Nachschlagen |
| `greenfield/config/.env` | Aus `.env.example` (Platzhalter → Setup-Seite) |
| `greenfield/runtime/local_settings.json` | z. B. `{"loxone_silent_mode": false}` |
| `greenfield/runtime/cons_data_hourly.csv` | Nur CSV-Header, keine Messzeilen |
| `greenfield/config/house_profiles.json` | `profiles: []` |
| `greenfield/config/tariffs.json` | Katalog aus `tariffs.example.json` (mehrere Import-/Export-Tarife zur Auswahl) |
| `greenfield/config/backtesting_scenarios.json` | `scenarios: []` (Solver-Defaults bleiben) |

Weitere Bootstrap-Dateien (Tarife, `deviation_rules.json`, leere Profil-CSVs, Log) siehe `runtime_store/bootstrap.py`.

Nach **Speichern** in der Ersteinrichtung:

| Prüfung | Erwartung |
|---------|-----------|
| `greenfield/config/.env` | Echte IPv4 + Benutzer + Passwort (keine Platzhalter) |
| UI | Nur Hauskonfigurator + Konfiguration; Sidebar-Hinweis zu fehlenden Schritten |
| Worker-Log | `greenfield/runtime/energy_optimizer.log` — kein Abbruch wegen fehlender `.env` |

```powershell
docker compose -f docker-compose-greenfield.yml logs -f optimizer-worker
```

## Manuelle Abnahme (1.24.e)

Mit abgeschlossener Ersteinrichtung und vollständiger Planungs-Konfiguration:

1. **Hauskonfigurator** — Tabs Hausprofil (thermischer Verbraucher „Haus Wärme“, auto-IDs), PV, Batterie, Tarifwahl; Grundlast-Vorschau prüfen.
2. **Backtesting** — Seite erscheint nach Freischaltung; Szenario anlegen, Planung starten.
3. **Szenarieneditor** — vorerst nicht freigeschaltet.

`ENERGY_OPTIMIZER_UI_MODES=sunset2sunset,backtesting` — Sunset-2-Sunset ist seit **1.26.0 P0** für Live-Pfad-Smoke freigeschaltet (zusammen mit Backtesting).

## Abnahme Live-Pfad (1.26.0 P0)

Ziel: Greenfield nutzt **ID-only** `runtime_settings` (Entitäts-Referenzen + Geo/Zeitzone, keine flachen PV-/Batterie-/Tarif-Felder). Live-Optimierung und Backtesting sollen dieselbe Auflösungslogik nutzen.

**Voraussetzung:** ~~Backlog **1.26.0 P2** (`resolve_runtime_settings()` im Live-Pfad) ist implementiert.~~ Ab **1.26.0 P2** nutzt `_load_dynamic_params()` dieselbe Auflösung wie Backtesting.

### Checkliste (nach P2)

| Schritt | Prüfung | Erwartung |
|---------|---------|-----------|
| 1. Config | `greenfield/config/config.json` → `runtime_settings` | Nur Entitäts-IDs: `battery_id`, `import_tariff_id`, `export_tariff_id`, `house_profile_id`, optional `pv_system_id` — **keine** flachen PV-/Batterie-/Tarif-/Geo-Felder. Standort/Zeitzone in `house_profiles.json`. |
| 2. Entitäts-Auflösung | Szenarieneditor → Runtime → **Auflösung testen** | JSON mit aufgelösten PV-, Batterie- und Tarifparametern aus `batteries[]`, `pv_systems[]`, `tariffs.json` |
| 3. Live-Zyklus | `docker compose -f docker-compose-greenfield.yml logs -f optimizer-worker` | `main.py` durchläuft mindestens einen Optimierungszyklus ohne Config-Fehler |
| 4. UI Sunset-2-Sunset | Modus **Sunset-2-Sunset** in der UI | Aufgelöste Werte (PV kWp, Batterie, Einspeisevergütung) **read-only** — keine flachen Sidebar-Edits auf Duplikat-Felder |
| 5. Backtesting-Parität | Gleiche Tarif-IDs, gleiches Zeitfenster | Import/Export-cent/kWh identisch zu Live (Detail-Paritätstest folgt in **1.26.0 P3**) |

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

```powershell
.venv\Scripts\python.exe -m pytest tests/test_greenfield_bootstrap.py tests/test_setup_readiness.py tests/test_navigation_setup.py tests/test_planning_editors.py tests/test_config_drift.py -q
```

Prüft Bootstrap auf leerem Verzeichnis und den Übergang Setup → konfigurierte `.env` (ohne Docker).

## Abgrenzung

Port-Übersicht aller Stacks: [streamlit-ports.md](../referenz/streamlit-ports.md).

| Stack | Zweck |
|-------|--------|
| **Greenfield** (diese Datei) | Ersteinrichtung, leere Volumes, Port 8502 |
| `docker-compose.yml` | Lokaler Dev mit bestehendem `config/` + `runtime/` |
| **7g Silent** | Prod-Loxone lesen, `loxone_silent_mode` |
| **7g Simuliert** | Synthetisches Haus (nach Loxone-Simulator) |
