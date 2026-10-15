# Thermal horizon simulation — year model once for parameters, horizon only in Live

**Status:** Approved 2026-10-15 — P1–P4 implemented on branch, P5 open  
**Date:** 2026-10-15  
**Branch:** `feat/thermal-horizon-sim` (based on `perf/thermal-year-cache`, PR #36)  
**Related:** [`thermals-p2.md`](thermals-p2.md) (§ Live / MILP store floor), [`early-start-scheduling.md`](early-start-scheduling.md), backlog epic **ThermalHorizon** P1–P5 (Version 2.7)

## 1. Problem

Every Live cycle still runs full 8760 h thermal year simulations (`house_year_result`, `thermal_rc_hourly_kw_and_temp_from_ambient`) although the optimizer only plans ~180 quarter-hour slots (~45 h). NAS profiling on 2026-10-15 (dev.54) counted ~810 house and ~440 `thermal_rc` year simulations per cycle; dev.55 and the memo (PR #36) remove the repeats, but the Live path still *depends* on year simulations in several places, and partly on the wrong climate:

- the year profile uses the **archive year** (last full year) at the same calendar day/hour, not the weather forecast for the horizon;
- the RC state at a given date comes from simulating 1 Jan → today, not from the measured state.

Goal: run a year simulation **only to derive parameters** (once per configuration × reference climate year). Live planning simulates **only the horizon**, starting from the measured (or carried) state and driven by the outdoor forecast.

## 2. Inventory — where the year model enters a Live cycle today

| # | Consumer | Year model used for | Live effect today | Target |
|---|----------|---------------------|-------------------|--------|
| A | `house_config/profiles_store._normalize_profile` → `compute_baseload_kwh` → `consumer_annual_kwh` | annual kWh of `thermal_annual` (house year sim) and `thermal_rc` (pool year sim) to split baseload = annual − Σ consumers | runs on **every** house-profile load (441× per cycle in the dev.54 profile) | **parameter** (§4.1) |
| B | `optimizer/thermal_live_store._year_ambient_for_house_h` | envelope `H` calibration from a year of outdoor temperature (no simulation, but needs a year series) | uses `datetime.now().year` → **current, partial** year; year sim uses `last_full_archive_year()` → two different `H` for the same house | **parameter** (§4.1), one reference year |
| C | `optimizer/thermal_flex_context._slot_aligned_thermal_energy_kwh` → `modeled_consumer_kw_for_slots` | slot kWh from the year PWM profile → `daily_targets`, `slot_energy_kwh` | with heat storage (Live overlay) the MILP **ignores** it (`want = live_min`, thermals-p2 §5) — computed, then discarded; without storage it **is** the day target | horizon (§4.2, §4.3) |
| D | `optimizer/targets.resolve_thermal_annual_horizon_kwh` | horizon target = Σ `thermal_daily_kwh_for_date` (year sim) | with storage: already Live plan; without storage: year sim | horizon (§4.3) |
| E | `thermal_live_store.resolve_live_collector_solar_kw` | collector irradiance from the archive year at the same DOY/hour (lookup, no sim) | **last year's** sunshine drives the Live store plan (forced WP hours) — material for any installation with `solar_thermal_area_m2 > 0` (owner installation: 10.3 m²) | horizon input (§4.4) |
| F | `thermal_targets` (`daily_target_source = thermal`, pool `thermal_control`) | — | already horizon (`plan_minimum_heating` from measured water temp + forecast) | unchanged |

Out of scope: backtesting / Szenario-Explorer (`consumption_mode = profile_spec`, `ModeledClimateContext`) and the HK temperature charts (`data/modeled_temperatures.py`). There the continuous year simulation **is** the simulated ground truth (state carried across days, historical weather); the memo of PR #36 covers their cost.

## 3. Principle

1. **Parameters** (slow, rare): one year simulation per `(thermal config, reference climate year)` yields a small, explicit parameter set. Reference year = `last_full_archive_year()` everywhere.
2. **Horizon** (fast, every cycle): RC simulation over the planning horizon only (≤ ~48 h), start state = measurement where available. **All weather inputs come from the forecast:** ambient = `get_outdoor_forecast_with_fallback` (Open-Meteo forecast, existing fallback to the live outdoor reading with its source logged), collector irradiance = Open-Meteo forecast (§4.4).
3. Live never calls `house_year_result` / `_modeled_thermal_annual_hourly_kw` / `thermal_daily_kwh_for_date`. A test enforces this (§6).

## 4. Design

### 4.1 Thermal parameters (year model once)

New module `optimizer/thermal_parameters.py`:

```python
@dataclass(frozen=True)
class ThermalParameters:
    reference_year: int
    annual_electric_kwh: float            # baseload split (A)
    house_heat_loss_kw_per_k: float | None  # calibrated H (B); None without Wohnfläche
    source: str                           # "year_sim" | "override" | "legacy_hdd"

def thermal_parameters_for_consumer(consumer: dict, profile: dict) -> ThermalParameters: ...
def thermal_rc_parameters_for_consumer(consumer: dict) -> ThermalParameters: ...
```

- Derived from **one** year simulation on the reference-year Open-Meteo bundle (house: `house_year_result`; pool: RC year model). `H` comes from the same calibration the year sim uses (`resolve_house_heat_loss_kw_per_k` on the reference-year ambient); an explicit `house_heat_loss_kw_per_k` override wins (`source = "override"`).
- Memoized in process (content key like PR #36: consumer thermal params + profile geo/tz + reference year). No file persistence: a cold start costs 1–2 year sims (< 1 s on the NAS); a persisted file would need its own invalidation.
- Callers switched: `consumer_annual_kwh` (A), `_resolve_live_house_heat_loss_kw_per_k` (B, replaces `_year_ambient_for_house_h` and its "scale short forecast" fallback — missing climate becomes a loud error, not an order-of-magnitude guess).
- **Result change:** B moves from the partial current year to the last full year → `H` and therefore Live floor hours change slightly.

### 4.2 Live with heat storage — stop computing the discarded year profile

`resolve_thermal_flex_contexts` (Live snapshot, storage enabled): build the context from the Live store plan only. `slot_energy_kwh` / `daily_targets` come from `LiveStorePlan.electric_by_hour` mapped to slots (same mapping as `map_forced_hours_to_slot_indices`), so debug/savings views show the energy the MILP actually plans against.

- MILP constraints unchanged (they already use `forced_indices` + `live_day_min_kwh`).
- The store plan is currently built twice per cycle (`_live_store_flex_overlay` and `_live_heat_storage_horizon_need_kwh`); compute it once per cycle and pass it to both.
- **Result change:** none in the plan; `daily_targets` shown in debug/savings switch from HDD to Live plan values.

### 4.3 Live without heat storage — house-only horizon simulation

New `plan_live_house_horizon(...)` in `thermal_live_store.py` (reuses `step_house_hour`, `house_requests_heat`, `_step_hour_direct_wp` semantics of the year sim):

- Start house temperature: target temperature (steady state; §7 Q2). No indoor sensor exists in EHAL today; carrying the simulated state between cycles stays a possible later refinement.
- Ambient: outdoor forecast over the horizon (hourly, mapped to slots as today).
- Output: hourly electric kWh → `slot_energy_kwh` + `daily_targets` (`targets_slot_aligned = True`) — same context keys, so `add_thermal_flex_constraints` is unchanged.
- `resolve_thermal_annual_horizon_kwh` Live branch: Σ slot energy of the horizon plan instead of calendar-day sums.
- Legacy path `living_area_m2 <= 0` (open-loop HDD): the year model has no space heat there (annual heat = area × HWB = 0), only warm water minus the collector credit. Horizon = warm water over the forecast hours minus the forecast collector heat (§4.4), netted per calendar day like the year model — no year series.
- **Result change:** day targets follow the forecast instead of last year's weather; the hourly shape is bang-bang from the RC model instead of the PWM spread of a daily total.

### 4.4 Collector irradiance from the forecast

`resolve_live_collector_solar_kw` reads last year's irradiance at today's DOY/hour. The collector heat is an input of the same horizon simulation as the outdoor temperature (store energy balance in `step_coupled_hour`), so it belongs to this epic — with storage it moves the forced WP hours directly.

- `data/outdoor_forecast.get_hourly_tilted_irradiance_forecast_wm2`: one Open-Meteo forecast request `hourly=temperature_2m,global_tilted_irradiance` with `tilt` / `azimuth` of the collector surface, cached per surface (30 min TTL); the temperature part seeds the outdoor-temperature cache for the same location. Open-Meteo takes one tilt/azimuth per request; installations have one collector surface today.
- Azimuth convention: `collector_surface_from_thermal` already uses Open-Meteo's convention (0° = south) — the archive path passes it unchanged; the forecast rounds tilt/azimuth to whole degrees like the archive.
- Convert W/m² → kW_th with the same function as the year sim (`open_meteo_solar_archive.irradiance_wm2_to_thermal_kwh`), so forecast and parameters stay on one collector model.
- Source label like the ambient (`open_meteo` / `fallback_archive_year`, §7 Q4) in `thermal_observability`; a fallback logs a warning.
- **Result change:** forced WP hours / store plan follow the forecast sunshine instead of last year's.

## 5. Phases

| Phase | Scope | Result change | Gate |
|-------|-------|---------------|------|
| **P1** | §4.1 parameters + callers A, B | `H` (reference year) → Live floor hours slightly | unit tests; regression deltas reviewed |
| **P2** | §4.2 Live store context from Live plan, plan once per cycle | debug/savings `daily_targets` only | MILP plan hashes of store cases unchanged |
| **P3** | §4.4 collector irradiance from the forecast | Live store plan / forced WP hours with solar thermal | unit tests (fetch, azimuth, conversion); NAS observability Q_sim vs Q_meas |
| **P4** | §4.3 house-only horizon + legacy HDD horizon; remove year-sim calls from Live | targets for installations **without** storage | regression deltas reviewed, goldens updated with rationale |
| **P5** | §6 guard: zero year sims in a Live cycle except §4.1 | none | test |

Order rationale: P1–P3 change the owner installation (storage + 10.3 m² collector), P4 only installations without storage.

Backtesting / SE: untouched in all phases.

## 6. Verification

- **Guard test:** run the Live preparation path (`prepare_optimization_matrix` + flex contexts + targets) on a fixture Live snapshot with a thermal house (with and without storage) and a pool; monkeypatch-count `house_year_result` / RC year model calls → at most one per thermal consumer (parameter derivation), and zero on a second call (memo).
- **Regression suite:** `python -m scripts.run_regression` before/after each phase; deltas listed per case in the PR (metric, old → new, cause). Goldens updated with `--update-golden` only after review (owner accepted slight changes, 2026-10-15).
- **Timing:** local bench on the NAS config snapshot (same script as PR #36); NAS `EARNIE_CYCLE_TIMING=1` after deploy (no `EARNIE_CYCLE_PROFILE`).
- **Live plausibility:** compare `thermal_observability` Q_sim vs Q_meas (Analyse Verbrauch & Kosten) for a few days after P1/P3.

## 7. Decisions (owner, 2026-10-15)

- **Q1** Epic **ThermalHorizon** P1–P5 in Version 2.7, after the *Cycle speed-up* items; listed in `roadmap-nomenclature.mdc`.
- **Q2** Start state without storage (§4.3): target temperature.
- **Q3** Reference year for `H` and parameters: last full archive year; slight `H` shifts for existing installations accepted.
- **Q4** Irradiance forecast unavailable (§4.4): last year's value at the same DOY/hour, labelled `fallback_archive_year`, with a warning.
- Regression deltas: slight changes accepted; reviewed per case in the PR before `--update-golden`.
