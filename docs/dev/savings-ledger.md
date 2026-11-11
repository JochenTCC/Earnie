# Savings ledger — realised savings from logged actuals

**Status:** implemented (v1), 2026-11-04. Flex re-timing (`savings_v: 2`, § 7) and the usage ping (§ 6) are open. Language: English (docs/dev).
**Decided 2026-11-11 (Ledger P9a):** the definition of `savings_v: 2` (§ 7, § 9 items 7–13); planned for 2.8, steps in [`savings-ledger-v2-plan.md`](savings-ledger-v2-plan.md). Not implemented.
**Fixed 2026-11-02:** D2 (Ledger P1) and D3 (Ledger P2); D1 is replaced by the ledger.
**Implemented 2026-11-02:** slot engine and day close `runtime_store/savings_ledger.py` (Ledger P3, P4), files `runtime_store/savings_ledger_store.py` (P4), daemon hook `runtime_store/savings_ledger_daemon.py` (P5), backfill CLI `scripts/build_savings_ledger.py` (P6).
**Decision 2026-11-02 (Ledger P0):** `p_ref`, partial days and powerstations are decided (§ 3, § 4, § 9).
**Superseded 2026-11-05 (Account view P2):** Chart 2 is an account view now ([`chart2-account-view.md`](chart2-account-view.md)); the "Ersparnis bisher" line and the per-day annotations described below are gone. The ledger supplies the slot series left of *Jetzt*.

**Implemented 2026-11-04 (Ledger P7):** Chart 2 reads "Ersparnis bisher" from the ledger (`ui/chart_ledger_savings.py`) and is shown again; `chart2_enabled()` and `EARNIE_UI_CHART2` are gone. On a running day BL Ziel, Optimiert and "Ersparnis erwartet" cover the rest of the day; an elapsed day shows only its ledger row. The SoC correction is a label, as the change against the previous day (`saving_adjusted − saving`).

**Implemented 2026-11-04 (Account view P1):** slot series of closed SA-days in `savings_ledger_slots.jsonl` (§ 4).

**Implemented 2026-11-07 (Ledger P11):** Chart 1's "SoC BL Ziel" runs on the shadow chain and the plan's baselines start from it (§ 5).

**Implemented 2026-11-04 (Ledger P8):** Monitor tile (`ui/ledger_kpi.py`, § 5), amounts without a sign (`ui/saving_text.py`, § 5), energy-counter slots count (§ 4, § 9 item 6).

**Decision 2026-11-02:** not in 2.7 — Chart 2 is hidden for the 2.7 release (`ui/live_mode.py::chart2_enabled()`, shown only with `EARNIE_UI_CHART2=1`) (known limitation in the release notes); the corrected chart ships with 2.8 (`backlog/Backlog.md` Version 2.7 / 2.8).
**Trigger:** debug dump `debug_dump_20261102_062129` ("Kumulierte Kosten - Anzeige unplausibel"), analysed on `release/2.7` (2.7.0-beta.3).
**Related:** [`../ui/charts.md`](../ui/charts.md) § Chart 2, [`done/ui-sunset2sunset.md`](done/ui-sunset2sunset.md), [`done/planning-horizon-sunset.md`](done/planning-horizon-sunset.md), [`../workflow/usage-ping.md`](../workflow/usage-ping.md), [`../workflow/earnie-points.md`](../workflow/earnie-points.md), backlog item "Simple Savings KPI as additional payload of the UsagePing" (`backlog/Backlog.md`, Version 2.+1).

---

## 1. Problem

Chart 2 ("Kumulierte Kosten & Verbrauch") reports **Ersparnis bisher** and **Ersparnis erwartet** from planning data. Three independent defects make the numbers wrong, independent of what the optimizer does. All three were verified on the dump above.

| # | Defect | Where | Effect in the dump |
|---|--------|-------|--------------------|
| D1 | **Baseline restarts from the live SoC every cycle.** `calculate_optimization_savings` runs the optimized open-loop plan and both baselines from `current_soc` (`main.py` → `optimizer/sim_costs.py::_run_savings_horizons`). **Ersparnis bisher** sums slot 0 of each cycle's `hourly_savings_euro`. In slot 0 the baseline discharges whatever the optimizer is holding above `min_soc`; the optimizer's cost of building that reserve is counted, its later use is credited to the baseline (which discharges in the same slot). | `runtime_store/history_timeline.py::_slot_plan_increments_from_snapshots`, `ui/chart_context.py::_overlay_history_plan_costs` | SA-day 2026-11-01: planned slot-0 cost optimized 2.08 €, matched baseline 0.003 €. The battery did a correct night→morning arbitrage (35 ct → 48 ct, 2 kWh) and the curve shows it as a pure loss. |
| D2 | **Hourly assumption on a quarter-hour matrix.** `align_hourly_increments_to_display_slots` keys values by the row's slot but looks them up by `normalize_hour_slot`, so only the `:00` row of every hour matches and its value is spread over four slots. The history overlay picks one snapshot per hour and spreads its slot-0 value over four slots. | `ui/chart_context.py:493`, `runtime_store/history_timeline.py:200` | Forecast part: optimized 5.46 € (snapshot) vs 1.06 € (chart); BL Ziel 11.46 € vs 2.56 €. History: −8.87 € (sum of cycles) vs −2.08 € (chart). |
| D3 | **BL Ziel carries energy the optimizer never plans.** `resolve_matched_baseline_horizon_targets` gives consumers with `daily_target_source=config` and target 0 their profile energy so the baseline battery sees flex competition. That energy is costed, the optimizer plans 0 kWh for it. | `optimizer/targets.py:321` | Geschirrspüler 2.4 + Trockner 5.0 + Waschmaschine 4.0 = 11.4 kWh in BL Ziel, 0 kWh optimized → about 4.5 € of the 6.0 € "Ersparnis erwartet". |

Not a defect, but worth stating: both numbers are **plan vs. plan**. Nothing in Chart 2 compares what actually happened against a counterfactual.

**Scenario Explorer is not affected.** Its reference ("ohne Optimierung") is closed-form without battery (`simulation/reference_costs.py`), the optimized run is one continuous SoC chain, flex energy parity is enforced per window (`simulation/plausibility.py`), and its chart slots are quarter-hourly with exact-slot alignment (`savings_view_for_chart`). The per-window snapshot view runs the baselines once per window from the window start SoC, which is fair inside the window.

## 2. Goal

1. Chart 2 shows numbers that are internally consistent and correctly scaled (short term: fix D2, D3; D1 is replaced, not fixed).
2. A **realised savings** figure per SA-day and cumulated over the installation's lifetime: *"What did Earnie save me, with the same consumption, compared with the plant running without it?"* Computed from logged actuals, not from plans.
3. A plan-vs-actual energy reconciliation per SA-day (planned flex energy vs delivered) as a by-product.
4. The lifetime figure becomes a usage-ping field (schema v3) and a server KPI.

Non-goals: valuing outage protection, comfort, or wear; a legally exact bill reconstruction (grid fees, monthly fees are out; the ledger prices energy at the per-slot `k_act` / `k_push_act` the daemon used).

## 3. Counterfactual definition ("ohne Earnie")

One definition, versioned as `savings_v`. Any later change starts a new version; old ledger rows keep theirs.

**`savings_v: 1`**

| Aspect | With Earnie (actual) | Without Earnie (shadow plant) |
|---|---|---|
| House load | logged `closed_interval.house_kw` | identical |
| PV | logged `closed_interval.pv_kw` | identical |
| Battery | logged `closed_interval.battery_kw`, `soc_start/end_percent` | **shadow battery**: vendor default = charge PV surplus, discharge on deficit, bounded by `min_soc`/`max_soc`, `max_power_kw`, `efficiency`, `standby_power_kw`; **one continuous SoC chain** across cycles and days |
| Grid | logged `grid_kw` | `house − pv + shadow_battery` |
| Prices | `market_price_cent` (buy), `k_push_act` (sell) of the cycle | identical |
| Flex timing | as logged | v1: as logged (see § 7 for v2 flex re-timing) |

**`savings_v: 2`** (implemented behind `SAVINGS_V = 1` until Ledger P9d; [`savings-ledger-v2-plan.md`](savings-ledger-v2-plan.md) § 4.1)

| Aspect | With Earnie (actual) | Without Earnie (shadow plant) |
|---|---|---|
| House load | as v1 | `house − Σ flex_delivered + Σ flex_retimed` per slot; `flex_retimed` = each consumer's delivered energy of the SA-day in its unshifted timing (§ 7) |
| PV, prices | as v1 | identical |
| Battery | as v1 | as v1, the chain SoC of the day start; **no battery**: `grid = load − pv`, no SoC correction |
| Computed | per slot | per SA-day when it closes (day replay); the open day as v1 |

Per closed quarter-hour slot:

```text
cost_with    = max(grid_kwh, 0) · k_act − max(−grid_kwh, 0) · k_push
cost_without = max(grid_kwh_shadow, 0) · k_act − max(−grid_kwh_shadow, 0) · k_push
saving_slot  = cost_without − cost_with
```

**SoC value correction.** At every SA-day close:

```text
soc_correction = (soc_actual_end − soc_shadow_end) / 100 · capacity_kwh · efficiency · p_ref
```

with `p_ref` = energy-weighted mean buy price of that SA-day (Σ import kWh · `market_price_cent` / Σ import kWh over the counted slots). A day without grid import has no weighted mean; it takes the time mean of the day's buy price instead, as an explicit rule recorded in the row (`p_ref_basis: "import_weighted" | "time_mean"`), not as a silent fallback. *(Decided 2026-11-02, Ledger P0.)*

The correction is booked as its own column and **reversed with the same euro amount** at the next day close:

```text
saving_adjusted_N = saving_N + soc_correction_N − soc_correction_(N−1)
```

The lifetime sum therefore telescopes to Σ `saving_eur` + the correction of the latest closed day (the first day of a chain has no predecessor term, because the shadow chain starts at the actual SoC). `p_ref` only moves amounts between days; it never changes the long-run total. On 43 days of the maintainer's plant the candidate prices (import-weighted mean, time mean, night hours of the next day) differ by about 1 ct in the median. Without the correction, a reserve built in the evening shows as a loss on day N and a gain on day N+1; on the dump the open-loop plan ends 2 kWh above the same-flex baseline, which is almost exactly the 0.77 € it looks more expensive.

The shadow battery is the existing baseline battery step fed with actuals instead of forecasts: `optimizer/battery.py::vendor_mode_step`, which `optimizer/sim_baseline.py::_simulate_single_hour_baseline` also calls. No new battery model. The shadow load is the logged `house_kw` plus the battery's `standby_power_kw`, as in the baseline.

Multi-ESS: v1 aggregates house batteries with `aggregate_battery_params_for_load` (as the baseline does today).

**Powerstations and virtual reserves are not part of the shadow plant** *(decided 2026-11-02, Ledger P0)*. The logged `house_kw` is the balance `pv + grid + battery` (`integrations/ehal_live.py::read_live_power_kw`); on 43 days of the maintainer's plant the residual `house − (pv + grid + battery)` is 0.00 kWh. Load a powerstation supplies from its own storage therefore appears on neither side, and its charging sits in the house load with its logged timing on both sides. The comparison stays neutral; the method note says that powerstation supply is not valued and their charging counts at its actual time.

## 4. Ledger

`runtime_store/savings_ledger.jsonl`, one row per **closed SA-day** (SA₁→SA₂ as the UI books it), append-only, plus `savings_ledger_state.json` for the open day and the shadow SoC:

```json
{
  "savings_v": 1,
  "day_start": "2026-11-01T07:04:38+01:00",
  "day_end": "2026-11-02T07:06:08+01:00",
  "slots_total": 96,
  "slots_present": 93,
  "coverage": 0.969,
  "incomplete": false,
  "cost_with_eur": 2.539,
  "cost_without_eur": 2.871,
  "saving_eur": 0.332,
  "soc_actual_end_pct": 19.0,
  "soc_shadow_end_pct": 5.0,
  "p_ref_cent": 31.0,
  "p_ref_basis": "import_weighted",
  "soc_correction_eur": 0.743,
  "soc_correction_prev_eur": 0.512,
  "saving_adjusted_eur": 0.563,
  "import_kwh_with": 6.21,
  "import_kwh_without": 7.02,
  "export_kwh_with": 0.0,
  "export_kwh_without": 0.0,
  "flex_planned_kwh": {"waermepumpe": 4.19, "pool_swimspa": 0.7},
  "flex_delivered_kwh": {"waermepumpe": 3.86, "pool_swimspa": 0.7},
  "app_version": "2.7.0-beta.3"
}
```

Rules:

- A slot counts when its `closed_interval` is present, has at least `MIN_SAMPLE_COUNT_FOR_MEAN` samples (the bar "Ist bisher" uses) and `ist_power_source` is `mean` or `counter` for pv and grid and `mean` for battery and house. With a counter on pv or grid the ledger books the house load as `pv_kw + grid_kw + battery_kw` instead of the logged `house_kw`, in the shadow plant and in the slot file's `house_kwh` (§ 9 item 6). A slot whose plant powers all read exactly 0 (meter outage) and a slot without its own log entry or `k_push_act` (no price) are skipped too. Missing slots are skipped on both sides (same slots, same prices), so a gap only understates the saving, it never distorts it. `coverage` and the skipped slots per reason (`slots_skipped`) are stored per row. The day close also counts the grid slots of the day that were never booked: `before_chain` before the chain start, `no_cycle` for a quarter hour without a completed cycle. So `slots_present` plus the sum of `slots_skipped` equals `slots_total` on every closed day.
- **Every closed day counts in the lifetime total**, whatever its coverage *(decided 2026-11-02, Ledger P0)*. Dropping a day would also drop its SoC corrections and break the telescoping sum of § 3. Days with `coverage < 0.8` are flagged `"incomplete": true` and shown as "unvollständig" in the UI. On 43 days of the maintainer's plant 37 reach 0.8; the others are restart or gap days.
- Shadow SoC is **never** reset from the live SoC. It starts once (first ledger run) at the live SoC of that moment and then only follows the shadow rule. If the ledger state is missing or `savings_v` changes, a new chain starts and the UI shows the start date. An unreadable state file is moved aside (`savings_ledger_state.json.broken-<timestamp>`) with a warning; the new chain's first row names the reason (`chain_start_reason`: `first_run`, `savings_v_changed`, `state_unreadable`, `backfill`).
- A day with no counted slot (or no actual SoC) carries the previous day's SoC correction unchanged (`p_ref_basis: "carried"`), so its correction terms cancel and the telescoping sum stays intact. Calendar days without any closed slot get no row.
- Lifetime total = Σ `saving_adjusted_eur` over all closed days of the chain. Shown together with its start date, the day count and the number of incomplete days.
- **Backfill:** `optimization_history.jsonl` (and rotated files) already hold every `closed_interval` with prices; a one-off CLI (`python -m scripts.build_savings_ledger --since <date>`) can build the ledger retroactively. The dump's log reaches back to July. It replays every closed slot from `--since` as one chain (`chain_start_reason: backfill`), writes the rows and the state with the open day, and keeps the newest entry's prices as `pending_slot` so the daemon continues the chain. An existing ledger or state file is only replaced with `--rebuild` (no merge with live rows); `--dry-run` prints the day table only. The daemon must be stopped while it writes (it holds the state in memory); the CLI refuses when it finds the local daemon running.

**v2 row fields** (in addition to the v1 row): `flex_retimed_kwh` (per consumer, equal to `flex_delivered_kwh` by construction), `flex_timing` (per consumer: `profile`, `native_window`, `enable_window`, `logged`, `logged_no_meter`, `no_energy`), `flex_logged_reasons` (per `logged` consumer: `no_shape_no_window`, `exceeds_eligible_slots`, `not_configured`, `ev_rule_missing`, `profile_read_error`), `saving_logged_timing_eur` (the day's saving with the logged timing from the same start SoC). Without battery: `p_ref_basis: "no_battery"`, corrections 0, `soc_shadow_end_pct` and `p_ref_cent` `null`. The state holds `shadow_soc_day_start` (v2 only). The slot file of a v2 day holds the replay's `cost_without_eur` per slot.

**Slot file.** `savings_ledger_slots.jsonl` holds the slot series of closed days for the account view ([`chart2-account-view.md`](chart2-account-view.md) § 4), one JSON line per closed SA-day, append-only:

```json
{
  "savings_v": 1,
  "chain_start": "2026-09-16T00:00:00+02:00",
  "day_start": "2026-11-01T07:04:38+01:00",
  "day_end": "2026-11-02T07:06:08+01:00",
  "slots": [
    {"slot_start": "2026-11-01T07:15:00+01:00", "counted": true, "skip_reason": null, "cost_with_eur": 0.0312, "cost_without_eur": 0.0287, "house_kwh": 0.11}
  ]
}
```

- Values are unrounded, so the slots of a day sum to its ledger row (`cost_with_eur`, `cost_without_eur` after the row's rounding; number of counted slots = `slots_present`). A skipped slot is zero, also in `house_kwh`. `house_kwh` is the logged `house_kw`, without the shadow battery's standby.
- The daemon writes the line right after the day's row, from the same slot rows the state holds. A failed slot write does not stop the chain, since raising would close the day a second time on the next slot: it logs a warning that names the repair, and the day stays without slots.
- Readers use `savings_ledger_store.closed_day_slots(rows)`, which raises `SlotFileError` when the file is missing or broken, a day is missing or repeated, or the slots do not add up to the row. There is no fallback to the log.
- **Backfill for existing ledgers:** `python -m scripts.build_savings_ledger --since <date> --slots-only` replays the log and writes only the slot file, replacing an existing one. It refuses unless the replay adds up to every ledger row and closes no other day, so `--since` must be the date the chain was built from. A chain the daemon started itself, or a ledger with several chains, cannot be reproduced from one replay; that fails loud, and only `--rebuild` then gives a slot file. `--rebuild` always writes the slot file too.
- **Upgrade:** the slots of a day still open when the version changes have no `house_kwh`, so that one day closes without slots and with the warning. Run the `--slots-only` backfill after that first close.

Where it runs: in `main.py` after the cycle's `closed_interval` is written (one shadow step per cycle, O(1)); SA-day close when the first slot after SA₂ is closed. The prices of a slot come from the cycle that ran in it; the hook keeps them in the state until the slot is closed one cycle later, so the log is never re-read. Failure is loud (logged warning, the slot booked as skipped `error`, counted in the row's `errors`), never a silent zero.

## 5. Chart 2 after the change

| Area | Today | Proposed |
|---|---|---|
| Grey (log) | **Ist bisher** from log; **Ersparnis bisher** = slot-0 plan differences (D1, D2) | **Ist bisher** unchanged; **Ersparnis bisher** = ledger slots of the current SA-day (`cost_without − cost_with`, cumulated), SoC correction shown as the last point or as a label |
| Neutral/green | **Ersparnis erwartet** = BL Ziel − optimized over the horizon (D2, D3) | keep, with exact-slot alignment (D2) and BL Ziel energy limited to what the optimizer plans (D3): either drop the profile fallback from the costed baseline or cost only the consumers with a non-zero optimizer target; the fallback may stay for SoC realism if its slots are excluded from € |
| Annotations | BL Ziel / Optimiert per SA-day, from the same series | same series, therefore corrected by the above |
| New KPI | — | Cockpit tile "Mit Earnie gespart: X € seit <date> (<n> Tage)" with a help text stating the counterfactual (§ 3) |

The method note (German, user docs) must say in one sentence what "ohne Earnie" means: *gleicher Verbrauch, gleiche PV, Batterie im Herstellermodus (Eigenverbrauch), gleiche Preise.*

**Tile (Ledger P8).** The main figure is the lifetime total of § 4, closed days of the current chain only: it stays stable through the day and is the value the ping would send (§ 6). "Heute bisher" shows the open day apart, because its SoC correction is provisional until the day closes. The main figure reads the ledger files on every fragment run; the today line takes `saving_euro` and `soc_correction_euro` from `savings_view["ledger_savings"]`, the dict Chart 2 draws, so both show the same values of the same moment. These fields come from the state alone and do not depend on the chart window, so the line stays when the user pages back. There is no today line without a display bundle, without a booked slot of the open day (the fields are `None`, and Chart 2 has no "Bisher" either), or once `open_day_end` has passed. Without a result the tile names the reason and shows no amount.

**Chart 2 labels (Ledger P8).** "Ergebnis" is reserved for an elapsed day with a ledger figure. A running day shows "Bisher" and "Erwartet". A day without actual values is plan only and reads "Plan", as does the Scenario Explorer.

**Chart 1 and the plan (Ledger P11).** D1 is gone from Chart 1 as well. `main.py` plans before `on_cycle` books the slot the cycle just closed, so `savings_ledger_daemon.planning_shadow_soc` steps the chain over that slot without saving anything, and all baselines of `calculate_optimization_savings` start there (`baseline_initial_soc`); the optimized plan keeps the live SoC. The "SoC BL Ziel" line is one trace: the open day's `shadow_soc_end` per slot left of *Jetzt*, the plan's baseline right of it. Closed days are not drawn, as paging back already shows no BL line. Without a chain (first start, unreadable state) all runs start at the live SoC, `baseline_start_source` says `live_soc`, and Chart 1 draws no line and shows a hint; Chart 2 keeps its plan figures, which then compare two runs from the same start.

Plan and baseline now start from different SoC, so the plan's cost gap holds the value of that start energy. `soc_correction_increments_euro` applies the formula of § 3 to the plan, with `p_ref` from the plan's own import: its sum is the value of the SoC gap at the end minus its value at the start. The start term is needed: the ledger's open-day correction has already credited that energy, and a plan that just uses it up saves nothing. `savings_matched_euro` and `savings_euro` include the correction; the slot series do not, so Chart 2 keeps the rule that no correction sits in a gap and shows it as the label "SoC am Ende", summed from *Jetzt* to the window end.

**Amounts without a sign** *(decided 2026-11-04)*. Savings and SoC corrections show the absolute amount and say what it means in words: "gespart" / "mehr ausgegeben", "gutgeschrieben" / "abgezogen" (`ui/saving_text.py`). A result that rounds to 0.00 € counts as saved. Only the cumulated line keeps negative values, because it needs the axis. The rule also covers the account view and the Scenario Explorer savings (headline metric, `Ersparnis vs. Standard-Regeln`, `Ersparnis zur Stufe davor`); differences such as `Δ vs Referenz`, the end-SoC term of the ladder table and the device page delta keep their sign. **Decimal separator** *(decided 2026-11-05)*: euro and cent amounts follow the viewer's browser language (`ui/number_format.py` on top of Edibert's `edibert.i18n.numbers`): the supported language (`en` / `de`) the `Accept-Language` header prefers most decides, `.` for `en`, `,` for `de`; `de` when the header is missing or names neither, since the UI is German. Every chart sets Plotly `layout.separators` the same way through `localized_figure`. kWh, kW and % follow as well; numeric `st.dataframe` columns use `localized_number_column` and take the browser's locale.

## 6. Usage ping and server

Schema v3 adds to the existing v2 payload:

```json
{"v": 3, "...": "...", "savings_v": 1, "savings_eur": 184.2, "savings_days": 97}
```

- `savings_eur` = lifetime `saving_adjusted_eur` of all closed days of the chain, rounded to 0.1 €; `savings_days` = closed days. Both from the ledger, latest-wins per install id on the server (as `points`).
- **Decision needed (privacy):** `usage-ping.md` § 2 excludes prices and costs from the payload. A lifetime euro aggregate is a new data category. It needs: an updated consent text and "Was wird gesendet?" preview, a note in `docs/einrichtung/betrieb.md` § Nutzungsstatistik, and a server-side schema bump (`earnie-server`, separate repo → tracker row).
- Server KPI: Σ `savings_eur` and median per install, by `savings_v`; histogram of `savings_eur / savings_days`. Marketing wording always carries the counterfactual and the method version; the figure is as fakeable as the points.

## 7. Flex re-timing (`savings_v: 2`, decided 2026-11-11, not implemented)

v1 measures the battery benefit only, because the logged house load already contains the shifted flex energy. v2 changes the load of the shadow plant per SA-day. Steps and data format: [`savings-ledger-v2-plan.md`](savings-ledger-v2-plan.md).

```text
house_without   = baseload_actual + Σ flex_retimed        (per slot)
baseload_actual = house_actual − Σ flex_delivered
```

- **Reference timing** *(§ 9 item 7)*: the consumer's unshifted timing, which is L1 of the Scenario Explorer ([`rule-based-reference.md`](rule-based-reference.md)): its profile shape scaled to the energy delivered in the SA-day and capped at nominal power (`optimizer/sim_baseline.py::build_shaped_flex_kw_per_slot`); thermal consumers with no profile use their native window (filter: `native_start_hour`/`duration`; others: flat over the enable window). Not the standard rules (L2): the tile therefore reads higher than the SE headline L2 − L3, and the method note says so.
- **Day replay**: the shape needs the day's delivered energy and may place energy earlier than Earnie did, so v2 is computed when the SA-day closes, from the slot rows of the day, over the counted slots only. Same day energy on both sides, whatever the coverage — the Scenario Explorer's energy-parity principle. The row, the slot file and the chain SoC come from the replay.
- **Open day** *(§ 9 item 8)*: as in v1, the shadow runs on the logged timing (battery only) and is replaced by the replay at the day close. "Heute bisher" says that moved consumers are added then.
- **No house battery** *(§ 9 item 9)*: the ledger is active; the shadow plant is `grid = load − pv`, without SoC correction.
- **Flex part** *(§ 9 item 10)*: the row also stores the day's saving with the logged timing from the same start SoC (`saving_logged_timing_eur`); the tile shows one figure at first. The split is approximate, since the two runs end at different SoC.
- **EV** *(§ 9 item 11)*: the energy delivered in the SA-day, charged at nominal power from the first plugged-in slot of that day. A session across the day boundary is re-timed per SA-day (energy of day N+1 starts at the day start), which understates slightly.
- **Consumer without its own meter** *(§ 9 item 12)*: keeps its logged timing and is named in the row (`flex_timing`). No estimate from setpoints. The same holds, per consumer and day, for energy that cannot be placed (no shape and no window, or more than the eligible slots hold) and for an EV day without plug state.
- **Network backends** *(§ 9 item 13)*: today only Loxone logs per-consumer power. Ledger P9e adds it on HA for consumers with a bound power or run-state entity; on OpenEMS every consumer keeps its logged timing, so the tile stays battery only there.
- **Heating rod beside a fuel source**: 0 kWh in the shadow plant; the heat it delivered is bought as fuel there, priced like the MILP's fuel credit (`fuel_saved_eur` in the row). Beside an electric heat source the rod is an ordinary consumer.

The plan-vs-actual reconciliation (`flex_planned_kwh` vs `flex_delivered_kwh`) is already in the v1 row and is the input for v2.

## 8. Work packages

| WP | Content | Size |
|---|---|---|
| 1 | D2: exact-slot alignment in `align_hourly_increments_to_display_slots` and `_slot_plan_increments_from_snapshots` (sum the four cycles of an hour, or map per slot); test with a quarter-hour matrix asserting Σ chart = Σ snapshot | S |
| 2 | D3: BL Ziel € without profile-fallback energy; `energy_comparison` shows it as its own column if the fallback stays for SoC | S |
| 3 | Ledger core: shadow step per cycle, SA-day close, SoC correction, state + jsonl, loud failure; unit tests with a synthetic 2-day log | M |
| 4 | Backfill CLI from `optimization_history.jsonl`; run on the home plant and compare with the dump day by hand | S |
| 5 | Chart 2 grey zone + cockpit KPI from the ledger; `charts.md` + user manual method note | M |
| 6 | Ping v3 (client contract, consent text, preview) — after the privacy decision | S |
| 7 | `earnie-server` receiver v3 + KPI panel — other repo, tracker row | S (there) |
| 8 | `savings_v: 2` flex re-timing | M |

WP 1–2 are independent bug fixes and can ship on `release/2.7`. WP 3–5 are one feature; WP 6–7 wait for the privacy decision; WP 8 is planned for 2.8 since 2026-11-11 ([`savings-ledger-v2-plan.md`](savings-ledger-v2-plan.md)).

**Backlog phases:** `backlog/Backlog.md` Version 2.8 splits these into epic **Ledger** P0–P11, one chat session each: P0 decisions (§ 9 items 1–3, done 2026-11-02), P1 = WP 1, P2 = WP 2, P3–P5 = WP 3 (slot engine, day close + files, daemon hook), P6 = WP 4, P7–P8 = WP 5 (chart, cockpit KPI), P9–P10 = WP 8, P11 = Chart 1 baseline from the shadow chain (no WP, found later). WP 6–7 stay under Version 2.+1 "Simple Savings KPI".

## 9. Open decisions

1. ~~`p_ref`~~ **Decided 2026-11-02 (Ledger P0):** energy-weighted mean buy price of the SA-day; time mean on days without import (§ 3).
2. ~~Coverage threshold~~ **Decided 2026-11-02 (Ledger P0):** every closed day counts; `coverage < 0.8` only flags the day as incomplete in the UI (§ 4).
3. ~~Powerstations~~ **Decided 2026-11-02 (Ledger P0):** not part of the shadow plant in v1; neutral because `house_kw` is the pv + grid + battery balance (§ 3).
4. Privacy: ship `savings_eur` in the ping at all; if yes, rounding granularity (0.1 € vs 1 €) and whether `savings_days` is needed.
5. Does D1's "Ersparnis bisher" disappear before the ledger exists (hide the trace), or stay with a warning label until WP 5 lands? Proposal: hide; a wrong number is worse than none.
6. ~~Energy counters~~ **Decided 2026-11-04 (Ledger P8):** with the plant energy counters configured (Loxone and HA), pv and grid of a slot come from the counters (`ist_power_source` = `counter`) while battery and house stay means, so `house = pv + grid + battery` no longer holds exactly. Booking the logged `house_kw` would give the shadow plant another load than the real one and show a saving that does not exist. Counter slots therefore count with the house load from the balance (§ 4). All-mean slots are unchanged to the cent, so this stays `savings_v: 1` and no chain restarts. The result only differs on plants with counters, whose slots were all skipped before; 2.8 is not released, so no released ledger changes. A ledger built before this change does not replay with `--slots-only` if it holds counter slots (the CLI refuses); `--rebuild` then applies.
7. **Decided 2026-11-11 (Ledger P9a):** `savings_v: 2` re-times flex to the unshifted timing (L1), not to the standard rules (L2); the day replay takes the timing from one function, so L2 can replace it in a later version (§ 7).
8. **Decided 2026-11-11 (Ledger P9a):** the open day shows the battery part only; the flex part is added at the day close (§ 7).
9. **Decided 2026-11-11 (Ledger P9a):** with v2 the ledger runs without a house battery too (§ 7).
10. **Decided 2026-11-11 (Ledger P9a):** the row stores the saving with the logged timing beside the total; the tile shows one figure at first (§ 7).
11. **Decided 2026-11-11 (Ledger P9a):** an EV is re-timed per SA-day from plug-in, not per session across days (§ 7).
12. **Decided 2026-11-11 (Ledger P9a):** a consumer without its own meter keeps its logged timing and is named in the row (§ 7).
13. **Decided 2026-11-11 (Ledger P9a):** v2 in 2.8 includes per-consumer power in the slot log on HA (Ledger P9e); OpenEMS is left out (§ 7).
