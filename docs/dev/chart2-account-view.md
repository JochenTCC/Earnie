# Chart 2 as an account view

**Status:** agreed with the maintainer in chat on 2026-11-04. **Implemented 2026-11-05 (Account view P2)** for the Monitor and the Scenario Explorer window: `ui/chart_account_view.py` (pure), `ui/chart_account_render.py` (Plotly/Streamlit), slots left of *Jetzt* from `ui/chart_ledger_savings.py`. The former traces and the per-day cost annotations are removed. The analysis page (P3) is still open.
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
- **Sign.** The whole view computes with the ledger's sign: positive = saving (`cost_without − cost_with`). Labels show amounts without a sign and name the meaning in words (`ui/saving_text.py`, [`savings-ledger.md`](savings-ledger.md) § 5). The annotations' old sign (`optimized − matched`) goes away.
- **Incomplete days.** A closed day with `coverage < 0.8` stays marked "unvollständig" when the annotations are replaced.

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
- **Rejected.** Showing the derivative instead (mean power, and a cost rate in €/h on the money side) was tried in the prototype and did not help.

## 6. Open

1. **Long windows on the analysis page.** The total cost dominates the y scale there, so the gap becomes too small to read. The prototype tries an optional panel with the gap alone.
2. **Axis label on the analysis page.** With 0 € at the window start, the axis values change with the window while the curve shapes stay the same.
3. **Forecast consumption.** The log's `savings_snapshot` has no consumption series, and the debug file stores the costed baseline's rows only implicitly (matched rows minus the profile-fallback consumers). The chart must take the series from the chart context.
4. **Optional: budget.** The user sets an amount for electricity; the axis then starts at that amount instead of 0 € and the line shows what is left, so reaching 0 € means the budget is used up. This is one more constant offset and needs no extra data. Still to decide: the budget's period (a calendar month does not match the visible window) and whether falling below 0 € is flagged.
5. ~~**Plan energy difference.**~~ **Decided 2026-11-05 (P2):** costed baseline and optimized plan need not end with the same energy, so "erwartet" also contains the price of that difference. A caption under the chart names it when the difference at *Jetzt* is at least 0.5 kWh **and** at least 2 % of the planned consumption (`ENERGY_DIFF_MIN_KWH`, `ENERGY_DIFF_MIN_SHARE`).
6. ~~**Scenario Explorer window.**~~ **Decided 2026-11-05 (P2):** the SE window view (`render_optimization_chart2`, RuleRef P3b) moves to the account view too. It has no *Jetzt*, so both lines start at 0 € (the modes coincide, no switch), the baseline is L2 ("Standard-Regeln", or BL Ziel for logs without a ladder) and the label at the window end reads "Plan".

## 7. Effect on Ledger P7

P7 is on `main` (`a68d2aec`): Chart 2 is visible again in the former presentation, with "Ersparnis bisher" from the ledger. This account view replaces that presentation. The slot series of closed SA-days it needs (§ 4) exist since Account view P1 (`savings_ledger_slots.jsonl`, [`savings-ledger.md`](savings-ledger.md) § 4); the chart uses them since P2.

## 8. Implementation notes (P2)

- **Slot states** (`ui.chart_account_view.SLOT_*`): `counted`, `skipped` (ledger did not count it), `no_data` (no ledger record: chain not running, before the chain start, unreadable slot file), `pending` (open day after the last booked slot: the daemon books it once it closes), `plan`. `skipped` and `no_data` are orange and count zero on both sides; `pending` counts zero without a mark. A log slot without data (`SLOT_MISSING`) is orange too.
- **Anchor** = the display's `history_slot_count`, a slot boundary: 0 for a window in the future, the slot count for one fully in the past.
- **Consumption control** = remaining baseline minus optimized energy: `Σ_{i≥k}(base_i − opt_i)` plus the plan energy after the window (`hourly_*_consumption_after_window_kwh` in `savings_view`), so it is zero at the horizon end on a phone's 24 h segment too. Left of *Jetzt* both sides count zero (savings_v 1 reuses the logged load).
- **Gap colouring:** the area between the lines is split where they cross; the sign of the gap (positive = saved, in both modes) picks green or red. 0,00 € is neither (`saving_color`).
- **Labels:** "Bisher" (window start in "Ist bei Jetzt", *Jetzt* in "Gemeinsamer Start"), "Erwartet" / "Gesamt" at the window end, "Plan" for a window without past; closed days "Ergebnis" with "unvollständig"; the open day's SoC correction at *Jetzt*.
- **Switch state:** `st.session_state["chart2_anchor_mode"]`, radio inside the Chart 2 fragment, default "Ist bei Jetzt".
