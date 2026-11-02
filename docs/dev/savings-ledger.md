# Savings ledger — realised savings from logged actuals

**Status:** design proposal, not implemented (2026-11-02). Language: English (docs/dev).
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

with `p_ref` = energy-weighted mean buy price of that SA-day. It is booked as its own column and reversed at the next day close (the next day's correction is computed from scratch against the new end SoC, so the series telescopes). Without it, a reserve built in the evening shows as a loss on day N and a gain on day N+1; on the dump the open-loop plan ends 2 kWh above the same-flex baseline, which is almost exactly the 0.77 € it looks more expensive.

The shadow battery is the existing baseline step `optimizer/sim_baseline.py::_simulate_single_hour_baseline` (`baseload_kw_override` path) fed with actuals instead of forecasts. No new battery model.

Multi-ESS: v1 aggregates house batteries with `aggregate_battery_params_for_load` (as the baseline does today). Powerstations and virtual reserves are not part of the shadow plant; the actual side includes whatever they did. This slightly favours Earnie when a powerstation covers load and is stated in the method note.

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
  "cost_with_eur": 2.539,
  "cost_without_eur": 2.871,
  "saving_eur": 0.332,
  "soc_actual_end_pct": 19.0,
  "soc_shadow_end_pct": 5.0,
  "soc_correction_eur": 0.743,
  "saving_adjusted_eur": 1.075,
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

- A slot counts when its `closed_interval` is present and `ist_power_source` is `mean` for pv, grid, battery and house. Missing slots are skipped on both sides (same slots, same prices), so partial days stay comparable; `coverage` is stored and days below a threshold (proposal: 0.8) are shown but not added to the lifetime total.
- Shadow SoC is **never** reset from the live SoC. It starts once (first ledger run) at the live SoC of that moment and then only follows the shadow rule. If the ledger state is missing or `savings_v` changes, a new chain starts and the UI shows the start date.
- Lifetime total = Σ `saving_adjusted_eur` over counted days. Shown together with its start date and the day count.
- **Backfill:** `optimization_history.jsonl` (and rotated files) already hold every `closed_interval` with prices; a one-off CLI (`python -m scripts.build_savings_ledger --since <date>`) can build the ledger retroactively. The dump's log reaches back to July.

Where it runs: in `main.py` after the cycle's `closed_interval` is written (one shadow step per cycle, O(1)); SA-day close when the first slot after SA₂ is closed. Failure is loud (logged warning, ledger row flagged), never a silent zero.

## 5. Chart 2 after the change

| Area | Today | Proposed |
|---|---|---|
| Grey (log) | **Ist bisher** from log; **Ersparnis bisher** = slot-0 plan differences (D1, D2) | **Ist bisher** unchanged; **Ersparnis bisher** = ledger slots of the current SA-day (`cost_without − cost_with`, cumulated), SoC correction shown as the last point or as a label |
| Neutral/green | **Ersparnis erwartet** = BL Ziel − optimized over the horizon (D2, D3) | keep, with exact-slot alignment (D2) and BL Ziel energy limited to what the optimizer plans (D3): either drop the profile fallback from the costed baseline or cost only the consumers with a non-zero optimizer target; the fallback may stay for SoC realism if its slots are excluded from € |
| Annotations | BL Ziel / Optimiert per SA-day, from the same series | same series, therefore corrected by the above |
| New KPI | — | Cockpit tile "Mit Earnie gespart: X € seit <date> (<n> Tage)" with a help text stating the counterfactual (§ 3) |

The method note (German, user docs) must say in one sentence what "ohne Earnie" means: *gleicher Verbrauch, gleiche PV, Batterie im Herstellermodus (Eigenverbrauch), gleiche Preise.*

## 6. Usage ping and server

Schema v3 adds to the existing v2 payload:

```json
{"v": 3, "...": "...", "savings_v": 1, "savings_eur": 184.2, "savings_days": 97}
```

- `savings_eur` = lifetime `saving_adjusted_eur` of counted days, rounded to 0.1 €; `savings_days` = counted days. Both from the ledger, latest-wins per install id on the server (as `points`).
- **Decision needed (privacy):** `usage-ping.md` § 2 excludes prices and costs from the payload. A lifetime euro aggregate is a new data category. It needs: an updated consent text and "Was wird gesendet?" preview, a note in `docs/einrichtung/betrieb.md` § Nutzungsstatistik, and a server-side schema bump (`earnie-server`, separate repo → tracker row).
- Server KPI: Σ `savings_eur` and median per install, by `savings_v`; histogram of `savings_eur / savings_days`. Marketing wording always carries the counterfactual and the method version; the figure is as fakeable as the points.

## 7. Flex re-timing (`savings_v: 2`, later)

v1 measures the battery benefit only, because the logged house load already contains the shifted flex energy. v2 re-times flex per SA-day:

- `flex_delivered_kwh[cid]` from the logged `flex_kw` per slot.
- Counterfactual shape = the matched-baseline profile of that consumer (`build_matched_flex_kw_per_hour` shape), scaled to the delivered energy; thermal consumers with no profile use their native window (filter: `native_start_hour`/`duration`; others: flat over the enable window).
- `house_without = baseload_actual + Σ flex_retimed`, shadow battery runs on that.

Same day energy, different timing — the Scenario Explorer's energy-parity principle. The plan-vs-actual reconciliation (`flex_planned_kwh` vs `flex_delivered_kwh`) is already in the v1 row and becomes the input for v2.

Open: EV sessions (deadline-bound; counterfactual = "charge immediately on plug-in" is the natural vendor default) and consumers whose Ist comes from `live_snapshot` without a per-consumer meter.

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

WP 1–2 are independent bug fixes and can ship on `release/2.7`. WP 3–5 are one feature; WP 6–7 wait for the privacy decision; WP 8 is optional.

## 9. Open decisions

1. `p_ref` for the SoC correction: day's energy-weighted mean buy price (proposal) vs. next day's first-hours price vs. flat tariff component.
2. Coverage threshold for counting a day (proposal 0.8) and how partial days appear in the UI.
3. Whether the shadow plant includes powerstations (v1: no).
4. Privacy: ship `savings_eur` in the ping at all; if yes, rounding granularity (0.1 € vs 1 €) and whether `savings_days` is needed.
5. Does D1's "Ersparnis bisher" disappear before the ledger exists (hide the trace), or stay with a warning label until WP 5 lands? Proposal: hide; a wrong number is worse than none.
