---
name: SOC plausibility Chart1
overview: "Rewrite 2.3.c’s user-facing slice for Live Monitor Chart 1: explain SOC gaps with a short caption/help, a third “same-flex” SOC line from existing `baseline_same_flex_rows`, and outline (“ghost”) bars for matched/standard flex charging — SE/backtesting and the terminal/weekend research bullets stay separate."
todos:
  - id: backlog-rewrite
    content: Rewrite 2.3.c user-facing bullets (Live Monitor 1D; research bullets kept separate)
    status: completed
  - id: persist-same-flex
    content: Persist/load baseline_same_flex_rows in live debug snapshot + display loader + Cockpit wiring
    status: completed
  - id: third-soc-line
    content: Add SoC bei Opt-Last trace in chart_soc.py; wire through charts.py Live path
    status: completed
  - id: ghost-bars
    content: Add outline ghost bars from matched-baseline flex kW on Chart 1 flow balance
    status: completed
  - id: help-docs-tests
    content: German Chart-1 help/caption + docs/ui/charts.md + unit tests for persist and chart helpers
    status: completed
isProject: false
---

# 2.3.c — Live Monitor SOC plausibility (1D)

## Decisions (locked)

- **UX package D:** Chart-1 caption/`?` text + third SOC line + ghost EV/flex bars
- **Surface:** Live Monitor / Cockpit only (not Scenario Explorer / backtesting charts)
- **Research bullets** (remove terminal SOC constraint; weekend `ready_by=12:00`) remain under `2.3.c` but are **out of scope for this implementation**

## Mental model (what we show)

```mermaid
flowchart LR
  blZiel["SoC BL Ziel<br/>profile flex + PV-surplus batt"]
  sameFlex["SoC bei Opt-Last<br/>opt flex + PV-surplus batt"]
  optSoc["SoC<br/>opt flex + MILP batt"]
  blZiel -->|"flex timing"| sameFlex
  sameFlex -->|"battery policy"| optSoc
```

Ghost bars = matched/profile flex power (outline) next to filled optimized flex bars — visual for the left arrow only.

## Backlog text (update when implementing)

Replace the vague bullets under **2.3.c** (lines 22–25) with something like:

- Live Monitor Chart 1: explain why **SoC** diverges from **SoC BL Ziel** (Lastverschiebung + andere Batteriestrategie)
- Third SOC line **SoC bei Opt-Last** from `baseline_same_flex_rows` (opt flex, BL battery), from Jetzt onward, same anchoring rules as BL Ziel
- Ghost outline bars for matched/BL-Ziel flex schedule (EV first; other active flex if columns exist) vs filled optimized bars
- Chart-1 `?` / caption in German; update [`docs/ui/charts.md`](docs/ui/charts.md)
- Keep separate: terminal-SOC backtest experiment; weekend noon ready-by check

## Data plumbing (required)

`calculate_optimization_savings` already returns `baseline_same_flex_rows`, but live persistence currently drops it.

1. Persist in [`runtime_store/live_optimization_debug.py`](runtime_store/live_optimization_debug.py) (`build_debug_payload`) and pass from [`main.py`](main.py) + opt-in path in [`ui/live_mode.py`](ui/live_mode.py)
2. Reconstruct in [`runtime_store/live_display_loader.py`](runtime_store/live_display_loader.py) (`savings_info_from_snapshot`)
3. Thread `same_flex_df` through display bundle → [`ui/charts.py`](ui/charts.py) `build_power_soc_chart_figure` / `render_power_soc_chart` (Live Cockpit path only; SE callers leave `None`)

Graceful degrade: if snapshot is old and lacks same-flex rows, draw existing two SOC lines + caption without the third line / without claiming the mid-counterfactual.

## Chart 1 — third SOC line

Extend [`ui/chart_soc.py`](ui/chart_soc.py):

- New helper mirroring `add_baseline_soc_traces` (reuse anchor-at-Jetzt, segment/ramp helpers)
- Style: same `COLOR_SOC`, distinct dash (e.g. `dashdot`), slightly thinner or lower opacity so solid SoC stays primary
- Legend name: **SoC bei Opt-Last** (short; full meaning in help text)
- Only from **Jetzt** onward (same as BL Ziel)

## Chart 1 — ghost bars

Extend [`ui/chart_flow_balance.py`](ui/chart_flow_balance.py) (or a small sibling helper):

- Input: matched-baseline consumer kW columns (same IDs as optimized flex stack)
- For each active flex consumer with non-zero matched kW in a future slot: draw **outline-only** bar (transparent fill, thick edge in that consumer’s palette color), aligned with existing down-stack geometry
- Prefer EV first if clutter is high; include other flex when columns are present and stack remains readable
- Hover: e.g. `BL-Ziel-Last … kW` so it is not confused with optimized bars
- Do **not** change optimized filled bars / hatching

## Caption / help (German)

- Extend [`ui/history_navigation.py`](ui/history_navigation.py) `s2_zone_help_text()` (or Live-only caption under Chart 1 in [`ui/live_mode.py`](ui/live_mode.py) / chart header) with 2–4 short sentences:
  - BL Ziel = gleiche Flex-Energie, Profilform, Batterie nur PV-Überschuss
  - SoC bei Opt-Last = Optimierungs-Lastzeiten, dieselbe Batterieregel → zeigt Lastverschiebung
  - Abstand Opt-Last → SoC = andere Batteriestrategie (Netzladen / Entladen)
  - Ghost bars = wo Flex laut BL-Ziel gelaufen wäre
- Keep help chart-focused; no SE wording

## Docs + tests

- [`docs/ui/charts.md`](docs/ui/charts.md): document the three SOC traces + ghost bars
- Tests: persist/load round-trip for `baseline_same_flex_rows`; chart helper unit tests that third trace / ghost segments appear when data present and are skipped when absent
- No SE chart changes; no terminal-SOC / weekend research in this PR/slice

## Explicit non-goals

- Scenario Explorer / backtesting Chart 1
- Auto-narrative of “EV moved X kWh from … to …” (optional later)
- Changing MILP constraints or horizon modes
- `version.py` bump
