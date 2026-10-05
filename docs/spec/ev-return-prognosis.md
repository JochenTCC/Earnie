# EV coming-back / connect prognosis

Developer spec for unplugged-EV charge planning (`forecast_when_absent`). User-facing summary: [flexible-verbraucher.md](../konfiguration/flexible-verbraucher.md) § E-Auto / Verspätete Rückkehr.

## Goal

When the car is **not plugged in**, Earnie may still plan a charging window (`anticipated=True`) so MILP can reserve cheap slots and house ESS energy — but **live setpoints stay 0 A** until plug-in (`suppresses_live_charging_output`).

Symptoms this design addresses:

1. **Too early** — eligibility opens at “now” before a realistic reconnect.
2. **Day skipped** — inactive or jump to tomorrow’s `car_available_from` while a ReadyAt (live or config) still allows a cycle.

## Call chain

```
resolve_charging_contexts
  → resolve_charging_context
       → fetch_loxone_charging_context / _resolve_config_path_charging_context
            → (unplugged + forecast_when_absent)
                 → resolve_connect_prognosis   # optimizer/ev_connect_prognosis.py
  → consumer_charging_eligible_indices (available_from / deadline)
```

Live writes: `suppresses_live_charging_output` when `anticipated && !plugged_in`.

## Phases (`connect_phase`)

| Phase | When | `available_from` | `deadline` |
|-------|------|------------------|------------|
| `open_cycle` | Same-day open-deadline latch after brief unplug | `horizon_start` | latch / ReadyAt |
| `overnight_open` | Yesterday’s config window still open (before config `ready_by`) | `horizon_start` | ReadyAt |
| `before_arrival` | Next `car_available_from` still in the future | scheduled arrival | ReadyAt |
| `late_return` | Today’s connect missed, or next schedule ≥ ReadyAt | `max(horizon, ReadyAt − charge×1.05 − 1h)` | ReadyAt |
| `inactive` | No schedule / no target / ReadyAt expired / no ReadyAt after fallback | — | — |

Plugged-in contexts do not set these phases (connected path unchanged).

## ReadyAt resolution

Ordered:

1. Live `get_evcs_ready_by_time` / FertigUm if parseable and `> horizon`
2. Else config `ready_by_hour` via `deadline_from_ready_hour(horizon, …)` if `> horizon`
3. Else `inactive` (true skip)

Both Loxone and config `daily_target_source` paths use this chain. Context fields: `connect_phase`, `ready_at_source` (`live` | `config`).

## Late-return math

Constant: `LATE_RETURN_CONNECT_BUFFER_H = 1.0`.

```
last = latest_start_datetime(deadline, target_kwh, max_kw) − 1h
available_from = max(horizon_start, last)
```

`latest_start_datetime` uses charge hours × 1.05 (`optimizer/charging_urgent.py`).

Keep the scheduled evening connect when it is still before ReadyAt and today’s connect slot was **not** missed (`before_arrival`). Never enter `late_return` / `available_from=now` while still before today’s `car_available_from`, except `open_cycle` / `overnight_open`.

## History

| When | Change | Intent |
|------|--------|--------|
| 2026-07 | `anticipated` + no live writes; absent ≠ immediately available | Stop charging while unplugged |
| 2026-07-31 | Bound overnight by config `ready_by` | No daytime Smart plan after overnight ready |
| 2026-08 | `open_charging_deadlines` latch | Brief unplug must not drop today’s cycle |
| 2026-09-29 | Open-cycle same calendar day only | Next-morning FertigUm must not force midday-now |
| 2026-10-04 | `late_return_available_from` | Missed slot → ReadyAt − charge − 1h |
| 2026-10-05 | `resolve_connect_prognosis` phases + config ReadyAt fallback | Unify paths; fix skip / too-early attribution |

## Module map

| Path | Role |
|------|------|
| `optimizer/ev_connect_prognosis.py` | Pure phase resolve + ReadyAt fallback |
| `optimizer/charging_resolve.py` | Assemble SOC / capacity / plugged sensor; thin wrappers |
| `optimizer/charging_schedule.py` | Eligibility, FertigUm parse, schedule helpers |
| `optimizer/charging_context.py` | Facade re-exports (tests patch here) |

## Failure modes (guarded)

- No live FertigUm **and** no config `ready_by` → inactive.
- `deadline <= available_from` after late-return → inactive.
- Next-day FertigUm latch → not `open_cycle` (same-calendar-day only).
- Overnight past config `ready_by` → wait for next `car_available_from`.
- Large `target_kwh` with late clock → clamp to horizon (urgent remainder; may still be infeasible).
