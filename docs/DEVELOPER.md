# Earnie — Developer Documentation

Technical reference for developers and contributors. Product overview and user onboarding: **[README.md](README.md)** · **[docs/README.md](docs/README.md)** · Contributing: **[CONTRIBUTING.md](../CONTRIBUTING.md)**

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
# optional: python -m scripts.run_pytest
python -m scripts.run_streamlit
```

`requirements-dev.txt` installs the project from `pyproject.toml` (incl. `python-dotenv`, Streamlit, …) plus pytest. Use `python -m pip` so install always targets the active venv. If you see `No module named 'dotenv'`, the venv is missing deps or you are not using `.\.venv\Scripts\python.exe`.

House-profile timezone is derived from `land` (`AT`/`DE`/`CH` → IANA) in `house_config/geo_timezone.py` — no `timezonefinder`/`h3`. Run tests with `python -m pytest` or `python -m scripts.run_pytest` (thin wrapper used by pre-commit). With `pytest-xdist` (dev extra), `run_pytest` defaults to `-n auto` (multi-CPU); use `-n 0` for sequential debugging.

### Dev Container (optional)

For a Linux-aligned editor/runtime (Docker Desktop required):

1. Command Palette → **Dev Containers: Reopen in Container**
2. Wait for `post-create` (`pip install --only-binary=:all: -e ".[dev]"`, bootstrap `earnie_env/`; remote user `vscode`)
3. F5 with **Streamlit app.py (:8531 lokal (earnie_env))**

Config: `.devcontainer/` (Python 3.14-slim, env aligned with `.vscode/launch.json`). UI: `http://localhost:8531`.

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

Local `build_container` default tags from `version.py`: every version → `:next` and `:<version>`; official also `:latest`; SemVer pre-release omits `:latest`. Legacy `ernie-energy` aliases follow the same rule. **CI** (tag → `release-publish.yml`): candidate is `:<version>` only; `:next` / `:latest` only after job `promote` (see bullet below and root [DEVELOPER.md](../DEVELOPER.md)).

### Release (tag → GitHub Actions)

**Primary path:** bump `version.py` (user approval only), commit + push `main`, then push an annotated tag. CI (`.github/workflows/release-publish.yml`) builds a release candidate (multi-arch image to GHCR, draft GitHub Release) and publishes it after your approval. Per-release checklist: [spec/release-checklist.md](spec/release-checklist.md).

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
- Official (after `promote`): GitHub Latest Release; images `:<version>`, `:next`, and `:latest` (+ legacy aliases).
- Pre-release (after `promote`): GitHub Pre-release (not Latest); images `:<version>` and `:next` (no `:latest`).
- **Candidate → approve → publish:** the tag pushes only `:<version>` images; `:next` / `:latest`, the published release and the HA add-on pin follow after you approve job `promote` (environment `release-approval`). Details: root [DEVELOPER.md](../DEVELOPER.md) · [spec/release-checklist.md](spec/release-checklist.md).
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

## Shadow Mode (Dev client)

Run a development build in parallel to Prod on the same live inputs without touching the smarthome backend. Spec: [`docs/spec/shadow-mode.md`](docs/spec/shadow-mode.md). User-facing German notes: [`docs/einrichtung/betrieb.md`](docs/einrichtung/betrieb.md) (Shadow-Feed + Shadow-Modus).

- Activate **only** with `EARNIE_SHADOW=1` (never a config key). Implies silent mode.
- Requires an explicit `EARNIE_RUNTIME_PATH` or `EARNIE_ENV_PATH`; shares Prod’s config (read-only) and feed under `{config}/shadow_feed/` (or `EARNIE_SHADOW_FEED_PATH`).
- Exception: EHAL-Com mapping may write `{runtime}/shadow_ehal_bindings.json` (merged on house-profile load); Prod config files stay untouched.
- Prod must run with `"shadow_feed_enabled": true` in its `local_settings.json`.
- Optional seed: `python -m scripts.shadow_seed_runtime --from <prod-runtime> --to <shadow-runtime>`.
- Same-host UI port: `EARNIE_UI_STREAMLIT_PORT` (existing override).
- Package trees must never set `EARNIE_SHADOW` (release gate in `release-publish.yml`).

## Roadmap

Open features and epics → **[backlog/Backlog.md](backlog/Backlog.md)**
