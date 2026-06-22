# Energy Optimizer

Python-basierte Energieoptimierung für Smarthome (Batterie, PV, flexible Verbraucher) mit Streamlit-UI und Produktiv-Daemon (`main.py`).

## Projektstruktur

```
Energy-Optimizer/
├── main.py, app.py          # Einstiegspunkte (bleiben in der Wurzel)
├── config.py, config.json   # Konfiguration
├── optimizer/               # MILP, Simulation, Ladekontext, Facade
├── integrations/            # Loxone, Awattar, Log-Import
├── data/                    # Profile, Verbrauch, PV-Prognose
├── simulation/              # Backtesting-Engine
├── runtime_store/           # JSON-Persistenz (run_state, History, Debug)
├── ui/                      # Streamlit-Komponenten
├── scripts/                 # CLI (generate_cons_data, run_backtesting)
├── tests/
└── runtime/                 # Laufzeit-JSON/Logs (Daten, nicht Code)
```

## Lokale Entwicklung

```powershell
python -m pytest
python main.py
streamlit run app.py
python -m scripts.run_backtesting --help
```

Legacy-Wrapper in der Wurzel: `GenerateConsData.py`, `run_backtesting.py` → delegieren an `scripts/`.

## Container-Build

> **Hinweis:** `README.md` verwies früher auf `containers.build`; dieses Modul ist im Repository derzeit **nicht** vorhanden. Container-Build erfolgt über das vorhandene Skript bzw. Docker direkt.

```powershell
.\build-container.ps1
```

Falls `containers.build` wieder eingeführt wird:

```powershell
python -m containers.build --tag deinusername/ernie-energy:latest
```

### Optionen (containers.build)

- `--tag`: Docker-Image-Tag
- `--platforms`: Komma-separierte Plattformen (z. B. `linux/amd64,linux/arm64`)
- `--dockerfile`, `--context`, `--no-push`, `--builder-name`

## Hinweise

- `config.json` ist lokal und ggf. gitignored.
- Laufzeitdaten liegen unter `runtime/` (oder `ENERGY_OPTIMIZER_RUNTIME_DIR`).
