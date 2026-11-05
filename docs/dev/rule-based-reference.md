# Rule-based reference — Earnie vs. standard rules (Scenario Explorer)

**Status:** design 2026-11-03, method decisions O1–O5 taken 2026-11-05 (§ 7), not implemented. Backlog: epic **RuleRef** and item **SE forecast mode** in `backlog/Backlog.md`.

**Related:** [`savings-ledger.md`](savings-ledger.md) (live counterfactual, `savings_v`), [`../workflow/earnie-points.md`](../workflow/earnie-points.md), `optimizer/sim_baseline.py`, `simulation/reference_costs.py`.

## 1. Problem

The Scenario Explorer (SE) compares every optimized run with a reference "Referenz (…) — ohne Optimierung" (`simulation/reference_costs.py::compute_historical_reference_costs`). That reference is closed-form: `_hour_cost_parts_without_optimization` (`simulation/anchor_step.py`) books `load − PV` per slot. **No battery, no flex control.**

Any real plant with a battery runs at least the inverter's self-consumption mode. So the SE saving credits Earnie with the whole battery benefit, plus everything a free rule (evcc PV charging, SG-Ready lock, "cheapest hours") would get. That makes the reference a straw man:

- Marketing: the "simple rules get you 80 %" (Pareto) argument cannot be answered.
- Upcoming studies (Earnie Points strategy, subscription prices) need the value **Earnie adds on top of what the customer already gets for free**. With today's reference that value is overstated.

The live side is already better: the matched baseline (`optimizer/sim_baseline.py::simulate_matched_baseline_horizon`) and the savings ledger (`savings_v: 1`) run the battery in vendor mode (`optimizer/battery.py::vendor_mode_step`). The SE does not.

## 2. Goal

A reference ladder in the SE. Each step adds one thing; the delta between two steps is attributable to that thing.

| Step | Name (UI, German) | Battery | Flex consumers | Delta belongs to |
|---|---|---|---|---|
| L0 | Ohne Steuerung | none | historical timing | — |
| L1 | Wechselrichter-Eigenverbrauch | `vendor_mode_step` | historical timing | hardware |
| L2 | Standard-Regeln | `vendor_mode_step` | local rules (§ 4) | free rules |
| L3 | Earnie | MILP | MILP | **Earnie** |

- **L2 replaces the current reference as the headline** ("Ersparnis" in the SE = L2 − L3).
- L0 is today's reference and stays as a ladder step (cheap, keeps the old figure comparable).
- KPIs: Earnie value `L2 − L3`; rule share of the total saving `(L0 − L2) / (L0 − L3)`. The second one answers the Pareto argument directly.
- Smaller savings factors are accepted; the goal is a defensible figure, not a large one.

## 3. Fairness requirements (all steps)

1. **Same energy.** Per window and per flex consumer, L1 and L2 deliver exactly the energy that L3 delivers (the same `consumer_daily_targets_kwh` / horizon targets the optimized run uses). Checked by the same `simulation/plausibility.py::validate_window_consumption` as the optimized run; a step that cannot reach its target in the eligible window fails loud with the missing kWh (`no-implicit-fallbacks.mdc`), no silent clipping. **Exception, heating rod:** it has no target, only an upper bound, and the MILP decides how much heat it replaces (`optimizer/targets.py::resolve_heating_rod_horizon_kwh`). In L1 and L2 it runs 0 kWh and the parent heat source delivers the heat (O4). L2 − L3 is therefore somewhat overstated for houses with a rod; the study export flags those scenarios.
2. **Same windows and constraints.** Same charging windows (`charging_contexts`, `consumer_charging_eligible_indices`), same nominal / min power, `min_on_quarterhours`.
3. **One continuous SoC chain** over the whole SE period, never reset per anchor (lesson D1 in `savings-ledger.md`). End-of-period SoC difference to L3 is valued like the ledger's SoC correction.
4. **Same prices and fees.** End-customer price per slot incl. time-variable grid fee, same feed-in settings (`_reference_feed_in_settings`).
5. **Information parity.** Rules see measured values in real time (surplus at the meter) and the day-ahead prices once published — that is what real products see. Earnie in the SE plans with perfect foresight of PV, load and prices (O1, § 7), so L2 − L3 from a plain SE run is an **upper bound**. Studies report it as a range together with the **SE forecast mode** (separate backlog item, required before final study prices); the ladder itself does not depend on that mode.
6. **Rule parameters fixed up front**, plus a sensitivity run (§ 4.5) that reports the best parameter set in hindsight. Being generous to the rules is the point.

## 4. L2 rule set

Each rule is local: it knows its own consumer, the meter, and the price. It knows nothing about other consumers' plans or the battery SoC. Every rule is named after the product behaviour it imitates, so the reference is "evcc + SG-Ready + HA cheapest hours", not an invented strategy.

### 4.1 Mechanism: deferral queue on top of the matched profile

Starting point per consumer is the matched-baseline profile (`build_matched_flex_kw_per_hour`: historical shape scaled to the target, zero outside the eligible window). SE matrices carry no `expected_flex_kw` today, so that function spreads every target flat over the eligible slots; the SE reference must supply the shape itself (O4):

- **Shape source:** `logged_day`: the consumer's `cons_data` column. `profile_spec`: `data/consumption_profiles.py::modeled_consumer_kw_at_datetime`, the source of the L0 load. Scaled to the target and capped at `nominal_power_kw`; energy cut by the cap moves to the next eligible slots with headroom.
- **Target > 0 but no shape in the eligible window:** nominal power from the start of the eligible window until the target is reached ("switch on and run"), counted per consumer in the step's meta. Not spread flat.
- **Consumer list:** the scenario's flex consumers. `build_matched_flex_kw_per_hour` and `_simulate_single_hour_baseline` read `config.get_flexible_consumers` (the live scenario) today.

Rules only **move** energy; a per-consumer budget keeps the total exact. Slots are processed in time order:

- `planned[t]` = matched profile value; `backlog` = energy deferred so far; `remaining` = target − delivered.
- Block → the slot's planned energy goes to `backlog`.
- Allowed → deliver `min(nominal, planned[t] + backlog_share)`; surplus pull may add more from `remaining` (§ 4.3).
- Deadline forcing (§ 4.4) overrides the block.

If no rule fires, L2 equals L1 slot for slot. Every L1 → L2 difference can therefore be traced to a rule.

**Rule per consumer type (O4):**

| Consumer | Rules |
|---|---|
| `ev` | PV surplus (§ 4.3), deadline (§ 4.4). No price lock, no V2G discharge. |
| `thermal_annual`, `thermal_rc` | Price lock (§ 4.2), surplus boost (§ 4.3), deadline (§ 4.4). |
| `generic` with `generic_flex_window` | Cheapest block (§ 4.5). |
| Other flexible `generic` | Price lock (§ 4.2), deadline (§ 4.4). |
| Fixed load (`continuous_load`, native filter run) | No rule: already booked as fixed load. |
| Heating rod (`daily_target_source: heating_rod`) | Runs 0 kWh in L1 and L2 (§ 3.1). |

### 4.2 Price lock — "SG-Ready lock / EVU-Sperre"

Blocked when the slot's end-customer price (incl. grid fee and VAT, `k_act` on actual prices) is **strictly above** the P75 quantile of the prices available at that slot. "Available" means from the slot to the end of the last published day-ahead day (`data/backtesting_prices.py::last_day_ahead_calendar_date`), recomputed per slot. So the rule never uses an unpublished price, and a flat tariff never locks. Deferred energy is caught up in the next allowed slots. Thermal comfort is not modelled (same limitation as the matched baseline today).

The available horizon reaches past the book's end (SA₂), so the rule builder needs the price series up to that day, not just the window matrix. A missing price in that range fails loud.

### 4.3 PV surplus charging (EV, heat pump and pool boost) — "evcc mode PV / SG-Ready state 3"

The consumer sees the local surplus `pv − baseload − Σ other flex in this slot` (before the battery: the consumer has priority, a common evcc setup). Battery first runs in the sensitivity (§ 4.7): there the consumer sees only what would be exported at the meter after `vendor_mode_step`. It charges when surplus ≥ `min_power_kw` with hysteresis via `min_on_quarterhours`, at most `nominal_power_kw`, from `remaining`. Energy pulled forward this way reduces later planned slots (from the back of the profile) so the total stays exact.

### 4.4 Deadline forcing — "evcc Min+PV / target charge"

If `remaining > (allowed slots left in the window) × nominal × dt`, the consumer runs regardless of price lock or surplus. This guarantees the target where the window allows it; if even that fails, the window is infeasible and the run fails loud (§ 3.1).

### 4.5 Generic flex with a start window — "HA cheapest hours"

Consumers with `generic_flex_window` start their historical cycle (same duration and energy) in the cheapest contiguous block inside the window, by end-customer day-ahead price. Only prices published when the window opens count; slots without a published price are not candidates. No PV term.

### 4.6 Battery

Unchanged `vendor_mode_step` on what remains after the flex consumers in that slot. No grid charging, no price logic: this is the inverter's own behaviour.

### 4.7 Parameters and sensitivity

Defaults: quantile 0.75, consumer before battery, hysteresis from `min_on_quarterhours`. Sensitivity run: quantile ∈ {0.50, 0.66, 0.75, 0.90} × surplus priority ∈ {consumer first, battery first}, 8 runs per scenario; the report shows the default and the best set in hindsight ("Regeln, im Nachhinein bestens parametriert").

## 5. Implementation sketch

- **Rule builder** `optimizer/sim_baseline.py::build_rule_based_flex_kw_per_hour(matrix, targets, charging_contexts, consumers, shapes, price_series, rule_params)` — pure, same output shape as `build_matched_flex_kw_per_hour`. `shapes` and `price_series` per § 4.1 and § 4.2. Per-slot simulation reuses `_simulate_single_hour_baseline(flex_kw_override=…)`.
- **SE reference runner**: L1 and L2 are not closed-form any more. They use the same per-window matrices as the optimized run (`build_historical_window_matrix` / `build_sunrise_window_matrix`) and carry the SoC across anchors. Those matrices split baseload from flex but hold only per-consumer targets, no per-consumer series, so the runner adds the shapes (§ 4.1). L1 and L2 always book actual prices. L0 stays closed-form.
- **Reference sharing**: today references are shared across scenarios by `reference_fingerprint` (Historisch = assets stripped). L1/L2 depend on battery and flex consumers, so the fingerprint must include them; sharing between scenarios with different storage ends.
- **Output**: per-slot frame with the same columns as today (`_REFERENCE_COST_COLUMNS`) per ladder step, plus SoC for L1/L2, so existing charts and the SE invoice keep working.
- **Study export**: one CLI (`python -m scripts.run_reference_ladder --scenario … --workers N`) writing L0–L3 per day and per scenario as CSV for the Points / pricing studies (`backtesting-max-workers.mdc`). Each scenario row carries a flag when the scenario has a heating rod (§ 3.1) and states that L3 is perfect foresight.

## 6. Effect on other features

- **Savings ledger:** `savings_v: 1` equals L1 on live actuals. Ledger P9/P10 (`savings_v: 2`, flex re-timing) could use the L2 rules on actuals, so live figures and study figures share one counterfactual. Separate decision, not part of this epic.
- **Earnie Points:** points are derived from the live scenario's components (`earnie-points.md`), not from savings; existing points do not change. The ladder is input for the Points strategy study.
- **SE figures change.** Savings drop for every scenario with a battery or flex consumers. User docs and release notes must say why (method change, not a regression). Golden-master regression cases that assert SE savings need `--update-golden` with that justification.

## 7. Method decisions (P0, maintainer, 2026-11-05)

Line numbers are as of this date.

### O1 Perfect foresight: yes. A forecast mode is required before final study prices.

The MILP sees the values that get booked:

| Input | What the MILP sees | Evidence |
|---|---|---|
| PV | Archive weather (Open-Meteo) or imported CSV, the series that is booked. `PV-Prognose (kW)` is this actual value. | `simulation/matrix_builder.py:315`, `simulation/historical_cache.py:149`, `simulation/engine.py:432` |
| Load | Baseload and flex targets of the window, i.e. the actual need; the book's values overlay the MILP matrix. `Verbrauch-Prognose (kW)` is this value. | `simulation/matrix_builder.py:478`, `:598-599`, `simulation/engine_scenario.py:177` |
| Prices | Default `perfect`: actual prices over SA₀→SA₂, no publication cutoff. The UI always runs this. | `data/backtesting_prices.py:341-357`, `scripts/run_backtesting.py:219` |

Limits on that foresight: one plan per day with no re-plan as in live, and no view past SA₂ (`simulation/backtesting_horizon.py:158`).

`--price-strategy mirror|forecast` does not fix this:

- It books at the planned price, not the actual one (`optimizer/sim_chart_rows.py:51`, `optimizer/sim_costs.py:82`), while references book actual prices (`simulation/reference_costs.py:153`).
- It plans at SA₀, so nearly the whole book lies past the day-ahead cutoff (`simulation/matrix_builder.py:574`).
- PV and load stay perfect.

The earlier result "forecast vs. mirror ±0.1–0.6 %" therefore says nothing about the foresight effect.

**Decision:** separate backlog item **SE forecast mode**: plan on forecasts, book on actuals. Perfect foresight is the upper bound for L3's value; one plan per day without re-plan is the lower bound. It does not block P1–P5, but final study prices wait for it.

### O2 Surplus priority: consumer before battery, battery first in the sensitivity.

See § 4.3 and § 4.7. The sensitivity grid doubles to 8 runs per scenario.

### O3 Lock basis: available horizon, end-customer price, strictly above P75.

See § 4.2. Calendar day was the alternative. The strict comparison is not a matter of basis: `≥` would lock every slot of a flat tariff.

### O4 Consumer mapping and profiles.

- **Mapping:** table in § 4.1, generous to the rules (surplus boost for thermal consumers).
- **Starting profile:** real timing per consumer, "switch on and run" where there is no shape (§ 4.1). Flat spreading is out: it runs consumers below their minimum power and breaks comparability with L0.
- **Heating rod:** 0 kWh in L1 and L2, flagged in the study export (§ 3.1). A surplus rule with heat replacement can follow later.

### O5 UI: L2 vs. L3 as the headline, ladder in an expander.

The headline shows the saving L2 − L3 and the rule share; the expander shows L0–L3.
