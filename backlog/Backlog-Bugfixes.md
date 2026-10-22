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
- [ ] **Small HA testbed findings F20, F23 (UI) — fixed, verify live:** (F23, corrected: the Live-Lesen table exists; its Status was derived from the empty HA entity-id mapping, so every activated, freshly pushed signal read `Kein Mapping` and the battery bindings were missing) `ui/loxone_debug_rows.py::build_telemetry_rows` now takes the push-inbox state and last receipt per activated signal (`ui/loxone_debug.py::_ha_push_read_info`): `OK`, `0 (gehalten)`, `0 angenommen (verstummt)`, receipt time instead of read time. (F20) Schreibtest explains a 0 W maximum (incomplete live scenario) with a warning. Lab: Live-Lesen shows OK + receipt times, Live-Schreiben lists 6 qualified rows, 3/3 writes, HA log without blocking-call warnings. **Still open:** `set_ess_mode` / grid export limit rows stay empty when not activated (intended); Loxone/OpenEMS Live-Lesen unchanged **Bench 2026-10-22 (F23):** the Live-Lesen Status column shows `OK` / `0 (gehalten)` per activated HA push signal, but the receipt time per signal was not visible and several OK rows show empty `Wert (EHAL)` cells (SoC, PV / grid energy, battery counters). F20 (Schreibtest 0 W warning) was not exercised.
- [ ] **Schreibtest via the Streamlit UI (F16, F17, F20) - click through once:** Schreibtest targets for push HA come from `adapter.cfg.setpoint_qids` (`integrations/ehal_write_probes.py`, F16). The UI path itself (sending a value; F20: max 0 W without a complete live scenario; the 10 s fragment refresh closes the expander and made it hard to automate) was not exercised in the bench. **Bench 2026-10-22:** the Schreibtest lists the expected qualified rows (`inv.wr_main.set_inv_ac_power_limit`, `ess.house.set_ess_active_power` (Force needed), charge / discharge limits, `heatpump.waermepumpe.set_enable`, `pool.pool_filter.set_enable`; F16 ok); sending a value could not be completed because of the refresh problem (B2 below) - one run reached `Alle schreiben`, but no publish arrived in the ledger / `status.json`.
- [ ] **`ess.<id>.sens_ess_power` required for grid-tied house batteries (F14) — fixed, verify live:** decided 2026-10-21 (required, not derived). `ehal/required_signals.py` (`grid_tied_house_batteries` moved here, `required_kinds_for_battery(..., grid_tied_house=)`), activation on Hauskonfigurator save and on inverter `ac_connection` change (`house_config/required_signal_activation.py`, `ui/house_config_*_io.py`), Signalliste marks it Pflicht, existing packs via `dm4.required_signal_activation` (detect + apply). Tests `tests/test_required_signals.py`, golden `v3_pre_ehal` and `tests/fixtures/backtesting` updated. Lab: gate triggers, migration adds the key, Live-Lesen derives plant power. **Release notes ## Migration:** every pack with a grid-tied house battery is flagged once; HA users regenerate the YAML package and map `ENTITY_ess_<id>_sens_ess_power` (documented in `docs/einrichtung/ha-evcc.md`, `docs/ui/ehal-com.md`, `docs/referenz/ehal.md`) **Bench 2026-10-22:** `dm4.required_signal_activation` adds `ess.<id>.sens_ess_power` (dry run on the shipped example pack) and the archetype generator requires it; the Hauskonfigurator save gate was not exercised.


## New Bugs (Do not remove this chapter — even if empty)

Found by the HA testbed baseline run (2026-10-21; evidence and finding ids F1–F18 in [`docs/dev/ha-contract-testbed.md`](../docs/dev/ha-contract-testbed.md) §3a):


Found by the first live run of the bench (2026-10-22; finding ids L1–L13 in the same doc, § 3f):

- [ ] **Live cycle spins without an SoC (L12):** with no `ess.<id>.sens_ess_soc` in the push inbox every cycle aborts (`Optimierung abgebrochen: Kein Zugriff auf EHAL SoC`) and the scheduler plans the next run "in 0 s" again: ~900 cycles and ~950 ERROR lines in 20 minutes until HA pushed the SoC. Add a backoff (no faster than the push interval) and a "waiting for SoC" message instead of an ERROR per cycle; also `Durchlauf erfolgreich beendet` is logged for aborted cycles.
- [ ] **Carrier skip message names the wrong cause (L13):** `integrations/ha_carrier_yaml.py` logs `unknown or incompatible unit_of_measurement … (need numeric)` when the published setpoint value is not numeric; the generated template never reads the unit for that decision. Fix the wording (+ test on the YAML).
- [ ] **`set_ess_mode` skipped for activation-only HA bindings (L9, question first):** `HaWriteMixin._write_ess_setpoints` tests `not self.cfg.entities.get("set_ess_mode")` (value), the push bindings are empty activation flags, so the mode is never published. Decide whether the mode belongs to the YAML (`ha_ess_force`) or should be published like the export limit (fixed to a key-presence test in the live run).
- [ ] **EHAL-Com Schreibtest: the expander closes and ticked rows reset on the 10 s refresh (B2):** the table fragment re-renders every ~10 s (`ui/fragment_refresh.py`); an open `Schreibtest` expander is collapsed again (`details.open=false`) and the `Senden` ticks are lost, so a value can hardly be sent by hand and not at all by automation. Keep the expander state and the row selection in `st.session_state` (skill `streamlit-ui-state`) or move the Schreibtest out of the refreshing fragment.
- [ ] **UI reports `Auto-Start OK` although the daemon can die right after (B3, split from F2):** `Streamlit maybe_auto_start` prints `main.py Auto-Start OK` right after the spawn; a startup crash (F2) is then only visible in the terminal / `earnie.log`. Check after the spawn that the daemon is alive (e.g. the lock / the listener) before reporting OK.
- [ ] **HA backend does not publish `set_evcs_mode` (B4, split from B1, from code reading, not verified live):** the HA cycle writes the EV current through `write_evcs_max_current_from_consumers` (current only); the mode (off / pv / now) is produced only by the flex path (`_evcs_current_output_values`, `_immediate_skip_output_values` in `integrations/loxone_writes.py`) that the HA branch does not call for EVs, although `docs/ui/ehal-com.md` lists `evcs.<id>.set_evcs_mode` as a write field and the Schreibtest offers it. Decide whether the HA contract needs the mode and publish it next to the current (no second current).



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
