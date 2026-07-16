# Earnie — Entwickler-Dokumentation

Technische Referenz für Entwickler und Mitwirkende. Produktüberblick und Anwender-Einstieg: **[README.md](README.md)** · **[docs/README.md](docs/README.md)**

## Projektstruktur

```
Earnie/
├── main.py, app.py          # Einstiegspunkte (bleiben in der Wurzel)
├── config.py                # Konfigurations-Loader
├── docker/                  # Dockerfile, Compose, Build-Skripte (siehe docker/README.md)
├── backlog/                 # Roadmap (Backlog.md, Backlog-Bugfixes.md, Backlog-Erledigt.md)
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

Kanonische Metadaten und Abhängigkeiten: `pyproject.toml` (`version.py` = Versionsquelle).

CLI nach `pip install -e .` (optional): `earnie-bootstrap`, `earnie-build-image`, `earnie-verify-loxone`, … (Legacy-Aliase: `ernie-*`).

Legacy: `config.json` im Projektroot wird weiterhin unterstützt, wenn `config/config.json` fehlt.

## Container (Synology / LoxBerry / Proxmox / Docker)

Ausführliche Anleitung für Betreiber: [docs/einrichtung/container.md](docs/einrichtung/container.md) · Proxmox LXC: [docs/einrichtung/proxmox-lxc.md](docs/einrichtung/proxmox-lxc.md) · Compose-Stacks und Build-Kontext: [docker/README.md](docker/README.md)

### Image bauen

```powershell
python -m scripts.build_container
```

Windows-Wrapper: `.\docker\build-container.ps1`

Standard-Tags: `ghcr.io/jochentcc/earnie-energy:latest` und `ghcr.io/jochentcc/earnie-energy:<version>` (aus `version.py`). Übergangsweise zusätzlich `ernie-energy`-Tags.

### Release (tag → GitHub Actions)

**Primary path:** bump `version.py` (user approval only), commit + push `main`, then push an annotated tag. CI (`.github/workflows/release.yml`) builds the multi-arch image to GHCR and creates the GitHub Release.

```powershell
# After version.py == X.Y.Z is on origin/main:
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

- Tag must match `version.py` exactly (`v2.0.0` ↔ `__version__ = "2.0.0"`); mismatch fails the workflow.
- Optional notes: `.github/release-notes/vX.Y.Z.md` (else a short default body).
- Images: `ghcr.io/jochentcc/earnie-energy:X.Y.Z` and `:latest` (+ legacy `ernie-energy` aliases).
- **GHCR visibility (one-time):** after the first Actions push, in GitHub → Packages → `earnie-energy` / `ernie-energy` → link to this repo and set **Public** if anonymous `docker pull` is required.

**Fallback** (CI down / emergency): local multi-arch push:

```powershell
python -m scripts.build_container --target all --push
```

Weitere Build-Optionen: `--target` (`synology` | `loxberry` | `all`), `--tag`, `--platform`, `--no-cache` — siehe [docker/README.md](docker/README.md).

### Lokal starten (Dev)

```powershell
docker compose --project-directory . -f docker/compose/dev.yml up -d --build
```

### Produktion (Synology / LoxBerry / Proxmox LXC)

1. Publish a tagged release (see above) — or fallback local `--push`
2. Auf der Zielplattform nur Compose-Datei (`docker/compose/synology.yml`, `loxberry.yml` oder `proxmox.yml`), `config/` und `runtime/` bereitstellen
3. `docker compose --project-directory . -f docker/compose/<stack>.yml pull`
4. `docker compose --project-directory . -f docker/compose/<stack>.yml up -d`
5. UI im LAN: `http://<host-ip>:8501`

Proxmox: LXC mit `nesting=1`/`keyctl=1`, optional `docker/proxmox/bootstrap.sh` — siehe [proxmox-lxc.md](docs/einrichtung/proxmox-lxc.md).

## Hinweise

- `config/config.json` (oder Legacy `config.json`) ist lokal und gitignored.
- Laufzeitdaten liegen unter `runtime/` (`EARNIE_RUNTIME_DIR`, Legacy: `ENERGY_OPTIMIZER_RUNTIME_DIR`).
- Config-Pfad überschreibbar mit `EARNIE_CONFIG_PATH` (Legacy: `ENERGY_OPTIMIZER_CONFIG_PATH`).

## Roadmap

Offene Features und Epics → **[backlog/Backlog.md](backlog/Backlog.md)**
