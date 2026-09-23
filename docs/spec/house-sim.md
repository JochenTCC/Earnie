# House simulator (`house_sim/`) — HA Lab P1 developer bench

**Status:** current (Energy-Optimizer **2.6.a** / HA Lab P1)  
**Purpose:** Fixture-based **mock** Home Assistant REST + short closed-loop physics so Earnie can exercise HA bindings locally.

## What this is (and is not)

`house_sim` is a **mock for Home Assistant**, not a real running HA installation (not HAOS, not the Synology lab, not Compose `homeassistant`). It only implements the few REST endpoints `HaAdapter` needs, so you can **test bindings** (`ehal.ha.entities` reads/writes, units, write-error degrade) without standing up HA.

**Not the same as:** [`ha-lab-setup.md`](ha-lab-setup.md) / `ha_lab/` (Compose Earnie+HAOS+evcc). Do not put this simulator under `ha_lab/`.

**Concept (German):** [Earnie-HA-Kompatibilitaetstests-Entwicklungsdokument](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Earnie-HA-Kompatibilitaetstests-Entwicklungsdokument.md)

---

## What it provides

| Piece | Role |
| --- | --- |
| `house_sim/fixtures/evcc_en/` | One hand-authored archetype + golden `ehal.ha.entities` (Mode A) |
| `house_sim/mock_rest.py` | `GET /api/states`, `GET /api/states/{id}`, `POST /api/services/{domain}/{service}` + Bearer |
| `house_sim/stepper.py` | Few ticks: SoC coulomb counter, synthetic PV kW series, optional `simulate_next_temp_c` |
| Pytest | Real `HaAdapter` HTTP against the mock |

Out of scope for P1: `simulation/engine.py::run_simulation()`, `data/pv_forecast.py`, fake clock in `main.py`, EV/heat-pump physics. Suggest-and-confirm (**2.6.b**) reuses this fixture: empty `ehal.ha.entities` + `entities.json` → heuristic fills the golden map’s obvious fields and leaves ambiguous ones (e.g. buffer temp) empty.

---

## Run the mock, then start Earnie

1. Start the mock (leave this process running).
2. Start Earnie with `ehal.backend=ha` and point `ehal.ha` at the values below (merge the golden map into `config.json`).

### Connection data (`evcc_en`, default port)

| Setting | Value |
| --- | --- |
| Base URL | `http://127.0.0.1:8124` |
| Token | `house-sim-bench-token` |
| Golden map | `house_sim/fixtures/evcc_en/ehal.ha.entities.json` |

Token constant in code: `house_sim.mock_rest.DEFAULT_BENCH_TOKEN`.

### Start the mock

From the Energy-Optimizer repo root (venv active):

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m house_sim --fixture evcc_en --port 8124
```

The process prints `base_url`, token, and the golden entity map. Keep it running while Earnie talks to it.

Closed-loop ticks without a long-lived server (physics smoke only — not for Earnie):

```powershell
.venv\Scripts\python.exe -m house_sim --fixture evcc_en --ticks 3 --dt-h 0.25
```

---

## Pytest

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m scripts.run_pytest `
  tests/test_house_sim_mock_rest.py `
  tests/test_house_sim_stepper.py `
  tests/test_house_sim_ha_adapter_loop.py `
  tests/test_ha_adapter.py -q --tb=short
```

Covers: Bearer auth, HA state shape, read/write units (kW→W), `unavailable`/`unknown`, `switch.*` negative write domain, write-error capability degrade, few-tick charge → SoC move.

---

## Fixture layout

```text
house_sim/fixtures/<name>/
  entities.json           # vendor signature (HA state objects)
  ehal.ha.entities.json   # golden map + optional sign
  house_params.json       # battery_kwh, load, optional thermal RC
  pv_series.json          # short synthetic kW series
```

`evcc_en` includes `switch.evcc_loadpoint_1_enable` (not mapped — negative case) and no heat-pump entity.
