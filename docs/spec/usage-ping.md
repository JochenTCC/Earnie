# Opt-in usage ping (installation statistics)

**Status:** draft — open questions in §9. No code yet.

## 1. Goal

Count active Earnie installations per day, with the least data possible. Strictly opt-in, revocable at any time, no effect on optimisation if the ping fails or is disabled.

Non-goals: usage analytics, feature tracking, error reporting, any per-user profile.

## 2. Principles

- **Opt-in, tri-state:** `unset` (never asked) / `on` / `off`. Only `on` sends. `unset` and `off` send nothing.
- **Hard kill-switch:** env `EARNIE_USAGE_PING=off` overrides config (for packagers / paranoid users).
- **Data minimisation:** payload is a fixed whitelist (§4); no free-form fields, no config content, no prices, no locations, no device names.
- **Fire-and-forget:** ping runs off the optimisation path, short timeout, one attempt per day plus a few retries; failure is logged at WARNING and never affects the cycle.
- **Transparency:** the UI shows the exact JSON that would be sent ("Show what is sent").

## 3. Client design

New module `runtime_store/usage_ping.py` (pure logic + one `send` function), state in `runtime/usage_ping.json`:

```json
{"consent": "on", "consent_at": "2026-10-16", "install_id": "<uuid4>", "last_sent_date": "2026-10-16"}
```

- `install_id`: random UUIDv4, generated on opt-in, deleted on opt-out. **Not** derived from `hardware_identity` (that fingerprint is stable and re-identifiable by design).
- `maybe_send_ping(now)`: no-op unless consent is `on`, `EARNIE_USAGE_PING != off` and `last_sent_date != today`. Called from the daemon loop in `main.py` (cheap check each cycle), executes the HTTP POST in a short-lived thread (timeout ~5 s). `last_sent_date` is updated only on HTTP 2xx → retried in the next cycle, naturally rate-limited by a min-interval (e.g. 1 h) after failure.
- Opt-out: set consent `off`, delete `install_id`. Optional: send one `DELETE`/"bye" is **not** needed if the server never stores the ID long-term (§5).
- Consent UI: Streamlit dialog + a toggle in the settings page; HA add-on gets an option mirrored from `addon_options.py`. UI state rules: `streamlit-ui-state.mdc`.
- Consent prompt timing: see Q2.

## 4. Payload (schema v1)

```json
{"v": 1, "id": "<uuid4>", "app_version": "2.7.0", "context": "homeassistant_addon"}
```

`context` = `detect_install_context()` (`loxberry` / `homeassistant_addon` / `manual`). Date is taken from the server (UTC), never sent by the client. IP is not stored (§5). Candidate extras (each needs an explicit yes): backend kind (loxone/ha/openems), OS/arch, country (derived server-side from IP, then discarded).

## 5. Server design

Minimal HTTPS endpoint `POST /ping` (details depend on Q3: Cloudflare Worker / small FastAPI behind the existing Caddy / other).

- Validate schema + size; reject everything else.
- **No IP / User-Agent logging** (disable access logs for this route).
- Count unique per UTC day: keep `{date: set(hash(id + daily_salt))}`; the salt is random per day and discarded after the day closes, so stored hashes cannot be linked across days. At day end, write `{date, installs, by_version, by_context}` and drop the set.
- Output: append-only `usage_daily.csv` / `.json` (one row per day). Optional derived views: 7-day / 30-day active (needs cross-day linkage → conflicts with the rotating salt, see Q1).
- Rate limit per IP (in memory only) against flooding; a public counter is trivially fakeable — accepted, it is a statistic, not a licence check.

## 6. Privacy / legal

- IP is personal data under GDPR even if not stored: the server must not persist it; mention it in the privacy note. Legal basis: consent (Art. 6(1)(a)), documented by `consent_at`.
- German user docs: new section in `docs/user-manual/` + `docs/einrichtung/betrieb.md` ("Was wird gesendet, wie abschalten"); repo `README` gets a one-line note.

## 7. Tests

- Pure logic: consent states, kill-switch, once-per-day, retry after failure, opt-out wipes ID (`tests/test_usage_ping.py`, injected clock + fake transport, no real network).
- Payload whitelist test (exact keys), UI AppTest for dialog and toggle.
- Server: schema rejection, dedup per day, salt rotation, no IP in logs.

## 8. Work packages (proposal)

1. Client module + state + payload + tests
2. Daemon hook + kill-switch + HA add-on option
3. UI consent dialog + settings toggle + "show payload"
4. Server + daily aggregation file + deployment
5. German docs + privacy text

## 9. Open questions

### Decided

- **Q1** Random install ID, server hashes with a daily rotating salt; only daily counters stored (no 7/30-day active values).
- **Q3** Receiver = own mini server on a Synology NAS (reachability from the internet, TLS and logging to be clarified, see below).
- **Q4** Payload extras: install context only (payload §4 stays `v`, `id`, `app_version`, `context`, plus the stage from Q2).

### Q2 (interpretation to confirm)

Two counters instead of one: a `stage` field in the payload, e.g. `explorer` (first scenario exploration, i.e. the user has tried Earnie) and `live` (first successful live cycle, i.e. a real installation). Server aggregates `installs_by_stage` per day.

**Confirmed:** one opt-in, asked at the first milestone (first scenario exploration). Payload field `stage` goes `explorer` -> `live`; each ping carries the highest stage reached, sent daily as long as consent is on.

### Still open

- Q3 proposal (hosting, to confirm): `docker compose` with two containers — Caddy (auto-TLS, only published service, access log off, body limit 1 KB, only `POST /ping`) and the receiver on an internal-only network (non-root, read-only rootfs, `cap_drop: ALL`, `no-new-privileges`, one writable volume, no outbound network, in-app per-IP rate limit in memory). Identical compose file runs on the NAS or a later EU VPS; only DNS and port forwarding change. On a home NAS: place it in a DMZ/VLAN, since an exposed port at home is the main residual risk.
- Q3a (original): Synology exposure — DDNS + reverse proxy (DSM) + Let's Encrypt, or Cloudflare Tunnel (no open port)? Container (Docker on DSM) vs. DSM Task Scheduler script.
- Q3b: DSM reverse proxy writes access logs with IPs by default → disable/anonymise for the ping host.
- Q5: output file format (CSV vs. JSON) and location.
