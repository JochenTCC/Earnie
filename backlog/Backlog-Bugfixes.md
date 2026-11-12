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

- [ ] **Bugfix — Cloud demo inflates the usage ping install counters** *(found 2026-11-09)*: with `EARNIE_CLOUD_DEMO=1` every browser session gets its own temp workspace, so `runtime/` (incl. the usage ping state) starts empty. A visitor who agrees in the consent dialog gets a new `install_id` per session, which counts as a new install (`installs_total`, `explorer`) on `earnie-server`. `runtime_store/usage_ping.py` and `ui/usage_ping_consent.py` do not look at `is_cloud_demo()`.
  - **Fix (decided 2026-11-09, maintainer):** in the cloud demo show no consent dialog (explorer and editor fallback), hide the toggle on Optimierer-Dienst and send no install ping (`maybe_send_ping` no-op). Demo visits are counted by the session counter instead (**Cloud demo session counter** in `Backlog.md`).
  - **Done when:** tests for the three paths with `EARNIE_CLOUD_DEMO=1`; German docs (`betrieb.md` § Nutzungsstatistik, `private-env.md`) say the demo sends no install ping.
  - **Landed (2026-11-09, `main`):** `maybe_send_ping` returns early under `is_cloud_demo()` (also with `force`); consent dialog (explorer + editor fallback) skipped; settings show a note instead of the toggle. Tests in `tests/test_usage_ping.py` and `tests/test_usage_ping_consent.py`; docs `betrieb.md`, `private-env.md`, `docs/workflow/usage-ping.md`.
  - **Verify:** after the next Community Cloud deploy, open the demo, run a scenario: no consent dialog; no new `explorer` installs from the demo in the dashboard.
  - **Note:** past demo installs stay in `usage_daily.csv`; they cannot be told apart from real installs afterwards.

- [ ] **PV forecast comparison run** `[dev]` *(logger done 2026-10-30, [Erledigt](Backlog-Erledigt.md); in autumn the forecast.solar quality varies strongly, e.g. on fog / inversion days)*: run `scripts/pv_forecast_compare.py fetch` hourly for 3–4 weeks in autumn, then `evaluate`. The result decides the default source (see **Solcast as PV forecast source**) and feeds the **PV forecast calibration factor** (**Adaptation P3**): the MAE after the per-source linear scale separates a constant bias, which the calibration factor absorbs, from weather skill. Optional later: DWD MOSMIX `Rad1h` as a further source in the logger.
  - **Note (2026-11-03):** fetch runs hourly since 2026-10-30 06:08 UTC as its own container next to the shadow instance (no gaps so far, Solcast 4 calls a day); `evaluate` from about 2026-11-20. When the production install moves to 2.8, keep that container and its output directory (`forecasts.jsonl`, `state.json`) running, or move both together, so the series has no break.


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Recorder replay misses the live plan for some SwimSpa and heat pump cycles** *(found 2026-10-31)*: follow-up of the archived push-reads fix. Replay of all 112 NAS cycles with `start_state.push_reads` (30.10. 15:49 – 31.10. 17:59, 2.7.0-beta.2, `release/2.7` @ `10491702`, `solver_mode="production"`): 108 replay hashes equal live. Reserve refill and plugged-in EV are covered now (EV connected 105/107, `e_auto` in live setpoints 17/19, reserve-refill cycles 4/6; all four misses are explained by the consumers below). The four misses:
  - **30.10. 23:59:57:** same setpoints (Zwangsladen 0.213 kW), but live writes `pool_swimspa: 0.0` in `consumer_powers_kw` and replay leaves the key out, so the hash differs. Live and replay build a different consumer set.
  - **31.10. 08:59:53:** live switched the heat pump off (Automatik, battery 0.5 kW); replay keeps `waermepumpe` 1.9 kW (battery −1.4 kW). The 08:44 cycle before (heat pump 1.9 kW live) matches.
  - **31.10. 14:14:52 and 14:29:52** (both with a pending virtual reserve refill): live Entladesperre (mode 2) with `pool_swimspa` 2.8 kW; replay Automatik without SwimSpa (battery 0.635 / 1.652 kW). The matching 13:59 and 14:44 cycles have the same SwimSpa `push_reads` and `thermal_readings` (36 °C, setpoint 35 °C, heating active).
  - Suspected cause: a SwimSpa / heat pump state from the previous cycle (run or session state) that the live cycle reads and the recorder does not store; `flexible_consumers_state` is empty in every cycle. Not proven.
  - **Note:** the outage cycle 31.10. 14:49:58 (`flags.outage`) carries the same live hash as 14:14 — check whether the outage path re-writes the last plan, and whether outage cycles are excluded from replay checks.
  - Done when the four cycles replay to their live hash (or the remaining difference is a documented, intended non-input) and a regression test pins the missing input.
  - **Analysis (2026-11-01):** `flexible_consumers_state` is not empty (it holds `delivered`, e.g. `pool_swimspa` 14.0 kWh on 30.10.). Two causes, none of them SwimSpa / heat pump run state:
    - **Planning clock (23:59:57, 08:59:53):** every NAS cycle is an early start (a few seconds before its tick) and live plans with `planning_now() = max(real now, tick)`. Replay froze the clock at the recorded `timestamp`, so 23:59:57 counted as 30.10. (SwimSpa target already delivered, `pool_filter` still in the set) and 08:59:53 as the 08:00 hour (heat pump window). Replay now freezes at `max(timestamp, planning_window.start)` (`_recorded_planning_moment`); `planning_window.start` is the anchored tick, so no new input is needed. Both cycles replay to their live hash.
    - **Solver time limit (14:14:52, 14:29:52):** these solves take ~3.2–3.7 s against the 3.0 s strict time limit. HiGHS returns its incumbent with status `Optimal` at the limit, so `strict_fallback` never fires and the plan depends on CPU load and timing. Sequential replays of the same entry give the live plan or the other one (objective 315.88 vs 316.48); all 12 cycles slower than 2.85 s (31.10. 13:44–17:44) are affected, all faster cycles match. Documented non-input (wall clock), not fixable by recording inputs; see the follow-up below.
    - **Telemetry limits:** live applies the HK + inbound export cap (`hk_max_export_kw`, `inbound_export_limit_kw`) and the effective `get_ess_*` limits; replay applied neither and did not drop ESS without own SoC. The recorder now stores `start_state.export_limits` and `start_state.ess_limits`; replay applies them and `filter_planning_batteries_with_soc` (cycles without the keys replay as before). Not the cause of the four misses (export cap 11 kW, limits equal to HK in these cycles), but live inputs replay could not see.
    - **Outage note:** `flags.outage` is set for out-of-band triggers (`bool(out_of_band)` in `main.py`), not for an outage. 14:49:58 runs a full fresh MILP; its hash equals 14:14 because the setpoints are equal (mode 2, SwimSpa 2.8 kW) — the hash covers only mode, target, battery plan and consumer powers. `list_full_horizon_cycles(require_unflagged=True)` excludes flagged cycles from the regression selection; ad-hoc replays of all cycles include them. The flag name is misleading (follow-up).
    - **Result:** replay of all 112 cycles, one worker: 110/112 match; the two misses (14:49:58, 14:50:11) are time-limited solves (14:14 and 14:29 matched in that run, missed in others). Tests: `tests/test_recorder_replay.py` (tick freeze, ESS / export limits), `tests/test_cycle_recorder.py` (recorded keys).
    - **Follow-up (done 2026-11-09 on `main`):** time-limited live solves are visible and no longer decide the plan. The recorder stores one record per MILP solve in `outputs.solver` (stage, elapsed, time limit hit, objective; `recorder_replay.recorded_time_limit_hit`). A strict stop at the limit (PuLP `Optimal` with `LpSolutionIntegerFeasible`) now counts as not optimal and the gap stage (`gapRel` 10 %, 15 s) decides; the strict limit went from 3 s to 5 s (maintainer decision). `flags.outage` is renamed to `out_of_band` (replay still reads `outage` in older cycles). Docs: `docs/workflow/regression-suite.md`. SE keeps its own `cbc_strict_time_limit_sec`.
      - **Live check (open):** after the next NAS image, count `strict_fallback` with `TimeLimit` and the cycle durations (the gap stage adds up to 15 s; the early-start lead adapts, `LEAD_MAX_SEC` 90 s), and replay a day: cycles without `gap_time_limit_hit` must replay to their live hash.
    - **Landed (2026-11-01):** fix committed on `release/2.7` and cherry-picked to `main` (collected pick).
    - **Replay on 2026-11-01 (open on `main`):** 73/76 cycles replay to their live hash; three deterministic misses remain: 09:29:52 (SwimSpa), 10:14:52 (heat pump), 16:44:53 (consumer list). Not analysed yet; follow-up on `main`.
    - **Analysis (2026-11-09, `main` @ `df63cb55`, dump `20261102-none-dump`):** 09:29 and 10:14 replay to their live hash on current `main` (3/3 runs each, solves under 0.5 s), fixed by commits since 01.11. 16:44 was a replay bug: the live snapshot was rejected (`negative_house`, house −0.46 kW), row 0 stayed `forecast`, and `is_live_thermal_planning` is True in a Live cycle only inside `live_cycle_scope()`, which replay did not enter. Replay therefore planned `waermepumpe` with SE day targets (horizon 35.95 kWh, 23.6 kWh remaining; live 0). **Fixed 2026-11-09 on `main`:** `_solve_prepared_entry` enters `live_cycle_scope()`; test `tests/test_recorder_replay.py::test_replay_runs_inside_the_live_cycle_scope`; docs `docs/workflow/regression-suite.md` § 14. The rule dates from 2026-10-15 (`8adcbe56`, on `release/2.7` too), so 2.7.0-beta.2 planned the same way live.
    - **New finding (not pursued):** full replay of 01.11. (104 cycles with ≥ 96 slots) on current `main`: 86 match, 18 miss: 02:59, 03:29, 06:59 and 11:44–14:59 (most cycles in that window). Suspected cause: planner changes on `main` since 2.7.0-beta.2 (e.g. `40e119cb` generic flex delivery), not missing inputs; time-limit hits not checked. Not pursued (maintainer decision 2026-11-09): no replay with the 2.7 code.


- [ ] **Bugfix — wallbox carries the current setpoint binding twice after migration** *(found 2026-11-10)*: after `dm6.wallboxes` and `dm4.required_signal_activation` a migrated wallbox holds both `set_evcs_max_current` and `evcs.<Kennung>.set_evcs_max_current` in `ehal_bindings`; a new wallbox that only went through the activation step holds only the qualified key. Cause not analysed (suspect: the activation step writes the qualified charger key onto the wallbox, where the keys are unqualified). Done when a migrated and a newly created wallbox carry each charger binding once, in one form, and a migration test pins it.
- [ ] **Bugfix — `run_backtesting` exits 0 after an abort** *(found 2026-11-10)*: a pending config migration, a missing wallbox binding and stale consumption data all print `Abbruch: …` and end with exit code 0, so scripts and CI cannot tell an aborted run from a finished one. Done when every abort path exits non-zero and a test covers it.
- [ ] **Bugfix — SE requires `sens_evcs_connected` on wallboxes of dynamic EVs** *(found 2026-11-10)*: loading an EV with `wallbox_assignment.mode: dynamic` fails without the `sens_evcs_connected` binding key on each allowed wallbox (`house_config/wallboxes.py`, "ohne Stecker-Signal erkennt Earnie kein angestecktes Auto"), also for a Scenario Explorer run, which uses no plug signals (D9 assigns by arrival). A planned second wallbox in a study therefore needs a dummy binding. Decide whether the check belongs to the live runtime only; done when the SE runs without it and Live still fails loud.

## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)



## Document Review Findings (Do not remove this chapter — even if empty)

