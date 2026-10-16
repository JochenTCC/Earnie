# Early-start scheduling — compute before the tick, commit on the tick

**Status:** v2 — EarlyStart P0 + P1 implemented (2026-10-15)
**Date:** 2026-10-15
**Backlog:** epic **EarlyStart** (P0, P1 → `backlog/Backlog-Erledigt.md`; follow-ups in `backlog/Backlog.md`, Version 2.7)
**Related:** `docs/spec/quarter-hour-slots.md`, `optimizer/start_scheduler.py`, `runtime_store/planning_clock.py`, `runtime_store/cycle_duration_stats.py`, `main.py`

## 1. Problem and goal

The live cycle used to start on the quarter-hour tick `T`, so setpoints for `[T, T+15)` reached the backend only after the cycle finished. Goal: start each regular cycle so that its plan is ready **at** `T` and write it at `T` — never before. The written setpoints should have **minimal age in both directions**: a plan ready long before `T` is built on old telemetry; a plan ready after `T` leaves the slot on the previous setpoints.

Measured on the owner NAS (EarlyStart P0 log, 2026-10-15):

| Version | Cycle | Setpoints after `T` | Notes |
|---------|-------|---------------------|-------|
| `2.7.0-dev.54` | ~212 s | +3…4 min, plus 66–73 s wake drift | ~810 thermal year simulations per cycle; wait-loop drift bug |
| `2.7.0-dev.57` | 12–19 s | +8…16 s | wake drift fixed (`wake_delay_sec` < 0.1 s) |
| `2.7.0-dev.57`, 13:00 | 76 s | +72 s | network only: ENTSO-E 17 s, two Open-Meteo calls 24 s + 22 s |

The remaining lateness is short and dominated by network I/O. P1 therefore keeps the design minimal: an adaptive lead of 15–90 s and **no state projection** to `T` (owner decision 2026-10-15). With ≤ 90 s lead, the SoC read at `T − L` differs from the SoC at `T` by at most ~0.1 kWh at 5 kW.

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

Consequence: the "official tick" is the quarter-hour boundary of the system clock, provided the host is NTP-synchronised. Clock accuracy is a requirement of the quarter-hour operation as a whole, not of early start: the hold (§4) writes at the system-clock tick, exactly like a cycle started on the tick, so a skewed clock shifts both by the same amount. The optional skew measurement (§7) is diagnostics only.

## 3. What is anchored to "now"

Starting before `T` is not only a scheduling change: many steps derive the slot, hour or day from the clock. Inside an early-started cycle these must refer to `T`, not to the slot the cycle runs in.

**Planning clock** (`runtime_store/planning_clock.py`): `main()` runs the cycle inside `planning_anchor(T)`. `planning_now(tz)` returns `max(datetime.now(tz), T)` — frozen at `T` until the tick, real time afterwards (a late cycle stays in slot `T`). Outside an anchor it is plain `datetime.now(tz)`.

| Uses `planning_now` (plans for `T`) | Keeps the real clock (measures) |
|--------------------------------------|----------------------------------|
| `schedule._normalize_now` → slot start / slot key / timing key | PV integral (`pv_tuner`) |
| `compute_live_planning_window`, `current_hour` (`main.py`) | power-interval sampler ticks |
| day-ahead price window (`awattar_fetch_window`, `_now_slot`) | cons_data samples |
| daily consumer targets, `optimizer.targets` | API guards / cache TTLs (`pv_forecast` 15-min guard, Open-Meteo cache) |
| PV forecast target hours, outdoor / tilted irradiance start, price-feature "yesterday", EU market forecast days | write / push timestamps |
| Live thermal plans (collector irradiance, house plan start) | `run_state` / history timestamps (written after `T`) |
| EV charging sessions / schedules, appliance schedules, delivery "today" | |

Rule for new code in the Live path: derive "now" for *planning* from `planning_now()` (or from matrix row 0); use `datetime.now()` only for measurements, timestamps and **external API semantics**. Tests that freeze planning time patch the module's `planning_now`.

External APIs count from their own (real) today: Open-Meteo `forecast_days` (`outdoor_forecast._required_forecast_days`, `eu_market_features._forecast_days_for_range`) must be computed from the real date, otherwise a cycle at 23:58 for 00:00 requests one day too few and the end of the horizon falls back. Likewise forecast.solar returns today + tomorrow of the request date: a cycle shortly before midnight lacks PV for the day after the tick (synthetic fallback there) — an availability difference of one cycle, not an anchoring error.

Import-time "now" is a bug in a long-running daemon: `consumption_profiles.MODELED_PROFILE_REF_START` (reference archive year) became `modeled_profile_ref_start()` (per call, planning year).

## 4. Cycle split

```
      T-L                         ready          T                          end
 ─────┬───────────────────────────┬──────────────┬──────────────────────────┬────
      │ PREPARE + SOLVE (for T)   │ HOLD (polls) │ CLOSE + WRITES + PERSIST │
```

1. **Prepare + solve** from `T − L`: read telemetry, fetch inputs, matrix row 0 = `[T, T+15)`, MILP. Nothing is written.
2. **Hold** (`main._hold_until_tick`): wait on a monotonic deadline until `T`, with the daemon poll (heartbeat + power-interval sampler). **No setpoint is written before `T`.** If the plan is ready only after `T`, write at once (= behaviour without early start); log INFO, and WARNING when later than `T + 90 s`.
3. **Close the interval** `[T−15, T)` (`finalize_closed_interval`) and take the PV delta — both need the closed interval, so they run after the hold.
4. **Writes + persist** as before; `run_state.completed_at` lies after `T`, so `app.py` slot sync is unchanged.

SoC plausibility (`closed_interval_confirms_reported`) runs before the solve and therefore uses the interval closed by the previous regular cycle (`[T−30, T−15)`, kept in-process; `None` after a restart). It is a sanity check, not a MILP input.

Not early-started (behaviour as before P1, `tick=None`): the first cycle after process start, out-of-band runs (`Earnie_Request_Optimize`), `EARNIE_EARLY_START=off`, and an iteration whose pending tick is already a slot old (skipped/failed iteration). An `Earnie_Request_Optimize` during the hold is not polled; it wakes the next wait right after the commit.

## 5. Lead estimation

### 5.1 Punctuality log (P0, extended in P1)

`runtime_store/cycle_duration_stats.py` appends one record per `main()` cycle to `runtime/cycle_stats.jsonl` (rolling 7 days):

```json
{
  "tick": "2026-10-15T13:00:00.000",
  "trigger": "quarter_hour",
  "outcome": "ok",
  "lead_sec": 15.0,
  "woke_at": "2026-10-15T12:59:45.005",
  "started_at": "2026-10-15T12:59:45.017",
  "ready_at": "2026-10-15T12:59:57.712",
  "writes_done_at": "2026-10-15T13:00:00.410",
  "finished_at": "2026-10-15T13:00:04.100",
  "wake_delay_sec": 0.005,
  "start_delay_sec": 0.017,
  "duration_sec": 19.083,
  "ready_by_sec": -2.288,
  "late_by_sec": 0.41,
  "on_time": true,
  "events": ["pv_forecast_fetch"],
  "horizon_slots": 169,
  "version": "2.7.0-dev.58",
  "platform": "58f9645a66ee"
}
```

- `tick` = slot the cycle plans for (early start: the target tick).
- `wake_delay_sec` / `start_delay_sec` against the planned start `tick − lead_sec`.
- `ready_by_sec` = plan ready relative to the tick (negative = plan waited, positive = late); `late_by_sec` = setpoints written relative to the tick; `on_time` = `late_by_sec ≤ 2 s` when the cycle was scheduled for that tick. `on_time` is `null` when no tick was passed (`main(tick=None)`: first cycle after process start, `EARNIE_EARLY_START=off`, a pending tick already a slot old) and for out-of-band runs. The record stays in the log; the on-time rate and P95 skip `on_time: null`.
- `platform` = hash of CPU model/count, machine, Python and MILP solver (no hostname).

`earnie.log` gets one line per regular cycle, e.g. `Pünktlichkeit: Tick 13:00 | Vorlauf 15 s | Weckzeit +0 s | Start +0 s | Plan fertig -2 s | Sollwerte +0 s | Dauer 17 s | 24 h: 80/96 pünktlich, P95 +9 s | 7 d: …`.

### 5.2 Events

Data modules report network fetches on the running cycle: `pv_forecast_fetch`, `weather_fetch`, `price_feature_refresh`, `day_ahead_fetch`, plus `cold_start`. The lead estimator skips `cold_start` records (§5.3). The other events explain outliers and show whether the prefetch (§8) keeps fetches off the critical path.

### 5.3 Estimator (P1, `optimizer/start_scheduler.py`)

Objective: minimal age of the setpoints at the tick in both directions, i.e. minimise the mean absolute gap `|ready − T|` over cycles. For a lead `L` and time to plan `d`, `ready − T = d − L`; the `L` that minimises `mean |d − L|` is the **median** of `d`. A high quantile would systematically start too early.

Pure function `decide_lead(records, platform=…, enabled=…) → LeadDecision(lead_sec, reason, estimate_sec, samples)`, evaluated after every cycle:

```
time_to_plan = ready_at − started_at            (old records: writes_done_at − started_at)
estimate     = median(time_to_plan of the last 96 regular "ok" cycles on this platform, excluding `cold_start`)
lead         = clamp(⌈estimate⌉, 15 s, 90 s)      → start between T−90 s and T−15 s
```

| Case | Lead | `reason` |
|------|------|----------|
| `EARNIE_EARLY_START=off` | 0 (start on the tick) | `off` |
| < 8 samples on this platform | 60 s (middle of the bounds) | `bootstrap` |
| estimate < 15 s | 15 s | `min` |
| 15 s ≤ estimate ≤ 90 s | ⌈estimate⌉ | `median` |
| estimate > 90 s | 90 s, start not moved further; WARNING once when entering this state | `capped` |

The 15 s floor (start at the latest at `T − 15 s`) is an owner decision: with the dev.57 NAS times (median ~12.5 s) the floor applies and the plan waits ~2–3 s for the tick on a typical cycle. A plan that is still late is warned about by the hold when it is ready later than `T + 90 s` (§4).

`next_regular_start(now, lead)` → `(tick, start_at)`: `tick` = next quarter-hour after `now`; `start_at = max(now, tick − lead)` — a previous cycle that ends inside the lead window starts the next one at once. Lead ≤ 90 s < 15 min, so cycles never overlap.

### 5.4 Dropped: event-aware lead

Idea: per-event medians with `will_refresh(at)` from the data modules, so predictable slow cycles (cache expiry, day-ahead auction) start earlier. Dropped 2026-10-15: the prefetch (§8) removes the cache-expiry fetches from the critical path instead of planning around them; the remaining day-ahead fetch after the auction (results ~12:45–13:08) cannot be predicted to the tick; fast cycles sit at the 15 s floor, so a lower per-event lead gains nothing. Revisit only if the punctuality log shows recurring late ticks around the auction after the prefetch.

## 6. Configuration

| Variable | Values | Default |
|----------|--------|---------|
| `EARNIE_EARLY_START` | `on` / `off` (case-insensitive; anything else fails loud at daemon start) | `on` |

Bounds (15 s / 90 s), bootstrap (60 s), window (96 cycles) and minimum samples (8) are constants in `optimizer/start_scheduler.py`.

## 7. Follow-ups (backlog)

- **Clock-skew diagnostics** — **implemented** (`runtime_store/clock_skew.py`, hook on `requests.Session.send` installed by the daemon; HTTPS public hosts only, responses > 2 s dropped, median of ≥ 3 samples within 1 h, warning at most hourly; tests `tests/test_clock_skew.py`) (not part of the epic, §2): estimate the host clock offset from the HTTP `Date` header of requests the cycle already makes (ENTSO-E, Energy-Charts, Open-Meteo; no extra request), using the request/response midpoint and +0.5 s for the truncated 1 s resolution, median over several responses; offset > 2 s → warning with an NTP hint, optional `clock_skew_sec` in the punctuality record. No gate on early start: the punctuality log measures against the host clock and cannot see a skew, and disabling early start would not change the write time.
- **Cockpit display:** lead, time to plan, gap to tick, on-time rate, capped warning.

Dropped with the P1 scope decision: SoC / thermal / EV projection to `T`, pre-commit SoC drift check and re-run, MILP solver deadline (MILP < 1 s on the NAS since dev.57), `target_slot` in `run_state`, `pv_forecast` guard rework (regular runs stay ~15 min apart).

## 8. Prefetch: move I/O out of the critical path (implemented)

With the thermal cost gone, the variance is network I/O. NAS 2026-10-15: the EU weather for the price forecast took 0.2–24 s per call, twice per refresh (forecast + bias lookback), plus up to 36 s for the EU power archive after a restart.

**Feature cache by calendar days** (`data/price_forecast_live.py`): the network inputs of the EU features are cached per `(kind, start date, end date)` — `forecast_weather`, `archive_weather`, `archive_power` — for `LIVE_FEATURE_CACHE_TTL_SEC` (45 min). The slot-specific frame (remap + enrich) is rebuilt per call, which is cheap. Before, the frame was cached per slot range; the planning window moves every hour, so the cache missed at every full hour. `price_feature_refresh` is now recorded only for a real fetch.

**Refresh-ahead** (`runtime_store/planning_clock.cache_valid_until` / `cache_entry_fresh`): inside `cache_valid_until(t)`, an entry counts as fresh only if it is still valid at `t`. Used by the feature-input cache and the Open-Meteo outdoor / tilted-irradiance caches.

**Prefetch** (`data/live_prefetch.prefetch_live_inputs`, called from the daemon after each cycle via `main._prefetch_for_next_cycle`):

1. Right after the cycle, once the next `(tick, start_at)` is known; skipped when the next start is less than 120 s away.
2. Runs under `planning_anchor(next tick)` and `cache_valid_until(start_at + 120 s)`, so it builds exactly the cache keys the next cycle will look up and renews entries that would expire before it reads them.
3. Steps: planning window → day-ahead prices (`fetch_live_day_ahead_prices`, picks up the auction as soon as it is published) → `resolve_market_slots` with the same kwargs as the matrix build (EU features for missing slots + bias lookback) → outdoor temperature for the thermal horizon and collector irradiance for consumers with `solar_thermal_area_m2 > 0`.
4. forecast.solar is not prefetched (15-min API guard and rate limit stay with the cycle).
5. A failing step is logged as WARNING and skipped; the cycle then fetches that input itself, as before. The prefetch never raises into the daemon.
6. One log line per prefetch: `Prefetch für 13:00: weather_fetch, price_feature_refresh in 23.4 s` or `… alles aus dem Cache …`.

A day-ahead auction published between prefetch and cycle still makes the cycle fetch once — the data did not exist at prefetch time.

Also fixed alongside P1: the Live day-ahead cache was never used with a sunrise horizon into D+2, because coverage was checked up to the planning end while prices exist only up to D+1 23:45. Coverage is now checked up to `published_cover_end(window_end, now)` (`data/live_price_cache.py`).

## 9. Tests

- `tests/test_start_scheduler.py`: env switch, bootstrap, 15 s floor, median estimate (and that it minimises the mean absolute gap), 90 s cap, outlier robustness, record filters, next start (hour rollover, midnight, inside the lead window).
- `tests/test_planning_clock.py`: frozen at the tick, timezone, past anchor, slot key.
- `tests/test_main_early_start.py`: hold waits on a monotonic deadline with polls; late plan → no wait, WARNING beyond 90 s; early cycle plans for `T` (`current_hour`, slot key) and runs solve → hold → close interval → writes in that order; no hold without a tick; out-of-band rejects a tick.
- `tests/test_cycle_duration_stats.py`: tick, lead, ready and delays of early-started records; log line.
- `tests/test_live_price_cache.py`: published cover end; sunrise window into D+2 served from cache; cache without tomorrow refetches.
- `tests/test_live_prefetch.py`: feature cache keyed by days (hour shift hits), refresh-ahead refetch, failing step logged not raised, daemon skip below 120 s idle, daemon survives a prefetch crash.
- `tests/test_early_start_equivalence.py` (slow, `time-machine`): additionally `test_prefetch_keeps_the_plan_and_takes_fetches_off_the_cycle` — prefetch 14 min before, then the early cycle in the same process: identical plan and writes, and no `day_ahead_fetch` / `price_feature_refresh` / `weather_fetch` in the cycle (15:00 and midnight).
- Full-cycle equivalence (slow, `time-machine`): **equivalence of the full cycle**. Per boundary tick a seed cycle runs at `T − 15 min`; from copies of that runtime, run A at `T` without early start and runs B at `T − 15 s` / `T − 90 s` with `tick=T`. The wall clock is frozen globally, inputs are deterministic functions of absolute time (`tests/early_start_runner.py`: fake Open-Meteo / forecast.solar / Energy-Charts, fixed telemetry, network blocked, each run a fresh interpreter with its own config copy). Planning window, daily targets, MILP inputs and result, every write call, `run_state` and history row must be identical (run timestamps excluded). Ticks: quarter, hour, 12:00, midnight, month, New Year, DST spring forward, DST fall back. A mutation that ignores the anchor fails all of them. Diagnostics: `EARLY_START_TRACE_CLOCK=1` lists project call sites that read the wall clock directly before the hold.

## Sources

- EPEX SPOT: [15-minute products live in EPEX SPOT day-ahead markets](https://www.epexspot.com/en/news/15-minute-products-live-epex-spot-day-ahead-markets)
- EPEX SPOT: [Market coupling steering committee confirms go-live of 15-minute MTU in SDAC (trading day 30 Sept)](https://www.epexspot.com/en/news/market-coupling-steering-committee-confirms-go-live-15-minute-mtu-sdac-trading-day-30)
- EPEX SPOT: [15' MTU in SDAC (2025-04-17)](https://www.epexspot.com/sites/default/files/download_center_files/2025-04-17_EPEXSPOT_15%27MTU%20in%20SDAC_FINAL_final.pdf)
- PwC: [Introduction of 15-minute intervals in day-ahead trading](https://blogs.pwc.de/en/auf-ein-watt/article/247689/weiterentwicklung-des-europaeischen-strommarkts-die-einfuehrung-von-15-minuten-zeitintervallen-im-day-ahead-handel/)
