# Earnie — Developer Documentation

Technical reference for developers and contributors. Product overview and user onboarding: **[README.md](README.md)** · **[docs/README.md](docs/README.md)** · Contributing: **[CONTRIBUTING.md](CONTRIBUTING.md)**

## Project Structure

```
Earnie/
├── main.py, app.py          # Entry points (stay in the root)
├── config.py                # Configuration loader
├── docker/                  # Dockerfile, Compose, build scripts (see docker/README.md)
├── backlog/                 # Roadmap (Backlog.md, Backlog-Bugfixes.md, Backlog-Erledigt.md)
├── config/
│   ├── config.json          # House configuration (gitignored, persistent)
│   ├── config.example.json  # Template for new installations
│   └── config.schema.json   # JSON schema (editor hover)
├── optimizer/               # MILP, simulation, charging context, facade
├── integrations/            # Loxone, Awattar, log import
├── data/                    # Profiles, consumption, PV forecast
├── simulation/              # Backtesting engine
├── runtime_store/           # JSON persistence, bootstrap, config drift
├── ui/                      # Streamlit components
├── scripts/                 # CLI (bootstrap, migrate, generate_cons_data, …)
├── tests/
└── runtime/                 # Runtime data (CSV, JSON, logs — gitignored)
```

## Local Development

Use a real Windows CPython (e.g. from [python.org](https://www.python.org/downloads/) via the `py` launcher). Do **not** use `python` from Inkscape or the Microsoft Store stub — those can create a Unix-style `.venv` (`bin\`) without `Scripts\Activate.ps1`.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
# optional: python -m pytest
python -m scripts.run_streamlit
```

`requirements-dev.txt` installs the project from `pyproject.toml` (incl. `python-dotenv`, Streamlit, …) plus pytest. Use `python -m pip` so install always targets the active venv. If you see `No module named 'dotenv'`, the venv is missing deps or you are not using `.\.venv\Scripts\python.exe`.

One process is enough for local UI work: Streamlit (`app.py`). Start/stop `main.py` from **Real-Time Environment → Optimizer Service**, or set `$env:EARNIE_AUTO_START_MAIN = "1"` before `run_streamlit` (as in Docker Compose). Only run `python main.py` in a second terminal when you need exclusive daemon debugging (local auto-start is off by default).

If `Activate.ps1` is missing: remove `.venv` and recreate with `py -3 -m venv .venv`. Confirm `.\.venv\Scripts\Activate.ps1` exists before activating.

Canonical metadata and dependencies: `pyproject.toml` (`version.py` = version source).

CLI after `pip install -e .` (optional): `earnie-bootstrap`, `earnie-build-image`, `earnie-verify-loxone`, … (legacy aliases: `ernie-*`).

Legacy: `config.json` in the project root is still supported when `config/config.json` is missing.

## Container (Synology / LoxBerry / Proxmox / Docker)

Detailed guide for operators: [docs/einrichtung/container.md](docs/einrichtung/container.md) · Proxmox LXC: [docs/einrichtung/proxmox-lxc.md](docs/einrichtung/proxmox-lxc.md) · Compose stacks and build context: [docker/README.md](docker/README.md)

### Build the Image

```powershell
python -m scripts.build_container
```

Windows wrapper: `.\docker\build-container.ps1`

Default tags from `version.py`: official → `:latest` and `:<version>`; SemVer pre-release (`-alpha.N` / `-rc.N`) → `:<version>` only. Legacy `ernie-energy` aliases follow the same rule.

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
- Publish from `main`; leave the pre-release string on `main` until the next approved bump.
- Parallel feature work + urgent fix for an already tagged build: [docs/spec/branching-hotfix-playbook.md](docs/spec/branching-hotfix-playbook.md) (`main` + tags; short-lived `hotfix/…` only when needed).
- **GHCR auth for Actions:** store a classic PAT with `write:packages` (and `read:packages`) as repo secret `GHCR_TOKEN`. Without it, `GITHUB_TOKEN` only works if each package (`earnie-energy`, `ernie-energy`) grants this repository **Write** under Package settings → Manage Actions access. Also set packages **Public** if anonymous `docker pull` is required.

**Fallback** (CI down / emergency): local multi-arch push:

```powershell
python -m scripts.build_container --target all --push
```

Additional build options: `--target` (`synology` | `loxberry` | `all`), `--tag`, `--platform`, `--no-cache` — see [docker/README.md](docker/README.md).

### Start Locally (Dev)

```powershell
docker compose --project-directory . -f docker/compose/dev.yml up -d --build
```

### Production (Synology / LoxBerry / Proxmox LXC)

1. Publish a tagged release (see above) — or fallback local `--push`
2. On the target platform, deploy only the compose file (`docker/compose/synology_productive.yml`, `loxberry_productive.yml`, or `proxmox_productive.yml`), `config/`, and `runtime/`
3. `docker compose --project-directory . -f docker/compose/<stack>.yml pull`
4. `docker compose --project-directory . -f docker/compose/<stack>.yml up -d`
5. UI on the LAN: `http://<host-ip>:8501`

Proxmox: LXC with `nesting=1`/`keyctl=1`, optional `docker/proxmox/bootstrap.sh` — see [proxmox-lxc.md](docs/einrichtung/proxmox-lxc.md).

## Notes

- `config/config.json` (or legacy `config.json`) is local and gitignored.
- Runtime data lives under `runtime/` (`EARNIE_RUNTIME_PATH`).
- Persistence root: `EARNIE_ENV_PATH` (default `earnie_env`). Config directory: `EARNIE_CONFIG_PATH` (default `{ENV_PATH}/config`). Runtime: `EARNIE_RUNTIME_PATH` or `{ENV_PATH}/runtime`.

## Roadmap

Open features and epics → **[backlog/Backlog.md](backlog/Backlog.md)**
