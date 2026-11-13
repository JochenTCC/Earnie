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
- [ ] **[release/2.7] Log flooded with `EHAL push: no value for unbound …` every 30 s on Loxone (found 2026-11-12 in tester support):** `runtime_store/power_interval_sampler.py` reads `read_live_power_kw()` every 30 s; `LoxoneAdapter.read_telemetry` reads the optional getters in `ehal/field_registry.py::PLANT_OPTIONAL_READ_FIELDS` (export limit, ESS SoC min/max, max charge/discharge power). A site whose VO export does not include them got one WARNING per field per read (5 lines every 30 s), which pushed the cycle lines out of the 200-line Dienst-Log view within about 20 minutes and made testers ask whether the warnings matter. Fix: `integrations/loxone_client.py::fetch_loxone_generic_value` warns once per unbound EHAL ID and logs repeats at DEBUG until a value arrives again (then a later gap warns again). Reads are unchanged, so regression replays are unaffected; missing values on bound IDs still warn on every read. Verify live: Loxone install without exported `get_*` limits shows each unbound warning once after a service restart, not every 30 s.


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **[release/2.7] `set_ess_mode` is "Pflicht" in the Loxone docs but not required by EHAL-Com (found 2026-11-12 in tester support):** `docs/einrichtung/loxone-anbindung.md` (and `docs/referenz/ehal.md` § sticky backends) say Earnie writes `set_ess_mode` on every ESS cycle and Loxone Config must treat `0` as Automatik, because Virtual-In values are sticky. `ehal/required_signals.py::required_kinds_for_battery` requires only the limits and `set_ess_active_power` for `control: full`, so EHAL-Com marks the mapping complete without it; `ui/setup_readiness.py::_required_plant_live_bindings_present` still lists `set_ess_mode`, but only on the onboarding path. Consequences seen on a tester install:
  - The VI template (`scripts/pilot_vi_template_gen.py`) only contains activated `set_*` signals, so `ess.{id}.set_ess_mode` was missing.
  - `integrations/loxone_writes.py` publishes `ess.{id}.set_ess_mode` only when bound, so a hand-added VI command found no key in `status.json` and Loxone showed it as faulty.
  - `status.json` still carries the plant-flat `"set_ess_mode": 0.0` from `integrations/loxone_status_json.py::_plant_status_keys`; unbound, it is a constant placeholder that looks like a real Automatik value.
  - Fix: decide whether `set_ess_mode` is required for `control: full` on Loxone (then add it to `required_kinds_for_battery` for that backend and pre-activate it in the mapping) or optional (then fix the docs and say how Loxone Config tells Automatik from a forced `0` kW). Either way, drop or mark the plant-flat placeholder when no battery binds the mode. User docs in the same change.

## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] **[release/2.7] Inverter form: control labels and type hints read like battery settings (found 2026-11-12 in tester support):** in the Hauskonfigurator (`ui/planning_inverter_form.py::_render_inv_choice_fields`) the inverter "Steuerbarkeit" select reuses the battery labels `house_config/battery_control.py::CONTROL_LABELS_DE` ("Voll steuerbar (Zwangsladen/-entladen)", "Nur Grenzen (Automatik / Entladesperre)", "Nur lesen (Eigenverbrauch, keine Setpoints)"). For an inverter, control means the AC power limit (`inv.{id}.set_inv_ac_power_limit`, required on EHAL-Com for `full` / `limits_only`), so testers cannot tell that "Nur lesen" is the choice when they do not want curtailment. Related confusion in the same report:
  - The type "Batterie-WR (AC-gekoppelt)" was chosen for a PV string inverter whose AC surplus charges the house battery through the hybrid inverter; the type help (`battery = AC-gekoppelte Batterie`) does not say that it means a battery inverter without PV.
  - The PV field inverter select (`ui/planning_pv_form.py::_pv_capable_inverters`) silently hides battery inverters, so the second inverter was missing there without a hint.
  - Fix: own inverter labels (e.g. full = PV curtailment via AC limit, read_only = no AC limit / no curtailment), clearer type help, and a caption under the PV field select when battery inverters are hidden. User docs (`docs/konfiguration/batterie-pv.md`, Hauskonfigurator pages) in the same change.


## Document Review Findings (Do not remove this chapter — even if empty)
