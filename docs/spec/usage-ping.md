# Opt-in usage ping (installation statistics)

**Status:** draft — client P1 + daemon/milestones P2 + consent UI P3 + German docs/privacy P5 implemented in this repo; **receiver** lives in private **`JochenTCC/earnie-server`** (LAN lab compose; VPS/Caddy edge = P4 remainder). Production host: **hosttech** (EU) with AV — see §6 / §9.

## 1. Goal

Count active Earnie installations per day, with the least data possible. Strictly opt-in, revocable at any time, no effect on optimisation if the ping fails or is disabled.

Non-goals: usage analytics, feature tracking, error reporting, any per-user profile.

## 2. Principles

- **Opt-in, tri-state:** `unset` (never asked) / `on` / `off`. Only `on` sends. `unset` and `off` send nothing. Missing state file = `unset`.
- **Hard kill-switch:** env `EARNIE_USAGE_PING=off` overrides config (for packagers / paranoid users).
- **Data minimisation:** payload is a fixed whitelist (§4); no free-form fields, no config content, no prices, no locations, no device names.
- **Fire-and-forget:** ping runs off the optimisation path, short timeout, one attempt per day plus retries after failure; failure is logged at WARNING and never affects the cycle.
- **Transparency:** the UI shows the exact JSON that would be sent ("Show what is sent").

## 3. Client design

Module `runtime_store/usage_ping.py` (pure logic + `maybe_send_ping`), state in `runtime/usage_ping.json` (path helper `usage_ping_state_file()`):

```json
{
  "consent": "on",
  "consent_at": "2026-10-16",
  "install_id": "<uuid4>",
  "stage": "explorer",
  "scenarios_calc_count": 3,
  "last_sent_date": "2026-10-16",
  "last_attempt_at": "2026-10-16T12:00:00+00:00"
}
```

- Dates (`consent_at`, `last_sent_date`) and the once-per-day gate use **UTC** calendar days (`YYYY-MM-DD`), matching server UTC day aggregation.
- `install_id`: random UUIDv4, generated on opt-in, deleted on opt-out. **Not** derived from `hardware_identity`.
- `stage`: highest milestone reached (`explorer` → `live`); set on opt-in to `explorer`; raised via `set_highest_stage` / `note_explorer_activated` / `note_live_cycle_success`.
- `scenarios_calc_count`: local lifetime counter of successfully calculated scenarios (not in wire payload). Bumped by `note_scenarios_calculated(n)` after a successful Scenario Explorer run (`scripts/run_backtesting.py` after log save, `n = len(enabled scenarios)`). When consent is `on`, a bump clears `last_sent_date` and `last_attempt_at` and calls `spawn_maybe_send_ping()` so the client may POST again the same UTC day. Server still daily-dedups by salted install id until Earnie-points.
- `maybe_send_ping(now, *, transport=None, endpoint_url=None)`: no-op unless consent is `on`, `EARNIE_USAGE_PING != off`, `last_sent_date != today (UTC)`, and `last_attempt_at` is older than 1 h (or missing). POST JSON with timeout 5 s. `last_sent_date` updates only on HTTP 2xx; every attempt stamps `last_attempt_at`. Endpoint URL from `EARNIE_USAGE_PING_URL` (or `endpoint_url`); if unset and no injected transport → WARNING no-op.
- **P2 wiring:** `spawn_maybe_send_ping()` (daemon thread, at most one in flight) from `main.py` after `after_prod_cycle` and from `_daemon_wait_poll`. Live milestone after `run_state.save_run_state` with `success: true`, skipped in shadow mode. HA add-on optional bool `usage_ping` mirrored by `addon_options._apply_usage_ping_option` → `set_consent` when the key is present (absent = leave state unchanged).
- Opt-out: set consent `off`, delete `install_id` (keep `consent_at` / `last_sent_date` / `stage` / `scenarios_calc_count` as historical). No DELETE/"bye".
- **P3 consent UI (German):** `ui/usage_ping_consent.py`. Dialog on first open of Szenarienkonfigurator (`page_scenario_editor.py`) when consent is `unset` (`maybe_prompt_consent_on_editor` → Zustimmen / Ablehnen; Abbrechen leaves unset). Explorer stage via `note_explorer_activated` after consent is decided or when already set. Settings on Optimierer-Dienst (`page_daemon.py`): toggle + expander “Was wird gesendet?”. Preview via `preview_payload()` (placeholder `id` until opt-in); live `build_payload()` when consent is `on`. Kill-switch caption when `EARNIE_USAGE_PING=off`. UI state rules: `streamlit-ui-state.mdc`.

## 4. Payload (schema v1)

```json
{"v": 1, "id": "<uuid4>", "app_version": "2.7.0", "context": "homeassistant_addon", "stage": "explorer"}
```

Exact keys only: `v`, `id`, `app_version`, `context`, `stage`. `context` = `detect_install_context()` (`loxberry` / `homeassistant_addon` / `manual`). `app_version` from `version.__version__`. `stage` is the highest stage stored in state. Date is taken from the server (UTC), never sent by the client. IP is not stored (§5). No other extras (backend kind, OS/arch, country) without an explicit decision.

## 5. Server design

Minimal HTTPS endpoint `POST /ping` on a rented VPS: **Caddy** terminates TLS and is the only published service; a **stdlib HTTP receiver** sits on an internal Docker network (no TLS in-process). Implementation and deploy artifacts live in the private repo **`JochenTCC/earnie-server`** (not this public tree). See §9 Q3.

- Validate schema + size; reject everything else.
- **No IP / User-Agent logging** (disable access logs for this route; Caddy access log off).
- Count unique per UTC day: keep `{date: set(hash(id + daily_salt))}`; the salt is random per day and discarded after the day closes, so stored hashes cannot be linked across days. At day end, write `{date, installs, by_version, by_context}` and drop the set.
- Output: append-only `usage_daily.csv` / `.json` (one row per day). Optional derived views: 7-day / 30-day active (needs cross-day linkage → conflicts with the rotating salt, see Q1).
- Rate limit per IP (in memory only) against flooding; a public counter is trivially fakeable — accepted, it is a statistic, not a licence check.

## 6. Privacy / legal

- IP is personal data under GDPR even if not stored: the server must not persist it (no access log for this route; User-Agent not stored). Legal basis: consent (Art. 6(1)(a)), documented by `consent_at`.
- Production endpoint: rented VPS at **hosttech** in the **EU**; **Auftragsverarbeitung (AV)** with the host is in place.
- German user docs: `docs/user-manual/Benutzer-Handbuch-Earnie.md` (Live-Betrieb blurb) + `docs/einrichtung/betrieb.md` § Nutzungsstatistik (payload, how to switch off, Datenschutz); repo `README` one-line note under Betrieb.

## 7. Tests

- Pure logic: consent states, kill-switch, once-per-day, retry after failure, opt-out wipes ID (`tests/test_usage_ping.py`, injected clock + fake transport, no real network).
- Payload whitelist test (exact keys), UI AppTest for dialog and toggle.
- Server: schema rejection, dedup per day, salt rotation, no IP in logs.

## 8. Work packages (proposal)

1. Client module + state + payload + tests — done
2. Daemon hook + kill-switch + HA add-on option — done
3. UI consent dialog + settings toggle + "show payload" — done
4. Server + daily aggregation file + deployment — open (earnie-server; VPS/Caddy remainder)
5. German docs + privacy text — done

## 9. Open questions

### Decided

- **Q1** Random install ID, server hashes with a daily rotating salt; only daily counters stored (no 7/30-day active values).
- **Q3** Production receiver = own VPS only (not internet-facing home NAS), implemented in private **`JochenTCC/earnie-server`**. `docker compose` with two containers — **Caddy** (auto-TLS, only published service, access log off, body limit 1 KB, only `POST /ping`) and a **minimal stdlib receiver** on an internal-only network (plain HTTP, non-root, read-only rootfs, `cap_drop: ALL`, `no-new-privileges`, one writable volume, no outbound network, in-app per-IP rate limit in memory). Pre-deploy against Earnie client mock / pytest, optional **LAN-only** lab on NAS (compose in `earnie-server`, no port-forward / DDNS / DSM proxy), then deploy on the VPS.
- **Q3 hosting** Provider **hosttech**, location **EU**, **AV** (Auftragsverarbeitung) with the host in place.
- **Q3a / Q3b** Synology as **public** endpoint / DSM reverse-proxy — **won't do**. LAN-only lab on NAS via `earnie-server` is allowed.
- **Q4** Payload extras: install context only (payload §4 stays `v`, `id`, `app_version`, `context`, plus the stage from Q2).
- **Q5** CSV columns (in `earnie-server`): `date, installs_total, explorer, live, ctx_loxberry, ctx_ha, ctx_manual, versions_json`.
- **P5 docs** German user docs + README privacy note shipped (handbook Live-Betrieb, `betrieb.md` § Nutzungsstatistik).

### Q2 (interpretation to confirm)

Two counters instead of one: a `stage` field in the payload, e.g. `explorer` (first scenario exploration, i.e. the user has tried Earnie) and `live` (first successful live cycle, i.e. a real installation). Server aggregates `installs_by_stage` per day.

**Confirmed:** one opt-in, asked at the first milestone (first open of Szenarienkonfigurator). Payload field `stage` goes `explorer` -> `live`; each ping carries the highest stage reached. While consent is on, the daemon sends at most once per UTC day unless a successful scenario calc bumps `scenarios_calc_count` (same-day force POST; server still dedups).

### Still open

- VPS compose with Caddy edge (P4 remainder in `earnie-server`).
