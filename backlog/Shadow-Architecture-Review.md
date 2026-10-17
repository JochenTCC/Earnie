# Shadow architecture review (post-2.7)

Review for Backlog 2.7: *Review entire Shadow architecture after all changes for 2.7 and propose a refactoring*. Spec: [`docs/dev/shadow-mode.md`](../docs/dev/shadow-mode.md).

**Verdict:** S1–S3 match the spec. The package under [`runtime_store/shadow/`](../runtime_store/shadow/) is layered correctly. Debt is **scatter** (transport/config hooks at many call sites) plus two **post-commit dual-paths**, not a broken core design. Refactor is phased follow-up (**R1–R4**); no greenfield rewrite.

**Scope of this document:** architecture review + phased follow-up. **R1–R4** implemented (2026-10-12); S4 stays **2.+1**.

---

## 1. As-built map

### 1.1 Roles

| Role | Activation | Duty |
|------|------------|------|
| **Prod recorder (S1)** | `local_settings.shadow_feed_enabled` | Record raw transport payloads into `{config}/shadow_feed/` |
| **Shadow client (S2+S3)** | `EARNIE_SHADOW=1` only | Replay feed, block backend writes, RO or private config, UI banner |

```text
Prod adapters / push inbox
  → hooks.record_* → feed (memory + latest/meta + JSONL)
  → after cycle: flush + HA/OpenEMS superset (Loxone superset = no-op)
        │
        ▼  shadow_feed/
Shadow replay / push overlay
  → same optimizer cycle
  → writes.block_write_if_shadow → shadow_writes.jsonl
  → config: RO + ehal overlay  OR  private writable (external feed)
```

### 1.2 Package modules (`runtime_store/shadow/`)

| Module | Responsibility |
|--------|----------------|
| `mode.py` | `is_shadow_mode()`, `is_shadow_config_readonly()` |
| `errors.py` | `ShadowBackendAccessError`, `ConfigReadOnlyError`, `ShadowStartupError` |
| `feed.py` | Prod writer: record, flush, retention, schema |
| `hooks.py` | Never-raise `record_transport` / `record_event` |
| `reader.py` | SMB-safe cached read of meta/latest |
| `replay.py` | Lookup, staleness, typed replay, `assert_not_shadow_backend` |
| `writes.py` | Write block, would-write log, `should_invoke_setpoint_writes` |
| `cycle.py` | Wait for Prod `cycle_seq`, feed health/lag, trigger consume |
| `startup.py` | §4.2 refuse + `.shadow_runtime` marker |
| `superset.py` | Post-cycle unbound HA/OpenEMS reads; Loxone no-op |
| `ehal_overlay.py` | Shadow-only EHAL bindings under runtime (shared-config mode) |
| `__init__.py` | Public façade re-exports |

### 1.3 Call-site scatter (outside the package)

| Area | Pattern today |
|------|----------------|
| Transport replay + record | `integrations/ha_adapter.py`, `openems_adapter.py`, `awattar_client.py`; `data/pv_forecast.py`, `outdoor_forecast.py`, `data_loader.py`; `runtime_store/loxone_push_inbox.py` — each embeds `if shadow: replay else: network + record` |
| Write block | `loxone_writes.py`, `ha_adapter.py`, `openems_adapter.py` — `block_write_if_shadow` per primitive |
| Silent dual-path | Shadow implies silent but still invokes setpoint helpers (`should_invoke_setpoint_writes`); plain silent skips |
| `assert_not_shadow_backend` | Present on some structure/watchdog/scanner paths; **incomplete** for MCP / greenfield / ehal mapping probes |
| Config RO | Every writer: `settings/json_io.py`, `profiles_store`, `components_store`, `dotenv_io`, `bootstrap`, `ha_secrets_migrate`, `ui/auto_persist` |
| EHAL overlay | Load merge + save divert in house_config + EHAL mapping UI |
| Daemon orchestration | `main.py`: wait/skip cycle, flush, superset, sampler flush, auth-gate bypass, optimize-trigger mirror |

**Centralized (keep):** mode helpers, feed I/O, would-write log, startup refuse, `ui/shadow_banner.py`.

---

## 2. Post-2.7 / post-commit change classification

| Change | When / where | Verdict |
|--------|----------------|---------|
| Loxone Merker-superset → **no-op**; VO push → `loxone:io:*` feed (`record_push` + cycle export) | Oct 2026 Erledigt + uncommitted feed path | **Keep** — correct push-only architecture |
| `is_shadow_config_readonly()` (feed under `config_dir()` → RO; external `EARNIE_SHADOW_FEED_PATH` → private writable) | Uncommitted + already in spec §6.4 | **Keep as first-class** — two deployment modes, not a workaround |
| Prod `loxone_push_inbox.json` file fallback + path sniff (`{feed}/../../runtime` or `EARNIE_SHADOW_PROD_RUNTIME_PATH`) | Pre-R2 | **Retired (R2 hard cut)** — feed-only + `loxone_feed: "push"`; no dual-path release |
| Tactical Merker skip-lists (pushable bindings / Q8 bare EHAL IDs in superset) | Oct 2026, before Merker removal | **Superseded** — do not revive |
| `should_invoke_setpoint_writes` (Shadow ≠ plain silent) | Characterization / silent PS setpoints | **Keep** — fills `shadow_writes.jsonl` |
| Incomplete `assert_not_shadow_backend` / ENTSO-E not in feed | Dogfood gaps (regression check 2026-10-10) | **Done** in **R3** / **R4** |

Deferred product items (not part of R1–R3 cleanup): Shadow would-write old-vs-new comparison; silent `status.json` publish gate; **S4** Soll/Soll + offline JSONL → **2.+1**.

---

## 3. Target architecture — phases R1–R4

### R1 — Policy façade (behavior-preserving) — **done (2026-10-12)**

**Goal:** One small, documented API for “what Shadow may do” so new call sites do not invent gates.

- `is_shadow_mode()` / `is_shadow_config_readonly()` remain the **only** gates.
- Gate checklist in [`DEVELOPER.md`](../DEVELOPER.md) (Shadow gates subsection); mirrors:

| Concern | Gate |
|---------|------|
| Backend read replay / write block / banner / cycle wait | `is_shadow_mode()` |
| Config writers, load-time migration skip, EHAL overlay use | `is_shadow_config_readonly()` |
| Setpoint helper invocation (would-write log) | `should_invoke_setpoint_writes()` |

- No new Python helpers in R1 (repeated `ConfigReadOnlyError` raise stays as-is).

**Acceptance:** No behavior change beyond landing shared/private dual-path; call-site audit below; shadow tests green.

#### R1 call-site audit (2026-10-12)

| Gate | Production call sites | Verdict |
|------|------------------------|---------|
| `is_shadow_mode()` | `feed`, `replay`, `writes`, `startup`, `cycle`, adapters (`ha`, `openems`, `awattar`), `data/*` forecast/loader, `loxone_push_inbox`, `loxone_request_http`, `config` silent imply, `main` cycle/trigger, UI banner/daemon/debug, `startup_checks` | Correct — runtime/backend/UI shadow detection |
| `is_shadow_config_readonly()` | `settings/json_io`, `profiles_store`, `components_store`, `dotenv_io`, `bootstrap` (config pack skip), `ha_secrets_migrate`, `ui/auto_persist`, EHAL mapping UIs, `page_house_config`, `house_config_entities_io`, banner RO caption | Correct — config/overlay only |
| Both | `bootstrap._bootstrap_all_artifacts`: `is_shadow_mode() and is_shadow_config_readonly()` before skipping config pack | Correct — private Shadow still bootstraps local config |
| `should_invoke_setpoint_writes()` | `main.py`, `optimizer/powerstation_live.py` | Correct |

**Wrong-gate fixes in R1:** none required after dual-path land.

### R2 — Single Loxone input contract

**Goal:** Feed is the only Shadow source for VO telemetry.

- Prod must record `loxone:io:*` via `record_push` and cycle export (already tested).
- Add `meta.json` capability `loxone_feed: "push"` when Prod `ehal_backend` is Loxone.
- **Hard cut (decided 2026-10-12):** delete Prod-inbox file fallback immediately; Shadow startup refuses Loxone feeds missing the capability (no dual-path warning release).
- **Never** reintroduce HTTP Merker-superset.

**Acceptance:** Capability in meta; fallback removed; startup refuse without capability; `test_superset_loxone_is_noop` and push→feed tests stay; inbox-fallback tests rewritten to feed-only / capability-missing behavior.

### R3 — Transport intercept layer — **done (2026-10-12)**

**Goal:** Collapse duplicated adapter branches; harden backend access; thin `main.py`.

- Shared helpers in `runtime_store/shadow/transport.py`: `safe_record`, `hub_get`, `ext_get` (HA / OpenEMS / `ext:*`; Loxone push left asymmetric).
- `assert_not_shadow_backend` on MCP, greenfield, connectivity probe, HA `list_mappable_entities`, `scan_structure`.
- Daemon orchestration in `runtime_store/shadow/daemon.py`; `main.py` calls named helpers.

**Acceptance:** New external HTTP client for live data must go through the helper (DEVELOPER.md + `tests/test_shadow_transport.py`); probes raise in Shadow (`test_probe_entries_raise_in_shadow`); daemon orchestration callable from tests without full `main` (`tests/test_shadow_daemon.py`).

### R4 — Gaps + S4 prep — **done (2026-10-12)**

**Goal:** Close dogfood holes; leave Soll/Soll for later.

- Record/replay **ENTSO-E** via Family-B `ext_get`/`safe_record` in `integrations/entsoe_client.py` → feed key `ext:prices:entsoe` (raw A44 XML). Energy-Charts / aWATTar / outdoor / PV were already covered under R3.
- Product deferred (separate backlog): would-write old-vs-new; silent `status.json` publish gate.
- **S4** (Prod↔Shadow decision diff; offline JSONL backtest) stays **2.+1** — not started.

**Acceptance:** ENTSO-E keys in feed + Shadow replay tests (`tests/test_entsoe_client.py`); S4 not started under this review.

### Out of scope

- Feed schema major bump without need
- Shadow as 2nd HA add-on (scenario C)
- Full Shadow config overlay beyond EHAL bindings (`shadow_ehal_bindings.json`)

---

## 4. Do-not list

When implementing R1–R4 (or any Shadow bugfix):

1. **Do not** reintroduce Loxone HTTP Merker-superset or poll VO titles / bare EHAL activation IDs.
2. **Do not** collapse Shadow into plain silent (would empty `shadow_writes.jsonl` and break S3 would-write UI).
3. **Do not** treat all Shadow as config-RO — private env with external feed must stay writable.
4. **Do not** reintroduce Prod-inbox file fallback (R2 hard cut — feed-only + `loxone_feed: "push"`).
5. **Do not** mix up `is_shadow_mode` vs `is_shadow_config_readonly` (wrong gate → write Prod config or skip overlay).
6. **Do not** use only UI disable for structure/MCP/greenfield probes — raise `ShadowBackendAccessError`.
7. **Do not** invent a second Shadow activation path (config key / `local_settings`) — env only.

---

## 5. Test freeze (must stay green until deliberately rewritten)

Behaviors encoded today that any refactor must preserve or consciously replace:

| Area | Tests (representative) |
|------|-------------------------|
| Mode / recorder | `test_is_shadow_mode_*`, `test_recording_disabled_by_default`, `test_shadow_env_disables_recorder`, `test_packaging_trees_lack_earnie_shadow` |
| Feed integrity | `test_record_ok_and_error_jsonl_no_secrets`, `test_atomic_latest_and_retention`, `test_recorder_exception_swallowed` |
| Loxone push → feed | `test_record_push_mirrors_to_shadow_feed`, `test_flush_after_cycle_exports_inbox`, `test_superset_loxone_is_noop` |
| Replay / staleness | `test_replay_*`, `test_shadow_read_push_value_uses_feed_soc` |
| Feed-only Loxone (R2) | `test_shadow_read_push_value_ignores_prod_inbox_file`, `test_shadow_ready_by_time_from_feed`, `test_startup_*_loxone_*` |
| Write block / silent | `test_loxone_write_blocked_and_logged`, `test_should_invoke_setpoint_writes_*`, `test_silent_implied_by_shadow` |
| Config RO vs private | `test_config_write_*`, `test_is_shadow_config_readonly_*`, `test_save_house_profiles_*`, overlay tests in `test_shadow_ehal_overlay.py` |
| Startup | `test_startup_refuses_*`, `test_startup_ok_writes_marker` |
| E2E | `test_housesim_prod_records_and_shadow_replays` |

Also: `tests/test_auto_persist_shadow.py` for UI persist under Shadow RO.

---

## 6. Suggested implementation order

1. ~~Land / commit Shadow dual-path (VO feed + readonly helper + inbox fallback).~~ **Done** with R1 (`37b71423`).
2. ~~**R1** docs + gate audit.~~ **Done** (2026-10-12).
3. ~~**R2** capability + hard-cut remove inbox fallback.~~ Implemented (hard cut; no dual-path release).
4. ~~**R3** transport helpers + assert coverage + `main` extract.~~ **Done** (2026-10-12).
5. ~~**R4** ENTSO-E; leave S4 on **2.+1**.~~ **Done** (2026-10-12).

Effort note: R2–R3 are the real structural payoffs; R4 is gap-fill.
