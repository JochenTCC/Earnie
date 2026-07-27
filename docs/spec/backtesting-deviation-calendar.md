# Backtesting — Abweichungs-Kalender (SE)

Replace the deviation table (`st.dataframe`) with a **12-month calendar navigator**. All in-run days are clickable and load Chart1/Chart2 below; deviation days are color-coded.

## Decisions

| Topic | Decision |
|-------|----------|
| Calendar bounds | Show **Jan–Dec** of `period.backtesting_year` (default `BACKTESTING_YEAR`). Days outside `period.start`…`period.end` are **disabled** (gray). Test-month runs show one active month. |
| Day key | Calendar cell date → `window_anchor_for_date(date)` → ISO anchor string (same rule as engine; EV `ready_by_hour` vs midnight-next-day). |
| In-run days | Date has a matching anchor in `list_simulation_anchors` for the log period (skip zero-load days). |
| Colors (worst wins if multiple scenarios) | **Red** — `milp_no_optimal`, `strict_slow`, `strict_fallback`. **Yellow (⚪)** — `consumption_tolerance` with relative `|diff|/historical ≤ CONSUMPTION_TOLERANCE_REL` (5%); abs `CONSUMPTION_TOLERANCE_KWH` (0.5 kWh) only when `historical_kwh` missing/≤0. **Orange** — `consumption_tolerance` above that. Feasible CBC with `window_consumption_ok` stays yellow. **Neutral** — in-run, no deviation. **Disabled** — outside run or no anchor. |
| Multi-scenario | Cell color = **worst** severity across scenarios. Detail area: **scenario checkbox list**. |
| Charts | Keep existing `render_deviation_detail` / SA-segment toggle for `sunset_window` logs. |
| Table | **Removed**; metadata (Art, Δ kWh, Szenario) stays in detail header/captions. |
| Scenarios | Radio list — deviation days marked with severity emoji at label. |
| Diagnose | `diag_single_window` CLI command + optional run from detail expander. |
| On-demand | Snapshot first; if missing, run single-window sim, **persist to JSONL**, session-cache. |

## Acceptance criteria

- Full-year log: single-month view with Zurück/Vor navigation; Jan deviation days colored; OK days clickable and load charts via on-demand sim when no snapshot exists.
- Test-month run: only one month has active (clickable) days.
- `fixed_24h` log: Chart1/2 without SA toggle.
- `sunset_window` log: SA segment toggle still works for detail charts.
- Red/orange/yellow days match prior table behaviour for the same window/scenario.

## Manual checks

1. **Greenfield full year (`s2-kein-pv`):** Jan days 2 & 7 show deviation colors; click OK day → charts load (~2–10 s first time, cached on rerun).
2. **Test-month run:** only selected month active; rest of year disabled.
3. **Horizon:** compare `fixed_24h` vs `sunset_window` logs — SA toggle only on sunset.

## Out of scope

- Timing-shift-only days (not in `critical_cases` today).
