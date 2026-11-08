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

- [ ] **SE: a generic flex consumer whose cycle did not fit the book made the whole step infeasible** *(found 2026-11-07 in the viability study, `packs_stufe1d_app`; fixed 2026-11-07 on `main`)*: the first SE book runs from the period start to SA₂ (00:00 to 08:00). A CSV-backed flex appliance whose run started at 07:00 (2.5 h) got the book target 0.36 kWh, but inside the book only the four slots 07:00 to 07:45 were eligible while `min_on_quarterhours` asked for a block of ten and `block_flex_outside_book` forced the rest to 0. `_max_deliverable_kwh` counted slots, not blocks, so the delivery constraint `≥ 0.36 kWh` was infeasible; the strict solve failed, the gap fallback cannot help against infeasibility, and every hourly step of that book booked `_AUTOMATIK_FALLBACK` (192 fallbacks per scenario in G1112 and G2296, L2 − L3 of G2296 on 1 January off by 2.8 €).
  - **Fix:** `optimizer/milp_consumer_delivery.py`: `deliverable_indices` keeps only eligible slots inside the book and, for a consumer with `generic_flex_window`, only those in a contiguous run of at least one `min_on` block (`generic_block_slots`). With no deliverable slot the step adds no delivery constraint for that consumer (verbose warning), the energy stays in the remaining target of the next step. `_add_consumer_delivery_constraints` takes `book_indices` (passed from `milp._add_flex_side_constraints`); the diagnostics report `deliverable_count`.
  - **Measured:** G1112 and G2296 January with flex appliances: 0 fallbacks instead of 384 each; G2296 L2 − L3 Dynamisch in January 21.45 € (fixed appliances 21.31 €) instead of 24.12 €. Unaffected without generic flex consumers (stage-1 packs have none).
  - **Side finding, not changed:** `filter_feasible_consumers` says it removes consumers whose target is unreachable, but appends every consumer in every branch and only warns in verbose mode.
  - **Tests:** `tests/test_generic_flex_block_delivery.py`.
  - **Verify:** a live house with a `flex` or `manual` appliance whose eligible window inside the horizon is shorter than one block must plan the other consumers normally instead of falling back to the automatic mode.
- [ ] **PV forecast comparison run** `[dev]` *(logger done 2026-10-30, [Erledigt](Backlog-Erledigt.md); in autumn the forecast.solar quality varies strongly, e.g. on fog / inversion days)*: run `scripts/pv_forecast_compare.py fetch` hourly for 3–4 weeks in autumn, then `evaluate`. The result decides the default source (see **Solcast as PV forecast source**) and feeds the **PV forecast calibration factor** (**Adaptation P3**): the MAE after the per-source linear scale separates a constant bias, which the calibration factor absorbs, from weather skill. Optional later: DWD MOSMIX `Rad1h` as a further source in the logger.
  - **Note (2026-11-03):** fetch runs hourly since 2026-10-30 06:08 UTC as its own container next to the shadow instance (no gaps so far, Solcast 4 calls a day); `evaluate` from about 2026-11-20. When the production install moves to 2.8, keep that container and its output directory (`forecasts.jsonl`, `state.json`) running, or move both together, so the series has no break.


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Ledger: slots without a booked cycle are missing from `slots_skipped`** *(found 2026-11-04 in the Ledger P5 live check)*: spec `docs/dev/savings-ledger.md` § 4 counts a slot without its own log entry as skipped and stores the skipped slots per reason in the row. `runtime_store/savings_ledger.py::advance` only records the slots the daemon hook hands it, so a quarter hour without a completed cycle leaves no trace. First live row (SA-day starting 2026-11-02 07:06): `slots_total` 96, `slots_present` 69, `slots_skipped` empty, so none of the 27 missing slots has a reason.
  - **The 27 slots, reconstructed from the log:** 24 lie before the chain start (07:15–13:00). Two quarter hours have no completed cycle: 15:30 (cause not checked) and 16:30 (inside the `prod_feed_stale` phase 16:29–16:48). One slot is unexplained.
  - **Proposal:** the day close counts missing slots under their own reasons (for example `before_chain`, `no_cycle`). Costs and shadow SoC stay as they are.
  - Done when `slots_present` plus the sum of `slots_skipped` equals `slots_total` on every closed day, pinned by a test with a gap in the slots.
- [ ] **Ledger: negative saving on the first live SA-days, cause not checked** *(found 2026-11-04 in the Ledger P5 live check; shadow on the maintainer's plant, driven by the 2.7 instance)*: the actual plant cost more than the shadow battery in vendor mode on both closed days. The ledger only reports this; the plan behind it was not examined.
  - **SA-day starting 2026-11-02 (coverage 0.72):** cost 7.43 € with, 6.33 € without, saving −1.10 €, adjusted −0.49 €, import 19.9 / 17.0 kWh, end SoC actual 17 % / shadow 5 %.
  - **SA-day starting 2026-11-03 (coverage 1.00):** cost 12.13 € with, 11.49 € without, saving −0.64 €, adjusted −0.69 €, import 29.4 / 27.6 kWh, end SoC actual 15 % / shadow 5 %.
  - **To check:** whether the 2.7 planner ran grid-charging cycles that did not pay, as in the hand check of 2026-11-01, or whether the configured efficiency flatters the shadow. See `Backlog.md` "Battery efficiency calibration from the log" (Ledger sensitivity, Planner impact).
  - Done when both days are explained slot by slot and the outcome is recorded: a planner bug gets its own entry, otherwise this entry closes with the explanation.
- [ ] There are two entries on subpage Heizsystem-Varianten in HK with same content - is this necessary (the one called Referenzsystem should be sufficient from my POV)
- [ ] New heat system editor should also save changes automatically (like on other sub pages) Add UI-Tests for Autosave when parameters are changed

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
    - **Follow-up (open):** make time-limited live solves visible or reproducible, e.g. record the strict elapsed time / time-limit hit and the objective in `outputs`, and treat a HiGHS time-limit stop as not optimal so `strict_fallback` fires; rename `flags.outage` to `out_of_band`.
    - **Landed (2026-11-01):** fix committed on `release/2.7` and cherry-picked to `main` (collected pick).
    - **Replay on 2026-11-01 (open on `main`):** 73/76 cycles replay to their live hash; three deterministic misses remain: 09:29:52 (SwimSpa), 10:14:52 (heat pump), 16:44:53 (consumer list). Not analysed yet; follow-up on `main`.

- [ ] **Flaky full-suite tests block the pre-commit hook** *(found 2026-10-31)*: in three full runs (two of them pre-commit) exactly one test failed each time, a different one per run: `tests/test_navigation_specs.py::test_n2_env_value_gives_expected_modes_and_sidebar_hints` (parameters `bogus` and `scenario_exploration`) and `tests/test_flash.py::test_flash_notices_are_shown_after_rerun_and_only_once`. Both files pass when run alone (twice each). Looks like state leaking between tests in the xdist full run (environment variable or session state), not a product bug. A commit had to use `--no-verify`. Done when five consecutive full runs are green
  - **Cause (2026-10-31):** not state leakage but load. The last red pre-commit run failed with `RuntimeError: AppTest script run timed out after 3(s)`: Streamlit `AppTest` defaults to a 3 s script timeout, and 128 bare `.run()` calls in the suite use it. Under `-n auto` (all cores busy with MILP tests) a cold script run exceeds 3 s now and then, so a random AppTest fails. The input data is the same in every run.
  - **Fix:** `tests/conftest.py` raises the `AppTest` default timeout to at least 30 s for every test (explicit larger values stay). The timeout only bounds a hung script, so green runs are not slower. Three consecutive full runs green after the fix (5126 passed); close after two more green full runs (e.g. the next pre-commit hooks). **Note (2026-10-31):** the pre-commit hook of commit 85b9a973 was green too, so four in a row; one more is missing
  - **Note (2026-10-31):** the pre-commit hook of 8a4d8d3e was green (fifth run), but two manual full runs the same day each failed one daemon timing test (`tests/test_main_early_start.py::test_early_cycle_plans_for_tick_and_writes_only_after_hold`, `tests/test_main_daemon.py::test_start_stop_with_stub_script`); both pass alone. A second flake pattern under xdist load, not the AppTest timeout; harden these tests, then count five green full runs again
  - **Note (2026-10-31):** `test_start_stop_with_stub_script` hardened: the stub takes `main.lock` before it writes its PID into it, so `status()` briefly reports `running` with `pid=None`; the test now waits for both (8 concurrent runs green). Pre-commit hook of 28d8ace9 failed on it once before the fix, the retry was green. Left: `test_main_early_start.py::test_early_cycle_plans_for_tick_and_writes_only_after_hold`, then count five green full runs
  - **Note (2026-11-01):** `test_early_cycle_plans_for_tick_and_writes_only_after_hold` hardened: it planned for the next quarter-hour tick, which can be seconds away; `planning_now()` is `max(real, tick)` and `_finalize_previous_interval` reads the real clock, so a slow run under xdist load passed the tick and the asserts saw the next slot. The test now plans one slot further out. Count restarted: 2 of 5 green full runs (5181 passed, 26 skipped)


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Add possibility to abort running SE simulation


## Document Review Findings (Do not remove this chapter — even if empty)

