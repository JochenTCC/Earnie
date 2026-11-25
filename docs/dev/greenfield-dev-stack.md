# Greenfield dev stack

The Greenfield stack is a local container stack in the state **right after first setup**. It is the acceptance environment for the Hauskonfigurator and backtesting on the dev PC. It needs no write access to a productive Loxone. It is separate from the pytest fixtures and from the regular dev stack.

## Prerequisites

- Docker Desktop (Windows) or Docker Engine
- Repo checkout with `docker/compose/greenfield.yml`

## Start the stack (empty state)

```powershell
mkdir greenfield\config, greenfield\runtime
docker compose --project-directory . -f docker/compose/greenfield.yml up -d --build
```

Persistent data lives only under `greenfield/config/` and `greenfield/runtime/`. The regular dev stack (`docker/compose/dev.yml` with `./earnie_env/config` and `./earnie_env/runtime`) is not touched.

| Service | Container | Host port |
|---------|-----------|-----------|
| earnie | `earnie-greenfield` | **8502** → 8501 |

Browser: `http://localhost:8502`

## First setup flow

1. **Bootstrap:** the entrypoint creates missing files (`python -m scripts.bootstrap_runtime`, see [Container](../einrichtung/container.md)). `config.json` and the planning files start **minimal**: empty catalogs, no Earnie example data.
2. **Planning:** while planning is incomplete, the navigation shows two sections:
   - **Konfiguration:** Hauskonfigurator; once the house config is ready (profile + battery) also Szenarienkonfigurator and Tarife.
   - **Daemon Control:** Smarthome-Backend (landing page when `live_environment` is enabled); EHAL-Com and Optimierer-Dienst appear only once a backend is configured.

   In the Hauskonfigurator create **Hausprofil**, **Heizsysteme**, **Wechselrichter**, **PV-Felder** and **Batterien**; in the Szenarienkonfigurator the live scenario and variants (entity references). The sidebar lists the missing steps.
3. **Smarthome-Backend (live path only):** see [Smarthome-Backend](../ui/smarthome-backend.md). Without a real Miniserver, backend **Loxone** with dummy credentials is enough, e.g. IP `192.168.178.99`, any user and password, then **Speichern**.
4. **Szenario-Explorer:** appears once planning is complete. What-if runs need no Smarthome-Backend.
5. **Daemon:** `main.py` starts together with the UI (`EARNIE_AUTO_START_MAIN=1`). The Loxone check at start is off (`EARNIE_VERIFY_LOXONE_ON_START=0`).

## Checklist: expected files after the first start

After `up` and before the manual setup, among others:

| Path | Expected |
|------|----------|
| `greenfield/config/config.json` | from `config.minimal.json`: `live_scenario_id: live`, `ehal.backend: loxone` |
| `greenfield/config/components.json` | from `components.minimal.json`: empty `batteries` / `pv_systems` |
| `greenfield/config/config.example.json` | full reference example, for lookup only |
| `greenfield/config/.env` | from `.env.example` (placeholders → setup page) |
| `greenfield/runtime/local_settings.json` | e.g. `{"silent_mode": false}` |
| `greenfield/runtime/cons_data.csv` | CSV header only, no data rows |
| `greenfield/config/house_profiles.json` | `profiles: []` |
| `greenfield/config/tariffs.json` | catalog from `share/config/tariffs.json` (fallback: `tariffs.example.json`) |
| `greenfield/config/grid_fees.json` | grid fee catalog from `share/config/grid_fees.json` |
| `greenfield/config/backtesting_scenarios.json` | at least the live scenario `live` (from `backtesting_scenarios.minimal.json`) |

Other bootstrap files (tariffs, `deviation_rules.json`, empty profile CSVs, log) are listed in `runtime_store/bootstrap.py`.

After **Speichern** on the Smarthome-Backend page:

| Check | Expected |
|-------|----------|
| `greenfield/config/.env` | real IPv4 address, user and password (no placeholders) |
| Worker log | `greenfield/runtime/earnie.log` without an abort for a missing `.env` |
| UI | Konfiguration: Hauskonfigurator (Szenarienkonfigurator and Tarife once the house config is ready); Daemon Control: Smarthome-Backend, EHAL-Com, Optimierer-Dienst; sidebar hint for missing steps |

```powershell
docker compose --project-directory . -f docker/compose/greenfield.yml logs -f earnie
```

## Manual acceptance

Prerequisite: first setup done and planning complete.

1. **Hauskonfigurator:** go through the tabs Hausprofil (thermal consumer „Haus Wärme“, automatic IDs), Wechselrichter, PV and Batterien; check the base-load preview.
2. **Szenarienkonfigurator:** save the live scenario and entity references, optionally add variants.
3. **Szenario-Explorer:** start a run.

`docker/compose/greenfield.yml` sets `EARNIE_UI_MODES=sunset2sunset,scenario_explorer,live_environment`, so Sunset-2-Sunset is available for the live-path smoke test, together with the Szenario-Explorer and Daemon Control.

## Live-path acceptance

**Goal:** Greenfield uses **`live_scenario_id`** and the live scenario in `backtesting_scenarios.json` with entity references. `config.json` holds no flat copies of PV, battery or tariff values. Live optimization and the Szenario-Explorer use the same resolution (`config._load_dynamic_params()`).

| Step | Check | Expected |
|------|-------|----------|
| 1. Config | `greenfield/config/config.json` | `live_scenario_id: live` |
| 2. Live scenario | `greenfield/config/backtesting_scenarios.json` → scenario `live` | entity IDs `battery_ids`, `import_tariff_id`, `export_tariff_id`, `house_profile_id`, optional `pv_system_ids`; geo data and time zone come from `house_profiles.json` |
| 3. Entity resolution | Konfiguration → Szenarienkonfigurator (live scenario) | the entity IDs point to PV, battery and tariff parameters in `components.json` and `tariffs.json` |
| 4. Live cycle | `docker compose --project-directory . -f docker/compose/greenfield.yml logs -f earnie` | `main.py` runs at least one optimization cycle without config errors |
| 5. UI Sunset-2-Sunset | page **Monitor** (live cockpit) | resolved values from the live scenario, no sidebar inputs for PV, battery or tariffs |
| 6. Szenario-Explorer parity | same tariff IDs, same time window | import and export prices (cent/kWh) equal to live |

Without Docker (venv, port **8532**), point Earnie at the Greenfield data:

```powershell
$env:EARNIE_ENV_PATH='greenfield'; $env:EARNIE_UI_STREAMLIT_PORT='8532'
.venv\Scripts\python.exe -m scripts.run_streamlit
```

`main.py` started with the same `EARNIE_ENV_PATH` uses `greenfield/config` and `greenfield/runtime` too. In the multi-root workspace, the launch configs "Streamlit app.py (Greenfield :8532)" (also "… auto main") and "main.py (Greenfield)" (`earnie-workspace/.vscode/launch.json`) do the same.

## Reset the stack

Start over (deletes all Greenfield data):

```powershell
docker compose --project-directory . -f docker/compose/greenfield.yml down
Remove-Item -Recurse -Force greenfield\config, greenfield\runtime
mkdir greenfield\config, greenfield\runtime
docker compose --project-directory . -f docker/compose/greenfield.yml up -d --build
```

## Automated smoke test

### Without Docker (pytest)

```powershell
.venv\Scripts\python.exe -m scripts.run_pytest tests/test_greenfield_bootstrap.py tests/test_setup_readiness.py tests/test_navigation_setup.py tests/test_planning_editors.py tests/test_config_drift.py -q
```

The tests check the bootstrap on an empty directory and the step from setup to a configured `.env`.

### Docker stack

Prepare the directories:

```powershell
.venv\Scripts\python.exe -m scripts.smoke_greenfield_docker --prepare-only
```

Full smoke test (build, start, bootstrap files, worker log, UI on port 8502):

```powershell
.venv\Scripts\python.exe -m scripts.smoke_greenfield_docker
```

`version.py` must hold a valid SemVer or pre-release version (e.g. `2.8.0-dev.41`); the image build normalizes it (`rewrite_version_file_for_image`).

Start over (empty volumes): `--reset`. Faster run without an image rebuild: `--no-build`.

**Expected on success:**

- Container `earnie-greenfield` is running.
- The bootstrap files are under `greenfield/`.
- The log contains „Earnie Live-Abfrage gestartet“; Loxone access fails with the dummy `.env`, as expected.
- Streamlit answers on `http://localhost:8502/`.

Helper tests without Docker: `tests/test_smoke_greenfield_docker.py`.

## Scope

Port overview of all stacks: [streamlit-ports.md](streamlit-ports.md).

| Stack | Purpose |
|-------|---------|
| **Greenfield** (this file) | first setup, empty volumes, host port **8502** (Docker) / **8532** (venv) |
| `docker/compose/dev.yml` | local development with `./earnie_env/…`, host port **8521** |
