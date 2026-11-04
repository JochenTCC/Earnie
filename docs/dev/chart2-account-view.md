# Chart 2 as an account view

**Status:** draft, agreed with the maintainer in chat on 2026-11-04; not implemented. The maintainer accepted the prototype's presentation; the former Chart 2 presentation is not revived.
**Related:** [`savings-ledger.md`](savings-ledger.md) § 3–5, [`../ui/charts.md`](../ui/charts.md) § Chart 2, `backlog/Backlog.md` epic Ledger (P7, P8).

---

## 1. Problem

Chart 2 only shows "Ist bisher" left of *Jetzt*. Baseline and optimized trajectories start at *Jetzt*, so nobody can see how the two developed before it. A cost curve also rises when money leaves, which reads the wrong way round.

## 2. Question the chart answers

*How much has Earnie saved so far, and how much more is expected?*

## 3. Design

- **Account view.** The y axis shows a balance: a falling line means paying, a rising line means earning (feed-in revenue). Value = −cumulative cost.
- **Full trajectories.** Baseline and optimized cover the whole visible window, past and forecast.
- **Anchoring, user's choice:**
  - **"Ist bei Jetzt" (default).** Optimized stays as it is; the baseline is shifted as a whole so that both lines meet at *Jetzt*. The gap at the window start is the saving so far, the gap at the window end is the expected saving.
  - **"Gemeinsamer Start".** Both lines start at the same balance at the window start. The gap at *Jetzt* is the saving so far, the gap at the window end is the total.
- **The switch needs no extra data.** The two modes differ by one constant: the saving so far in the window is added to the baseline. The state is kept for the session (`streamlit-ui-state.mdc`).
- **Gap colouring.** Green = saving, red = loss, with labels "bisher gespart/Verlust" and "erwartet". In "Ist bei Jetzt" the line on top means opposite things left and right of *Jetzt*; colour and labels carry the meaning.

- **Where it lives.** The Monitor shows two SA-days: the last closed one, the open one and the plan up to the end of the horizon. Longer periods belong on the page "Analyse Verbrauch & Kosten" (`ui/pages/page_consumer_analysis.py`), in the same presentation. "Ist bei Jetzt" suits this: more history only lengthens the lines to the left.

## 4. Data

| Part | Optimized line | Baseline line |
|---|---|---|
| Left of *Jetzt* | actual, ledger `cost_with` per slot | shadow plant, ledger `cost_without` per slot |
| Right of *Jetzt* | plan (`hourly_optimized_cost_euro`) | plan (`hourly_matched_baseline_cost_euro`, "BL Ziel") |

- **The baseline changes its definition at *Jetzt*:** shadow plant in vendor mode on the left, matched baseline from the live SoC on the right. The **?** help text says so.
- **Slot series for closed days.** The ledger holds one row per closed SA-day, the slot series only for the open day. The Monitor needs the series of the last closed day, the analysis page those of all closed days: a slot file next to the ledger, filled by a backfill from `optimization_history.jsonl`, so the chart does not replay the log on each render. A read-only replay reproduces the ledger's day rows exactly, so the backfill can use the existing engine.
- **Skipped slots** count as zero on both sides, as in the ledger, and are marked orange.
- **SoC correction.** Reserve built so far is in neither gap: it shows as extra cost on the left, while the forecast baseline starts from the live SoC and inherits it. It stays a separate label.
- **Sign.** The whole view uses the ledger's sign: positive = saving (`cost_without − cost_with`). The annotations' old sign (`optimized − matched`) goes away.

## 5. Axis and layout

- The axis reads "Kontostand seit Fensterstart" and starts at 0 €. It is energy cost and feed-in revenue at the ledger prices, not a bank balance and not the bill (no grid or monthly fees).
- The balance runs through SA₁; a vertical marker shows the SA boundary.
- **Consumption control** moves to its own small panel below, see § 5.1. This keeps "falling = paying" to the money panel and removes the second y axis.
- **Paging and mobile** use one rule: the anchor is *Jetzt*, clamped to the visible window. A window that lies fully in the past is anchored at its end.

### 5.1 Consumption control

The panel only checks that both sides were computed with the same consumption; it is not a second result. Absolute energies are not shown: a steadily rising curve says less the longer the window is.

- **What it shows.** One line, baseline minus optimized in kWh, with **zero at the end of the horizon**, independent of the anchor chosen for money.
- **How to read it.** The value at *Jetzt* is the energy difference of the plan over the remaining horizon. Right of *Jetzt* the line also shows flex timing: it leaves zero while one side consumes earlier and returns when the other catches up.
- **Data.** Left of *Jetzt*: optimized = logged `house_kw`, baseline = the same logged `house_kw`. Right of *Jetzt*: the plan's `hourly_optimized_consumption_kwh` and `hourly_matched_baseline_consumption_kwh`, the same costed series as the money panel.
- **Limit of the check.** In `savings_v: 1` the shadow reuses the logged load, so the line is flat left of *Jetzt* by construction. Only the part right of *Jetzt* can reveal a real mismatch.
- **No standby option.** The shadow plant's cost includes `standby_power_kw` (`savings-ledger.md` § 3), but this panel leaves it out and offers no switch: it would only add a steady drift that says nothing about consumption, and it proved confusing in the prototype.
- **Experiment.** The prototype can show the derivative instead: mean power per bucket, and a cost rate in €/h for the money side. Neither is part of this design unless the maintainer decides so.

## 6. Open

1. **Long windows on the analysis page.** The total cost dominates the y scale there, so the gap becomes too small to read. The prototype tries an optional panel with the gap alone.
2. **Axis label on the analysis page.** With 0 € at the window start, the axis values change with the window while the curve shapes stay the same.
3. **Forecast consumption.** The log's `savings_snapshot` has no consumption series, and the debug file stores the costed baseline's rows only implicitly (matched rows minus the profile-fallback consumers). The chart must take the series from the chart context.
4. **Optional: budget.** The user sets an amount for electricity; the axis then starts at that amount instead of 0 € and the line shows what is left, so reaching 0 € means the budget is used up. This is one more constant offset and needs no extra data. Still to decide: the budget's period (a calendar month does not match the visible window) and whether falling below 0 € is flagged.
5. **Plan energy difference.** Costed baseline and optimized plan need not end with the same energy, so "erwartet" also contains the price of that difference. Decide whether a difference above a threshold is flagged.

## 7. Effect on Ledger P7

P7 is on `main` (`a68d2aec`): Chart 2 is visible again in the former presentation, with "Ersparnis bisher" from the ledger. This account view replaces that presentation. It also needs the slot series of closed SA-days, which the ledger does not store yet (§ 4). Not implemented yet.
