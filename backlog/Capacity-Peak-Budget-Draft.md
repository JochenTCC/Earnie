# Capacity charge AT 2027 — monthly peak budget: algorithm draft

**Status:** draft (2026-10-14), nothing implemented. Backlog: [Backlog.md](Backlog.md) → **Edibert integration** → **Capacity charge AT 2027** → *Planning loop* and *Expected PV for the rest of the month*.
**Related:** Leistungstarif development document (L1→L5, outside this repo: `Earnie-Projekt/Entwicklungsplan/Offen/Earnie-Leistungstarif-AT-2027-Entwicklungsdokument.md`), sections 1.4 (ratchet), 4.3 (SE formula), 5.2 (import cap with slack), 5.5 (cap sweep). Tariff model and ladder: Edibert spec section 5b.

---

## Problem in one paragraph

The capacity charge bills the highest clock-aligned 15-min import power of the calendar month, at least `P_min = max(2 kW, 0.2 · P_contracted)`. A higher peak costs one step of the ladder **once per month**; after that, import up to this peak is free for the rest of the month (ratchet). The live MILP sees only 1–2 days, so on its own it either refuses every exceedance (hard cap) or takes one too lightly (ladder cost without the future benefit). A slow loop must decide each day which peak budget is worth it for the rest of the month. That depends on the PV and load still to come and on what extra import power is worth: cheaper import slots for battery and EV, PV sold at a higher feed-in price instead of stored.

## Notation

| Symbol | Meaning |
|---|---|
| `D`, `k` | days in the month, today's day of month |
| `R` | remaining days of the month incl. today; `R_after` = remaining days after the MILP horizon |
| `P_m0` | measured month-to-date peak (state, never assumed `0`) |
| `P_min` | minimum billing power (`max(2 kW, 0.2 · P_contracted)`); below it nothing is saved |
| `C(P)` | monthly capacity cost of billed peak `max(P, P_min)`: `c1 · min(P, 10) + c2 · max(P − 10, 0)`, `c1 < c2` (from Edibert) |
| `c(P)` | marginal capacity price at `P` in €/kW·month (`c1` or `c2`) |
| `b` | peak budget: import cap the plan respects |
| `E_d(b)` | energy cost of day `d` under cap `b`: import cost − feed-in revenue + wear (MILP objective, with slack per dev doc 5.2) |
| `v_d(b)` | value of 1 kW more budget on day `d`: `(E_d(b) − E_d(b + Δ)) / Δ`, ≥ 0 |
| `v̄_m(b)` | mean daily `v` in calendar month `m`, from the SE sweep (part 1) |

Feed-in revenue and cheap import need no separate model: both are already in the MILP objective, so `E_d(b)` measures the net effect of the cap.

## Why not "typical" or averaged weather

- The monthly peak is set by the **worst** days (dull, cold, heat pump and EV at the same time), not by an average day.
- Hour-by-hour averages over several years turn every day into "partly cloudy" and flatten price spreads and negative prices. They overstate how easily a cap holds and understate the value of extra import power. Optimizer results on averaged inputs are not averaged results (the problem is non-linear).
- Weather and prices must come from the **same real day**: PV drives day-ahead prices, cold days are often dull days.

Therefore the algorithm samples **real historical days** (Open-Meteo archive + historical prices + modelled/measured load for those dates) and works with distributions, not means.

---

## Part 1 — Value table from an SE cap sweep (offline)

Extends the cap sweep of dev doc 5.5.

1. For each of the last `N` years (default 3–5; years like 2022 excludable, or prices normalised to a current level — open), run the SE with a uniform import cap `b` from a grid `{P_min, P_min + 0.5, …, b_max}` kW. Weather and prices from the same year. Run whole years (or at least whole months), not single days, so the battery's carry-over between days is included.
2. Per calendar month `m`, year `y` and cap `b` record:
   - `E_m,y(b)` — energy cost of the month
   - `P_real,m,y(b)` — realised month peak (`> b` where the cap was not holdable, i.e. slack used)
   - days with slack, and the per-day costs (kept for sampling in part 2)
3. Derive
   - `v̄_m(b) = mean_y (E_m,y(b) − E_m,y(b + Δ)) / (Δ · D_m)` plus its spread
   - **best static budget per month** `b*_m = argmin_b mean_y [E_m,y(b) + C(P_real,m,y(b))]` — the proposal for `import_cap_kw` per calendar month, and the spread of monthly peaks shown to the user (e.g. "January 6.8–9.1 kW")
4. Recompute after a relevant config change (battery, PV, consumers, tariff; key = config hash) and once a month when a new archive month is available. Runtime: `N · |grid|` SE year runs, parallel with `--workers`.

## Part 2 — Monthly budget loop (live, daily)

Runs after the day-ahead prices arrive and at midnight (month change: `P_m0` resets, loop restarts).

1. Candidates `b ∈ {max(P_m0, P_min), … + Δ, …}` up to a sensible limit.
2. Expected rest-of-month cost per candidate:

   ```
   J(b) = E[ C(max(P_m0, P_real(b))) ] + Σ_forecast days E_d(b) + Σ_sample days E_d(b)
   ```

   - **Forecast days** (weather forecast, known day-ahead prices, planned EV sessions): `E_d(b)` from the live MILP solved as a what-if for a few caps.
   - **Remaining days**: Monte Carlo over `S` samples, each built from blocks of 3–5 **consecutive** real days of the same calendar month from the archive years (keeps multi-day dull periods), with that day's weather, prices and load. Per-day costs and forced peaks come from the part-1 runs.
   - `P_real(b)` per sample: `b`, or higher where a sampled day cannot hold `b` (slack). If a sample is likely to force a higher peak anyway, saving below it is worth less — the expectation covers this.
3. `b* = argmin_b E[J(b)]`. Optional risk setting: minimise a quantile (e.g. P80) instead of the mean.
4. Equivalent marginal rule (useful as a check and for explaining the decision in the UI):

   > raise `b` by `Δ` while `c(b) · Δ ≤ Σ_remaining days v_d(b) · Δ`

Properties:

- `b* ≥ max(P_m0, P_min)` always: the reached peak and anything below the minimum are free.
- Early in the month `R` is large, a higher budget pays off more easily; towards month end the sum shrinks and the budget freezes.
- After a measured exceedance `P_m0` rises and the headroom up to it is used actively.
- User-facing output: budget `b*`, expected month peak, probability that `b*` holds until month end.

## Part 3 — Coupling to the MILP: effective capacity price

The backlog's MILP bullet uses a peak variable with ladder cost, the dev doc (5.2) a hard cap with slack. Both become special cases of one formulation:

- `P_peak ≥ p_grid_buy[t]` for all slots, `P_peak ≥ max(P_m0, P_min)`.
- No cost up to `b*` (accepted by the loop with the whole month in view).
- Above `b*`, a convex piecewise-linear cost with the **effective** price

  ```
  λ_eff(P) = max(0, c(P) − R_after · v̄_m(P))
  ```

  The MILP pays only the part of the ladder step that the days after its horizon do not earn back anyway. `v̄` falls with `P`, so `λ_eff` rises → convex, no binaries.
- Month end: `R_after = 0`, `λ_eff = c` — full ladder price (backlog formulation). A very high constant `λ` gives the hard cap of dev doc 5.2.
- Horizon across the month boundary: second peak variable for the new month, `P_m0 = 0`, its own `λ_eff` with the new month's `R_after` and `v̄`.
- Safety margin and the intra-quarter-hour control (dev doc 5.4) stay unchanged.

---

## Stages

| Stage | Content | Fits |
|---|---|---|
| **A** | Part 1 as best static budget per calendar month; MILP hard cap with slack and margin | dev doc L2/L3 |
| **B** | `v̄_m(b)` table and `λ_eff` with `R_after` in the MILP | after A |
| **C** | Part 2 with forecast days, block sampling and risk setting; UI output | after B |

## Open questions

- Is `E(b)` convex in `b` (i.e. `v̄` decreasing)? Check in the SE; otherwise fit a monotone curve before building `λ_eff`.
- Load for sample days: house profile model vs. measured `cons_data`; EV sessions as a statistic or from the user's schedule.
- Price normalisation across years (crisis years, rising grid fees): exclude years or rescale the level while keeping the shape.
- How many forecast days are reliable enough (Open-Meteo offers up to 16)?
- SE runtime of the sweep and cache key.
- Final SNE-T-V prices and minimum billing rules (Edibert research item).
