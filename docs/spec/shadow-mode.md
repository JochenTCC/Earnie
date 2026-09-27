# Specification: Shadow Mode (Dev instance fed by Prod)

**Version:** 0.3  
**Status:** S1 (Prod recorder) implemented; S2+S3 (Shadow client) implemented on `feature/2.7` — backlog **2.6.o** → **2.7.f** → **2.+1** (S4)  
**Epic short name:** **Shadow**  
**Related:** Silent mode (`config.is_silent_mode()`), [EHAL](ehal.md), [Release Checklist](release-checklist.md)

## 1. Goal

Run a **development build** of Earnie (Shadow) in parallel to the **productive** installation (Prod) on real, live input data — without the Shadow instance ever touching the smarthome backend or disturbing Prod.

- **Prod** talks to the smarthome backend (Loxone / HA / OpenEMS) as today and additionally **records every input value** into a feed on disk.
- **Shadow** does **not** talk to the backend. It takes its inputs from the feed Prod wrote, runs the full optimizer cycle and **only logs** the setpoints it would have written.
- Both read the **same configuration**. Shadow reads it **read-only**.
- Shadow runs on **its own runtime directory**, so logs, locks, state and learned data never collide with Prod.

Typical use: validate a new optimizer / mapping / feature against the house for days before tagging a release candidate.

## 2. Terms

| Term | Meaning |
|---|---|
| **Prod** | Released Earnie installation that controls the plant (e.g. HA add-on *Earnie (Vorabversion)*). Runs with the **feed recorder** enabled. |
| **Shadow** | Dev build started with `EARNIE_SHADOW=1`. Never contacts the backend, never writes config. |
| **Feed** | Directory written by Prod, read by Shadow (§5.3). |
| **Transport primitive** | Lowest-level function that performs one backend HTTP call (§5.2, §6.1). |

## 3. Scope

| In scope (v1) | Out of scope (v1) |
|---|---|
| Recorder in Prod (opt-in), feed format, retention | Shadow as HA add-on (add-on cannot read another add-on's `addon_config`; see §9) |
| Shadow input replay at the transport layer | Automatic Soll/Soll comparison Prod vs. Shadow (later, see §11 S4) |
| Central write block + "would write" log | Offline replay of archived feeds as a backtest (later, §11 S4) |
| Config read-only guard | Multiple Shadow instances on one feed (works, but not tested) |
| Own runtime dir, optional seeding from Prod | Shadow editing config (explicitly excluded) |
| UI banner + feed health | |

## 4. Activation

### 4.1 Shadow: `EARNIE_SHADOW=1`

- Shadow is enabled **only** by the process environment variable `EARNIE_SHADOW=1` (read via `runtime_store.env_vars.is_truthy("SHADOW")`). It is **not** a key in `config.json` or `local_settings.json`: the config is shared with Prod, and a config key could switch Prod into Shadow.
- One helper `runtime_store.shadow.is_shadow_mode()` is the only place that reads it; all other code asks this helper.
- Shadow **implies silent**: `config.is_silent_mode()` returns `True` regardless of `local_settings.json`; the silent toggle in the UI is disabled while Shadow is active.

### 4.2 Startup checks (Shadow refuses to start)

Shadow exits with a clear error (non-zero exit code, UI error page) when any of these hold:

1. **No explicit runtime dir:** neither `EARNIE_RUNTIME_PATH` nor `EARNIE_ENV_PATH` is set. Falling back to the default would risk sharing Prod's `earnie_env/runtime`.
2. **Runtime dir equals Prod's:** `runtime_dir()` resolves to the path Prod reports in `feed/meta.json` (`prod_runtime_dir`), or the dir contains a Prod single-instance lock without the Shadow marker (§6.5).
3. **Feed missing or incompatible:** `feed/meta.json` missing, or `feed_schema` not supported by this build.
4. **Config data model incompatible:** the shared config's `earnie_data_model` is not in this build's `COMPATIBLE_DATA_MODELS`. Shadow never migrates or re-stamps the config.

A stale feed (Prod stopped) is **not** a startup error: Shadow starts, shows the feed as stale and skips cycles (§6.2).

### 4.3 Recorder in Prod: `local_settings.json`

- Enabled per instance with `"shadow_feed_enabled": true` in Prod's `local_settings.json` (runtime dir → not shared). Default `false`: nothing changes for regular users.
- Optional `"shadow_feed_retention_days"` (default 14) for the JSONL archive.
- The recorder is ignored (and logs one warning) when the process itself runs with `EARNIE_SHADOW=1`.

### 4.4 Release guard

`EARNIE_SHADOW` must never reach a shipped image:

- Test: no file under `packaging/`, `docker/`, `Dockerfile*`, `.github/workflows/` sets `EARNIE_SHADOW`.
- Test: `is_shadow_mode()` is `False` without the env var (no code default).
- `release-publish.yml` version gate: `grep -rn EARNIE_SHADOW packaging docker` must be empty, otherwise the candidate fails before the build.

## 5. Prod side: feed recorder

### 5.1 Principle

Record **raw backend responses** at the transport primitives, not parsed values. Shadow then runs the **same parsing / unit conversion / sign handling of its own build** on real payloads — which is exactly what a dev build needs to test (e.g. a changed `integrations/ha_units.py`).

### 5.2 Recorded transport primitives

| Backend | Primitive | Feed key |
|---|---|---|
| Loxone | `loxone_client.fetch_loxone_raw_value(io)` | `loxone:io:<io_name>` |
| Loxone | `loxone_client._fetch_loxone_io_all(io)` | `loxone:io_all:<io_name>` |
| HA | `HaAdapter._get_json(path)` | `ha:get:<path>` (e.g. `ha:get:/api/states/sensor.x`) |
| OpenEMS | `OpenemsAdapter` GET | `openems:get:<path>` |
| forecast.solar | `data.pv_forecast` fetch | `ext:pv_forecast:<url-hash>` |
| Day-ahead prices | `data.live_market_prices` fetch | `ext:prices:<source>` |
| Outdoor forecast | `data.outdoor_forecast` fetch | `ext:outdoor:<url-hash>` |
| Inbound trigger | `loxone_request_http` optimize request | event `trigger:request_optimize` |

Each record: `{"key", "ts" (UTC ISO), "ok": bool, "status" (HTTP code or null), "payload" (JSON / raw string), "error" (text or null)}`. Failed reads are recorded too (`ok=false`), so Shadow reproduces outages faithfully.

**Never recorded:** request headers, auth, tokens, URLs with credentials. Keys use paths / IO names only.

### 5.3 Superset: what Shadow might need but Prod does not read

Shadow can only see what Prod reads. To cover bindings present in the shared config but not touched in this Prod cycle, Prod additionally reads, **once per quarter-hour cycle**:

- **HA (default):** only entities referenced in the shared config bindings (plant / consumers / EHAL map) that were not read in this cycle — one `GET /api/states/<entity>` each → key `ha:get:/api/states/<entity>`. Full `GET /api/states` dump is **not** the default (payload size on SMB); optional later via a local_settings flag if needed.
- **Loxone:** every IO name referenced in the config bindings (house profiles, consumers, EHAL mapping) that was not read in this cycle. The config is shared, so bindings added for the dev build are included.
- **OpenEMS:** the configured ESS / EVCS component channels.

Superset reads run **after** the optimizer cycle's writes, are soft-fail, and have a per-cycle time budget (default 10 s). They must never delay setpoint writes.

### 5.4 Feed layout

Location: `{config_dir}/shadow_feed/` (the config dir is already shared between both instances, e.g. via Samba `\\HOMEASSISTANT\addon_configs\…`). Override: `EARNIE_SHADOW_FEED_PATH` (both sides).

| File | Content | Write mode |
|---|---|---|
| `meta.json` | `feed_schema`, Prod `earnie_version`, `earnie_data_model`, `ehal_backend`, `prod_runtime_dir`, `heartbeat_ts`, `cycle_seq` | atomic (tmp + `os.replace`) |
| `latest.json` | map key → newest record; plus `cycle_seq`, `cycle_ts` of the last completed Prod cycle | atomic, after each cycle **and** each sampler tick (30 s) |
| `feed-YYYY-MM-DD.jsonl` | append-only archive of all records + events | append; rotated daily; deleted after retention |

- `feed_schema` starts at `1`; Shadow refuses unknown major versions.
- Writes are atomic so a reader on SMB never sees a half file; the reader retries once on `JSONDecodeError`.
- Size guard: large payloads (if any) are stored once per cycle, not per sampler tick.

### 5.5 Failure isolation

The recorder must never break Prod: every recorder call is wrapped, errors are logged (rate-limited, max 1 warning / 15 min per cause) and the cycle continues. Recording is synchronous but bounded (file write only); no network calls except the superset reads of §5.3.

## 6. Shadow side

### 6.1 Input replay

When `is_shadow_mode()`:

- Every transport primitive of §5.2 returns the recorded payload for its key instead of calling the network — **same return types and same exceptions** as a real call (`HaHttpError`, `LoxoneAdapterError`, `None` for Loxone reads, …), so the calling code runs unchanged.
- **Missing key** → behave like "backend unreachable" for that read + log `shadow: no feed value for <key>` (once per key per hour).
- **Stale value** (`ts` older than `EARNIE_SHADOW_MAX_AGE_SEC`, default 120 s) → treated as missing.
- External data (`ext:*`) comes from the feed. Shadow does **not** call forecast.solar (rate limit is per IP and shared with Prod). Prices / outdoor forecast fall back to an own fetch when missing.
- No other network I/O to the backend is allowed; any backend call outside the replayed primitives raises `ShadowBackendAccessError` (programming error, surfaces in tests).

### 6.2 Cycle timing

- Shadow keeps its own quarter-hour scheduler. At cycle start it waits up to 60 s for `latest.json` with a `cycle_seq` newer than the last one consumed, so Prod and Shadow optimize on the **same snapshot**.
- No new cycle within 60 s → run with the latest values (they may be stale → §6.1) and mark the run `feed_lag=true` in the run state.
- Feed heartbeat older than 5 min → skip the cycle, UI shows "Prod feed stale".
- `trigger:request_optimize` events in the feed start an out-of-band Shadow run (mirrors Prod).

### 6.3 Outputs: write block

- **Central block at the write primitives**, not only at the scattered silent checks: `loxone_writes._send_loxone_value_traced` (Loxone writes are HTTP **GET** `/dev/sps/io/<name>/<value>` — blocking by HTTP method is not enough), `HaAdapter` POST, `OpenemsAdapter` POST.
- Structure / setup probes (`loxone_structure`, `loxone_mcp_transport`, `loxone_greenfield_import`, `loxone_ehal_mapping`, `integration_scanner`) are backend access, not replayable: in Shadow they raise `ShadowBackendAccessError` and the UI actions that start them are disabled.
- A blocked write returns the same "not sent" result as silent mode today, and appends a structured record to `{runtime}/shadow_writes.jsonl`: `{ts, cycle_seq, backend, target, value, source}` plus a normal INFO log line `shadow: would write …`.
- Suppressed entirely in Shadow: `push_safe_setpoints_on_startup`, the Loxone request HTTP listener (`start_loxone_request_http`, port 8541), `loxone_watchdog`, the EHAL write test page (disabled like in silent mode).

### 6.4 Config read-only

- All config writers raise `ConfigReadOnlyError` when the target is under `config_dir()`: `settings.json_io.write_json_dict`, `.env` writes (`runtime_store.dotenv_io`), uploads, config pack import, bootstrap of config files.
- Load-time migrations that write back are **skipped** in Shadow (e.g. `apply_ha_secrets_migration_to_disk` in `runtime_store/config_load.py`); Shadow uses the migrated values in memory only.
- UI: banner "Konfiguration schreibgeschützt (Shadow)"; save buttons disabled.
- Consequence: config changes for a dev feature are made in Prod's UI / file. The Prod build **ignores** keys it does not know. Keys the Prod build would **reject** cannot be tested via Shadow in v1 (no Shadow-only overlay).

### 6.5 Own runtime dir

- Shadow requires an explicit `EARNIE_RUNTIME_PATH` (or `EARNIE_ENV_PATH`) — §4.2.
- On first start Shadow writes `{runtime}/.shadow_runtime` (marker). Everything runtime-scoped is then separate from Prod: `earnie.log`, single-instance locks, `local_settings.json`, `run_state`, `optimization_history.jsonl`, `pv_counter_state.json`, `power_interval_sampler_state.json`, `flexible_consumers_state.json`, `cons_data.csv`, consumption profiles.
- **Seeding (optional):** `python -m scripts.shadow_seed_runtime --from <prod runtime> --to <shadow runtime>` copies learned data and state (profiles, `cons_data*.csv`, `optimization_history.jsonl`, counter states) and **excludes** `earnie.log*`, locks, `local_settings.json`, `ehal_write_error.json`. Without seeding Shadow starts with empty history like a fresh install.

### 6.6 Silent-mode relation

| | Silent | Shadow |
|---|---|---|
| Reads backend | yes | **no** (feed) |
| Writes backend | no | no (hard block + `shadow_writes.jsonl`) |
| Writes config | yes | **no** |
| Switch | UI / `local_settings.json` | `EARNIE_SHADOW=1` only |
| Runtime dir | shared default | own, mandatory |

## 7. Ports and hosts

- **Daemon listener (8541):** not started in Shadow (§6.3) → no conflict.
- **Streamlit:** `scripts/run_streamlit.py` binds `--server.address 0.0.0.0` with `ui.streamlit_port` from the (shared) config.
  - Shadow on **another host** (e.g. dev PC, Prod on HA): same port is fine — the ports are per host.
  - Shadow on the **same host** as Prod: `0.0.0.0` covers all IPs of the host, so the same port conflicts even with several IPs. Because Shadow cannot change the shared config, use the existing env override `EARNIE_UI_STREAMLIT_PORT` (both modes, wins over `ui.streamlit_port`).
- Ingress (HA add-on) is not involved: Shadow is not an add-on in v1.

## 8. UI

- Persistent banner on every page: **"Shadow-Modus — Eingänge aus Prod-Feed (Stand HH:MM:SS, Alter N s), keine Schreibzugriffe, Konfiguration schreibgeschützt"**; colour changes to warning when the feed is stale.
- Smarthome backend page: connection tests show "Shadow — Feed" instead of probing the backend; missing feed keys are listed per mapped field.
- Loxone/EHAL debug page: "would write" table from `shadow_writes.jsonl` for the last run (reuses the existing `loxone_writes` / `ehal_writes` rendering).
- Status bar: Prod version from `meta.json` next to the Shadow version.

## 9. Deployment scenarios

| Scenario | Prod | Shadow | Config path for Shadow |
|---|---|---|---|
| **A (primary)** | HA add-on | Dev PC (Windows, repo checkout) | `EARNIE_CONFIG_PATH=\\HOMEASSISTANT\addon_configs\<prod slug>` |
| **B** | Docker on NAS / Proxmox | Dev PC or 2nd container | NAS share of Prod's config dir, mounted read-only |
| C (not v1) | HA add-on | 2nd HA add-on (`earnie_dev`) | would need `addon_configs` mapped read-only in the add-on — later |

Example scenario A (PowerShell):

```powershell
$env:EARNIE_SHADOW='1'
$env:EARNIE_CONFIG_PATH='\\HOMEASSISTANT\addon_configs\20b22c55_earnie_prerelease'
$env:EARNIE_RUNTIME_PATH='C:\earnie-shadow\runtime'
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe main.py
```

Shadow also reads Prod's `.env` in the config dir (backend secrets). It never uses them for backend calls; they are only loaded because config loading requires them.

## 10. Tests

- Recorder: records per primitive (ok + error), no secrets in records, atomic `latest.json`, JSONL rotation + retention, recorder exception does not break `main()`.
- Replay: each primitive returns identical types / exceptions as live; missing / stale key → unreachable behaviour; `ShadowBackendAccessError` on any unreplayed backend call (monkeypatch `requests.get/post` to fail).
- Write block: every write primitive blocked in Shadow, `shadow_writes.jsonl` written; startup safe setpoints, listener, watchdog not started.
- Config read-only: every writer raises under `config_dir()`; `apply_ha_secrets_migration_to_disk` skipped.
- Startup checks §4.2 (each refusal path).
- Release guard §4.4.
- End-to-end: HouseSim (`house_sim/`) as Prod backend with recorder → Shadow run on the feed → same optimizer inputs, zero backend requests from Shadow.

## 11. Implementation plan

| Step | Content | Backlog | Ships to Prod? |
|---|---|---|---|
| **S1** | Recorder (§5) behind `shadow_feed_enabled`, feed schema 1, tests | **2.6.o** | **yes — must be released first**, otherwise Prod cannot feed Shadow |
| **S2** | `is_shadow_mode()`, replay (§6.1–6.2), write block (§6.3), config read-only (§6.4), startup checks (§4.2), release guard (§4.4) | **2.7.f** | code may ship on `feature/2.7`; inactive without env var |
| **S3** | UI (§8), `EARNIE_UI_STREAMLIT_PORT`, seed script (§6.5), user docs (German: `docs/einrichtung/`, DEVELOPER.md) | **2.7.f** | with S2 |
| S4 (later) | Prod-vs-Shadow decision diff per slot; offline replay of `feed-*.jsonl` as backtest input | **2.+1** | — |

## 12. Decisions / remaining open

**Decided (2026-09-27):**

1. **HA superset (default):** only config-referenced entities (§5.3); no full `/api/states` dump by default.
2. **Config keys unknown to Prod:** no Shadow overlay in v1. Prod ignores unknown keys; Prod-rejected keys cannot be tested via Shadow.
3. **Backlog packaging:** S1 recorder = **2.6.o** (before finishing **2.6.r** Sonar); S2+S3 Shadow client = **2.7.f** (first on `feature/2.7`, before **2.7.a–e**). S4 → **2.+1**.

**Still open:**

- **Feed retention default:** 14 days of JSONL — size estimate needed after S1 on the real house.
- **Clock skew:** resolved for S2 — staleness uses age vs `meta.json.heartbeat_ts` (fallback: Shadow wall clock), gated by `EARNIE_SHADOW_MAX_AGE_SEC` (default 120).
