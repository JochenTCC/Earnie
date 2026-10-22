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

- [ ] **Carrier skip message names the wrong cause (L13):** fixed in `integrations/ha_carrier_yaml.py` (no version bump): the setpoint skip log names the unit only for converted units (W/kWh/%/A), otherwise `published value is not numeric`; test in `tests/test_ha_carrier_yaml_gen.py`. **Pending:** verify live on the bench (2026-10-22).
- [ ] **Recorder replay fails offline for installations with an EV `get_evcs_limit_soc` binding:** fixed in `runtime_store/cycle_recorder.py` + `runtime_store/recorder_replay.py` (no version bump): the recorder now stores the resolved limit SoC per EV in `start_state.ev_limit_soc_percent`; replay serves it for the bound marker and fails loud (`ValueError`) for cycles recorded without it. Tests in `tests/test_recorder_replay.py`. **Pending:** old cycles (e.g. the productive-NAS dump) stay unreplayable — verify with a fresh dump from the NAS (`--intake ... --update-golden`).


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Every tariff must carry a `land`; the tariff catalog and its validation allow tariffs without one:** the shipped `share/config/tariffs.json` is fine (0 of 50 without `land`), but `share/config/tariffs.example.json` (4 of 6) and the test fixture `tests/fixtures/backtesting/tariffs.json` (4 of 7: `fixed_25ct`, `fixed_37ct`, `fixed_35ct`, `monthly_test`) have tariffs without `land`, and `house_config/tariffs_store.py` (`_import_tariff_spec` / `_export_tariff_spec`) plus `share/config/tariffs.schema.json` only require it for `spot_hourly` / `ex_post_spot` / `monthly_market`. Effect: with a Land filter set, such tariffs silently drop out of the tariff selects in the Szenarienkonfigurator (only the already saved one stays visible), so the filter hides valid choices without any hint. Found by the UI persistence tests (scenario editor). Fix: make `land` mandatory for all tariff types in the schema and the loader (fail loud, no implicit fallback), give every tariff in the example file and the fixture a `land` (then adjust the tests that rely on the land-less fixture tariffs, e.g. `tests/apptest/test_persist_scenarios_apptest.py`, `tests/test_planning_editors.py`, and check `tariffs.minimal.json`), and add a validation test that rejects a land-less tariff. The user-defined pseudo tariff `__user_fixed__` ("Eigener Festpreis") is not a catalog entry and stays exempt.
- [ ] **Szenarienkonfigurator hides a rejected save (duplicate label):** `ui/pages/scenario_editor_sections.py::_auto_persist_scenario` catches the `ValueError` from `upsert_scenario` (`assert_unique_label`) with `st.error(...)`, but `auto_persist` still treats the save as done (fingerprint + "Gespeichert" flash) and the caller then runs `st.rerun()` — the error is discarded, the field keeps the rejected label and the page reports success while the file is unchanged. Found by the UI persistence tests (level 1, scenario editor); regression test is `xfail(strict)` `test_t3_duplicate_label_is_rejected_and_file_stays_unchanged` in `tests/apptest/test_persist_scenarios_apptest.py`. Fix: let `save()` signal failure to `auto_persist` (re-raise or return False) and keep the message across the rerun (flash pattern, see `auto_persist`); remove the `xfail` with the fix. Repro: Szenarienkonfigurator → rename a scenario to the label of another one.
- [ ] **Profile geo/PV defaults swallow a legitimate `0`:** `house_config/profiles_store.py::_profile_geo_and_csv_fields` uses `float(raw.get(key, default) or default)`, so `default_pv_tilt = 0` (flat roof) is saved and loaded as `25`, `latitude = 0` as `48`, `longitude = 0` as `10` — silently, no error. Found by the UI persistence tests (level 1, house profile); regression test is `xfail(strict)` in `tests/apptest/test_persist_house_profile_apptest.py` (`_KNOWN_BUGS`). Fix: distinguish missing/`None`/`""` from `0` (fail loud for invalid values, `.cursor/rules/no-implicit-fallbacks.mdc`); remove the `xfail` entry with the fix. Repro: set `Neigung` to 0 in Hauskonfigurator → new session shows 25.



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
