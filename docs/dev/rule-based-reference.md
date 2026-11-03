# Rule-based reference — Earnie vs. standard rules (Scenario Explorer)

**Status:** draft 2026-11-03, not implemented. Backlog: epic **RuleRef** in `backlog/Backlog.md`.

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

1. **Same energy.** Per window and per flex consumer, L1 and L2 deliver exactly the energy that L3 delivers (the same `consumer_daily_targets_kwh` / horizon targets the optimized run uses). Checked by the same `simulation/plausibility.py::validate_window_consumption` as the optimized run; a step that cannot reach its target in the eligible window fails loud with the missing kWh (`no-implicit-fallbacks.mdc`), no silent clipping.
2. **Same windows and constraints.** Same charging windows (`charging_contexts`, `consumer_charging_eligible_indices`), same nominal / min power, `min_on_quarterhours`.
3. **One continuous SoC chain** over the whole SE period, never reset per anchor (lesson D1 in `savings-ledger.md`). End-of-period SoC difference to L3 is valued like the ledger's SoC correction.
4. **Same prices and fees.** End-customer price per slot incl. time-variable grid fee, same feed-in settings (`_reference_feed_in_settings`).
5. **Information parity.** Rules see measured values in real time (surplus at the meter) and the day-ahead prices once published — that is what real products see. Earnie in the SE plans from the window matrix built from historical/actual series (`simulation/matrix_builder.py`); no forecast-error model was found. If the SE effectively gives Earnie perfect foresight, L2 − L3 is overstated. **Open question O1** (§ 7) must be answered before the studies.
6. **Rule parameters fixed up front**, plus a sensitivity run (§ 4.5) that reports the best parameter set in hindsight. Being generous to the rules is the point.

## 4. L2 rule set

Each rule is local: it knows its own consumer, the meter, and the price. It knows nothing about other consumers' plans or the battery SoC. Every rule is named after the product behaviour it imitates, so the reference is "evcc + SG-Ready + HA cheapest hours", not an invented strategy.

### 4.1 Mechanism: deferral queue on top of the matched profile

Starting point per consumer is the matched-baseline profile (`build_matched_flex_kw_per_hour`: historical shape scaled to the target, zero outside the eligible window). Rules only **move** energy; a per-consumer budget keeps the total exact. Slots are processed in time order:

- `planned[t]` = matched profile value; `backlog` = energy deferred so far; `remaining` = target − delivered.
- Block → the slot's planned energy goes to `backlog`.
- Allowed → deliver `min(nominal, planned[t] + backlog_share)`; surplus pull may add more from `remaining` (§ 4.3).
- Deadline forcing (§ 4.4) overrides the block.

If no rule fires, L2 equals L1 slot for slot. Every L1 → L2 difference can therefore be traced to a rule.

### 4.2 Price lock (heat pump, heating rod, generic flex) — "SG-Ready lock / EVU-Sperre"

Blocked when the slot's end-customer price ≥ the P75 quantile of that calendar day's prices (day-ahead, known in advance; same basis the HA templates and Tibber-style automations use). Deferred energy is caught up in the next allowed slots. Thermal comfort is not modelled (same limitation as the matched baseline today).

### 4.3 PV surplus charging (EV, optional heat pump boost) — "evcc mode PV / SG-Ready state 3"

The consumer sees the local surplus `pv − baseload − Σ other flex in this slot` (before the battery: EV has priority, a common evcc setup; the other order is a P0 decision). It charges when surplus ≥ `min_power_kw` with hysteresis via `min_on_quarterhours`, at most `nominal_power_kw`, from `remaining`. Energy pulled forward this way reduces later planned slots (from the back of the profile) so the total stays exact.

### 4.4 Deadline forcing — "evcc Min+PV / target charge"

If `remaining > (allowed slots left in the window) × nominal × dt`, the consumer runs regardless of price lock or surplus. This guarantees the target where the window allows it; if even that fails, the window is infeasible and the run fails loud (§ 3.1).

### 4.5 Generic flex with a start window — "HA cheapest hours"

Consumers with `generic_flex_window` start their historical cycle (same duration and energy) in the cheapest contiguous block inside the window, by day-ahead price. No PV term.

### 4.6 Battery

Unchanged `vendor_mode_step` on what remains after the flex consumers in that slot. No grid charging, no price logic: this is the inverter's own behaviour.

### 4.7 Parameters and sensitivity

Defaults: quantile 0.75, EV before battery, hysteresis from `min_on_quarterhours`. Sensitivity run: quantile ∈ {0.50, 0.66, 0.75, 0.90}; the report shows the default and the best set in hindsight ("Regeln, im Nachhinein bestens parametriert").

## 5. Implementation sketch

- **Rule builder** `optimizer/sim_baseline.py::build_rule_based_flex_kw_per_hour(matrix, targets, charging_contexts, rule_params)` — pure, same output shape as `build_matched_flex_kw_per_hour`. Per-slot simulation reuses `_simulate_single_hour_baseline(flex_kw_override=…)`.
- **SE reference runner**: L1 and L2 are not closed-form any more. They use the same per-window matrices as the optimized run (`build_historical_window_matrix` / `build_sunrise_window_matrix`), which already split baseload and per-consumer flex, and carry the SoC across anchors. L0 stays closed-form.
- **Reference sharing**: today references are shared across scenarios by `reference_fingerprint` (Historisch = assets stripped). L1/L2 depend on battery and flex consumers, so the fingerprint must include them; sharing between scenarios with different storage ends.
- **Output**: per-slot frame with the same columns as today (`_REFERENCE_COST_COLUMNS`) per ladder step, plus SoC for L1/L2, so existing charts and the SE invoice keep working.
- **Study export**: one CLI (`python -m scripts.run_reference_ladder --scenario … --workers N`) writing L0–L3 per day and per scenario as CSV for the Points / pricing studies (`backtesting-max-workers.mdc`).

## 6. Effect on other features

- **Savings ledger:** `savings_v: 1` equals L1 on live actuals. Ledger P9/P10 (`savings_v: 2`, flex re-timing) could use the L2 rules on actuals, so live figures and study figures share one counterfactual. Separate decision, not part of this epic.
- **Earnie Points:** points are derived from the live scenario's components (`earnie-points.md`), not from savings; existing points do not change. The ladder is input for the Points strategy study.
- **SE figures change.** Savings drop for every scenario with a battery or flex consumers. User docs and release notes must say why (method change, not a regression). Golden-master regression cases that assert SE savings need `--update-golden` with that justification.

## 7. Open questions (P0)

- **O1** Does the SE plan with perfect foresight (matrix = booked actuals)? If yes: accept and state it, or add a forecast mode for L3 before the studies.
- **O2** EV vs. battery priority for surplus (§ 4.3).
- **O3** Quantile basis: calendar day vs. available horizon; price incl. or excl. grid fee and VAT (proposal: end-customer price, calendar day).
- **O4** Which consumer types get which rule (mapping per `type` / `thermal` / `generic_flex_window`), and what happens to consumers without a historical profile.
- **O5** UI: show the full ladder or only L2 vs. L3 with the ladder in an expander.
