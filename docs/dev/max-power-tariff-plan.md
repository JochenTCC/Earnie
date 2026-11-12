# Max-power dependent tariff: implementation plan (Version 2.8)

**Status:** P0–P5b and P6a–P6c on `main` (PR #96 merged 2026-11-08; P6a–P6c 2026-11-11). P6d 2026-11-11. Open: P5c field test with the margin proposal, P7.
**Backlog item:** **Implement max-power dependent tariff**, Version 2.8. Scope as decided on 2026-11-07: dev doc steps L2, L3 and L4, stage A of [`Capacity-Peak-Budget-Draft.md`](../../backlog/Capacity-Peak-Budget-Draft.md) with a cap the user chooses.
**Regulation:** [`SNE-G-V-2027-Research.md`](../../backlog/SNE-G-V-2027-Research.md).

## Goal

1. The Scenario Explorer (SE) shows the capacity charge in euro per month, for every reference level and for the optimized run.
2. The user sets an import cap. The plan keeps the 15-minute import under it, in Live and in the SE.
3. Earnie reports which slots cannot hold the cap and why. The docs say that this is a reliable plan and no guarantee.

Not in this item: the automatic peak budget, the effective price in the MILP, control inside the quarter hour, flexible withdrawal under § 10 (all **Max-power tariff — automatic peak budget**, Version 2.+1), and the capacity charge in the live ledger or Earnie Points.

## What the code has today

| Area | Finding | Where |
|---|---|---|
| Edibert | `v0.1.15` is pinned (capacity module since `v0.1.14`) and has `capacity_charge_eur`, `capacity_ladder`, `charge_for_month`, `CapacityState`. `GridFee.capacity` holds the entries in effect. Default `include_status` is `verordnet` only. | `Edibert/src/edibert/capacity.py`, `gridfee.py:51` |
| Prices | **No grid area in the shipped catalog has `capacity_charges`.** Earnie's user-area helper `flat_user_grid_area` does not write them, and the Edibert editor keeps them but does not edit them (Edibert backlog, open). Today they can only be typed into `user_grid_fees.json`. | `share/config/grid_fees.json`, `Edibert/src/edibert/editor/house.py:200` |
| MILP | Per-slot export caps exist as a list and are the model for import caps. `p_grid_buy` is not limited. Added constraints run after the model is built (`add_vendor_mode_export_constraints`). | `optimizer/milp_horizon.py:392-398`, `optimizer/milp.py:372` |
| Infeasible plan | `_solve_milp_to_model` returns `None`, Live falls back to Automatik. So a hard cap needs a slack variable. | `optimizer/milp.py:382-384` |
| SE plan | `milp_horizon_schedule` gets no caps at all, which is why `max_export_power_kw` has no effect in the SE. Import caps must be wired through. | `optimizer/simulation.py:375` |
| SE state across windows | The rod store carries its level from window to window. The month peak can follow the same path. | `simulation/engine.py:509-539` |
| SE cost | Fees are one constant per month (`monthly_fee_by_scenario`). A capacity charge differs per month and per result, so this shape does not hold it. | `simulation/backtesting_log.py:124-144`, `ui/backtesting_results.py:179,265` |
| SE invoice | The text says "Leistungspreis fehlt"; the fixed-amounts table is the model for the new line. | `simulation/se_invoice_netznutzung.py:194-217`, `simulation/se_invoice_markdown.py:216-222` |
| Study | The ladder export sums `sim_cost` and excludes fixed fees, so a charge outside `sim_cost` leaves the study unchanged. | `simulation/reference_ladder_export.py:4,89` |
| Load resolution | Profiles are still hourly in places (`load_hourly_profile_csv`, hourly resampling). 15-minute profiles belong to **Edibert meter CSV import**, Version 2.+1. Hourly means flatten short peaks, so SE peaks may be too low. Size not measured. | `data/consumption_profiles.py`, `data/cons_data_house_profile.py` |
| Live measurement | The sampler closes clock-aligned quarter hours with `grid_kw`, from 30 s samples or the counter delta. That value is **net** of export inside the quarter hour; the bill needs import only. The counter delta runs from the first sample in the slot to the close, yet is divided by a fixed 0.25 h, so the window it covers is not exactly the quarter hour. The sampler state holds open samples only, so no month peak survives. | `runtime_store/power_interval_sampler.py:108-129`, `integrations/loxone_meter_energy.py:386`, `main.py:107-114` |
| Replay | `recorder_replay` calls the MILP and must see the same cap and peak, as it does for the export limits. | `runtime_store/recorder_replay.py:631`, `main.py:631` |
| Solver | CBC or HiGHS (the regression suite runs HiGHS in strict mode), with a two-stage relative gap. A large penalty in the objective widens what that gap allows on the energy cost. | `optimizer/cbc_solver.py` |

## Decisions

All accepted by the maintainer on 2026-11-07, as recommended. D4 and D6 go beyond or differ from the backlog text, so the backlog item follows them.

| # | Question | Decision | Why |
|---|---|---|---|
| D1 | Where do prices come from in 2.8? | Catalog entries per grid area from the final SNE-T-V, as a data step like `tf1.grid_area_levies`. Until then test with a hand-written user area. Pull the Edibert editor field forward only if the SNE-T-V slips past the release. | Only per-area values are correct, and the editor is a separate Edibert release. Without D1 the feature ships invisible. |
| D2 | Where does the cap live? | Scenario field `import_cap_kw` with `import_cap_margin_kw`. The Live scenario is a scenario too, so Live and SE read one source. | The 2.8 scope has users compare caps by hand, which needs one cap per scenario. `plant.*` holds one value per file and does not reach the SE. |
| D3 | Does the cap apply in months without a capacity charge? | No. It is active only where `charge_for_month` finds an entry; the UI shows "inaktiv bis …". A cap with no `netznutzung` is an error. | The start differs per grid area up to mid-2028. Earlier, the cap costs energy money and saves nothing. |
| D4 | How is overshoot penalized? | Per-slot slack **plus** one overshoot variable per month, `S_m >= s[t]`. | This goes beyond the backlog text. Linear slack alone treats one slot at +4 kW like four slots at +1 kW, but the bill counts only the height. |
| D5 | Cap below the minimum billing power? | The form refuses to save it. At runtime, if the grid area changed later: visible warning, cap used as entered. | Follows the backlog: tell the user, never raise it silently. |
| D6 | L4 check before or after the solve? | After the solve: `s[t] > 0` names the slots exactly, then a simple power and energy check names the cause. | This differs from the backlog's "before the solve". A check before the solve would duplicate the flex and inverter rules and could disagree with the plan. |
| D7 | Margin value? | Required once a cap is set, form proposes 0.3 kW. The value is a placeholder until P6 measures it. | No hidden default (`no-implicit-fallbacks.mdc`). |
| D8 | Peak source in Live? | Earnie's own 15-minute import log only. A meter sensor as source comes later. | It works on every backend with `grid_kw`; a new EHAL field adds binding work and is not needed for the first version. |
| D9 | Hourly profiles? | Do not pull the 15-minute import into 2.8. Measure the effect in P1 and label the SE peak with its resolution. | That item touches many consumers and pack files. |

## Phases

Each phase is one chat session and ends with green tests and a commit.

### P0: Environment and baseline

**Done 2026-11-07**, on `b2275bbd`:

- Junction `earnie_env/config` set up with `scripts/link_private_env.ps1`. It points at the same private config as the main clone, so a change there changes the real house config.
- **No venv of its own.** A new `.venv` installed fine, but Windows application control blocked its pandas DLL. Run from the worktree root with the main clone's interpreter: `..\Earnie\.venv\Scripts\python.exe -m scripts.run_pytest ...`. Checked in xdist workers: `config`, `main`, `optimizer` and `simulation` load from the worktree. Dependency changes on this branch would not reach that venv.
- Baseline: `scripts.run_pytest tests`: 6035 passed, 26 skipped, about 2 minutes. `scripts.run_regression`: all 12 cases pass.
- SNE-T-V draft in consultation until 2026-11-20, no capacity price per kW found yet; see the research note. D1 stays open until those values exist, so P1 to P6 test with a hand-written user grid area.

### P1: Capacity charge in the SE (L2)

**Built 2026-11-07.** Differences from the list below: `check_capacity_coverage` stops a run with a gap before it starts; the German docs changed with it. Measured for D9, on one house with 15 months of 10-minute import counter readings: the hourly peak is 8 % (0.6 kW) below the 15-minute peak in the median month and 15 % (1.2 kW) in the worst full month. Interpolating 10-minute readings makes the 15-minute value a lower bound. D9 stands, and caps compared on hourly profiles look easier to hold than they are. A real one-month SE on a copy of the offline fixture pack produced the log block and the invoices; the logged peaks matched the booked CSV, and every total equalled `sim_cost` plus the amount. That run has no battery cap and low load, so it checks the wiring, not the size of the charge.

- `house_config/edibert_tariffs.py`: wrappers for `charge_for_month` and `capacity_charge_eur`, since it is the only module that calls `edibert.api`. German messages for `CAPACITY_CHARGE_MISSING` and `CAPACITY_STATE_*`.
- New `simulation/capacity_charge.py`:
  - month peak per result from booked `import_kwh`, `kW = kWh / dt_h`, grouped by local calendar month, one value per slot (`heat_fuel.py` shows the deduplication; the autumn clock change needs its own test);
  - month amount net from Edibert, gross with the import tariff's VAT, as in `grid_fixed_parts`.
- Result: `{result_id: {month: CapacityMonth(peak_kw, billed_kw, net_eur, gross_eur)}}`. It stays outside `sim_cost` and is added after aggregation, like the fixed fees.
- Carry it through `_build_summary`, `ui/backtesting_results.py`, the invoice (year line and a month table with peak and amount) and the hints. Remove "Leistungspreis fehlt".
- Partial months count like the fixed fees, per calendar month touched, with a hint in the invoice.
- Show entries skipped by `include_status`, and `CAPACITY_BANDS_NOT_CONVEX`, as warnings.
- Measure D9 on a house with 15-minute data: peak from 15-minute against hourly load.
- **Tests:** ladder examples A to E of the dev doc § 1.4, month reset, charge starting mid-period, gap gives the coded error, unchanged `sim_cost`, study export unchanged.

### P2: Cap configuration

**Built 2026-11-07**, without the migration; see below. A profile always has a grid area, so D3's "cap without `netznutzung`" only arises for a scenario without a house profile. `strip_assets_for_reference` drops the cap, so scenarios that differ only in the cap share one reference.

- `import_cap_kw` and `import_cap_margin_kw` in `backtesting_scenarios.json`, validated like `_plant_max_export_kw`: both or neither, cap > 0, margin >= 0 and smaller than the cap.
- Scenario resolution passes them on; D3 and D5 are checked there.
- Editor in `ui/pages/scenario_editor_sections.py`, with the minimum billing power and the active months of the grid area shown beside it. Follow `streamlit-ui-state`, `streamlit-apptest`.
- Migration: **none, changed on 2026-11-07 while building.** The plan first said to bump `earnie_data_model` to 6. The fields are optional, absent means no cap, and existing files stay valid, so nothing is reshaped; `own_reference` and `heating_system_ids` were added the same way. A bump would close the startup gate on every install and change the stamp in every fixture, with no data to move. An older Earnie ignores the keys, since `settings` allows additional properties.
- Until P3 and P5 are in, the fields are stored but nothing plans with them; the form's help text already states the final behaviour, so this branch must not ship before those phases.
- **Tests:** validation, step with fixture, AppTest smoke.

### P3: Import cap in the MILP (L3)

**Built 2026-11-07:** model and tests only. Nothing passes caps yet: the SE follows in P4, Live in P5.

Penalty sized on one synthetic winter day (96 slots, 10 kWh battery, evening load 7 kW, price spread 26 cent, with and without a 25 kWh EV), on HiGHS and CBC, in the production flow (3 s strict, then a 10 % gap) and with the gap alone. Pairs are cent per kWh of slack / cent per kW of overshoot.

| Case | 30/50 | 200/500 | 2000/20000 |
|---|---|---|---|
| Cap 4 kW, holds: peak | 4.00 kW | 4.00 kW | 4.00 kW |
| Same, HiGHS gap alone, no EV: energy cost | 349.5 | 349.5 | 361.7 (no cap, strict: 338.2) |
| Cap 2 kW, EV, cannot hold, HiGHS gap alone: slack | 10.50 kWh | 7.92 kWh | 7.88 kWh |
| Same, production flow: slack | 7.87 kWh | 7.87 kWh | 7.88 kWh |

- **Chosen: 200/500.** 200 cent is above any price spread this day has, and a test holds at 150 cent. 30/50 buys overshoot under the gap, and at a spread near 60 cent over two hours it would pay off. 2000/20000 widens what the gap allows on the energy cost.
- On this day, the production flow on both solvers: a 4 kW cap costs 639.3 instead of 638.2 cent and lowers the peak from 16.5 to 4.0 kW. Only one day and made-up numbers, so it says nothing about a year; P4 measures that.
- **Solve time:** with the EV, a holdable cap takes the production solve from 0.19 s to about 0.4 s. A cap that cannot hold runs into the 3 s strict limit on both solvers (0.10–0.19 s without a cap). An unlimited strict solve across this grid did not finish in 9 minutes and was stopped. So strict mode, used by the regression suite, is a risk for capped cases, and P4 has to measure the year's runtime.
- A trivial window (no battery, no flex) skips the solve and reports no slack; P6 has to cover that.

- New `optimizer/import_power_limit.py`, pure: `import_caps_for_horizon(slot_datetimes, cap_kw, margin_kw, peak_by_month, active_months)` gives one value per slot. `P_cap = max(import_cap_kw, P_m0) - margin`, `P_m0 = 0` in a later month, `None` in an inactive month.
- New `optimizer/milp_import_cap.py`, called after the model is built, like the vendor mode: `p_grid_buy[t] <= P_cap[t] + s[t]`, `S_m >= s[t]`, penalty on both in the objective. `s[t]` goes into the plan output.
- `import_caps_kw` passes through `_solve_milp_to_model`, `milp_optimizer` and `milp_horizon_schedule`.
- `None` everywhere adds no variable, so plans without a cap stay identical. A test compares the two models, and the regression suite must stay green without `--update-golden`.
- **Size the penalty, do not guess it:** high enough to beat any energy gain, low enough that the solver gap does not distort the energy plan, on both solvers. Test: a window where the cap cannot hold, energy cost against the same plan with its slots fixed.
- **Tests:** cap holds with battery; EV shifts; EV deadline wins and slack is reported; `limits_only` and `read_only` batteries stay feasible; ratchet; horizon across the month boundary; several batteries; solve time with cap against without.

### P4: Cap in the SE

**Built 2026-11-07.** Live still plans without the cap (P5).

Only booked slots get a limit. A window's lead-in SA₀→SA₁ was booked by the previous window, and a limit there would make the overshoot variable free for the slots that count. Slots over the cap count booked rows against `cap_kw`, not against the cap less the margin.

Measured on the public sample pack `studies/poc_cloud` (2025, AT prices), sunrise window, HiGHS, margin 0.3 kW, four scenarios in parallel, with a made-up capacity charge of 150/300 cent per kW and month (band limit 10 kW, minimum 2 kW). Run B on a mostly idle machine (about 5 of 24 cores busy, 4 of them the run); run A earlier the same evening under unknown load from other jobs:

| Cap | Energy € | Capacity € | Sum € B (A) | Highest month peak kW B (A) | Slots over the cap B (A) | Solves cut at 3 s B | Runtime s B (A) |
|---|---:|---:|---:|---:|---:|---:|---:|
| none | 2179.83 | 176.28 | 2356.11 (2355.39) | 9.62 (9.62) | – | 132 | 695 (777) |
| 8 kW | 2181.47 | 165.71 | 2347.17 (2348.04) | 9.62 (9.62) | 23 (23) | 144 | 719 (793) |
| 5 kW | 2195.35 | 138.29 | 2333.64 (2336.53) | 7.12 (8.12) | 580 (611) | 153 | 753 (834) |
| 3 kW | 2208.98 | 147.56 | 2356.54 (2354.40) | 7.12 (8.12) | 13775 (13783) | 159 | 770 (852) |

- **Runtime:** same order, at most about 11 % longer with a cap. No window failed and no solve hung.
- **Load changes the plans:** between A and B the sums move by up to 2.9 € and the December peak at 5 kW by 1 kW. That is as large as what 8 kW saves (about 9 €). With roughly one window a day, 36 % to 44 % of the solves stop at the 3 s limit and use the plan they have, more with a tighter cap. Small differences between scenarios are therefore noise until the limit stops being wall clock.
- **Reading the euros:** the price is a placeholder, so only the shape counts. In both runs 5 kW pays best (22 € in B), and 3 kW costs more energy without lowering the charge further than 5 kW does. This is what the handbook means by a cap that can cost more than it saves.
- **The sample house is hard to cap:** heat pump and EV each draw 3.5 kW, the EV averages 1.65 kW over the year, and load is hourly. Base load and heat pump alone reach 3.65 kW, so 3 kW cannot hold while the heat pump runs. A peak of 7.12 kW in most months at 5 kW is heat pump plus EV plus base load. A house with less load needs its own run before anyone quotes a saving.
- **Plan, not replay:** January at 8 kW has 9 slots over the cap, and plan and booked import agree at all of them. So they come from the plan, not from the replay. The plan exceeds even the raised limit in 6 of the month's 2976 slots.
- **One breach lifts the month:** on 15 January dryer, EV and heat pump meet an empty battery at 9.54 kW. After that the limit is 9.24 kW and the battery charges from the grid at 2.5 kW on top of a 7.12 kW load. That follows the ratchet by design, and it is why a missed cap counts many slots. Why the plan stacks those loads on that evening was not traced.

Known limits:

- A re-solve inside one window does not lift limits by peaks of that same window. The product path has one solve per window.
- On-demand single-window replay (`simulate_window_snapshot`) starts with no peak, as it starts with no rod store level.
- The forced grid recharge of fixed_24h at the horizon end is not capped; it only happens with an active SoC anchor.
- **Strict mode has no time limit:** a 0.1 kW cap did not end in 240 s with `EARNIE_CBC_STRICT=1`, against 5 s without. Importing `scripts.run_regression` sets that variable for the whole process, so all of a full pytest run is strict, which is what hung the suite. `tests/test_se_import_cap.py` removes the variable; the import side effect stays, as a separate change. A regression case with a cap needs a look at this first.
- **What the two solver stages really do (HiGHS):** PuLP reports a time limit with a solution as `Optimal`, so that plan is used after 3 s and logged as `strict_slow`. The gap stage only runs when no solution exists after 3 s. In January of this pack (32 solves per run) 10 solves without a cap and 11 at 5 kW stopped at the limit, and none reached the gap stage; in year run B no solve did (no `strict_fallback` event). The quality of plans cut off at the limit is not logged, and the limit is wall clock, so SE results can depend on machine load.
- **The gap stage is limited to 15 s** (decided 2026-11-07, maintainer; `GAP_STAGE_TIME_LIMIT_SEC`). It had no limit, and the solve runs inside the live cycle, so it could have blocked the cycle. Without a solution by then, the existing `milp_no_optimal` path sends the battery to Automatik. The 15 s is a first value, not measured on slow hardware; the field test in P5 should check it. CBC was not checked.

Planned:

- `_HorizonOptions` and `_refill_commit_buffer` pass caps. Peaks per month carry across windows next to the rod store and update from booked rows.
- Only L3 gets the cap. L0 to L2 stay uncapped and still get their capacity line, so the comparison shows what the cap earns.
- The booked replay can differ from the plan (Automatik, control mapping). The result therefore reports booked peak, planned cap and slots over the cap per month.
- Forecast mode: the plan uses the plan matrix, the peak comes from the booked matrix.
- **Tests:** year run on a sample pack with caps of 3, 5 and 8 kW; peak held against cost of holding it; runs stay at the same speed order, with `--workers` per `backtesting-max-workers.mdc`.

### P5: Month peak and cap in Live

Split on 2026-11-07 (maintainer): **P5a** measurement and month store, **P5b** cap in `main.py`, recorder and replay, **P5c** clock warning, field test and HouseSim. The raw-sample log for the field test is opt-in and belongs to P5c.

**P5a built 2026-11-07.** The sampler adds `grid_import_kw` with `grid_import_source` and the window (`grid_import_start`, `grid_import_end`) to each closed quarter hour. From the import counter it divides by the real time between the two reads, so the window starts up to one sample interval (30 s) late; interpolating to the boundaries waits for the field test. Without a counter, on a reset or with a window under 5 minutes, it is the mean of `max(grid_kw, 0)`. `grid_kw` is unchanged. `runtime_store/capacity_peak_store.py` keeps one entry per month in `capacity_peaks.json`; `main.py` feeds it after each closed quarter hour and logs a failure without stopping the cycle. A sample mean from fewer than 3 samples or over less than 5 minutes counts as a missing quarter hour (the 5-minute rule for the mean was added after the testbed run below). Nothing plans with the peak yet.

**P5b built 2026-11-07.** `optimizer/live_import_cap.py` builds the limits from the resolved Live scenario and the stored month peaks, for every month the horizon touches. A month without an entry is unknown: the plan holds the cap itself (the strictest limit), and the month is named in `unknown_months`. `main.py` passes the limits to `milp_optimizer`; the cycle recorder keeps limits, months, peaks and unknown months in `start_state.import_caps`, and replay plans with the recorded limits, so it needs neither the scenario nor the peak store of that time. Cycles recorded before P5b replay without a cap. The trivial window and the Automatik fallback log that the cap was not planned. `capacity_peaks.json` is in the debug dump. An unreadable peak store or a cap without a grid area fails the cycle instead of planning without a cap; what the daemon does after such a cycle was not changed or checked here.

**P5c, part built 2026-11-07.**

- **Clock:** nothing new. `runtime_store/clock_skew.py` already estimates the offset from the `Date` headers of public HTTPS responses on every platform and warns in `earnie.log` above 2 s, at most hourly. At 2 s the error on the month peak is at most 0.02 kW for a 10 kW step at the boundary, so the warning threshold is enough for this.
- **Raw log for the field test:** `EARNIE_POWER_SAMPLE_LOG_DAYS=<days>` writes every 30 s sample to `runtime/power_samples/<date>.jsonl`: grid power, import and export counter read at the same moment, when each of the three arrived as a push (`*_pushed_at`, from the inbox row's `last_ts`), clock offset estimate. The field test can run in a Shadow instance: Shadow reads the values through Prod's feed, which Prod writes after each sampler tick, so they arrive up to about 30 s late; the push times are Prod's, so the analysis takes that delay out. Files older than the days set are removed; a failure is logged and never stops sampling.
- **HouseSim run on HA (2026-11-08):** HA contract testbed (HA 2025.7.0, HouseSim archetype from the testbed pack, Earnie built from this branch in Docker), pack migrated to data model 5 with a user grid area, the placeholder capacity charge and a 3 kW cap (margin 0.3 kW). Seen:
  - The Live plan carries the limit 2.7 kW on all 191 slots; the cycle record names November as unknown until the first quarter hour is stored, then holds the peak.
  - The quarter hour 08:00 closed with `grid_import_kw` 0.312 kW from the import counter over 885 s (first read 15 s into the slot), while the net `grid_kw` was -1.451 kW: import and export in the same quarter hour, which is why the import needs its own value.
  - The quarter hour before (Earnie ran its last 35 s) fell back to the mean, as intended, but three samples marked it as measured. Fixed: a mean now needs 5 minutes as well.
  - Not seen: an import above the cap. The simulated house stayed well below 3 kW in this run, so holding the cap was not exercised end to end.
  - The old testbed pack named a `thermal_rc` pool heater `pool_filter`, the id the planning reserves for the pool filter pump, so planning built two consumers with one id and the daemon stopped at start. The pool was removed from the testbed copy; nothing rejects that id when the pack is saved.
- **Open, needs the maintainer:** the two-week field test against the operator's quarter-hour export. The margin stays a placeholder until then.

Planned:

- Sampler: new `grid_import_kw` per quarter hour, from the import counter only (`total`, without `total_neg`), else the mean of `max(grid_kw, 0)` over the samples. `grid_kw` stays as it is. Check the sign convention per backend (`ehal-unit-conversion.mdc`).
- Measure the real window: store the time of both counter reads and divide by the elapsed time, or interpolate to the quarter-hour boundaries, instead of the fixed 0.25 h. The value records its source and window.
- Clock: Earnie measures on its own host clock and does not try to follow the meter (see **Meter timing** below). Show a warning when the host clock is not synchronised, if the platform can tell.
- **Field test before the margin is set:** two weeks of the maintainer's meter. Keep the 30 s samples for that time and compare with the quarter-hour export from the operator's portal: peak difference per month, typical and worst error per quarter hour, and the shift of Earnie's window that fits best. The data stays private, only the method and the rounded error go into this repo.
- New `runtime_store/capacity_peak_store.py`: persisted per calendar month, local time of the house: peak, its slot, first logged slot, quarter hours missing. Survives restarts; a month change starts a new entry.
- Unknown is never 0: after an install or a gap the state says "gemessen seit …" or "n Viertelstunden fehlen", and the UI shows it. This value is measured, but it can be lower than the meter's.
- `main.py`: build caps before `milp_optimizer`; record cap and peak in `cycle_recorder` like `record_export_limits`; `recorder_replay` reads them.
- Automatik fallback and `_trivial_optimizer_result` hold no cap, so both report it.
- A mid-slot `Request_Optimize` does not count energy already used in the running quarter hour. Known limit, part of L4b.
- **Tests:** peak over a month change and restart, gaps, import against net inside one quarter hour, replay with cap, HouseSim run on HA.

### P6: Warning and display (L4)

Split on 2026-11-11 (maintainer) into **P6a** report, **P6b** Monitor page and **P6c** SE and testbed, built before the field test; only the margin's proposal waits for it. Decisions of that day:

- **E1, causes:** in this order, the first that applies is the main cause, all that apply are kept: base load (load − PV without the planned flex stays above the limit even with full battery power), battery or inverter power, battery empty or reserve, consumer with a target, none detected (said as such).
- **E2, measured overshoot:** Live checks each closed quarter hour; above the cap and the month peak before it, the cause is the plan's own if the plan had that slot over its limit, else "Lastprognose" (the plan held, the meter did not), "nicht eingeplant" (trivial window, Automatik) or none detected (plan of that slot not known).
- **E3:** the display goes to the Monitor page (`ui/pages/page_cockpit.py`). `ui/truth_banner.py` is the attribution banner, not a status banner.
- **E4:** each step commits to `main` with green tests.

**P6a built 2026-11-11.** `optimizer/import_cap_report.py` builds the report from the solved model: per slot with slack the planned import, the limit, the overshoot, the causes and the consumers with a target that run. `milp_optimizer` puts it into the plan (`milp_plan["import_cap_report"]`), the trivial window and Automatik get a report that says the cap was not planned and why. Live had only slot 0's slack before (`_extract_milp_plan`), so the report is built from the model, not from the plan output. `main.py` stores the latest report in `runtime/import_cap_report.json` (only while a cap is set; removing the cap clears it), logs the first slot over the limit, and records the report in the cycle record (`outputs.import_cap_report`); replay builds it again (`ReplayResult.import_cap_report`). After each closed quarter hour `main.py` checks the measured import against the cap and the month peak before it (`runtime_store/import_cap_report_store.record_measured`), keeps the events of the current and the previous month in the same file and logs them. The file is in the debug dump.

- How the causes are read: battery power from the discharge against the batteries' upper bounds, inverter limits from the binding `inv_ac_dis_*` / `inv_ac_clip_*` constraints, battery energy from a charge in the slot (reserve refill) or the batteries reaching their floor before they charge again, base load from the slot's balance. A house without battery power gets no battery cause.
- **Not covered:** an SoC pinned by an equality (SE SA₁ carry-in) is not read as a reserve. "None detected" stays possible and is reported as such.
- **Tests:** `tests/test_import_cap_report.py` (each cause, inverter limit, report in the plan, trivial and Automatik, cycle record, store, measured check, Live hooks).

**P6b built 2026-11-11.** `ui/capacity_charge_panel.py` puts a "Leistungspreis" block on the Monitor page (`ui/pages/page_cockpit.py`, under the absent-mode notice; since 2026-11-12 below Chart 2 in the "Earnie-Effekt" section), only when the resolved Live scenario has a cap or the grid area a capacity charge in the current month (host clock, as the peak store keeps months).

- Figures: month peak from `capacity_peak_store.month_peak` with measured-since, peak slot and missing quarter hours; billed power = max(peak, charge minimum); amount so far and the next kW (`capacity_charge_eur(billed + 1) − capacity_charge_eur(billed)`), both gross with the import tariff's VAT as in `simulation/capacity_charge.py`. A month without entry shows "unbekannt" and the minimum amount ("mind. …"), never 0, and no next-kW price.
- Cap: cap, margin and the planning limit `max(cap, peak) − margin`; a peak above the cap is named.
- Report (`import_cap_report_store.load()`): warning with count, first slot and main cause (most frequent `cause` over the slots, the earliest on a tie), a line for this month's measured overshoots, both as tables in an expander; info when the last cycle did not plan the cap (trivial window, Automatik); a caption when no report exists yet or the plan holds. The report has no timestamp of its own, so the block shows the plan's first slot.
- Notices from `check_import_cap`: below the grid area's minimum (D5 at runtime: warning, cap used as entered), inactive until the charge starts, no released charge. A cap without grid area is an error.
- Errors (Edibert gap `CAPACITY_CHARGE_MISSING`, unreadable store or report, unknown cause key) are shown as an error in the block; the rest of the Monitor still renders. During onboarding (`is_runtime_params_deferred`) the block is not shown.
- **Tests:** `tests/test_capacity_charge_panel.py` (billing, minimum, band limit, unknown month, planning limit, inactive, D5, report and measured filtering, Edibert gap, main cause), `tests/apptest/test_capacity_charge_panel_apptest.py` (shown, hidden, warning with details, unknown month, not planned, D5, inactive, error), Monitor smoke: hidden without cap and charge.
- **Not checked:** the block in a running app with a real cap; covered by AppTest only.

**P6c built 2026-11-11.** The SE month report names days and causes; a HouseSim run at 1.5 kW and a first estimate of the margin's forecast part.

- **Cause per booked slot:** `milp_horizon_schedule` (the SE's open-loop path) gives each slot with a limit the limit and, where the plan goes over it, the main cause (`import_cap_report.plan_slot_marks`, the same reading as the Live report). A trivial window and a failed solve mark their slots `not_planned`. The slot-by-slot path (`commit_hours` 1, fixed_24h only) takes slot 0's cause from the report `milp_optimizer` puts into the plan (`first_slot_mark`). The chart rows carry both; a run planned with a cap adds the columns `import_cap_limit` and `import_cap_cause` to its result and the SE log CSV. They do not end in `_kw`, because every `*_kw` column of the log counts as a consumer. A run without a cap has neither, so plans and goldens stay as they were.
- **Month report:** `CapacityMonth` gains `days_over_cap` (local calendar days with at least one booked slot over the cap) and `causes_over_cap` (main cause → booked slots, most first). A booked slot over the cap takes the plan's cause; without one the SE adds two causes of its own: **month peak** when the booked slot stayed within the plan's limit, so an earlier peak of the month had lifted the limit above the cap (the ratchet), and **booked above the plan** when it went over the plan's limit (forecast mode, or the control mapping in `derive_control_from_milp_plan`). A capped result without the columns, or a slot over the cap without a plan limit, is an error.
- **Table:** "Tage über der Grenze" and "Hauptursachen" (German label: slots, most first) next to "Viertelstunden über der Grenze". Logs written before P6c show a dash. German docs: `docs/ui/betriebsmodi.md`.
- **Tests:** `tests/test_se_import_cap_causes.py` (marks per slot, schedule, trivial window and failed solve, slot 0 of the per-slot path, chart rows of both paths, days and each SE cause, missing columns, a run where every slot over a 0.1 kW cap has a cause, a run without a cap has no columns, table and old logs).

**HouseSim run at 1.5 kW (2026-11-11).** Same bench as P5c (HA 2025.7.0, archetype `earnie_pack`, Earnie built from the working tree in Docker), Live scenario with `import_cap_kw` 1.5 and margin 0.3, the placeholder charge on the user grid area. The bench's `capacity_peaks.json` held 18.07 kW from an earlier run (limit 17.77 kW, cap without effect), so it was moved aside; November then counted as unknown and the plan held the cap itself. Seen in four cycles (13:40 to 14:00):

- **Report:** the plan cannot hold 1.2 kW in 44 to 46 quarter hours (highest planned import 4.3 to 5.2 kW: heat pump and swim spa with targets, plus base load). Main causes: battery empty or reserve in all slots but the first (battery at 56 % with the evening and night ahead); the first slot names the consumer with a target, once battery power. `runtime/import_cap_report.json`, the warning in `earnie.log` and `outputs.import_cap_report` in the cycle record agree.
- **Measured:** the quarter hour 13:45 closed at 2.44 kW (mean of samples; the bench has no import counter), 0.94 kW over 1.5 kW, and was stored as a measured overshoot with the plan's cause `consumer_target`. The month peak became 2.44 kW. The cycle at 13:59:45 still planned with 1.2 kW, since it starts 15 s before the quarter hour closes; the next one plans with the raised limit.
- **What the cause says here:** the measured 2.44 kW is the archetype's constant base load (2.5 kW) with the battery idle; the sim does not model the heat pump and swim spa the plan counted on, so measured import stayed below the planned 4.3 kW. E2 takes the plan's cause for a slot the plan already had over its limit, so the measured event names the consumer although base load set it. That follows E2 by design; whether the measured check should compare measured and planned import before it takes the plan's cause is a question for P7 or later.
- **Replay:** with HiGHS in production mode, the cycle whose replay solved within the strict limit gave the same plan hash, slots and causes. Three replays hit the 5 s strict limit on the development machine, where Live had solved in 0.5–1.1 s; their gap-stage plans differ (same slots with other causes in two, 47 instead of 44 slots with three "none detected" in one). So a replayed report is only comparable when the replay solves at the same stage, as P4 found for SE plans cut at the wall-clock limit.
- **Not exercised:** the import counter path of the measured check (bench without counter), a month change, and a cap in the SE on the bench.

**Margin, forecast part (estimate 2026-11-11, for the proposal only).** Defaults unchanged; the placeholder 0.3 kW stays until the field test. Method: the Shadow's optimization history holds, per quarter-hour cycle, the plan inputs of slot 0 (base-load forecast `expected_p_act`, PV forecast), and the next cycle's closed quarter hour holds the measured house load, PV and the optimized consumers. Forecast error = measured net load (house − optimized consumers − PV) − forecast net load (base load − PV), per quarter hour. Battery and optimized consumers are left out on both sides, since Prod, not the Shadow, controls them. One house, 11 November days, 983 quarter hours, so a first figure, not a value to ship:

| Quarter hours | n | Mean | P90 | P95 | P99 | Max |
|---|---:|---:|---:|---:|---:|---:|
| all | 983 | +0.25 | +1.1 | +1.5 | +2.1 | +3.2 |
| forecast net load ≥ 1 kW | 117 | −0.6 | +0.3 | +0.4 | +0.7 | +0.8 |
| measured net load in the top tenth | 99 | +0.8 | +2.0 | +2.2 | +3.1 | +3.2 |

kW, positive = more import than planned. Read:

- Where the plan already expects a high import, and the cap binds, the forecast part is about 0.4 kW at P95 and 0.7 kW at P99. The placeholder 0.3 kW covers about 90 % of those quarter hours.
- The month's highest measured quarter hours come mostly from load the forecast did not see (cooking, appliances): +2.2 kW at P95. No margin of sensible size covers that; it is the case for control inside the quarter hour (L4b, Version 2.+1) and for the docs' "reliable plan, no guarantee".
- Base load is under-forecast on average by 0.25 kW (0.14 kW without PV), so part of the margin is bias, not noise.
- Proposal input once the field test adds the measurement error: forecast part 0.4 kW (P95 where the cap binds) plus the measured error at peak quarter hours.

### P6d: Observe mode

Added on 2026-11-11 (maintainer), for the release: a user can switch the cap to **observe** first. Earnie then plans and controls as without a cap, and shows what it would have done with the cap and what that would have saved. Users, and the maintainer, can watch the feature without risk before they let it control. Decisions of that day, as recommended:

- **O1, where the switch lives:** a scenario field `import_cap_mode`, `observe` or `optimize`, next to `import_cap_kw` (D2: the Live scenario is a scenario). Required once a cap is set, no default in the code (`no-implicit-fallbacks.mdc`); the form proposes **observe** for a new cap and saves it. It acts in Live only; the SE always plans with the cap, since a simulation has no risk. Not `EARNIE_UI_MODES`, which only decides which pages exist, and no environment variable of its own, so the user can switch in the UI. Migration: none, the key is optional like the cap. A file with a cap and no mode is an error; it can only be a development file (the maintainer's pack, the HA bench), since no release has shipped the cap yet.
- **O2, shadow plan:** in observe mode `milp_optimizer` solves the executed plan without caps, then a second time with the caps on the same matrix, start state and consumer targets. The second plan is never executed. The P6a report comes from the second model and says it is observe mode. If the second solve fails or hits its limit, the executed plan is untouched and the report says the cap was not planned (new reason). The cycle record keeps both solver records; replay rebuilds both. Cost: on the development machine the Live MILP took 1.6–3.4 s in a cycle of 17–19 s (`runtime/timing/cycles.jsonl`, October 2026); P6d-1 measures the second solve, also on the NAS, before the step is committed.
- **O3, hypothetical month peak:** per closed quarter hour, hypothetical import = max(0, measured import + Δ), Δ = slot-0 grid import of the shadow plan − slot-0 grid import of the executed plan, from the cycle whose slot 0 was that quarter hour. A month store of its own keeps the hypothetical peak (measured-since and missing quarter hours as in `capacity_peaks.json`), and the shadow plan's ratchet uses it, not the real peak; otherwise the first real overshoot lifts the shadow limit and the shadow stops showing interventions. An unknown month holds the cap itself, as in P5b. Limit, said in the docs: each shadow plan starts from the real state (SoC, consumer progress), so the hypothetical peak is an estimate, not a closed-loop replay.
- **O4, what the Monitor shows in observe mode:** a notice that the cap is observed only; the capacity charge with the real peak against the hypothetical one, and the difference as the estimated saving on the capacity charge; the extra energy cost of holding the cap; the list of interventions (quarter hours where the two plans differ in slot 0 by more than the tolerance, or the shadow plan goes over its limit): slot, import without and with the cap, cause, consumers. Measured overshoots (E2) keep the cap as threshold and take their cause from the shadow plan.
  - **Changed while writing the plan:** the extra energy cost is **not** summed from slot 0. A shadow plan that discharges more in slot 0 pays for it with a recharge later, so slot 0 alone shows a gain where there is a cost. The block shows the current plan's extra energy cost over the horizon (energy cost of both plans over the same slots, without the cap penalty), labeled as an estimate, and no month sum. A month sum is open (for example per closed SA day from the plans at its start), decided when P6d-1 has data.

Steps, each committed to `main` with green tests (E4):

- **P6d-1 service:** field and validation, second solve, report from the shadow model, hypothetical peak store, measured check with the shadow cause, cycle record and replay, solve time measured. Tests: mode required with a cap, observe plans without caps and reports with them, `optimize` unchanged, shadow failure leaves the executed plan, Δ and the hypothetical peak per quarter hour, the shadow ratchet uses the hypothetical peak, month change, replay.
- **P6d-2 UI and docs:** mode in the scenario form (proposal observe), Monitor block per O4, German docs (`docs/ui/betriebsmodi.md`, handbook, `docs/konfiguration/preise.md`). Tests: AppTest for both modes, panel unit tests for the saving and the intervention list.

**P6d-1 built 2026-11-11.** The service side of observe mode.

- **Setting:** `house_config.import_cap.parse_import_cap_mode`. Refined from O1 while building: the mode is required where it acts, in Live (`resolve_live_import_caps` and the measured check fail loud on a cap without it); the scenario check (`_check_import_cap`) and the SE accept a missing mode but refuse an unknown value or a mode without a cap, so SE scenarios with a cap stay valid. Schema entry in `share/config/backtesting_scenarios.schema.json`.
- **Shadow plan:** `milp_optimizer(..., import_cap_observe=True)` solves the executed plan without the caps, then `milp.shadow_import_cap_report` solves the same arguments with them (`verbose` off). The report (schema 2, every report now names its `mode`) comes from the shadow model; its `observe` block holds slot 0 of both plans (import, battery = discharge − charge, consumers), `delta_import_kw` and `energy_cost_extra_eur` (grid cash flow over the horizon as the objective prices it, without wear, credits and penalty: `import_cap_report.plan_energy_cost_cent`). Trivial window: delta 0; Automatik and a failed shadow solve (`shadow_failed`): delta unknown. Observe mode logs no "not planned" warning.
- **Hypothetical peak:** `capacity_peak_store.record_slot` (the old `record_closed_interval` now calls it) writes `capacity_peaks_observe.json` (`capacity_observe_peak_file`), and `resolve_live_import_caps` reads that file for the shadow plan's ratchet in observe mode. `import_cap_report_store.record_observed`, called by `main._record_month_peak` in observe mode, takes the delta from the stored report when its slot 0 is the closed quarter hour; otherwise, or unmeasured, the quarter hour counts as missing. The real peak store is recorded as before.
- **Refined from O4 while building:** in observe mode the measured check (E2) runs on the hypothetical import against max(cap, hypothetical peak before), so its events say where Earnie would still have gone over the cap; each event keeps the metered value beside it (`hypothetical: true`, `measured_kw`). Quarter hours where the plans differ by more than the tolerance go to `interventions` in `import_cap_report.json` (slot, measured, hypothetical, delta, slot 0 of both plans, shadow cause), current and previous month.
- **Record and replay:** `start_state.import_caps.mode`; replay solves without the cap in observe mode, so the plan hash matches the executed plan, and rebuilds the shadow report. Records from before P6d have no mode and replay as `optimize`, the only mode then.
- **Solve time (development machine, synthetic 165-slot horizon, battery and EV, cap that binds):** without cap 0.3 s, `optimize` 5.7 s, `observe` 5.9 s. Observe mode costs one uncapped solve more than `optimize`; the capped solve dominates and is bounded by the solver's limits. **Not measured on the NAS**: that needs a build there.
- **Tests:** `tests/test_import_cap_observe.py` (mode rules, executed plan equals the free plan, shadow report and delta, `optimize` unchanged, failed shadow solve, trivial and Automatik, Live caps from the hypothetical peak, delta per quarter hour, missing quarter hours, threshold from the hypothetical peak, Live hooks and log, cycle record, replay hash). The Live tests with a cap now set `import_cap_mode`.
- **Not covered:** a run in the app or on the HA bench; the Monitor block still shows an observe report like an `optimize` one until P6d-2; a month sum of the extra energy cost (open, see O4).

**P6d-2 built 2026-11-11.** Form, Monitor block and German docs.

- **Form:** radio "Im Live-Betrieb" (Beobachten / Danach planen) under cap and margin, disabled without a cap, seeded with the stored mode or the proposal `MODE_PROPOSAL` (observe). Stored only with a cap, like the margin; clearing the cap removes it. The help text says it acts only for the Live scenario. A scenario with a cap and no mode gets the proposal when it is opened in the form and is then saved with it.
- **Monitor:** in observe mode the block says so, keeps the measured figures and adds a second row: "Spitze mit Earnie" (from `capacity_peaks_observe.json`), "Leistungspreis mit Earnie", "Ersparnis (geschätzt)" (amount so far − amount with Earnie) and "Mehrkosten Energie" (the latest report's `energy_cost_extra_eur`, current plan, no month sum). Captions: estimated since, quarter hours without comparison, a measured peak that covers quarter hours before observing began, and that each comparison plan starts from the real state. The planning limit, warning and the line over the cap refer to the comparison plan and the hypothetical events; the details add "Wo Earnie eingegriffen hätte" (measured, estimated, delta, battery without → with the cap, changed consumers, cause). Events of the other mode in the same month are left out, and a report of the other mode (mode just switched) counts as no report yet. A cap without a mode is shown as an error in the block.
- **Docs:** `docs/ui/betriebsmodi.md`, `docs/user-manual/Benutzer-Handbuch-Earnie.md` (scenario field and Monitor), `docs/konfiguration/overview.md`, `docs/konfiguration/preise.md`.
- **Tests:** `tests/test_capacity_charge_panel_observe.py` (charge with the hypothetical peak and saving, unknown hypothetical month, optimize mode filters, missing mode or store, AppTest of the observe block with tables, failed comparison plan, report of the other mode), `tests/apptest/test_scenario_import_cap_apptest.py` (mode proposed, switched and stored, cleared with the cap).
- **Not checked:** the block and the form in a running app with a real cap; AppTest only, as for P6b. Observe mode has not run on the NAS.

**HouseSim run in observe mode (2026-11-11).** Same bench as P6c, Earnie built from `e3131d0d` in Docker, Live scenario with `import_cap_kw` 1.5, margin 0.3, `import_cap_mode` observe, the placeholder charge (min 2 kW) on the user grid area. The real `capacity_peaks.json` kept its 18.07 kW from earlier runs; the hypothetical store started empty, so the shadow plan held the cap itself. Three cycles (15:03 start and an early run on `request_optimize`, 15:15), then reset.

- **Plans:** the executed plan had no cap (slot 0 import 6.4 to 10.8 kW, battery locked), the shadow plan discharged up to 5 kW in slot 0 (import 4.6 to 5.8 kW) and still went over 1.2 kW in 36 to 40 quarter hours (consumer with a target, battery power). Extra energy cost of the shadow plan 0.65 to 1.20 EUR over the horizon. Log lines, `import_cap_report.json` (schema 2, `mode` observe, `observe` block) and the cycle record (`import_caps.mode`, two solver records) agree.
- **Solve time on the bench:** executed plan 0.1 s, shadow plan 0.4 to 1.8 s (strict limit of the bench 2 s), against 0.5 to 0.9 s for the capped plan in P6c.
- **Quarter hour 15:00:** measured 1.54 kW (mean of samples), delta −5.0 kW from the plan of that slot, hypothetical import clamped at 0; stored in `capacity_peaks_observe.json` (peak 0.00 kW, source `measured_plus_plan_delta`) and as an intervention with both slot-0 plans and the cause `battery_power`. No hypothetical overshoot.
- **Monitor:** block as specified (observe notice, second row, intervention list, comparison-plan wording). The notice for a cap below the minimum still said "Earnie plant mit der Grenze wie eingegeben"; changed to name the comparison plan.
- **Replay** (local, `EARNIE_ENV_PATH` on the bench; `recorder_replay` is not in the image): both observed cycles give the executed plan's hash. The cycle whose shadow solve took 1.76 s replays with a slightly different shadow plan (delta −1.89 instead of −1.79 kW, extra 1.51 instead of 1.20 EUR), as P6c found for solves near the strict limit; the other matches exactly.
- **Findings:**
  1. **The estimated saving compares different periods.** "Ersparnis (geschätzt)" takes the real month peak (18.07 kW, from 09.11.) against the hypothetical peak since observing began (0.00 kW, from 15:00), so it showed 43.45 EUR after one quarter hour. The caption says the real peak covers earlier quarter hours, but the metric stands as a number. Every user who switches to observe mode mid-month sees this.
     **Fixed the same day (maintainer):** `record_observed` also writes the measured import of exactly the quarter hours that get a hypothetical value to `capacity_peaks_observe_measured.json` (`capacity_observe_baseline_file`, missing where the hypothetical one is). The Monitor's second row is now "Spitze ohne Earnie" (that measured peak), "Spitze mit Earnie", "Ersparnis (geschätzt)" = charge at the measured minus charge at the hypothetical peak of the same quarter hours, and "Mehrkosten Energie"; "Leistungspreis mit Earnie" is gone. Tests: baseline per quarter hour and missing slots in `tests/test_import_cap_observe.py`, saving independent of the real month peak in `tests/test_capacity_charge_panel_observe.py`. Not run on the bench again.
  2. **The delta inherits the forecast error.** The hypothetical import is measured plus the difference of the two plans' slot 0. On the bench the sim does not run heat pump and swim spa, so measured import (1.54 kW) lay far below the plan (10.78 kW) and the −5 kW delta clamped it to 0. For a fixed discharge setpoint that is what would have happened (the battery would have covered the load and exported the rest), but in a real house the estimate is as good as the base-load forecast of that quarter hour. Kept as is (maintainer, 2026-11-11) and said in the docs.

### P7: Docs and close

- German user docs, in the same change as the behaviour where possible: `docs/konfiguration/preise.md`, `docs/referenz/tarife-quellen.md`, `docs/ui/betriebsmodi.md`, `docs/user-manual/Benutzer-Handbuch-Earnie.md`, `docs/einrichtung/betrieb.md`. They state: a reliable plan, no guarantee; start per grid area; prices with their status.
- Catalog values per D1 once the SNE-T-V is final. A change to `grid_fees.json` needs a matching release on both sides if the format changes.
- Backlog, Edibert backlog item and dev doc kept consistent. Release notes as a draft only.
- `version.py` stays untouched until approved.

## Meter timing

Research of 2026-11-07, details and sources in [`SNE-G-V-2027-Research.md`](../../backlog/SNE-G-V-2027-Research.md) section 3a.

- Fixed quarter hours at :00, :15, :30, :45 on the meter's own clock are explicit for Flanders. In Austria the ordinance speaks of a 15-minute market interval; the texts read do not state the alignment or a limit for the clock. Treat clock alignment as the working assumption, not as a confirmed rule.
- Germany allows 27 s against legal time, so a deviation of that order is a sensible case to plan for.
- Earnie's error from a clock offset is at most `step of import power x offset / 900 s`:

| Offset | Step 5 kW | Step 10 kW |
|---|---|---|
| 5 s | 0.03 kW | 0.06 kW |
| 27 s | 0.15 kW | 0.30 kW |
| 60 s | 0.33 kW | 0.67 kW |

This needs the full step right at the boundary of the quarter hour that sets the month's peak. So own measurement is good enough for 2.8, with the margin covering the rest. Earnie's counter window (P5) can be a similar size, so that gets fixed first.

Not used here, kept for later: the customer interface gives the meter's clock and import counter at 10 s on the types documented in Styria, so it could replace the assumption. The example telegram there has no running-average or peak register, unlike Flanders.

## Risks

| Risk | Effect | Handling |
|---|---|---|
| Clock offset to the meter | Earnie's peak differs from the bill, at most by the table in **Meter timing** | Field test in P5, margin, docs say the bill is what counts |
| No prices at release | Feature cannot be switched on | D1; the feature ships ready and stays inactive per grid area |
| Hourly load | SE peak too low, cap looks easier to hold than it is | D9: measure, label |
| Plan holds, meter does not | Short peaks inside a quarter hour, forecast errors | Margin, L4 report, docs; control inside the quarter hour is L4b |
| Penalty and solver gap | Worse energy plan or longer solves on every capped run | Sized by test in P3 |
| Cap costs more than it saves | User picks a cap too low | SE shows both; the proposal comes with the automatic budget in 2.+1 |
| Open rules | § 34 Abs. 1, billing month of the peak | Parameters stay in Edibert; research note re-checked in P0 and P7 |

## Done means

- A scenario with a capacity charge shows the monthly amount per result in the SE, and `sim_cost` and the study export are unchanged.
- With no cap configured, plans and regression goldens are unchanged.
- With a cap, the booked month peak stays at or under the cap in every month where the report names no slot.
- In Live the month peak survives a restart and resets at the month change, and a gap is visible.
- Unholdable slots are reported with a cause, and the docs no longer say "nicht modelliert".
- In observe mode Live plans and controls as without a cap, and the Monitor shows the interventions and the estimated saving on the capacity charge.
