# Earnie — Entwickler-Dokumentation

Technische Referenz für Entwickler und Mitwirkende. Produktüberblick und Anwender-Einstieg: **[README.md](README.md)** · **[docs/README.md](docs/README.md)** · Mitwirken: **[CONTRIBUTING.md](CONTRIBUTING.md)**

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

Use a real Windows CPython (e.g. from [python.org](https://www.python.org/downloads/) via the `py` launcher). Do **not** use `python` from Inkscape or the Microsoft Store stub — those can create a Unix-style `.venv` (`bin\`) without `Scripts\Activate.ps1`.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
# optional: python -m pytest
python -m scripts.run_streamlit
```

`requirements-dev.txt` installs the project from `pyproject.toml` (incl. `python-dotenv`, Streamlit, …) plus pytest. Use `python -m pip` so install always targets the active venv. If you see `No module named 'dotenv'`, the venv is missing deps or you are not using `.\.venv\Scripts\python.exe`.

One process is enough for local UI work: Streamlit (`app.py`). Start/stop `main.py` from **Echtzeit-Umgebung → Optimierer-Dienst**, or set `$env:EARNIE_AUTO_START_MAIN = "1"` before `run_streamlit` (as in Docker Compose). Only run `python main.py` in a second terminal when you need exclusive daemon debugging (local auto-start is off by default).

If `Activate.ps1` is missing: remove `.venv` and recreate with `py -3 -m venv .venv`. Confirm `.\.venv\Scripts\Activate.ps1` exists before activating.

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

Standard-Tags from `version.py`: official → `:latest` and `:<version>`; SemVer pre-release (`-alpha.N` / `-rc.N`) → `:<version>` only. Legacy `ernie-energy` aliases follow the same rule.

### Release (tag → GitHub Actions)

**Primary path:** bump `version.py` (user approval only), commit + push `main`, then push an annotated tag. CI (`.github/workflows/release.yml`) builds the multi-arch image to GHCR and creates the GitHub Release.

```powershell
# Official — after version.py == X.Y.Z is on origin/main:
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z

# Community pre-release — after version.py == X.Y.Z-alpha.N on origin/main:
git tag -a vX.Y.Z-alpha.N -m "Pre-release vX.Y.Z-alpha.N"
git push origin vX.Y.Z-alpha.N
```

- Tag must match `version.py` exactly (`v2.0.0` ↔ `__version__ = "2.0.0"`; `v2.2.0-alpha.1` ↔ `2.2.0-alpha.1`); mismatch fails the workflow.
- Optional notes: `.github/release-notes/vX.Y.Z.md` or `vX.Y.Z-alpha.N.md` (else a short default body).
- Official: GitHub Latest Release; images `:<version>` and `:latest` (+ legacy aliases).
- Pre-release (`-` in version): GitHub Pre-release (not Latest); images `:<version>` only (no `:latest`).
- **HA Add-on:** same tag triggers job `publish_ha_addon` — bumps `packaging/homeassistant-addon/earnie/`, lints, commits Earnie `main`, mirrors [`ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie). Requires repo secret `HA_ADDON_REPO_TOKEN` (PAT `contents:write` on both repos). Manual retry: workflow **HA Add-on publish**. Details: `packaging/homeassistant-addon/README.md`.
- Publish from `main`; leave the pre-release string on `main` until the next approved bump.
- Parallel feature work + urgent fix for an already tagged build: [docs/spec/branching-hotfix-playbook.md](docs/spec/branching-hotfix-playbook.md) (`main` + tags; short-lived `hotfix/…` only when needed).
- **GHCR auth for Actions:** store a classic PAT with `write:packages` (and `read:packages`) as repo secret `GHCR_TOKEN`. Without it, `GITHUB_TOKEN` only works if each package (`earnie-energy`, `ernie-energy`) grants this repository **Write** under Package settings → Manage Actions access. Also set packages **Public** if anonymous `docker pull` is required.

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
2. Auf der Zielplattform nur Compose-Datei (`docker/compose/synology_productive.yml`, `loxberry_productive.yml` oder `proxmox_productive.yml`), `config/` und `runtime/` bereitstellen
3. `docker compose --project-directory . -f docker/compose/<stack>.yml pull`
4. `docker compose --project-directory . -f docker/compose/<stack>.yml up -d`
5. UI im LAN: `http://<host-ip>:8501`

Proxmox: LXC mit `nesting=1`/`keyctl=1`, optional `docker/proxmox/bootstrap.sh` — siehe [proxmox-lxc.md](docs/einrichtung/proxmox-lxc.md).

## Hinweise

- `config/config.json` (oder Legacy `config.json`) ist lokal und gitignored.
- Laufzeitdaten liegen unter `runtime/` (`EARNIE_RUNTIME_PATH`).
- Persistenz-Wurzel: `EARNIE_ENV_PATH` (Default `earnie_env`). Config-Verzeichnis: `EARNIE_CONFIG_PATH` (Default `{ENV_PATH}/config`). Laufzeit: `EARNIE_RUNTIME_PATH` bzw. `{ENV_PATH}/runtime`.

## Roadmap

Offene Features und Epics → **[backlog/Backlog.md](backlog/Backlog.md)**
