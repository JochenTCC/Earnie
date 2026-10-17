# Greenfield Dev-Stack 

Der Greenfield-Stack ist ein lokaler Container-Stack im Zustand **nach der Ersteinrichtung**. Er dient als Abnahme-Umgebung für Hauskonfigurator und Backtesting auf dem Dev-PC. Schreibzugriff auf eine produktive Loxone ist nicht nötig. Der Stack ist getrennt von den pytest-Fixtures und von den Silent- und Simuliert-Stacks.

## Voraussetzungen

- Docker Desktop (Windows) oder Docker Engine
- Projekt-Checkout mit `docker/compose/greenfield.yml`

## Stack starten (leerer Zustand)

```powershell
mkdir greenfield\config, greenfield\runtime
docker compose --project-directory . -f docker/compose/greenfield.yml up -d --build
```

Persistente Daten liegen nur unter `greenfield/config/` und `greenfield/runtime/`. Der normale Dev-Stack (`docker/compose/dev.yml` mit `./earnie_env/config` und `./earnie_env/runtime`) bleibt unberührt.

| Service | Container | Host-Port |
|---------|-----------|-----------|
| earnie | `earnie-greenfield` | **8502** → 8501 |

Im Browser: `http://localhost:8502`

## Ablauf Ersteinrichtung

1. **Bootstrap:** Der Entrypoint legt fehlende Dateien an (`python -m scripts.bootstrap_runtime`, siehe [Container](container.md)). `config.json` und die Planungs-Dateien starten **minimal**, also mit leeren Katalogen und ohne Earnie-Beispieldaten.
2. **Planungs-Konfiguration:** Solange die Planung nicht abgeschlossen ist, zeigt die Navigation nur zwei Bereiche:
   - **Konfiguration:** Hauskonfigurator, nach Freischaltung auch Szenarienkonfigurator und Szenario-Explorer.
   - **Daemon Control:** Optimierer-Dienst und EHAL-Com.

   Die Backend-Einrichtung ist in dieser Phase bewusst zurückgestellt (`loxone_setup_deferred`). Im Hauskonfigurator werden **Hausprofil**, **Wechselrichter**, **PV-Anlagen** und **Batterien** angelegt, im Szenarienkonfigurator das Live-Szenario und Varianten (Entitäts-Referenzen). Die Sidebar listet die noch fehlenden Schritte. Während der Planung erscheint **kein** Config-Drift-Hinweis zu `flexible_consumers` aus `config.example.json`.
3. **Smarthome-Backend (nur für den Live-Pfad):** Ist die Planung abgeschlossen und noch kein Backend konfiguriert, blockiert die App die übrige Navigation mit der Seite **Smarthome-Backend** (`ui/pages/page_smarthome_backend.py`, siehe [Smarthome-Backend](../ui/smarthome-backend.md)). Für Greenfield ohne echte Miniserver-Anbindung genügt Backend **Loxone** mit Dummy-Zugangsdaten: z. B. IP `192.168.178.99`, beliebiger Benutzer und beliebiges Passwort, danach **Speichern**.
4. **Szenario-Explorer:** Nach vollständiger Planungs-Konfiguration erscheint die Seite Szenario-Explorer unter **Konfiguration**. Für reine Was-wäre-wenn-Rechnungen ist dafür kein Smarthome-Backend nötig.
5. **Daemon:** `main.py` startet zusammen mit der UI (`EARNIE_AUTO_START_MAIN=1`). Die Loxone-Prüfung beim Start ist deaktiviert (`EARNIE_VERIFY_LOXONE_ON_START=0`).

## Checkliste: erwartete Dateien nach dem ersten Start

Nach `up` und vor der manuellen Ersteinrichtung sollten u. a. diese Dateien vorhanden sein:

| Pfad | Erwartung |
|------|-----------|
| `greenfield/config/config.json` | Aus `config.minimal.json`: leere `flexible_consumers`, `live_scenario_id: live`, Platzhalter-Loxone |
| `greenfield/config/components.json` | Aus `components.minimal.json`: leere `batteries`/`pv_systems` |
| `greenfield/config/config.example.json` | Vollständiges Referenzbeispiel (Earnie), nur zum Nachschlagen |
| `greenfield/config/.env` | Aus `.env.example` (Platzhalter → Setup-Seite) |
| `greenfield/runtime/local_settings.json` | z. B. `{"silent_mode": false}` |
| `greenfield/runtime/cons_data.csv` | Nur CSV-Header, keine Messzeilen |
| `greenfield/config/house_profiles.json` | `profiles: []` |
| `greenfield/config/tariffs.json` | Katalog aus `share/config/tariffs.json` (Fallback: `tariffs.example.json`) |
| `greenfield/config/grid_fees.json` | Netzentgelt-Katalog aus `share/config/grid_fees.json` |
| `greenfield/config/backtesting_scenarios.json` | Mindestens das Live-Szenario `live` (aus `backtesting_scenarios.minimal.json`) |

Weitere Bootstrap-Dateien (Tarife, `deviation_rules.json`, leere Profil-CSVs, Log) stehen in `runtime_store/bootstrap.py`.

Nach **Speichern** in der Ersteinrichtung:

| Prüfung | Erwartung |
|---------|-----------|
| `greenfield/config/.env` | Echte IPv4-Adresse, Benutzer und Passwort (keine Platzhalter) |
| Worker-Log | `greenfield/runtime/earnie.log` ohne Abbruch wegen fehlender `.env` |
| UI | Nur Hauskonfigurator (Szenarienkonfigurator nach angelegtem Hausprofil) und Optimierer-Dienst (Daemon Control); Sidebar-Hinweis zu fehlenden Schritten |

```powershell
docker compose --project-directory . -f docker/compose/greenfield.yml logs -f earnie
```

## Manuelle Abnahme 

Voraussetzung: abgeschlossene Ersteinrichtung und vollständige Planungs-Konfiguration.

1. **Hauskonfigurator:** Tabs Hausprofil (thermischer Verbraucher „Haus Wärme“, automatische IDs), Wechselrichter, PV und Batterien durchgehen; Grundlast-Vorschau prüfen.
2. **Szenarienkonfigurator:** Live-Szenario und Entitäts-Referenzen speichern, optional Varianten anlegen.
3. **Szenario-Explorer:** Die Seite erscheint nach Freischaltung; Planung starten.

`docker/compose/greenfield.yml` setzt `EARNIE_UI_MODES=sunset2sunset,scenario_explorer,live_environment`. Damit ist Sunset-2-Sunset für den Smoke-Test des Live-Pfads freigeschaltet, zusammen mit Szenario-Explorer und Daemon Control.

## Abnahme Live-Pfad

**Ziel:** Greenfield nutzt **`live_scenario_id`** und das Live-Szenario in `backtesting_scenarios.json` mit Entitäts-Referenzen. `config.json` enthält keine flachen Duplikate von PV-, Batterie- oder Tarifwerten. Live-Optimierung und Szenario-Explorer verwenden dieselbe Auflösungslogik.

**Voraussetzung:** `_load_dynamic_params()` nutzt dieselbe Auflösung wie der Szenario-Explorer, und `config.json` enthält keinen Block `runtime_settings` mehr.

### Checkliste

| Schritt | Prüfung | Erwartung |
|---------|---------|-----------|
| 1. Config | `greenfield/config/config.json` | `live_scenario_id: live`, **kein** Block `runtime_settings` |
| 2. Live-Szenario | `greenfield/config/backtesting_scenarios.json` → Szenario `live` | Entitäts-IDs `battery_id`, `import_tariff_id`, `export_tariff_id`, `house_profile_id`, optional `pv_system_ids`; Geo-Daten und Zeitzone kommen aus `house_profiles.json` |
| 3. Entitäts-Auflösung | Konfiguration → Szenarienkonfigurator (Live-Szenario) | Die Entitäts-IDs verweisen auf PV-, Batterie- und Tarifparameter aus `components.json` und `tariffs.json` |
| 3. Live-Zyklus | `docker compose --project-directory . -f docker/compose/greenfield.yml logs -f earnie` | `main.py` durchläuft mindestens einen Optimierungszyklus ohne Config-Fehler |
| 4. UI Sunset-2-Sunset | Seite **Monitor** (Live-Cockpit) | Aufgelöste Werte aus dem Live-Szenario, keine Sidebar-Eingaben für PV, Batterie oder Tarife |
| 5. Szenario-Explorer-Parität | Gleiche Tarif-IDs, gleiches Zeitfenster | Import- und Export-Preise (cent/kWh) identisch zu Live (ein detaillierter Paritätstest folgt) |

```powershell
docker compose --project-directory . -f docker/compose/greenfield.yml up -d --build
docker compose --project-directory . -f docker/compose/greenfield.yml logs -f earnie
```

Mit lokalem venv (Port **8532**) die VS-Code-Startkonfigurationen **„main.py (Greenfield)“** und **„Streamlit app.py (Greenfield :8532)“** verwenden. Worker und UI laufen dann mit `greenfield/config` und `greenfield/runtime`. Für nur die UI genügt „Streamlit app.py (Greenfield :8532)“ (oder „… auto main“).

## Stack zurücksetzen

Komplett neu beginnen (alle Greenfield-Daten werden gelöscht):

```powershell
docker compose --project-directory . -f docker/compose/greenfield.yml down
Remove-Item -Recurse -Force greenfield\config, greenfield\runtime
mkdir greenfield\config, greenfield\runtime
docker compose --project-directory . -f docker/compose/greenfield.yml up -d --build
```

## Automatisierter Smoke-Test

### Ohne Docker (pytest)

```powershell
.venv\Scripts\python.exe -m scripts.run_pytest tests/test_greenfield_bootstrap.py tests/test_setup_readiness.py tests/test_navigation_setup.py tests/test_planning_editors.py tests/test_config_drift.py -q
```

Die Tests prüfen den Bootstrap auf einem leeren Verzeichnis und den Übergang vom Setup zur konfigurierten `.env`.

### Docker-Stack (Greenfield)

Verzeichnisse vorbereiten:

```powershell
.venv\Scripts\python.exe -m scripts.smoke_greenfield_docker --prepare-only
```

Vollständiger Smoke-Test (Build, Start, Bootstrap-Dateien, Worker-Log, UI auf Port 8502):

```powershell
.venv\Scripts\python.exe -m scripts.smoke_greenfield_docker
```

> **Hinweis:** `version.py` muss eine gültige SemVer- bzw. Pre-release-Version enthalten (z. B. `2.7.0-dev.61`). Der Image-Build normalisiert die Version (`rewrite_version_file_for_image`).

Komplett neu (Volumes leeren):

```powershell
.venv\Scripts\python.exe -m scripts.smoke_greenfield_docker --reset
```

Schnellerer Lauf ohne Image-Rebuild:

```powershell
.venv\Scripts\python.exe -m scripts.smoke_greenfield_docker --no-build
```

**Erwartung bei Erfolg:**

- Der Container `earnie-greenfield` läuft.
- Die Bootstrap-Dateien liegen unter `greenfield/`.
- Das Log enthält „Earnie Live-Abfrage gestartet“. Der Loxone-Zugriff schlägt mit der Dummy-`.env` erwartungsgemäß fehl.
- Streamlit antwortet auf `http://localhost:8502/`.

Hilfs-Tests ohne Docker: `tests/test_smoke_greenfield_docker.py`.

## Abgrenzung

Port-Übersicht aller Stacks: [streamlit-ports.md](../referenz/streamlit-ports.md).

| Stack | Zweck |
|-------|--------|
| **Greenfield** (diese Datei) | Ersteinrichtung, leere Volumes, Host-Port **8502** (Docker) / **8532** (venv) |
| `docker/compose/dev.yml` | Lokale Entwicklung mit `./earnie_env/…`, Host-Port **8521** |
| **Silent** | Produktive Loxone nur lesen, `loxone_silent_mode` |
| **Simuliert** | Synthetisches Haus (nach Loxone-Simulator) |
