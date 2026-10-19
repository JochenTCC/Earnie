# Reference climate window + baseload consistency — implementation plan

Status: **plan, not implemented** (2026-10-19). Language: English (docs/dev).

## 1. Problem (verified on `earnie/greenfield`)

| # | Finding | Evidence |
|---|---------|----------|
| P1 | `baseload_kwh` is non-deterministic: it depends on whether `config.CONFIG` is already built when the profile is normalised (`_config_ready_for_open_meteo`, `house_config/baseload.py:72`). Fallback path: `pool_swimspa` = 0 kWh, `waermepumpe` = legacy estimate. | Σ consumers 11 679 vs 8 098 kWh → baseload 1 321 vs 4 902 kWh/a |
| P2 | `cons_data_hourly.csv` was generated with baseload 0.151 kW (1 321 kWh/a); the backtest runs with the profile loaded in the fallback context (4 902 kWh/a). Reference load 17 014 kWh vs. `Verbrauch (Info)` 13 474 kWh. | `backtesting.csv`, `cons_data_hourly.csv` |
| P3 | The staleness fingerprint hashes the derived `baseload_kwh` → mismatch / false green depending on load context. | `house_profile_cons_data_fingerprint` |
| P4 | No fail-loud when Σ consumers > annual kWh: `max(raw, 2 % floor)` silently clamps. UI only prints "Untergrenze". | `compute_baseload_kwh`, `_render_baseload_preview` |
| P5 | Three different weather bases: baseload uses calendar year `last_full_archive_year()` (= year − 1); WP synthesis uses the calendar year of each slot; pool (`thermal_rc`) always maps to the last full archive year. WP sum: 1 465 kWh (cal. 2025) vs 1 927 kWh (SE window Oct 2025–Sep 2026, +32 %). | monthly sums of `cons_data_hourly.csv` |
| P6 | Further silent fallbacks in the same chain: `data/consumption_profiles.py` (`CONFIG is None` → flat annual / legacy WP), `estimate_annual_kwh_from_profile_csv` (missing hours = 0, mean × 8760 fallback), `ModeledClimateContext._thermal_rc_hourly_profile_for_year` (pads to 8760). | code review |
| P7 | CLI `scripts/run_backtesting.py` does not check cons_data staleness (only the Streamlit button is gated). | `ui/backtesting_run.py:331` |

Not the cause (checked): the 2 % floor does **not** trigger in the greenfield (raw baseload 1 321 / 4 902 kWh vs floor 260 kWh).

## 2. Decisions (agreed with maintainer)

* Terminology: **`last_full_year` is NOT the calendar year `Y-1`.** The new name is `latest_contiguous_12m`
  = most recent gap-free 12-month period the data provides. (`last_full_archive_year()` stays as-is for Live.)
* Two reference-window modes, **derived, not configured**:
  * `rolling_12m` — no CSV import in the profile: 12 whole calendar months ending at the last complete month
    (= existing `wall_clock_simulation_window`, i.e. the SE window).
  * `latest_contiguous_12m` — profile uses historical CSV import (consumer `profile_csv` with `use_profile_csv`,
    and/or `total_profile_csv` when SE uses meter-residual / monthly baseload).
* `latest_contiguous_12m` rules: gap-free to the hour; whole calendar months; with several CSVs → intersection;
  if several gap-free periods exist → the most recent; no 12-month common period → **error** naming the CSV and the gaps
  (no fallback to modelled values). The chosen period + source is shown in the configurator.
* Baseload must be fail-loud (Σ consumers > annual) with a suggestion.

## 3. Target design

```
resolve_reference_climate_window(profile, *, now=None) -> ReferenceClimateWindow
    start: date, end: date            # whole months, 12 months
    mode: "rolling_12m" | "latest_contiguous_12m"
    source: "wall_clock" | "<csv label/path>"
    fingerprint_part: str             # mode + start + end (+ csv size/mtime digest)
```

Single consumer-facing API; used by: configurator baseload, `consumer_annual_kwh` (thermal_annual / thermal_rc),
cons_data synthesis, staleness fingerprint, plausibility check, Season-Mirror/SE period defaults.

Baseload derivation after the change (deterministic):

```
Σ_window = Σ consumer energy over the reference window (CSV consumers: CSV sum; modelled: weather of the window)
baseload = annual_kwh − Σ_window
if baseload < floor → raise/flag BaselineOverAllocated (see §4.B), no silent clamp
```

Synthesis rules (`build_synthetic_dataframe_from_house_profile`):
* `rolling_12m`: slots inside the window use the real weather of their date (this equals what the Season-Mirror
  already selects for the window); slots older than the window are not required for SE — either not generated or
  mapped by calendar month onto the window (same semantics as the mirror).
* `latest_contiguous_12m`: all modelled consumers use the weather of the CSV window, mapped by calendar month/day
  (leap-day handling explicit, error instead of padding).
* WP (`thermal_annual`) and pool (`thermal_rc`) use the **same** weather mapping function (today they differ).

## 4. Work packages

### PR 1 — deterministic baseload + fail-loud (A + B + fingerprint)

**Status (2026-10-19): implemented, not committed.** Deviations from the plan below:
* A was done as "Weg 1 + lazy": house-profile normalization no longer derives `baseload_kwh` / `consumer_kwh` /
  `baseload_min_kwh` (so `Config.__init__` never touches Open-Meteo and stays offline-capable). They are resolved on
  first use via `house_config.baseload.resolve_profile_baseload` / `profile_baseload_kwh` / `profile_consumer_kwh`.
* `_config_ready_for_open_meteo` fallback replaced by `_require_config_ready_for_climate` (RuntimeError); `CONFIG is None`
  fallbacks in `data/consumption_profiles.py` and the `Europe/Berlin` / swallow-all timezone fallbacks in
  `data/modeled_climate.py` / `house_config/thermal_rc_profile.py` replaced by explicit errors.
* Fingerprint hashes inputs only, plus `climate_reference_year` (interim until the reference window of PR 2 exists).
  Existing `cons_data*.meta.json` therefore report `profile_mismatch` once → regenerate.
* Still open (out of PR 1 scope): `data/modeled_temperatures.py` (chart helper, `CONFIG is None` → Europe/Vienna / None),
  `price_forecast_live._archive_latest_complete_day` (UTC fallback, shared with price forecast), legacy estimate for
  thermal consumers **without** lat/lon (kept: UI preview state, covered by existing tests), `estimate_annual_kwh_from_profile_csv`
  (PR 2), relative `OPEN_METEO_CACHE_DIR` (cwd-dependent).

**A. Remove context dependence**
1. Spike (≤ 0.5 d): find the exact import cycle (`modeled_climate → config`) that `_config_ready_for_open_meteo`
   works around. Preferred fix: make archive/climate access independent of `config.CONFIG` (pass timezone / "now"
   explicitly; `planning_now` is the only real config dependency) so `consumer_annual_kwh` always takes the same path.
   Fallback plan if the cycle is not removable: compute `baseload_kwh` lazily after `Config` is built
   (`profile_baseload_kwh(profile)` accessor; update readers of `profile["baseload_kwh"]`).
2. Delete `_config_ready_for_open_meteo` branch and the `CONFIG is None` fallbacks in
   `data/consumption_profiles.py` (`_thermal_annual_daily_from_archive`, `_modeled_thermal_rc_hourly_kw`):
   missing lat/lon, missing Open-Meteo data or missing config → `ValueError` with the consumer id.
3. Same strictness for the `thermal_rc` path in `consumer_annual_kwh` (`annual_kwh` fallback of 0).

**B. Fail-loud over-allocation**
1. `compute_baseload_kwh` returns additionally: `over_allocated: bool`, `shortfall_kwh = Σ − (annual − floor_kwh)`,
   `suggested_annual_kwh`, `suggested_consumer_reduction_kwh`.
   * `over_allocated` ⇔ `annual − Σ < annual × floor` (clamp would apply).
   * Suggestion: `suggested_annual_kwh = max(Σ + TYPICAL_BASELOAD_KWH, Σ / (1 − floor))`
     with `TYPICAL_BASELOAD_KWH` a named constant (proposal: 150 W × 8760 h ≈ 1 314 kWh) — value to be confirmed.
   * Soft warning when baseload < ~5 % of annual (plausibility), no blocking.
2. Policy for hard failure (no startup crash for existing profiles): `profiles_store` marks the profile
   (`baseload_status`), logs a warning at load; **raises** on (a) configurator save, (b) cons_data generation,
   (c) backtest start (UI and CLI).
3. UI (`ui/house_config_profile_form.py::_render_baseload_preview`): `st.error` box with Σ, annual, shortfall,
   "Verbraucher reduzieren um X kWh/a **oder** Jahresverbrauch auf ≥ Y kWh/a erhöhen (Vorschlag: Y)".
4. `trim_baseload_floor_to_match_ist` stays; reuse its result in the suggestion text where an Ist value exists.

**Fingerprint**
5. `house_profile_cons_data_fingerprint`: drop derived fields `baseload_kwh`, `consumer_kwh`, `baseload_min_kwh`;
   hash only inputs (+ reference-window part in PR 2). Existing metas become `profile_mismatch` once → one-time
   regeneration, mention in release-notes draft.

**Tests (PR 1)**
* fingerprint identical for a profile loaded before and after `CONFIG` exists (monkeypatch both contexts).
* `consumer_annual_kwh` raises (not 0) for thermal_rc without lat/lon / without config.
* `compute_baseload_kwh`: Σ > annual → `over_allocated`, suggestion ≥ Σ + floor; boundary Σ = annual × (1 − floor).
* `test_baseload_minimum_fraction` stays green (floor semantics unchanged for non-over-allocated cases) or is
  updated deliberately.
* configurator AppTest: error box with suggestion, save blocked.

### PR 2 — reference climate window

1. New module `house_config/reference_window.py` with `ReferenceClimateWindow` + `resolve_reference_climate_window`.
   * `rolling_12m`: reuse `data.cons_data_season_mirror.wall_clock_simulation_window` (independent of the
     `season_mirror_to_last_month` flag).
   * `latest_contiguous_12m`: reuse `house_config.consumption_csv.load_hourly_profile_csv` / `profile_rows_bounds`;
     hour-set per CSV (cached by path + mtime), whole-month contiguity scan, intersection over CSVs, newest period.
   * Detection of "CSV profile": `consumer_uses_profile_csv` for any consumer, plus `total_profile_csv` when
     `se_uses_meter_residual_baseload` / `se_uses_monthly_baseload` (`house_config/profile_csv_policy.py`).
2. Weather plumbing: make the thermal year models accept a window instead of a calendar year.
   * Check assumptions of `daily_electric_kwh`, `house_thermal_parameters`, `estimate_thermal_rc_annual_kwh`
     (calendar-year arrays, 8760 h, `_slot_hour_index_in_year` ignores leap years) — **spike before coding**.
   * Wire `thermal_annual_kwh_from_archive`, `estimate_thermal_rc_annual_kwh`, `consumer_annual_kwh`,
     `ModeledClimateContext._thermal_hourly_profile_for_year` / `_thermal_rc_*` to the resolved window;
     unify the WP/pool weather mapping (remove the pool-only `_thermal_rc_archive_year` special case).
   * `estimate_annual_kwh_from_profile_csv`: sum over the reference window (no "year with most samples",
     no missing-hour = 0, no mean × 8760); error on gaps.
3. cons_data synthesis (`build_synthetic_dataframe_from_house_profile`, `scripts/generate_cons_data.py`): window-aware
   per §3; remove padding in `_thermal_rc_hourly_profile_for_year` (error instead).
4. Staleness: fingerprint gets `ReferenceClimateWindow.fingerprint_part`; new reason `window_mismatch` in
   `cons_data_consumer_match_reason` + message in `ui/backtesting_cons_data.py`. Rolling mode flags stale once a month (intended).
5. Configurator UI: caption "Referenzfenster: rolling 12 Monate (10/2025–09/2026)" or "CSV <name> 03/2024–02/2025".
6. SE period: in CSV mode default the SE period to the CSV window; if the user picks another period show a warning
   (assumption — confirm in review).

**Tests (PR 2)**
* resolver: no CSV → rolling window for fixed `now`; CSV with gap → newest gap-free 12 months; two CSVs → intersection;
  no common 12 months → error naming file + gap; leap year.
* Σ(cons_data in window) + baseload == annual_kwh (±0.5 %) for greenfield-like fixture in both modes.
* WP and pool use the same weather base (sum equal across years in csv mode).
* fingerprint changes when window or CSV content changes, not when `now` moves within the same month.

### PR 3 — consistency checks, single total load, CLI gate, docs

1. `check_window_energy_balance(profile, cons_df, window, tol=3 %)` (new, `data/` or `simulation/plausibility.py`):
   called after synthesis and before SE; message contains per-consumer deviation vs. reference and a baseload proposal
   (`annual − Σ_window`).
2. One total load: `Verbrauch (Info)` for `historical_reference` currently sums cons_data (`historical_ref_kwh_for_period`),
   while the simulated load is `profile_reference_hourly_load`. Make both come from the same series
   (preferred: sum of the reference run's `consumption_kw`; keep cons_data sum as a cross-check) and add an invariant
   test: historical Info == `ref:*` load == cons_data window sum (±0.5 %). Update `simulation/jahres_verbrauch.py`
   and its docstring ("asymmetric sources").
3. Move the readiness gate (`cons_data_ready`) from `ui/` to the data layer and call it in
   `scripts/run_backtesting.py` (abort with reason) and the UI.
4. Docs/backlog (per CLAUDE.md): German user docs (`docs/konfiguration/`, Hauskonfigurator + Szenario-Explorer) for the
   reference window and the over-allocation error; English backlog entries (`Backlog-Bugfixes.md`, anonymised);
   release-notes **draft** only. No `version.py` change. No config-pack JSON change (window is derived) → no migration wizard.
5. Regression: run `scripts.run_regression` triage per `.cursor/skills/regression-triage` — numbers will move
   (baseload, reference load); verdict = intended, update goldens only after review.

## 5. Acceptance criteria (greenfield re-run)

* Same profile → same fingerprint in every process/context.
* `Verbrauch (Info)` identical for historical, `ref:*` and (within plausibility tolerance) optimised scenarios.
* Σ(cons_data in reference window) + baseload = Jahresverbrauch.
* Σ consumers > Jahresverbrauch → blocking error with concrete numbers and a proposed value.
* CLI backtest aborts on stale cons_data.

## 6. Risks / open points

1. **DECIDED (maintainer, 2026-10-19): Live keeps `last_full_archive_year()`.** Live only reads the envelope heat
   loss H from `house_thermal_parameters` (`thermal_live_house.py`, `thermal_live_store.py`); H is a building property
   and must not drift monthly. Consequence: split the shared derivation — H calibration for Live stays on the fixed
   archive year; the annual kWh for baseload (`thermal_annual_kwh_from_archive`, `estimate_thermal_rc_annual_kwh`)
   get a window parameter and a separate cache key. `house_thermal_parameters().annual_electric_kwh` must not be used for baseload anymore.
2. Existing profiles with Σ > annual will start failing on save/run (intended, but visible); example profiles/fixtures need a check.
3. Year-array assumptions in climate code (8760 h, leap years) may make PR 2 larger than estimated — hence the spike.
4. Open-Meteo availability/cache for the most recent months (archive lag): error with the missing date range; no padding.
5. `TYPICAL_BASELOAD_KWH` value (proposal 1 314 kWh) and the 3 % / 5 % thresholds are proposals.
6. Rolling mode makes baseload (and thus cons_data) change monthly — intended, but users see a monthly "regenerate" hint.

## 7. Suggested order / size

PR 1 (≈ 1–1.5 d incl. spike) → PR 2 (≈ 2–3 d, depends on spike) → PR 3 (≈ 1 d). PR 1 alone already removes the
large error (3.5 MWh); PR 2 removes the remaining ≈ 0.5 MWh weather effect; PR 3 locks consistency.
