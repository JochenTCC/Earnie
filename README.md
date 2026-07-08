# Energy Optimizer

Python-basierte Energieoptimierung für Smarthome (Batterie, PV, flexible Verbraucher) mit Streamlit-UI und Produktiv-Daemon (`main.py`).

## Anwender-Dokumentation

Einrichtung, Konfiguration, Streamlit-Oberfläche und Loxone-Schnittstelle: **[docs/README.md](docs/README.md)**

## Projektstruktur

```
Energy-Optimizer/
├── main.py, app.py          # Einstiegspunkte (bleiben in der Wurzel)
├── config.py                # Konfigurations-Loader
├── config/
│   ├── config.json          # Haus-Konfiguration (gitignored, persistent)
│   ├── config.example.json  # Vorlage für neue Installationen
│   └── config.schema.json   # JSON-Schema (Editor-Hover)
├── optimizer/               # MILP, Simulation, Ladekontext, Facade
├── integrations/            # Loxone, Awattar, Log-Import
├── data/                    # Profile, Verbrauch, PV-Prognose
├── simulation/              # Backtesting-Engine
├── runtime_store/           # JSON-Persistenz, Bootstrap, Config-Drift
├── ui/                      # Streamlit-Komponenten
├── scripts/                 # CLI (bootstrap, migrate, generate_cons_data, …)
├── tests/
└── runtime/                 # Laufzeitdaten (CSV, JSON, Logs — gitignored)
```

## Lokale Entwicklung

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest
python main.py
python -m scripts.run_streamlit
```

Kanonische Metadaten und Abhängigkeiten: **`pyproject.toml`** (`version.py` = Versionsquelle).

CLI nach `pip install -e .` (optional): `ernie-bootstrap`, `ernie-build-image`, `ernie-verify-loxone`, …

Legacy: `config.json` im Projektroot wird weiterhin unterstützt, wenn `config/config.json` fehlt.

## Container (Synology / LoxBerry / Docker)

### Image bauen (kanonisch)

```powershell
# Windows – Wrapper
.\build-container.ps1

# plattformübergreifend (Standard: Synology amd64)
python -m scripts.build_container
```

Standard-Tags: `ghcr.io/jochentcc/ernie-energy:latest` und `ghcr.io/jochentcc/ernie-energy:<version>` (aus `version.py`).

Registry-Push:

```powershell
# Nur Synology (amd64)
.\build-container.ps1 --target synology --push

# Release Synology + LoxBerry (Multi-Arch-Manifest)
.\build-container.ps1 --target all --push
```

Weitere Optionen: `--target` (`synology` | `loxberry` | `all`), `--tag`, `--platform`, `--no-cache`, `--dockerfile`, `--context`.

### Lokal starten (Dev)

```powershell
docker compose build
docker compose up -d
```

### Produktion (Synology)

1. Multi-Arch-Image bauen und pushen: `python -m scripts.build_container --target all --push`
2. Auf der NAS nur `docker-compose-synology.yml`, `config/`, `runtime/` bereitstellen
3. `docker compose -f docker-compose-synology.yml pull && docker compose -f docker-compose-synology.yml up -d`

### Produktion (LoxBerry, RPi 4B)

1. Multi-Arch-Image bauen und pushen (siehe oben)
2. Auf dem LoxBerry nur `docker-compose-loxberry.yml`, `config/`, `runtime/` bereitstellen
3. `docker compose -f docker-compose-loxberry.yml pull && docker compose -f docker-compose-loxberry.yml up -d`
4. UI im LAN: `http://<loxberry-ip>:8501`

### Go/No-Go LoxBerry

**Go:** LoxBerry 4, Docker-Plugin, RPi 4B 64-bit, mind. 4 GB RAM, SSD empfohlen.

**Risiko:** MILP-Läufe sind auf dem Pi langsamer als auf einem x86-NAS — vor Produktivbetrieb `runtime/energy_optimizer.log` prüfen.

**No-Go:** 32-bit-Image, unter 2 GB RAM, Erwartung identischer MILP-Performance wie auf der Synology.

Persistente Daten liegen in `./config/` (inkl. `config/.env`) und `./runtime/` — sie werden **nicht** vom Image überschrieben. Beim ersten Start legt der Entrypoint fehlende Dateien an.

Details: **[docs/einrichtung/container.md](docs/einrichtung/container.md)**

## Hinweise

- `config/config.json` (oder Legacy `config.json`) ist lokal und gitignored.
- Laufzeitdaten liegen unter `runtime/` (`ENERGY_OPTIMIZER_RUNTIME_DIR`).
- Config-Pfad überschreibbar mit `ENERGY_OPTIMIZER_CONFIG_PATH`.

## Lizenz

Die Software ist **Source-Available** und auf **private, nicht-kommerzielle Nutzung** beschränkt. Vollständige Bedingungen: **[LICENSE.md](LICENSE.md)**.
