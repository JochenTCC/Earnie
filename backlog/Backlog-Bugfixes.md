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
- [ ] **Small HA testbed findings F19, F20, F23 (UI) — fixed, verify live:** (F23, corrected: the Live-Lesen table exists; its Status was derived from the empty HA entity-id mapping, so every activated, freshly pushed signal read `Kein Mapping` and the battery bindings were missing) `ui/loxone_debug_rows.py::build_telemetry_rows` now takes the push-inbox state and last receipt per activated signal (`ui/loxone_debug.py::_ha_push_read_info`): `OK`, `0 (gehalten)`, `0 angenommen (verstummt)`, receipt time instead of read time. (F19) `expand_ha_writes_for_live` maps bare `set_ess_*` records onto `ess.<id>.set_*`, and never-activated fields (`set_ess_mode`) are no longer recorded as successful writes (`HaAdapter.last_unconfigured_fields`, `build_ehal_write_records(unconfigured=…)`). (F20) Schreibtest explains a 0 W maximum (incomplete live scenario) with a warning. Lab: Live-Lesen shows OK + receipt times, Live-Schreiben lists 6 qualified rows, 3/3 writes, HA log without blocking-call warnings. **Still open:** `set_ess_mode` / grid export limit rows stay empty when not activated (intended); Loxone/OpenEMS Live-Lesen unchanged
- [ ] **HA write feedback (F22) — fixed, verify live:** setpoint automations use `continue_on_error`, re-check the target after 5 s and push `hub_write_failed` when it still differs (one WARNING instead of 4 nested ERRORs per attempt); Earnie shows a red notice in EHAL-Com Live-Schreiben and logs a warning at the next write (`runtime_store/ehal_push_inbox.py::hub_write_failure_age_s`, `integrations/ha_adapter_write.py`, `ui/loxone_debug.py`). New synthetic push id `hub_write_failed` (accepted by the inbox). Not done: no capability degrade / `ehal_write_error` entry (the schema enumerates setpoint fields; a contract change), no per-field detail. Packages must be regenerated. Lab: `reject_writes` → notice within seconds, expires after 3 intervals, value applied once writes work again **Bench 2026-10-22:** `hub_write_failed` reaches Earnie in every `reject_writes` run; not yet seen: the red notice in Live-Schreiben and the warning at the next write. The HA log still shows one ERROR (`Error executing script … reject_writes active`) per automation attempt next to the WARNING, not the single WARNING promised.
- [ ] **Schreibtest via the Streamlit UI (F16, F17, F20) - click through once:** Schreibtest targets for push HA come from `adapter.cfg.setpoint_qids` (`integrations/ehal_write_probes.py`, F16). The UI path itself (sending a value; F20: max 0 W without a complete live scenario; the 10 s fragment refresh closes the expander and made it hard to automate) was not exercised in the bench.
- [ ] **Silent daemon death at startup (F2) - fixed, verify live:** `push_safe_setpoints_on_startup` logs the traceback to `earnie.log` and re-raises. No startup crash occurred in the bench, so this was not triggered. Still open: the UI reports `Auto-Start OK` although the daemon can die right after (separate); a bind failure on port 8541 (`PermissionError 10013`, bench finding L2) printed its traceback in the terminal - whether it reaches `earnie.log` was not checked
- [ ] **`ess.<id>.sens_ess_power` required for grid-tied house batteries (F14) — fixed, verify live:** decided 2026-10-21 (required, not derived). `ehal/required_signals.py` (`grid_tied_house_batteries` moved here, `required_kinds_for_battery(..., grid_tied_house=)`), activation on Hauskonfigurator save and on inverter `ac_connection` change (`house_config/required_signal_activation.py`, `ui/house_config_*_io.py`), Signalliste marks it Pflicht, existing packs via `dm4.required_signal_activation` (detect + apply). Tests `tests/test_required_signals.py`, golden `v3_pre_ehal` and `tests/fixtures/backtesting` updated. Lab: gate triggers, migration adds the key, Live-Lesen derives plant power. **Release notes ## Migration:** every pack with a grid-tied house battery is flagged once; HA users regenerate the YAML package and map `ENTITY_ess_<id>_sens_ess_power` (documented in `docs/einrichtung/ha-evcc.md`, `docs/ui/ehal-com.md`, `docs/referenz/ehal.md`) **Bench 2026-10-22:** `dm4.required_signal_activation` adds `ess.<id>.sens_ess_power` (dry run on the shipped example pack) and the archetype generator requires it; the Hauskonfigurator save gate was not exercised.


## New Bugs (Do not remove this chapter — even if empty)

Found by the HA testbed baseline run (2026-10-21; evidence and finding ids F1–F18 in [`docs/dev/ha-contract-testbed.md`](../docs/dev/ha-contract-testbed.md) §3a):


Found by the first live run of the bench (2026-10-22; finding ids L1–L13 in the same doc, § 3f):

- [ ] **Live cycle spins without an SoC (L12):** with no `ess.<id>.sens_ess_soc` in the push inbox every cycle aborts (`Optimierung abgebrochen: Kein Zugriff auf EHAL SoC`) and the scheduler plans the next run "in 0 s" again: ~900 cycles and ~950 ERROR lines in 20 minutes until HA pushed the SoC. Add a backoff (no faster than the push interval) and a "waiting for SoC" message instead of an ERROR per cycle; also `Durchlauf erfolgreich beendet` is logged for aborted cycles.
- [ ] **Carrier skip message names the wrong cause (L13):** `integrations/ha_carrier_yaml.py` logs `unknown or incompatible unit_of_measurement … (need numeric)` when the published setpoint value is not numeric; the generated template never reads the unit for that decision. Fix the wording (+ test on the YAML).
- [ ] **`set_ess_mode` skipped for activation-only HA bindings (L9, question first):** `HaWriteMixin._write_ess_setpoints` tests `not self.cfg.entities.get("set_ess_mode")` (value), the push bindings are empty activation flags, so the mode is never published. Decide whether the mode belongs to the YAML (`ha_ess_force`) or should be published like the export limit (fixed to a key-presence test in the live run).



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
