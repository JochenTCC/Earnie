# Max-power dependent tariff: implementation plan (Version 2.8)

**Status:** plan (2026-11-07), nothing implemented. Branch `feat/max-power-tariff`, based on `main` at `b2275bbd`.
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
| Edibert | `v0.1.14` is pinned and has `capacity_charge_eur`, `capacity_ladder`, `charge_for_month`, `CapacityState`. `GridFee.capacity` holds the entries in effect. Default `include_status` is `verordnet` only. | `Edibert/src/edibert/capacity.py`, `gridfee.py:51` |
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

**P5a built 2026-11-07.** The sampler adds `grid_import_kw` with `grid_import_source` and the window (`grid_import_start`, `grid_import_end`) to each closed quarter hour. From the import counter it divides by the real time between the two reads, so the window starts up to one sample interval (30 s) late; interpolating to the boundaries waits for the field test. Without a counter, on a reset or with a window under 5 minutes, it is the mean of `max(grid_kw, 0)`. `grid_kw` is unchanged. `runtime_store/capacity_peak_store.py` keeps one entry per month in `capacity_peaks.json`; `main.py` feeds it after each closed quarter hour and logs a failure without stopping the cycle. A sample mean from fewer than 3 samples counts as a missing quarter hour. Nothing plans with the peak yet.

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

- `optimizer/import_cap_report.py`: from `s[t]` per slot, with a cause: inverter power, battery empty or reserve, flex deadline, load forecast.
- UI: state in `ui/truth_banner.py`; Cockpit shows month peak, cap, billed power and the amount so far from `capacity_ladder`, plus what the next kW costs this month.
- SE: slots and days per month where the cap did not hold.
- Set the proposal from D7 from the field test in P5 and a HouseSim run: forecast error plus measurement error.
- **Tests:** each cause, truth banner, AppTest.

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
