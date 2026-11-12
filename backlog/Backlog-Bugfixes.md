# Open Bugs

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md) (sections `### Bugfix …` / `### Document Review …` / regressions)

Feature roadmap → [Backlog.md](Backlog.md)

## Classification

**Here:** Prod deviation, regression (`xfail`), known misbehavior, review with clear fix/remove outcome; plus `## Document Review Findings` (docs corrections).
**Not here:** New behavior, UX, models, research — see feature backlog in `Backlog.md`.
**Versioning:** completed bugfixes → **PATCH** only in `version.py` (no minor bump). Docs-only findings: no version bump unless asked.
**Document Review Findings:** After the agent corrects the docs → move straight to `Backlog-Erledigt.md` (skip Verifications Pending). See skill `doc-review-findings`.

### `## Bugfix Verifications Pending`

Fix is **implemented** (code + tests + optional PATCH in `version.py`), but **prod/live acceptance** is still pending.

- Move item from the thematic bugfix chapter here once the fix is committed — **not** directly to `Backlog-Erledigt.md`.
- Briefly note what changed (commit/version) if helpful.
- After successful verification: remove from this chapter → `Backlog-Erledigt.md` (`### Bugfix …`) with `- [x]`.
- If verification fails: return to open bugfix chapter or formulate follow-up; document PATCH if applicable, but do not archive as done.


## Bugfix Verifications Pending (Do not remove this chapter — even if empty) + Testing Todos

- [ ] **[release/2.7] Signalliste always showed `heartbeat_earnie` as „nie veröffentlicht“ (found 2026-11-12 in tester support):** `ehal/signal_list.py::_write_match` looked the heartbeat up in the publish ledger, but `integrations/loxone_status_json.py` fills `heartbeat_earnie` in live on every `status.json` fetch and never writes it to the ledger, so the row stayed „nie veröffentlicht“ although the Miniserver received the timestamp. Fix: the heartbeat row shows the last `status.json` fetch („MS-Abruf …“) or „status.json noch nicht abgerufen“. The fetch time is now recorded separately (`status_json_ts` in `runtime/loxone_last_callback.json`, set only by `GET …/status.json`); before, a `heartbeat_smarthome` push also counted as „MS-Abruf“ for all write rows, the watchdog and the write test (`published_fetched_at`). Verify live: Signalliste on a Loxone install shows `heartbeat_earnie` with „MS-Abruf“ within one VI poll.
- [ ] **[release/2.7] Optimizer service never ran a cycle on Loxone without `LOXONE_*` in `.env` (found 2026-11-12 in tester support):** the main loop in `main.py` waited on `runtime_store/dotenv_io.py::deferred_loxone_blocks_live` whenever the Loxone credentials were missing. The wait was logged once at INFO („optional bis Live-/Silent-Betrieb“), then only at DEBUG, and the Daemon page still showed the service as running; `Earnie_Request_Optimize` wakes were logged by the HTTP listener but never consumed. The gate was a leftover from the Miniserver poll path: since 2.7 the live path reads only the VO push inbox and writes via `status.json`. The deferred branch also never reloaded `.env`, so credentials saved in the UI after the service start kept it waiting until a restart. Same leftover: a persisted Loxone auth error (HTTP 401/403, `runtime_store/loxone_auth_error.py`) made the main loop probe the Miniserver and wait before every cycle, so a wrong password stopped the optimization. Fix: both gates removed from `main.py` (plus the dead `LoxoneAuthError` path in `integrations/loxone_connectivity.py` and `runtime_store/shadow/daemon.py::maybe_clear_auth_gate`); credentials stay needed only for the Loxone import (`LoxAPP3.json`) and the presence probe (`docs/einrichtung/loxone-anbindung.md`). The auth banner is cleared by a successful credential save in the UI or a successful startup probe (`scripts/startup_checks.py`). Verify live: Loxone install without `LOXONE_*` (and one with a wrong password) logs „--- Earnie Live-Abfrage gestartet“ at the next quarter-hour after a service restart.


## New Bugs (Do not remove this chapter — even if empty)


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] **[release/2.7] Inverter form: control labels and type hints read like battery settings (found 2026-11-12 in tester support):** in the Hauskonfigurator (`ui/planning_inverter_form.py::_render_inv_choice_fields`) the inverter "Steuerbarkeit" select reuses the battery labels `house_config/battery_control.py::CONTROL_LABELS_DE` ("Voll steuerbar (Zwangsladen/-entladen)", "Nur Grenzen (Automatik / Entladesperre)", "Nur lesen (Eigenverbrauch, keine Setpoints)"). For an inverter, control means the AC power limit (`inv.{id}.set_inv_ac_power_limit`, required on EHAL-Com for `full` / `limits_only`), so testers cannot tell that "Nur lesen" is the choice when they do not want curtailment. Related confusion in the same report:
  - The type "Batterie-WR (AC-gekoppelt)" was chosen for a PV string inverter whose AC surplus charges the house battery through the hybrid inverter; the type help (`battery = AC-gekoppelte Batterie`) does not say that it means a battery inverter without PV.
  - The PV field inverter select (`ui/planning_pv_form.py::_pv_capable_inverters`) silently hides battery inverters, so the second inverter was missing there without a hint.
  - Fix: own inverter labels (e.g. full = PV curtailment via AC limit, read_only = no AC limit / no curtailment), clearer type help, and a caption under the PV field select when battery inverters are hidden. User docs (`docs/konfiguration/batterie-pv.md`, Hauskonfigurator pages) in the same change.


## Document Review Findings (Do not remove this chapter — even if empty)
