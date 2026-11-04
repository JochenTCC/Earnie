# Hauskonfigurator (HK) page — profiling session and speed-up options

Status: investigation, 2026-11-03. Probe changes live on branch `claude/focused-meitner-jcxhtt`
(not on `main`). Harness: `tests/apptest/perf_house_config_harness.py`.

## 1. Method

- The real page (`ui/pages/page_house_config.py`) runs through Streamlit `AppTest` with the
  offline isolation of the AppTests (`tests/apptest/conftest.py`: tmp copy of the fixtures,
  Open-Meteo mocked, `EARNIE_OFFLINE=1`).
- Every script run is profiled **inside the script thread** with pyinstrument (2 ms sampling).
  Profiling from the test thread only shows `sleep` (AppTest joins a worker thread), and cProfile
  mixes the threads.
- Two profiles: the test fixture (`test_home`: heating on, one `thermal_annual` consumer) and the
  example profile from `share/config/house_profiles.example.json` (heat pump + EV + three
  `generic` appliances, heating on, no CSV). The example is the realistic one.
- Scenarios per profile: cold open (process caches empty), warm rerun (no change), three field
  edits (Jahresverbrauch twice, Personen once), the four other tabs.
- Machine: cloud sandbox, single core, no Edibert wheel (installed from the public tag). Absolute
  numbers are indicative; the ratios are what matter. Local desktop numbers should be 1.5–3× lower.

## 2. Baseline (before any change)

Wall time of one user action = sum of the script runs it triggers.

| Action (example profile) | script runs | render time | notes |
|---|---|---|---|
| cold open | 2 | 0.95 s + 1.32 s = **2.6 s** | run 1 ends in an auto-save `st.rerun()` |
| warm rerun (nothing changed) | 1 | **0.75 s** | |
| edit Jahresverbrauch | 2 | 0.72 s + 1.54 s = **2.4 s** | run 1 ends in the auto-save rerun |
| edit Personen | 2 | 0.73 s + 1.47 s = **2.3 s** | |
| switch tab Heizsysteme / WR / PV / Batterien | 1–2 | 0.01–0.10 s | not a problem |

Fixture profile: cold 1.5 s, edit 0.75–0.9 s (two runs each).

### Where the time goes (edit Jahresverbrauch, example profile, 2.26 s render)

| # | cost | what | why it runs on every edit |
|---|---|---|---|
| F1 | 0.72 s | **second script run** after the auto-save (`_render_house_profile_save` → `auto_persist` → `st.rerun()`) | the rerun exists to refresh the Profil dropdown labels from disk; it repeats the whole form and all previews |
| F2 | 0.81 s | **Gesamt-Lastverhalten bundle** (`bundle_from_modeled_profile`): hourly kW of every consumer for 8760 h + the house RC year simulation for the temperature chart | session memo keyed on the full profile fingerprint → any edit is a miss; the memo also grows by one 8760×N bundle per keystroke (never evicted) |
| F3 | 0.30 s + 0.37 s | **house RC year simulation twice** per edit: once for the „Haus Wärme“ expander title (`consumer_annual_kwh` → `house_thermal_parameters` → `house_year_result`) and once for the chart (`_house_year_temps` → `house_year_result`) | both go through `HOUSE_YEAR_CACHE`, but the two callers build different kwargs sets (chart omits `cooling`, `heating_booked`, …) and the chart rebuilds the temperature `Series` with a new index → two different keys for the same simulation; the first miss is legitimate (Grundlast gain depends on Jahresverbrauch) |
| F4 | 0.40 s inside F2/F3 | **per-hour day loops**: `_modeled_generic_schedule_hourly_kw` and `_modeled_ev_hourly_kw` call the per-day function 8760× (once per hour) instead of 365× | plain inefficiency (`generic_hourly_kw_for_day` ran 105 120× on cold open) |
| F5 | 0.30 s per run | **consumer forms** (`_render_consumer_form` × 5: widgets, expanders, labeled rows) | pure Streamlit widget cost, scales with consumer count; ~60 ms per consumer |
| F6 | 0.14 + 0.06 s | monthly stacked chart (`monthly_kwh_from_series` parses 8760 timestamps per consumer with `parse_timestamp`), week chart | aggregation per consumer in Python |
| F7 | 0.33 s (cold only) | `upsert_house_profile` on **open without any edit** | the auto-persist fingerprint is not seeded from disk, so the first run writes the file and reruns |

Not found: Open-Meteo bundle loading (52 ms from the JSON cache, memoised in-process), Edibert
grid-area lookups, EHAL absent-mode read, `load_house_profiles` — all < 20 ms.

## 3. Probe changes on the branch (measured)

| change | files | effect |
|---|---|---|
| A — per-day loops compute each day once and tile 24 h (`_tile_daily_profiles`) | `data/consumption_profiles.py` | generic + EV hourly series 0.40 s → 0.02 s; identical output |
| B — one shared year-simulation cache key: `house_year_result` keys on the effective call (signature defaults merged), the chart path hands the Open-Meteo `Series` through unchanged when it spans the year | `optimizer/thermal_house.py`, `data/modeled_temperatures.py` | second house simulation per edit gone (cache hit) |
| C — rerun after auto-save only when the label (Bezeichnung) changed; `auto_persist(rerun_follows=…)` stores the „Gespeichert“ flash only for callers that rerun (the two plant writers never did, their flash surfaced on the next action) | `ui/house_config_profile_save.py`, `ui/auto_persist.py`, `ui/house_config_plant.py` | one script run per edit instead of two |
| D — session bundle memo bounded to the last 4 bundles | `ui/consumption_display/bundle_cache.py` | memory: no longer one 8760×N bundle per keystroke |

Result (example profile, same harness):

| action | before | after A+B+D | after A–D |
|---|---|---|---|
| cold open | 2.6 s | 1.9 s | **1.7 s** |
| warm rerun | 0.75 s | 0.71 s | 0.70 s |
| edit Jahresverbrauch | 2.4 s | 1.5 s | **1.0–1.1 s** |
| edit Personen | 2.3 s | 1.6 s | **1.0 s** |

Fixture profile: edit 0.78 s → 0.53 s, cold 1.55 s → 1.32 s.

Tests: the modules' own tests (443 tests of the touched areas), `tests/apptest` (without e2e)
and the editor / display tests are green with A–D; two tests were added
(`test_auto_persist_without_rerun_leaves_no_flash`,
`test_house_explicit_defaults_share_the_cache_entry`). C is the only behavioural change: after a
non-label edit the page no longer reruns once more; the „Gespeichert“ caption is shown directly
by `auto_persist`. The T3 AppTests (rejected value → error, no „Gespeichert“) caught the stale
flash of the plant writers that the extra rerun had been hiding.

### What is left after A–D (edit, example profile, ≈ 1.0 s)

| cost | part |
|---|---|
| 0.30 s | consumer forms (F5) — widget floor, grows with consumers |
| 0.17 s | one house RC year simulation (legitimate: Grundlast gain changed) |
| 0.35 s | Gesamt-Lastverhalten: bundle 0.06 s, monthly chart 0.12 s, week chart 0.08 s, navigation 0.03 s, plotly serialisation (before O1; after O1 ≈ 0.25 s, the rest is plotly) |
| 0.10 s | identity / heating / cooling sections, baseload preview, household reference |

### O1 + O2, done (2026-11-04, same branch)

| change | files | effect (section trees, same machine state) |
|---|---|---|
| O1 — month keys sliced from the ISO string once per bundle instead of parsed per hour and per consumer; ISO-week membership parsed once per calendar day; hourly timestamp strings formatted once per (reference year, hours) | `ui/consumption_display/aggregation.py`, `period.py`, `adapters.py` | monthly chart 0.12 s → 0.05 s; week slicing and bundle timestamps ≈ 0.05 s less |
| O2 — `THERMAL_PARAMETERS_CACHE` keyed on the year-model parameters (`heating_params_from_thermal`) instead of the whole consumer dict | `optimizer/thermal_parameters.py` | the HK form, the saved profile and the preview carry the same building with different `label` / `id` / `ehal_bindings` / `timezone_name`; before: 3 derivations per run (each loads the climate bundle, rebuilds the parameters, copies the year result), after: 1. Misses over the harness: 27 → 9 |

A/B in one time window (two runs each, example profile): edit 1.18–1.42 s → 0.95–1.18 s, warm
rerun 0.91–1.11 s → 0.72–0.77 s. The sandbox CPU drifted by ±0.2 s between runs that day, so
the section trees above are the reliable evidence; the totals show the direction. Tests:
`test_house_parameters_key_ignores_fields_the_derivation_does_not_read`,
`test_month_keys_fast_path_matches_parsing`, `test_indices_in_iso_week_window_match_hourly_parsing`.

The O2 described originally (one `consumer_annual_kwh` call passed down instead of two call
sites) is *not* worth doing: with the shared key the second site is a cache hit, and the title
needs the number before the widgets render either way.

## 4. Further options

Ordered by value per risk. O3 is a local optimisation; O4–O6 change *when* things are computed
and need the validity concept in section 5.

- **O3 — seed the auto-persist fingerprint from disk** on first render (F7): no write and no
  rerun on open. Needs a check that the first save is not relied on to normalise old files.
- **O4 — `st.fragment` for „Gesamt-Lastverhalten“**: the section becomes its own fragment that
  reruns on its own buttons (week navigation, period jump) without the form, and the form's
  reruns skip the charts until the inputs that feed them changed. Streamlit fragments rerun with
  the full script on every full rerun, so the gain is for the chart's own interactions (week
  browsing today = a full 1 s run), not for field edits. Low risk, see `fragment_refresh.py`
  for the existing pattern.
- **O5 — deferred model section with an explicit state (recommended if O1–O3 are not enough)**:
  the Gesamt-Lastverbrauch charts and the model-only numbers (house kWh/a, cooling kWh/a,
  household reference) are computed from a fingerprint of the *saved* profile, not of every
  widget value. A field edit saves (as today, cheap) and marks the model section „veraltet“; the
  section recomputes on a button, on leaving the form, or after a debounce — never silently.
  Section 5 describes the state model. Saves ≈ 0.5 s per edit on top of A–D, and makes the
  remaining per-edit cost the widget floor (F5).
- **O6 — process-wide memo for the bundle** (`st.cache_data` or a `YearModelCache` keyed on the
  profile fingerprint) instead of the per-session dict: a second browser tab or a reload reuses
  the result. Only worth it together with O5 (same key discipline).

Not recommended:

- Replacing the RC year simulation by a cheaper estimate for the UI: the kWh/a in the title, the
  baseload and the saved `house_heat_loss_kw_per_k` must stay the planner's numbers
  (`no-implicit-fallbacks.mdc`).
- Reducing the hour resolution of the charts: the week chart is the user's check of the model.

## 5. Validity concept for deferred computations (for O5)

Goal: the user always sees whether a number or chart belongs to the inputs on screen.

State per model section (`ModelState`, kept in `st.session_state` under the profile scope):

| state | meaning | shown as |
|---|---|---|
| `current` | result fingerprint == fingerprint of the inputs that feed it | normal rendering, caption „Modell: aktuell (Stand hh:mm:ss)“ |
| `stale` | inputs changed since the result was computed | result stays visible, greyed, `st.warning`-style chip „Modell veraltet — Eingaben geändert“, button „Neu berechnen“; numbers that are *derived* from the model (Grundlast, Richtwert) show the stale marker too |
| `computing` | a computation is running | spinner in place of the chip |
| `error` | computation failed (CSV unreadable, climate missing) | `st.error` with the message, no result shown (fail loud, as today) |

Rules:

1. The fingerprint is `payload_fingerprint()` over exactly the inputs the computation reads
   (profile fields + consumers + heating/cooling payload + reference year), not the whole session.
   The same function keys the memo (`bundle_cache.modeled_profile_cache_key`) so „current“ is a
   lookup, never a guess.
2. A stale result is never used for anything that is **persisted** or **planned**: the save path
   keeps computing the numbers it stores (Grundlast check, `house_heat_loss_kw_per_k`) exactly as
   today. Deferral only covers what is displayed.
3. Recompute triggers: the button, switching profiles or tabs (then the result is computed
   before the section renders, as today), and optionally a debounce (no edit for N seconds →
   next run recomputes). The debounce is a nicety; the chip is the contract.
4. The chip text names *what* changed when it is cheap to know (field label of the last edit) —
   otherwise just „Eingaben geändert“.
5. AppTest coverage: edit → chip shows stale and the old number stays; button → chip current and
   the number changed; profile switch → no stale result of the other profile (ties into
   `test_session_switch_apptest.py`).

This keeps the „no silent fallback“ rule: nothing is computed with a cheaper model, nothing is
hidden; the user sees a labelled, dated result and decides when to refresh.

## 6. Reproduce

```bash
pip install pyinstrument
PROFILE_OUT=/tmp/hk-prof python -m pytest tests/apptest/perf_house_config_harness.py -q -n 0
cat /tmp/hk-prof/timings.txt
```

`example_03_edit_annual_kwh_run*.tree.txt` is the tree to read first; `cache_keys.txt` lists
the year-model cache hits and misses per run.
