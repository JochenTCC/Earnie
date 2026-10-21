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
- [ ] **HA carrier status sensor (F13) — fixed, verify live:** `json_attributes_path: $` removed in `integrations/ha_carrier_yaml.py::_status_sensor` (tests `test_carrier_yaml_status_sensor_has_no_json_attributes_path`). Lab-verified on HA 2025.7.0 (setpoints from `status.json` reached the sim). **Existing users must regenerate and reload the package** — add to release notes and `docs/einrichtung/homeassistant-addon.md`; check on a real HA that setpoints arrive
- [ ] **Entity-scoped setpoints in HA adapter / Schreibtest (F3, F16) — fixed, verify live:** `setpoint_qualified_ids` accepts `ess.<id>.set_*` / `inv.<id>.set_*`; Schreibtest targets for push HA come from `adapter.cfg.setpoint_qids` (`integrations/ehal_write_probes.py`). Tests `tests/test_ha_push_read_setpoints.py`. Lab: no more `Missing HA push setpoint binding`, startup safe setpoints reach the sim; the **Schreibtest UI itself (sending a value) is not yet exercised** — also decides F17
- [ ] **Silent daemon death at startup (F2) — fixed, F1 decision open:** `push_safe_setpoints_on_startup` now logs the traceback to `earnie.log` and re-raises (test in `tests/test_ehal_live.py`). Still open (F1): `ehal.backend=ha` requires `EHAL_HA_BASE_URL` + `EHAL_HA_TOKEN` although push-only HA never calls REST — either drop the requirement (check Smarthome-Backend page + `tests/test_ehal_setup.py`) or correct `ehal-com.md` / `ha-lab-setup.md`, which call them optional. Also: UI reports `Auto-Start OK` although the daemon dies right after — separate
- [ ] **Carrier Jinja on non-numeric state (F7) — fixed, verify with sim:** push conversion now yields `none` (→ "push skipped" log) for `unavailable`/`unknown` (`test_carrier_yaml_push_skips_non_numeric_state`). Verify with `earnie_house_sim.set_unavailable` in a real HA run
- [ ] **`ess.<id>.sens_ess_power` required for grid-tied house batteries (F14) — fixed, verify live:** decided 2026-10-21 (required, not derived). `ehal/required_signals.py` (`grid_tied_house_batteries` moved here, `required_kinds_for_battery(..., grid_tied_house=)`), activation on Hauskonfigurator save and on inverter `ac_connection` change (`house_config/required_signal_activation.py`, `ui/house_config_*_io.py`), Signalliste marks it Pflicht, existing packs via `dm4.required_signal_activation` (detect + apply). Tests `tests/test_required_signals.py`, golden `v3_pre_ehal` and `tests/fixtures/backtesting` updated. Lab: gate triggers, migration adds the key, Live-Lesen derives plant power. **Release notes ## Migration:** every pack with a grid-tied house battery is flagged once; HA users regenerate the YAML package and map `ENTITY_ess_<id>_sens_ess_power` (documented in `docs/einrichtung/ha-evcc.md`, `docs/ui/ehal-com.md`, `docs/referenz/ehal.md`)


## New Bugs (Do not remove this chapter — even if empty)

Found by the HA testbed baseline run (2026-10-21; evidence and finding ids F1–F18 in [`docs/dev/ha-contract-testbed.md`](../docs/dev/ha-contract-testbed.md) §3a):

- [ ] **Verify — publish ledger is per process (F17)**: `integrations/ehal_write.py` loads `ehal_published.json` once; a value published from another process (UI Schreibtest, debug script) is not in the daemon's `status.json` until restart. Check whether Streamlit-initiated writes reach HA; fix with reload-on-change or a daemon endpoint
- [ ] **Bugfix — HA setpoints are not re-applied after HA / sim restart (F8, F18)**: setpoint automations trigger only on a *change* of the `status.json` attribute; after a restart limits stay at their old values until Earnie publishes a different number. Decide: add `homeassistant: start` + periodic re-apply to the generated automations (sticky backends elsewhere re-assert)
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
