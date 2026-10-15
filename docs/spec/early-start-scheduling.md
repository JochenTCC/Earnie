# Early-start scheduling — compute before the tick, commit on the tick

**Status:** Draft (design, not implemented)  
**Date:** 2026-10-15  
**Backlog:** epic **EarlyStart** P0–P1 + follow-ups (Version 2.7 in `backlog/Backlog.md`, after the profiling item)  
**Related:** `docs/spec/quarter-hour-slots.md`, `optimizer/schedule.py`, `runtime_store/cycle_timing.py`, `main.py`

## 1. Problem

The live cycle in `main.py` starts on the quarter-hour tick (`seconds_until_next_quarter_hour`) and currently takes ~4 min end-to-end. Setpoints therefore reach the backend at ~T+4 min:

- for ~4 of 15 min (≈27 %) the slot runs on the *previous* cycle's setpoints, planned for a different slot and price;
- the decision for slot `[T, T+15)` is effectively applied to `[T+4, T+19)` and bleeds into the next slot.

Goal: start each regular cycle early enough that the result is ready **before** tick `T`, and apply it **exactly at** `T`. The lead time must adapt to the platform (Raspberry Pi vs. NUC vs. dev PC) and to known expensive events (forecast refreshes, new day-ahead prices).

## 2. Market facts — is there an official tick?

Yes. The relevant boundary is the start of a quarter-hour delivery period at `hh:00`, `hh:15`, `hh:30`, `hh:45` local time.

| Fact | Detail |
|------|--------|
| SDAC day-ahead MTU | 15 min since delivery day **2025-10-01** (trading day 2025-09-30). 96 delivery periods per normal day (92/100 on DST days). Periods start on the full quarter-hour. |
| Day-ahead timing | Gate closure 12:00 CET on D-1; results typically ~12:45–13:00 (go-live day: 13:08). Prices are known 11–35 h ahead, so the tick is about *delivery*, not price publication. |
| Intraday (SIDC) | 15-min products on all borders since October 2025, same grid. |
| Imbalance settlement / smart meter | 15-min settlement period on the same grid; a smart meter's (iMSys) quarter-hour values are aligned to it. |
| Timezone | CET/CEST offsets are whole hours, so the quarter-hour grid is identical in UTC and local time. DST days only change the slot count. |
| Tariff caveat | Some catalog tariffs still settle hourly (`settlement_mtu = "60min"`, see `quarter-hour-slots.md` §3.3). Their *price* changes only at `hh:00`, but the plan grid, meter intervals and battery accounting stay on 15 min. The tick stays the quarter-hour. |

Consequence: the "official tick" is the quarter-hour boundary of the system clock, provided the host is NTP-synchronised. **Early start depends on clock accuracy**; a clock skew check (§7.5) belongs to the design.

## 3. Current cycle — what is anchored to "now"

Starting the existing cycle earlier is **not** a pure scheduling change. Several steps implicitly assume `now ∈ [T, T+15)`:

| Step (main.py / module) | Assumption today | Impact of early start |
|-------------------------|------------------|-----------------------|
| `power_interval_sampler.finalize_closed_interval(previous_slot)` | previous slot `[T-15, T)` is already closed | Slot is still open at `T-L` → wrong or partial interval |
| `pv_tuner.get_pv_delta_and_update()` | PV meter delta covers the closed interval | Delta would cover a partial interval |
| `ehal_live.read_ess_soc()` → `current_soc` | SoC at slot start | SoC at `T-L` ≠ SoC at `T` (battery keeps running on old setpoint) |
| `compute_live_planning_window()` → `quarter_hour_slot_start(now)` | row 0 = current slot | row 0 would be `[T-15, T)` instead of `[T, T+15)` |
| `current_hour = datetime.now().hour` | hour of current slot | wrong hour at `hh:4x` → `hh+1:00` |
| live snapshot → `apply_live_snapshot_to_matrix(..., hour_index=0)` | snapshot describes row 0 | still a reasonable persistence forecast for `[T, T+15)`, just 1–4 min older |
| `writes` phase | setpoints apply immediately | must **not** apply before `T`, otherwise the *current* slot is changed early |
| `run_state.completed_at` / `schedule.completed_at_in_current_slot` | completion lies inside the slot it was computed for | completion at `T-ε` lands in the previous slot → `app.py` waits / shows stale data |
| `pv_forecast` 15-min API guard (`_LAST_API_CALL < 15 min`) | runs are exactly 15 min apart | variable lead → spacing occasionally < 15 min → forecast.solar fetch skipped every other run |

`compute_live_planning_window(now=...)` already accepts an explicit timestamp, which keeps the anchoring change small.

## 4. Design overview

Split every regular cycle into three parts with a clear time contract:

```
            T-L                      T-L+d          T-δ   T                    T+15-L'
 ───────────┬────────────────────────┬──────────────┬────┬──────────────────────┬──────
            │ PREPARE + SOLVE        │   HOLD       │ CHK│ COMMIT + BOOKKEEPING │ next PREPARE
            │ (anchored to slot T)   │ (idle/poll)  │    │ (writes, closed int.)│
```

1. **Prepare + solve** (starts at `T - L`): read telemetry, project state to `T`, fetch/refresh inputs, build the matrix with row 0 = `[T, T+15)`, run MILP. Result = a *staged plan* (setpoints + plan + metadata). Nothing is written to the backend.
2. **Hold**: wait for `T` with the existing `wait_until_next_run` polling (sampler ticks, `Earnie_Request_Optimize`).
3. **Pre-commit check** (`T - δ`, δ ≈ 2 s): cheap re-read of SoC. If the drift vs. projection exceeds a threshold, or the staged plan is invalid, follow §6.
4. **Commit at `T`**: execute the `writes` phase with the staged setpoints, then the bookkeeping that needs the closed interval: `finalize_closed_interval([T-15, T))`, `pv_tuner` delta, `cons_data`, `cycle_recorder`, `optimization_history`, `run_state` (with `target_slot = T`).

Out-of-band runs (`TRIGGER_REQUEST_OPTIMIZE`) keep today's behaviour: anchored to the current slot, written immediately.

### 4.1 State projection to T

The plan for `[T, T+15)` needs the SoC at `T`, not at `T-L`:

```
soc_T = soc_now + (P_ess_measured_kw × η(sign) × (T - now)_h) / capacity_kwh × 100
```

- `P_ess_measured_kw` from the live telemetry already read for the snapshot (better than the previous plan's setpoint, because it reflects reality incl. limits).
- Use the existing conversion-loss parameters (`docs/spec/conversion-losses.md`) for η; clamp to [SoC_min, SoC_max] per ESS.
- Multi-ESS: project `current_soc_by_id` per ESS.
- Thermal storages and EV SoC: same pattern where a live power reading exists; otherwise no projection (L ≤ a few minutes keeps the error small). Listed explicitly in the implementation backlog, not silently skipped.

### 4.2 Closed interval and learning data

The bookkeeping that needs `[T-15, T)` closed moves to the commit step. It is I/O-light (file appends), so it does not delay the writes noticeably. The *previous* cycle's closed interval is not needed for the solve itself except for SoC plausibility (`closed_interval_confirms_reported`), which then uses `[T-30, T-15)` plus the live SoC — acceptable, as the plausibility logic is a sanity check, not an input to the MILP.

## 5. Lead-time estimation (the statistics part)

### 5.1 Always-on duration recording

**Implemented in EarlyStart P0.** `runtime_store/cycle_duration_stats.py` appends one record per `main()` cycle to `runtime/cycle_stats.jsonl` (rolling 7 days, pruned at most once per day). It is independent of the env-gated profiling in `runtime_store/cycle_timing.py` (`EARNIE_CYCLE_TIMING`, phase times): the profiling code can be removed without touching this module. Phase times are a profiling concern; the estimator needs totals, events and punctuality only.

```json
{
  "tick": "2026-10-15T09:15:00.000",
  "trigger": "quarter_hour",
  "outcome": "ok",
  "woke_at": "2026-10-15T09:16:10.204",
  "started_at": "2026-10-15T09:16:13.020",
  "writes_done_at": "2026-10-15T09:17:57.410",
  "finished_at": "2026-10-15T09:19:35.180",
  "wake_delay_sec": 70.204,
  "start_delay_sec": 73.02,
  "duration_sec": 202.16,
  "late_by_sec": 177.41,
  "on_time": false,
  "events": ["weather_fetch"],
  "horizon_slots": 186,
  "version": "2.7.0-dev.54",
  "platform": "3f9c0a1b2d4e"
}
```

- `tick` = start of the slot the cycle computes for (today: the slot it starts in; with EarlyStart P1: the target slot).
- `outcome`: `ok` (setpoints written), `no_writes` (cycle returned early, e.g. no SoC / no prices), `error` (exception).
- `platform` = hash of CPU model, CPU count, machine, Python version and MILP solver + version. Hostname is left out (Docker gives each recreated container a new one); the Earnie version is a separate field so the estimator can decide whether an update resets its statistics.
- MILP status is not recorded in P0; the solver-deadline follow-up (§6.1) adds it where it needs it.

### 5.2 Events (known causes of slow cycles)

Each data source reports whether this cycle hit the network or the cache. The scheduler can *predict* most of them for the next run, because the cache TTLs are known:

| Event | Source | Predictable? |
|-------|--------|--------------|
| `pv_forecast_fetch` | `data/pv_forecast.py` (15-min guard, 429 back-off) | yes — last call time + guard |
| `weather_fetch` | `data/outdoor_forecast.py` (`_CACHE_TTL` 30 min) | yes |
| `price_feature_refresh` | `data/price_forecast_live.py` (`LIVE_FEATURE_CACHE_TTL_SEC` 45 min) | yes |
| `day_ahead_refresh` | `data/live_market_prices.py` (new auction ~12:45–13:00, cache staleness) | yes (time window) |
| `cold_start` | first cycle after process start (imports, caches empty) | yes |
| `month_rollover` | `profile_manager.check_and_update_profile_if_new_month` | yes |
| horizon length | sunset horizon varies over the day | yes — `compute_live_planning_window(T)` is cheap |

### 5.3 Estimator

Use a **high quantile**, not the mean — the cost of a miss (late setpoints) is higher than the cost of starting a minute too early (slightly older telemetry).

Two stages:

**Stage 1 (simple, robust):**

```
L = clamp( Q95(duration of last N regular cycles) × (1 + m) + s,  L_min, L_max )
```

- N = 96 (one day), m = 0.15 relative margin, s = 15 s fixed margin (pre-commit check, writes jitter).
- Fewer than 8 samples → conservative bootstrap `L = L_max_bootstrap` (e.g. 300 s) — explicit, logged, never silent.

**Stage 2 (event-aware):**

```
L = base_Q95(horizon bucket) + Σ_e∈predicted_events extra_Q90(e) + s
```

- `base` = cycles without network events, bucketed by `horizon_slots` (e.g. bins of 24 slots).
- `extra(e)` = observed duration minus base median for cycles with event `e` (quantile per event).
- Fallback to Stage 1 per bucket while it has too few samples.

### 5.4 Continuous re-evaluation and adaptation

- The lead is recomputed **after every cycle**, before scheduling the next start.
- **Fast attack / slow decay:** after a deadline miss, raise `L` immediately to `observed_duration × 1.2 + s`; afterwards let it sink towards the estimator value by at most e.g. 10 s per cycle. Prevents oscillation between "just in time" and "late".
- **Platform fingerprint:** hash of hostname, CPU count, CPU model, Python version, solver + version, Earnie version. On change, old samples get weight 0 (or are kept but marked) → bootstrap again. Earnie updates can change runtime, so the version is part of it.
- **Exponential age weighting** (half-life ~2 days) inside the quantile so gradual drifts (more consumers, seasonal horizon) are followed.

### 5.5 Bounds and guard rails

| Parameter | Proposal | Reason |
|-----------|----------|--------|
| `L_min` | 20 s | pre-commit check + writes |
| `L_max` | 600 s | beyond that, telemetry is too old; log **warning** "platform too slow for 15-min cycle" and surface it in the UI |
| sequencing | next start ≥ previous commit + 5 s | a cycle never overlaps the previous one |
| `L + duration > 15 min` | impossible to hit | fall back to "late mode" (today's behaviour) with a loud warning |

### 5.6 Punctuality log

Every regular cycle records how late its setpoints reached the backend, in early-start mode and in today's mode alike:

- `late_by_sec = committed_at − T` (≤ 0 means on time), `on_time = late_by_sec ≤ tolerance` (proposal: 2 s for write jitter).
- One log line per cycle, plus a rolling summary (on-time rate, P95 lateness) over 24 h and 7 d.

Today's mode gives the baseline (~0 % on time, ~240 s late). The summary shows whether early start works on a platform (§9). It replaces a separate shadow phase: a miss in early-start mode writes late, which is exactly today's behaviour, so the live run cannot do worse than the baseline.

## 6. Deadline handling and pre-commit check

| Situation at `T` | Action |
|------------------|--------|
| plan ready, SoC drift ≤ threshold (e.g. 3 %-pt.) | commit staged plan at `T` |
| plan ready, drift > threshold | commit staged plan anyway (it is still better than the old one) **and** trigger an out-of-band re-run anchored to `T` |
| plan not ready | keep the previous setpoints, commit as soon as the solve finishes (= today's behaviour), record `deadline_missed`, fast-attack the lead |
| `Earnie_Request_Optimize` during HOLD | discard staged plan, run out-of-band immediately (today's behaviour) |
| solve failed / no prices | as today: log error, no writes |

### 6.1 Solver deadline (optional, strong guarantee)

`optimizer/cbc_solver.py` already supports time limits (strict stage + `gapRel`). The scheduler can pass a deadline `T - δ - now - writes_reserve` to the HiGHS stage so a slow solve returns the best incumbent instead of missing the tick. Only if the status is a feasible incumbent; otherwise the deadline-miss path applies. This must be visible in the log and `milp_status` — not a silent quality drop.

## 7. Affected code (implementation sketch)

### 7.1 `optimizer/schedule.py`

```python
def next_tick(now: datetime | None = None) -> datetime: ...          # = next_quarter_hour_datetime
def run_start_for_tick(tick: datetime, lead_sec: float) -> datetime: ...
def target_slot_for_regular_run(now: datetime, lead_sec: float) -> datetime:
    """Slot the next regular run computes for (the tick the run will commit on)."""
```

`completed_at_in_current_slot` gets a sibling that compares a stored `target_slot` key instead of the completion timestamp.

### 7.2 New `optimizer/start_scheduler.py`

```python
@dataclass(frozen=True)
class StartDecision:
    tick: datetime
    start_at: datetime
    lead_sec: float
    reason: str          # "stage1_q95" | "stage2_events" | "bootstrap" | "fast_attack" | "late_mode"
    predicted_events: tuple[str, ...]

def decide_next_start(now: datetime, stats: DurationStats, *, mode: str) -> StartDecision: ...
```

Pure function on top of the stats → unit-testable without clock or I/O.

### 7.3 `main.py`

- `_main_cycle` is split into `prepare_and_solve(target_slot) -> StagedPlan` and `commit(staged, closed_interval)`.
- All `now`-derived anchors in the solve path use `target_slot` (`compute_live_planning_window(now=target_slot)`, `current_hour = target_slot.hour`).
- Daemon loop: `decision = decide_next_start(...)`; wait until `decision.start_at`; solve; wait until `decision.tick - δ`; check; wait until `tick`; commit; record stats.

### 7.4 Data modules

- `pv_forecast`: replace the "≥ 15 min since last call" guard by "at most one live call per target slot" (or 14 min), so variable start times do not suppress every other fetch.
- `pv_forecast`, `outdoor_forecast`, `price_forecast_live`, `live_market_prices`: expose `will_refresh(at: datetime) -> bool` and report `fetched_live` per call → events list.

### 7.5 Clock check

On startup and hourly: compare system time with an HTTP `Date` header of an already used endpoint (Energy-Charts / ENTSO-E) or `timedatectl` status on Linux. Skew > 2 s → warning; > 10 s → early start disabled (late mode) until fixed. No silent correction.

### 7.6 `app.py` / UI

- `run_state` stores `target_slot` and `committed_at`; UI sync uses the slot key.
- Cockpit shows: current lead, last duration, P95, deadline misses (24 h), platform-too-slow warning.

## 8. Complementary measure: move I/O out of the critical path

Most of the variance comes from network fetches. During the HOLD/idle phase after a commit, a **prefetch** step can refresh the caches that will expire before the next run (`will_refresh(next_start)`). The next solve then sees warm caches, the event surcharge disappears, and `L` shrinks to roughly `base_Q95`. This is independent of early start and can be implemented first if quick wins are wanted.

Before tuning either, run one day with `EARNIE_CYCLE_TIMING=1` on the target platform: if ~4 min is dominated by `milp_live`, the solver deadline (§6.1) and model size matter most; if by `prices_matrix`/`ehal_read`, prefetch (§8) is the bigger lever.

## 9. Rollout

`EARNIE_EARLY_START` is a new environment variable (values `on` | `off`). Unset means `on`; `off` = today's behaviour (start on the tick, write when ready).

| Phase | Mode (`EARNIE_EARLY_START`) | Behaviour |
|-------|-----------------------------|-----------|
| **EarlyStart P0** | — (variable does not exist yet) | Always-on duration, events and punctuality recording (§5.1, §5.2, §5.6). No scheduling change; records today's baseline. |
| **EarlyStart P1** | `on` (default) | Lead estimator (§5.3 Stage 1, §5.4, §5.5), split cycle with commit at tick (§3, §4), deadline-miss path (§6), German user docs. Estimator checked by replaying P0 records offline before release. |

No shadow and no gate phase (owner decision 2026-10-15): a missed tick writes late, which is today's behaviour, so early start cannot do worse than now. Success is judged from the punctuality log (§5.6) in `earnie.log`.

Follow-ups (separate backlog items, not phases): event-aware estimator (§5.3 Stage 2, needs `will_refresh(at)` from §7.4), solver deadline (§6.1), prefetch (§8), thermal/EV projection (§4.1), pre-commit SoC drift check (§6), clock-skew check (§7.5), cockpit display (§7.6).

## 10. Tests

- `start_scheduler`: bootstrap, Q95, event surcharges, fast attack / slow decay, bounds, platform change, `L + d > 15 min` → late mode.
- `schedule`: target slot across `hh:45 → hh+1:00`, midnight, DST switch days (92/100 slots).
- SoC projection: charge/discharge with η, clamping, multi-ESS.
- `main` loop with fake clock: commit happens at `T`, not at `ready_at`; out-of-band trigger during HOLD discards the staged plan; deadline miss path writes late and records the miss.
- `pv_forecast` guard: run spacing of 14:30 min still fetches once per slot.
- Punctuality log: `late_by_sec` / `on_time` for on-time commit, late commit and out-of-band runs (excluded from the rate); rolling 24 h / 7 d summary.
- Estimator replay: recorded P0 durations through `decide_next_start` give the expected on-time rate before `on` is switched.

## 11. Open questions

1. SoC drift threshold for the re-run (§6): fixed %-pt. or relative to slot energy?
2. Should the solver deadline (§6.1) be enabled by default, or only after a miss?
3. Thermal/EV projection: required for **EarlyStart P1** or acceptable as follow-up?
4. Where is the ~4 min spent on the target platform? (**EarlyStart P0** data decides between §6.1 and §8 as the first lever.)

## Sources

- EPEX SPOT: [15-minute products live in EPEX SPOT day-ahead markets](https://www.epexspot.com/en/news/15-minute-products-live-epex-spot-day-ahead-markets)
- EPEX SPOT: [Market coupling steering committee confirms go-live of 15-minute MTU in SDAC (trading day 30 Sept)](https://www.epexspot.com/en/news/market-coupling-steering-committee-confirms-go-live-15-minute-mtu-sdac-trading-day-30)
- EPEX SPOT: [15' MTU in SDAC (2025-04-17)](https://www.epexspot.com/sites/default/files/download_center_files/2025-04-17_EPEXSPOT_15%27MTU%20in%20SDAC_FINAL_final.pdf)
- PwC: [Introduction of 15-minute intervals in day-ahead trading](https://blogs.pwc.de/en/auf-ein-watt/article/247689/weiterentwicklung-des-europaeischen-strommarkts-die-einfuehrung-von-15-minuten-zeitintervallen-im-day-ahead-handel/)
