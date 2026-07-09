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

1. **Bootstrap** — Entrypoint legt fehlende Dateien an (`python -m scripts.bootstrap_runtime`, siehe [Container](container.md)).
2. **UI: Loxone-Zugang** — Formular aus [`ui/setup_dotenv.py`](../../ui/setup_dotenv.py); Platzhalter in `config/.env` reichen nicht.
3. **Dummy-Zugangsdaten** — Für Greenfield ohne echte Miniserver-Anbindung z. B. IP `192.168.178.99`, beliebiger Benutzer/Passwort eintragen und **Speichern**.
4. **Worker** — `ernie-greenfield-worker` läuft weiter; Loxone-Startup-Prüfung ist deaktiviert (`ENERGY_OPTIMIZER_VERIFY_LOXONE_ON_START=0`).

## Checkliste — erwartete Dateien nach erstem Start

Nach `up` (vor manueller Ersteinrichtung) sollten u. a. vorhanden sein:

| Pfad | Erwartung |
|------|-----------|
| `greenfield/config/config.json` | Aus `config.example.json` |
| `greenfield/config/.env` | Aus `.env.example` (Platzhalter → Setup-Seite) |
| `greenfield/runtime/local_settings.json` | z. B. `{"loxone_silent_mode": false}` |
| `greenfield/runtime/cons_data_hourly.csv` | Nur CSV-Header, keine Messzeilen |
| `greenfield/config/house_profiles.json` | Leere/minimale Hausprofile-Vorlage |
| `greenfield/config/backtesting_scenarios.json` | Szenario-Vorlage |

Weitere Bootstrap-Dateien (Tarife, `deviation_rules.json`, leere Profil-CSVs, Log) siehe `runtime_store/bootstrap.py`.

Nach **Speichern** in der Ersteinrichtung:

| Prüfung | Erwartung |
|---------|-----------|
| `greenfield/config/.env` | Echte IPv4 + Benutzer + Passwort (keine Platzhalter) |
| UI | Lädt Cockpit/Navigation statt Setup-Formular |
| Worker-Log | `greenfield/runtime/energy_optimizer.log` — kein Abbruch wegen fehlender `.env` |

```powershell
docker compose -f docker-compose-greenfield.yml logs -f optimizer-worker
```

## Manuelle Abnahme (1.24.0)

Mit abgeschlossener Ersteinrichtung:

1. **Backtesting** — Sidebar-Modus „Backtesting“; Szenario wählen oder anlegen, Planung starten.
2. **Hauskonfigurator** — Konfiguration → Hauskonfigurator; Profil anlegen/bearbeiten, Grundlast-Vorschau prüfen.
3. **Szenarieneditor** — optional, gleiche persistente `config/`-Dateien.

`ENERGY_OPTIMIZER_UI_MODES=backtesting` — Sunset-2-Sunset ist in diesem Stack absichtlich aus; Hauskonfigurator und Szenarieneditor sind immer registriert.

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
.venv\Scripts\python.exe -m pytest tests/test_greenfield_bootstrap.py -q
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
