# Binding P0c — Persisted files keyed by entity id

**Spike:** Session B / Binding P0c (2026-10-10). Research only — no product code.

**Scope:** house-config entity id (Kennung / battery / PV / consumer / EV / scenario) — **not** Home Assistant `entity_id` strings.

**Cascade today:** `house_config/clean_entity_ids.py` (battery/PV + scenario `battery_ids` / `pv_system_ids` + house `powerstation_id`) and UI battery unlock → shadow battery overlay. Does **not** touch history, flex state, cons_data, reserves, schedules, `ehal_published`, push inbox, or consumer overlay slots.

**No read-time Kennung alias exists in code** (`legacy_id` was removed and is rejected).

---

## Inventory

| Artifact | Path | Keys by entity id? | Rename risk |
| --- | --- | --- | --- |
| Optimization history | `runtime/optimization_history.jsonl` (+ monthly archives) | **Yes** — `consumer_*`, `flex_live_kw`, `soc_percent_by_ess`, contexts, delivery_*, `consumption_snapshot.flex_kw`, thermal `consumer_id`, nested `ehal_published` qids | Charts join via current config ids → orphan series |
| Run state | `runtime/optimizer_run_state.json` | **Yes** — same payload as history | Stale keys until next overwrite |
| Flex day state | `runtime/flexible_consumers_state.json` | **Yes** — `delivered`, `charging_sessions`, `generic_flex_run`, plug/deadline maps | Mid-day rename loses session / min_on |
| Powerstation reserves | `runtime/powerstation_reserves.json` | **Yes** — top-level battery/PS id | Reserve state orphaned |
| Appliance schedules | `runtime/appliance_schedules.json` | **Yes** — appliance/consumer id | Schedule orphaned |
| Power sampler | `runtime/power_interval_sampler_state.json` | **Yes** (flex) — `flex_kw` + energy-anchor flex readings | Mid-slot mean / ΔkWh break |
| Cons data / profiles | `runtime/cons_data.csv` (+ `.meta`), `flexible_consumer_profiles.csv` | **Yes** — columns `{consumer_id}_kw` / profile columns = consumer id | Column mismatch / meta fingerprint |
| EHAL publish ledger | `runtime/ehal_published.json` | **Yes** — qualified EHAL ids embed Kennung | Stale setpoints under old qids |
| Push inbox | `runtime/loxone_push_inbox.json` | **Yes** — EHAL id keys with Kennung segment | Cache continuity |
| Live / historical debug | `live_optimization_debug.json`, `historical_optimization_debug.json` | **Yes** (nested) | Regenerates; join until next run |
| Shadow overlay | `runtime/shadow_ehal_bindings.json` | **Yes** — `battery_bindings[id]`, `consumer_bindings[profile][id]` | Battery rewrite exists; consumers not yet |
| Backtesting logs | `runtime/backtesting_log.json`, snapshots, CBC events | **Yes** for `scenario_id` (+ nested flex ids) | Scenario rename / nested flex |
| HTTP `status.json` | regenerated (not a disk map) | Wire keys embed Kennung | Ledgers above still need alias/rewrite |
| Debug dumps | `runtime/chart_debug/debug_dump_*.zip` | **Yes (embedded)** — `inputs/*` config + history/run_state (+ optional flex state) | Self-contained for replay; no live alias |
| Fixtures | `tests/fixtures/prod_dumps/**`, `tests/fixtures/backtesting/` | **Yes (pinned)** | Re-record / one-off rewrite |
| Config cascade | `components.json`, `house_profiles.json`, scenarios | **Yes** | Rewritten by `clean_entity_ids` — not an alias table |

### Not keyed by house Kennung

`pv_counter_state.json` (plant PV integral), aggregate `consumption_profiles.csv` / `total_consumption_profiles.csv`, `shadow_writes.jsonl` / shadow feed (backend/HA transport keys), HouseSim HA golden maps (EHAL field → HA `entity_id`), `earnie.log`, `main.lock`, `local_settings.json`, heartbeat/auth.

`tests/regression/` is not built yet — plan ids into cases when **2.7.i** lands.

PV system ids appear in **config/scenarios**, not as history dict keys (plant `pv_kw` is aggregate). EVs are consumers (`type=ev`) — same consumer-id maps + `ev.` / `evcs.` wire ids.

---

## Alias table: **yes**

| Mechanism | Artifacts |
| --- | --- |
| **Alias-on-read (primary)** | `optimization_history.jsonl` (+ monthly archives) — large, append-only; chart/timeline join |
| **Rewrite-on-rename (prefer)** | `flexible_consumers_state.json`, `powerstation_reserves.json`, `appliance_schedules.json`, `power_interval_sampler_state.json`, `optimizer_run_state.json`, `shadow_ehal_bindings.json`, `ehal_published.json`, `loxone_push_inbox.json`, `cons_data.csv`/meta, `flexible_consumer_profiles.csv` |
| **Out of runtime alias scope** | Debug dumps (self-contained); test fixtures (re-record / script) |
| **No separate immutable `uid`** | Dependence is real but limited to known dict/column keys; config cascade + history alias-on-read suffice |

### Implications

- **Session C (2.7.n-3):** consumer/EV `entity_id_lock` now; full “Kennung ändern” + alias/rewrite stays Binding P6 / 2.+1 — but alias **is** required when that cascade lands.
- **Inverter P1:** one-off migration creates new inverter ids and rewrites battery/PV `inverter_id` in config; history has no inverter keys yet → no history alias for inverter migration. Battery Kennung renames still need the path above before broad Kennung edit.
