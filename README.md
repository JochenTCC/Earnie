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
│   └── config.json          # Haus-Konfiguration (gitignored, persistent)
├── config.example.json      # Vorlage für neue Installationen
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
streamlit run app.py
```

Kanonische Metadaten und Abhängigkeiten: **`pyproject.toml`** (`version.py` = Versionsquelle).

CLI nach `pip install -e .` (optional): `ernie-bootstrap`, `ernie-build-image`, `ernie-verify-loxone`, …

Legacy: `config.json` im Projektroot wird weiterhin unterstützt, wenn `config/config.json` fehlt.

## Container (Synology / Docker)

### Image bauen (kanonisch)

```powershell
# Windows – Wrapper
.\build-container.ps1

# plattformübergreifend
python -m scripts.build_container
```

Standard-Tags: `ghcr.io/jochentcc/ernie-energy:latest` und `ghcr.io/jochentcc/ernie-energy:<version>` (aus `version.py`).

Registry-Push nach erfolgreichem Build:

```powershell
.\build-container.ps1 --push
```

Weitere Optionen: `--tag`, `--platform`, `--no-cache`, `--dockerfile`, `--context`.

### Lokal starten (Dev)

```powershell
docker compose build
docker compose up -d
```

### Produktion (Synology)

1. Image bauen und pushen (siehe oben)
2. Auf der NAS nur `docker-compose-synology.yml`, `.env`, `config/`, `runtime/` bereitstellen
3. `docker compose -f docker-compose-synology.yml pull && docker compose -f docker-compose-synology.yml up -d`

Persistente Daten liegen in `./config/`, `./runtime/` und `./.env` — sie werden **nicht** vom Image überschrieben. Beim ersten Start legt der Entrypoint fehlende Dateien an.

Details: **[docs/einrichtung/container.md](docs/einrichtung/container.md)**

Migration vom alten flachen Layout:

```powershell
python -m scripts.migrate_persist_layout --apply
```

## Hinweise

- `config/config.json` (oder Legacy `config.json`) ist lokal und gitignored.
- Laufzeitdaten liegen unter `runtime/` (`ENERGY_OPTIMIZER_RUNTIME_DIR`).
- Config-Pfad überschreibbar mit `ENERGY_OPTIMIZER_CONFIG_PATH`.
