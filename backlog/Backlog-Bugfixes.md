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

- [ ] **Live golden dump (private REG):** when the fixed version is running on productive NAS, capture a debug dump (with `recorder/`) around a cheap-slot Delta 3 refill and intake as a private golden case confirming charge ≤ HK ∩ live (Delta 3 standby HK/live limits fix; verified 2026-10-21).
- [ ] **Close GitHub #42** after the reporter confirms Haus Wärme is selectable on a non–Verbraucher-1 slot (e.g. Verbraucher 7) on a build ≥ `2.7.0-alpha` / next pre-release. Fix already verified in archive (2026-10-18); see [Backlog-Erledigt.md](Backlog-Erledigt.md) „Haus Wärme type after Loxone consumer import“.
- [ ] **Plausibility of pushed power (F21) — fixed, verify live:** `integrations/power_plausibility.py`; HA push reads of `inv.<id>.sens_inv_power_pv`, `pv.<id>.sens_pv_production_active` and `ess.<id>.sens_ess_power` fail loud (`Implausible value for …`) beyond 3 × the configured hardware reference (inverter PV input / AC rating / kWp, battery power). Grid power has no configured reference and is not checked; Loxone / OpenEMS paths are not covered yet. Tests `tests/test_power_plausibility.py`; lab: a 900 kW PV push is rejected with the message
- [ ] **HA write feedback (F22) — fixed, verify live:** setpoint automations use `continue_on_error`, re-check the target after 5 s and push `hub_write_failed` when it still differs (one WARNING instead of 4 nested ERRORs per attempt); Earnie shows a red notice in EHAL-Com Live-Schreiben and logs a warning at the next write (`runtime_store/ehal_push_inbox.py::hub_write_failure_age_s`, `integrations/ha_adapter_write.py`, `ui/loxone_debug.py`). New synthetic push id `hub_write_failed` (accepted by the inbox). Not done: no capability degrade / `ehal_write_error` entry (the schema enumerates setpoint fields; a contract change), no per-field detail. Packages must be regenerated. Lab: `reject_writes` → notice within seconds, expires after 3 intervals, value applied once writes work again
- [ ] **Flaky tests blocked pre-commit about every second full run — fixed, verify on CI:** (1) `runtime_store/ehal_push_inbox.py`: a timer flush wrote its snapshot into whatever runtime dir was current when it fired, and a second `flush_inbox_now` returned before an in-flight timer write finished (`test_loxone_push_inbox` family, `KeyError`/stale value); the target dir is now fixed when the data is recorded and flushes are serialized (production race, also relevant to the daemon). (2) `tests/conftest.py`: per-test runtime dir + reset of inbox/ledger memory (tests without their own `EARNIE_RUNTIME_PATH` shared the default runtime dir across xdist workers; showed up as `test_ha_active_only_mapping_writes_nothing` after the ledger became disk-aware). Six consecutive full runs green locally (previously ≈50 % red). `test_usage_points::test_refresh_skips_when_stamp_unchanged` failed once earlier and did not reappear; keep an eye on it
- [ ] **HA carrier status sensor (F13) — fixed, verify live:** `json_attributes_path: $` removed in `integrations/ha_carrier_yaml.py::_status_sensor` (tests `test_carrier_yaml_status_sensor_has_no_json_attributes_path`). Lab-verified on HA 2025.7.0 (setpoints from `status.json` reached the sim). **Existing users must regenerate and reload the package** — add to release notes and `docs/einrichtung/homeassistant-addon.md`; check on a real HA that setpoints arrive
- [ ] **Entity-scoped setpoints in HA adapter / Schreibtest (F3, F16) — fixed, verify live:** `setpoint_qualified_ids` accepts `ess.<id>.set_*` / `inv.<id>.set_*`; Schreibtest targets for push HA come from `adapter.cfg.setpoint_qids` (`integrations/ehal_write_probes.py`). Tests `tests/test_ha_push_read_setpoints.py`. Lab: no more `Missing HA push setpoint binding`, startup safe setpoints reach the sim; the **Schreibtest UI itself (sending a value) is not yet exercised** — also decides F17
- [ ] **Silent daemon death at startup (F2) — fixed, F1 decision open:** `push_safe_setpoints_on_startup` now logs the traceback to `earnie.log` and re-raises (test in `tests/test_ehal_live.py`). Still open (F1): `ehal.backend=ha` requires `EHAL_HA_BASE_URL` + `EHAL_HA_TOKEN` although push-only HA never calls REST — either drop the requirement (check Smarthome-Backend page + `tests/test_ehal_setup.py`) or correct `ehal-com.md` / `ha-lab-setup.md`, which call them optional. Also: UI reports `Auto-Start OK` although the daemon dies right after — separate
- [ ] **Carrier Jinja on non-numeric state (F7) — fixed, verify with sim:** push conversion now yields `none` (→ "push skipped" log) for `unavailable`/`unknown` (`test_carrier_yaml_push_skips_non_numeric_state`). Verify with `earnie_house_sim.set_unavailable` in a real HA run
- [ ] **`ess.<id>.sens_ess_power` required for grid-tied house batteries (F14) — fixed, verify live:** decided 2026-10-21 (required, not derived). `ehal/required_signals.py` (`grid_tied_house_batteries` moved here, `required_kinds_for_battery(..., grid_tied_house=)`), activation on Hauskonfigurator save and on inverter `ac_connection` change (`house_config/required_signal_activation.py`, `ui/house_config_*_io.py`), Signalliste marks it Pflicht, existing packs via `dm4.required_signal_activation` (detect + apply). Tests `tests/test_required_signals.py`, golden `v3_pre_ehal` and `tests/fixtures/backtesting` updated. Lab: gate triggers, migration adds the key, Live-Lesen derives plant power. **Release notes ## Migration:** every pack with a grid-tied house battery is flagged once; HA users regenerate the YAML package and map `ENTITY_ess_<id>_sens_ess_power` (documented in `docs/einrichtung/ha-evcc.md`, `docs/ui/ehal-com.md`, `docs/referenz/ehal.md`)
- [ ] **Publish ledger shared between processes (F17) — fixed, verify live:** `integrations/ehal_write.py` kept a per-process dict loaded once, so a value published by the UI (Schreibtest, other process) never reached the daemon's `status.json` (Loxone and HA; also the UI could overwrite the file with a stale view). The ledger now merges `ehal_published.json` on mtime change, newest `published_at` wins (tests in `tests/test_ehal_write.py`). Lab: a value published from a second process appears in `status.json` and reaches the sim. **Schreibtest via the Streamlit UI itself is still to be clicked through once** (the 10 s fragment refresh closes the expander and made it hard to automate; Schreibtest max is 0 W without a complete live scenario)
- [ ] **HA setpoints re-applied after restart / drift (F8, F18) — fixed, verify live:** setpoint automations now also trigger on HA start and every push interval, write only when the target drifts by more than ~1 %, and ignore fields Earnie did not publish (`integrations/ha_carrier_yaml.py::_setpoint_automation`, tests `test_carrier_yaml_setpoints_*`). Lab: after an HA restart the sim charge limit followed the published 0 W. Package must be regenerated; consider write load on real hardware (Modbus) — the drift guard avoids rewrites


## New Bugs (Do not remove this chapter — even if empty)

Found by the HA testbed baseline run (2026-10-21; evidence and finding ids F1–F18 in [`docs/dev/ha-contract-testbed.md`](../docs/dev/ha-contract-testbed.md) §3a):

- [ ] **Bugfix — Live-Schreiben lists qualified rows empty and bare `set_ess_*` rows with values (F19):** after a real cycle the table shows `ess.house.set_ess_*` without value / success and, below, bare `set_ess_charge_power_limit` etc. with the written values; the write trace is recorded under bare names while the expected rows are qualified. Also `set_ess_mode` appears as `2.0` although no mode entity is activated
- [ ] **Bugfix — Schreibtest limit is 0 W without a complete live scenario (F20):** the value field's max is `max_power_kw` of the live scenario's battery params; with an incomplete live scenario (no house profile / tariffs) every value is invalid and nothing can be written, while the table lists the fields as writable. Show why instead of a red field
- [ ] **Bugfix — Live-Lesen table missing for the HA backend (F23):** the push-state table (`0 angenommen (verstummt)`, age) is not rendered, only a summary; a silent grid push shows `Netz 0.0 · Haus 2.35 kW` with no hint that the value is assumed
- [ ] **Wording — carrier skip log for `unavailable` (F24):** says "unknown or incompatible unit_of_measurement"; say "unavailable / non-numeric state"
- [ ] **Bugfix — HouseSim S4 blocking file reads in the HA event loop (F12)** `[dev]`: `load_archetype` is called from `HouseSimCoordinator.__init__`; HA warns today, may reject in future versions. Load in an executor; resync (`scripts.sync_house_sim_integration`)


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Set default "Temperaturabsenkung" in annual-rc to 2.5°C
- [ ] Review and modify text in SE review pop-up dialogue


## Document Review Findings (Do not remove this chapter — even if empty)

- [ ] **Cloud demo vs „einmalig“ for SE star review** (`docs/einrichtung/betrieb.md`, `private-env.md`): with `EARNIE_CLOUD_DEMO=1` each browser session uses a temp workspace, so `feature_reviews.json` is session-scoped — “once per install” wording may overstate permanence on Community Cloud. Confirm whether docs should say once per session there.
- [ ] **`verify_loxone_setup` error wording** (`docs/einrichtung/loxone-anbindung.md`): „Miniserver-Callback auf `status.json` fehlt“ may not match push-only VI polling; check against script messages.
- [ ] **`Earnie_Batterie_Sollleistung` in Automatik tip** (`docs/einrichtung/loxone-anbindung.md`): catalog name vs qualified VI / optional Namenskatalog — align wording.
- [ ] **Einspeisegrenze wording** (`docs/konfiguration/batterie-pv.md`): clarify „Ohne geplante Wechselrichter“ and which two values „beide unbekannt“ refers to; confirm `1000` kW vs EHAL 1 000 000 W.
- [ ] **Handbook vs activation-flag bindings** (`docs/user-manual/Benutzer-Handbuch-Earnie.md`): after the export/Signalliste rewrite, residual Merker/Entity mapping wording may be stale — Allgemeine Verbraucher „Loxone-Leistungsmerker zuordnen“; Hausprofil / EHAL-Com Abwesenheitsmodus still names Loxone Merker / HA-Entity / OpenEMS channel as if stored in Earnie; Haus-Wärme „über EHAL-Bindings“ could point to Signalliste instead.
- [ ] **Broken handbook fragments in `ui/doc_links.py` / inbound docs:** `kurz-checkliste-vom-initial-zustand-zum-go-live` vs heading „vom ersten Start zum Go-Live“; `analyse-verbrauch-kosten` vs GitHub `analyse-verbrauch--kosten`; `gesamtkosten-und-verbrauch-jahres-verbrauch-kwh` vs likely double-hyphen slug; `betriebsmodi.md` / `charts.md` link `#gesamtkosten-jahres-verbrauch-kwh` (missing in handbook). Fix fragments or add `<a id>` anchors.
