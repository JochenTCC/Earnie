# Quarter-hour slots — migration study (Version 2.5)

**Status:** Implemented (decision B; phases **2.5.d–h**, 2026-08-11)  
**Date:** 2026-08-11  
**Backlog:** `2.5.a`–`2.5.h`  
**Related:** Research item “quarterly-hour EPEX / 15 min slots” closed; prior deferral **2.3.c.2**; check **2.3.2** closed via **2.5.c**

## 1. Decision options

| Option | Meaning |
|--------|---------|
| **A** | Stay on hourly MILP (`dt ≡ 1 h`). Optionally store native QH Day-Ahead prices for SE / billing fidelity. |
| **B** | Full optimizer on 15‑min slots (`dt_h = 0.25`). |
| **C** | Hybrid (e.g. QH prices on a coarser control / commit grid). |

Official EPEX SFTP/MATS remains **out of scope** (paid / license).

## 2. Decision (owner): **B**

**Chosen:** full MILP on 15‑min slots. Implementation phases: backlog **2.5.d**–**2.5.h**.

Desk study had **recommended A** (mixed tariff settlement, large blast radius, Live aWATTar-only). Owner overrode to **B**; light HiGHS probe showed Live-sized QH headroom (~0.6 s heavy stub). Study caveats in §§3–4 remain binding constraints for the implementation phases.

### Study recommendation (historical, not chosen)

Prefer A unless solver headroom *and* material QH settlement for main products justified B. Evidence: mixed aWATTar 60‑min vs VKW/Tibber QH; Live re-opt already 15 min on hourly plan; breakage list large; Live prices aWATTar-only today.

---

## 3. Data fidelity (2.5.a)

### 3.1 Energy-Charts native resolution (HTTP probe 2026-08-11)

API: `GET https://api.energy-charts.info/price?bzn=&start=&end=`

| Zone | Pre 2025-10 (~2025-09-28/29) | Post go-live (~2025-10-02/03) | Later sample |
|------|------------------------------|-------------------------------|--------------|
| **AT** | 48 pts, Δ=60 min | 192 pts, Δ=15 min | 2025-12-10/11: Δ=15 min |
| **DE-LU** | 48 pts, Δ=60 min | 192 pts, Δ=15 min | (2026-03 / 2026-07 windows returned API 404 “no content”) |
| **CH** | 48 pts, Δ=60 min | **still** 48 pts, Δ=60 min | 2026-03-15/16 and 2026-07-01/02: Δ=60 min |

SDAC Day-Ahead switched to 15‑min MTU for delivery from **2025-10-01** (EPEX / EU Commission). Energy-Charts reflects that for **AT** and **DE-LU**. **CH** on this free API remains hourly in the sampled windows (Swiss coupling / product packaging may differ; do not assume QH for CH SE).

**Mixed-resolution handling today:** `data/market_prices.py` → `normalize_price_slot` (floor to hour) and `epex_prices_for_slots` → `resample("h").mean()`. Pre-QH history (1 sample/h) and post-QH (4 samples/h) both collapse to one hourly mean. No special-case date split is required for current hourly MILP.

### 3.2 Live vs SE provider gap

| Path | Code | Notes |
|------|------|-------|
| SE / backtesting | `data/data_loader.py` `fetch_energy_charts_prices` | AT / DE-LU / CH; AT falls back to aWATTar on failure |
| Live | `integrations/awattar_client.py` via `main.py`, `ui/live_mode.py` | **aWATTar only** (hourly API) |

User docs ([`docs/konfiguration/preise.md`](../konfiguration/preise.md)) describe Energy-Charts for planning; Live prose still implies provider choice — **code path is aWATTar-only**. Fidelity finding for follow-up; not a blocker for A/B/C.

### 3.3 Catalog tariff settlement map

Catalog type is only `spot_hourly` ([`share/config/tariffs.json`](../../share/config/tariffs.json)). There is **no** `settlement_mtu` field. Classification below is from product notes / public marketing (spot-check 2026-08), not from Earnie runtime fields.

| Settlement | Catalog ids (representative) | Evidence |
|------------|------------------------------|----------|
| **Hourly / 60‑min product** | `awattar_at`, `de_awattar_de_hourly_de`, export `dynamic_epex` (SUNNY Spot) | aWATTar HOURLY: “24 Preise”, “EPEX Spot AT (60 min)”; SUNNY Spot **60 min** by name and Tarifblatt |
| **¼‑h EPEX** | `at_vkw_strom_dynamisch`, `at_vkw_pv_dynamisch`, `de_tibber_tibber_dynamic` | VKW: “Viertelstundenpreise EPEX Spot Day-Ahead AT”; Tibber: quarter-hourly product page post‑2025‑10 |
| **Likely hourly (name / notes)** | `at_aae_…_spot_stunde_ii`, `at_avia_…_stundenfloater`, export `at_smartenergy_smartsun_spot` (“Stuendlich…”) | Naming / notes; not re-verified on every Tarifblatt |
| **Unclear / assume market MTU** | Most other AT/DE/CH `spot_hourly` without notes | Day-Ahead market is QH for AT/DE-LU since 2025-10; supplier may still invoice hourly averages — **verify before treating as QH billing** |

CH catalog entries (`ch_ekz_…`, `ch_groupe_e_vario`): Energy-Charts CH series sampled as hourly → treat as **hourly** for Earnie SE until proven otherwise.

### 3.4 Billing vs plan mismatch (if MILP stays hourly)

If the household’s **invoice** uses native ¼‑h EPEX × ¼‑h meter energy (e.g. VKW, Tibber) while Earnie:

- collapses Day-Ahead to **hourly mean**, and
- plans / scores on **1 h** slots,

then:

| Layer | Behaviour | Mismatch |
|-------|-----------|----------|
| Plan objective | Uses hourly-mean `k_act` | Misses intra-hour price shape (sawtooth) |
| Fake invoice / SE cost | Same hourly prices × hourly energy | Can diverge from supplier QH bill |
| Live control | Re-opt every 15 min, still one price per clock hour | Current-hour setpoint can change; price signal inside the hour is flat |

For **aWATTar HOURLY / SUNNY 60 min**, plan and bill share hourly grain → mismatch is small (API vs Energy-Charts source differences aside).

OeMAG / E-Control RefMarkt: still **monthly** aggregates; E-Control notes QH market inputs but hourly aggregates while EAG requires hours — see [`docs/referenz/oemag-referenzmarktwert.md`](../referenz/oemag-referenzmarktwert.md).

---

## 4. MILP / horizon impact (2.5.b)

### 4.1 Implicit `dt ≡ 1 h` touchpoints

Energy in one slot is treated as **power × 1 h** (kW → kWh). Moving to `dt_h = 0.25` requires multiplying energy/cost/wear contributions by `dt_h` (or equivalent) everywhere below.

| Concern | Location | Today |
|---------|----------|--------|
| Battery SoC | `optimizer/milp_horizon.py` `_build_milp_model` | `e_batt[t] = … + p_charge*η − p_discharge/η` (no `dt_h`) |
| Import / export objective | `_add_milp_objective` | `Σ p_grid_buy[t]*k_act − p_grid_sell[t]*k_push` |
| Battery wear | same + `optimizer/battery_wear.py` | `wear * Σ (p_charge + p_discharge)` |
| Flex delivery energy | `optimizer/milp_consumers.py` `_delivery_energy_expr` | `Σ p[t]` or `charge_kw * on[t]` |
| `min_on_quarterhours` | `add_min_on_time_constraints`, `_min_on_hours` | Coarsened: `max(1, (qh+3)//4)` **hours** |
| Thermal `max_on` / day target | `optimizer/thermal_flex_context.py` | `max_on_quarterhours // 4`; proration `/ 24.0` |
| EV hours / slots | `optimizer/charging_context.py` `hours_needed_to_deliver`; `optimizer/eauto_milp.py` | Wall-clock hours ↔ slot count 1:1 |
| Generic min energy | `optimizer/targets.py` | `nominal_power_kw * min_hours` |
| Price indexing | `data/market_prices.py` `normalize_price_slot` | Floor to `:00` |
| Horizon slots | `data/planning_window.py` `hourly_slots_inclusive` | `timedelta(hours=1)` |

Config names already use quarter-hours; MILP currently **throws away** that resolution.

### 4.2 Size estimate

| Mode | Typical hourly slots | At `dt_h=0.25` |
|------|----------------------|----------------|
| Live sunrise window (~SA₀→SA₂) | ~40–50 | ~160–200 |
| SE `sunrise_window` | same order | ~4× |
| Variables / constraints | ~N | ~4×N |

`simulate_horizon(..., commit_hours=K)` and SE defaults (`DEFAULT_BACKTESTING_COMMIT_HOURS`) are **wall-clock hours**. Under QH slots, either keep K as hours (commit 4K slots) or rename to avoid slot/hour confusion.

Horizon semantics: MILP end is **sunrise SA₂**, not sunset — [`docs/spec/planning-horizon-sunset.md`](planning-horizon-sunset.md) §2.3 still documents hourly grain.

### 4.3 Light HiGHS timing probe (2026-08-11)

Environment: `EARNIE_MILP_SOLVER=highs`, trivial fast-path off. Synthetic matrix; default solver time/gap limits unchanged (`optimizer/cbc_solver.py`: strict ~3 s, gap 10 %).

| Case | Slots | Wall time |
|------|-------|-----------|
| Battery only | 48 / 192 | 0.04 s / 0.13 s |
| Battery + EV + 1 generic | 48 / 192 | 0.08 s / 0.39 s |
| Battery + EV + 3 generics (heavier) | 48 / 192 | 0.27 s / 0.62 s |

**Takeaway:** Live-sized QH MILP stays well under the strict time budget in this stub. SE open-loop year cost would still rise ~4× *number of solves* × slower per solve — not measured here (desk depth only).

### 4.4 Breakage list for full B

| Surface | Paths / notes |
|---------|----------------|
| `cons_data` | Hourly CSV + hour flush (`data/cons_data_store.py`, `main.py`) |
| PV forecast | `data/pv_forecast.py` — hourly watts map |
| Outdoor / archive PV | `data/outdoor_forecast.py`, `data/open_meteo_solar_archive.py` |
| Price features | `docs/spec/price-forecast-renewables.md` — EC 15‑min → hourly mean for features |
| Charts | Mixed 15‑min log + 1‑h MILP (`ui/chart_context.py`, `docs/spec/ui-sunset2sunset.md`) — would need redefinition if MILP becomes QH |
| Loxone write cadence | Can remain 15 min regardless of MILP grain; **doc drift:** [`docs/referenz/loxone-signals.md`](../referenz/loxone-signals.md) claims “MILP … 15-Min-Slots intern” — **false today** |
| SE commit-K / scripts | `optimizer/simulation.py`, `scripts/run_commit_hours_backtests.py` |

---

## 5. Implementation carve (decision B)

Open backlog (same MINOR **2.5**):

| Phase | Scope |
|-------|--------|
| **2.5.d** | Explicit `dt_h` (SoC, objective, wear, delivery energy) |
| **2.5.e** | Prices & planning window QH; Live Energy-Charts (aWATTar hourly fallback) |
| **2.5.f** | Flex: `min_on_quarterhours` as real slots; thermal/generic |
| **2.5.g** | `cons_data`, forecasts, charts, SE `commit_hours` |
| **2.5.h** | Soak tests + German user-doc note |

Rejected for this cycle: **A** (hourly-only) and **C** (hybrid without a separate grid contract).

---

## 6. Probe / source appendix

- Energy-Charts probes: AT/DE-LU/CH windows listed in §3.1 (rate limits 429 occurred; retries succeeded for core pre/post pairs).
- Tariff pages: [aWATTar HOURLY](https://www.awattar.at/tariffs/hourly), [SUNNY Spot 60 min](https://www.awattar.at/tariffs/sunnyspot), VKW Strom Dynamisch (Viertelstunden), [Tibber quarter-hourly](https://tibber.com/en/quarter-hourly-electricity-prices).
- EPEX SDAC 15‑min MTU: delivery day 2025-10-01.
- Code anchors: `normalize_price_slot`, `milp_horizon._build_milp_model`, `milp_consumers.add_min_on_time_constraints`.
