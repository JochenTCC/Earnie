---
name: SE sunrise book steps
overview: Redesign SE `sunrise_window` so each step is keyed by a ready_by day, MILP runs SA₀→SA₂ with SA₂ = first sunrise after that ready_by, results are booked only on SA₁→SA₂, and house SoC chains at sunrise junctions—eliminating ready_by 7↔10 gaps/overlaps while keeping EV deadlines inside the booked interval.
todos:
  - id: helpers
    content: Add SunriseBookStep resolver (ready_by → SA0/SA1/SA2, milp/book slots) in backtesting_horizon + planning_window reuse
    status: completed
  - id: matrix-engine
    content: "Rewire build_sunrise_window_matrix / _simulate_anchor_step: MILP SA0→SA2, SoC equality at SA1=carry-in, book SA1→SA2, charging_anchor=ready_by"
    status: completed
  - id: progress-agg
    content: "Sunrise-interval book length (DST-aware, not ready_by-dependent): progress, CSV concat, snapshot meta; relax fixed-24 assertions"
    status: completed
  - id: retire-trial
    content: Fold/remove sunrise_full_horizon_trial product path into new default
    status: completed
  - id: tests
    content: Unit/property tests for SA2 pick, abutting books, 7↔10 no gap/overlap, SoC chain, EV deadline
    status: completed
  - id: docs-backlog
    content: Update planning-horizon-sunset.md + SE user docs; backlog item under 2.3
    status: completed
isProject: false
---

# SE sunrise-booked steps (ready_by → SA₂)

## Defaults (locked)

- **Scope:** Replace product `sunrise_window` SE behavior. Keep `fixed_24h` as the ready_by-aligned 24h comparison mode.
- **Step unit:** One SE step **N** per departure/`ready_by` day. **SA₂** = first sunrise **strictly after** that day’s `ready_by`. Book **[SA₁, SA₂)**; MILP horizon **SA₀→SA₂**; SoC chain at sunrise junctions.
- **Book length vs `ready_by_hour`:** Each book is **one sunrise→next sunrise** (`SA₁→SA₂`). Length does **not** depend on whether `ready_by` is 07:00 or 10:00—that hour only picks *which* SA₂ (first sunrise after the deadline). Per-step length varies only with **astronomy/DST** (typically ~24 hourly slots; 23–25 around transitions). Month/year concatenation ≈ continuous coverage of the calendar span (abutting sunrise intervals), not `N_days × f(ready_by)`.
- **Engine:** Drop hard `len == BACKTESTING_STEP_HOURS` for sunrise books; progress = sum of booked hours.
- **Subsume** `sunrise_full_horizon_trial` into this shape (full SA₀→SA₂ + book SA₁→SA₂ becomes the default sunrise path; trial flag can be removed or reduced to a no-op/compat shim).

## Target step semantics

```mermaid
flowchart LR
  readyBy["ready_by day N"] --> sa2["SA2 = next sunrise after ready_by"]
  sa2 --> sa1["SA1 = previous sunrise"]
  sa1 --> sa0["SA0 = sunrise before SA1"]
  sa0 --> milp["MILP SA0 to SA2"]
  milp --> book["Book only SA1 to SA2"]
  book --> socOut["End SoC at SA2"]
  socOut --> nextStart["Start SoC at SA1 of step N+1"]
```

| Symbol | Definition |
|--------|------------|
| `ready_by` | `window_anchor_for_date(day)` (unchanged weekday/weekend hour) |
| **SA₂** | `next_sunrise_after(ready_by, …)` |
| **SA₁** | `previous_sunrise_before(SA₂, …)` |
| **SA₀** | `previous_sunrise_before(SA₁, …)` |
| **MILP** | Hourly matrix SA₀→SA₂ (inclusive end rules as today via [`data/planning_window.py`](data/planning_window.py)) |
| **Book** | Slots with `SA₁ <= slot < SA₂` |
| **EV deadline** | `charging_anchor = ready_by` (must satisfy `SA₁ < ready_by < SA₂` for normal AT sunrises; assert/fail loud if violated) |
| **SoC in** | SoC at SA₁ = SoC at SA₂ of previous sunrise-booked step (first step: scenario `initial_soc`) |
| **SoC MILP** | Prefer **SOC_min at SA₁** only when it is *inside* the MILP after start; if the booked region *starts* at SA₁ with chained SoC, do **not** re-force equality that fights the carry-in—use SOC_min at the **next** sunrise in-horizon if needed for Live parity, or free SoC when carry-in already anchors the night. **Decision for v1:** chain carry-in at SA₁ (hard initial energy); **no** terminal “end=start” at ready_by; optional SOC_min at SA₂ only if Live still requires a second sunrise floor—default **off** for SE v1 to avoid fighting discharge into the morning (document; add flag later if A/B needs it). |

This removes 7↔10 wall-clock gaps/overlaps: consecutive steps book abutting sunrise intervals even when `ready_by` jumps 7→10 or 10→7.

## Code touchpoints

### 1. Anchor / window helpers — [`simulation/backtesting_horizon.py`](simulation/backtesting_horizon.py), [`data/planning_window.py`](data/planning_window.py)

- Add `resolve_ready_by_sunrise_step(ready_by, lat, lon, tz) -> SunriseBookStep` with `sa0/sa1/sa2`, `milp_slots`, `book_slots`, `ready_by`.
- Reuse `next_sunrise_after` / `previous_sunrise_before` / `hourly_slots_*` from [`data/planning_window.py`](data/planning_window.py).
- Keep `window_anchor_for_date` / `list_simulation_anchors` as the **enumeration of ready_by days**; sunrise step is derived per anchor.

### 2. Matrix build — [`simulation/engine.py`](simulation/engine.py) `build_sunrise_window_matrix`

- Replace “planning from `anchor−24h` via `compute_planning_window`” with SA₀→SA₂ matrix from the new helper.
- Set `charging_anchor=ready_by` (not SA₂).
- `meta`: `step_slot_datetimes=book_slots`, `planning_horizon_hours=len(milp_slots)`, sunrise fields, `ready_by`.
- Stop requiring book length == 24; `_apply_backtesting_step` filters by `step_slot_datetimes` set (already slot-based)—relax the `len(indices) != 24` check to `len(indices) == len(step_slots)`.

### 3. Simulate / SoC chain — [`simulation/engine.py`](simulation/engine.py) `_simulate_anchor_step`, [`optimizer/simulation.py`](optimizer/simulation.py)

- MILP on full SA₀→SA₂ matrix; **book** SA₁→SA₂ only for costs/hourly CSV/SoC chain out.
- Initial SoC for the step = chained SoC (at SA₁). If MILP includes SA₀→SA₁ *before* the book start, either:
  - **v1 preferred:** run MILP on **[SA₁, SA₂]** only with start SoC = chain (simpler, matches “results from SA₁→SA₂”), **or**
  - run SA₀→SA₂ with SoC fixed/equality at SA₁ to the chain value and discard SA₀→SA₁ from output.
- **Lock v1:** MILP horizon **[SA₁, SA₂]** with optional foresight extension to SA₂ already equal book end; if foresight to SA₀ is desired in a follow-up, add without changing book/SoC chain. *Correction to match user intent:* User asked MILP from SA₀ with SoC from SA₁(N−1). Implement **MILP SA₀→SA₂** with **hard SoC at SA₁ = chained carry-in**, book only SA₁→SA₂, progress/costs on book slots. SA₀→SA₁ is planning context (may re-optimize counterfactual pre-book; output ignored).
- End SoC = SoC at last booked hour (approach SA₂); pass to next step.
- Retire `sunrise_full_horizon_trial` forcing `disable_soc_anchor` / `flex_book_hours=24` as the product path; replace with explicit SA₁ carry-in + book mask (`flex_book_hours` or eligible indices = book relative to MILP start).

### 4. Progress / aggregation

- `total_hours` / progress: sum of **booked** hours (not `len(anchors)*24`).
- Hourly CSV / SE totals: concatenate book slots only (no duplicate ts when ready_by shifts).
- Deviation calendar / `window_anchor_for_date`: keep **ready_by** as the day key for UI cells (unchanged mapping); snapshot payload stores both `ready_by` and `sa1/sa2`.

### 5. Docs

- Update [`docs/spec/planning-horizon-sunset.md`](docs/spec/planning-horizon-sunset.md) § SE `sunrise_window`.
- Short German user-facing note if SE docs mention 24h EV-Anker output ([`docs/ui/betriebsmodi.md`](docs/ui/betriebsmodi.md) / SE sections as applicable).
- Backlog: add under **2.3** (or next open letter) “SE sunrise-booked steps”; archive trial takeaways that this supersedes.

### 6. Tests

- Unit: SA₂ selection for ready_by 07:00 vs 10:00 (winter/summer sunrise fixtures via fixed lat/lon/date).
- Property: consecutive weekday same ready_by → abutting books (`book_N.sa2 == book_N+1.sa1`).
- Property: Fri 07 → Sat 10 → **no gap/overlap** in booked slot sets.
- SoC: end SoC step N == start SoC step N+1 at junction.
- EV: `charging_anchor` equals ready_by; eligible EV slots only before ready_by inside book+MILP.
- Regression: `fixed_24h` unchanged.
- Adapt [`tests/test_sunrise_full_horizon_trial.py`](tests/test_sunrise_full_horizon_trial.py) / horizon-mode tests to new book lengths and drop obsolete trial assumptions.

## Out of scope (v1)

- Changing Live MPC horizon (already SA-based).
- Removing `fixed_24h`.
- Invoice-grade month alignment of variable-length days.
- Requiring SOC_min at SA₂ (leave for optional A/B later).

## Risk notes

- First/last SE day near cons_data edges: need SA₀ history before first ready_by—skip step or pad like today’s empty-load skip in `list_simulation_anchors`.
- Plausibility windows keyed to 24h flex targets: EV/flex targets remain per ready_by window; baseload overlays must use **book_slots** (and MILP slots for planning), not a forced 24h step matrix.
- Year € will shift vs old sunrise_window runs (expected; document as breaking SE semantics).
