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

- [ ] **House profile: `min_on_quarterhours = 0` of an EV / Haus Wärme consumer is silently turned into 4 (decide first):** the widgets allow `min_value=0` (`ui/house_config_profile_ev.py`, `ui/house_config_profile_thermal_annual.py`), but `house_config/profiles_consumers.py` (EV) and `house_config/profiles_thermal_annual.py` use `max(0, int(raw.get("min_on_quarterhours", 4) or 4))`, so 0 is saved and shown as 4; `tests/test_house_config.py::test_ev_min_on_quarterhours_defaults_to_four` asserts that 0 falls back to 4, so it may be intended. Found while fixing the `persons = 0` entry. Fix (decide first): either keep 0 ("no minimum run time") and change that test, or raise the widget minimum to 1.

- [ ] **House config: choosing "— neu —" silently creates a profile and jumps back to the previous one:** selecting `— neu —` in the profile select (`ui/house_config_profile_form.py::_render_profile_selector`) renders the new-profile form with the default label "Mein Haushalt"; as the form is `ready`, autosave (`_perform_house_profile_save`, `is_new=True`) writes the profile `mein_haushalt` to `house_profiles.json` immediately (empty consumers, defaults 4500 kWh/a, 48.2/11.0) and puts the profile **id** into `house_profile_select_pending`. `_align_profile_select_session` only knows display labels (`id_by_display`), so the id is rejected and the select falls back to the previously selected profile. Result: the user never gets to edit the new profile, and a "Mein Haushalt" profile appears in the list unasked. Found by the UI persistence tests (level 1, L8); regression test is `xfail(strict)` `test_l8_new_profile_selection_does_not_jump_back_to_previous_profile` in `tests/apptest/test_session_switch_apptest.py`. Fix (decide first): either do not persist a new profile before the user changed anything (and keep the select on "— neu —"), or set the pending select to the display label of the created profile. Check the same pending-id pattern in the scenario editor (`scenario_editor_sections.py:374`) and the component forms.
- [ ] **House config (browser only): the first edit after opening loses the input and creates a "Mein Haushalt" profile:** in a real browser (Playwright against `streamlit run app.py`), in roughly 60 % of page opens the profile select (`house_profile_select`) reads `— neu —` on the first rerun caused by the user (instrumented `_sync_profile_session`: `scope=__new__`, `sel=— neu —`). The new-profile form then autosaves the default profile `mein_haushalt` (see the "— neu —" entry above), the selection falls back to the previous profile and the typed value is gone (shown value reverts, e.g. 4000 instead of 5321). Not reproducible with AppTest, where session state stays on the server. Suspected cause (not verified): the select is built with `index=1` only in the first run and without `index` afterwards (`_initial_profile_index` returns None once the key exists), so the frontend sends the default index 0 for the changed widget definition. Found by the level-2 tests; regression test is `xfail(strict)` `test_house_config_first_edit_after_open_is_kept` in `tests/apptest/e2e/test_smoke.py` (six open/edit attempts, so a pass by luck is below 1 %). Fix: pass the selection through `st.session_state["house_profile_select"]` (set before the widget, no `index`) instead of `index`, and decide the "— neu —" behaviour (entry above); then drop the `xfail` and move the E2E persistence tests back to the house profile if wanted.
- [ ] **Loxone import (Smarthome-Backend) switches the backend before the import and does not catch import errors:** `ui/ehal_greenfield_import.py::_run_import` calls `persist_ehal_backend(BACKEND_LOXONE)` (writes `ehal.backend` to `config.json`) before `run_greenfield_import(...)`; an exception from the import (e.g. `ValueError` for an unknown profile) is not caught, so the page shows a traceback while the config already says `loxone` and `house_profiles.json` is unchanged (half-applied state). Only the fetch error (`LoxoneStructureError`) is handled. Found by the UI persistence tests (greenfield import); regression test is `xfail(strict)` `test_t5_failing_import_leaves_config_untouched_and_shows_error` in `tests/apptest/test_persist_greenfield_apptest.py`. Fix: run the import first, then persist backend and house document together, and show import errors with `st.error`. Also check the pending profile select (`_SESSION_SELECT_PENDING_KEY = profile_id`): same id-versus-display-label mismatch as in the "— neu —" entry above, not verified separately.


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
