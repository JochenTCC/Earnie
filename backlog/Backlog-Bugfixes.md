# Open Bugs

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md) (sections `### Bugfix …` / `### Document Review …` / regressions)

Feature roadmap → [Backlog.md](Backlog.md)

## Classification

**Here:** Prod deviation, regression (`xfail`), known misbehavior, review with clear fix/remove outcome; plus `## Document Review Findings` (docs corrections).
**Not here:** New behavior, UX, models, research — see feature backlog in `Backlog.md`.
**Versioning:** completed bugfixes → **PATCH** only in `version.py` (no minor bump). Docs-only findings: no version bump unless asked.
**Document Review Findings:** After the agent corrects the docs → move straight to `Backlog-Erledigt.md` (skip Verifications Pending). See skill `doc-review-findings`.

### `## Bugfix Verifications Pending`

Fix is **implemented** (code + tests + optional PATCH in `version.py`), but **prod/live acceptance** is still pending.

- Move item from the thematic bugfix chapter here once the fix is committed — **not** directly to `Backlog-Erledigt.md`.
- Briefly note what changed (commit/version) if helpful.
- After successful verification: remove from this chapter → `Backlog-Erledigt.md` (`### Bugfix …`) with `- [x]`.
- If verification fails: return to open bugfix chapter or formulate follow-up; document PATCH if applicable, but do not archive as done.


## Bugfix Verifications Pending (Do not remove this chapter — even if empty) + Testing Todos

- [ ] **PV forecast comparison run** `[dev]` *(logger done 2026-10-30, [Erledigt](Backlog-Erledigt.md); in autumn the forecast.solar quality varies strongly, e.g. on fog / inversion days)*: run `scripts/pv_forecast_compare.py fetch` hourly for 3–4 weeks in autumn, then `evaluate`. The result decides the default source (see **Solcast as PV forecast source**) and feeds the **PV forecast calibration factor** (**Adaptation P3**): the MAE after the per-source linear scale separates a constant bias, which the calibration factor absorbs, from weather skill. Optional later: DWD MOSMIX `Rad1h` as a further source in the logger.



## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Recorder replay misses the live plan for some SwimSpa and heat pump cycles** *(found 2026-10-31)*: follow-up of the archived push-reads fix. Replay of all 112 NAS cycles with `start_state.push_reads` (30.10. 15:49 – 31.10. 17:59, 2.7.0-beta.2, `release/2.7` @ `10491702`, `solver_mode="production"`): 108 replay hashes equal live. Reserve refill and plugged-in EV are covered now (EV connected 105/107, `e_auto` in live setpoints 17/19, reserve-refill cycles 4/6; all four misses are explained by the consumers below). The four misses:
  - **30.10. 23:59:57:** same setpoints (Zwangsladen 0.213 kW), but live writes `pool_swimspa: 0.0` in `consumer_powers_kw` and replay leaves the key out, so the hash differs. Live and replay build a different consumer set.
  - **31.10. 08:59:53:** live switched the heat pump off (Automatik, battery 0.5 kW); replay keeps `waermepumpe` 1.9 kW (battery −1.4 kW). The 08:44 cycle before (heat pump 1.9 kW live) matches.
  - **31.10. 14:14:52 and 14:29:52** (both with a pending virtual reserve refill): live Entladesperre (mode 2) with `pool_swimspa` 2.8 kW; replay Automatik without SwimSpa (battery 0.635 / 1.652 kW). The matching 13:59 and 14:44 cycles have the same SwimSpa `push_reads` and `thermal_readings` (36 °C, setpoint 35 °C, heating active).
  - Suspected cause: a SwimSpa / heat pump state from the previous cycle (run or session state) that the live cycle reads and the recorder does not store; `flexible_consumers_state` is empty in every cycle. Not proven.
  - **Note:** the outage cycle 31.10. 14:49:58 (`flags.outage`) carries the same live hash as 14:14 — check whether the outage path re-writes the last plan, and whether outage cycles are excluded from replay checks.
  - Done when the four cycles replay to their live hash (or the remaining difference is a documented, intended non-input) and a regression test pins the missing input.

- [ ] **Flaky full-suite tests block the pre-commit hook** *(found 2026-10-31)*: in three full runs (two of them pre-commit) exactly one test failed each time, a different one per run: `tests/test_navigation_specs.py::test_n2_env_value_gives_expected_modes_and_sidebar_hints` (parameters `bogus` and `scenario_exploration`) and `tests/test_flash.py::test_flash_notices_are_shown_after_rerun_and_only_once`. Both files pass when run alone (twice each). Looks like state leaking between tests in the xdist full run (environment variable or session state), not a product bug. A commit had to use `--no-verify`. Done when five consecutive full runs are green
  - **Cause (2026-10-31):** not state leakage but load. The last red pre-commit run failed with `RuntimeError: AppTest script run timed out after 3(s)`: Streamlit `AppTest` defaults to a 3 s script timeout, and 128 bare `.run()` calls in the suite use it. Under `-n auto` (all cores busy with MILP tests) a cold script run exceeds 3 s now and then, so a random AppTest fails. The input data is the same in every run.
  - **Fix:** `tests/conftest.py` raises the `AppTest` default timeout to at least 30 s for every test (explicit larger values stay). The timeout only bounds a hung script, so green runs are not slower. Three consecutive full runs green after the fix (5126 passed); close after two more green full runs (e.g. the next pre-commit hooks). **Note (2026-10-31):** the pre-commit hook of commit 85b9a973 was green too, so four in a row; one more is missing
  - **Note (2026-10-31):** the pre-commit hook of 8a4d8d3e was green (fifth run), but two manual full runs the same day each failed one daemon timing test (`tests/test_main_early_start.py::test_early_cycle_plans_for_tick_and_writes_only_after_hold`, `tests/test_main_daemon.py::test_start_stop_with_stub_script`); both pass alone. A second flake pattern under xdist load, not the AppTest timeout; harden these tests, then count five green full runs again
  - **Tracker:** clarify the daemon timing flakes, then five green full runs, then archive

- [ ] **Dump `debug_dump_20261030_055437` — discharge bar above zero during Zwangsentladen (2.7.0-beta.1, Loxone):** the note says 19.10. 17:00 Zwangsentladen with no battery-withdrawal bar above zero. History at 19.10. 17:00 is mode 0 (Automatik), plan −0.04 kW, Ist discharge ~0.18 kW. The chart that was open is 29.10. 07:00–31.10. 07:03. There, 29.10. 17:15–17:45 is Zwangsentladen 5 kW (Ist −4.2 / −5 / −5 kW). The chart draws „Batterie entladen (Verbrauch)“ above zero only for the house share (~0.39 / 0.50 / 0.48 kW). The rest (~3.8–4.5 kW) is „Einspeisung (Batterie)“ below zero. Confirmed gap: that export kW has no matching up bar, so the two columns differ by „Einspeisung (Batterie)“. Add an up segment of the same kW (discharge that feeds the export), stacked with „Batterie entladen (Verbrauch)“, and keep the down bar. **Arrives with the next pick from `release/2.7`** (owner, 2026-10-31).


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] **Issue #50 — release notes for the next version:** the Netznutzung now receives VAT on gross import tariffs (`prices_include_vat: true`), so computed import prices rise by the VAT share of the grid fee (e.g. +1.0 ct at 5 ct grid fee, 20 %). Also mention the new load warnings and the recompute button. Draft only, per `release-notes.mdc`; not started yet (no draft in `.github/release-notes/`, `UNRELEASED.md` only has the HA sign hint and the removed `flexible_consumers`). Also mention the new migration question `dm4.ha_sign` (leftover `ehal.ha.sign`, #56) the EU feature pause after an unreachable host (#59), the new HA package automation `earnie_watchdog_release_force` (default on, 300 s; #60), the templated `set_value` action for `input_number` targets (#60) and the report page / daemon start after the migration (#61).


## Document Review Findings (Do not remove this chapter — even if empty)

