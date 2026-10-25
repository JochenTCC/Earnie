# Completed Items

Archive of completed work. Open todos → [Backlog.md](Backlog.md) · Bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md).

### Bugfix CI `ui-e2e` and blocking climate fetch in the house config (2026-10-25)

- [x] **CI job `ui-e2e` red on every run — fixed:** `test_house_config_first_edit_after_open_is_kept` hung at the first `_wait_until_idle`: the e2e server (own process, no climate mock) downloaded Open-Meteo climate data for the `thermal_annual` consumer of `test_home` when the house config opened; with a cold cache that exceeded the 60 s wait (local runs had a warm gitignored `data/cache/open_meteo`). New env var `EARNIE_OPEN_METEO_CACHE_PATH` (`data/open_meteo_solar_archive.py`, documented in `docs/einrichtung/betrieb.md`); the e2e conftest seeds that cache from an AppTest run of the page with the mock. On failure the e2e run prints the Streamlit server log and a browser diagnosis.
- [x] **Hauskonfigurator blocked the page for minutes on a slow/rate-limited Open-Meteo — fixed:** `climate_fetch_budget(seconds)` / `ClimateFetchBudgetExceeded` in `data/open_meteo_solar_archive.py` (total budget over all attempts, per-request timeout capped to the remaining time, no sleep past the budget). `ui/pages/page_house_config.py` renders inside a 30 s budget with a spinner and shows an error on overrun (no silent fallback; the next open retries). A download that needs more than 30 s never completes and is not cached partially. Docs: `docs/konfiguration/flexible-verbraucher.md`.

### Version 2.8 — streamlit-ports translation (2026-10-24)

- [x] **Translate `docs/dev/streamlit-ports.md` to English** `[dev]`: [docs/dev/streamlit-ports.md](../docs/dev/streamlit-ports.md) translated; paths, ports, env vars, compose names, launch-entry names and link targets unchanged. The inbound user-doc links (`betrieb.md`, `container.md`, handbook, `docs/README.md`, …) stay as they are and point to the English dev doc (decided 2026-10-24: keep the links, do not move the production-port part into a user doc).

### Issue #50 — HA YAML package (2026-10-24)

- [x] **Issue #50 / [#60](https://github.com/JochenTCC/Earnie/issues/60) (c) — watchdog for a forced active power when Earnie is unreachable — implemented and verified live:** decisions 2026-10-24: release only the sticky force (`set_ess_active_power` -> 0, or `huawei_solar.stop_forcible_charge` with `ha_ess_force`), caps / mode / EV current stay, default 300 s, on by default and switchable. `integrations/ha_carrier_yaml.py::_watchdog_automation` adds the automation `earnie_watchdog_release_force` (state trigger: `sensor.earnie_ehal_status` `unavailable` / `unknown` for the timeout); `scripts/ha_carrier_yaml_gen --watchdog-s` (0 = off); header comment in the package; no watchdog without an active-power signal. Tests in `tests/test_ha_carrier_yaml_gen.py`; docs `docs/einrichtung/ha-evcc.md`, `docs/ui/ehal-com.md`. **Live check 2026-10-24 (lab HA 2025.7.0, package generated from the lab pack, status.json stub, lab restored afterwards):** with the stub up the setpoint automation applied 3000 W to the target; after the stub went down the status sensor became `unavailable`, its attributes were empty (so the periodic re-assert did not re-apply the old force), the watchdog fired exactly 60 s later (test timeout) and set the target to 0; with the stub back the sensor recovered and the setpoint automation applied 3000 W again. Not run: with a real inverter and the full Earnie push chain. Release notes: mention the new automation (draft later).
- [x] **Issue #50 / [#60](https://github.com/JochenTCC/Earnie/issues/60) (a)+(b) — export hint and `input_number` targets — fixed and verified live:** (a) the EHAL-Com export section said "HA-YAML-Paket folgt mit Binding P5c"; it now points to the section "HA Push-Carrier" (`ui/ehal_signal_list.py`, AppTest in `tests/apptest/test_persist_signal_list_apptest.py`). (b) the generated apply step always called `number.set_value`; `integrations/ha_carrier_yaml.py::set_value_action` now emits `{{ 'ENTITY_x'.split('.')[0] }}.set_value`, so the domain follows the entity entered for the placeholder (`tests/test_ha_carrier_yaml_gen.py`). **Live check 2026-10-24 (lab HA 2025.7.0, throw-away package, lab config restored afterwards):** the action blocks were taken from a package generated from the lab pack (`scripts.ha_carrier_yaml_gen`) with the placeholder replaced; run from an HA automation, the templated action set a template `number` to 4242 and an `input_number` to 4243. The old literal `number.set_value` against the same `input_number` left it unchanged (reproduces the reporter's failure). Not run: the full carrier chain with the Earnie push and `ha_testbed_check` (needs onboarding and a token). Open: (c) watchdog, see `Backlog-Bugfixes.md`.

### Issue #50 — decided not to change (2026-10-24)

- [x] **Tariff preview keeps listing "Abwicklungsgebühr" for `monthly_table`:** the load warning for `settlement_fee_cent_kwh` is enough; `fixed_cent` already hides the row. No change (maintainer decision).
- [x] **No extra hint "0 = no grid costs" in the house profile (Netznutzung):** not wanted; the docs state it (`docs/konfiguration/preise.md`). No change (maintainer decision).

### Issue #50 — verified by UI tests (2026-10-24)

- [x] **`settlement_fee_cent_kwh` on `fixed_cent` / `monthly_table`: load warning — implemented (`3517ccbe`) and verified (AppTest):** the scenario editor loads the tariff catalog; with a fixed tariff carrying a 9.08 ct fee the page renders without exception, the tariff stays selectable, and exactly one warning naming the tariff and `netznutzung` is logged, also over a second run (`tests/apptest/test_issue50_ui_apptest.py`, plus `tests/test_tariff_settlement_fee_warning.py`). A spot tariff with a fee does not warn. Mutation check: with the warning call removed the test is red. The tariff preview still lists the field, see the minor item in `Backlog-Bugfixes.md`.
- [x] **"Jetzt neu berechnen" on the Optimierer-Dienst page — implemented (`e3933822`) and verified (AppTest + HTTP):** the button is disabled while the daemon is stopped or no plan input is newer than the last run, and enabled otherwise (real mtime logic with probe files); a click calls the request once and shows "Neuberechnung angefordert."; an unreachable daemon shows an error instead of an exception; an end-to-end click sends a real `POST` to `/ehal/loxone/request_optimize` on a throw-away listener. Tests `tests/apptest/test_issue50_ui_apptest.py` (9 tests, `apptest` suite 338 passed); mutation check: with the disable logic removed four tests are red. Not run against a real `main.py` daemon.
- [x] **Issue #50 / 1b — VAT on `netznutzung` for tariffs with `prices_include_vat: true` — fixed (`3517ccbe`), closed 2026-10-24:** the net grid fee was added without VAT (about 20 % too low in AT; confirmed by the Vorarlberger Energienetze price sheet 2026). `data/tariff_pricing.py::grid_fee_on_tariff_basis`, `simulation/se_invoice_netznutzung.py`, land VAT for the user-fixed import (`apply_land_vat_to_user_fixed_import`), warning for gross import tariffs without `vat_percent`, `share/config/tariffs.example.json` completed. Evidence: `tests/test_tariff_pricing.py`, L2 case `REG-S-gross-tariff-netznutzung` (k_act 18 ct = 12 + 5 x 1.2), all 11 public golden-master cases pass. Closed on the maintainer's decision without private golden-master cases (none exist yet) and without the reporter's acceptance (his net-price setup is not affected). Follow-up VAT model: feature item in `Backlog.md` (Version 2.+1).
- [x] **Issue #50 / [#59](https://github.com/JochenTCC/Earnie/issues/59) — EU power data: retry loop without an error cache blocked the cycle — fixed (`235c8ebb`), closed 2026-10-24:** `_http_get_json` retried every connection error 5 times for each of 12 countries (over 12 min per cycle with energy-charts unreachable, stale heartbeat, unhealthy container). Now `ApiUnreachableError` at the first connection error or timeout, `fetch_eu_power_hourly` aborts instead of asking the other countries, a failed live feature load pauses for 1 h per mode (`LIVE_FEATURE_FAILURE_BACKOFF_SEC`); 429 keeps its backoff; `missing_price_strategy: mirror` already switches the EU requests off (documented in `docs/konfiguration/preise.md`). Evidence: tests in `tests/test_eu_market_features.py` and `tests/test_price_forecast_live.py` (red before); local run against an unreachable host returned after one attempt (2.4 s refused connection, 5.3 s with a 3 s timeout) with one warning, the second call in the pause took 0.0 s. Closed on the maintainer's decision without a container health check during a real outage; the reporter's IP block is not proven to stem from the old loop. Backtest/training fetches no longer retry timeouts either.
- [x] **Issue #50 / [#56](https://github.com/JochenTCC/Earnie/issues/56) — leftover `ehal.ha.sign` applied on top of the HA push after the 2.6 -> 2.7 migration — fixed (`9bff652a`), verified 2026-10-24:** reported with Live-Lesen +1130 W but a live power line of battery -1.13 kW / house -1.03 kW; removing `sign` fixed it. Every push read applies `sign` (`integrations/ha_push_read.py::read_push_ehal_value`) and `ehal.ha.sign` stays a documented setting for hub-native signs, so the migration asks instead of removing it blindly: new step `dm4.ha_sign` (`runtime_store/migration/steps/ha_sign.py`), only from data model 3 with HA backend and a non-empty `sign`, required choice `ha_sign.remove` (`Behalten` / `Entfernen`), `Entfernen` empties `sign` and leaves a to-do to check Live-Lesen against the live power line; never asked again on model 4. Evidence: fixture `tests/fixtures/migration/v3_ha_sign`, six tests in `tests/test_migration_registry.py`; `scripts.migrate_config` on fixture copies (no answer -> exit 1, nothing written; Entfernen -> `{}`; Behalten keeps both `negate` entries; no second question); wizard click-through on an isolated pack in the browser (question, empty dropdown, both answers, to-do on the report page). Docs: `docs/einrichtung/betrieb.md`, `docs/workflow/config-migration.md`; the release-notes helper lists the step. Not covered: installs that already migrated to model 4 (like the reporter's alpha.9) are not asked and keep the entry; no run against a real 2.6 HA install.

### Document Review — Issue #50 tariff and daemon docs (2026-10-24)

- [x] **`settlement_fee_cent_kwh` description misled:** `docs/konfiguration/preise.md` and `docs/referenz/tarife-quellen.md` now state that the field is a supplier surcharge on the exchange price, spot types only, without effect on `fixed_cent` / `monthly_table` (Earnie warns at load); grid costs belong to `netznutzung` in the house profile and apply to all import types (0 = off). Corrected in `3517ccbe`. The 2.6.2 docs keep the old wording (no backport planned).
- [x] **User manual: "Optimierer-Dienst" explains the quarter-hour cycle and "Jetzt neu berechnen":** `docs/user-manual/Benutzer-Handbuch-Earnie.md` (config changes act from the next run, the button starts a run at once, a daemon restart does not speed it up). Added in `e3933822`.

### Issue #50 — grid fee default (2026-10-24)

- [x] **12.0 ct/kWh grid fee in a live setup:** not a code default (0 in `v2.6.2` and `release/2.7`). The reporter confirmed having pasted the fixed energy price (`fix_cent_kwh` 12.0) into `netznutzung_arbeitspreis_cent_kwh`; corrected to 9.08 ct, import price now 25.30 ct. No change; the new load warning for `settlement_fee_cent_kwh` on fixed tariffs covers the related misconfiguration (the reporter first entered the grid cost there).

### Document Review — Loxone/Signalliste/Cloud-Demo wording (2026-10-23)

- [x] **Cloud demo vs „einmalig“ for SE star review** (`betrieb.md`, `private-env.md`): docs now say the review state is per browser session on Community Cloud (`EARNIE_CLOUD_DEMO=1`, temp workspace).
- [x] **`verify_loxone_setup` error wording** (`loxone-anbindung.md`): replaced the stale callback/rights errors with the real push-inbox messages (`[OK]`/`[WARNUNG]`/`[FEHLER]`); write path is not checked by the script.
- [x] **`Earnie_Batterie_Sollleistung` in Automatik tip** (`loxone-anbindung.md`): now refers to the VI for `set_ess_active_power` with the catalog name as optional.
- [x] **Einspeisegrenze wording** (`batterie-pv.md`): clarified „Ohne Wechselrichter in der Anlagen-Topologie“ and the 0/unknown case; `1000` kW = 1 000 000 W confirmed against `optimizer/export_power_limit.py`.
- [x] **Handbook vs activation-flag bindings** (`Benutzer-Handbuch-Earnie.md`): Allgemeine Verbraucher, Abwesenheitsmodus (Hausprofil + Backend section) and Haus-Wärme now point to the Signalliste instead of Merker/Entity/Channel mapping.

### Version 2.7 — Pre-release dogfood + HA docs review (2026-10-23)

- [x] **Dogfood greenfield Earnie configuration for a Loxone SB** `[qual]`
- [x] **Pre-Release 2.7.0-alpha.7 for Loxone** `[qual]`
- [x] **Dogfood and finalize new HA binding** `[qual]`
- [x] **Review HA related docs** `[qual]`: user-facing docs changed in the HA doc review
  - [x] [docs/einrichtung/homeassistant-addon.md](../docs/einrichtung/homeassistant-addon.md)
  - [x] [docs/einrichtung/ha-evcc.md](../docs/einrichtung/ha-evcc.md) (rewritten: one guide, two starting points; lab parts → `docs/dev/ha-lab-setup.md`)
  - [x] [docs/einrichtung/smarthome-backend-wahl.md](../docs/einrichtung/smarthome-backend-wahl.md)
  - [x] [docs/einrichtung/container.md](../docs/einrichtung/container.md)
    - [x] Anmerkungen eingefügt
  - [x] [docs/einrichtung/betrieb.md](../docs/einrichtung/betrieb.md) (port key / env var)
    - [x] Anmerkungen eingefügt
  - [x] [docs/einrichtung/loxberry-plugin.md](../docs/einrichtung/loxberry-plugin.md) (port key)
  - [x] [docs/ui/smarthome-backend.md](../docs/ui/smarthome-backend.md)
  - [x] [docs/ui/ehal-com.md](../docs/ui/ehal-com.md) (English)
  - [x] [docs/ui/betriebsmodi.md](../docs/ui/betriebsmodi.md) (history sentences removed)
  - [x] [docs/referenz/loxone-signals.md](../docs/referenz/loxone-signals.md) (port key)
  - [x] [docs/referenz/ehal.md](../docs/referenz/ehal.md) (English, rather a spec)
  - [x] [docs/README.md](../docs/README.md)
  - [x] [docs/user-manual/Benutzer-Handbuch-Earnie.md](../docs/user-manual/Benutzer-Handbuch-Earnie.md)
  - [x] Add-on tab "Dokumentation": [earnie/DOCS.md](../packaging/homeassistant-addon/earnie/DOCS.md) + [earnie_prerelease/DOCS.md](../packaging/homeassistant-addon/earnie_prerelease/DOCS.md)
  - [x] Add-on tab "Konfiguration" (option texts, option rename `ehal_loxone_http_port` → `ehal_http_port`): [earnie/translations/en.yaml](../packaging/homeassistant-addon/earnie/translations/en.yaml) + [earnie_prerelease/translations/en.yaml](../packaging/homeassistant-addon/earnie_prerelease/translations/en.yaml)
  - [x] Add-on port description (`ports_description` only): [earnie/config.yaml](../packaging/homeassistant-addon/earnie/config.yaml) + [earnie_prerelease/config.yaml](../packaging/homeassistant-addon/earnie_prerelease/config.yaml)

### Version 2.7 — HK wait UX for first consumption calculations (2026-10-23)

- [x] **HK spinner + session memo for first modeled-year consumption charts** `[feat]`: Gesamt-Lastverhalten (model-only and Ist-vs-Modell probe) shows `Modell-Jahresverbrauch wird berechnet…` on cache miss; `ui/consumption_display/bundle_cache.py` memos bundles in `st.session_state` keyed by profile / CSV fingerprint so widget reruns do not rebuild. Wired in `ui/consumption_display/panel.py` and `ui/house_config_historical_csv.py`. Tests: `tests/test_consumption_bundle_cache.py`.

### HA carrier bugfixes (2026-10-23)

- [x] **Carrier skip message names the wrong cause (L13) — fixed and verified live on the bench:** `integrations/ha_carrier_yaml.py` (no version bump): the setpoint skip guard (`hub_value is none` → unit message) is generated only for converted units (W/kWh/%/A); for all other units a non-numeric value is already stopped by `Earnie published no value for this field`, so no dead guard or misleading text is emitted. Test: `test_carrier_yaml_setpoint_skip_message_only_for_converted_units` in `tests/test_ha_carrier_yaml_gen.py`. Bench (HA 2025.7.0, Earnie in the bench, 2026-10-23): `ess.house.set_ess_charge_power_limit` target with a foreign `unit_of_measurement` (`°C` via `customize`) logs `... unknown or incompatible unit_of_measurement on number.earnie_ess_house_set_ess_charge_power_limit (need W)` and does not write; without the override a deviating value is corrected again (W path), as is `heatpump.waermepumpe.set_enable` (no unit, no guard, no skip log); `ha_testbed_check --require-all` 11 PASS / 0 FAIL.

### House profile bugfixes (2026-10-23)

- [x] **House profile: `min_on_quarterhours = 0` of an EV / Haus Wärme consumer was silently turned into 4 — fixed and verified (unit + full suite):** decided 2026-10-23: the minimum run time is never 0, minimum 1 and default 1. The widgets (`ui/house_config_profile_ev.py`, `ui/house_config_profile_thermal_annual.py`, also the Wärme-RC one in `ui/house_config_profile_thermal.py`) use `min_value=1`; `house_config/profiles_consumers.py` and `house_config/profiles_thermal_annual.py` normalize with `max(1, int(raw.get(..., 1) or 1))`, the serializers default to 1. `planning_thermal_to_milp` no longer raises the value to at least 4 (`max(4, …)` → `max(1, …)`), otherwise a configured 1 would have had no effect in the optimizer; the defaults in `planning_ev_to_milp` and `optimizer/milp_consumer_vars.py::_min_on_hours` are 1 as well. Stored configs with 0 are clamped to 1 on load. Tests: `test_ev_min_on_quarterhours_defaults_to_one_and_is_never_zero`, `test_planning_thermal_to_milp_bridge` adjusted.

### Document Review — handbook fragments (2026-10-23)

- [x] **Broken handbook fragments in `ui/doc_links.py` / inbound docs:** the handbook now carries explicit anchors (`<a id="analyse-verbrauch-kosten">`, `gesamtkosten-jahres-verbrauch-kwh`, `kurz-checkliste-go-live`, same style as `pv-anlagen`), so the links no longer depend on GitHub slug rules; `ui/doc_links.py` uses `gesamtkosten-jahres-verbrauch-kwh` (as `betriebsmodi.md` / `charts.md` already did) and `kurz-checkliste-go-live`. This also repairs the "Jahres Verbrauch" link in `ui/backtesting_results.py`, whose lookup by fragment never matched the old value. New tests in `tests/test_doc_links.py` check every `DocLink` fragment against the target document and every inbound handbook link in `docs/`.

### UI persistence bugfixes (2026-10-22)

- [x] **House config (browser only): the first edit after opening lost the input and created a "Mein Haushalt" profile — fixed and verified (Playwright):** cause confirmed as suspected: the profile select got `index=` only on the first run and none afterwards, so the changed widget definition made the browser send its default index 0 ("— neu —") with the user's first edit. `ui/house_config_profile_form.py::_render_profile_selector` now preselects through `st.session_state["house_profile_select"]` (before the widget, `_render_profile_select_row` takes no `index`). Verified with the real browser test `test_house_config_first_edit_after_open_is_kept` (`xfail` removed; 6 open/edit attempts per run, passed in three consecutive runs after failing consistently before) and the whole e2e suite (5 passed); the "— neu —" behaviour was decided in the entry above.

- [x] **House config: choosing "— neu —" silently created a profile and jumped back to the previous one — fixed and verified (AppTest):** decided 2026-10-22: a new profile is only created after the user changed something. `ui/house_config_profile_save.py::_render_house_profile_save` compares the payload with a baseline taken from the freshly seeded defaults (`_NEW_PROFILE_BASELINE_PREFIX`, reset by `_sync_profile_session` on every re-seed) and saves nothing while they are equal; the select stays on "— neu —". The pending select, which carries a profile **id** (new profile, Loxone import), is now mapped to the display label first in `_align_profile_select_session`, so after the first edit the new profile is selected instead of the previous one. The Loxone import (`_SESSION_SELECT_PENDING_KEY = profile_id`) uses the same path; the scenario editor and component forms were checked and set their own selects consistently. `xfail(strict)` test replaced by three tests in `test_session_switch_apptest.py` (defaults shown, nothing created unasked, first edit creates and selects the profile).

- [x] **Loxone import (Smarthome-Backend) switched the backend before the import and did not catch import errors — fixed and verified (AppTest):** `ui/ehal_greenfield_import.py::_run_import` now runs `run_greenfield_import` first and shows a failure (`ValueError` / `OSError`) with `st.error("Loxone-Import fehlgeschlagen — nichts gespeichert: …")`; only after a successful import it writes the house document and `ehal.backend=loxone` together. A failing import leaves `config.json` and `house_profiles.json` untouched. `xfail(strict)` of `test_t5_failing_import_leaves_config_untouched_and_shows_error` removed. The pending-profile-select check from the original entry moved to the open "— neu —" entry.

- [x] **EHAL-Com signal list raised `ConfigReadOnlyError` when toggling a signal in Shadow mode — fixed and verified (AppTest):** with a read-only Shadow config `ui/ehal_signal_list.py::_render_optional_toggles` now disables the switches and shows the same caption as the autosave forms (`ui/auto_persist.SHADOW_READONLY_CAPTION`, the text now lives in one constant), and a `ConfigReadOnlyError` from `_persist_docs` is caught and shown as that hint instead of a traceback. `xfail(strict)` test replaced by `test_t3_shadow_mode_disables_the_switches_and_shows_the_hint` and `test_t3_read_only_write_error_is_shown_as_hint_not_as_exception` (AppTest refuses to change a disabled widget, so the write path is covered with a forced error).

- [x] **EHAL-Com signal list overwrote an unreadable `components.json` with an empty document — fixed and verified (AppTest):** `ui/ehal_signal_list.py` no longer substitutes `{"batteries": [], "pv_systems": []}` (or `{}` for the house document) on a load failure. `render_ehal_signal_list_section` catches `ValueError` / `OSError` of the load, shows an `st.error` ("Signalliste nicht verfügbar: Konfiguration nicht lesbar — …") and renders neither table nor switches, so nothing can be saved over the broken file. The bare `except Exception` around the push inbox and publish ledger reads is removed as well (those readers already return empty for a missing / invalid file by contract; unexpected errors now surface instead of showing "nie empfangen"). `xfail(strict)` of `test_t3_unreadable_components_file_is_reported` and `test_t3_toggle_never_overwrites_an_unreadable_components_file` removed; the tests now restore the file through a fixture.

- [x] **Every tariff must carry a `land` — fixed and verified (unit + full suite):** `house_config/tariffs_store.py::_require_land` makes `land` mandatory for every import and export tariff type (fail loud, message names the tariff), replacing the per-type check for spot / market tariffs; `share/config/tariffs.schema.json` requires it for `import_tariff` and `export_tariff`. `share/config/tariffs.example.json` and `tests/fixtures/backtesting/tariffs.json` give their land-less tariffs `land: AT`; the shipped `tariffs.json` and `tariffs.minimal.json` already complied. Inline tariff dicts in tests got a `land`; new `tests/test_tariff_land_required.py` (rejects a land-less tariff, checks all shipped / fixture catalogs). `__user_fixed__` stays exempt. German reference updated (`docs/referenz/tarife-quellen.md`). **Note:** a user-made tariff without `land` in a live `tariffs.json` is now rejected on load; no migration step was added (tariff track belongs to Edbert).

- [x] **House profile: `persons = 0` of a Haus Wärme consumer was silently turned into 2 — fixed and verified (AppTest + unit):** decided 2026-10-22: 0 persons is not meaningful for the thermal model (absence is the absent mode, which overrides the already normalized dict and never passes the loader). The widget minimum is now 1 (`ui/house_config_profile_thermal_annual.py`) and `house_config/profiles_thermal_annual.py::_persons` raises for `persons < 1` (missing / empty still defaults to 2). The same `or` pattern also swallowed a flat solar collector (`solar_thermal_tilt_deg = 0` became 18); fixed likewise. `_KNOWN_BUGS` of `test_persist_consumers_apptest.py` removed (boundary now `persons` 1 and 2, plus `solar_tilt` 0 is covered by the unit test); new `tests/test_profile_thermal_defaults.py`.

- [x] **Profile geo / PV defaults swallowed a legitimate `0` — fixed and verified (AppTest + unit):** `house_config/profiles_store.py::_float_field_or_default` replaces `float(x or default)` for `latitude`, `longitude`, `default_pv_tilt` and `default_pv_azimuth`: only a missing / `None` / empty value uses the default, `0` (flat roof, longitude 0) round-trips, a non-numeric value raises `ValueError`. The `_KNOWN_BUGS` entry in `test_persist_house_profile_apptest.py` is removed (the `default_pv_tilt = 0` boundary case now passes); new `tests/test_profile_geo_defaults.py`.

- [x] **Battery form accepted `max. SoC` below `min. SoC` without any message — fixed and verified (AppTest + unit):** decided 2026-10-22: strict rule `battery_min_soc < battery_max_soc` (equal would be a zero-width window). `house_config/battery_normalize.py::_validated_soc_window` raises a `ValueError` naming both values; the form shows it via the rejected-save path and the file stays unchanged, a config that already violates the rule now fails loud on load. `xfail(strict)` of `test_t3_battery_max_soc_below_min_soc_is_rejected` removed; new `tests/test_battery_soc_window.py`. Full suite green (no shipped config or fixture violated the rule).

- [x] **Inverter and PV field forms gave no hint when the label was empty — fixed and verified (AppTest):** the shared helper `ui/auto_persist.warn_not_saved(subject, blockers)` (extracted from the battery form, which now uses it) shows "… noch nicht gespeichert: …" with the blockers; the inverter form names `Bezeichnung`, the PV form `Bezeichnung`, `kWp > 0` and the missing inverter. `xfail(strict)` of `test_t3_empty_label_is_not_saved_and_user_is_told[planning_inv_label|planning_pv_label]` removed.

- [x] **Save confirmations were never shown (`st.success` directly before `st.rerun()`) — fixed and verified (AppTest):** new `ui/flash.py` (`flash(kind, text)` queues the notice in the session, `render_flash_notices()` shows it once; `app.py` calls it before the page, the AppTest page/form scripts stand in for that shell). Used for OpenEMS connection, Home Assistant selection, Loxone credentials (and `.env` import), Silent switch, daemon start/stop/restart, LAN subnet, plus the same pattern in the Loxone mapping save, house profile save, scenario removal and the inverter / PV / battery forms ("ID gesetzt", "… entfernt", EcoFlow Delta 3). The `xfail(strict)` markers of `test_l3_*` and `test_d2_action_confirmation_is_visible` are removed; new `test_l3_lan_subnet_save_confirmation_is_visible` and `tests/test_flash.py`.

- [x] **Autosave hid rejected saves (scenario editor, inverter / PV / battery forms, house profile consumers) — fixed and verified (AppTest):** a `save` callback can now refuse a write by raising `ui/auto_persist.PersistRejected` (helper `require_saved` for store helpers that return `None`); `auto_persist` then records no fingerprint, flashes no `Gespeichert` and returns False, so the callers no longer `st.rerun()` the `st.error` away and the file stays unchanged. Applied in `_auto_persist_scenario`, `_save_inv` / `_save_pv` / `_save_battery` and `_render_house_profile_save`. The `xfail(strict)` markers of `test_t3_duplicate_label_is_rejected_and_file_stays_unchanged`, `test_t3_duplicate_label_shows_error_and_keeps_file` (3 cases) and `test_t3_rejected_value_shows_error_and_keeps_file[ev-min-power-above-nominal]` are removed; `tests/apptest` green (275 passed).
- [x] **Konfiguration: `Neu laden (Datei)` raised `StreamlitWidgetAlreadyInstantiatedError` (found 2026-10-22, reproduced with AppTest) — fixed, then moot:** `cc977b09` moved the reload of the `config_json_editor` text area into an `on_click` callback (read errors shown as `st.error` on the next run) with AppTest regressions. The same day `e84497b4` removed the whole raw `config.json` editor page (`ui/pages/page_config.py`), which had been out of the navigation since 2026-07-11 and was linked from nowhere, together with its tests. Nothing left to verify.

### HA testbed fixes verified live (2026-10-22)

- [x] **Schreibtest 0 W warning without a complete live scenario (F20) — fixed and verified (AppTest):** `ui/ehal_write_test.py::power_limit_unknown_notice` explains why every power value is rejected when the live scenario has no battery maximum (`render_write_test_section` shows it when `max_power_kw <= 0`). Tests `tests/test_ehal_write_test.py::test_power_limit_notice_names_the_live_scenario` (text) and, rendered through the section, `tests/test_ehal_write_test_ui_state.py::test_incomplete_live_scenario_shows_power_limit_warning` / `test_complete_live_scenario_shows_no_power_limit_warning`. **Verified (2026-10-22):** by the AppTest only; the bench scenario is complete, so the warning was not exercised against a pack with an incomplete live scenario (owner accepted this).
- [x] **HA: a forced `set_ess_active_power` is released on automatic (L18) — fixed and verified live:** decided 2026-10-22 (option a): on the HA backend with `batteries[].control = full`, `write_ess_setpoints_from_control` publishes `set_ess_active_power = 0` whenever the mapping yields no force (automatic, Entladesperre, startup safe push), so the sticky HA `number` no longer keeps the last force (the Huawei `ha_ess_force` automation releases at `|power| < 1`). Limits-only batteries, other backends and a not activated signal are unchanged. Tests `tests/test_ha_ess_release.py` (red before). `EVCS_MODE_VALUES` moved to `ehal/field_catalog.py` (no cross import of the Loxone adapter into the HA adapter). **Bench:** force charge `-2000 W` (sim `ess_power -2000`, SoC rising) -> automatic: ledger, `status.json` and the HA `number` went to 0 and `ess_power` to 0 (before: stayed at -2000 for several cycles). Known trade-off: a device where `0` means "hold at 0 W" (the sim) idles instead of self-consumption and needs its own mapping of `set_ess_mode`; documented in `docs/referenz/ehal.md`.
- [x] **EV mode on the HA backend (B4) — verified live:** `write_evcs_max_current_from_consumers` publishes `set_evcs_mode` (off=0 / pv=1 / now=2, numbers only) next to the current; "Sofort laden" publishes only the mode and no 0 A current. **Bench 2026-10-22** (`evcs.e_auto.set_evcs_mode` activated in the pack, archetype + carrier rebuilt with `ha_testbed_build`, `number.earnie_evcs_e_auto_set_evcs_mode`): charge 5 kW -> mode 2 and 21.7 A, PV follow -> mode 1, Sofort laden -> mode 2 and the current untouched (21.7 A stayed), no charging -> mode 0 and 0 A; ledger, `status.json` and the HA `number` agreed after each step. A real optimizer cycle then published mode 0 / 0 A, no `set_evcs_mode skipped` startup warning any more. Check 11/11 with the 30-entity archetype.
- [x] **`set_ess_mode` on the HA backend (L9) — decided and verified live:** decided 2026-10-22: the mode is published like the export limit (not owned by the YAML `ha_ess_force`); `HaWriteMixin._write_ess_setpoints` tests the activated key (flat or `ess.<id>.set_ess_mode`) instead of its empty value (`tests/test_ha_adapter.py::test_ess_mode_is_published_when_only_activated`). **Bench 2026-10-22:** force charge published mode 1 / `-2000 W`, automatic mode 0; the HA `number.earnie_ess_house_set_ess_mode` followed (1 -> 0). Does not release a forced active power on its own, see the open item L18.
- [x] **EHAL-Com Schreibtest sends the ticked rows (B2, F16, F17):** the UI reported `Schreiben OK (published)` for the inverter AC limit (`inv.<id>.set_inv_ac_power_limit`) and the flex `set_enable` although nothing reached the publish ledger: the inverter key went into the ESS/EVCS-only `HaAdapter.write_setpoints`, and `_write_flex_enable_probes` was a no-op on every network backend. Now inverter rows go through `write_mapped_fields` (as in the live cycle) and flex rows through the new `HaAdapter.write_published_fields` (an unmapped row raises instead of being dropped). Tests `tests/test_ehal_write_test_ha_dispatch.py` (red before). **Verified live (2026-10-22, bench):** inverter limit 1000 W + heat pump `set_enable` 1 sent from the browser reached `ehal_published.json`, `status.json` and the HA `number` entities. The expander collapse / reset of the `Senden` ticks could **not** be reproduced (no collapse over 24 s of fragment refreshes, a full rerun and a 15:30 cycle; the Schreibtest is not inside a fragment); it is hardened anyway: working in the expander sets `ehal_write_test_open` and later runs render it `expanded` (`tests/test_ehal_write_test_ui_state.py`).
- [x] **Live-Lesen value of pushed signals (F23):** SoC, energy counters, inverter and EV signals are not on the HA telemetry document, so their OK rows showed an empty `Wert (EHAL)`. `ui/loxone_debug.py::_ha_push_read_info` now carries the last pushed value from the inbox into `build_telemetry_rows`. Test `test_build_telemetry_rows_shows_the_pushed_value_of_signals_outside_the_telemetry`. The receipt time per signal (`Zuletzt gelesen`) was already correct; verified against the bench inbox (SoC `50 %`, energy `0.29472 kWh`, ...).
- [x] **`ess.<id>.sens_ess_power` required for grid-tied house batteries (F14) — verified live:** bench 2026-10-22: with the key removed and the inverter on `Insel`, switching **AC-Anschluss** to `Netzgekoppelt` in the Hauskonfigurator wrote `ess.house.sens_ess_power` into the battery bindings. Regression tests for both save paths (`upsert_battery`, `upsert_inverter`): `tests/test_house_config_required_signal_save.py`. A pack that lacks the key is routed through the migration page (`dm4.required_signal_activation`) before the Hauskonfigurator opens.
- [x] **Live cycle spun without an SoC (L12) — fixed and verified:** `main()` / `_main_cycle` return `False` when the cycle aborts before planning (no SoC / no prices); the daemon loop then waits `ABORTED_CYCLE_RETRY_SEC` (30 s, never shorter than the 10 s push interval; an `Earnie_Request_Optimize` wake ends it early) instead of restarting inside the lead window, and no longer logs `Durchlauf erfolgreich beendet`. On a network backend the missing SoC is the warning `Optimierung wartet auf den EHAL-SoC …` (Loxone keeps the error). Tests `tests/test_main_aborted_cycle.py`. **Verified live:** native `main.py` on the bench pack with an empty push inbox ran one cycle per 30 s over 100 s (before: about 45 per minute). The two reader ERROR lines per cycle (`EHAL SoC read failed`, `EHAL live power read failed`) remain, i.e. 2 per 30 s instead of ~47 per minute.
- [x] **UI reported `Auto-Start OK` although the daemon can die right after (B3, F2):** `main_daemon.start()` returned as soon as `main.lock` was held, but a startup crash (F2) comes after the lock. It now returns only once the daemon wrote a fresh heartbeat (main loop reached, `daemon_heartbeat.json` not older than the spawn), raises `DaemonError` with the stdio tail when the process exits meanwhile, and logs a warning (still returns the running status) when the lock is held but startup is slower than `wait_sec`. Tests `tests/test_main_daemon.py` (real stub subprocesses: crash after the lock, heartbeat wait, stale heartbeat of an earlier run). Not forced live: the bench's published port did not make the native `main.py` crash.
- [x] **Plausibility of pushed power (F21) — fixed and verified:** `integrations/power_plausibility.py`; HA push reads of `inv.<id>.sens_inv_power_pv`, `pv.<id>.sens_pv_production_active` and `ess.<id>.sens_ess_power` fail loud (`Implausible value for …`) beyond 3 × the configured hardware reference (inverter PV input / AC rating / kWp, battery power). Grid power has no configured reference and is not checked; Loxone / OpenEMS paths are not covered yet. Tests `tests/test_power_plausibility.py`; lab: a 900 kW PV push is rejected with the message **Verified live (2026-10-22, bench):** a 900 000 W push for `inv.wr_main.sens_inv_power_pv` (attached PV 10 kWp) made `HaAdapter._scoped_pv_live` raise `Implausible value for inv.wr_main.sens_inv_power_pv: 900000 W exceeds 3 x the inverter's PV input / AC rating / attached kWp (10 kW = 30000 W). Check the unit of the source entity (kW sent as W?)`. Notes: the bound is an upper bound only - `unit_flip` on a generated archetype makes the value 1000 x too small and is not caught; `read_scoped_pv_ha` (`integrations/pv_attribution.py`) reads without the bound and swallows errors, the bound applies on the telemetry path.
- [x] **HA carrier status sensor (F13) — fixed and verified:** `json_attributes_path: $` removed in `integrations/ha_carrier_yaml.py::_status_sensor` (tests `test_carrier_yaml_status_sensor_has_no_json_attributes_path`). Lab-verified on HA 2025.7.0 (setpoints from `status.json` reached the sim). **Existing users must regenerate and reload the package** — add to release notes and `docs/einrichtung/homeassistant-addon.md`; check on a real HA that setpoints arrive **Verified live (2026-10-22, bench):** every run (HA 2025.7.0 container, lab and full pack, 20+ setpoint round trips incl. `set_enable` and the EV current) delivered `status.json` setpoints to the `number` entities. Still a docs task, not a fix: release notes and `docs/einrichtung/homeassistant-addon.md` must tell existing users to regenerate and reload the package; HA OS / the add-on were not part of the bench.
- [x] **Carrier Jinja on non-numeric state (F7) — fixed and verified:** push conversion now yields `none` (→ "push skipped" log) for `unavailable`/`unknown` (`test_carrier_yaml_push_skips_non_numeric_state`). Verify with `earnie_house_sim.set_unavailable` in a real HA run **Verified live (2026-10-22, bench):** the `set_unavailable` check case is green in every run, the HA log shows `push skipped … unavailable/non-numeric`, and the push resumes after the fault.
- [x] **HA setpoints re-applied after restart / drift (F8, F18) — fixed and verified:** setpoint automations now also trigger on HA start and every push interval, write only when the target drifts by more than ~1 %, and ignore fields Earnie did not publish (`integrations/ha_carrier_yaml.py::_setpoint_automation`, tests `test_carrier_yaml_setpoints_*`). Lab: after an HA restart the sim charge limit followed the published 0 W. Package must be regenerated; consider write load on real hardware (Modbus) — the drift guard avoids rewrites **Verified live (2026-10-22, bench):** after `reject_writes` was switched off the setpoint was applied about 20 s later without a new publish (interval trigger + drift guard; check case `value applied after reject_writes is switched off`). The HA-restart case uses the same trigger (`homeassistant` start + `time_pattern`) but is not asserted separately.
- [x] **Flaky tests blocked pre-commit about every second full run — fixed and verified:** (1) `runtime_store/ehal_push_inbox.py`: a timer flush wrote its snapshot into whatever runtime dir was current when it fired, and a second `flush_inbox_now` returned before an in-flight timer write finished (`test_loxone_push_inbox` family, `KeyError`/stale value); the target dir is now fixed when the data is recorded and flushes are serialized (production race, also relevant to the daemon). (2) `tests/conftest.py`: per-test runtime dir + reset of inbox/ledger memory (tests without their own `EARNIE_RUNTIME_PATH` shared the default runtime dir across xdist workers; showed up as `test_ha_active_only_mapping_writes_nothing` after the ledger became disk-aware). Six consecutive full runs green locally (previously ≈50 % red). `test_usage_points::test_refresh_skips_when_stamp_unchanged` failed once earlier and did not reappear; keep an eye on it **Verified locally (2026-10-22):** at least five further full-suite runs were green (three pre-commit hooks and full runs with 4242 / 4249 / 4252 passed). The repo has no CI, so "verify on CI" cannot be done.
- [x] **Publish ledger shared between processes (F17) — fixed and verified:** `integrations/ehal_write.py` kept a per-process dict loaded once, so a value published by the UI (Schreibtest, other process) never reached the daemon's `status.json` (Loxone and HA; also the UI could overwrite the file with a stale view). The ledger now merges `ehal_published.json` on mtime change, newest `published_at` wins (tests in `tests/test_ehal_write.py`). Lab: a value published from a second process appears in `status.json` and reaches the sim. The Streamlit Schreibtest click-through is tracked in the pending F16 item **Verified live (2026-10-22, bench):** a value published from a second process (`ehal_write.write_field`) appeared in the daemon's `status.json` and reached HA, native and in the container (shared runtime dir).
- [x] **Entity-scoped setpoints in HA adapter (F3):** `setpoint_qualified_ids` accepts `ess.<id>.set_*` / `inv.<id>.set_*` (`integrations/ha_push_read.py`; tests `tests/test_ha_push_read_setpoints.py`). **Verified live (2026-10-22, bench):** ESS limits, grid export limit, EV current and `set_enable` are published and reach HA; no `Missing HA push setpoint binding`.
- [x] **HA credentials (F1):** decided 2026-10-21 - HA needs no URL / token in Earnie (push-only, Earnie never calls the HA API). `_resolve_ha_credentials` no longer raises, `hub_credentials_configured` is true as soon as `ehal.backend=ha`, the Smarthome-Backend HA form only asks for `adapter_id` and explains the YAML-package step; `EHAL_HA_*` in `.env` is ignored (legacy `ha_secrets_migrate` / `read_ha_credentials` stay for old packs; Supervisor resolvers are kept). Docs and `.env.example` updated. **Verified live (2026-10-22, bench):** Earnie in the bench container with a `.env` holding only `EARNIE_PILOT_PUSH_TOKEN` starts and serves the push loop (lab and full pack).
- [x] **Small HA testbed findings F12, F24:** (F24) the carrier skip log names the unavailable/non-numeric state. (F12, `[dev]`) the S4 integration loads the archetype in an executor job. **Verified live (2026-10-22, bench):** fresh HA start with the sim integration (58 `earnie_*` entities): 0 `blocking call` / `inside the event loop` lines in the HA log; the `push skipped` log reads `… is unavailable/non-numeric or has an unknown or incompatible unit_of_measurement`.
- [x] **HA write feedback (F22) — fixed, verify live:** setpoint automations use `continue_on_error`, re-check the target after 5 s and push `hub_write_failed` when it still differs (one WARNING instead of 4 nested ERRORs per attempt); Earnie shows a red notice in EHAL-Com Live-Schreiben and logs a warning at the next write (`runtime_store/ehal_push_inbox.py::hub_write_failure_age_s`, `integrations/ha_adapter_write.py`, `ui/loxone_debug.py`). New synthetic push id `hub_write_failed` (accepted by the inbox). Not done: no capability degrade / `ehal_write_error` entry (the schema enumerates setpoint fields; a contract change), no per-field detail. Packages must be regenerated. Lab: `reject_writes` → notice within seconds, expires after 3 intervals, value applied once writes work again **Verified live (2026-10-22, bench):** `hub_write_failed` reaches Earnie in every `reject_writes` run; Earnie logs `Home Assistant meldet nicht angewendete Sollwerte (hub_write_failed vor 6 s)` at the next write; EHAL-Com Live-Schreiben shows the notice, now as a warning (yellow) instead of a red error (`ui/loxone_debug.py::_render_hub_write_failure`, owner decision, tests in `tests/test_loxone_debug.py`). HA still logs one ERROR line per failed attempt (`Error executing script … reject_writes active`): even with `continue_on_error` HA logs an action error itself (`helpers/script.py::_handle_exception`), so the carrier cannot lower it; read "one WARNING instead of 4 nested ERRORs" as 1 HA ERROR + 1 carrier WARNING per attempt.
- [x] **Live-Schreiben rows for entity-scoped writes (F19):** (F19) `expand_ha_writes_for_live` maps bare `set_ess_*` records onto `ess.<id>.set_*`, and never-activated fields (`set_ess_mode`) are no longer recorded as successful writes (`HaAdapter.last_unconfigured_fields`, `build_ehal_write_records(unconfigured=…)`). **Verified live (2026-10-22, bench):** Live-Schreiben lists the qualified rows (`ess.house.set_ess_charge_power_limit`, `evcs.e_auto.set_evcs_max_current`, `heatpump.waermepumpe.set_enable`, `grid.meter.set_grid_export_power_limit`, …) with the last written values; `set_ess_mode` (not activated) is listed empty and not counted as a successful write.
- [x] **Silent daemon death at startup (F2):** `push_safe_setpoints_on_startup` logs the traceback to `earnie.log` and re-raises. **Verified (2026-10-22):** by `tests/test_ehal_live.py::test_push_safe_setpoints_on_startup_logs_and_reraises`; a live crash could not be provoked in the bench (a native `main.py` binds `0.0.0.0:8541` next to the Docker port without an error, so the port-conflict route of bench finding L2 does not reproduce).
- [x] **HA backend publishes the flex `set_enable` in the live cycle (B1, found and fixed 2026-10-22):** the network-backend branch of `main.py` wrote ESS limits, the EVCS current and the WR AC limits only; `ehal_live.write_flexible_consumer_states` ran in the Loxone branch only, so the optimizer's heat pump / pool / generic enables never reached `status.json`. Now `send_flexible_consumer_enables` (`integrations/loxone_writes.py`, `publish_kinds={"set_enable"}`) → `ehal_live.write_flex_enables_for_ha` runs in the HA branch (not for OpenEMS) and its rows go into `optimizer_run_state.ehal_writes`; the EV current is not published a second time. Tests `tests/test_flex_enable_publish_ha.py` (the main-cycle test is red without the fix). **Verified live (2026-10-22, bench):** the first real cycle after the rebuild (15:07:14) computed `Freigabe=1 (3.50 kW)` for the heat pump and published it: ledger `heatpump.waermepumpe.set_enable = 1.0`, `status.json` 1.0, `number.earnie_heatpump_waermepumpe_set_enable` 1.0; pool stayed 0.0, EV current unchanged. Not done: the EV mode (`set_evcs_mode`) is still not published on the HA backend.

### HA Testbed — carrier YAML ↔ HouseSim (2026-10-22)

- [x] **HA Testbed live run — first end-to-end run of the bench** `[dev]` (2026-10-22): runbook Part B run for real. Lab pack (`ha_lab/config`) and a full pack (`ha_lab/config_full`: ESS + inverter + EV + heat pump + pool, 28 entities) on a fresh `reset --all`, Earnie native and in the bench (`up --with-earnie`): `ha_testbed_check --require-all` 11/11 on the full pack, 10 PASS + 1 structural SKIP on the lab pack (no energy signal); `ha_container` wrapper green with `HA_TESTBED_TOKEN`. Findings L1–L13 in [`docs/dev/ha-contract-testbed.md`](../docs/dev/ha-contract-testbed.md) § 3f.
  - Fixed with regression tests: check crash on HTTP errors (L1), flat + qualified consumer key = one signal (`ehal/push_signals.py`, L4), grid export limit skipped for activation-only HA bindings (`ha_adapter_write.py`, L9), stopped-push cases on a fresh bench (L10, L11), check names an optimizer overwrite (L8).
  - Decision (§ 3g): setpoints are `number` (`set_value`) only for 2.7; `set_enable` verified live on `number` helpers, a real `switch` target is not applied. switch/select → own backlog item (Version 2.+1). Open follow-ups moved to [Backlog-Bugfixes.md](Backlog-Bugfixes.md): L12, L13, `set_ess_mode`.
- [x] **HA Testbed — carrier YAML ↔ HouseSim in a real HA container** `[dev]`: permanent, reproducible bench for the HA push contract without a production HA install: generate the carrier YAML and a matching simulated house from **any** Earnie configuration, load both into an HA container, verify the loop (HA → telemetry inbox, `status.json` → HA setpoints). Also reproduces customer problems from their activated signal set (not device quirks). Plan + runbook: [`docs/dev/ha-contract-testbed.md`](../docs/dev/ha-contract-testbed.md).
  - **Note:** reuses `house_sim/contract.py` (`build_contract`, `contract_entity_id`, `fill_yaml_placeholders`) and the S4 integration. Related but different: **HouseSim scenario import** builds *physics* from a scenario; this epic builds the sim from the *activated signal set*. Share the generator code where they meet, do not duplicate.
  - **Note:** the bench does not replace the by-hand `ENTITY_*` mapping step real users do — do it once per release.
  - [x] **HA Testbed P0 — baseline smoke with `evcc_en`** (no code): hand-filled carrier YAML + shipped archetype in the HA container (Container image, not the HAOS VM). Findings go into the plan doc § Findings. Decides: (a) carrier writes only `number.set_value` — switch/select setpoints (`set_enable`, `set_evcs_mode`, `set_ess_source_select`) are not applied; (b) legacy `sensor: - platform: rest` status sensor on current HA; (c) host reachability (`host.docker.internal:8541`, firewall)
  - [x] **HA Testbed P1 — archetype generator** (`house_sim/archetype_gen.py`, `scripts.house_sim_archetype_gen`): activated keys → archetype dir (`entities.json`, `ehal.ha.entities.json`, `house_params.json`, `pv_series.json`, `placeholders.json`, `meta.json`). Physics looks up flat field names (`set_ess_active_power`), Earnie uses qualified ids → emit flat keys for the physics subset, or resolve qualified ids in `house_sim/core/` (stays free of `ehal` imports; run `scripts.sync_house_sim_integration`). Non-physical signals get explicit static values (listed in `meta.json`); missing battery capacity etc. → fail loud. Tests: minimal + full pack, all signals covered, ids unique, `load_archetype` + `step_physics` run
    - Done: flat keys (no core change, WP2 skipped); only grid / PV (one inverter) / one house battery / first wallbox are physical, rest static as `number` entities listed in `meta.json`; pack must be canonical (PV per inverter, `ess.<id>.sens_ess_power` for grid-tied house batteries). Decisions: plan doc § 3b. Limits: one PV source, one house battery, setpoints numbers only
  - [x] **HA Testbed P2 — S4 external archetype dir + build/fill**: S4 lists archetypes from `/config/earnie_house_sim/archetypes/` next to the shipped ones; `scripts.ha_testbed_build` writes `packages/earnie_ha_carrier.yaml` (all `ENTITY_*` filled, fail if any survives), the archetype and the `configuration.yaml` packages snippet
    - Done: `list_archetypes` / `load_archetype_from_roots` in `house_sim/core` (synced), S4 flow + setup use `<config>/earnie_house_sim/archetypes/`, name clash with a shipped archetype aborts the flow; `scripts.ha_testbed_build` (needs a real `--token`, never touches `configuration.yaml`, writes `earnie_testbed_configuration.snippet.yaml`). Not run in a real HA yet (P3/P4)
  - [x] **HA Testbed P3 — compose + install script**: `docker/compose/ha-sim-testbed.yml` (pinned HA + optional Earnie, no evcc/HACS, ports 8123/8506/8541), `scripts/ha_testbed.py up|down|install|status|reset`; optional HA onboarding + config entry via REST so no UI clicks are needed
    - Done: `docker/compose/ha-sim-testbed.yml` (HA 2025.7.0 as in the lab; `earnie` only with `--with-earnie`; work dir `ha_lab/testbed/`, gitignored) and `scripts/ha_testbed.py up|down|install|status|reset` (config patch idempotent and refuses a conflicting `packages:`). **Not done:** the optional REST onboarding / config entry (HA account + integration are created once in the UI); containers not started in the suite (tests mock Docker; `compose config` validated)
  - [x] **HA Testbed P4 — automated check** (`scripts.ha_testbed_check`): entities + units, all activated reads fresh in the inbox, setpoint round-trip via `status.json`, negative cases (`reject_writes`, `set_unavailable`, stopped push → `0 angenommen (verstummt)`, energy never invented as 0). Optional pytest wrapper marked `ha_container` (skipped by default, not in the quality gate)
    - Done: `scripts/ha_testbed_check.py` (HA REST with a long-lived token; without `--ha-token` the HA checks are SKIP, `--require-all` makes SKIP fail) and `tests/test_ha_testbed_live.py` (`ha_container`, skipped unless `HA_TESTBED_TOKEN`). Unit-tested against a simulated bench only; **not yet run against a real HA + Earnie** — first live run may need timing tweaks (`--timeout-s`, `--repeat-s`)
  - [x] **HA Testbed P5 — docs + support playbook**: update `house-sim.md` (drop the stale "bind with 2.6.h UI / merge golden map" steps), `ha-lab-setup.md` header (still says REST pull), customer-reproduction checklist (config pack, HA version, unit + sign per bound entity, filled YAML without tokens)
    - Done: `house-sim.md` (testbed row, S4 install steps now push-contract, no golden-map/2.6.h binding), `ha-lab.yml` header (push, not REST), `ha-lab-setup.md` related link, plan doc § 4 Part B + customer playbook with question template. **Open before closing the epic:** first live run of `ha_testbed_check` against real HA + Earnie, then tick the epic; switch/select setpoints (finding 5) stay a product decision

### Version 2.7 — earnie-server client HTTPS (2026-10-21)

- [x] **earnie-server: switch the client to HTTPS** `[qual]`: `SERVER_BASE` is `https://cloudserver.earnie-hems.com` (no port) in `runtime_store/server_endpoints.py`; `PATH_PING` / `PATH_REVIEW` unchanged. `post_json` keeps default certificate verification, the 5 s timeout, logs certificate errors at ERROR, and does not fall back to HTTP. Tests: `tests/test_server_endpoints.py`, `tests/test_usage_ping.py`, `tests/test_feature_review.py`. Docs: `docs/einrichtung/betrieb.md`, `docs/workflow/usage-ping.md`, `docs/workflow/feature-review.md`.
  - **Note:** Behind Caddy every request arrives as `127.0.0.1`, so the receiver's per-IP rate limit (60/min) is global until `earnie-server` reads `X-Forwarded-For`.

### Bugfix — Dogfooding 2.7.0-alpha.7 SE modes + SE conf drift (2026-10-21)

- [x] **Dogfooding 2.7.0-alpha.7** (dump `debug-dumps/earnie_config_20261021_151607`) — **Verified** (2026-10-21)
  - Symptom A: After scenario configuration, Szenario-Explorer did not appear in the nav.
  - Cause A: Productive/alpha compose set `EARNIE_UI_MODES` to `sunset2sunset,live_environment` (comment already listed `scenario_explorer`).
  - Fix A: Align compose (and LoxBerry packaging) with `sunset2sunset,scenario_explorer,live_environment`.
  - Symptom B: Drift banner after migration for `scenario_explorer_conf.season_mirror_to_last_month` (and `export_price_series`).
  - Cause B: Migration did not fill additive SE conf keys from `config.example.json`.
  - Fix B: Detect-based step `dm4.se_conf_defaults` fills missing `scenario_explorer_conf` keys only; docs updated.

### Version 2.7 — earnie-server endpoints hard-coded (2026-10-21)

- [x] **earnie-server endpoints: hard-code in the code instead of `.env`** `[qual]`: production base `http://cloudserver.earnie-hems.com:8787` plus path constants `/ping` and `/review` in `runtime_store/server_endpoints.py`; clients compose via `resolve_endpoint`. Removed `EARNIE_USAGE_PING_URL` / `EARNIE_REVIEW_URL` from env reads and local `.env`. Injectable `endpoint_url` / `transport` kept for offline tests. Opt-out remains consent / `EARNIE_USAGE_PING=off`. Docs: `betrieb.md`, `private-env.md`, `docs/workflow/usage-ping.md`, `docs/workflow/feature-review.md`.

### LoxBerry plugin ZIP (2026-10-21)

- [x] **LoxBerry plugin ZIP — ship Versionsvariante UI strings** `[qual]`: rebuild and publish plugin ZIP `0.2.1` after the rename Versionskanal → Versionsvariante (`packaging/loxberry/templates/lang/language_{de,en}.ini`, docs). Bump `plugin.cfg` / `release.cfg` / `prerelease.cfg` `VERSION`, package per [`packaging/loxberry/README.md`](../packaging/loxberry/README.md) (7-Zip / `zip` with `/` separators), GitHub Release `loxberry-plugin-v0.2.1`. Existing installs only pick up the new labels via this Plugin-ZIP (not via Earnie image pull).

### Version 2.7 — Rename PV-Anlage to PV-Feld / PV-Felder (2026-10-21)

- [x] **Rename "PV-Anlage" and similar namings to "PV-Felder" in UI and docs** `[qual]`: singular **PV-Feld**, catalog/tab/multiselect **PV-Felder**. UI (Hauskonfigurator, PV form, scenario editor, Sankey, Earnie-Points), user-visible errors, schema descriptions, user docs, README, LICENSE. Unchanged: JSON keys (`pv_systems`, `pv_system_ids`), slug `pv_anlage`, Loxone meter titles, tariff-catalog legal wording, historical archive / `docs/dev/done`. Handbook heading keeps `<a id="pv-anlagen"></a>`.

### Bugfix — Delta 3 standby charge exceeds HK / live ESS limits (2026-10-21)

- [x] **Delta 3 standby charge exceeds HK / live ESS limits** (dump `debug_dump_20261015_222809`) — **Verified** (2026-10-21; overnight Chart1 / write acceptance)
  - Symptom: Chart1 SoC for Ecoflow Delta 3 jumped steeply around 03:00 (implied ~1.5 kW/QH) above the intended HK / Smarthome max-charge ceiling.
  - Cause: `collect_standby_packs` used raw HK charge power and skipped 2.7.j effective limits; live resolve could also loosen HK.
  - Fix: standby packs + writes use HK ∩ live; live never loosens HK; PS live gets are entity-scoped only.
  - Tests: `tests/test_ess_limits_2_7_j.py`, `tests/test_powerstation_2_7_h.py` (`test_collect_standby_packs_applies_hk_and_live_charge_cap`), `tests/test_standby_charge_cap_regression.py` (cheap-slot refill through plan, house load and Chart1 SoC stays within HK ∩ live; added 2026-10-22).
  - Golden case dropped (2026-10-22): the NAS prod recorder of 2026-10-22 (virtual_gs reserve drained and refilled) could not be replayed offline - `prepare_optimization_matrix` reads the live `ev.e_auto.get_evcs_limit_soc` marker and `start_state.charging_contexts` is recorded empty. Pytest regression only (owner decision).

### Bugfix — SE sunrise windows: day gaps / double booking and foresight merge lost flex energy (2026-10-20)

- [x] **SE sunrise book chain + foresight merge** — **Verified** (2026-10-20; greenfield 12-month SE, 3 scenarios)
  - Symptom: Optimized scenarios booked different consumption (11,892 / 12,316 / 12,216 kWh) although their window targets were identical; battery discharge exceeded charge (ratio 1.11–1.37, 300–480 SoC jumps > 20 %-pts).
  - Cause A: Book [SA₁, SA₂) derived from ready_by (SA₂ = first sunrise after ready_by). With sunrise after 07:00 the Saturday anchor (12:00) skipped Fri-SA→Sat-SA and Monday (07:00) re-booked Sun-SA→Mon-SA (25 weeks, ~2,400 duplicate / ~2,300 missing QH, −289 kWh targets).
  - Cause B: EV deadline consumers ignored the book slice and the MILP never blocked flex outside it, so 82–94 % of EV energy (with gap tolerance also pool / WP / appliance energy) was planned before SA₁. `_merge_foresight_flex_into_series` then replaced whole rows of the previous window and deleted its flex energy and battery actions.
  - Cause C: The SoC carry used the start SoC of the last book slot (its battery action dropped per window); the unbooked SA₀→SA₁ simulation could reach SA₁ away from the hold SoC.
  - Fix: SA₂ = sunrise on ready_by's date (contiguous sunrise chain; the run books start … end+1 so every QH of the period is covered once). Explicit `flex_indices` are a hard allow-list for every flex consumer incl. EV deadline (`contexts_within_book`, `block_flex_outside_book`). Foresight merge removed; fail loud on flex outside the book and on duplicate slots. SoC carried from the slot after the book and anchored at the SA₁ hold. Period clip keeps 23:15–23:45 of the end day.
  - Verified: greenfield year, 366 windows, 35,040 / 35,040 QH, 0 duplicates; booked flex per consumer = Σ window targets (Δ ≤ 0.05 kWh) in all three scenarios, except `pool_filter` (verification ran before the native filter booking fix 6109938c). Battery: no SoC jumps; discharge / charge 0.887–0.889 vs. η² = 0.884 (residual 2.5–12 kWh/yr from per-slot 0.1 % SoC rounding in the slot simulation, follow-up).
  - Tests: `tests/test_sunrise_book_steps.py`, `tests/test_se_book_allow_list.py`, `tests/test_monthly_fees.py::test_clip_results_keeps_every_quarter_hour_of_end_day`.
  - Regression: L2 goldens `REG-O-ev-deadline`, `REG-O-heat-swimspa`, `REG-O-summer-june` red as intended (extra book window covers the case day, SoC chain); re-record pending maintainer OK.

### Version 2.7 — earnie-server installed on easyname VPS (2026-10-20)

- [x] **Install earnie-server on a VPS** — done on an easyname virtual server (originally planned on a Hosttech VDC); verified from the PC with `POST /ping` → `204`.
  - Host: Debian 12 VPS at easyname; service runs under systemd as unprivileged user `earnie` (Python 3.11, stdlib only, no Docker), port 8787, data in `/srv/earnie-data` (`usage_daily.csv`, `reviews.jsonl`).
  - Domain: `cloudserver.earnie-hems.com` (DNS A-record on the `earnie-hems.com` subdomain) reaches the server; plain HTTP for now.
  - Data access: Samba share `[earnie]` on `/srv/earnie-data`; port 445 restricted by `ufw` to the maintainer's home IP, 8787 open.
  - Deploy process: tar the `earnie-server` repo (without `.git`), `scp` to the server, unpack to `/opt/earnie-server`, `systemctl restart earnie-server`.
  - Not done / follow-ups: "Savings KPI" as additional payload (own open item under Version 2.+1 in [Backlog.md](Backlog.md)). HTTPS via Caddy + client `SERVER_BASE` → done 2026-10-21 (see archive entry above). Hard-coded client endpoints → done 2026-10-21.

### Bugfix — SE consumption accounting: native pool filter never booked, Jahres Verbrauch from mixed sources (2026-10-20)

- [x] **SE native pool-filter run never booked** — fix implemented (2026-10-20); greenfield May: `pool_filter` 22.3 kWh (= 31 × 0.72) in every optimized scenario; full year: plausibility 365/365 OK (was 332/365, all failures exactly 0.72 kWh flex Δ), `pool_filter` 245.5–246.8 kWh booked (was 0) — the remaining ~17 kWh to 262.8 are the sunrise book gaps (`gap_slots` 2181–2401), fixed separately
  - Cause: `adjust_targets_for_native_filter` reduced the filter target by the expected native delivery and blocked the native slots, but in SE (`profile_spec` / `logged_day`) the native duty cycle was never booked as load.
  - Fix: `simulation/matrix_builder.native_filter_kw_by_slot` adds the `config_fallback` window × `nominal_power_kw` to `expected_p_act` (fixed load in the energy balance); `_consumption_kw_columns_from_chart_rows` moves it from `baseload_kw` to `pool_filter_kw`; plausibility counts it as filter flex. Sunrise MILP credits only native runs inside the book window (`credit_indices`).
- [x] **SE Jahres Verbrauch / invoices / plausibility hid booked differences** — fix implemented (2026-10-20)
  - Cause: Historisch = `cons_data` calendar sum, `ref:*` = parent's Σ window targets, optimized = baseload + full-horizon MILP flex → all optimized scenarios showed the same value while `backtesting.csv` booked different energy; battery standby mixed into consumption; invoice fallback summed kW without slot duration.
  - Fix: `simulation/booked_consumption.py` — one source per result series (unique slots, standby separate, duplicate / gap slots and slot diff to the reference); stored as `booked_consumption` in `backtesting_log.json`, used by Gesamtkosten (new column `Speicher-Standby [kWh]`, Hinweis for duplicates / gaps / slot differences), Verbrauchsvergleich (Soll / Geplant MILP / gebucht), invoices (`Verbrauch (Info)`, `Speicher-Standby (Info)`) and `consumption_totals.booked_kwh` / `booked_delta_kwh`.
  - References (Historisch, `ref:*`) now evaluate the optimized run's slots (`reference_slot_datetimes`: sunrise book step [SA₁, SA₂) resp. fixed 24 h).
  - Tests: `tests/test_se_consumption_accounting.py`, `tests/test_backtesting_results_helpers.py`, `tests/test_monthly_fees.py`.
  - Open: booked losses from foresight merge / sunrise window gaps (Verbrauchsanalyse U1/U3) are now visible but fixed separately (branch `fix/se-sunrise-book-chain`).

### Bugfix — SE detailed calendar disabled Okt–Dez on rolling 12-month window (2026-10-19)

- [x] **SE detailed calendar disabled Okt–Dez on rolling 12-month window** — **Verified** (2026-10-19; greenfield 12-month SE)
  - Symptom: After a 12-month SE, Okt/Nov/Dez (and the selected month) looked disabled in Detaillierte Simulationsansicht.
  - Cause: Calendar built Jan–Dez only for `backtesting_year` (end year); rolling window `2025-10`–`2026-09` left Okt–Dez 2026 empty while run data lived in 2025. Selected month is intentionally non-clickable.
  - Fix: Resolve each calendar month to the year overlapping the SE period; header shows year span.
  - Tests: `tests/test_backtesting_deviation_calendar.py` (`test_build_index_rolling_window_maps_oct_dec_to_prior_year`).

### Bugfix — Powerstation planning ignored live SOC limits (2026-10-19)

- [x] **Powerstation planning ignored live SOC limits** (dump `debug_dump_20261019_124658`) — **Verified** (2026-10-19; Shadow Chart1, live `max_soc` 95%)
  - Symptom: Chart1 Ecoflow SoC planned up to 100% while live `get_ess_soc_max` was 95%.
  - Cause: `read_telemetry` only carried plant-flat gets for the primary house ESS; standby packs require entity-scoped `ess.{id}.get_ess_*`. Chart path also called `load_standby_packs()` without telemetry.
  - Fix: `enrich_telemetry_with_ess_live_limits` + use in `main.py` and Chart1 `_resolve_standby_chart_plans`.
  - Tests: `tests/test_ehal_live_ess_limits_enrich.py`, `tests/test_powerstation_2_7_h.py` (`test_collect_standby_packs_applies_hk_and_live_soc_cap`).

### Bugfix — Virtual reserve target_kwh wiped on advance/trigger (2026-10-19)

- [x] **Virtual reserve: `advance_reserve_after_slot` / `set_trigger` wiped `target_kwh` to 0** — **Verified** (2026-10-19; NAS productive)
  - Symptom (Nas productive, Geschirrspüler / `virtual_gs`): dishwasher running, MILP ZWANGSLADEN toward ~11.8% (≈1 kWh refill), but `powerstation_reserves.json` stayed `empty` / `stored_kwh=0` / `target_kwh=0`.
  - Cause: `get_or_init_state(..., target_kwh=0.0)` always overwrote the configured target on every slot advance / trigger latch, so charge credit was capped at `min(0, …)`.
  - Fix: `update_target=False` for advance + trigger; collect/learn still refresh the target.
  - Tests: `tests/test_powerstation_2_7_p.py` (`test_advance_and_trigger_preserve_target_kwh`).

### Bugfix — Cockpit pages disabled after EHAL PV retirement + migration (2026-10-19)

- [x] **Cockpit pages disabled after EHAL PV retirement + migration** — **Verified** (2026-10-19; NAS productive; `v2.7.0-alpha.4`)
  - Symptom: After `dm4.retire_plant_pv_binding` / inv-PV required signals, Live-Cockpit (Monitor / Manuelle Geräte) disappeared on NAS productive.
  - Cause: (1) `_REQUIRED_PLANT_LIVE_FIELDS` still required retired plant `sens_pv_production_active`; (2) Binding-P5 consumers with only `ehal_bindings` kept `needs_planning_onboarding` true, so the markers gate applied.
  - Fix: drop plant PV from Cockpit gate; require `inv.*.sens_inv_power_pv` activation; treat `ehal_bindings` consumers as live wiring.
  - Tests: `tests/test_setup_readiness.py` (`test_needs_planning_onboarding_false_for_ehal_bindings_consumers`, `test_betrieb_unlocked_with_ehal_consumers_without_plant_pv`).

### Bugfix — Inverter PV mandatory; bare plant PV removed from telemetry (2026-10-19)

- [x] **Inverter PV mandatory; bare plant PV removed from telemetry** — **Verified** (2026-10-19)
  - Symptom: EHAL push Lesefehler for `pv.dach_sued|nord.sens_pv_production_active` when only inverter-sum PV exists.
  - Fix: require `inv.{id}.sens_inv_power_pv` when inverter has attached PV; per-string `pv.*` optional (empty keys stripped); bare plant `sens_pv_production_active` removed from telemetry document (plant AC derived via attribution); migration `dm4.retire_plant_pv_binding`.
  - Tests: `tests/test_required_signals.py`, `tests/test_retire_plant_pv_binding.py`, `tests/test_pv_attribution.py`, topology P2 / adapter characterization updates.

### Bugfix — config pack import accepts incompatible member files (2026-10-19)

- [x] **Bug — config pack import accepts incompatible member files** — **Verified** (2026-10-19; greenfield `EARNIE_ENV_PATH`)
  - Cause: `_migrate_and_validate_pack_docs` stamped members to current before `ensure_compatible` (would whitewash v1/v2/untagged if validate were bypassed).
  - Fix: ensure then stamp; `grid_fees.json` still exempt; doc `speichern-laden.md` states members are checked too.
  - Live: v4 manifest + v2/`untagged` `config.json` → `DataModelError`, greenfield files unchanged; compatible re-import OK, `grid_fees.json` unstamped.
  - Tests: `tests/test_config_pack_and_paths.py` (`test_config_pack_rejects_v2_member_with_v4_manifest`, `test_migrate_and_validate_ensures_before_stamp`).

### Bugfix — SE 5-star review dialog + earnie-server `POST /review` (2026-10-19)

- [x] **SE 5-star review dialog + earnie-server `POST /review`** — **Verified** (2026-10-19)
  - Replaced cloud-demo GitHub feedback banner with reusable `@st.dialog` (`ui/star_review_dialog.py`) for all SE installs.
  - Trigger: leave Szenario-Explorer after a run was started; once per `review_id` (`runtime/feature_reviews.json`); send or abort.
  - Always POST anonymous payload to `EARNIE_REVIEW_URL`; earnie-server appends `reviews.jsonl`.
  - Tests: `tests/test_feature_review.py`, earnie-server `tests/test_usage_ping_receiver.py` (review route).

### Bugfix — Loxone VI/VO export: Pilot→Earnie + open push token (2026-10-19)

- [x] **Loxone VI/VO export: Pilot→Earnie + open push token** — **Verified** (2026-10-19)
  - Remove `(2.7.q Q4)` from exported VI Comments / library VI_v2 HTML comments.
  - Export filenames: `VO_Earnie_*` / `VI_Earnie_*`, `Earnie-*-Signalliste.csv` (was Pilot).
  - Placeholder `PUSH_TOKEN_HIER_ERSETZEN`; ZIP README step 3 updated.
  - Unset `EARNIE_PUSH_TOKEN` → open LAN telemetry (no 404); empty VO token omits `?t=` / `/t/`.
  - Tests: `test_ehal_signal_list`, `test_pilot_vi_template_gen`, `test_pilot_vo_template_gen`, `test_loxone_push_inbox`.

### Minor — sidebar order EHAL-Com before Optimierer-Dienst (2026-10-18)

- [x] **Swap EHAL-Com and Optimierer-Dienst in sidebar** `[feat]` — Daemon Control order is now Smarthome-Backend → EHAL-Com → Optimierer-Dienst (`ui/navigation.py`). Docs `betriebsmodi.md` / `betrieb.md` aligned; test `test_navigation_setup.py`.

### Bugfix — Signalliste heartbeat rename + Pflicht (2026-10-18)

- [x] **Signalliste heartbeat rename + Pflicht** — **Verified** (2026-10-18)
  - Wire IDs: read `heartbeat_smarthome`, write `heartbeat_earnie` (was `heartbeat` / `heartbeat_ts`); no dual-accept of old IDs.
  - Both rows **Pflicht** with clear Bedeutung; still not in the optional-signals expander.
  - VO Title stays `Push_Earnie_Heartbeat`; Cmd URL / VI Check / `status.json` use the new IDs.
  - Tests: `test_ehal_signal_list`, `test_qualified_ids`, `test_pilot_*`, `test_loxone_status_json`, `test_loxone_push_inbox`, `test_ha_carrier_yaml_gen`.

### Bugfix — Signalliste Earnie-Host label + LAN IP prefill (2026-10-18)

- [x] **Earnie-Host (LAN-IP für den Hub)** — **Verified** (2026-10-18)
  - Label → `IP-Adresse des Geräts, auf dem Earnie läuft`.
  - Prefill: `EARNIE_LAN_IP` / `EARNIE_HOST` → Supervisor host LAN IP → local IPv4 (Docker bridge skipped).
  - Tests: `tests/test_ehal_signal_list.py` (`test_default_host_*`).

### Bugfix — Example paths NAS-specific UNC placeholders (2026-10-18)

- [x] **Example paths: NAS-specific UNC placeholders** — **Verified** (2026-10-18)
  - `.env.example`: `\\YOUR-NAS\docker\earnie…` → relative `earnie_env` / `earnie_env/config` / `earnie_env/runtime`.
  - `remote_backtesting.example.json`: aligned with script/tests (`\\NAS\EnergyOptimizer\backtesting-sync`).
  - `_diag_swimspa_nas.py`: example UNC → `\\NAS\earnie_env\runtime`.

### Bugfix — Consumer EHAL storage flex.* → typed namespaces (2026-10-18)

- [x] **Consumer EHAL storage still uses legacy `flex.{id}.*` keys** — **Verified** (2026-10-18)
  - Symptom: Loxone import / EFM create and Kennung rename wrote `ehal_bindings` as `flex.<slug>.*` while exchange / Signalliste emit `consumer.` / `heatpump.` / `pool.*`.
  - Fix: writers persist typed namespaces; migration step `dm4.consumer_flex_bindings` rekeys existing `flex.*` (Merker conflicts → Blocker); dual-read of legacy `flex.*` kept until packs migrate.
  - Tests: `test_flex_fields`, `test_migrate_consumer_flex_bindings`, greenfield/EFM/entity_id_lock updates.

### Bugfix — Loxone import consumer Bezeichnung / id / type sync (2026-10-18)

- [x] **house_profiles consumers after Loxone import: Bezeichnung / id / type mess** — **Verified** (2026-10-18)
  - Symptom: after import + editing consumers, `id` / Bezeichnung / types drifted (and imports treated as permanently locked so Bezeichnung never renamed Kennung).
  - Cause: Loxone/EFM-created consumers omitted `id_locked` / `id_provisional_label` (missing flag ⇒ legacy locked); EFM-only Wärmepumpe stayed `generic`; `_resolve_consumer_ids` used already-merged session rows as `existing`.
  - Fix: import stubs set `id_locked: false` + provisional label; EFM Wärmepumpe/WP → `thermal_annual`; resolve uses pre-merge session as `existing` so first Bezeichnung change renames id + rewrites bindings.
  - Tests: `tests/test_loxone_greenfield_import.py`, `tests/test_loxone_efm_meters.py` (`test_efm_only_waermepumpe_create_is_thermal_and_unlocked`), existing `tests/test_entity_id_lock.py`.
  - Follow-up: stored bindings `flex.*` → typed namespaces — verified (see section above).

### Bugfix — Greenfield Live / SK missing after reload (2026-10-18)

- [x] **Greenfield: Live scenario / SK missing after reload** — **Verified** (2026-10-18)
  - Symptom: after configuring Live and a first SE, reload hid SK and Live entity refs looked empty.
  - Cause: incomplete HK drafts (esp. Batterie without inverter) never auto-persisted; `st.rerun()` after a successful write hid “Gespeichert”, so users left tabs believing defaults were saved. Empty `components.batteries` kept SK locked and Live refs empty.
  - Fix: `auto_persist` keeps a one-rerun “Gespeichert” flash; Batterien warns when not ready (draft would be lost on tab leave).
  - Tests: `tests/test_auto_persist_shadow.py` (`test_auto_persist_flash_survives_simulated_rerun`).

### Bugfix — Haus Wärme type after Loxone consumer import (2026-10-18)

- [x] **Haus Wärme type after Loxone consumer import** ([GitHub #42](https://github.com/JochenTCC/Earnie/issues/42)) — **Verified** (2026-10-18; reporter confirmation and issue closed 2026-10-22)
  - Symptom: after Consumer-Import, imported heatpump could not be set to `thermal_annual` (Haus Wärme) when not at list index 0 (same as #42: WP as Verbraucher 7 only offered Allgemein / Temperatur RC / E-Auto).
  - Cause: UI `_consumer_type_options` and store validation required Haus Wärme only on Verbraucher 1; import appends consumers so heatpump often lands at index ≥ 1.
  - Fix: offer `thermal_annual` whenever no *other* consumer already has that type; drop index-0-only store check (keep singleton).
  - Tests: `tests/test_planning_editors.py` (`test_consumer_type_options_thermal_uniqueness`, `test_profile_accepts_thermal_on_second_consumer`, `test_profile_rejects_two_thermal_annual_consumers`).
  - Note: reporter on Earnie 2.6.2; fix shipped from `2.7.0-alpha`. Reporter confirmed Haus Wärme is selectable on a non–Verbraucher-1 slot (e.g. Verbraucher 7). GitHub #42 closed 2026-10-22.

### Bugfix — Hausprofil Verbraucher Entfernen (2026-10-18)

- [x] **Deleting consumer is flaky (wrong / deleted consumer edited after Entfernen)** — **Verified** (2026-10-18)
  - Symptom: after Entfernen, editing a remaining Verbraucher changed the deleted one’s Bezeichnung; labels shifted across surviving IDs via auto_persist.
  - Cause: index-keyed `hc_*` Streamlit widgets reused after list shift; clearing session keys was not enough — later reruns restored stale frontend values onto the same key names.
  - Fix: bump `house_consumer_widget_gen` on Entfernen; `_scoped_key` embeds gen as `hc_g{N}_…` so widgets remount cleanly.
  - Tests: `tests/test_planning_editors.py` (`test_consumer_widget_gen_bump_changes_scoped_hc_keys`).

### Bugfix — Greenfield Loxone Dogfood (2026-10-18)

- [x] **Greenfield: unclear Anlagen-PV-Abdeckung checkbox** — **Verified** (2026-10-18)
  - Cause: `plant.pv_covers_all_inverters` was only an acknowledgement that a flat plant PV total covered every grid-tied inverter; wording was easy to misread as load coverage.
  - Fix: remove the Hauskonfigurator checkbox and the config flag; with several grid-tied inverters that own PV, always derive plant PV as Σ inv/pv · η_inv (flat plant EHAL value ignored); incomplete maps fail loud.
  - Tests: `tests/test_topology_p2.py` (`test_multi_inv_ignores_mapped_plant_and_derives_sum`), `tests/test_pv_attribution.py` (`test_with_attributed_multi_inv_derives_even_when_plant_mapped`).
- [x] **Greenfield: Netznutzung Messart / Viertelstunden-Zähler UI** — **Verified** (2026-10-18)
  - Cause: `netznutzung.quarter_hour_meter` and `power_metering` were user toggles; not Earnie's concern.
  - Fix: remove Hauskonfigurator Leistungsmessung select + QH-meter checkbox + migration QH question; always `quarter_hour_meter: true` and `power_metering: unmetered_power` on normalize; catalog still stores both base prices / `requires` for documentation.
  - Tests: `tests/test_grid_fees.py` (`test_snap_applies_even_when_quarter_hour_meter_flag_false_in_raw`, `test_metered_power_raw_is_forced_to_unmetered_base`).
- [x] **Szenarienkonfigurator: pre-select live Hausprofil / PV / Batterien when unconfigured** — **Verified** (2026-10-18)
  - Symptom (Greenfield Loxone Dogfood): first open of Szenarienkonfigurator left Hausprofil / Batterien / PV empty (`— keine —` / `[]`) even when catalogs had entities.
  - Cause: `_seed_scenario_widget_state` only mirrored disk; empty live refs stayed empty.
  - Fix: when live scenario has all three entity refs empty, seed first Hausprofil + all selectable batteries + all PVs; auto_persist writes on ready. Partial / non-live unchanged.
  - Tests: `tests/test_planning_editors.py` (`test_default_live_entity_refs_*`).

### Bugfix — Greenfield / HA first start Migration UI (2026-10-18)

- [x] **Greenfield / HA first start opens Migration UI** — **Verified** (2026-10-18)
  - Cause: `house_profiles.minimal.json` stamped dm4 but lacked `plant.grid_meter`, so `dm4.topology` stayed pending and Streamlit entered migration mode.
  - Fix: seed `plant.grid_meter` (`DEFAULT_GRID_METER`) in `share/config/house_profiles.minimal.json`.
  - Tests: `tests/test_migration_startup_gate.py` (`test_greenfield_bootstrap_gate_stays_open`).

### Bugfix — Smarthome-Backend Anbindung / discovery IP (2026-10-18)

- [x] **SB: Anbindung chapter stayed open after Loxone connect** — **Verified** (2026-10-18)
  - Cause: configured summary always rendered top-level **Anbindung** once `is_sb_configured()`; first-run `sb_chosen_backend` also stuck and reopened credentials under Backend ändern.
  - Fix: credentials under collapsed **Zugangsdaten** (auto-expand on Loxone auth recovery); clear `sb_chosen_backend` on save; docs/UI copy updated.
  - Tests: `tests/apptest/test_page_smarthome_backend_apptest.py` (no Anbindung subheader when configured).
- [x] **SB: discovered Miniserver IP not copied into Zugangsdaten** — **Verified** (2026-10-18)
  - Cause: `_select_hit` stored only backend kind, not host/port.
  - Fix: persist discovered host into session + credential form IP widgets (`sb_loxone_form` / `sb_anbindung_loxone_form`).
  - Tests: `test_selecting_discovered_loxone_prefills_miniserver_ip`.

### Binding P5 — signal contract for all backends, HA push-only (2026-10-18)

- [x] **Binding P5 — signal contract for all backends, HA push-only** `[feat]` (epic **Binding**; target [`docs/dev/EHAL-Binding-UX-Draft.md`](../docs/dev/EHAL-Binding-UX-Draft.md) **§0.6**; live transport **2.7.r** was already done)
  - [x] **Binding P5a — required-signal activation:** `ehal/required_signals.py`, `house_config/required_signal_activation.py`; Hauskonfigurator save/delete; migration `dm4.required_signal_activation`
  - [x] **Binding P5b — Signal list for all backends:** catalog + Pflicht/aktiviert + optional toggle; HA render; `signals_for_export(mode="all")`; Lx2 soft never-received warnings
  - [x] **Binding P5c — HA YAML package:** periodic `time_pattern`, Jinja units, setpoints, `ha_ess_force` automations, EHAL-Com download
  - [x] **Binding P5d — HouseSim contract / push harness:** `house_sim/contract.py`, `push_harness.py`; pull adapter-loop tests skipped pending P5e (then removed)
  - [x] **Binding P5e — remove pull (atomic):** migration `dm4.ha_pull_removal`; mapping UI / pull paths gone; leftover transport fails loud
  - [x] **Binding P5f — docs, cadence, add-on:** ehal.md, ehal-com.md, ha-lab-setup.md, homeassistant-addon.md, loxone-signals.md, ha-evcc.md (push-only)

### Binding — Loxone follow-ups for the shared contract (2026-10-18)

- [x] **Binding — Loxone follow-ups for the shared contract** `[qual]` (epic **Binding**)
  - [x] **Binding Lx1 — one activation path:** greenfield / EFM use `activate_required_in_house`
  - [x] **Binding Lx2 — soft "never received":** Live-Lesen / startup verify = warning + export hint
  - [x] **Binding Lx3 — backend-neutral names:** `ehal_request_http` / `ehal_push_inbox` / `system.ehal_http_port` / `EARNIE_PUSH_*` with aliases; migration `dm4.ehal_http_port`; URL path aliases kept
  - [x] **Binding Lx4 — Merker naming leftovers:** `MerkerBinding` → `BindingSource`; watchdog / write-test wording

### Bugfix — usage_ping opt-in `v: 1` vs v2 + points on consent (2026-10-17)

- [x] **usage_ping: opt-in preview `v: 1` (clarified) + points refresh on consent** — **Verified** (2026-10-17)
  - Clarified: wire schema `v` is 2 only when `stage == live` **and** `points` are in state; explorer / pre-points preview correctly shows v1.
  - Fix: `set_consent("on")` calls `refresh_points()` so Earnie-Points are stored from live plant config without an optimiser cycle; payload becomes v2 once stage is live.
  - Tests: `test_set_consent_on_refreshes_points_without_live_cycle`, `test_set_consent_on_with_live_stage_yields_payload_v2`; live UI showed v2 with `points: 10`.

### 2.7 quality / release hardening (2026-10-17)

- [x] **2.7 quality / release hardening** `[qual]`: full gate before first community alpha (skill `quality-gate`; no `version.py` bump; letter `2.7.r` already used for Binding HA transport)
  - [x] Coverage baseline — **3905** passed / **14** skipped (final suite); overall **83.0%** (`data` 74.5, `ehal` 90.6, `house_config` 85.3, `optimizer` 85.2, `runtime_store` 83.7, `settings` 79.1, `simulation` 87.1); no package &lt; 40% (vs 2.6.r re-check 80.7% / 2728 passed). First `run --coverage` had 2 xdist-flaky local-HTTP failures (`test_endpoint_token_validation_and_storage`, `test_http_get_status_json`); both green sequential and on final suite.
  - [x] Dead-code / obsolete-test audit — vulture `--min-confidence 80`: **0** hits; `--dead-fixtures`: all fixtures used; health-report flags are expected mock-heavy / always-skipped (no removals).
  - [x] Simplify redundant / complex / unneeded — no behavior-changing removals this pass (no `_backup` / `_tmp` leftovers; comment-block scan clean); triage deferred.
  - [x] KPI refactor — all core/UI files ≤ 600 code LOC (mega-file sibling splits + facades/re-exports; `optimizer/milp.py` → `milp_defaults.py`); functions > 60 LOC cleared except exempt MILP constraint blocks `_create_grid_battery_vars` / `_add_slot_power_balance_and_soc` in `milp_horizon.py`.
  - [x] Official docs review (thin) — prior [`docs/dev/doc-review-checklist.md`](../docs/dev/doc-review-checklist.md) P1/P2 Check+Style complete; `## Document Review Findings` empty; no docs-editor rewalk (KPI splits did not change user-facing behavior).
  - [x] Fix last failed sonarcloud Action — [run 39016600274](https://github.com/JochenTCC/Earnie/actions/runs/39016600274): `test_thermal_hourly_overlay_maps_slots` Open-Meteo `ReadTimeout`; offline mock via `install_open_meteo_climate_mock` in `tests/test_price_pipeline_p3.py`.

### Semi-automatic docs / manuals review (2026-10-17)

- [x] **Semi-automatic review of docs / manuals** `[qual]` — remove obsolete ones

### Document Review abbreviations.md language (2026-10-17)

- [x] **`abbreviations.md` language:** decided — the glossary stays fully English (already is); no translation. German TOC link texts "Abkürzungen" in German docs are unchanged.

### Document Review abbreviations.md EHAL-Com row (2026-10-17)

- [x] **`abbreviations.md` EHAL-Com row:** removed the outdated "backend choice" (moved to Smarthome-Backend); row now reads "live read/write, mapping".

### Document Review entwicklung/README.md Shadow status (2026-10-17)

- [x] **`entwicklung/README.md` Shadow status verified:** the line (S1 recorder + S2+S3 client done in 2.7.f, S4 in 2.+1) matches the backlog — 2.7.f is archived as done, "Shadow Mode S4" is open under `### Version 2.+1` in `Backlog.md`. No doc change needed.

### Document Review greenfield-dev-stack.md checklist (2026-10-17)

- [x] **`greenfield-dev-stack.md`** backlog IDs already scrubbed; Live-Pfad checklist renumbered 1–6 (duplicate “3.” fixed) and the stale “detaillierter Paritätstest folgt” note removed (price parity is covered by `tests/test_price_pipeline_p3.py`).

### Document Review proxmox bootstrap.sh paths (2026-10-17)

- [x] **`proxmox` bootstrap.sh** now creates `earnie_env/config` and `earnie_env/runtime` under the Earnie dir, matching the compose volumes; closing hint paths updated.

### Document Review tarife-quellen.md audit date (2026-10-17)

- [x] **`tarife-quellen.md` § 7 audit refreshed:** all audited values (monthly fees, energy markups, VKW formulas) re-checked against `share/config/tariffs.json` (`catalog_as_of` 2026-09-28) and match; heading now states audit date 2026-10-17 and catalog stand. Provider pages were not re-fetched.

### Document Review verbrauchs-csv.md Cursor plan link (2026-10-17)

- [x] **Cursor plan reference removed:** `docs/konfiguration/verbrauchs-csv.md` no longer points to the repo plan `energieflussmonitor_hausprofil_blueprint_a`; the EFM-Auto-Sync spec link remains.

### Document Review waermespeicher-schichtung-teq.md external concept link (2026-10-17)

- [x] **Internal ID / external link removed:** the "Thermals P3" ID was already gone from `docs/konfiguration/waermespeicher-schichtung-teq.md`; the remaining "Konzept: Entwicklungsplan §3.5 im `Earnie-Projekt`-Repo" sentence (unreachable external reference) was dropped.

### Document Review lab docs in TOC / link lists (2026-10-17)

- [x] **Lab docs removed from TOC-style lists:** `docs/README.md` TOC never listed the lab docs (`private-env.md` entry removed); `OpenEMS-Lab` entries removed from the link lists in `docs/einrichtung/smarthome-backend-wahl.md` ("Weiterlesen") and `docs/ui/ehal-com.md` ("See Also"). Inline cross-links to `greenfield-dev-stack.md` / `openems-lab.md` and moving the lab files to `docs/entwicklung/` / `docs/dev/` were not part of this pass.

### Document Review smarthome-backend.md Loxone-Import section (2026-10-17)

- [x] **`docs/ui/smarthome-backend.md` „Loxone-Import“:** heading and button label match the UI (`ui/ehal_greenfield_import.py`); history wording („war früher im Hauskonfigurator … jetzt“) removed so the section states current behaviour only.

### Document Review docs/README.md Scope-A wording (2026-10-17)

- [x] **`docs/README.md` „Scope-A-Plugin“:** internal term removed from the LoxBerry-Plugin TOC line (now "Plugin (Docker-Wrapper) und manuelle Compose-Installation im Vergleich"); no other "Scope-A" occurrences under `docs/`.

### Document Review charts.md developer tests (2026-10-17)

- [x] **`charts.md` developer test paragraphs moved** (Deviation-Test, Flow-Balance-Test) to `docs/dev/charts-dev-tests.md` (English). No changelog wording found in `charts.md`.

### Document Review betriebsmodi.md planned features / internal names (2026-10-17)

- [x] **`betriebsmodi.md` scrubbed:** removed the "planned" statements (calendar-day recalc developer function, new Parameter-Anpassung approach) and the internal function names `build_annual_cost_rows` / `_jahres_kwh_for_row` from the Jahres-Verbrauch heading. The kWh source table (internal keys like `reference_kwh_for_period`, `plausibility[...]`) is left as is.

### Document Review loxberry-plugin.md Go/No-Go table sync (2026-10-17)

- [x] **`loxberry-plugin.md` Go/No-Go table** synced with `container.md`: added the MILP-performance row, aligned the reference sentence, kept the plugin-specific Docker row.

### Document Review loxberry-plugin.md parallel operation (2026-10-17)

- [x] **`loxberry-plugin.md` parallelbetrieb:** Internal section "Parallelbetrieb mit manueller Compose" (container-name clash with `earnie-productive`, host-port workaround) and the link sentence in the port chapter removed from the user doc.

### Document Review docs/README.md TOC developer pages (2026-10-17)

- [x] **`docs/README.md` TOC:** Greenfield Dev-Stack, OpenEMS-Lab and HA ↔ Loxone Bridge-Generator moved from the user Einrichtung list to `docs/entwicklung/README.md` (Entwickler-Betrieb). The pages themselves stay under `docs/einrichtung/`; only the TOC entries moved.

### Document Review betrieb.md developer sections (2026-10-17)

- [x] **`betrieb.md` Cycle-Recorder / Prod-Dump:** developer content moved to `docs/dev/cycle-recorder-and-prod-dump.md` (English). `betrieb.md` keeps only a short Cycle-Recorder note (default on, load profiles stay local, how to disable, retention) because the debug-dump privacy hint links to it; the Prod-Dump fixture section was removed.

### Document Review handbook Silent/Loud status (2026-10-17)

- [x] **Handbuch Silent/Loud:** the EHAL-Com sentence no longer claims a Silent / Loud status; it now says that **Live-Schreiben** shows the last run's result (including a silent run). The switch stays on **Optimierer-Dienst**.

### Document Review handbook first-start nav (2026-10-17)

- [x] **Handbuch first-start nav:** sentence now states that the app opens on **Smarthome-Backend** and that **Optimierer-Dienst** / **EHAL-Com** unlock after connecting (matches `page_smarthome_backend.py`).

### Document Review handbook internal path (2026-10-17)

- [x] **Handbuch → `Entwicklungsplan/Hardware-Registry-Ausstellung.md`:** internal Earnie-Projekt path replaced by a link to `docs/workflow/hardware-registry-layer-c.md` ("Technische Details zum Prüfverfahren").

### Document Review doc aligned to code (2026-10-17)

- [x] **`betrieb.md` `EARNIE_UI_MODES`:** `sunset2sunset` now lists Monitor / Manuelle Geräte, `live_environment` lists Smarthome-Backend, Optimierer-Dienst, EHAL-Com, Analyse (as in `betriebsmodi.md` and `ui/mode_selector.py`).
- [x] **`container.md` tariff validation command:** no change needed. The command intentionally validates the bundled catalog `share/config/tariffs.json` before `--push`; the productive `earnie_env/config/tariffs.json` is documented separately.
- [x] **`loxone-anbindung.md` Vorzeichen table:** Merker titles replaced by qualified wire IDs (`grid.meter.sens_grid_power_active`, `ess.{id}.sens_ess_power`); old names marked as optional name catalog.
- [x] **`preise.md` „Fehlende Zukunftspreise“:** refers to the whole source cascade (ENTSO-E, Energy-Charts, cache, aWATTar) instead of aWATTar alone.
- [x] **`preise.md` heading:** renamed to „Preise und Marktdaten“; links in `docs/`, handbook and `ui/doc_links.py` updated.
- [x] **`loxone-signals.md` Flex enable:** note added that `flex.{slug}.set_enable` is the binding key, while the wire check uses `consumer.` / `heatpump.` / `pool.{slug}.set_enable`.

### Document Review envelope schema version (2026-10-17)

- [x] **`envelope.schema.json` `schema_version` const 1 vs wire version 4:** schema set to `const: 4` (title and descriptions updated), matching `ehal.md` and `telemetry.schema.json`. `tests/test_ehal.py` passes.

### Document Review ehal.md PV telemetry required vs optional (2026-10-17)

- [x] **`ehal.md` `sens_pv_production_active` asterisk / entity-scoped fields:** doc aligned to code (schema unchanged). The plant field is always required on the validated telemetry document; only its mapping may be omitted when Live derives it (`with_live_pv_attribution`, fail loud otherwise). `pv.{id}.sens_pv_production_active` is documented as binding/push key only, outside the schema (`additionalProperties: false`).

### Document Review ehal-com.md backlog IDs and cutover tables (2026-10-17)

- [x] **`ehal-com.md` backlog IDs:** no `Q5` / `Q8` / `q.D` left in `docs/ui/`; `backlog_id_baseline` has no entry for the file, nothing to lower.
- [x] **`ehal-com.md` Write push-only / historical cutover tables:** staged rollout checklist moved to `docs/dev/loxone-write-push-only-cutover.md`; `### Write push-only` kept as a short summary (inbound anchor `#write-push-only` still valid).

### Document Review streamlit-ports.md launch names (2026-10-17)

- [x] **`streamlit-ports.md` VS Code launch names:** local `.vscode/launch.json` aligned to the doc (untracked file): local venv entries now `:8501` (port 8501), NAS entry `NAS` on 8504 (8503 stays free for the OpenEMS lab). Shadow (8531) and chart_debug_review (8502) are `[dev]`: not in the user doc, noted in `DEVELOPER.md` (Shadow Mode section).
- [x] **`streamlit-ports.md` audience:** moved from `docs/referenz/` to `docs/dev/streamlit-ports.md` (still German, translation pending); all inbound links updated (user docs, READMEs, compose comments, `DEVELOPER.md`).

### Document Review loxone-signals.md language (2026-10-17)

- [x] **`loxone-signals.md` language:** translated to German in place (`docs/referenz/loxone-signals.md`, link targets and anchors unchanged). The English original is kept as developer reference `docs/dev/loxone-signals-en.md`.

### Document Review flexible-verbraucher.md legacy overlay (2026-10-17)

- [x] **`flexible-verbraucher.md` legacy overlay:** "beim Laden abgelehnt bzw. ignoriert" replaced by the actual behaviour: `flexible_consumers[]` is still loaded and merged with the house-profile consumers; on equal `id` the overlay entry wins. Behavior review → `Backlog.md` Version 2.8.

### Document Review speichern-laden.md stamping (2026-10-17)

- [x] **`speichern-laden.md` stamping claims:** "Jede JSON-Datei trägt `earnie_data_model`" replaced by the actual behaviour: manifest + JSON files carry it, `grid_fees.json` is never stamped (export/import); the manifest version decides the import; v3 is migrated automatically with the same chain the wizard uses.

### Document Review betriebsmodi.md dev link (2026-10-17)

- [x] **`betriebsmodi.md` dev-doc link:** dropped the "Spezifikation (Entwicklerdokument)" link to `docs/dev/done/ui-sunset2sunset.md` from the user doc.

### Document Review internal jargon in user docs (2026-10-17)

- [x] **Internal jargon in user docs:** `S-2-Modus`, `(v0.8.1)`, `Pool C.6`, `design-C1` — only `loxone-signals.md` still contained any (`design-C1`, `§C.6` x2); scrubbed there. `betriebsmodi.md`, `charts.md`, `flexible-verbraucher.md` were already clean (remaining `S-2-Modus` hits are in `docs/spec/` and `docs/dev/done/`, not user docs).

### Document Review betriebsmodi.md Leistungspreis (2026-10-17)

- [x] **`betriebsmodi.md` — Leistungspreis:** doc claimed "Leistungspreis und netzgebietsspezifische Tabellen fehlen". Reworded: the Netznutzung Arbeitspreis is taken per Netzgebiet from `grid_fees.json`; only the Leistungspreis is not yet considered.

### Bugfix — Preisprognose EU-Features Spiegelung (2026-10-17)

- [x] **Preisprognose: EU-Features → Spiegelung (NAS)** — **Verified** (2026-10-17)
  - Symptom: frequent `Preisprognose: EU-Features nicht ladbar (ValueError, mode=live_forecast) — Spiegelung als Fallback`.
  - Cause: all-or-nothing Energy-Charts load — one flaky country (e.g. Italy timeout under `GLOBAL_TIMEOUT=5`) aborted the whole EU power day → mirror for green slots.
  - Fix: soft-skip failed countries and sum the rest; Energy-Charts HTTP timeout floor 30s; warning includes exception text. Mirror only if every country fails.
  - Tests: `tests/test_eu_market_features.py` (`test_fetch_eu_power_hourly_skips_failed_country`, `test_fetch_eu_power_hourly_raises_when_all_countries_fail`, `test_energy_charts_timeout_floors_at_30`).

### Document Review smarthome-backend-wahl.md HA snippet (2026-10-17)

- [x] **`smarthome-backend-wahl.md` — HA snippet:** doc said the snippet contains only `ehal.backend` and `sign`. Extended to list `adapter_id`, `ha.transport` (link to `ha-evcc.md`), `ha.sign` and `ha.boolean_invert`.

### Document Review ha-evcc.md optional map fields (2026-10-17)

- [x] **`ha-evcc.md` — optional map fields:** doc claimed outdoor temperature, EV-SoC/connected and Flex-/Pool fields could be stored in the UI but did not run in the HA live path. Reworded: these fields are not part of `HA_MAP_FIELDS`, the mapping assistant does not offer them, and they are currently unavailable with the Home Assistant backend (live reads go through the Loxone push inbox).

### Document Review container.md alpha compose pin (2026-10-17)

- [x] **`container.md` — alpha compose pin `2.6.1-beta.1`:** doc now states the pin is only updated with the next pre-release and may be older than the latest official release (`v2.6.2`). Compose pins stay unchanged until the next approved pre-release bump (release process, `version.py` needs approval).

### Document Review homeassistant-addon.md port 8541 (2026-10-17)

- [x] **`homeassistant-addon.md` — port 8541 scope:** Ports table now states the port is relevant for `ehal.backend=loxone` and for Home Assistant with `ehal.ha.transport=push` (same HTTP contract), not needed for `pull`. Add-on `config.yaml` port descriptions (`earnie`, `earnie_prerelease`) aligned ("bei Loxone-Backend oder HA-Transport push").

### Document Review homeassistant-addon.md internal vocabulary (2026-10-17)

- [x] **`homeassistant-addon.md` — internal planning vocabulary:** headings reworded for users ("Add-on 0.2" / "Feature-Stufe 0.2" removed, "M3-Persistenz-Nachweis" and "Sprint 2" dropped); Dogfood checklist (HAOS-in-VM) moved to `docs/dev/homeassistant-addon-dogfood.md`.
- [x] **`homeassistant-addon.md` — image name:** intro now names the add-on image `ghcr.io/jochentcc/earnie-addon-{arch}` and states it builds on `earnie-energy`.

### Document Review P1 DE Check fact fixes (2026-10-17)

- [x] **Priority-1 German docs Check** against code (checklist § 2026-10-17); clear fact/link fixes applied
  - Data model: `speichern-laden.md` → `earnie_data_model` **4** (import 4 / migrate 3).
  - Container: alpha pin `2.6.1-beta.1`, backtick link, drop `2.0 P6` / obsolete log rename.
  - HA add-on: link → `ha-evcc.md`, `usage_ping` option, uninstall `addon_configs` + `/data`, drop stale 2.6 version wording.
  - Loxone: ESS writes on `batteries[].ehal_bindings` / `ess.{slug}.*`; sticky = Virtual In; Write push-only anchor.
  - `loxone-signals.md`: Signalliste anchors, drop Q5/Q8/P4, add `VO_Earnie_Battery.xml`.
  - Ports/README: venv **8501** (not 8531); HA add-on in Betrieb + install table; roadmap 2.7/2.8.
  - Misc: `smarthome-backend` backlog draft link removed; `batterie-pv` / `flexible-verbraucher` epic IDs + Nennleistung wording; loxberry backtick links.
  - Verified OK (no doc change): Sankey Flex/EV-SoC still Loxone-only; handbook Jahres-Verbrauch explicit anchors; `preise.md` Leistungspreis; `overview.md`.
  - Checklist: all Priority-1 DE **Check = x**. Style and maintainer decisions remain open in Findings.

### Cleanup — drop `/alive`; keep `heartbeat` (2026-10-17)

- [x] **Hard-remove `GET /ehal/loxone/alive` / `Earnie_Push_Alive`** `[qual]` — hub→Earnie link proof is synthetic `heartbeat` only
  - Removed `ALIVE_PATH` handler (now 404); dropped VO cmd from `VO_Earnie_Status.xml`.
  - Successful `heartbeat` telemetry push also updates `loxone_last_callback` (former `/alive` role).
  - Kept: `heartbeat_ts` VI / `status.json`, `request_optimize`, callback on status poll.
  - Tests: `test_loxone_request_http` (`test_http_alive_removed`, `test_http_heartbeat_records_callback`), `test_loxone_push_inbox`.
  - Docs/schema/compose: scrub `/alive`; note to delete obsolete Push_Alive in existing Config.

### Bugfix — request_optimize missing from Signalliste / Live-Lesen (2026-10-17)

- [x] **`request_optimize` missing from EHAL-Com Signalliste / Live-Lesen** — **Verified** (2026-10-17, local Streamlit)
  - Still used: VO `Earnie_Request_Optimize` → `POST /ehal/loxone/request_optimize` wakes the daemon.
  - Fix: receipt recorded in push inbox (`request_optimize`); listed on Signalliste (Status) and Live-Lesen (Mapping `Earnie_Request_Optimize`); age stays OK (not stale after 5 min).
  - Tests: `test_ehal_signal_list`, `test_loxone_request_http`, `test_loxone_connectivity`, `test_loxone_push_inbox`, `test_qualified_ids`.
  - Docs: `docs/ui/ehal-com.md`, `docs/referenz/loxone-signals.md`, `docs/spec/ehal.md`.

### Bugfix — EV unplugged live slot planned charge (2026-10-17)

- [x] **EV unplugged: live slot still planned charge** — **Verified** (2026-10-17, Shadow)
  - Dump: `debug-dumps/debug_dump_20261016_150238` (title: planned charging although not connected).
  - Symptom: with `forecast_when_absent` / `open_cycle`, MILP could fill the **current** quarter-hour while `plugged_in=false` (future slots OK; live setpoint already 0 via `suppresses_live_charging_output`).
  - Fix: `consumer_charging_eligible_indices` skips `t==0` when `anticipated` and not plugged in (`optimizer/charging_schedule.py`).
  - Tests: `tests/test_charging_context.py::TestEligibleIndices` (`test_late_return_skips_live_slot_keeps_future`, `test_anticipated_open_cycle_blocks_current_slot_only`).
  - Docs: `docs/spec/ev-return-prognosis.md`, `docs/konfiguration/flexible-verbraucher.md`.
  - Verification: Shadow — live slot `smart=0.0`, future slots still planned; eligibility log `slot0_eligible: false`.

### Bugfix — normalize_backend unknown → Loxone (2026-10-17)

- [x] **`normalize_backend` silently maps unknown `ehal.backend` values to Loxone** (found 2026-10-16 while testing ConfigMigration `dm4.loxone_binding_names`)
  - Symptom: typo like `ehal.backend: "homeassistant"` (meant `"ha"`) ran Earnie as Loxone with no error; migration step `dm4.loxone_binding_names` then treated HA entity ids as Merker names.
  - Cause: final `return BACKEND_LOXONE` caught every unknown value; schema enum was not enforced on the runtime path.
  - Fix: unknown → `ValueError` (fail-loud, same as `normalize_ha_transport`); empty / `None` / `loxone` / `none` → Loxone; `ha` / `openems` unchanged.
  - Tests: `tests/test_ehal_setup.py::test_normalize_backend_defaults_to_loxone`; `tests/test_migration_registry.py::test_loxone_names_unknown_backend_surfaces_error`.

### Bugfix — EHAL SoC error logged literal `ess.{id}` (2026-10-17)

- [x] **EHAL SoC read error logged literal `ess.{id}`** — **Verified** (2026-10-17)
  - Symptom: at `main.py` start, `EHAL SoC read failed: missing primary ess.{id}.sens_ess_soc` — placeholder not replaced; ambiguous on NAS.
  - Cause: `integrations.ehal_live.read_ess_soc` logged a docs-style template; `primary_id` was already resolved but unused in the message.
  - Fix: log concrete `ess.<primary_id>.sens_ess_soc` (or a clear no-primary-id branch) plus a short map/Live hint.
  - Tests: `tests/test_ess_soc_by_id.py` (`test_read_ess_soc_error_names_concrete_primary_id`).

### Bugfix — grid_fees.json earnie_data_model stamp (2026-10-17)

- [x] **`grid_fees.json` gets `earnie_data_model` stamped by config-pack export / import** — **Verified** (2026-10-17; ConfigMigration P2)
  - Export (`build_config_pack_bytes`) and `write_json_dict` no longer stamp `earnie_data_model` onto `grid_fees.json`; import already skipped stamp. Existing stamped keys are not stripped on load (migration step later).
  - Tests: `tests/test_config_pack_and_paths.py` round trip; `tests/test_json_io.py` (`test_write_json_dict_does_not_stamp_grid_fees`).
  - Live check (NAS productive): live `grid_fees.json` and pre-migration backup have no stamp; Earnie-track siblings in the same backup are stamped `4`.

### Bugfix — Live day-ahead ENTSO-E re-fetch every cycle (2026-10-17)

- [x] **Live day-ahead prices re-fetched from ENTSO-E every cycle** — **Verified** on NAS productive (2026-10-17, `2.7.0-dev.60`)
  - Symptom (NAS productive `earnie.log`, 2026-10-15): `ENTSO-E AT request …` in every cycle, never `Using cached day-ahead`; `day_ahead_fetch` event in every `cycle_stats.jsonl` record; 4–17 s per cycle in `prices_matrix`.
  - Cause: `_try_cached_live` required the cache to cover the full planning window; the sunrise horizon reaches into D+2 (e.g. 17.10. 07:30), but day-ahead prices exist at most up to D+1 23:45, so coverage always failed.
  - Fix: fresh-cache coverage is checked up to `published_cover_end(window_end, now)` (last quarter-hour of `last_day_ahead_calendar_date(now)`); a cache without tomorrow after the publish hour still refetches. Outage path unchanged.
  - Tests: `tests/test_live_price_cache.py` (`test_published_cover_end_caps_window_at_last_day_ahead_day`, `test_sunrise_window_into_d2_uses_cache_once_tomorrow_is_published`, `test_cache_without_tomorrow_still_refetches_after_publish`).
  - Live verification (NAS `earnie.log` + `cycle_stats.jsonl`): after the bug day 2026-10-15, cache hits dominate — 2026-10-16: 195× `Using cached day-ahead`, **1×** `ENTSO-E AT request` at 11:45 (auction); 2026-10-17 to ~05:30: 45× cached, **0** ENTSO fetches. `live_day_ahead_AT.json` mtime 16.10. 11:45. `day_ahead_fetch` in cycle_stats: last on 2026-10-15 15:00; **0/121** records since 2026-10-16.

### Bugfix — usage_ping HTTP 400 (v2 vs stale LAN receiver) (2026-10-17)

- [x] **usage_ping send failed with HTTP 400 (v2 vs stale LAN receiver)** — **Verified** (2026-10-17)
  - Symptom: `usage_ping: send failed with status 400` when consent on and live+points (schema v2). Explorer/v1 pings to the same URL succeeded (204).
  - Cause: LAN receiver at `EARNIE_USAGE_PING_URL` (`…:8787/ping`) still ran the committed v1-only image (`v must be 1`); Earnie correctly POSTed v2 (`points` / `points_v`). Schema v2 existed only as uncommitted `earnie-server` working-tree changes until redeploy.
  - Fix: rebuild/redeploy `earnie-usage-ping:lan` from earnie-server with v2; client: `maybe_send_ping(force=True)` for lab resend (skips once-per-day / 1 h gate); WARNING on failure includes `v` / `stage` / keys + redeploy hint. Endpoint stays in `.env` as `EARNIE_USAGE_PING_URL`.
  - Live verification: force-send or next daily ping → HTTP 2xx; `last_sent_date` set; no 400 for live+points.

### Hauskonfigurator tab order (2026-10-17)

- [x] **Change order of sub-pages in HK** `[qual]`: segmented tabs Hausprofil → Wechselrichter → PV-Anlagen → Batterien (`ui/pages/page_house_config.py`); AppTest options assert; greenfield walkthrough lists.

### Epic UsagePing — opt-in anonymous install counter (2026-10-16)

- [x] **Epic UsagePing — opt-in anonymous install counter** `[qual]` (spec [`docs/spec/usage-ping.md`](../docs/spec/usage-ping.md); owner decisions 2026-10-16): count active installations per day. Strictly opt-in and revocable, one daily ping while consent is on, nothing sent otherwise; a failed ping never affects the optimisation. Payload is a fixed whitelist: `v`, random `id`, `app_version`, `context` (install context), `stage` (`explorer` → `live`, highest stage reached). The server hashes the ID with a daily rotating salt and stores only daily counters (`usage_daily.csv`), no IP, no access log.
  - **Decided:** one opt-in at the first milestone (first scenario exploration); second counter stage at the first successful live cycle. Install ID is random (not `hardware_identity`). Kill-switch `EARNIE_USAGE_PING=off`. Receiver = private **`JochenTCC/earnie-server`**. Deploy target = own VPS with **Caddy** TLS edge and stdlib receiver on an internal network; pre-deploy via mock/LAN lab; production host **hosttech** (EU) with AV. CSV columns: `date, installs_total, explorer, live, ctx_loxberry, ctx_ha, ctx_manual, versions_json`.
  - **Phases:** **P1**–**P5** in this archive below. Follow-on **EarniePoints** EP0–EP4 (schema v2 `points` / `points_v`) → next section below.

### EarniePoints EP0–EP4 — Earnie-Points in the usage ping (2026-10-16)

- [x] **Epic EarniePoints — Earnie-Points of the live plant in the ping (EP0–EP4)** `[qual]`: the daily ping (schema v2) additionally carries `points` + `points_v` of the **live** plant; the tariff mapping (S / M / L) happens offline at analysis time. Rule `points_v: 1` (business plan §5.2) is mirrored in `docs/spec/earnie-points.md`.
  - **EP0:** spec + decisions: air conditioner = new optional consumer key `appliance_kind: air_conditioner` (1 point); wallbox `bidirectional` flag on `ev` consumers (3 points); `earnie_role: manual` and known generic consumers are never counted; EV count not rated; existing consent is **not** re-prompted for schema v2 (transparency via “Was wird gesendet?” only). New keys are strict (`house_config/consumer_points_fields.py`, wired into `profiles_store.py`) and editable in the Hauskonfigurator (`ui/house_config_profile_points.py`).
  - **EP1:** `house_config/earnie_points.py` `compute_earnie_points(components, profile)` → `total/pv/storage/wallbox/heat/other`; fails loud on missing/negative values and on wallbox phases other than 1 or 3.
  - **EP2:** `runtime_store/usage_points.py`: the live plant is derived from the **live scenario** (`live_scenario_id` → `pv_system_ids`, `battery_ids`, `house_profile_id`; all powerstations included), so unused alternative components in `components.json` do not inflate the points. Recompute only when the mtime stamp of config / scenarios / components / profiles changes (not `config_drift`, which is a config-vs-example diff); hook in `note_live_cycle_success()` (live stage only, not in shadow mode). A calculation error logs a WARNING and sends no points (ping stays v1); same-UTC-day re-ping when `points` changed.
  - **EP3:** client whitelists `PAYLOAD_KEYS_V1` / `PAYLOAD_KEYS_V2` (`points` sent only at stage `live`). Receiver in private `JochenTCC/earnie-server` (code done and tested, **not yet deployed**): accepts v1 + v2, strict range check (`points` 0–99, `points_v` 1–999), counters stay first-wins per salted id and day, `points` is latest-wins; `usage_daily.csv` gains `points_hist` (JSON buckets `"0"`…`"20"`, `"21+"`).
  - **EP4:** “Was wird gesendet?” shows `points`/`points_v` with an explanation; read-only block “Earnie-Points dieser Anlage” with breakdown on the page Optimierer-Dienst (`ui/earnie_points_view.py`); German user docs (`docs/einrichtung/betrieb.md` with the public rule table, `docs/user-manual/Benutzer-Handbuch-Earnie.md`, `docs/konfiguration/flexible-verbraucher.md`) incl. privacy note.
  - **Tests:** `tests/test_consumer_points_fields.py`, `tests/test_earnie_points.py`, `tests/test_usage_points.py`, `tests/test_usage_ping.py`, AppTests for daemon page and Hauskonfigurator; receiver tests in `earnie-server`.

### UsagePing P3 — consent UI (2026-10-16)

- [x] **UsagePing P3 — consent UI (German)** `[qual]`: opt-in dialog at first open of Szenarienkonfigurator (`ui/usage_ping_consent.py`, `page_scenario_editor.py`); settings toggle + “Was wird gesendet?” on Optimierer-Dienst (`page_daemon.py`); AppTest coverage. Explorer stage on editor activate; `scenarios_calc_count` bump after successful SE calc forces same-day re-ping; advertising opt-in copy (“Um die Qualität von Earnie permanent zu verbessern …”).

### UsagePing P4 — receiver + deployment (2026-10-16)

- [x] **UsagePing P4 — receiver + deployment** `[qual]`: private repo **`JochenTCC/earnie-server`** (not this public tree): minimal stdlib receiver (strict schema, daily salt, in-memory rate limit, `usage_daily.csv`); LAN-only NAS compose (port 8787, no public edge, no port-forward / DDNS / DSM reverse-proxy); hardened container (`read_only`, `cap_drop`, `no-new-privileges`, internal network). Production URL on VPS + Caddy remains follow-up work in `earnie-server`.

### UsagePing P5 — docs + privacy (2026-10-16)

- [x] **UsagePing P5 — docs + privacy** `[qual]`: German user docs (what is sent, how to switch off) in `docs/user-manual/Benutzer-Handbuch-Earnie.md` (Live-Betrieb) and `docs/einrichtung/betrieb.md` § Nutzungsstatistik (payload table, UI / `EARNIE_USAGE_PING=off` / HA `usage_ping`, `usage_ping.json`, Datenschutz); privacy note (consent Art. 6(1)(a), IP/UA not stored, daily salt counters, host **hosttech** EU with AV); README Betrieb one-liner; spec `docs/spec/usage-ping.md` §6 / §9 hosting decided. Receiver lives in `earnie-server`.

### UsagePing P2 — daemon hook + milestones (2026-10-16)

- [x] **UsagePing P2 — daemon hook + milestones** `[qual]`: `spawn_maybe_send_ping()` (daemon thread, single in-flight) from `main.py` after `after_prod_cycle` and `_daemon_wait_poll`; `note_explorer_success` on successful Scenario Explorer (`ui/backtesting_run.py`, `scripts/run_backtesting.py`); `note_live_cycle_success` after `run_state.save_run_state` with `success` (skipped in shadow); HA add-on optional `usage_ping` bool mirrored via `addon_options._apply_usage_ping_option` → `set_consent` (earnie + prerelease `config.yaml`); spec §3 P2 note; tests in `tests/test_usage_ping.py` + `tests/test_addon_options.py`. Consent UI remains **P3**; receiver **P4**; docs **P5**.

### UsagePing P1 — client (2026-10-16)

- [x] **UsagePing P1 — client** `[qual]`: `runtime_store/usage_ping.py` (consent tri-state `unset`/`on`/`off`, random UUIDv4 install ID, payload whitelist `v`/`id`/`app_version`/`context`/`stage`, once-per-day UTC, 1 h retry via `last_attempt_at`, kill-switch `EARNIE_USAGE_PING=off`, endpoint `EARNIE_USAGE_PING_URL`, injected clock + fake transport); state `runtime/usage_ping.json` via `usage_ping_state_file()`; spec `docs/spec/usage-ping.md` §3–4 synced; tests `tests/test_usage_ping.py` (fake transport + local mock HTTP server). Daemon hook / milestones **P2** → done; consent UI **P3**; receiver **P4**; docs **P5**.

### Release-Notes workflow — draft, review, finalize (2026-10-16)

- [x] **Release-Notes workflow with maintainer review** `[dev]`: spec `docs/spec/release-notes-workflow.md`; rule `.cursor/rules/release-notes.mdc` + skill `release-notes` (AI writes drafts only to `.github/release-notes/drafts/`, no notes for `-dev` versions); `scripts/release_notes_collect.py` (evidence pack since the last published productive release, audience classification, unmerged-hotfix-tag warning, migration section from `HEAD`) and `scripts/release_notes_finalize.py` (`--approved` promote, `--check` CI gate); `release-publish.yml` fails without reviewed notes (generic fallback removed); `session-abschluss`, `versioning.mdc`, release checklist updated.
  - Audience marker `[feat]` / `[qual]` / `[dev]` on every top-level backlog entry (`backlog.mdc` §7, AI asks when missing; bugfixes need none); 117 existing archive entries backfilled; `.github/release-notes/audience.toml` pre-classifies commits and `dev_terms`.
  - No internal backlog version IDs (`2.7.n`, `2.+1`, …) in release notes or user docs: finalize/CI reject them, `tests/test_user_docs_audience.py` guards user docs; IDs removed from 15 user docs (`efm-auto-sync-2.4.l.md` renamed to `efm-auto-sync.md`).
  - Tests: `tests/test_release_notes_collect.py`, `tests/test_release_notes_finalize.py`, `tests/test_user_docs_audience.py`.
  - Shadow-Modus/Feed sections moved from `docs/einrichtung/betrieb.md` to `docs/entwicklung/shadow-betrieb.md`; developer index `docs/entwicklung/README.md`; `docs_allowlist` is empty. Open: dry-run draft for 2.7.0-alpha.1 pending review; `gh` required for automatic baseline.

### ConfigMigration P4 — process + docs (2026-10-16)

- [x] **ConfigMigration P4 — process + docs:** `[feat]` rule `.cursor/rules/config-migration.mdc` + `CLAUDE.md` Area notes pointer; release checklist Migration item + helper `python -m scripts.migration_release_notes --since <tag>` (`tests/test_migration_release_notes.py`); German user docs `docs/einrichtung/betrieb.md` → Update und Migration (backup paths Docker / LoxBerry / HA add-on) + TOC/cross-links; spec `docs/spec/config-migration.md`. Epic **ConfigMigration** (P0–P4) complete for Version 2.7; tariff track deferred to 2.8 Edbert integration.

### ConfigMigration P3 — wizard (German) (2026-10-16)

- [x] **ConfigMigration P3 — wizard (German):** `[feat]` hint + last run version + release-notes link; pending steps (`title_de` / files) with expandable diffs; questions (`str` / `bool` / `choice`); blockers; manual to-dos (download only when `export_kind` is known); button **Backup anlegen und migrieren** → `run_migration` → report; **Weiter zur App** calls `maybe_auto_start()` (respects `EARNIE_AUTO_START_MAIN` / add-on `auto_start_main`) then `st.rerun()` into normal UI; AppTest `tests/apptest/test_page_config_migration_apptest.py` + unit helpers `tests/test_page_config_migration.py`. Process/docs remain **P4**.

### ConfigMigration P2 — startup gate (2026-10-16)

- [x] **ConfigMigration P2 — startup gate:** `[feat]` bootstrap no longer silently stamps/migrates live pack files (templates only; new greenfield live files stamped once on create); untagged Earnie-track file = planner blocker (`grid_fees.json` exempt); `runtime_store/migration/gate.py`; `run_streamlit` + `app.py` migration mode (skip `load_config_or_exit`, no daemon auto-start, stub page + log); `load_config_or_exit` / `main_daemon.start` / Shadow refuse while pending; `ensure_compatible` messages point to wizard + CLI; `grid_fees.json` no longer stamped on export/`write_json_dict`; tests `tests/test_migration_startup_gate.py`. Full wizard UI remains **P3**.

### ConfigMigration P1 — registry + runner (2026-10-16)

- [x] **ConfigMigration P1 — registry + runner:** `[feat]` `MigrationStep` registry in [`runtime_store/migration/`](../runtime_store/migration/) (pure detect / apply, questions, blockers, manual to-dos); planner (dry run + per-file diff) and runner (validate with real loaders → backup `config/backups/pre-migration-…` → atomic replace); CLI `python -m scripts.migrate_config`; v3→v4 + seven legacy steps as detect-based dm4 steps; config-pack import on the same chain; legacy `migrate_*` CLIs thin-wrapped; goldens under `tests/fixtures/migration/goldens/`; tests `tests/test_migration_registry.py` (chain, golden, idempotency, meta coverage, failure injection, dual-track synthetic, pack import). CLI dogfood on fixture copies accepted 2026-10-16.

### ConfigMigration P0 — inventory + fixtures (2026-10-16)

- [x] **ConfigMigration P0 — inventory + fixtures:** `[dev]` documented order / inputs / idempotency / loader rejections for v3→v4 and the seven in-model one-shots in [`Config-Migration-Inventory.md`](Config-Migration-Inventory.md); scrubbed before-snapshots from Earnie-env-home (`v3_last`, `v3_single_battery`, `v3_pre_ehal`, `v4_pre_quellenwahl`, `v4_pre_inverter_gridfee`, `v4_pre_conversion`, `v4_pre_topology`) under `tests/fixtures/migration/`; re-extract via `python -m scripts.extract_migration_fixtures --env-home <Earnie-env-home>`. Goldens and registry tests remain **P1**.

### Bugfix — Restart cycle counted in punctuality and early-start lead (2026-10-16)

- [x] **Punctuality stats and early-start lead include the first cycle after a `main.py` restart** — **Verified** (2026-10-16)
  - Symptom: the first cycle after a daemon (re)start is recorded with `trigger = quarter_hour`, `outcome = ok` and therefore counts like a regular cycle. NAS 2026-10-15: the restart at 12:17 (`cold_start`, `late_by_sec` +213 s) alone made the 24 h summary report `P95 +213 s`.
  - Cause 1 — punctuality (`runtime_store/cycle_duration_stats.py`, `CycleStats.to_record`): `on_time` is set for every `quarter_hour` cycle. The first cycle after start is not planned for a tick (`tick=None`), starts somewhere inside the slot and is counted as late in the on-time rate and P95.
  - Cause 2 — lead estimator (`optimizer/start_scheduler.py`, `plan_durations`): filters only by trigger, outcome and platform, not by the `cold_start` event. A cold start's time to plan includes imports, profile recomputation and the EU power-archive load (30–45 s vs. 8–16 s on dev.57). The median is robust to a few restarts per day, but several deploys in a row would push the lead up.
  - Fix: (1) cycles not scheduled for a tick (first cycle after start; `main.main(tick=None)` on the regular trigger) get `on_time = null` → excluded from rate and P95 like out-of-band runs; the record stays in `cycle_stats.jsonl`. (2) `plan_durations` skips records with event `cold_start`.
  - Tests: `tests/test_cycle_duration_stats.py` (`test_first_cycle_after_start_is_excluded_from_punctuality`), `tests/test_start_scheduler.py` (`test_cold_start_records_are_ignored_by_decide_lead`).

### Minor — Debug-dump includes powerstation_reserves.json (2026-10-15)

- [x] **powerstation_reserves.json in debug-dump** `[feat]` — added to `_OPTIONAL_RUNTIME` in `runtime_store/debug_dump_archive.py` (copied when present); docs `docs/einrichtung/betrieb.md`; test `test_write_debug_dump_zip_without_chart`.

### Bugfix — Chart 1 SoC vs Zwangsladen/Zwangsentladen underlay time alignment (2026-10-15)

- [x] **Alignment mismatch (time-wise) between SOC line and forced charging / discharging decoration** — **Verified** (2026-10-15, Monitor Chart 1)
  - Symptom: thick ESS-mode underlay (Zwangsladen / Zwangsentladen) looked shifted vs the visible SoC line (e.g. tomorrow ~18:15).
  - Cause: underlay followed aggregate `Simulierter SoC (%)` while Chart 1 drew per-ESS `SoC · {label}`; multi-ESS horizon also lagged the controlled battery column by one slot (start-of-slot written back into `soc_by_ess`).
  - Fix: underlay resolves the Steuerbefehl battery via `battery_params` label/id; `_advance_chart_soc_after_slot` uses end-of-slot SoC for the controlled ESS.
  - Tests: `tests/test_ess_mode_soc_underlay.py` (`test_underlay_follows_controlled_battery_column_not_aggregate`).

### Bugfix — Metered consumers missing in Sankey + Chart 1 (2026-10-15)

- [x] **Consumption of consumers with provided current power neither shown as Sankey paths nor Chart 1 bars** — **Verified** (2026-10-15, shadow Monitor)
  - Symptom: known/manual/thermal consumers with mapped `sens_power_act` (e.g. Kochen, TV, appliances, pool) missing as separate Sankey paths and as consumer-specific Chart 1 bars; live power still visible on EHAL-Com / sampler.
  - Cause: `marker_flex_power` only accepted `flex.{id}.sens_power_act`; house profile stores Live/exchange qids (`consumer|pool|heatpump.{id}.sens_power_act`, often empty Merker / push-only), so meters never entered live resolve / Sankey `meter_ids`. Chart 1 history also omitted known metered Ist columns.
  - Fix: `marker_flex_power` resolves qualified `*.sens_power_act` like `marker_flex_enable`; `entry_to_chart_row` attaches known metered Ist via `_attach_known_meter_flex_columns`.
  - Tests: `tests/test_clear_loxone_binding_names.py` (`test_empty_activation_resolves_sens_power_act_qids`); `tests/test_history_timeline.py` (`test_entry_to_chart_row_attaches_known_meter_ist`).

### Bugfix — Standby Powerstation charge not covered by house grid/battery energy (2026-10-15)

- [x] **Standby Powerstation charge not covered by house grid/battery energy** — **Verified** (2026-10-15) on `fix/powerstation-charge-energy-balance`
  - Symptom (dump `debug_dump_20261015_145649`, Ecoflow `standby_backup`): Chart1 SoC rises (e.g. 67.8→100%) while house battery/grid cover is short.
  - Cause: standby `charge_kw` planned + SoC advanced, but not added to house `expected_p_act` (live and Chart1 horizon).
  - Fix: `apply_standby_load_relief` also adds grid-pass-through charge; wired in `main.py` + `simulation.py` horizon setup.
  - Tests: `tests/test_powerstation_2_7_h.py` (`test_apply_standby_load_relief_adds_grid_charge_to_house_load`).

### Bugfix — Heat storage: Live never applied solar-collector heat (2026-10-15)

- [x] **Heat storage: Live never applied solar-collector heat** — **Verified live** (2026-10-15)
  - Symptom: heat storage appeared never to collect energy via the solar collector on NAS productive.
  - Cause: Live callers (`_live_store_flex_overlay`, horizon need, observability) never passed `solar_forecast_kw`; planner defaulted to zeros. Year-sim already injected collector yield.
  - Fix: `resolve_live_collector_solar_kw` (Open-Meteo archive DOY/hour; later horizon path uses forecast irradiance) auto-fills when callers omit solar; wired in `plan_live_store_for_thermal_consumer`.
  - Tests: `tests/test_collector_irradiance_forecast.py` (resolve); `tests/test_thermal_live_collector_regression.py` (store T rises above setpoint when `solar_forecast_kw=None` + sunny midday + `solar_thermal_area_m2` > 0).

### Clock-skew diagnostics (2026-10-15)

- [x] **Clock-skew diagnostics** `[qual]` (spec [`docs/spec/early-start-scheduling.md`](../docs/spec/early-start-scheduling.md) §7; not part of EarlyStart): `runtime_store/clock_skew.py` — daemon installs a hook on `requests.Session.send` and reads the `Date` header of HTTPS responses from public hosts the cycle already receives (no extra request; LAN/plain-HTTP hosts ignored). Sample = (Date + 0.5 s) − (received − elapsed/2); responses slower than 2 s dropped; estimate = median of ≥ 3 samples from the last hour. |offset| > 2 s → `clock_skew` WARNING with NTP hint (at most hourly). `clock_skew_sec` in each `cycle_stats.jsonl` record (+ = system clock behind). No early-start gate.
  - Tests: `tests/test_clock_skew.py`. Docs: `docs/einrichtung/betrieb.md` § Zyklus-Pünktlichkeit und Vorlauf.

### EarlyStart follow-up — prefetch slow inputs off the critical path (2026-10-15)

- [x] **EarlyStart follow-up — prefetch slow inputs off the critical path** `[feat]` (spec [`docs/spec/early-start-scheduling.md`](../docs/spec/early-start-scheduling.md) §8)
  - Finding: the EU-feature cache was keyed by slot range, so it missed at every full hour (planning window moves); NAS 13:00 cycle spent 24 s + 22 s on two Open-Meteo calls.
  - `data/price_forecast_live.py`: network inputs cached per `(kind, start date, end date)` (`forecast_weather`, `archive_weather`, `archive_power`), 45 min TTL; `price_feature_refresh` only on a real fetch; routine cached builds log at DEBUG.
  - `runtime_store/planning_clock.py`: `cache_valid_until` / `cache_entry_fresh` (refresh-ahead), used by the feature cache and the Open-Meteo outdoor / tilted caches.
  - `data/live_prefetch.py` + `main._prefetch_for_next_cycle`: after each cycle (≥ 120 s idle), under `planning_anchor(next tick)` and `cache_valid_until(start + 120 s)`: day-ahead, `resolve_market_slots` (features + bias lookback), outdoor temperature + collector irradiance. forecast.solar excluded. Failing steps → WARNING, cycle fetches itself. Log `Prefetch für HH:MM: … in X s`.
  - Tests: `tests/test_live_prefetch.py`, `tests/test_planning_clock.py`, `tests/test_early_start_equivalence.py::test_prefetch_keeps_the_plan_and_takes_fetches_off_the_cycle`. Docs: `docs/einrichtung/betrieb.md`.
  - Live check on NAS: `weather_fetch` / `price_feature_refresh` should disappear from the `Pünktlichkeit:` events; `day_ahead_fetch` only once right after the auction.

### EarlyStart P1 — adaptive lead, plan for the tick, write at the tick (2026-10-15)

- [x] **EarlyStart P1 — early start on by default** `[feat]` (epic **EarlyStart**; spec [`docs/spec/early-start-scheduling.md`](../docs/spec/early-start-scheduling.md) v2) — reduced scope after the NAS dev.57 measurements (cycles 12–19 s, setpoints +8…16 s; outlier +72 s from Open-Meteo/ENTSO-E I/O)
  - `optimizer/start_scheduler.py` (pure): goal = minimal age of the written setpoints in both directions → lead = clamp(**median** time to plan of the last 96 regular cycles on this platform, **15 s, 90 s**) — start between T−90 s and T−15 s (median minimises mean |ready − T|); < 8 samples → 60 s bootstrap; estimate > 90 s → capped + warning (once per transition). `EARNIE_EARLY_START=on|off` (default `on`, other values fail loud).
  - `runtime_store/planning_clock.py`: `planning_anchor(T)` / `planning_now()` = max(real now, T). Planning-relevant "now" (slot start/key, planning window, `current_hour`, today's targets, forecast/thermal start, price windows, EV sessions, appliance schedules) reads it; measurements keep the real clock (PV integral, sampler, cons_data, API guards, write timestamps).
  - `main.py`: daemon starts the regular cycle `lead` before the next tick; `_hold_until_tick` before the first write (no setpoint before T; late plan → write at once, info up to T+90 s, warning beyond); `finalize_closed_interval` + PV delta after the hold; SoC plausibility uses the previous cycle's closed interval. No state projection (owner decision). First cycle after start, out-of-band runs and `off` keep today's behaviour.
  - Punctuality log: `lead_sec`, `ready_at`, `ready_by_sec`; wake/start delay vs. planned start; log line `Vorlauf … | Plan fertig …`.
  - Docs: `docs/einrichtung/betrieb.md` § Zyklus-Pünktlichkeit + env table. Tests: `tests/test_start_scheduler.py`, `tests/test_planning_clock.py`, `tests/test_main_early_start.py`, `tests/test_cycle_duration_stats.py`.
  - Equivalence test `tests/test_early_start_equivalence.py` (full offline cycle, wall clock frozen with `time-machine` — new dev dependency): early start at T−15 s / T−90 s plans and writes exactly what a cycle at T does, for quarter/hour/12:00/midnight/month/New Year/DST ticks. It found and fixed: Open-Meteo `forecast_days` must use the real date (API semantics; a 23:58 cycle asked for one day too few → heat-pump target off by 3 kWh); `MODELED_PROFILE_REF_START` evaluated at import (stale archive year after New Year in a long-running daemon) → `modeled_profile_ref_start()`; `last_full_archive_year` follows the planning date. Known availability difference (not fixed): forecast.solar returns today + tomorrow of the request date, so the cycle just before midnight lacks PV for the day after the tick (synthetic fallback) for one cycle.
  - Live check on NAS productive: `Pünktlichkeit:` lines should show `Sollwerte +0…2 s` for most ticks; misses cluster at cache-expiry ticks → prefetch follow-up.

### Bugfix — Daemon wait loop drifted ~1 min behind the quarter-hour tick (2026-10-15)

- [x] **Daemon wait loop drifts ~1 min behind the quarter-hour tick** — **Verified live** (2026-10-15)
  - Symptom (NAS productive `earnie.log`): regular cycles started 66–73 s after the tick (e.g. tick 09:15, `Live-Abfrage gestartet` 09:16:13), so setpoints landed ~1 min late every slot.
  - Cause: `wait_for_optimize_or_timeout` (`integrations/loxone_request_http.py`) decremented `remaining` only by the sleep chunk; time spent in `on_poll` (`touch_daemon_heartbeat` + `power_interval_sampler.tick`, loads the ~190 KB state JSON each poll) extended the wait (~900 polls × ~0.07–0.1 s ≈ 1 min).
  - Fix: wait against a monotonic deadline (`clock_fn`, default `time.monotonic`); early wake via Earnie_Request_Optimize unchanged. `wait_until_next_run` passes `clock_fn` through.
  - Tests: `tests/test_loxone_request_http.py` (`test_wait_on_poll_cost_does_not_extend_total_wait`, `test_wait_early_wake_with_fake_clock`).
  - Live verification: NAS `runtime/cycle_stats.jsonl` from 11:00 on: `wake_delay_sec` 0.006–0.09 s (2.04 s once) vs. 66–73 s before.

### Profiling session — main.py optimization cycle (2026-10-15)

- [x] **Make a profiling session for main.py to identify acceleration potentials for optimization cycle** `[dev]`
  - Instrumentation: `EARNIE_CYCLE_TIMING=1` / `EARNIE_CYCLE_PROFILE=1` → `runtime/timing/cycles.jsonl` (+ optional `runtime/profile/`); docs `betrieb.md` / `container.md` § Live-Zyklus-Profiling; summarize with `python -m scripts.summarize_cycle_timing …`.
  - NAS window 2026-10-15 (`2.7.0-dev.54`, 7 cycles timed / 2 with cProfile): Ø cycle ≈ 212 s — dominant cost ~810 full-year thermal simulations. Follow-ups shipped: **dev.55** slot-series, **dev.56** year-model memo, **ThermalHorizon P1–P5** (`2.7.0-dev.57`, PR #37). Mid-path NAS sample after dev.55 alone: ~211 s → 54 s.
  - **Do not** use `EARNIE_CYCLE_PROFILE=1` in production again (Python ≥ 3.12 `sys.monitoring` instruments all threads; slowed Loxone push HTTP ~3× → Miniserver `state=Lesefehler`). Prefer local recorder-cycle replay or py-spy.
  - Closed with owner decision: remaining NAS re-measure / `thermal_observability` Q_sim vs Q_meas no longer tracked as an open backlog item; further speed-ups live under EarlyStart follow-ups and ad-hoc timing.

### Rotate `main_stdio.log` like `earnie.log` (2026-10-15)

- [x] **Rotate `main_stdio.log` like `earnie.log`:** `[dev]` spawn-time rotation in `runtime_store/main_daemon.py` (`_maybe_rotate_stdio_on_spawn`: ≥ 5 MiB or prior calendar month; archives `main_stdio.log.YYYY-MM-DD_HH-MM-SS`, max 12 via `month_file_rotation`). UI/auto-start sets `EARNIE_DAEMON_STDIO_CAPTURE=1`; `logger_config.setup_logging` skips the console `StreamHandler` so INFO is not mirrored into the capture (prints/tracebacks remain). Docs: `docs/einrichtung/betrieb.md`. Tests: `tests/test_main_daemon.py`, `tests/test_logger_config_rotation.py`.

### Cycle speed-up — batch Loxone push inbox writes (2026-10-15)

- [x] **Cycle speed-up — batch Loxone push inbox writes:** `[feat]` `record_push` keeps `_memory` / `_last_known` synchronous; disk flush of `loxone_push_inbox.json` is debounced (`INBOX_FLUSH_INTERVAL_S` = 1.0, `threading.Timer`, write outside `_lock`); `flush_inbox_now()` for tests/shutdown (`atexit`). Shadow feed JSONL append stays per-push. Daemon `read_push_*` unchanged; UI may lag ≤1 s. Tests: `tests/test_loxone_push_inbox.py` (`test_record_push_debounces_disk_flush`).

### Cycle speed-up — Open-Meteo + config I/O caches (2026-10-15)

- [x] **Cycle speed-up — in-process cache for Open-Meteo climate bundles:** `[feat]` process-wide path+mtime memo in `data/open_meteo_solar_archive.py` (`_load_bundle_from_cache` / `_save_bundle_to_cache`); `clear_open_meteo_bundle_mem_cache()` for tests. Avoids re-`pandas.read_json` across fresh `ModeledClimateContext` / thermal callers (~1269×/cycle before). Tests: `tests/test_open_meteo_solar_archive.py` (mem hit + mtime invalidation).
- [x] **Cycle speed-up — cache config documents and sidecar path resolution:** `[dev]` `_resolve_sidecar_json_path` memo by env key (`clear_sidecar_path_cache`); mtime/shadow memo for `load_house_profiles_document` and `load_components_document` (save clears); push/shadow writers use mkdir-only-if-missing. Tests: `tests/test_persist_paths_sidecars.py`, `tests/test_config_doc_caches.py`.

### ThermalHorizon P1–P5 — year model for parameters only, horizon in Live (2026-10-15)

- [x] **Thermal horizon simulation — year model once for parameters, horizon only in Live** `[feat]` (epic **ThermalHorizon**; spec [`docs/spec/thermal-horizon-simulation.md`](../docs/spec/thermal-horizon-simulation.md); `2.7.0-dev.57`, PR #37 → `main` `25a1a601`)
  - **P1:** `optimizer/thermal_parameters.py` — annual WP/RC electric kWh + envelope `H` from last full archive year, memoized; baseload + Live store read it; missing climate fails loud. Owner install `H` 0.110 → 0.069 kW/K (partial-year calibration removed).
  - **P2:** Live store flex context from `LiveStorePlan`; `optimizer/live_cycle_scope.py` shares one plan per cycle (readings + forecast) across flex / targets / both MILPs.
  - **P3:** collector irradiance from Open-Meteo `global_tilted_irradiance` (`get_hourly_tilted_irradiance_forecast_wm2`); fallback last year + warning; `collector_solar_source` in observability; user doc `docs/konfiguration/flexible-verbraucher.md`.
  - **P4:** `plan_live_house_horizon` / `live_house_plan_for_matrix` for Live without storage; legacy no-Wohnfläche = warm water minus forecast collector heat.
  - **P5:** `tests/test_thermal_live_guard.py` — no year-model calls in Live outside parameter derivation; rejected telemetry no longer drops Live thermal semantics (`is_live_thermal_planning`).
  - Tests: `tests/test_thermal_parameters.py`, `test_thermal_live_context.py`, `test_thermal_live_house.py`, `test_collector_irradiance_forecast.py`, `test_thermal_live_guard.py`.
  - NAS re-measure / Q_sim vs Q_meas follow-up closed with the profiling session archive above.

### Cycle speed-up — memoize thermal year models (2026-10-15)

- [x] **Cycle speed-up — memoize the thermal year models:** `[feat]` process-wide LRU `optimizer/thermal_year_cache.py` for `house_year_result` and `thermal_rc` year model (`thermal_rc_hourly_kw_and_temp_from_ambient`). Keys hash full inputs (climate by content; offline fixture by path + mtime); hits return list copies (bit-identical). Shipped as `2.7.0-dev.56` on the ThermalHorizon branch; merged via PR #37. Tests: `tests/test_thermal_year_cache.py`. Local bench: identical outputs; residual baseload cost = climate bundle `read_json` → closed under *Open-Meteo + config I/O caches* above.

### Cycle speed-up — deploy dev.55 thermal slot-series fix (2026-10-15)

- [x] **Cycle speed-up — deploy dev.55 thermal slot-series fix to the NAS:** `[feat]` `9eb1cbe9` (`modeled_consumer_kw_for_slots`) was not in the profiled image. Live passes `climate=None`, so it removes ~360 of ~810 year simulations (2 × 181 slots in `_slot_aligned_thermal_energy_kwh`). Expected ~−25…35 % cycle time; confirm with `EARNIE_CYCLE_TIMING=1`. Merged via PR #35 (`53e937f9`).

### EarlyStart P0 — always-on cycle duration + punctuality log (2026-10-15)

- [x] **EarlyStart P0 — always-on duration, event + punctuality recording** `[qual]` (epic **EarlyStart**; spec [`docs/spec/early-start-scheduling.md`](../docs/spec/early-start-scheduling.md) §5.1, §5.2, §5.6)
  - `runtime_store/cycle_duration_stats.py` → rolling `runtime/cycle_stats.jsonl` (7 d): tick, woke/start/writes-done/finish, wake/start delay, duration, `late_by_sec`, `on_time` (≤ 2 s), outcome (`ok` / `no_writes` / `error`), events, horizon slots, version, platform fingerprint (CPU, Python, solver; no hostname).
  - Event hooks: `pv_forecast_fetch`, `weather_fetch`, `price_feature_refresh`, `day_ahead_fetch` (network instead of cache) + `cold_start`.
  - `earnie.log`: one `Pünktlichkeit: …` line per regular cycle with 24 h / 7 d on-time rate and P95 lateness; out-of-band runs excluded.
  - Independent of the env-gated profiling (`runtime_store/cycle_timing.py`), which stays removable on its own. Not in P0 (moved to follow-ups): `will_refresh(at)`, MILP status.
  - Docs: `docs/einrichtung/betrieb.md` § Zyklus-Pünktlichkeit. Tests: `tests/test_cycle_duration_stats.py`.
  - Live check on NAS productive: `wake_delay_sec` should confirm the wait-loop drift bug (`Backlog-Bugfixes.md`).

### Regression P2 — customer data + intake (2026-10-15)

- [x] **Regression P2 — customer data:** `[qual]` private repo `JochenTCC/Earnie-regression-private` + `$EARNIE_REGRESSION_PRIVATE_DIR` (default sibling `..\Earnie-regression-private\cases`); missing private root reported as skipped (`private-root-missing`); public + private SHAs in `regression_report.md`.
  - `--intake` ZIP → private L1 case (`tests/regression/intake.py`): requires `--private`, `--id REG-<issue>-<slug>`, and `--seed-anchor` or `--cycle-index`; dump without `recorder/` fails loud; no `expected.json` (follow with `--update-golden`); case-local `recorder/`.
  - `resolve_recorder_root` prefers case-dir then `tests/regression/`; `archive_prod_dump.py` help points customer dumps to `--intake --private`.
  - Docs: spec v0.5; `docs/einrichtung/private-env.md` private-regression section; soft gate kept (hard CI = P3).
  - Tests: `tests/test_regression_intake.py`, loader skip coverage in `tests/test_regression_loader.py`.

### Regression P1 — MVP golden-master suite (2026-10-15)

- [x] **Regression P1 — MVP:** `[qual]` case format + schema, runner for L1 (cycle replay) and L2 (backtest window), `--update-golden`, markdown report; public cases (winter/autumn L1, negative prices L1, summer/EV/heat L2); prod_dumps as `L1-invariants` wrappers only (MILP goldens stay recorder/backtesting-shaped); tolerances and solver mode from R0 (`EARNIE_CBC_STRICT=1`, ±0.05 %); release-checklist item; privacy scrub on seed fixtures (address/geo/`cons_data` stub).
  - Runner: `scripts/run_regression.py`; package `tests/regression/` (loader, compare, L1/L2, prod-dump invariants); fixtures under `tests/regression/fixtures/`.
  - Pytest marker `regression` deselected by default in `tests/conftest.py` (`-m regression` or `EARNIE_RUN_REGRESSION=1`); entry `tests/regression/test_regression_suite.py`.
  - Spec [`docs/spec/regression-suite.md`](../docs/spec/regression-suite.md) v0.4; checklist [`docs/spec/release-checklist.md`](../docs/spec/release-checklist.md) §1.
  - Decisions: **1A** seed/backtesting cases now (live recorder refresh later); **2B** prod_dumps tier-1 only; keep `tests/test_prod_dump_regression.py`.

### Regression R0 — solver determinism / tolerance study (2026-10-14)

- [x] **Regression R0 — solver determinism / tolerance study (reduced scope for 2.7)** `[dev]` (epic **Regression**; after R-Rec; spec [`docs/spec/regression-suite.md`](../docs/spec/regression-suite.md) §16)
  - Offline replay: `runtime_store/recorder_replay.py` (config snapshot → prepare → MILP); study harness `scripts/run_regression_r0_study.py` (`--seed` / `--recorder-dir`).
  - Measured on 3× 96-slot recorder-format cases (HiGHS; production vs `EARNIE_CBC_STRICT`; idle vs parallel; 5 reps): Optimal groups bit-stable (plan hash + **0.0 %** cost spread). Cases were **historical `--seed`** (no live recorder yet) — backlog note: replace with live recorder cycles ASAP.
  - **Decision:** regression goldens use **`EARNIE_CBC_STRICT=1`**; default metric tolerance **±0.05 %**; pin **`highspy==1.15.1`** in `pyproject.toml`. Production-path sample + full §16 matrix remain follow-ups.
  - Test: `tests/test_recorder_replay.py`.

### Regression R-Rec — cycle recorder (2026-10-14)

- [x] **Regression R-Rec — cycle recorder (first)** `[qual]` (epic **Regression**; Version 2.7; spec [`docs/spec/regression-suite.md`](../docs/spec/regression-suite.md) §14)
  - Always-on production recorder: `runtime/recorder/cycles_YYYY-MM-DD.jsonl.gz`, config snapshots by hash, `recorder_enabled` (default on) / `recorder_retention_days` (default 7) in `local_settings.json`.
  - Capture immediately before `prepare_optimization_matrix` in `main.py`; finish with setpoints / plan hash / flags; soft-fail never aborts the live run.
  - Debug dumps (schema v3) auto-include the whole ring buffer under `recorder/` + optional `manifest.recorder`; dump dialog + `docs/einrichtung/betrieb.md` privacy/opt-out.
  - Module `runtime_store/cycle_recorder.py`; tests `tests/test_cycle_recorder.py` (incl. capture-point record → prepare replay).

### Bugfix — Chart1 powerstation SoC dips at Jetzt / hour boundary (2026-10-14)

- [x] **Chart1: powerstation SoC dips at Jetzt / next hour boundary** — fix implemented; **Verified live** (2026-10-14)
  - Symptom: physical + virtual PS SoC lines dipped toward house SoC at Jetzt and again at the next hour `:00` when Jetzt was in the last QH; overlapping virtual lines hard to tell apart.
  - Cause: per-ESS Jetzt / hour-end ramps anchored to primary `Simulierter SoC (%)` (`_soc_at_chart_now` / `_soc_tail_y_from_row`).
  - Fix: series-local anchors in `_milp_part_soc_ramps` / `_ramp_end_point`; virtual PS non-solid dash cycle.
  - Tests: `tests/test_chart1_multi_ess_soc.py` (`test_powerstation_soc_ramps_stay_on_own_series_not_house`).

### Document Review EcoFlow guide: Virtual Output placeholder (2026-10-14)

- [x] **`docs/einrichtung/ecoflow-delta3-loxone.md` prescribed `\v` in Virtual Output commands** `[dev]`
  - `\v` is the Virtual **Input** placeholder; in a Virtual Output it is sent as the control character 0x0B. Replaced with `<v>` in step 5 variant A (Miniserver self-write) and variant B (charge-limit webhook); removed the claim that `\v` matches the Earnie VO templates (they use `<v>`).
  - Step 6 variant B (bypass webhook): switched to a **digital** VO with fixed `?v=1` / `?v=0`, since an analog VO sends nothing at value 0 and the switch to grid would never reach HA.
  - Possible root cause of the open bug "Miniserver self-write of a Virtual Input is overwritten" — noted there for verification.
  - Variant B of steps 5 and 6 rewritten to match the bridge generator: random webhook id, `GET` + `local_only: true`, `is_number` guard (no silent 1500 W default), 50 W rounding, write only on change; VO hangs on F2 (W) instead of the `Earnie_LadeLeistungs-Limit` Merker (kW — old automation turned 1.5 kW into 100 W).
  - HA port: added how to find it (browser address; `/api/` → 401 = reachable, `ERR_CONNECTION_REFUSED` = wrong port), incl. installs on port 80 without `:8123`; same note in `ha-loxone-bridge.md`.

### Bugfix — Physical standby PS Chart1 SoC held flat (2026-10-14)

- [x] **SOC of Delta 3 Powerstation stayed constant in Chart1 despite wired `dev-pc` 0.1 kW 24/7** — fix implemented; **Verified live** (2026-10-14)
  - Cause (1): Chart1 held physical PS SoC (“Forecast gehalten”) and never applied the `standby_backup` island/charge plan.
  - Cause (2): `load_standby_packs` let flex consumers overwrite appliances, so `default_power_kw` was lost and a pack sizing hint (0.375 kW) was used instead of 0.1 kW.
  - Fix: resolve attached load from appliance/`default_power_kw` → recommendation → nominal; Chart1 advances physical standby SoC from the standby plan (`advance_physical_standby_soc_after_slot`); docs `docs/ui/charts.md`.
  - Tests: `tests/test_powerstation_2_7_h.py` (`test_attached_load_falls_back_to_nominal_not_sizing_hint`, `test_attached_load_uses_appliance_recommendation_nested`, `test_advance_physical_standby_soc_islands_then_charges`).

### Bugfix Haus Wärme over-request / Best-Effort HDD target (2026-10-14)

- [x] **Earnie requested much more heating energy than expected** — live verified (2026-10-14)
  - Symptom: Best-Effort warning `Haus Wärme: Ziel (25.57 kWh) … mit 37 h à 1.90 kW` while store was hot (T_eq above band_max) and Freigabe correctly stayed 0. (“37 h” was 37 QH slots → max deliverable ≈ 17.6 kWh.)
  - Cause: (1) Live remaining used full-calendar HDD sum, not store floor+opp; (2) space-heat climb pulled `C·ΔT` in one hour and emptied the buffer early; (3) Best-Effort warned on thermal_annual remaining even though delivery uses forced/day constraints.
  - Fix: `resolve_thermal_annual_horizon_kwh` Live+heat_storage → floor+opp; climb rate-limited to 0.1 K/h in `_space_heat_demand_kw`; skip Best-Effort for `thermal_annual`.
  - Tests: `tests/test_thermal_live_store.py` (`test_space_heat_climb_rate_limited_at_band_min`, `test_live_horizon_need_uses_floor_not_hdd`).

### Topology P2 + Powerstation AC wording (2026-10-14)

- [x] **Topology P2 — generator-side coverage in the live balance** `[qual]` (epic **Topology**; [`Plant-Topology-Conclusion.md`](Plant-Topology-Conclusion.md) §4)
  - Plant `sens_ess_power` = Σ grid-tied house `ess.{id}.sens_ess_power` (fail loud on missing binding); battery-less → `0`
  - Mapped plant PV + several grid-tied inverters with PV → complete `inv.*`/`pv.*` coverage or `plant.pv_covers_all_inverters: true`
  - Derived-load tolerance `plant.balance_tolerance_pct` / `balance_tolerance_w` (defaults 5 / 100 W); below floor → telemetry error
  - `pv_attribution._eta_inv` → `inverter_efficiency` (no 0.97 soft default)
  - Helpers in `integrations/plant_balance.py`; wired in Loxone / HA / OpenEMS / `ehal_live` / `loxone_live_power`; UI checkbox; `tests/test_topology_p2.py`
- [x] **Topology follow-up — Powerstation AC wording (`island`)** `[feat]`
  - Auto labels `Powerstation-WR …` (lifecycle / presets / migrate_inverters; existing stored labels unchanged)
  - UI + German user docs + `docs/spec/ehal.md` / `ehal-com.md`: Insel = bus participation, not off-grid

### Retire flat plant `sens_ess_soc` (2026-10-14)

- [x] **Remove `sens_ess_soc` from code as flat EHAL field** `[feat]` (full wire break; `EHAL_SCHEMA_VERSION` stays **4** — no public release since 3)
  - Plant telemetry / `EhalTelemetry` no longer require or accept flat SoC; SoC is entity-scoped only (`ess.{id}.sens_ess_soc`).
  - Adapters stop synthesizing plant SoC; `read_ess_soc` / `read_ess_soc_by_id` have no plant alias; bare push `/ehal/telemetry/sens_ess_soc/…` rejected.
  - Residual `plant.ehal_bindings.sens_ess_soc` fails loud (migrate hint); HouseSim golden maps + docs updated.

### Bugfix Shadow SoC Lesefehler via VO silence (2026-10-14)

- [x] **Shadow: feed-fresh `sens_ess_soc` became `Lesefehler` after ~30s**
  - Cause: inbox re-applied live VO silence (3×repeat) on shadow-feed rows that `lookup_record` already gated vs `cycle_ts`.
  - Fix: tag feed rows `source=shadow_feed`; `is_stale` skips silence for that source (`runtime_store/loxone_push_inbox.py`).
  - Tests: `tests/test_shadow_replay.py` (`test_shadow_soc_older_than_vo_silence_still_ok`).

### Bugfix Negative house_kw live snapshot → Automatik (2026-10-14)

- [x] **Negative `house_kw` live snapshot → Automatik instead of Entladesperre / missed Zwangsladen (08:00)** — verified live (2026-10-14); fix implemented 2026-10-11
  - Dump: `debug-dumps/debug_dump_20261011_082448` (meta: „Zwangsladen nicht ausgeführt um 8:00“); chart slot 08:00 `battery_forced_charge_missing`.
  - Symptom: at 07:52 optimizer wrote Automatik (`mode=0`, discharge limits open); 07:45–08:00 battery discharged; 08:00 mean charge only ~0.06 kW vs planned Zwangsladen 0.213 kW.
  - Cause: glitchy `house_kw=-0.04` → `baseload_kw=0` → live matrix overwrite zeroed `expected_p_act` → Entladesperre skipped → Automatik.
  - Fix: `reject_live_matrix_snapshot_reason` (`negative_house` / `all_zero`) keeps forecast in `main.py` + UI opt-in.
  - Tests: `tests/test_live_consumption.py` (`test_reject_live_matrix_snapshot_negative_house`).

### Bugfix Wechselrichter auto-create on open (2026-10-14)

- [x] **Wechselrichter subpage auto-created default WR on open**
  - Cause: selectbox defaulted to `— neu —` when session unset; `auto_persist` wrote `Haupt-Wechselrichter N`.
  - Fix: `_initial_inv_index` / `_inv_selectbox` prefer first existing inverter (index 1) on first open (`ui/planning_inverter_form.py`).

### Topology P1 — root assertion + regulates_on (2026-10-12)

- [x] **Topology P1 — explicit root, regulator declaration, validation** `[feat]` (epic **Topology**; decision [`Plant-Topology-Conclusion.md`](Plant-Topology-Conclusion.md))
  - Design pack: theses / Claude+Grok reviews / conclusion; epic phases P1–P5 in [`Backlog.md`](Backlog.md); nomenclature in `roadmap-nomenclature.mdc`
  - `plant.grid_meter` (`at_house_connection`, `single_tariff`) required `true` on live path; `batteries[].regulates_on` (`grid` | `none`); optional `inverters[].regulates_on`
  - One-shot `scripts.migrate_topology_once` + fail-fast loader; live validation (≤1 loop at root; ≤1 grid-tied house battery until P3+P4); reject battery on `pv_string` inverter
  - UI (profile / battery / plant), German `docs/konfiguration/batterie-pv.md` (three questions), spec § Plant topology in `docs/spec/ehal.md`
  - Tests: `tests/test_topology_p1.py`

### Inverter follow-ups — η split + live PV attribution (2026-10-12)

- [x] Design note [`docs/spec/conversion-losses.md`](../docs/spec/conversion-losses.md) `[feat]`
- [x] Schema + MILP/sim `η_inv` / `η_batt` + migration of lumped `battery_efficiency` (AC-path only in v1; `scripts.migrate_conversion_efficiency_once`) `[feat]`
- [x] Multi-inverter live attribution of `sens_pv_production_active` + first `pv.{pv_system_id}.*` (derive plant from Σ grid-tied inv · η_inv; fail-loud partial maps; curtailment stays forecast) `[feat]`
- Open remain in [`Backlog.md`](Backlog.md): curtailment live weights; device catalog deferred

### Shadow R4 — Feed gaps / ENTSO-E (2026-10-12)

- [x] **Shadow R4 — Feed gaps:** `[dev]` ENTSO-E record/replay (`ext:prices:entsoe`); S4 Soll/Soll stays **2.+1**
  - Family-B `ext_get`/`safe_record` in `integrations/entsoe_client.py`; raw A44 XML payload; no token in feed
  - Inventory: Energy-Charts / aWATTar / outdoor / PV already covered (R3); no other live `ext:*` gaps
  - Tests: Prod record, Shadow replay hit, Shadow miss live-fallback unrecorded (`tests/test_entsoe_client.py`)
  - Docs: spec §5.2 / §11.1; review §3 R4 / §6
  - Deferred (not R4): S4; would-write old-vs-new; silent `status.json` publish gate

### Shadow R3 — Transport intercept (2026-10-12)

- [x] **Shadow R3 — Transport intercept** `[dev]`
  - Shared helpers: `runtime_store/shadow/transport.py` (`safe_record`, `hub_get`, `ext_get`); rewrote HA / OpenEMS / aWATTar / outdoor / energy_charts / PV call sites (Loxone push left asymmetric)
  - `assert_not_shadow_backend` on MCP, greenfield import, Loxone HTTP probe, HA `list_mappable_entities`, `scan_structure`
  - Daemon orchestration: `runtime_store/shadow/daemon.py`; thin wiring in `main.py`
  - Docs: `DEVELOPER.md` transport convention; spec §11.1 R3 done; review §3 R3
  - Tests: `tests/test_shadow_transport.py`, `tests/test_shadow_daemon.py`, probe asserts in `test_shadow_replay.py`
  - Open remain were **R4** (→ archive above); S4 stays **2.+1**

### Shadow R2 — Single Loxone input contract (2026-10-12)

- [x] **Shadow R2 — Single Loxone input contract** `[dev]` (hard cut)
  - Prod `meta.json` advertises `loxone_feed: "push"` when `ehal_backend` is Loxone (`runtime_store/shadow/feed.py`)
  - Shadow startup refuses Loxone feeds without that capability (`runtime_store/shadow/startup.py`)
  - Deleted Prod-inbox file fallback / path sniff; Shadow VO reads are feed-only (`runtime_store/loxone_push_inbox.py`); Merker-superset stays no-op
  - Spec / docs: [`docs/dev/shadow-mode.md`](../docs/dev/shadow-mode.md) §5.3 / §5.4 / §11.1 / §12; [`docs/einrichtung/betrieb.md`](../docs/einrichtung/betrieb.md); review §3 R2
  - Tests: capability + startup refuse; feed-miss ignores Prod inbox; keep push→feed / `test_superset_loxone_is_noop`
  - Open remain were **R3–R4** (R3 → archive above)

### Shadow R1 — Policy façade (2026-10-12)

- [x] **Shadow R1 — Policy façade** `[dev]` (behavior-preserving)
  - Landed `is_shadow_config_readonly()` (shared feed → RO; external feed → private writable) + VO push → `loxone:io:*` feed with Prod-inbox fallback (compat until R2)
  - Gate checklist in `DEVELOPER.md`; call-site audit in [`Shadow-Architecture-Review.md`](Shadow-Architecture-Review.md) §3 R1 (no wrong-gate fixes needed)
  - No new helpers; R2–R4 archived above (same day)

### 2.7.l — Inverter entity P1–P5 (2026-10-12)

- [x] **2.7.l — Inverter entity (PV × battery topology)** `[feat]` (epic **Inverter**; draft [`EHAL-Inverter-Draft.md`](EHAL-Inverter-Draft.md))
  - Model: `inverters[]` in `components.json`; PV/batteries reference via `inverter_id` (n:1); scenario keeps `pv_system_ids[]` / `battery_ids[]` (no `inverter_ids[]`)
  - `type` `hybrid` | `pv_string` | `battery`; caps `max_ac_power_kw` / `max_pv_input_kw` / `max_ac_charge_kw`; `control`; `ac_connection` `grid_tied` | `island` (replaces `batteries[].kind` / Topologie)
  - Built-in inverter: `owned_by` battery (UI/lifecycle); virtual PS none; physical PS owned `island`; EHAL role optional `inv.{id}.*`
  - Data model stays `earnie_data_model` **4**; structural fail-fast + one-off `scripts/migrate_inverters_once.py` (no permanent loader shim)
- [x] **Inverter P1 — schema + resolution:** `[feat]` `components.schema.json`, `inverter_id`, `entity_resolution` (`_planning_inverters`, validation), migrate + fail-fast, tests (`tests/test_inverter_p1.py`)
- [x] **Inverter P2 — UI + docs:** `[feat]` house-configurator inverter editor, PV/battery selects, built-in section + presets, remove Topologie; German `docs/konfiguration/batterie-pv.md`; `entity_id_lock` from day one
- [x] **Inverter P3 — MILP:** `[feat]` per-inverter PV node, AC/DC clipping, grid-charge rules, island outside house balance (`optimizer/milp_inverter.py`); efficiency deferred to follow-ups
- [x] **Inverter P4 — EHAL:** `[feat]` role `share/ehal/roles/inverter.json`, Live/mapping, HA/Loxone/OpenEMS, export-limit unconstrained per inverter, `qualified_inverter_id()`, docs `ehal.md` / `ehal-com.md`
- [x] **Inverter P5 — curtailment write:** `[feat]` `inv.{id}.set_inv_ac_power_limit` from plant `p_pv_curtail[t0]` (`optimizer/inv_ac_power_limit.py`, `write_inv_ac_limits_from_plan`); sticky rating release when no curtail
- Open remain were Inverter follow-ups (η + live PV attribution → archive above; curtailment weights still open); device catalog deferred

### Shadow architecture review — proposal (2026-10-12)

- [x] Review entire Shadow architecture after 2.7 changes and propose refactoring (attention: post-commit bugfixes) `[dev]`
  - Verdict: S1–S3 match the spec; debt is call-site scatter + Prod-inbox fallback compat — not a broken core
  - Classification: keep push-only Loxone feed, `is_shadow_config_readonly` (shared vs private), `should_invoke_setpoint_writes`; retire inbox-file fallback only after R2 capability gate; do not revive Merker-superset
  - Proposal: **R1–R4** in [`Shadow-Architecture-Review.md`](Shadow-Architecture-Review.md); locked in [`docs/dev/shadow-mode.md`](../docs/dev/shadow-mode.md) §11.1 / §12
  - Proposal-only at the time; R1–R4 implemented and archived above (2026-10-12)

### Thermal Wärmeinhalt — latest-12 forecast fan (2026-10-11)

- [x] **Improve chart for thermal simulation** `[feat]` — Analyse Verbrauch & Kosten Wärmeinhalt: keep Sim/Ist; overlay latest 12 hourly Q-forecast lines (`horizon_q_sim_kwh`) for heat storage + pools; common horizon ≤ 24 h
  - Persist pool/thermal_control `horizon_q_sim_kwh` in `optimizer/thermal_targets.py`; heat storage already had it via `thermal_live_store`
  - Loader + Plotly fan: `ui/consumption_display/heat_content_history.py`, `charts.py`, `page_consumer_analysis.py`
  - Docs: `docs/konfiguration/waermespeicher-schichtung-teq.md`, `docs/ui/charts.md`, `docs/spec/thermals-p2.md`

### Time-dependent Netznutzung Arbeitspreis SNAP / WiNAP (2026-10-11)

- [x] **Time-variable grid fee (Netznutzung Arbeitspreis)** `[feat]` — Austria SNAP/WiNAP catalog + profile `netznutzung` object (PR [#32](https://github.com/JochenTCC/Earnie/pull/32))
  - `data/grid_fees.py` + `share/config/grid_fees.json` (areas / rule sets); migrate `scripts/migrate_grid_fee_profile.py`
  - Pricing / SE / invoice use resolved per-slot fees; house-profile UI + `house_profiles.schema.json`
  - Later (still open elsewhere): Leistungspreis / import cap — see Leistungstarif Entwicklungsdokument L1→L5

### Push before 2.7.l inverter (2026-10-11)

- [x] Push `main` (and site pack tag) before starting **2.7.l** inverter — tag `2.7.0-dev.49` (no GHCR publish) `[feat]`

### 2.7.r — HA live I/O contract / Binding P5 transport (2026-10-11)

- [x] **T1 — Contract & transport switch:** `[feat]` Single Earnie↔HA I/O story in `docs/spec/ehal.md` and user docs; config `ehal.ha.transport` (`pull`|`push`, default `pull`) via `runtime_store/ehal_setup.py` / `settings/config_loaders.py`; canonical `GET /ehal/status.json` with `/ehal/loxone/status.json` alias (`integrations/loxone_status_json.py`); HA push telemetry on the wire in canonical EHAL units (W/kWh/%/A; carrier converts in HA).
- [x] **T2 — HA → Earnie push read:** `[feat]` With `transport=push`, `integrations/ha_adapter.py` reads activated fields from the push inbox (`integrations/ha_push_read.py`, `runtime_store/loxone_push_inbox.py`); REST is fenced for push-covered fields; missing/stale push fails loud (no pull fallback).
- [x] **T3 — Earnie → HA via status.json:** `[feat]` Setpoints published to the status ledger for push; service-call writes skipped for covered fields (`integrations/ehal_live.py`); `ha_ess_force`/Huawei paths remain REST exceptions.
- [x] **T4 — Minimal carrier YAML + lab:** `[feat]` `scripts/ha_carrier_yaml_gen.py` + `integrations/ha_carrier_yaml.py`, example `share/config/ehal.ha.snippet.json`, lab checklist in `docs/dev/ha-lab-setup.md` §9 (not Add-on / full Binding P5 comfort).

### Rename Pattern B → entity-scoped bindings (2026-10-11)

- [x] Chosen term **entity-scoped bindings** (replacing internal name Pattern B); wire shapes unchanged (`ess.{slug}.*`, `flex.{slug}.*`, qualified exchange IDs) `[feat]`
- [x] Python API renames (`parse_ess_entity_scoped`, `is_ess_entity_scoped_field`, `entity_scoped_battery_bindings`, `ha_entity_scoped_live_mapping`, `_ENTITY_SCOPED`, `_write_entity_scoped_probes`, …) `[feat]`
- [x] Docs, spec, user docs, share templates, backlog notes, and `.cursor` rules/skills updated to entity-scoped prose `[feat]`
- [x] Historical release notes, packaging changelogs, and `.cursor/plans` left unchanged `[feat]`

### Binding P5 — Telemetry path rename (2026-10-11)

- [x] **Binding P5 path rename:** `[feat]` canonical `/ehal/telemetry/…`; keep `/ehal/loxone/telemetry/…` as alias for deployed VOs
  - Receiver: `integrations/loxone_request_http.py` (`match_telemetry_prefix`, dual strip)
  - Emitters: `scripts/pilot_vo_template_gen.py` + `share/loxone/templates/VirtualOut/VO_Earnie_*.xml`
  - Docs: `docs/einrichtung/loxone-anbindung.md`, `docs/referenz/loxone-signals.md`, `docs/ui/ehal-com.md`, templates README
  - Tests: `tests/test_loxone_push_inbox.py`, `test_pilot_vo_template_gen.py`, `test_loxone_vo_template_shape.py`

### Retire LOXONE_* plant loud names, loxone_blocks migrate, plant-flat ESS merge (2026-10-11)

- [x] Removed all `LOXONE_*` plant loud-name config slots (`load_loxone_block_params` / `_LOXONE_BLOCK_ATTRS`) — reads and writes `[dev]`
- [x] ESS writes/reads resolve primary-battery entity-scoped via `house_config.ess_bindings.resolve_primary_ess_binding`; plant non-ESS via `resolve_plant_binding` `[dev]`
- [x] Retired `merge_ess_bindings_into_plant` plant-flat ESS alias merge; HA aggregate keeps plant-stored flat ESS until `migrate_ess_bindings_once` when batteries exist `[dev]`
- [x] `ensure_migrated` refuses non-empty `loxone_blocks` (CLI `scripts/migrate_ehal_bindings.py` migrates explicitly); refuses residual plant-flat ESS when mappable batteries exist `[dev]`
- [x] Docs/schema/tests updated (`docs/spec/ehal.md`, `share/config/config.schema.json`) `[dev]`

### SH concentration Phases A–D (2026-10-11)

- [x] **Phase A** `[feat]` — Named ops in `integrations/ehal_live_ops.py`, re-exported from `ehal_live` (`read_generic_value`, flex live/write, `read_absent_mode`, `publish_setpoint_traced`, …); `load_default_house_profiles_doc` in `house_config/profiles_store.py`.
- [x] **Phase B** `[feat]` — `main.py`, `optimizer/*`, `data/*`, `runtime_store/power_interval_sampler.py` use `ehal_live` (no `loxone_client` / `loxone_writes` imports).
- [x] **Phase C** `[feat]` — Production import ban outside `integrations/` (`tests/test_no_loxone_client_outside_integrations.py`); UI/settings/scripts migrated; CONTRIBUTING updated.
- [x] **Phase D** `[feat]` — Canonical backend flags on `ehal_live`; UI debug uses them; `config.is_ehal_*` wrappers removed.
- Review: [`SH-Backend-Concentration-Review.md`](SH-Backend-Concentration-Review.md). Binding P5 path rename → done (see section above).

### EHAL / SH-backend cleanup — concentration review, binding rollback, Loxone-agnostic naming (2026-10-11)

- [x] **SH-Backend communication concentration — review** `[dev]` — Findings: [`SH-Backend-Concentration-Review.md`](SH-Backend-Concentration-Review.md). Façade `ehal_live.get_adapter()` already exists; scatter documented; Phases A–D implemented (see section above).
- [x] **Remove Binding rollback legacy** `[dev]` — Dead Merker HTTP write (`_send_loxone_value_traced` / `send_loxone_value`); deprecated push-entity stubs; unused `ui/loxone_marker_forms.py` + `ui/smarthome_marker_fields.py` (moved `assemble_filter_bindings` to `house_config/ehal_bindings.py`); reverse `loxone_blocks` helpers; legacy `ascii_title`; non-`_v2` `VI_Earnie_*.xml`; doc scrub (dual-emit / Q5 rollback / Merker-HTTP drift); Binding walkthroughs marked STALE. Follow-up done: `LOXONE_*` loud names / `loxone_blocks` migrate / plant-flat ESS merge retired (see section above).
- [x] **EHAL naming Loxone-agnostic (hub-agnostic layer)** `[dev]` — `TELEMETRY_OPTIONAL_STATIC_HUB` / `STATIC_HUB_MAP_FIELDS` (+ temporary aliases); docs/schema/UI reword (Merker → binding/hub channel; sticky hubs; Smarthome-Binding); role JSON `"loxone"` + `apply_loxone_*` unchanged. Follow-up Binding P5 path rename → done (see section above); SH concentration A–D done.

### EHAL Loxone vs HA mapping review (2026-10-11)

- [x] Code review comparing EHAL field mapping / binding for Loxone and HA (similarities, duplications, reuse) `[dev]`
  - Findings: [EHAL-Mapping-Review.md](EHAL-Mapping-Review.md)
  - Safe unification: hub-agnostic membership catalogs in `ehal/field_catalog.py`; adapters/UI import shared tuples
  - Transport, unit conversion, Live-Lesen catalogs, HITL UIs, and Loxone read-loop membership stay separate
  - Tests: `tests/test_ehal_field_catalog.py`

### Bugfix — Sidebar logo, Monitor main.py status, log backlog IDs (2026-10-11)

- [x] **Earnie logo disappeared in Sidebar** — logos lived under `docs/assets/` (excluded by `.dockerignore`); silent skip when missing. Ship under `ui/assets/` + `ui/branding.py` path. Tests: `tests/test_branding.py`.
- [x] **Don't show "main.py nicht aktiv" while main.py is optimizing** — `main_down` after 30 s without slot `completed_at` ignored process liveness. `live_simulation_readiness(..., daemon_alive=)` stays `wait_main` when `main_daemon.status()` is running. Tests: `test_wait_main_when_daemon_alive_after_max_wait`.
- [x] **Remove backlog chapter IDs from Earnie logs** — stripped `2.7.h` / `2.7.g/h` prefixes from 8 logger strings in `main.py`, `optimizer/powerstation_live.py`, `optimizer/powerstation_standby.py`.

### Remove remaining `/jdev/sps/io` Merker HTTP (2026-10-11)

- [x] **No `/jdev/sps/io` in production Python** `[dev]` — inventory + removal after 2.7.o/q push-only
  - Dead `/all` AlarmClock path removed (`_fetch_loxone_io_all`, Tna helpers)
  - Live reads fail-closed on VO push inbox; shadow Loxone superset is a no-op
  - Greenfield/structure/UI presence = LoxAPP3 control-name membership (no Merker ping)
  - Deleted `fetch_loxone_raw_value` / `_loxone_jdev_url`; docs scrubbed (`loxone-anbindung`, `loxone-signals`, `ehal.md`)
  - External HA→Loxone YAML examples in EcoFlow guide may still show Miniserver write URLs (not Earnie Core)

### Bugfix — Q8 bare EHAL IDs Merker-polled (shadow feed 404) (2026-10-11)

- [x] **debug_dump_20261011_064913 — charge limits + Loxone 404 on bare EHAL IDs**
  - Symptom: “Falsche Interpretation der Lade-Limits”; earnie.log 404 on `/jdev/sps/io/sens_ess_power` (and other bare `sens_ess_*` / `set_ess_*`).
  - Units: Loxone hub must send **kW** (5, not 5000 W). Live-Lesen/Schreiben 5 kW ↔ 5000 W OK after operator Merker fix (not a leftover Earnie `*1000`).
  - 404 cause: Q8 empty-Merker → `LOXONE_*` = bare EHAL IDs; with **`shadow_feed_enabled: true`** (not Shadow Mode) after-cycle `superset` Merker-polled them. Earlier VO-title poll fix did not cover EHAL activation IDs.
  - Fix: skip EHAL exchange IDs in `_superset_loxone`; refuse them in `fetch_loxone_raw_value`.
  - Tests: `test_superset_loxone_skips_q8_ehal_activation_ids`, `test_fetch_loxone_raw_value_refuses_ehal_exchange_ids`
  - Verified on NAS productive (operator, 2026-10-11)

### Bugfix — Q8 empty grid bindings → Live-Lesen Merker-Poll (2026-10-10)

- [x] **EHAL binding mismatch** — `grid.meter.sens_grid_power_active` / `get_grid_export_power_limit` showed `Kein Push-Inbox-Wert (Merker-Poll entfernt)` while empty plant activation and energy counters worked
  - Cause: Q8 empty Merker fallback returned bare field IDs; push inbox / ehal index use `grid.meter.*`
  - Fix: `resolve_plant_binding` empty activation → `qualified_plant_id`; `resolve_push_binding` maps bare `GRID_KINDS` → exchange ID
  - Tests: `test_empty_grid_read_activation_resolves_qualified_exchange_id`, `test_empty_grid_activation_collects_qualified_io`
  - Verified on NAS productive Live-Lesen (operator)

### Shadow recorder + client regression check (2026-10-10)

- [x] Review code for shadow functionality on host and client side `[dev]`
  - Suite green: 84 passed (`tests/test_shadow_*.py`, `test_auto_persist_shadow`, `test_local_settings`, `test_loxone_write_characterization`)
  - Wiring still intact after **2.7.n** / **2.7.q** (record/replay, push-only write block, listener off, config RO, release guard)
  - Dogfood gaps noted (not fixed): ENTSO-E not in feed; push-only sensors skipped by design; a few structure probes without `assert_not_shadow_backend`
  - Deferred unchanged: S4 Soll/Soll + offline JSONL (**2.+1**); would-write old-vs-new; silent `status.json` publish gate

### EHAL-Com — units, raw↔converted, Live-Lesen readability (2026-10-10)

- [x] **EHAL-Com — units, raw↔converted, Live-Lesen readability** `[feat]` (follow-up to EHAL unit conversion registry)
  - **Phase A:** shared `ui/ehal_unit_display.py` (registry / `ha_units` only); Signalliste **Hub-Einheit** / **EHAL-Einheit**; Live-Lesen **Wert (EHAL)** + unit suffixes; Live-Schreiben **Wert (Hub)** with Loxone hub-trace normalized to EHAL; same headers on all backends (`—` when no path); `docs/ui/ehal-com.md`
  - **Phase B:** Pandas Styler row colours (optional gray / cached blue / stale yellow / error red) + optional empty-row fallback hint; Status text remains authoritative
  - Tests: `tests/test_ehal_unit_display.py`, Signalliste + Live row assertions

### Q8 — Clear Loxone Merker names + write activation by key presence (2026-10-10)

- [x] Remove remaining Merker name values from `ehal_bindings` (keep keys as activation flags) or mark code still needing Merker poll / non-empty HA entity_ids `[feat]`
  - Write resolvers: key presence → qualified EHAL ID (`settings/ehal_marker_resolve.py`, `resolve_plant_binding` for `set_*`, `_binding_for_ps`); adapter publish allows empty display Merker
  - `clear_loxone_binding_names_in_house` also clears list-shaped `profiles` (was dict-only)
  - Cleared Earnie-env-home `house_profiles.json` / `components.json` + `share/config/house_profiles.example.json`
  - Marked intentional Merker polls (structure/greenfield); `docs/spec/ehal.md` Q8 note; HA entity_ids remain until Binding P5
  - Tests: `tests/test_clear_loxone_binding_names.py`

### `set_ess_source_select` → entity-scoped `ess.<id>.*` (2026-10-10)

- [x] **`set_ess_source_select` → entity-scoped `ess.<id>.set_ess_source_select`** `[feat]` (follow-up to **2.7.h** / **2.7.m**)
  - Quellenwahl is a physical `standby_backup` capability only — not plant / house ESS.
  - Removed plant `ehal_bindings` / plant-flat remap (`_PLANT_FLAT_ALLOWED_KINDS`); `status.json` / Live-Schreiben / Signalliste use `ess.<id>.set_ess_source_select`.
  - One-off migrate: `migrate_plant_source_select_to_standby` + phase 2 in `scripts/migrate_ess_bindings_once.py`.
  - Docs: `docs/spec/ehal.md`, `docs/ui/ehal-com.md`, `docs/konfiguration/batterie-pv.md`, EcoFlow guide, `docs/referenz/loxone-signals.md`; plant VI templates drop flat Quellenwahl.
  - **Out of scope:** Loxone ↔ HA EcoFlow bypass bridge rewire (operator). Productive **2.7.h** dogfood remains under [Bugfixes](Backlog-Bugfixes.md) until that rewire + live acceptance.

### Optimierer-Dienst — earnie.log auto-refresh + Gehe nach Oben (2026-10-10)

- [x] Make an automatic update every 10 sec on page Optimierer-Dienst for the display on earnie.log `[feat]`
  - [x] Add a "Gehe nach Oben" button near the "Aktualisieren" button at the lower end
  - `@st.fragment(run_every=10s)` for log body; expander keyed `daemon_log_expander`; scroll via `st.html` to `#daemon-log-top`
  - Docs: `docs/einrichtung/betrieb.md`, handbook; AppTest: `tests/apptest/test_page_daemon_apptest.py`

### Monitor Chart1 — multi-battery + virtual PS SoC lines (2026-10-10)

- [x] Add additional SOC lines in chart1 of Monitor page for all batteries and also virtual powerstations `[feat]`
  - Different greens via `soc_color_for_index`; very slim lines for virtual powerstation SoCs (`VIRTUAL_SOC_LINE_WIDTH`)
  - Entities: house ESS + physical PS + virtual PS; virtual `% = stored_kwh / capacity`; forecast from house battery-plan attribution (mirror of reserve advance)
  - `optimizer/powerstation_soc_chart.py`; history `soc_percent_by_ess` includes virtual; docs `docs/ui/charts.md`; tests `test_powerstation_soc_chart.py`, `test_chart1_multi_ess_soc.py`

### Bugfix — Silent `loxone_sent` omitted physical powerstation setpoints (2026-10-10)

- [x] **Loxone: silent `loxone_sent` omitted physical powerstation setpoints** — fix implemented (2026-10-09); **Verified live** (2026-10-10, NAS productive Silent cycle `request_optimize` @ `13:11:25`)
  - Loud `loxone_writes` merge was already done (Erledigt 2026-10-07). Remaining gap: Silent Live-Schreiben / watchdog Soll from `loxone_sent`.
  - Fix: `planned_powerstation_loxone_sent` in `optimizer/powerstation_live.py` (Merker → wire, no publish); `main.py` merges into `loxone_sent` after `build_sent_loxone_snapshot`. Does not update `_last_powerstation_sent` in silent.
  - Tests: `tests/test_powerstation_2_7_h.py`, `tests/test_main_loxone_writes.py`, `tests/test_loxone_debug.py`.
  - Live: `silent_mode=true`, `loxone_writes` empty, all four `Earnie_Delta3_*` setpoints present in `loxone_sent` (`0.0`). Loud restored after acceptance.

### Bugfix — Loxone `status.json` powerstation keys vs house battery flats (2026-10-10)

- [x] **Loxone `status.json`: physical powerstation limits overwrote the house battery's flat keys** — fix on `main` (commit `b5a658d2` via `fix/status-json-powerstation-keys`); **Verified live** (2026-10-10, NAS productive `192.168.178.35:8541`)
  - Cause: `_write_powerstation_loxone` cached under flat field kinds; `build_loxone_status_payload` wrote into house flat keys (last write won). VI Pattern-B Checks never got data.
  - Fix: cache/emit entity-scoped `ess.<id>.<kind>`; only shared `set_ess_source_select` stays plant-flat. Tests in `tests/test_loxone_status_json.py` / `tests/test_powerstation_2_7_h.py`.
  - Live: `status.json` keeps house flats (`set_ess_charge_power_limit=5.0`, …) beside `ess.15_kwh_speicher.*` and `ess.ecoflow_delta_3.*`; flat `set_ess_source_select` present. Miniserver VIs are Pattern-B titled (`ess.ecoflow_delta_3.set_ess_charge_power_limit`, …); legacy `Earnie_Delta3_*` / bare flat Merker names 404. House VI `5.000 kW` matches status (no DestValHigh sign invert). EHAL-Com Schreibtest published `ess.ecoflow_delta_3.set_ess_charge_power_limit=1000.0` with Miniserver fetch ack; house flats stayed at 5.0 (no overwrite).

### Bugfix — Physical powerstation ESS writes plant-flat fallback (2026-10-10)

- [x] **Physical powerstation ESS writes fall back to the house battery's plant-flat entity** — fix implemented (2026-10-06); **Verified live** (2026-10-10, NAS productive; Loxone hub units for max charge/discharge corrected to kW)
  - `optimizer/powerstation_live.py`: no plant-flat remap for charge/discharge (HA + Loxone); explicit exception only for `set_ess_source_select` (EcoFlow bridge — to be removed when Quellenwahl is entity-scoped); missing binding → skip + `runtime/ehal_write_error.json`
  - Docs: `docs/konfiguration/batterie-pv.md`; regression: `tests/test_powerstation_2_7_h.py` (`test_ha_charge_does_not_remap_to_house_battery`, Loxone charge isolation, HA source_select plant-flat)
  - Follow-up (feature): EHAL-Com Signalliste expected units + Live-Lesen/Schreiben raw vs converted columns → [Backlog.md](Backlog.md) Version 2.7

### EHAL unit conversion — no hardcoding (write registry + hub audit) (2026-10-10)

- [x] **EHAL unit conversion — no hardcoding (all backends, read + write):** `[feat]` After **2.7.n Session F** (Loxone **read** registry), finish writes + remaining hubs so adapters never embed `* 1000` / `/ 1000` / ad-hoc sign flips per field.
  - **Loxone write:** setpoint `loxone` blocks on `set_ess_active_power` / charge+discharge limits / `set_grid_export_power_limit` in `share/ehal/roles/{ess,grid}.json`; `apply_loxone_write` / `require_loxone_write` in `ehal/field_registry.py`; adapter + powerstation + Schreibtest driven from registry; retired `ehal_*_w_to_loxone_kw` and battery-read `*1000` fallbacks.
  - **HA:** runtime conversion only via `integrations/ha_units.py`; removed dead `parse_ha_numeric_state` hardcode.
  - **OpenEMS:** optional `openems` polarity blocks + `apply_openems_read` / `apply_openems_write`; adapter helpers delegate to registry.
  - Schema/docs/rule: `device_roles.schema.json`, `docs/spec/ehal.md`, `.cursor/rules/ehal-unit-conversion.mdc`. Tests: `test_field_registry`, Loxone/HA/OpenEMS adapter + write suites green.

### 2.7.n Session F — Field registry + generic Loxone read (2026-10-10)

- [x] **2.7.n — Binding 1.0: stable identifiers + generic EHAL read path** `[feat]` (slice of epic **Binding**; write side + Signal list = archived **2.7.q**): Sessions A–F complete. Identifier contract frozen (`ehal/qualified_ids.py`); Loxone **read** conversion data-driven. Full Binding tools (HA, import hardening, Kennung cascade) stay in **2.+1** (P4–P6).
- [x] **Session F — 2.7.n-5 field registry + generic Loxone read:** `[feat]` nested `loxone` blocks on read fields in `share/ehal/roles/{grid,pv,ess}.json` + `device_roles.schema.json` (unit / ehal_unit / factor / sign / clamp / `omit_if` / `read_required`); `ehal/field_registry.py`; `LoxoneAdapter.read_telemetry` inbox by qualified ID → registry convert → required/optional; `LoxoneConfig` read Merker fields removed; per-battery SoC via `qualified_battery_id`; unbound EHAL IDs push-only (no Merker poll). Scope: Loxone only. Characterization (`tests/test_loxone_read_characterization.py`) + `tests/test_field_registry.py` green. Spec: `docs/spec/ehal.md` units table + Loxone registry note.
  - **Decided (namespaces):** `ess`, `evcs`, `ev`, `inv`, `grid` (`grid.meter.*`), `heatpump`, `pool`, `consumer`; plant house-wide / PV bare until deferred `pv.*`; storage may still hold `flex.{slug}.*` / bare grid keys.
  - **Decided:** `ev.` + `evcs.`; `sens_evcs_connected` not renamed in 2.7.n. Write conversion registry → archived **EHAL unit conversion — no hardcoding** (2026-10-10).

### 2.7.n Session E — Read characterization extend (2026-10-10)

- [x] **Session E — 2.7.n-4 characterization extend** `[dev]` (gate for F): extended `tests/test_loxone_read_characterization.py` with optional ESS `get_*` (clamp / kW→W / omit), per-battery SoC via `read_ess_soc_by_id` (entity-scoped address, secondary refuse, primary plant alias), and push-inbox composition (missing/stale required → `LoxoneAdapterError`; optional omit). Baseline kW→W / clamps / required missing / export-limit omit kept. Write half = **2.7.q Q1** (already done). Must stay green through Session F.

### 2.7.n Session D — Wire cleanup export limit (2026-10-10)

- [x] **Session D — 2.7.n-2a wire cleanup** `[feat]`: loud write / `status.json` / stock VI emit `grid.meter.set_grid_export_power_limit` (align Live-Schreiben / Pilot VI). Plant bindings stay bare (`plant.ehal_bindings.set_grid_export_power_limit`). Schreibtest probe ID + merge of stale bare ledger → qualified wire key. Deferred: PV namespace; kind rename to `set_export_power_limit`.

### 2.7.n Session C — Kennung lock for consumers / EVs (2026-10-10)

- [x] **Session C — 2.7.n-3 Kennung lock for consumers / EVs** `[feat]` (Binding P6 core): lock-on-first-change via `house_config/entity_id_lock.py` on consumer/EV upsert paths (same pattern as battery/PV). Full “Kennung ändern” cascade + alias/rewrite stays in 2.+1 / Binding P6. **Decided (P0c):** alias table **yes** — see [`Binding-P0c-Inventory.md`](Binding-P0c-Inventory.md).

### Binding P0c — Entity-id persistence inventory (2026-10-10)

- [x] **Session B — Binding P0c spike** `[dev]` (**2.7.n**): inventory which persisted files key by house-config entity id (history, run_state, shadow, dumps, fixtures).
  - Deliverable: [`Binding-P0c-Inventory.md`](Binding-P0c-Inventory.md).
  - **Alias table: yes** — alias-on-read for `optimization_history.jsonl` (+ archives); rewrite-on-rename for small live runtime files (flex state, reserves, schedules, sampler, run_state, shadow overlay, `ehal_published`, push inbox, cons_data/profile CSVs); dumps/fixtures out of runtime alias scope (re-record).
  - No separate immutable `uid`. Unblocks Session C (alias required when Kennung cascade lands) and Inverter P1 (no history alias for inverter migration; battery renames still need the path above).

### Bugfix — Retire remaining Loxone Merker poll reads (2026-10-09)

- [x] **Retire remaining Loxone Merker poll reads** (**2.7.n Session A**) — fix implemented (2026-10-09); **Verified live** (2026-10-09)
  - Gap after archived **2.7.o** / **2.7.q**: optimize Merker-polled VO-only titles (e.g. `Earnie_EAuto_MaxStrom` → 404 every cycle).
  - Fix: `resolve_consumer_nominal_power_kw` / `resolve_consumer_battery_capacity_kwh` → `fetch_loxone_generic_value` (push inbox); shadow `_superset_loxone` skips pushable bindings; Live-check `read_raw` no longer Merker-polls; docstring + `docs/referenz/loxone-signals.md` note intentional poll exceptions.
  - Tests: `tests/test_loxone_client.py`, `tests/test_loxone_push_source.py` (`test_ev_nominal_and_capacity_use_inbox_not_merker`), `tests/test_shadow_feed.py` (`test_superset_loxone_skips_pushable_bindings`).
  - Commit `3ad9ede4` (`v2.7.0-dev.33`); alpha logs free of MaxStrom-style 404s.

### Powerstation savings study 2025 (2026-10-09)

- [x] **Savings study** `[dev]` (done 2026-10-05, private `Earnie-env-home/studies/powerstation-savings-2025.md`, home plant, 2025). Cash bill: virtual reserves/floors are flat or more expensive (about 2–21 €/year). Physical packs save about 4–18 €/year (150 W on 1024 Wh: 18 €; late Trockner starts about 21 €). Bill savings alone do not carry **2.7.h**; a virtual floor is not worth more than the 15 kWh battery alone. Outage value is not priced. **2.7.g** shipped for UX; **2.7.h** implemented (physical only; virtual floor declined) — productive dogfood deferred until Quellenwahl is entity-scoped (see [Backlog.md](Backlog.md) Version 2.7).

### Loxone-verify hydrate/wait + warn on missing VO (2026-10-09)

- [x] **Loxone-verify: hydrate / wait before verify + warn on missing VO** `[feat]`
  - `prepare_loxone_push_inbox_for_startup`: hydrate inbox → start VO HTTP → `wait_for_push_link` (token), then startup verify
  - Push miss / outdated last-known → Live Read + startup **Warnung**; last-known ≤5 min still OK; unbound stays error
  - Tests: `tests/test_loxone_connectivity.py`, `tests/test_startup_checks.py`; docs: `docs/ui/ehal-com.md`

### Bugfix — Duplicate `PLANT_FIELDS` heuristic proposals (2026-10-09)

- [x] **Loxone / HA mapping: duplicate `PLANT_FIELDS` — heuristic proposals miss fields** (**2.7.n-1** half) — fix implemented (2026-10-09); **Verified** UI (2026-10-09)
  - Removed stale field-list copy in `ui/ehal_loxone_mapping_ui.py`; `heuristic_propose` uses canonical `PROPOSAL_FIELDS` (`PLANT_FIELDS` + `ESS_BATTERY_MAPPING_KINDS` + EV/FLEX/FILTER).
  - entity-scoped lookup: `proposal_for_mapping_field` (Loxone) and `_proposed_entity_id` (HA) resolve `ess.<id>.<kind>` → flat kind.
  - Tests: `tests/test_ehal_loxone_mapping_entities.py`, `tests/test_ehal_ha_mapping_entities.py`, `tests/test_loxone_ehal_mapping.py`.
  - UI: EHAL-Com HTTP probe proposes `set_grid_export_power_limit` and battery SoC on a multi-ESS plant.

### Bugfix — Second battery SoC no longer falls back to primary (2026-10-09)

- [x] **Second battery / physical PS: missing SoC no longer falls back to primary** (**2.7.n-1**) — fix implemented (2026-10-09); **Verified live** (2026-10-09)
  - `read_ess_soc_by_id` iterates `ehal_mappable_batteries`; primary may use plant `sens_ess_soc`; others omitted + warn once. Standby pack without SoC skipped; house ESS without SoC dropped from this cycle’s MILP list; milp/sim no longer reinject primary SoC for missing multi-ESS ids.
  - Tests: `tests/test_ess_soc_by_id.py`.

### Bugfix — Live-Lesen / Live-Schreiben obsolete bare / colon EHAL IDs (2026-10-09)

- [x] **Live-Lesen / Live-Schreiben show obsolete bare / colon EHAL IDs** — fix implemented (2026-10-09); **Verified live** (2026-10-09)
  - Live tables use exchange IDs only: `grid.meter.*`, `ess.<id>.*` when mappable batteries exist (no bare `get_ess_soc_min` / `sens_grid_energy_import` / plant ESS flats), qualified consumer writes (`evcs.*` / `consumer|heatpump|pool.*.set_enable`) instead of `{cid}:field`.
  - Code: `integrations/ehal_debug_mapping.py`, `integrations/loxone_connectivity.py`; docs `docs/ui/ehal-com.md`; tests `test_loxone_debug.py`, `test_loxone_connectivity.py`, `test_ehal_ha_mapping_entities.py`.

### Bugfix — Remove consumer `*.sens_energy_export` (2026-10-09)

- [x] **Remove consumer `*.sens_energy_export`** — fix implemented (2026-10-09); **Verified live** (2026-10-09)
  - Consumers are mono only (`sens_energy_total`); bipolar export field dropped from role/FLEX_FIELDS/Live-Lesen/`VO_Earnie_Consumer.xml`, meter energy activate/read, and EFM.
  - Migrate strips leftover `sens_energy_export` from `consumers[].ehal_bindings`. Plant `sens_grid_energy_export` and battery charge/discharge unchanged.
  - Docs: `charts.md`, `ehal-com.md`, `loxone-signals.md`, `loxone-meter-energy-slot-ist.md`. Tests: `test_loxone_meter_energy.py`, `test_ehal_entity_bindings.py`, VO/mapping entity tests.
  - Live: Miniserver VO cmds no longer push `consumer.*.sens_energy_export`; Live-Lesen / slot Ist use `sens_energy_total` only.

### 2.7.q — Binding push-only write path + retire the Loxone mapping (2026-10-09)

- [x] **2.7.q — Binding push-only write path + retire the Loxone mapping** `[feat]` (epic **Binding**; follows archived **2.7.o**)
  - **Packages (all code done):** q.A/Q1 · q.B/Q2+Q3 · q.C/Q4 · q.D/Q5 (live dogfood verified) · q.E/Q6 (meter energy VO push; **Verified live** 2026-10-09) · q.F/Q7+Q8 — detail sections below
  - **Outcome:** Loud writes publish only via qualified IDs in `status.json` (VI poll ≤10 s); no Merker HTTP for setpoints; meter-energy `/all` poll removed in code; EHAL-Com mapping chapter → Signal list; empty-string activation flags; dual-emit legacy peers removed
  - **Deferred (Shadow future undecided):** Shadow would-write old-vs-new comparison; silent publish gate so planned `status.json` setpoints never actuate
  - **Follow-up (open in Backlog):** Retire remaining Loxone Merker poll reads (gap after push-only read/write)

### 2.7.q q.F — Contract UI + storage Q7+Q8 (2026-10-09)

- [x] **q.F — Contract UI + storage** `[feat]` (Q7+Q8; done 2026-10-09)
  - **Note (adapted after Q5/Q6):** Loud Live-Schreiben was already push-only; VO/VI CLI gens (q.C) reused for UI ZIP export.
  - [x] **Q7 — EHAL-Com Signalliste:** mapping chapter replaced; Schreibtest = publish + callback; SpecialState10 poll removed; verify/watchdog on inbox/callback; docs updated.
  - [x] **Q8 — Storage cleanup:** empty-string activation flags; `_mapped_fields(require_nonempty_value=…)`; import writes empty values; `scripts/clear_loxone_binding_names_once`; dual-emit legacy peers removed from `status.json`.

### 2.7.q q.E / Q6 — Meter energy as VO push (2026-10-09)

- [x] **q.E / Q6 — Meter energy as VO push** `[dev]` (decided 2026-10-08): each meter gets a second VO for cumulative kWh (bipolar: consumption + delivery). No averaging / integration of pushed power. QH-open/close anchors read last pushed counter from the inbox; `*_kw = ΔE / 0.25` unchanged (negative Δ rejects that channel).
  - Fields: plant `sens_pv_energy`, `sens_grid_energy_import` / `_export`; consumers `sens_energy_total` (+ `sens_energy_export` when bipolar); batteries `sens_ess_energy_charge` / `_discharge` (push IO ready; slot overlay deferred)
  - Code: energy kinds pushable in `ehal/loxone_push_source.py`; inbox / `read_signals_from_docs`; `integrations/loxone_meter_energy.py` inbox-only (no `/all`, no `loxone_meter_energy` profile names); EFM import activates energy bindings; stale (> 3 × repeat) / never received → no overlay, sample-mean fallback; never zero-assumed
  - Templates: `VO_Earnie_Plant` / `Consumer` / `Battery` + generator; spec `docs/spec/loxone-meter-energy-slot-ist.md` push section; docs `ehal-com.md`, `loxone-signals.md`
  - Tests: `tests/test_loxone_meter_energy.py`, `test_loxone_push_source.py`, VO template / EFM / mapping coverage
  - **Verified live** (2026-10-09): energy VOs next to power; inbox values and QH slot-Ist ΔE overlay OK; no Meter `/all` poll; no zero-assumption for silent counters

### Minor — Live-Lesen push zero / last-known Status (2026-10-09)

- [x] **Finding from 2.7.q q.D / Q5 dogfood:** `[feat]` Live-Lesen showed **Kein Mapping** (or bare OK) for push signals at / assumed `0` instead of Push-Inbox style Status
  - `LoxoneCheck.state` from `read_push_value`; `build_read_rows` uses push-state labels (`0 angenommen …`, `Zuletzt bekannt …`) and inbox `last_ts`
  - Empty Merker entity-scoped ESS → EHAL-ID in `collect_read_checks`; Kein Mapping only when unbound / push resolve fails
  - Tests: `tests/test_loxone_debug.py`, `tests/test_loxone_connectivity.py`; docs: `docs/ui/ehal-com.md` Live Read

### 2.7.q q.D / Q5 — Write push-only cutover + live dogfood (2026-10-09)

- [x] **Q5 code — version cut:** `[feat]` Loud cycle, Schreibtest, Loxone adapter, and watchdog restore publish only via `status.json` (`integrations/loxone_writes.py::_publish_setpoint_traced`); no Merker HTTP for setpoints. Dual-emit of legacy Check keys kept until Q8.
  - Call sites: `send_huawei_modbus_states`, flex/EV outputs, `optimizer/powerstation_live.py`, `integrations/ehal_write_test.py`, `integrations/loxone_adapter.py`, `integrations/loxone_watchdog.py`
  - Tests: `tests/test_ehal_write.py`, `test_loxone_client.py` (Huawei/flex), `test_powerstation_2_7_h.py`, `test_loxone_watchdog.py`, `test_loxone_adapter.py`, `test_loxone_status_json.py`
  - Docs: `docs/ui/ehal-com.md` § Q5 staged VI checklist; `docs/referenz/loxone-signals.md`; `docs/einrichtung/loxone-anbindung.md`; `share/loxone/templates/README.md`
  - Pilot VIs regenerated: `tmp/vi_pilot_out/` from Earnie-env-home config
  - **Decided:** accept ≤10 s VI poll for EV / powerstation writes; Freigabe stays Analog
- [x] **Q5 ops — plant dogfood verified live** `[feat]` (2026-10-09): Loxone Config VI Checks (2026-10-08); cut build `2.7.0-dev.28`; no Merker HTTP for cycle setpoints; actuators follow VI within ≤10 s; Loud ≥24 h OK

### 2.7.q q.C — Templates + VI generator Q4 (2026-10-08)

- [x] **q.C / Q4 — Templates + generator:** `[feat]` VI library v2 (`VI_Earnie_*_v2.xml`) with qualified Check keys; keep legacy `VI_Earnie_*.xml` for Q5 rollback; `scripts/pilot_vi_template_gen.py` fills real Kennungen from config (`VI_Pilot_*.xml` + CSV); VO titles from qualified ID (`title_from_qualified_id` / `Push_<id>`); `write_signals_from_docs` + `heartbeat_write_signal` in `ehal/push_signals.py`
  - Tests: `tests/test_pilot_vi_template_gen.py`, updated `test_pilot_vo_template_gen.py` / `test_loxone_vo_template_shape.py`
  - Docs: `share/loxone/templates/README.md`, `docs/referenz/loxone-signals.md`, `docs/ui/ehal-com.md`

### 2.7.q q.B — Dual-run write Q2+Q3 (2026-10-08)

- [x] **q.B / Q2 — Key scheme:** `[feat]` `status.json` dual-emits qualified IDs next to legacy keys for one version (`evcs.<slug>.set_evcs_*`, `consumer.` / `heatpump.` / `pool.<slug>.set_enable`; plant bare + powerstation `ess.<id>.set_*` unchanged). Built from `ehal/qualified_ids.py`; title sniffing only for legacy keys
- [x] **q.B / Q3 — Writer** `[feat]` (former 2.7.n-6): `integrations/ehal_write.py::write_field` publishes ledger (`ehal_published.json` + run_state); wired in `send_huawei_modbus_states`, flex/EV outputs, powerstation Loxone writes, Schreibtest; success = published + Miniserver callback `ts`; direct `/dev/sps/io/…` stays (dual-run)
  - Tests: `tests/test_ehal_write.py`, dual-emit asserts in `test_loxone_write_characterization.py` / `test_loxone_status_json.py`
  - Docs: `docs/referenz/loxone-signals.md`, `docs/ui/ehal-com.md`

### 2.7.q q.A — Write-path characterization gate Q1 (2026-10-08)

- [x] **q.A / Q1 — Write characterization** `[dev]` (former write half of 2.7.n-4; gate for 2.7.q dual-run)
  - Thin pins in `tests/test_loxone_write_characterization.py`: ESS modes (incl. sticky active `0`, asymmetric limits), flex enable + status key shapes, EV current/mode/Sofort, powerstation W→kW + Pattern-B status keys (house flat untouched), frozen legacy `status.json` payload snapshot
  - Minimal silent/Shadow: Shadow does not start status.json listener; silent still serves planned `loxone_sent` (characterized as known risk)
  - **Deferred** (Shadow future undecided): Shadow would-write old-vs-new; silent publish gate so planned status.json values never actuate

### 2.7.p — Virtual powerstation consumer-start release (2026-10-08)

- [x] **2.7.p — Virtual powerstation consumer-start release** `[feat]`
  - EHAL exchange/Live/VO: `consumer.{Kennung}.sens_consumer_active` (digital; storage may still be `flex.{slug}.*`); Merker `Earnie_Verbraucher_<Slug>_Aktiv`; Live-Lesen; recipe/role/HITL
  - OR-trigger: digital active **or** `sens_power_act` threshold **or** physical `ess.*.sens_ess_power` **or** UI button (live reads, not plant telemetry alone; accepts `consumer.*` and `flex.*` telemetry keys)
  - Release while active; after inactive drain leftover `stored_kwh`; refill price-optimal with hard **24 h** deadline (`refill_opened_at`, MILP deadline charge window replaces ASAP front-load)
  - Docs: `batterie-pv.md`, `flexible-verbraucher.md`, `ehal-com.md`, `loxone-signals.md`, `docs/spec/ehal.md`; tests `tests/test_powerstation_2_7_p.py`

### 2.7.o — Push-only Loxone read path + cleanup (2026-10-08)

- [x] **2.7.o — Binding push-only read path** `[feat]` (WP1–WP8 + post Phase C cleanup; procedure [`Binding-Push-Only-Conversion.md`](Binding-Push-Only-Conversion.md))
  - Inbox `read_push_value` / `read_push_ready_by_time`, zero rule + 5 min last-known, start-up wait, EHAL-Com Quelle
  - Push is unconditional for pushable `sens_*` / `get_*` (`ehal.loxone_push.entities` deprecated/ignored)
  - No Merker poll fallback for bound push fields; meter `*_energy` / writes / probe / watchdog stay on poll
  - FertigUm: numeric or fresh Tna text (`Morgen, 07:00`) via inbox → existing `parse_loxone_ready_by_time`
  - READ Merker optional (EHAL-ID fallback when binding key present); WRITE Merkers required
  - Removed EHAL-Com **Push-Inbox** UI (`ui/loxone_push_inbox_ui.py`); daemon inbox kept
  - Docs: `docs/ui/ehal-com.md`, `docs/referenz/loxone-signals.md`
- [x] Former backlog “Push works for all EHAL values…” checklist (opt-in removal, Wecker path, Merker read strip) folded into this item `[feat]`

### Powerstation every-cycle set_* writes + Schreibtest full field list (2026-10-07)

- [x] **Physical powerstation Merkers refreshed every optimize cycle** `[feat]` (sticky Loxone state)
  - `write_cycle_powerstation_setpoints` / `build_cycle_powerstation_fields` in [`optimizer/powerstation_live.py`](../optimizer/powerstation_live.py): all **mapped** `ess.{slug}.set_*` (charge from plan else 0; discharge/active → 0; mode → 0 Automatik; source_select → plan else grid)
  - Wired in [`main.py`](../main.py); idle packs no longer skip writes when no reserve/standby charge
  - Loxone wire units: charge/discharge/active W→kW; records returned for Live-Schreiben
- [x] **Live-Schreiben includes powerstation Merker writes** `[feat]` in last-run table
  - PS `LoxoneWriteRecord`s merged into `loxone_writes` with house ESS + flex (`serialize_write_records`)
  - entity-scoped write IO index: batteries + plant `set_ess_source_select` in [`integrations/ehal_debug_mapping.py`](../integrations/ehal_debug_mapping.py)
- [x] **Schreibtest lists all mapped write fields** `[feat]` (plant, entity-scoped, EV, Flex)
  - [`integrations/ehal_write_test.py`](../integrations/ehal_write_test.py) / [`ui/ehal_write_test.py`](../ui/ehal_write_test.py): auto rows from `expected_live_write_fields` ∩ mapped; **Senden** default unchecked
  - `set_ess_active_power` (incl. entity-scoped) always visible; Force checkbox unlocks send only (±200 W + second confirm)
  - Docs [`docs/ui/ehal-com.md`](../docs/ui/ehal-com.md); tests `tests/test_powerstation_2_7_h.py`, `tests/test_ehal_write_test.py`

### 2.7.m — Per-battery EHAL mapping (EHAL-Com) (2026-10-06)

- [x] **2.7.m — Per-battery EHAL mapping (EHAL-Com)** `[feat]` (before **2.7.l**; unblocks **2.7.h** dogfood mapping)
  - Decisions: ESS off plant row (runtime primary flat aliases only); per-battery Loxone Merker `Earnie_Batterie_<Slug>_…`; shared plant `set_ess_source_select` / `Earnie_Speicher_Quellenwahl`; virtual powerstations excluded from EHAL binding
  - **2.7.m-1:** `kind: battery` rows in `build_entity_rows` (house + physical PS only); persist via `apply_battery_bindings` → `components.json`; Shadow `battery_bindings`
  - **2.7.m-2:** `aggregate_ha_entities` merges entity-scoped + primary aliases; Live-Lesen per-battery rows; plant-flat ESS fallback until migrate
  - **2.7.m-3:** battery required SoC; function status entity-scoped scope; per-battery HA sign inherit; setup_readiness via `resolve_plant_binding`
  - **2.7.m-4:** `scripts/migrate_ess_bindings_once.py` (`--config-dir` / `--dry-run`); top-level plant migrate; keep `set_ess_source_select` on plant
  - Docs: `ehal-com.md` §C.2, `batterie-pv.md`, `ehal.md`, `loxone-signals.md`; tests mapping / aggregate×2 / shadow / migrate

### Monthly rotation — optimization_history.jsonl + earnie.log (2026-10-06)

- [x] Monthly rotation for `optimization_history.jsonl` and `earnie.log` (no size trigger; `backupCount=12` ≈ one year) `[qual]`
  - Shared helpers: `runtime_store/month_file_rotation.py` (`compute_next_month_rollover`, archive naming, rename→copy/truncate, prune)
  - `logger_config.MonthRotatingFileHandler` (replaces size+weekly `W0`); history rotates on append; loaders merge active + archives
  - Debug dump + shadow seed include history archive siblings; docs `docs/einrichtung/betrieb.md`
  - Tests: `tests/test_logger_config_rotation.py`, `tests/test_optimization_history_rotation.py`

### Bugfix — EV setpoints empty / continuous postpone (2026-10-06)

- [x] EV charging continuously postponed / empty live setpoints (dump `debug_dump_20261006_055651`)
  - Cause: virtual-reserve ASAP (`_virtual_reserve_asap_kwh`) + sunrise PV-only → MILP Infeasible → Automatik fallback (`consumer_powers_kw={}`)
  - Fix: skip PV-only when ASAP carve-out pending (`optimizer/milp.py`); regression `tests/test_milp_sunrise_soc.py::test_milp_feasible_with_virtual_asap_and_sunrise_pv_only`
  - **Verified live** (2026-10-06): productive NAS — `earnie.log` ASAP skip @ 06:22; `e_auto` 3.52 kW (was empty); no further `milp_no_optimal`

### Bugfix — Consumer editor Standard-Laufzeit removed (2026-10-06)

- [x] Consumer editor: removed redundant "Standard-Laufzeit"; advice/reserve runtime = `schedule.duration_h` only (dropped persisted `appliance_recommendation.default_runtime_h`)
  - **Verified live** (2026-10-06)

### Bugfix — Powerstations not selectable in Scenario-Config (2026-10-06)

- [x] Virtual and physical powerstations shall not be selectable in Scenario-Config (not only warning)
  - Scenario catalog filters via `scenario_selectable_batteries` (`house_config/powerstation.py` → `_load_scenario_catalogs`); regression `test_scenario_selectable_batteries_excludes_virtual_and_physical_ps`
  - **Verified live** (2026-10-06)

### 2.7.h — Powerstation smart standby-backup for continuous loads (2026-10-06)

- [x] **2.7.h — Powerstation smart standby-backup for continuous loads** `[feat]` (`role: standby_backup`; shared model with **2.7.g**)
  - Physical only: virtual floor declined (savings study / go/no-go — not worth more than raising house `min_soc`)
  - Rolling per-slot MILP: expensive → battery island, cheap → grid pass-through (+ optional recharge); reserve = load kW × expensive hours, capped by pack capacity
  - EHAL `set_ess_source_select` (0 = grid / 1 = battery) + capability `supports_ess_source_select`; setpoint schema_version **4**; HA boolean invert for EcoFlow `switch.*_grid_bypass` (`ban_bypass_en`)
  - Runtime: [`optimizer/powerstation_standby.py`](../optimizer/powerstation_standby.py) + live write path; Loxone Merker `Earnie_Speicher_Quellenwahl` / `VI_Earnie_Plant.xml`; readiness warnings in setup UI
  - Docs: `ehal.md`, `loxone-signals.md`, `batterie-pv.md`, EcoFlow bridge guide; tests `tests/test_powerstation_2_7_h.py`
  - Spec: `Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` §3.4.2 (`Earnie-Projekt`)
  - **Productive dogfood deferred (2026-10-10):** wait for `set_ess_source_select` → entity-scoped `ess.<id>.*` in [Backlog.md](Backlog.md) Version 2.7; EcoFlow Loxone↔HA bridge rewire is separate. Then re-open live acceptance under [Bugfixes](Backlog-Bugfixes.md).

### Bugfix — New battery from Powerstation selection crash (2026-10-06)

- [x] Creating a new battery, when a powerstation is selected — crashes
  - Cause: `new_battery_template` cloned charge-only PS powers (`discharge=0`) into a typeless Hausbatterie draft; seed then failed house power rules in `split_battery_max_power_kw`
  - Fix: coerce asymmetric charge/discharge to both non-zero (or both zero) in `ui/planning_battery_form.py` `new_battery_template`
  - Regression: `tests/test_planning_editors.py::test_new_battery_template_from_powerstation_coerces_house_powers`
  - **Verified live** (2026-10-06): Hauskonfigurator → Batterien → Powerstation selected → „— neu —“ opens without crash

### 2.7.k — ENTSO-E first in live day-ahead price chain (2026-10-05)

- [x] **2.7.k — ENTSO-E Transparency as additional EPEX day-ahead source (user token)** `[feat]`
  - Live chain: ENTSO-E (when `ENTSOE_API_TOKEN` in `config/.env`) → Energy-Charts (Fraunhofer) → QH disk cache → aWATTar; no token → INFO skip with checked `.env` path
  - Client [`integrations/entsoe_client.py`](../integrations/entsoe_client.py): A44, EIC map AT/DE-LU/CH; PT15M native, PT60M (CH) → QH expand; token never logged; env + `.env` file fallback for token
  - Cache rename `live_day_ahead_<zone>.json` (`CACHE_VERSION` 2, optional `source`); orchestrator [`data/live_market_prices.py`](../data/live_market_prices.py)
  - Fixtures `tests/fixtures/entsoe/`; tests `test_entsoe_client.py` + live cache order/fallback
  - Docs: `tarife-quellen.md`, `preise.md`, `betrieb.md`, `quarter-hour-slots.md`; `.env.example` + `dotenv_io` quoted key
  - **Verified live** (2026-10-05): API probe AT/DE-LU PT15M, CH PT60M; main.py against NAS productive `.env` with token → ENTSO-E used
  - Out of scope: Earnie-hosted relay / subscription SLA; SE price chain; Streamlit token UI

### EV coming-back prognosis review and refactor (2026-10-05)

- [x] Thorough review of EV coming-back / connect prognosis (too-early planning + day skip) `[dev]`
  - Spec: [`docs/spec/ev-return-prognosis.md`](../docs/spec/ev-return-prognosis.md) (current algorithm, Jul–Oct 2026 history, phase model)
  - Single resolver `resolve_connect_prognosis` in [`optimizer/ev_connect_prognosis.py`](../optimizer/ev_connect_prognosis.py); phases `before_arrival` / `late_return` / `open_cycle` / `overnight_open` / `inactive`
  - ReadyAt: live FertigUm, else config `ready_by_hour` (both Loxone and config paths) — no day skip when only config ReadyAt exists
  - Context fields `connect_phase` + `ready_at_source` for debug dumps; German user doc + schema for `forecast_when_absent`
  - Tests: [`tests/test_charging_context.py`](../tests/test_charging_context.py)

### 2.7.g — Powerstation reserve for single-use manual devices (2026-10-05)

- [x] **2.7.g — Powerstation reserve for single-use manual devices** `[feat]` (`role: single_use`; shared model with **2.7.h**)
  - Assist mode XOR: `appliance_recommendation.mode` `advice` | `reserve` + `powerstation_id` when reserve (Hausprofil + Manuelle Geräte UI)
  - Shared data model: `type: powerstation`, `backing: virtual|physical`, `attached_consumer_ids[]` (legacy singular = first; virtual multi, physical max 1), `role: single_use`
  - Virtual carve-out: UI hide/inherit electrical fields from primary Hausbatterie; capacity = reserve cap
  - Bidirectional attach sync: battery form ↔ house-profile consumers; consumer→battery clears empty PS lists; battery multiselect reads `profiles` dict
  - Runtime: reserve state machine + virtual floor (`optimizer/powerstation_reserve.py`, `powerstation_live.py`, `runtime_store/powerstation_reserves.py`); MILP / export-limit carve-out; physical packs excluded from house-grid discharge planning
  - Trigger: Manuelle Geräte button; meter path when `loxone_inputs.power_name` present; energy-per-run learning helper
  - Multi-reserve equal-share for v1; prioritization deferred to **2.+1**
  - Schemas/examples, German docs (`batterie-pv.md`, `flexible-verbraucher.md`, handbook, EcoFlow note); tests `tests/test_powerstation_2_7_g.py`
  - Spec: `Entwicklungsplan/Entwicklungs-Plan-Earnie-cons.md` §3.4.1 (`Earnie-Projekt`)

### Virtual Powerstation multi-consumer attach (2.7.g partial) (2026-10-05)

- [x] **Multiple consumers on one virtual Powerstation** `[feat]`
  - Canonical field `attached_consumer_ids[]` (+ legacy `attached_consumer_id` = first); physical stays max 1
  - Hauskonfigurator: multiselect for virtual; profile caption; sync from all reserve-mode manuals
  - Runtime: one shared reserve pool per PS (summed target, cap by capacity); trigger from any attached appliance
  - Docs: `docs/konfiguration/batterie-pv.md`, `flexible-verbraucher.md`; tests in `tests/test_powerstation_2_7_g.py`

### Virtual Powerstation UI hide / inherit (2.7.g partial) (2026-10-05)

- [x] **Virtual Powerstation (`backing: virtual`): hide nonsensical Hausbatterie parameters** `[feat]` and inherit from the primary `type: house` battery on save/normalize
  - UI ([`ui/planning_battery_form.py`](../ui/planning_battery_form.py)): only Bezeichnung, Typ, Backing, Rolle, Verbraucher, Kapazität (carve-out cap); caption / warning when no Hausbatterie
  - Inheritance helpers: [`house_config/powerstation.py`](../house_config/powerstation.py) (`apply_virtual_powerstation_inheritance`); applied in [`components_store.py`](../house_config/components_store.py) + [`upsert_battery`](../ui/house_config_entities_io.py)
  - Hidden → inherit charge/efficiency/SoC/threshold from main ESS; discharge `0`, standby `0`, `limits_from_live` false, `control: limits_only`, wear off; fixed defaults if no Hausbatterie
  - Physical Powerstations unchanged (full form)
  - Docs: [`docs/konfiguration/batterie-pv.md`](../docs/konfiguration/batterie-pv.md) § Virtuelle Powerstation; tests in `tests/test_powerstation_2_7_g.py`
  - Superseded by full **2.7.g** archive entry above; **2.7.h** archived 2026-10-06 (productive dogfood deferred — entity-scoped Quellenwahl move)

### Powerstation savings study 2.7.g / 2.7.h (2026-10-05)

- [x] Prepare and execute a small study about saving potentials for 2.7.g and 2.7.h `[dev]`
  - Private result: `Earnie-env-home/studies/powerstation-savings-2025.md` (home plant, 2025, aWATTar hourly day-ahead; Energy-Charts was down)
  - Cash bill: virtual reserves/floors flat or more expensive (about 2–21 €/year). Physical packs save about 4–18 €/year (150 W on 1024 Wh: 18 €; late Trockner starts about 21 €)
  - Bill savings alone do not carry **2.7.g** / **2.7.h**. A virtual floor is not worth more than the 15 kWh battery alone. Outage value is not priced
  - Study informed keep-**2.7.g**-for-UX and physical-only **2.7.h** (virtual floor declined)

### EV late-return connect prognosis (2026-10-04)

- [x] Improve prognosis for EV coming back (connecting for charging) `[feat]`
  - Take schedule from config as start
  - If scheduled time passed without connected EV: last possible start = ReadyAt − charge duration − 1h buffer as internal connecting schedule (`late_return_available_from` in `optimizer/charging_resolve.py`)
  - Only skip future charging completely when no ReadyAt from smarthome-backend (or deadline already expired)
  - Docs: `docs/konfiguration/flexible-verbraucher.md`; tests: `tests/test_charging_context.py`

### SE calendar month buttons (2026-10-04)

- [x] Instead of Previous/Next (Zurück/Vor) on Detaillierte Simulationsansicht on SE page: one button per month to change visible month (`ui/backtesting_deviation_calendar.py`; months without in-run days disabled) `[feat]`

### Bugfix NAS live startup / price fallback (2026-10-04)

- [x] **Live aWATTar fallback NameError `MARKET_ZONE_CH`** — Energy-Charts 503 hit `if zone == MARKET_ZONE_CH` without importing the constant. Fix: import `MARKET_ZONE_CH` in `data/live_market_prices.py`. Regression: `tests/test_live_market_prices_regression.py`. NAS productive verified.
- [x] **Startup abort `settings.battery_id` on data-model 4** — Bootstrap stamped `earnie_data_model=4` without migrating singular `battery_id`. Fix: `_migrate_pack_legacy_keys` in `runtime_store/bootstrap.py`, soft-coerce in `house_config/scenario_resolution.py`, startup check uses `battery_ids`. Regression: `tests/test_bootstrap_battery_id_regression.py`. NAS productive verified.

### 2.7.c — Multiple isolated battery / battery+inverter entities (2026-10-03)

- [x] **2.7.c — Multiple isolated battery / battery+inverter entities** `[feat]` (bidirectional)
  - Isolated battery modes: charging / discharging / standby
  - batt+inverter modes: optimizing / charging / discharging
  - All batteries participate in optimization
  - **Export limit "unconstrained" value (from 2.7.a):** `live_unconstrained_export_kw()` in `optimizer/live_export_limit.py` sums PV kWp + max discharge of **every** battery that supports forced discharge (skip `limits_only` / `read_only` / physical powerstations from **2.7.g**/**2.7.h** that cannot feed the house grid); docs `docs/spec/ehal.md` + `docs/einrichtung/loxone-anbindung.md`
  - EHAL / entity-scoped namespacing for multi-ESS (design reusable by **2.+1** multiple EV / Wallboxes)
  - [x] In SE after calculation of Test Month the Detaillierte Simulationsansicht should automatically go to March (tested month)
  - [x] Show SOC line for each battery in Monitor chart1
  - **Note:** Downstream Loxone template XML gen and HouseSim scenario import multi-battery support remains open under Version 2.+1

### Bugfix SE Plausibility Class A / Class B (2026-10-03)

- [x] **SE Class A: MILP Infeasible / EV zero under pay-to-export** — Fix: `optimizer/milp_horizon.py` (`p_pv_curtail`). Regression: `tests/test_milp_export_cap.py::test_milp_pay_to_export_feasible_when_pv_exceeds_charge`. Snapshot re-solve `2026-04-23T07:00:00`/`live`: Optimal + EV ~10.5 kWh. **SE year verified** (`2025-10-01`–`2026-09-30`, `sunrise_window`, `live`/`live_copy`): Class A days gone.
- [x] **SE Class B: WP under-delivery on Optimal sunrise windows** — Fix: `optimizer/thermal_flex_context.py` (slot-aligned book-slot climate kWh vs calendar HDD × `day_slots/96`). Regression: `tests/test_thermal_flex_bridge.py::test_thermal_book_slots_use_slot_aligned_energy_not_calendar_prorate`. Diag: `python -m scripts.diag_class_b_window`. **SE year verified** same run: **364/365** OK (was ~310/365); sole leftover `2026-09-21` flex Δ 0.72 = `pool_filter` native-credit residual (tracked as open follow-up).

### Bugfix RC model simulation plausibility (2026-10-03)

- [x] **Plausibility of RC model simulation on NAS productive** — Live acceptance verified on NAS productive; no code change.

### Version 2.6 - Enhancements for HA coupling (2026-10-03)

- [x] **Version 2.6 — Enhancements for HA coupling** `[feat]` (chapter closed; official **2.6.0** on `main`, supersedes **2.5.3** on `:latest`)
  - Scope: easier HA coupling for Earnie. HA entity IDs live on `plant` / `consumers[].ehal_bindings` (entity-scoped, Loxone-parity HITL). The generic HA↔Loxone bridge stays under Research Items in [Backlog.md](Backlog.md). Add-on 1.0 (Earnie publishing its own state) is deferred to **Version 2.+1**.
  - Documents: [House simulator spec](../docs/dev/house-sim.md) (HouseSim S1–S4); [EHAL spec — entity-scoped / Loxone HITL](../docs/spec/ehal.md); [Add-on backlog](https://github.com/JochenTCC/ha-addon-earnie/blob/main/BACKLOG.md) (channel work **2.6.k**)
  - Letter archive: **2.6.a**…**2.6.p**, **2.6.r**, alphas through **2.6.0-alpha.12**, and official **2.6.0** — see sections below in this file

### 2.7.j — Additional ESS parameters (2026-10-03)

- [x] **2.7.j — Additional ESS parameters** `[feat]`
  - Four plant EHAL **reads** (W / %), HK switch `limits_from_live` on `batteries[]`; plant bindings until **2.7.c** namespaces multi-ESS:
    - `get_ess_soc_min` / `get_ess_soc_max` [%] — read/MILP only (no `set_ess_soc_*`); Huawei LUNA 47082 / 47081
    - `get_ess_max_charge_power` / `get_ess_max_discharge_power` [W ≥ 0]; Huawei LUNA 47075 / 47077
    - Cycle writes reuse existing `set_ess_*_power_limit` (W)
  - HK: per-ESS “Grenzwerte … übernehmen” (`limits_from_live`); split `battery_max_power_kw` → `battery_max_charge_power_kw` / `battery_max_discharge_power_kw` (legacy migrate on load; persist split fields in `components_store._serialize_battery`)
  - Wired through Loxone / HA / OpenEMS adapters, `share/ehal/roles/ess.json`, telemetry schema, EHAL-Com mapping and docs

### Bugfix Negative export tariff + battery discharge (2026-10-02)

- [x] **Negative export tariff + battery discharge** — Soft pay-to-export live dogfood closed with **2.7.a** (2026-09-30). Live verification: plan vs live discharge when `k_push` is negative. PV curtailment var for hard cap when SoC full remains optional hardening if the cap becomes infeasible at full SoC.

### Bugfix Invalid JSON config crash message (2026-10-01)

- [x] **Invalid JSON in config.json crash** — `read_json_dict` raises clear `ValueError` (path + Zeile/Spalte, no chained `JSONDecodeError`); `bootstrap.run()` aborts via `_abort_config_error` (`Abbruch:…`, exit 1) like `load_config_or_exit`. Regression: `tests/test_json_io.py`. Verified.

### Bugfix Tariff forecast surcharges already applied (2026-10-01)

- [x] **Tariff forecast vs known tariff extras / volumetric Netzentgelt** — Checked: no fix. Predicted/mirrored slots use the same `epex_to_brutto_cent` → `import_cent_kwh` path as day-ahead (markup, `settlement_fee_cent_kwh`, `netzentgelt_override` before VAT). Forecast model outputs EPEX only; brutto add-ons are applied at price resolution (`docs/spec/price-forecast-renewables.md`). Persistent “forecast looks cheaper” is not missing surcharges on that path.

### Bugfix Unneeded Hauswärme / hot heat storage (2026-10-01)

- [x] **Unneeded Hauswärme with hot heat storage** (`debug_dump_20260930_182138`, NAS Shadow) — Live planned WP Freigabe while buffer was ~60–80 °C (setpoint 47 °C). Three stacked causes: (1) MILP day lower bound `max(HDD, live_min)` kept open-loop climate kWh even with measured store; (2) floor electric was a movable day budget → early ON; (3) Live envelope `H` calibrated from short outdoor forecast (HWB÷~48h HDD ≈ ×100 too large) plus space demand = full WP `max_heat` emptied the tank in ~3 h → forced Freigabe ~14:00. Shadow did receive `T_eq`/`T_low`. Fix: Live overlay ignores HDD; floor only via `forced_indices`; flexible want = `opp_cap` only; year-scale H + envelope-hold space draw. Spec `docs/spec/thermals-p2.md`. Tests: `test_thermal_milp_live_hot_store_ignores_hdd_day_target`, `test_thermal_milp_live_warm_store_no_early_floor_budget`, `test_live_min_kwh_excludes_floor_when_above_setpoint`, `test_hot_store_floor_does_not_force_within_few_hours`. Verified on NAS Shadow (no unneeded near-term Freigabe with hot store).

### Bugfix #24 Hourly Gesamt-CSV baseload quartered (2026-10-01)

- [x] **[#24](https://github.com/JochenTCC/Earnie/issues/24) — Hourly Gesamt-CSV baseload quartered in 15‑min SE** — Path B `meter_residual_baseload_kw` used exact slot timestamps; hourly CSV only has `:00`, so `:15`/`:30`/`:45` became 0 → energy ≈ ÷4. Fix: hour-floor ZOH via `csv_kw_at_datetime`. Test: `test_meter_residual_holds_hourly_csv_on_qh_slots`. Verified on reporter pack March 2026 Gesamt ≈ 302.8 kWh (old exact-ts ≈ 75.7). Branch: `fix/issue24`.
- [x] **[#24](https://github.com/JochenTCC/Earnie/issues/24) — EEG `k_push_cent` edit (9.03) not shown (still 8.04)** — HA add-on: missing `/config/tariffs.json` fell back to stale `/data/earnie_env/config/tariffs.json` (catalog 8.04). Fix: with `EARNIE_INSTALL_CONTEXT=homeassistant_addon`, sidecars always resolve under `EARNIE_CONFIG_PATH`. Regression: `test_ha_addon_tariffs_ignore_stale_data_volume_copy`. Verified (path repro: edited add-on file → 9.03; missing add-on file no longer reads data-volume 8.04).

### 2.7.b — Thermals P2 (2026-09-30)

- [x] **2.7.b — Thermals P2** `[feat]` — Coupled single-node models
  - [x] **Slice 1 — House ↔ heat storage ↔ solar (linear)** — optional `thermal.heat_storage` on `thermal_annual`; coupled day targets via `optimizer/thermal_coupled.py`; HK fields; spec [`docs/spec/thermals-p2.md`](../docs/spec/thermals-p2.md); legacy open-loop when volume ≤ 0
  - [x] **House indoor RC** — DIN V 18599 Bauweise `leicht`/`mittel`/`schwer` → C from Wohnfläche; H calibrated from HWB (override optional); band control; `T_house` state; HK fields; chart Haus-Ist; [`optimizer/thermal_house.py`](../optimizer/thermal_house.py)
  - [x] House parameters from energy certificate — **research only** (manual mapping; no automatic PDF/import). Reference: local GEQ EAW EFH Dornbirn 2014 (not in repo). Usable seeds: HWB ≈ 40 kWh/m²a, BGF ≈ 157 m² (≠ Wohnfläche), θi = 20 °C, Sole/Wasser-WP, solar Neigung 18° + Verdrehung 26° (WW-only). **Superseded for the reference installation by the hydraulic plan (2015, local, not in repo) and the tank datasheet:** one combined buffer of **887 l** gross / 861 l net (INHAUS PR 1000; the "1000" is only the type name) → `heat_storage.volume_liters` = **887** (not ≈ 500 from the EAW tank split 100 l RH + 400 l WW); solar collector **10.6 m²** (not 6 m²) → `solar_thermal_area_m2`. Tank: H 2040 mm without insulation, Ø 790 mm, 100 mm PU foam, solar register 3.1 m² (310–1030 mm), four ½" sensor wells at 310 / 745 / 1250 / 1710 mm. Start value `heat_loss_kw_per_k` ≈ 0.006 (estimate, to be calibrated; code default 0.02 is ~3× too high for this tank). **Do not** map building LT+LV ≈ 0.125 kW/K onto `heat_storage.heat_loss_kw_per_k` (tank U only; EAW standby ≈ 4.7 kWh/d → U ≈ 0.006–0.01). BRI ≈ 489 m³ optional for volume heuristics; house C uses Wohnfläche × Bauweise. Monthly Hausprofil model uses Open-Meteo + collector irradiance (same as Live metric), not the offline climate fixture alone.
  - [x] Add a new y-Axis to "Stündlicher Verlauf" Chart on HK page with temperatures (outside ambient, house temp, heat storage tank, pool temp) to give user a visualization of simulation
  - [x] **Heat storage topology (year-sim):** solar thermal collector and heat pump feed heat **only into the heat storage**; space heating and domestic hot water draw heat **only from the heat storage** (the storage also serves house heating, not just DHW); legacy no-store path unchanged
  - [x] **Heat storage temperature band (year-sim):** storage temperature may float between `setpoint − tolerance` and **95 °C**; only above 95 °C is the solar collector heat input capped (`HEAT_STORAGE_ABS_MAX_C` in `optimizer/thermal_coupled.py`)
  - [x] **Heat pump in the band (year-sim):** WP bang-bang at the floor; WP heat capped at `setpoint` (not `setpoint + tolerance`); above the setpoint WP stays off (surplus above setpoint from solar only)
  - [x] **Below the band (year-sim):** if projected storage temperature drops below `setpoint − tolerance`, the heat pump **must** heat (hard lower bound)
  - [x] **Below the band (Live/MILP):** align Live/MILP with year-sim hard lower bound (and opportunistic WP in `[setpoint−tol, setpoint]`) — still daily electric kWh flex only; MILP store-T SoC remains out of scope for this slice; Live reads `T_eq` + `T_low`
  - [x] Change default year of Yearly view on HK page (also on SE page) to the last / current year not 2023
  - [x] **Virtual heat-content sensor (prep for Thermals P3)** — derive `Q = C(V) × T` (C from `capacity_kwh_per_k_from_volume`, T ref 0 °C) for heat storage and pool; same C for sim and measured. Stratified tanks: SM supplies energy-equivalent `T_eq` (not top sensor alone). Spec: Entwicklungsplan §3.5; operator guide [`docs/konfiguration/waermespeicher-schichtung-teq.md`](../docs/konfiguration/waermespeicher-schichtung-teq.md); physics [`docs/spec/thermals-p2.md`](../docs/spec/thermals-p2.md)
    - [x] **EHAL binding** `sens_temperature_heat_storage` (`T_eq`) + `sens_temperature_heat_storage_low` (`T_low`) on `thermal_annual` — Live floor/`T_low` hint wired
    - [x] **Reference installation `T_eq` weights:** only **three** sensors (S3 oben / S4 mitte / S5 unten) in a tank with four sensor wells (310 / 745 / 1250 / 1710 mm); occupied wells not confirmed. **Provisional mapping (best fit of one snapshot against four dial thermometers):** S3 → 1710, S4 → 1250, S5 → 745 mm → `0.27*T_oben + 0.24*T_mitte + 0.49*T_unten` (Schritt A in [`waermespeicher-schichtung-teq.md`](../docs/konfiguration/waermespeicher-schichtung-teq.md)). Risk: lowest ~530 mm (well 310 mm) unmeasured → `T_eq` too high when the tank bottom is cold; consider a fourth immersion sensor in the 310 mm well. Verify mapping with several dial-vs-Loxone snapshots under different stratification, then fix `w_i`
    - [x] **Live:** read measured `T_eq` → `Q_meas`; compute `Q_sim` from RC state / short forecast; persist via `thermal_observability` on `optimization_history.jsonl`
    - [x] **Year-sim / HK model path:** expose `Q_sim` hour series (`heat_content_series` on consumption display bundle)
    - [x] **Weekly chart:** simulated vs measured heat content (kWh) for heat storage and pool — HK Gesamt-Lastverhalten / Stündlicher Verlauf (Ist from Live history when available)
    - [x] **Move Wärmeinhalt chart** from HK Gesamt-Lastverhalten to page **Analyse Verbrauch & Kosten** — show **past** MILP-simulated vs measured heat content (`Q_sim` / `Q_meas` from Live `thermal_observability` / `optimization_history.jsonl`), not the year-sim HK model series; keep model-only °C axis on HK Stündlicher Verlauf
    - [x] Remove Swimspa charts on page Analyse v&K including code for that

### Minor: Remove EHAL flex.set_power_setpoint (2026-09-30)

- [x] **Remove EHAL `flex.{slug}.set_power_setpoint` permanently** `[feat]` — unused for live control (non-EV flex writes only `set_enable`; variable kW/A is EV-only via `set_evcs_max_current`). Stripped entity-scoped field + legacy stub `flex.power_setpoint_name` / non-EV migrate from `loxone_outputs.power_setpoint_name`; mapping UI / Live-Schreiben expected fields / `share/ehal/roles/consumer.json` / greenfield recipes / docs (`loxone-signals`, `ehal-com`). EV `set_evcs_max_current` kept. Heat-pump Prio3 temperature-setpoint path (2.+1) unrelated.

### Bugfix Loxone Live-Lesen range checks removed (2026-09-30)

- [x] **Loxone Live-Lesen range checks removed** — Dropped Earnie-side SoC/power/temp/binary/export min–max validators in `loxone_connectivity` (Loxone already enforces ranges). Live-Lesen still fails on read/parse only. Live acceptance verified (EHAL-Com Live-Lesen / `verify_loxone_setup`).

### Bugfix EHAL-Com Mapping-Tabelle EHAL column (2026-09-30)

- [x] **EHAL-Com Mapping-Tabelle EHAL column** — HTTP-Probe scan shows `ehal` (house binding reverse, else greenfield device map); columns ordered `name, ehal, type, source, room, category, uuid`. Live acceptance verified.

### 2.7.a dogfood — Loxone productive + live test (2026-09-30)

- [x] **2.7.a dogfood — Loxone productive + live test** `[feat]` (wiring archived 2026-09-29)
  - Live-test: static HK cap, inbound grid limit override, pay-to-export soft behaviour, release (unconstrained = PV kWp sum + battery max discharge kW)
  - Prefer Shadow dogfood via **2.7.f**; completes the open live-test from wiring-only archive

### Bugfix Stale SoC sanitize chain (2026-09-30)

- [x] **Stale SoC sanitize chain** (`debug_dump_20260927_083552`) — Trust plant SoC when closed-interval sampler confirms against history (`closed_interval_confirms_reported` + `reported_soc_percent` consecutive count). Live acceptance verified.

### 2.7.d — One-way storage type folded into 2.7.g / 2.7.h (2026-09-29)

- [x] **2.7.d — One-way storage type** (planning fold; not implemented as a standalone letter)
  - Superseded by the shared powerstation model: **2.7.g** (`role: single_use`, physical `backing` = former one-way / no forced discharge) and **2.7.h** (`role: standby_backup`, owns `set_ess_source_select` / EcoFlow mapping / Loxone Merker bridge)
  - No separate `batteries[].direction: one_way` flag — use `type: powerstation` + `backing` + `role` instead
  - Follow-on work shipped as **2.7.g** / **2.7.h** (see archive entries above)

### 2.7.a dogfood — Loxone wiring (partial) (2026-09-29)

- [x] **2.7.a dogfood — Loxone productive wiring** (partial)
  - Wire export-limit Merker / VI–VO in the productive Loxone config (`set_grid_export_power_limit`, optional inbound `get_grid_export_power_limit`; Einspeisesperre = limit `0`, `set_ess_mode` stays battery-only)
  - Bind in EHAL-Com; set a HK `plant.max_export_power_kw` and verify Live writes + MILP respect the cap
  - Live-test closed 2026-09-30 → `### 2.7.a dogfood — Loxone productive + live test (2026-09-30)`

### 2.7.f — Shadow Mode S2+S3: Dev client (2026-09-29)

- [x] **2.7.f — Shadow Mode S2+S3: Dev client** (depends on Prod running **2.6.o** recorder)
  - Spec: [`docs/dev/shadow-mode.md`](../docs/dev/shadow-mode.md) — `EARNIE_SHADOW=1` only (`runtime_store.shadow.is_shadow_mode()`); implies silent; never a config key
  - **S2:** transport replay (§6.1–6.2), central write block + `shadow_writes.jsonl` (§6.3), config read-only / skip load-time migrations that write (§6.4), startup checks (§4.2), release guard (§4.4); own mandatory runtime dir + optional `scripts.shadow_seed_runtime`
  - Accept Prod’s `earnie_data_model` if in `COMPATIBLE_DATA_MODELS`; never migrate/re-stamp shared config. No Shadow `config_overlay` in v1 (Prod-rejected keys not testable)
  - **S3:** UI banner + feed health + would-write table; `EARNIE_UI_STREAMLIT_PORT`; German user docs (`docs/einrichtung/`) + `DEVELOPER.md`
  - Tests per spec §10; E2E with HouseSim as Prod backend (`tests/test_shadow_*.py` — 36 passed)
  - **Out of scope (unchanged):** S4 Soll/Soll diff + offline JSONL backtest → **2.+1**; Shadow as 2nd HA add-on (scenario C)

### Official 2.6.0 release (2026-09-30)

- [x] Bump `version.py` **2.6.0-alpha.12** → **2.6.0**; release notes `.github/release-notes/v2.6.0.md` `[feat]`
- [x] Candidate tag `v2.6.0` (promote after platform test → `:latest` + official HA add-on) `[feat]`

### 2.6.0-alpha.12 pre-release (2026-09-29)

- [x] Bump `version.py` + alpha compose pins to **2.6.0-alpha.12**; release notes `.github/release-notes/v2.6.0-alpha.12.md`
- [x] Candidate tag `v2.6.0-alpha.12` (promote after platform test)

### Bugfix earnie.log run separator + second Aktualisieren (2026-09-29)

- [x] **Add a separator in earnie.log when main.py was started** — After `ensure_single_instance`, `main.py` logs a `====` banner with pid + Earnie version. Docs: `betrieb.md`. Live verified.
- [x] **Second "Aktualisieren" on Optimierer-Dienst Dienst-Log** — Top + bottom refresh (`daemon_log_refresh_top` / `_bottom`) in `ui/pages/page_daemon.py`. Live verified.

### Bugfix Temperatur RC expander 0 kWh/a (2026-09-29)

- [x] **Energy consumption pre-calculation in expander of Temperatur RC shows zero (on NAS env)** — Form sync rewrote `thermal_rc` without lat/lon → `consumer_annual_kwh` fell back to `annual_kwh=0`. Fix: re-inject Standort from profile widgets in `_live_consumer_for_annual`; keep geo on session consumers after sync (`_edit_and_sync_consumers`). Test: `test_live_consumer_for_annual_injects_thermal_rc_geo_from_profile`. Live verified on Shadow NAS (~4082 kWh/a after expand/edit).

### Bugfix EV daytime plan while unplugged + PV Retry-At tz (2026-09-29)

- [x] **EV planned charge while not connected (productive)** — `open_charging_deadlines` with next-morning FertigUm forced `available_from=now` → MILP planned ~3.5 kW midday while unplugged (writes already 0 A via `anticipated`). Fix: same-calendar-day only for open-cycle latch (`_open_cycle_keeps_available_now`). Tests: `TestAbsentAvailability`. Live verified on NAS productive (`14:23:49`: `available_from` 18:00, `e_auto_kw` 0 with latch still present).
- [x] **forecast.solar 429 Retry-At naive/aware crash** — aware `X-Ratelimit-Retry-At` vs `datetime.now()` crashed the cycle. Fix: `_as_naive_local` on parse/compare. Tests: `test_pv_forecast`.

### Bugfix Debug-Dump UTF-8 BOM (2026-09-29)

- [x] **Debug-Dump save failed with UTF-8 BOM** — `Unexpected UTF-8 BOM (decode using utf-8-sig)` when `config.json` (or run_state) had a Windows BOM. Dump readers used plain `utf-8`; now use `settings.json_io.read_json_dict` (`utf-8-sig`). Test: `test_write_debug_dump_zip_accepts_utf8_bom_config`. Live UI acceptance verified.

### 2.6.r re-check — quality gate before alpha.11 (2026-09-29)

- [x] **2.6.r re-check** on `main` (pre-candidate **2.6.0-alpha.11**; skill `quality-gate`; no `version.py` bump in chapter)
  - [x] Coverage baseline — **2728** passed / **14** skipped; overall **80.7%** (`data` 72.5, `ehal` 90.7, `house_config` 81.2, `optimizer` 86.0, `runtime_store` 79.8, `settings` 78.1, `simulation` 87.3); no package &lt; 40% (vs prior re-check 81.2% / 2638 passed)
  - [x] Dead-code / obsolete-test — vulture `--min-confidence 80` **0** hits; `--dead-fixtures` clean (“every declared fixture is being used”)
  - [x] Simplification — no behavior-changing removals this pass (prior 2.6.r remediations stand); SSRF allowlist in `ha_addon_smoke` is a security fix, not a simplify step
  - [x] KPI — split `scenario_editor_sections` → `scenario_editor_tariffs` (was **666** LOC); split 5 bodies &gt; 60 (`pv_forecast._check_and_fetch_api_data`, `history_timeline.build_chart_history`, `setup_readiness.missing_runtime_scenario_items_for`, `scenario_form_helpers.read_scenario_form_snapshot`, `page_daemon.render`); **0** files &gt; 600 / **0** bodies &gt; 60 after
  - [x] Official docs — Doc-Review-Checklist alpha.11 sync (Monitor Sankey order, Silent/Loud, green-zone OLS spec, Festpreis in `tarife-quellen`, German `overview.md`, Shadow S1 status)
  - [x] SonarCloud snapshot — Actions [36555037600](https://github.com/JochenTCC/Earnie/actions/runs/36555037600) @ `dd10387`: scan **HTTP 403** (informational infra; suite had already passed on previous flaky Open-Meteo runs after mock in PR #22). No new code bugs/vulns recorded this pass; prior SSRF `S8703` fixed locally in this commit

### Document Review Doc↔code sync alpha.11 (2026-09-29)

- [x] Monitor layout: Chart 1 → Nav → Sankey → Chart 2 (`charts.md`, `betriebsmodi.md`, `ui-sunset2sunset.md`, `ui-menu-structure.md`)
- [x] Handbuch Silent/Loud on Optimierer-Dienst (not „Silent vs Live“ only under EHAL-Com); checklist Silent → Loud
- [x] Spec green-zone prices: OLS/`forecast` default, Phase 3 live done (`price-forecast-renewables.md`)
- [x] `betriebsmodi.md` Silent/Loud toggle under Daemon Control; `tarife-quellen.md` Eigener Festpreis / `__user_fixed__`
- [x] `overview.md` German; Shadow TOC/spec status S1 shipped (S2+S3 → **2.7.f**)

### Bugfix ha_addon_smoke SSRF S8703 (2026-09-29)

- [x] **Remaining SonarQube issue: SSRF via LLM-supplied CLI arguments in `ha_addon_smoke._health_ok()`** (`pythonsecurity:S8703`) — Allowlist scheme/host/path before `urlopen` (`_safe_local_health_url`, `health_check_url`); non-loopback URLs never reach the sink. Tests in `test_ha_addon_smoke.py`. Verified.

### Bugfix SonarCloud coverage failure (2026-09-29)

- [x] **Check last SonarCloud failure during coverage testing on Github** — Checked and verified fixed (remaining open finding tracked separately: SSRF `pythonsecurity:S8703` in `ha_addon_smoke._health_ok()`).

### Silent toggle affects running daemon (verified) (2026-09-29)

- [x] **Check whether Silent Modus Switch on Optimierer-Dienst impacts a running daemon** — Yes: same `local_settings.json` path (UI write + daemon reload); no process restart needed. Next `main()` cycle after toggle picks up `silent_mode` (`is_silent_mode` false→true across pid 44400 after UI wrote silent). Mid-cycle writes already decided for the current run stay unchanged until that next cycle.

### Minor Monitor Sankey order + Silent/Loud UI toggle (2026-09-29)

- [x] **Monitor: Sankey under Chart 1** — Order Chart 1 → S2 nav → Sankey → Chart 2 → Simulation Details → Energievergleich (`ui/live_mode.py`; Sankey removed from `page_cockpit.py`).
- [x] **Optimierer-Dienst Silent/Loud toggle** — `st.toggle` persists `silent_mode` in `runtime/local_settings.json` (`write_silent_mode_to_local_settings`); disabled under `EARNIE_SHADOW=1`; docs `betrieb.md` / `ehal-com.md`; tests `test_local_settings.py`.

### Minor SE Chart NNE on import price (2026-09-29)

- [x] **SE analysis charts: show volumetric Netznutzung AP on import price** — Already correct: Chart 1 Preis is matrix `k_act` (NNE via `netzentgelt_override` before VAT). No UI change; regression `test_se_chart_strompreis_includes_netznutzung` locks chart field == `k_act` with NNE > without.

### Bugfix Dynamic tariff green-zone mirroring (2026-09-29)

- [x] **Dynamic tariff green-zone prices used mirroring instead of OLS** — Prod lacked `price_model_coefficients.json` (gitignored `data/cache/`); live features archive-only so future slots always mirrored. Shipped model `share/data/price_model_coefficients.json`; live features via Open-Meteo forecast weather + hour-of-day EU power stand-in (cached). Shadow acceptance verified (`price_source=predicted`).

### Bugfix Monitor Chart 2 daily Kosten KPIs (2026-09-29)

- [x] **Monitor Chart 2 daily Kosten KPIs** — SA-day annotation columns (full span = two cols; segment = visible day); plan-based **Ersparnis bisher** in gray zone. Live fix: gray slots overlay log `savings_snapshot` plan costs (`_overlay_history_plan_costs`) so BL−Opt cumulates SA₀→now instead of MILP fill zeros. Tests: `test_chart_day_costs` / `test_build_display_savings_series_overlays_history_plan_in_gray_zone`. Live Monitor acceptance verified.

### Bugfix False “Zwangs-Entladen nicht ausgeführt” (2026-09-29)

- [x] **False “Zwangs-Entladen nicht ausgeführt”** (`debug_dump_20260923_201155`) — Deviation uses full-entry `closed_by` (not `by_slot` winners); `battery_power_below_tolerance` = Ist ≤ tol only (S6 “nicht ausgeführt”). Tests: `test_deviation_timeline` / `test_deviation_eval`. Dump evening 19:15–19:45 cleared; live Monitor acceptance verified.

### Bugfix monthly_table slot_datetime (2026-09-29)

- [x] **`monthly_table` import: Monitor/`main.py` ValueError `slot_datetime`** — Fix: `epex_to_brutto_cent(..., slot_datetime=)` forwarded from `resolve_market_slots` (and mirrored/predicted paths). Test: `test_resolve_market_slots_monthly_table_passes_slot_datetime`. Live HA-Addon acceptance verified.

### Bugfix HA EHAL scan 401 (2026-09-29)

- [x] **HA dog fooding: Scan fehlgeschlagen HTTP 401** on EHAL page (HA-Addon Local Dev) — not a code defect; wrong / stale Long-Lived Access Token in the form. Correct token → Entities scannen OK. No code change; no PATCH.

### 2.6.p — Absent / holiday mode via EHAL on all backends (2026-09-29)

- [x] **2.6.p — Absent / holiday mode via EHAL on all backends**
  - `read_ehal_absent_mode` dispatches on active backend (Loxone Merker / HA entity via aggregate / OpenEMS `component/Channel`); shared binary parse (`on`/`off`/0/1/…)
  - HA: `TELEMETRY_BINARY_OPTIONAL` → `HA_ALL_FIELDS`; `MAPPABLE_DOMAINS` includes `binary_sensor` / `input_boolean`; not in EhalTelemetry wire schema
  - Same effective OR semantics (Monitor + live MILP opt-out / Haus-Wärme); OpenEMS HITL plant mapper still out of scope
  - Tests: `tests/test_absent_mode.py` per-backend reads; docs caveat removed (`flexible-verbraucher.md`, `betriebsmodi.md`, handbook, `ha-evcc.md`, `ehal-com.md`)

### Document Review docs↔code sync (2026-09-29)

- [x] Manual Todo: Review updated docs (German user docs + release/HA wording) — `README.md`, `container.md`, `DEVELOPER.md`, `ehal-com.md`, `loxone-signals.md`, `ha-evcc.md`, `ehal.md`, `doc_links.py`, issue template
- [x] Update documents in Earnie-Projekt repo with current achievements — `Communication/CLAUDE.md`, Entwicklungsplan (Härting / HA-Kompat / Addon / Master-Plan), Businessplan MCP wording, FB Status-Update historical note

### User-fixed tariffs — Eigener Festpreis (2026-09-28)

- [x] **User-fixed import/export tariffs** — Scenario-local Cent/kWh via dropdown **Eigener Festpreis** (`__user_fixed__`); values in `backtesting_scenarios.json` (`user_import_cent_kwh` / `user_export_cent_kwh`), not `tariffs.json`
  - Store resolve + plausibility + setup readiness; schema fields; Scenario Editor edit fields; German docs (`preise.md`, Benutzer-Handbuch)
  - Tests: `tests/test_user_fixed_tariffs.py`
  - Follow-up (open): non-fixed / scheduled own tariffs under **Data & tariff fidelity - Part 2**

### 2.6.o — Shadow Mode S1: Prod feed recorder (2026-09-28)

- [x] **2.6.o — Shadow Mode S1 (Prod recorder)** — Spec: [`docs/dev/shadow-mode.md`](../docs/dev/shadow-mode.md) (Epic **Shadow**; S1 only). Ships in a **2.6** Prod build so Dev can feed Shadow during **2.7**.
  - Opt-in `"shadow_feed_enabled": true` (+ optional `"shadow_feed_retention_days"`, default 14) in Prod `local_settings.json`; default off; ignored + warning if `EARNIE_SHADOW=1`
  - Record raw backend responses at transport primitives (Loxone `fetch_loxone_raw_value` / `_fetch_loxone_io_all`, HA `HaAdapter._get_json`, OpenEMS GET, `ext:pv_forecast` / prices / outdoor, optimize-trigger events) — no secrets/auth in records
  - Feed layout under `{config_dir}/shadow_feed/` (`meta.json`, atomic `latest.json`, daily JSONL + retention); override `EARNIE_SHADOW_FEED_PATH`
  - Superset after cycle writes (soft-fail, ≤10 s budget): **HA default = config-referenced entities only** (not full `/api/states`); Loxone IOs / OpenEMS channels from shared bindings
  - Failure isolation: recorder never breaks Prod (wrap + rate-limited warnings)
  - Tests: per-primitive ok/error, no secrets, atomic `latest.json`, JSONL rotation/retention, recorder exception does not break `main()`
  - **Not in this letter:** Shadow replay / write block / UI / seed (**2.7.f**); Soll/Soll diff & offline JSONL replay (S4 → **2.+1**)

### Tariff catalog: monthly curve updater + scan runbook (2026-09-28)

- [x] **`monthly_seed`** on catalog `monthly_table` tariffs (schema + `data/monthly_float_rates.build_seeded_monthly_rates`): OeMAG-proportional floats (OeMAG, Energie AG Team Sonne, EVN, Wien Energie, Tibber) and RefMarkt-based VKW PV-Flex; replaces seed factors that only lived in `notes`
- [x] **`scripts/update_tariff_curves.py`**: upsert OeMAG / E-Control RefMarkt PV months, recompute seeded tariffs, `--set` for unseeded tables (SUNNY), `--check` drift gate (test asserts the shipped catalog matches its seeds)
- [x] Catalog caught up: OeMAG 2026-07/08 (6.146 / 8.997), RefMarkt PV 2026-07/08 (6.85 / 9.42, E-Control xlsx), SUNNY 2026-09 (8.989); VKW PV-Flex placeholders replaced; `catalog_as_of` now an ISO date
- [x] Runbook `docs/spec/tariff-monthly-scan.md` for the monthly cloud routine (first AT working day, 17:00 Vienna; branch + PR, stage B findings report-only)

### Bugfix Docker missing share/ehal (2026-09-27)

- [x] **Docker image missing `share/ehal` schemas** — S6470 explicit COPY only shipped `share/config/`; live EHAL validation failed every ~30s (`EHAL schema not found: /app/share/ehal/telemetry.schema.json`). Fixed in `docker/Dockerfile` (`COPY share/ share/`); verified on NAS with **2.6.0-alpha.8**.

### Bugfix SonarCloud leak-period QG (2026-09-27)

- [x] **SonarCloud leak-period QG** — Closed as open verification (2026-09-27). Historical: re-check 2026-09-26 on `main` @ `64b151c` (Actions [36225774457](https://github.com/JochenTCC/Earnie/actions/runs/36225774457)): QG **ERROR** — `new_bugs` **1**, `new_vulnerabilities` **19**, `new_reliability_rating` C, `new_security_rating` C, `new_coverage` ≈ **66%**. Remediations verified; remaining follow-ups obsolete:
  - [x] Verified — Cleared previously: `bump_ha_addon.py` python:S3923; secrets:S7636; `.devcontainer` docker/shell
  - [x] Verified — Fixed locally: `ha_units.py` S1244; Actions SHA pins + job permissions (`qemu-image-smoke` / `release-publish`); `report_repo_stats.py` path/URL guards; intentional NOSONAR for mock HTTP + add-on root
  - [x] Verified — Accepted (CLI threat model): `pythonsecurity:S8707` / `S8705` ignored project-wide via `sonar.issue.ignore.multicriteria` in `sonar-project.properties` (also `scripts.sonar_ignore_llm_cli_rules` + `SONAR_TOKEN` to mirror in SonarCloud Analysis Scope); `# NOSONAR` on scripts/tools remains as belt-and-suspenders
  - [x] Verified — Dockerfile S6470: replace `COPY . .` with explicit package/app copies; tighten `.dockerignore`
  - [x] Verified — `remote_backtesting_support` S2083: validate absolute share roots + relative `result_dir`
  - [x] Obsolete — Still failing / accept after scan: `release-publish.yml` `pip install -r requirements.txt` (S8541 / S8544 — `--only-binary=:all:` breaks local package `.`); `new_coverage` informational
  - [x] Obsolete — Optional follow-ups: raise new-code coverage; `ui/chart_trace_segments.py` S3923 if still open; confirm S8707/S8705 gone after next Sonar analysis

### 2.7.a — Export power limitation (2026-09-26)

- [x] **2.7.a — Export power limitation** (Live / MILP / EHAL; HK static cap) — code on `feature/2.7` (`46918e8`)
  - Hard ceilings (kW): effective export cap = `min` of active sources (HK `plant.max_export_power_kw`, inbound EHAL `get_grid_export_power_limit`, pay-to-export → 0); MILP `p_grid_sell` constraint
  - Soft / economic: positive export tariffs prefer avoiding export (objective), separate from hard ceiling
  - Outbound `set_grid_export_power_limit` + ESS mode Einspeisesperre (**3**); Loxone VI/VO templates + greenfield/recipe maps; HA/OpenEMS adapters
  - Helpers: `optimizer/export_power_limit.py`, `optimizer/live_export_limit.py`; HK UI `ui/house_config_plant.py`; tests `test_export_power_limit` / `test_live_export_limit` / `test_milp_export_cap`
  - Live-test dogfood closed 2026-09-30 (Loxone wiring archived 2026-09-29)

### Release approval gate — candidate → approve → publish (2026-09-26)

- [x] **`release-publish.yml` two-step release:** tag push builds a candidate only (`build_container --versioned-only` → `:<version>`; GitHub Release as draft); job `promote` (environment `release-approval`, required reviewer) sets `:next` / `:latest` (`build_container --promote`, `buildx imagetools` retag) and publishes the release; `publish_ha_addon` runs only after approval. `release` fails early if the environment has no required-reviewer rule.
- [x] **Pre-gate checks:** `addon_smoke` (`scripts/ha_addon_smoke.py` — Supervisor-like start of `earnie-addon-{arch}:<version>`, Streamlit health, `config.json` under `/config`; amd64 blocking, aarch64 QEMU soft), `addon_lint` (dry pin bump + addon-linter). Verified locally: alpha.6 OK, alpha.5 FAIL (`No module named 'config'`).
- [x] Docs: `DEVELOPER.md`, HA add-on README (*Test a release candidate* — local add-on `earnie_dev` on the candidate image), LoxBerry README (pinned channel for candidate tests), branching playbook.

### 2.6.0-alpha.6 pre-release (2026-09-26)

- [x] **HA add-on start crash** (`ModuleNotFoundError: No module named 'config'`): restore `COPY config.py` after S6470 explicit Dockerfile COPY; honor `EARNIE_CONFIG_PATH=/config` when `EARNIE_INSTALL_CONTEXT=homeassistant_addon` (addon_config vs `/data/earnie_env` runtime split)
- [x] Bump `version.py` + alpha compose pins to **2.6.0-alpha.6** (branch `bugfix/alpha.5-config-module` from `v2.6.0-alpha.5`)

### 2.6.0-alpha.5 pre-release (2026-09-26)

- [x] Publish community pre-release **2.6.0-alpha.5** (`version.py` + alpha compose pin + tag `v2.6.0-alpha.5`) — same payload as failed **alpha.4** plus HA add-on Dockerfile fix (NOSONAR off `FROM` line; BuildKit parse error)

### 2.6.0-alpha.4 pre-release attempt (2026-09-26)

- [x] Tag `v2.6.0-alpha.4` pushed; main GHCR image built; **GitHub Release aborted** — HA add-on H6 step failed on inline `# NOSONAR` after `FROM` (fixed in `d2b8c71`, superseded by **alpha.5**)

### 2.6.r re-check — quality gate progress (2026-09-26)

- [x] **2.6.r re-check** on `main` @ `64b151c` (+ local remediations; ships in **2.6.0-alpha.4**) — completed steps; SonarCloud snapshot closed 2026-09-27 (also `### Bugfix SonarCloud leak-period QG`)
  - [x] Coverage baseline — 2638 passed / 14 skipped; overall **81.2%** (`data` 73.6, `ehal` 90.5, `house_config` 81.0, `optimizer` 85.8, `runtime_store` 80.9, `settings` 77.5, `simulation` 87.3); no package &lt; 40% (vs 2.6.r 80.9% / 2500 passed)
  - [x] Dead-code / obsolete-test audit — `vulture` (confidence 80) clean after re-export keep for `ui_chart_zone_indices`; `pytest --dead-fixtures` clean; health-report flags = expected mock-heavy
  - [x] Simplification triage — deferred to follow-up item below (no in-gate rewrites this pass); **step 3 applied** in follow-up
  - [x] KPI mega-files — **0** core/UI files &gt; 600 LOC
  - [x] KPI functions — split `derive_control_from_milp_plan`, `_add_power_balance_and_soc_dynamics`, `render_ehal_ha_mapping_section` → **0** bodies &gt; 60 LOC
  - [x] Official docs — `Doc-Review-Checklist.md` §2.6.0 still current; no new Document Review Findings this pass
  - [x] **SonarCloud snapshot** — pre-fix QG **ERROR** (`new_reliability_rating` C, `new_security_rating` C, `new_coverage` 66%); last successful analysis pre-remediation `@271a6a3`; CI red was pytest before scan (UNC share-root). Closed 2026-09-27: remediations verified; coverage / remaining QG noise obsolete (informational — do not chase as in-gate):
    - [x] Verified — CI blocker: Windows UNC + POSIX absolute `share_root` / `remote_share_root` (`scripts/remote_backtesting_support.py`); NOSONAR on post-`_safe_join` sinks (S2083 / S6549)
    - [x] Verified — `python:S1244` float eq in `integrations/ha_units.py`; `python:S1764` NaN check in `house_config/known_chart_display.py` (`math.isnan`)
    - [x] Verified — SHA-pin Actions in `release-publish.yml` + `qemu-image-smoke.yml`; job-level permissions (S8233)
    - [x] Verified — path/URL hardening in `scripts/report_repo_stats.py` (S8707 / S8703)
    - [x] Verified — `docker/Dockerfile` explicit COPY (S6470) + tighter `.dockerignore`
    - [x] Verified — Ignore (sonar-project.properties multicriteria): LLM CLI S8707/S8705; pip unlock S8541/S8544 (local `.` package); lockfile S8565; container root S6471; Loxone/lab HTTP S5332
    - [x] Verified — Marked intentional: mock REST HTTP (`house_sim/mock_rest.py`), HA add-on root (comment NOSONAR; inline on `FROM` breaks BuildKit)
    - [x] Obsolete — Sonar `new_coverage` 66% / QG ERROR on coverage alone until gate policy relaxed in SonarCloud UI
- [x] **Simplify redundant / unnecessarily complex / unneeded code** (quality-gate step 3; no behavior change)
  - **Removed:** `_anchor_fraction_from_legacy_shift`; unused `ui/charts.py` late re-exports (~70) + dead `render_optimization_chart`; `simulate_24h_horizon`; `_var_value_at_zero`; `_consumer_power_now` / `_consumer_pv_follow_now` (+ milp_consumers re-exports); inlined `_optimization_interval_hours`, `is_generic_flex_consumer`, `_bundle_flex_context`; EV schedule checks via `charging_schedule_enabled`; inlined `charge_immediate_io_name` → `marker_charge_immediate`; dropped `get_runtime_scenario_refs` / `save_runtime_scenario_refs` (callers use live_* names)
  - **Leftover scan:** no large commented-out blocks / `_backup`/`_tmp_*` in `optimizer/`/`simulation/`/`ui/`
  - **Verify:** 149 chart + 25 generic-flex/horizon + 94 planning/eauto/charge_immediate tests passed

### 2.6.n — Battery controllability + Huawei force services (2026-09-26)

- [x] **2.6.n — Battery controllability in `house_config` + MILP**
  - [x] **House config:** `batteries[].control` = `full` \| `limits_only` \| `read_only` (default `full`); schema, normalize/resolve, UI, `battery_params`, backtesting.
  - [x] **MILP:** `limits_only` envelope (no grid charge / no battery export); `read_only` self-consumption residual coupling; modes Automatik/Entladesperre only for limits; no setpoints for read_only.
  - [x] **Cross-check:** EHAL-Com warns when `control` exceeds `ess_limits` / `ess_active` (entity or `plant.ha_ess_force`).
  - [x] **Deviation:** forced-mode predicates gated on `control == full`.
  - [x] **Huawei HA services:** `plant.ha_ess_force` → `huawei_solar.forcible_charge` / `forcible_discharge` / `stop_forcible_charge` (Elevate permissions); enables `ess_active` without `set_ess_active_power` entity.
  - [x] Tests: `tests/test_battery_control.py`; docs `ehal.md`, `ehal-com.md`, `batterie-pv.md`; HouseSim `huawei_en` meta note.

### 2.6.e — Stronger HA propose / vendor name recognition (2026-09-26)

- [x] **2.6.e — Stronger propose, still confirm-before-save.** Empty entity-scoped map + HouseSim S2 archetypes: token-boundary name hints, longer-hint ranking (uncapped for ties), unique best score or leave empty; vendor vocab (Huawei / Fronius DE / SMA / go-e / KEBA). No LLM; empty-only UI unchanged. Module: `integrations/ha_ehal_mapping.py`.
  - [x] Hit rates (correct / golden, 0 wrong): `evcc_en` 13/13, `fronius_de` 9/9, `huawei_en` 11/11, `sma_keba` 11/11. Distractors never proposed (`inverter_active_power`, SMA `…_grid_power`, Fronius `leistung_verbrauch`).
  - [x] Tests: `tests/test_ha_ehal_mapping.py` (all archetypes ⊆ golden; vocab examples; token-boundary unit cases). Spec note: `docs/spec/ehal.md`.

### 2.6.m Sprint 4 — startup checks + runtime monitoring (2026-09-26)

- [x] **2.6.m — Sprint 4: startup checks + runtime monitoring** (ships with the next path **B**/**C** publish).
  - [x] **H1** `docker/cpu_check.sh` → `docker/preflight.sh`: abort on non-writable config/runtime and clock before image `BUILD_DATE` (NTP wait up to 30 s); warn on RAM < 2 GB / free disk < 500 MB. `ARG BUILD_DATE` + `scripts/build_container.py --build-arg`. Tests: `tests/test_container_cpu_check.py`.
  - [x] **H4** `HEALTHCHECK` in `docker/Dockerfile` (`/_stcore/health` via `EARNIE_UI_STREAMLIT_PORT`, default 8501 / add-on 8502) + `runtime/daemon_heartbeat.json` from `main.py`; no `config.yaml` `watchdog:` (addon-linter obsolete — Supervisor uses image HEALTHCHECK); LoxBerry `healthcheck` WARN on `.State.Health.Status=unhealthy`. Tests: `tests/test_daemon_heartbeat.py`.

### 2.6.j H0 — x86-64-v2 preflight shipped (2026-09-26)

- [x] **2.6.j — Sprint 1 complete** (remaining open item was **H0** ship only; code/workflow archived earlier the same day).
  - [x] **H0** Ship x86-64-v2 preflight with image publish — landed in community **`2.6.0-alpha.2`** / current channel pin **`2.6.0-alpha.3`** (`docker/cpu_check.sh` via `docker/entrypoint.sh`; add-on docs link). Closes the open checkbox under Sprint 1 in [Backlog.md](Backlog.md).

### H11 (verify) Gen2 HTTP vs HTTPS-only (2026-09-26)

- [x] **H11 (verify)** Gen2 Miniserver (live): `http://…/jdev/sps/status` and `http://…/data/LoxAPP3.json` still answer over plain HTTP (401 auth, not TLS-only / refused). Hard-coded `http://` in `integrations/loxone_client.py` remains OK — **no H11 (fix)** / no schema or fingerprint change.

### 2.6.l Sprint 3 — network Loxone + HA (2026-09-26)

- [x] **2.6.l — Sprint 3: network (Loxone + HA)** (ships in community pre-release **`2.6.0-alpha.2`**).
  - [x] **H9 (fix)** `EARNIE_LAN_SUBNET` (+ LoxBerry install sync / compose `.env`); Docker `172.16.0.0/12` gate with SB CIDR prompt; HA add-on host IP via Supervisor `/network/info`.
  - [x] **H10** Last Miniserver callback (time + peer IP) on SB / EHAL-Com (`runtime/loxone_last_callback.json`); docs bridged VM + fixed IP / DHCP reservation.
  - [x] **H8** SB: on Docker bridge (non–add-on) offer HA URL + LLAT instead of empty mDNS-only path; `docs/einrichtung/container.md` § Netzwerk.

### 2.6.k Sprint 2 — release pipeline + version channels (2026-09-26)

- [x] **2.6.k — Sprint 2: release pipeline + version channels** (concept doc §3). Code on `main`; ships with the next publish after **2.6.m** (no mid-sprint tag).
  - [x] **GHCR `:next`** on every release (stable + pre-release) via `scripts/build_container.default_tags` + `release-publish.yml` notes.
  - [x] **LoxBerry channels** `stable` / `prerelease` / `pinned` (**H13**): `plugin.env` (`EARNIE_CHANNEL`, `EARNIE_PINNED_VERSION`, `EARNIE_AUTO_UPDATE`), `sync_compose_env.sh`, compose `${EARNIE_IMAGE_TAG}`, Web UI + GitHub releases list, daily `earnie-update.timer`, `postupgrade` default `stable`.
  - [x] **HA `addon_config` migration** (§3.4): `EARNIE_CONFIG_PATH=/config`, runtime `/data/earnie_env/runtime`, idempotent copy in `run.sh`. Live backup/restore of `addon_config` remains a dogfood gate on next HA install.
  - [x] **HA add-on `earnie_prerelease`** (**H12** final): dual trees in Earnie packaging + `ha-addon-earnie`; official bumps both, pre-release only prerelease; `hassio_api` mutual-run guard; docs „Stabile Version oder Vorabversion“.
  - [x] **H6** Prebuilt `ghcr.io/jochentcc/earnie-addon-{arch}:<version>` + `image:` in both `config.yaml` (CI build on release).
  - [x] **H2** QEMU smoke workflow (`qemu-image-smoke.yml` + `scripts/qemu_image_smoke.py`; called from release with `continue-on-error`).
  - [x] **Downgrade warning**: `runtime/last_run_version` + log + Streamlit warning (`runtime_store/version_track.py`).

### 2.6.j Sprint 1 — installation safeguards (code) (2026-09-26)

- [x] **2.6.j — Sprint 1 code/workflow** (H0 ship closed 2026-09-26 with published image — see section above; H11 verify closed 2026-09-26 without code change).
  - [x] **H12 (stopgap)** `release-publish.yml` job `publish_ha_addon` runs only when `prerelease != true`; manual `ha-addon-publish.yml` refuses versions containing `-`. Docs: packaging README, `DEVELOPER.md`, `docs/einrichtung/homeassistant-addon.md`, `ha-addon-earnie` README/BACKLOG. Dual channel = **2.6.k**.
  - [x] **H3** LoxBerry plugin compose `restart: on-failure:3` (`packaging/loxberry/data/docker/docker-compose.yml`).
  - [x] **H5** LoxBerry `TZ: ${TZ:-Europe/Vienna}`; `sync_streamlit_env.sh` + PHP write host `/etc/timezone` into compose `.env`; note in `docs/einrichtung/loxberry-plugin.md`.
  - [x] **H7** Add-on `startup: application`; `wait_for_supervisor_core()` in `integrations/ha_supervisor.py`; daemon `maybe_auto_start` waits before starting `main`. Tests in `tests/test_ha_supervisor.py`.
  - [x] **H9 (verify)** Confirmed for OpenEMS `full_active`: `local_ipv4_hosts_for_scan()` uses container IP `/24` (unit test mocks `172.17.0.2` → Docker subnet). Loxone/HA discovery is SSDP/mDNS (separate bridge issue). Fix remains **2.6.l H9 (fix)**.

### HouseSim S2 — Vendor archetypes (2026-09-26)

- [x] **HouseSim S2 — 2–3 more hand-authored archetypes on the same physics; write-back per archetype.** Three archetypes (vendor choice by AT/DE market share), entities checked against the integration source code; provenance, verified and unverified points per archetype in `meta.json`. Spec: [`docs/dev/house-sim.md`](../docs/dev/house-sim.md) § S2.
  - [x] `fronius_de` — Fronius GEN24 Plus + BYD HVS (Core `fronius`) + Fronius Wattpilot (HACS `goecharger_api2`): German entity ids/names, energy counters in **Wh**, no ESS setpoints (read-only), wallbox mode as `select`.
  - [x] `huawei_en` — Huawei SUN2000 + LUNA2000 + DTSU666 (HACS `huawei_solar`) + go-e Gemini: vendor sign (meter + = export, battery + = charge → `negate`), only charge/discharge **limits**, SoC as "state of capacity", battery totals `state_class: total`.
  - [x] `sma_keba` — SMA Sunny Tripower Smart Energy (Core `sma`) + KEBA P30 (Core `keba`): mixed language, **kW** power and kW setpoint/limit helpers (DIY Modbus `input_number`), SMA split channels behind signed template sensors, distractor `…_grid_power`, wallbox without writable current, no heat pump.
  - [x] Core (`house_sim/core/`): unit-aware (W/kW, Wh/kWh) and vendor-sign projection, unit-aware setpoint read, `ess_fallback: self_consumption`, `derived_entities` for split channels; mock REST rejects out-of-range values / invalid options like HA; S4 `select` platform + `state_class: total`; sync copy updated.
  - [x] **Bugfix:** grid balance had the wrong battery sign since S1 (`load − pv + ess` → `load − pv − ess`; discharging raised grid import). Regression test added.
  - [x] Triggered on the Earnie side: HA unit-aware mapping and function completeness check (entries below). Propose baseline for **2.6.e**: `evcc_en` 13/13, `fronius_de` 3/9, `huawei_en` 0/11, `sma_keba` 3/9 correct; no physically impossible proposals.
  - [x] Tests: `tests/test_house_sim_s2_archetypes.py` (closed loop via mock REST + `HaAdapter` per archetype).
  - Not included: wallbox writes (`amp` / `frc`) acting on physics — open as **HouseSim wallbox write-back** in [Backlog.md](Backlog.md).

### EHAL function completeness — unavailable until fully mapped (2026-09-26)

- [x] **Function completeness check** (user proposal; robustness). New `ehal/functions.py` (backend-agnostic): a function is `available` only when all its required EHAL fields are mapped, `incomplete` when partly mapped (warning), `not_configured` when nothing is mapped. **Speicher zwingen** stays `not_configured` until `set_ess_active_power` itself is mapped, so a limits-only plant does not warn. Functions: Grundtelemetrie; **Speicher begrenzen** (both limits); **Speicher zwingen** (active power **plus** both limits — without limits Earnie cannot return safely to Automatik); **Wallbox-Ladestrom**; **Slot-Ist aus Energiezählern** (PV + import + export). Becomes available again as soon as the mapping is completed (adapter rebuilt on save).
  - [x] **Bugfix:** `HaAdapter` treated an unmapped `set_ess_active_power` as a write failure and switched off all ESS writes (Huawei-style limits-only installs lost the working limits after the first Zwangsmodus). Now fields of unavailable functions are **skipped** (logged once per session), only real write failures degrade capabilities.
  - [x] Adapters: `HaAdapter` and `LoxoneAdapter` derive `supports_ess_write` / `supports_evcs_current` (+ internal active-power flag) from function availability; `last_skipped_fields()` lists only fields of an **incomplete** function. Unmapped mode fields (`set_ess_mode` / `set_evcs_mode`) and never-configured functions are not written and not shown in Live-Schreiben (logged once). Loxone previously failed fast on an unmapped EVCS mode and degraded EVCS. `ha_meter_energy` returns no counter readings unless all three counters are mapped.
  - [x] Live trace: `build_ehal_write_records(..., skipped=)` marks dropped setpoints of incomplete functions; Live-Schreiben shows **Übersprungen** with „Funktion nicht verfügbar (Mapping unvollständig)“.
  - [x] Mapping UI (HA + Loxone, `ui/ehal_function_status.py`): warning per incomplete function with missing fields (German labels) and a caption of available functions; saving stays allowed.
  - [x] HouseSim `sma_keba` got kW charge/discharge limit helpers (complete DIY setup). Existing configs checked (alpha env, greenfield, debug dump, examples): no function lost.
  - [x] Tests: `tests/test_ehal_functions.py` (states, scope, messages, HA limits-only on `huawei_en`, active-only HA/Loxone, partial counters, skipped records, unmapped modes), `tests/test_loxone_adapter.py` (mode skip). Full suite 2573 passed / 6 skipped.
  - Follow-up in [Backlog.md](Backlog.md): **2.6.n** battery controllability in `house_config` + MILP.

### HA unit-aware mapping — physical quantity check + runtime conversion (2026-09-26)

- [x] **HA unit-aware mapping** (prep for **2.6.e**; user proposal). Two rules for HA bindings, shared module `integrations/ha_units.py` (EHAL field → quantity power / energy / percent / current; base units W / kWh / % / A):
  - [x] **Rule 1 — only physically compatible signals.** `unit_check` (unit + `device_class`): W↔kW↔MW ok, kW↔kWh / %↔W / VA rejected. `heuristic_propose` drops incompatible rows (sensors without unit are not proposed for quantity fields; unitless `number`/`input_number` helpers stay allowed). EHAL-Com HA mapping (`ui/ehal_ha_mapping.py`) offers only compatible scan rows per field and refuses to save a mismatching binding (`binding_unit_issues`). Modes/flags stay unconstrained.
  - [x] **Rule 2 — factor from `unit_of_measurement` at runtime, never stored.** Read: `HaAdapter` converts every mapped field (was kW→W only); a wrong-quantity unit raises `UnitMismatchError` (required field → error, optional → skipped + warning). Write: setpoints are converted EHAL W/A → target entity unit, read fresh from HA before each write (fixes W written into kW helpers); mismatch → write error without service call. Energy counters (`ha_meter_energy`) accept Wh/kWh/MWh and skip non-energy units. EHAL-Com Schreibtest read-back uses the same conversion. UI shows the automatic conversion per binding (e.g. `kW → W (×1000)`).
  - [x] **Evidence on HouseSim S2 archetypes** (`fronius_de`, `huawei_en`, `sma_keba`): before, propose suggested the Huawei SoC (%) as battery power; now no proposal crosses quantities on any archetype (hit rate unchanged — name hints are **2.6.e** scope). `sma_keba` kW setpoint (`input_number.batterie_sollleistung`) now written as kW (former xfail).
  - [x] Tests: `tests/test_ha_units.py` (new), `tests/test_ha_adapter.py` (unit GET mocked; kW write, wrong-quantity write/read), `tests/test_ha_meter_energy.py` (MWh, W rejected), `tests/test_house_sim_s2_archetypes.py`. Full suite 2561 passed / 6 skipped.

### Bugfix HA add-on crash loop on CPUs without x86-64-v2 (2026-09-26)

- [x] **HA add-on 2.5.3 crash loop — `RuntimeError: NumPy was built with baseline optimizations (X86_V2)`** (dump 20260925; HA OS VM, most likely Proxmox CPU type `kvm64`). Bootstrap OK, then every start died at `import pandas` → `numpy` (NumPy ≥ 2.4 x86 wheels require x86-64-v2); Supervisor restarted it in a loop. Not fixed in 2.6.0-alpha.1 (same `python:3.14-slim` + unpinned NumPy, ships 2.5.3).
  - [x] **`numpy<2.4` pin evaluated and rejected** — Image with pin tested under QEMU user-mode `-cpu kvm64-v1`: numpy 2.3.5 / pandas without pyarrow / highspy OK, but **pyarrow 25.0.1 → SIGILL** (pandas 3 auto-imports it; Streamlit hard-depends on it). Pin reverted; x86-64-v2 is now a documented minimum.
  - [x] **Preflight in `docker/cpu_check.sh`**, called from `docker/entrypoint.sh` before bootstrap → covers all container targets (HA add-on, Synology, Proxmox, VMware). `_check_x86_64_v2` reads `/proc/cpuinfo` on `x86_64` (cx16, lahf_lm, popcnt, pni, sse4_1, sse4_2, ssse3) and exits with a German message + Proxmox fix (CPU type `host` / `x86-64-v2-AES`, cold VM restart) instead of a traceback. Add-on `run.sh` only exports `EARNIE_CPU_CHECK_DOCS_URL` (HA docs link; default = `container.md#cpu-voraussetzung-amd64`). Dockerfile strips CRLF from `cpu_check.sh`. Tests: `tests/test_container_cpu_check.py`.
  - [x] **Docs** — `docs/einrichtung/container.md` § CPU-Voraussetzung (amd64); `docs/einrichtung/homeassistant-addon.md` Go/No-Go row + Proxmox steps; add-on `DOCS.md` hint; add-on `CHANGELOG.md` Unreleased.
  - [x] **Verification / ship** — preflight in published community images (**`2.6.0-alpha.2`** / **`2.6.0-alpha.3`**); **H0** closed 2026-09-26 (see section above). Live CPU-type switch confirmation from the support-case host remains optional dogfood.

### Document Review Anwender-TOC / SB German / ehal-com EN (2026-09-26)

- [x] **`docs/README.md` = landing clone** — Restored German Anwender-TOC with **Erste Schritte** (`#erste-schritte`); paths relative to `docs/`; HA add-on / VMware / SB page linked; HouseSim only under Entwickler-Specs
- [x] **`docs/ui/smarthome-backend.md`** — Translated to German (user-doc scope)
- [x] **`docs/ui/ehal-com.md` mostly English** — Kept English by decision; exception noted in `german-user-docs.mdc`
- [x] **HouseSim absent from German user TOC** — Confirmed intentional (internal only); no Einrichtung pointer; listed under Entwickler-Specs only

### 2.6.0-alpha.1 pre-release (2026-09-25)

- [x] Publish community pre-release **2.6.0-alpha.1** (`version.py` + alpha compose pin + tag `v2.6.0-alpha.1`)

### 2.6.r Quality / release hardening (2026-09-25)

- [x] **2.6.r — Quality / release hardening** (same shape as `2.5.r` / skill `quality-gate`; no `version.py` bump)
  - [x] Coverage baseline — prep @ `43b317b`: 2500 passed / 6 skipped; overall **80.9%**; no package &lt; 40%
  - [x] Dead-code / obsolete-test audit — `vulture` (confidence 80) clean; `pytest --dead-fixtures` clean; health-report flags = expected mock-heavy + `pv_follow_name` fail-fast
  - [x] Simplification triage — mechanical unused-import removals (`simulation/engine`, `backtesting_single_window`, `ui/backtesting_display_bundle`, `chart_trace_segments`, `loxone_debug_rows`, `optimizer/consistency`, `simulation`, `milp_consumer_*`, `__init__` battery aliases); deferred needs-accept: identical helpers / charts barrel trim / `_anchor_fraction_from_legacy_shift`
  - [x] KPI mega-files — **0** core/UI files &gt; 600 LOC: `ui/charts.py` → facade + `chart_cumulative_render.py` (+ flow ghosts); `data/planning_window.py` → `planning_window_zones.py`; `optimizer/milp.py` via `milp_inputs.py`
  - [x] KPI functions — **0** bodies &gt; 60 LOC in quality-gate packages (Wave 1 + full follow-on; full hard-limit bar)
  - [x] Official docs — `Doc-Review-Checklist.md` §2.6.0 HA/HouseSim/entity-scoped; entity-scoped drift fixed in HA/user docs; issue-template placeholder `2.6.0`; 3 deferred findings → [Backlog-Bugfixes.md](Backlog-Bugfixes.md) Document Review Findings
  - [x] SonarCloud snapshot — last successful analysis [36110376214](https://github.com/JochenTCC/Earnie/actions/runs/36110376214) @ `d4ec89d`: QG **ERROR** (informational); `new_bugs` **0**; `new_vulnerabilities` **13** deferred under Bugfixes Verifications Pending / accepted triage. Post-`ddf5938` CI pulp-4 fail unblocked by pin below (refresh leak-period after push)
  - [x] **Pin `pulp` to `&lt;4`** in `pyproject.toml` (`pulp>=2.8.0,&lt;4`); local MILP smoke green on 3.3.2
  - [x] Optional near-hard pre-split (`scenario_editor_sections` ~598, `profiles_store` ~595) — **skipped** (explicit; not required for gate)

### 2.6 quality-gate prep snapshot (2026-09-25)

- [x] **Prepare quality gate** — Ran coverage / vulture / dead-fixtures / KPI / Sonar snapshot on `main` @ `43b317b`; remediations completed as **2.6.r** (archived above).

### EHAL-Com Schreibtest — bounded write + roundtrip (2026-09-25)

- [x] **EHAL-Com Schreibtest** (Secrets parity / HouseSim write-path verification). Table UI under Live-Schreiben: mapped safe probes (`set_ess_mode`, charge/discharge limits, `set_evcs_max_current`) + optional Force `set_ess_active_power` (±200 W, second confirm); batch write / Auto-Roundtrip as one setpoint; Silent gate; restore Automatik + EVCS 0 A. Core: `integrations/ehal_write_test.py` (+ bounds), UI `ui/ehal_write_test.py`. Tests: `tests/test_ehal_write_test.py`. Docs: `docs/ui/ehal-com.md` § Schreibtest. **Verified** greenfield / HouseSim HA (mode + active power; Force unlocks table row, does not auto-send).

### Bugfix EHAL-Com HA credentials save (2026-09-25)

- [x] **EHAL-Com — HA credentials editable without dedicated save.** Credentials on HA mapping (`ui/ehal_ha_mapping.py`) persist via mapping save → `write_ha_dotenv` / `adapter_id` in config (**2.6.i**); primary Anbindung remains on Smarthome-Backend. **Verified** by user 2026-09-25.

### 2.6.i — HA credentials in `.env` (Loxone parity) (2026-09-25)

- [x] **2.6.i — HA credentials in `.env` (Loxone parity).** `EHAL_HA_BASE_URL` / `EHAL_HA_TOKEN` in `config/.env` (merge-upsert with `LOXONE_*`); `ehal.backend` / `sign` stay in `config.json`. One-shot migrate strips JSON secrets (`runtime_store/ha_secrets_migrate.py`). SB + EHAL-Com write via `write_ha_dotenv`. Add-on: empty `.env` → Supervisor proxy unchanged. OpenEMS still `config.json` (follow-up). Tests: `test_dotenv_io`, `test_ha_secrets_migrate`, readiness/setup/addon. Docs/schema/snippet updated.

### HouseSim S4 — HAOS acceptance verified (2026-09-25)

- [x] **HouseSim S4 — HAOS acceptance** (concept §5 Abnahme; Spec [`docs/dev/house-sim.md`](../docs/dev/house-sim.md) § S4). Verified on live HA: sync/copy integration → restart; config flow `evcc_en` (+ weather PV); Earnie `ehal.backend=ha` via **2.6.h** EHAL-Com; read path (PV/SoC/grid±/counters — early wrong EVCS/PV bindings corrected); faults (`reject_writes` / `set_unavailable`); HA restart keeps energy counters monotonic. Write path (battery setpoint → SoC/grid) covered by **EHAL-Com Schreibtest** (verified 2026-09-25).

### HouseSim S4 — Simulated house as HA custom integration (2026-09-24)

- [x] **HouseSim S4 — Simulated house as HA custom integration.** Optional follow-up after **2.6.h** (no S2/S3). Custom integration `earnie_house_sim` for Synology HAOS / `ha_lab/haos-docker`: config flow (archetype + PV source), coordinator ticks pure core on wall clock, native `sensor` / `number` / `switch` with archetype IDs (fixture `input_number.ess_*` → `number.ess_*`), one HA device per component. Shared core `house_sim/core/` (no HA/Earnie imports; thermal Euler + weather PV + scenario overlay); used by mock REST and integration. Packaging variant 1: `scripts/sync_house_sim_integration.py` → `_core/` + `fixtures/` (generated); pytest equality + import-isolation. Energy counters `total_increasing` persisted; PV from HA `weather` `cloud_coverage` or synthetic series; services for scenarios/faults. Earnie via **2.6.h** UI unchanged. Code home `house_sim/ha_integration/custom_components/earnie_house_sim/`. Spec: [`docs/dev/house-sim.md`](../docs/dev/house-sim.md). Live HAOS acceptance → verified 2026-09-25 (Write path later covered by EHAL-Com Schreibtest).

### 2.6.h — HA EHAL-Com UX parity with Loxone (2026-09-23)

- [x] **2.6.h — HA EHAL-Com UX parity with Loxone.** Entity picker first (plant + live-profile consumers), then only that entity’s EHAL fields; save via `apply_entity_bindings` (not giant form). Reuse Loxone HITL (`build_entity_rows` / role grouping / empty-only propose). Scan HA `/api/states` once per session; suggest-and-confirm never overwrites saved bindings; no LLM. Live-Lesen/Schreiben: entity-centric Mapping column from entity-scoped. UI: `ui/ehal_ha_mapping.py`; Live helpers in `integrations/ehal_debug_mapping.py`. Tests: `tests/test_ehal_ha_mapping_entities.py` (+ HA / Live suite). Docs: `ehal-com.md`, `ehal.md`, `ha-evcc.md`.

### 2.6.g — HA bindings on entity-scoped (2026-09-23)

- [x] **2.6.g — HA bindings on entity-scoped (`house_profiles`).** Flat `ehal.ha.entities` → `plant.ehal_bindings` / EV consumer `ehal_bindings` (same §C keys as Loxone). One-shot migrator in `house_config/ha_ehal_bindings.py` via `ensure_migrated` / CLI; strip flat entities; `sign` stays in `ehal.ha`. Live: `aggregate_ha_entities` → `get_ha_adapter` (legacy fallback if empty). HITL save writes entity-scoped (`ui/ehal_ha_mapping.py`). Golden `evcc_en` map kept for heuristics; house_sim print/docs updated. Tests: `tests/test_ha_ehal_bindings.py` (+ HA suite). Docs: `ehal.md`, `ehal-com.md`, `house-sim.md`, `smarthome-backend-wahl.md`, `loxone-meter-energy-slot-ist.md`, snippet.

### 2.6.c — HA energy counters for slot Ist (2026-09-23)

- [x] **2.6.c — Energy counters (ΔkWh) for slot Ist on the HA backend.** `house_sim` cumulative `total_increasing` PV/grid± energy (∫P·Δt). Flat optional maps `sens_pv_energy` / `sens_grid_energy_import` / `sens_grid_energy_export`. Reader `integrations/ha_meter_energy.py` → same `overlay_counter_on_closed` shape as Loxone; sampler `_default_read_energy` for HA. Heuristic empty-only propose for energy fields. Battery/flex stay on sample mean. Tests: `tests/test_ha_meter_energy.py`, stepper energy assert, golden map heuristic. Docs: `loxone-meter-energy-slot-ist.md`, `charts.md`, `ehal.md`, `ehal-com.md`, `house-sim.md`.

### 2.6.b — Suggest-and-confirm HA binding (2026-09-23)

- [x] **2.6.b — Suggest-and-confirm HA binding (interim flat map).** `integrations/ha_ehal_mapping.py`: empty-only `heuristic_propose` (domain / `device_class` / unit / name tokens; no LLM; no overwrite of saved bindings). EHAL-Com HA mapping: scan → propose → confirm → save `ehal.ha.entities`. Scan rows expose attrs for scoring. Regression: `evcc_en` empty map matches golden; buffer temp / `switch.*` left out; ambiguous names empty. Tests: `tests/test_ha_ehal_mapping.py`. Interim until **2.6.g** / **2.6.h**. Spec cross-links: `docs/spec/ehal.md`, `docs/dev/house-sim.md`.

### 2.6.a + HouseSim S1 — Developer bench (2026-09-22)

- [x] **2.6.a + HouseSim S1 — Developer bench.** `house_sim/`: mock HA REST (`GET /api/states`, `GET /api/states/{id}`, `POST /api/services/{domain}/{service}` + Bearer) with fixture `evcc_en` (golden `ehal.ha.entities`, `switch.*` negative case, no WP). Short closed-loop stepper (SoC coulomb counter, synthetic PV kW series, optional `simulate_next_temp_c`). Pytest against live mock (`tests/test_house_sim_*`). Spec note: [`docs/dev/house-sim.md`](../docs/dev/house-sim.md). Concept: [HA compatibility tests](https://github.com/JochenTCC/Earnie-Projekt/blob/main/Entwicklungsplan/Earnie-HA-Kompatibilitaetstests-Entwicklungsdokument.md).

### 2.6 Phase 2 — HA/OpenEMS port UX + Loxone HTTP env override (2026-09-22)

- [x] Allow changing HTTP port for Home Assistant and OpenEMS (follow-up to Miniserver #9) — help/caption on SB Anbindung and EHAL-Com HA mapping (`ui/ehal_connection.py`, `ui/ehal_ha_mapping.py`); port remains part of `ehal.*.base_url` (no dedicated field); doc note in `docs/ui/smarthome-backend.md`
- [x] Add-on `ehal_loxone_http_port` env-override — `run.sh` exports `EARNIE_EHAL_LOXONE_HTTP_PORT`; `Config.get_ehal_loxone_http_port()` prefers env over `config.json`; packaging + `ha-addon-earnie` docs/translations; closed Entwicklungsplan open point #1; tests in `tests/test_ehal_loxone_http_port.py`

### Bugfix HA add-on Ingress cold-start page (2026-09-22)

- [x] **HA add-on Ingress cold-start page** — nginx „Earnie startet noch“ (HTTP 200) while Streamlit boots (`v2.5.3`). Dogfood verified: OPEN WEB UI immediately after add-on start shows hint page or brief HA 502, then UI.

### Add-on Version 0.2 — Options + Ingress (2026-09-22)

- [x] **Add-on Version 0.2** (Entwicklungsplan roadmap): Options-UI → `config.json` generation; Ingress (embedded UI, no separate port / no `homeassistant.local:8501` lookup)
  - Supervisor-Proxy for EHAL-HA (`homeassistant_api` + `SUPERVISOR_TOKEN` / `http://supervisor/core`) — Phase 1 discovery + auth (see also archive 2026-09-21)
  - Options → `config.json`: fresh install seeds `ehal.backend=ha`; each start merges `streamlit_port` / `ehal_loxone_http_port` from `/data/options.json` (`runtime_store/addon_options.py`, tests)
  - **Ingress (official `2.5.3`):** nginx path re-inject + start fix + cold-start page. Dogfood on Synology HAOS: OPEN WEB UI works. Checklist: [`docs/einrichtung/homeassistant-addon.md`](../docs/einrichtung/homeassistant-addon.md) § Dogfood-Checkliste. Historical: `2.5.3-alpha.4` "Not found"; `2.5.3-alpha.5` broken `sed` start abort
  - Without Ingress, OPEN WEB UI opened `http://homeassistant.local:8501` (fails when mDNS does not resolve the extra port) — Ingress removes port/IP lookup

### Bugfix HA add-on Ingress start abort (2026-09-21)

- [x] **HA add-on Ingress start abort (`20b22c55_…` log)** — `run.sh` invalid GNU sed aborted start under `set -e`. Fix: Python `str.replace` for nginx conf. Live: OPEN WEB UI works on Synology HAOS (`v2.5.3-alpha.6` / official **v2.5.3**).

### HA Add-on Phase 1 installation blockers (2026-09-21)

- [x] **Remove Loxone-only Supervisor options** — Dropped `loxone_user` / `loxone_pass` / `loxone_ip` from add-on `config.yaml` `options`/`schema`, `run.sh`, translations, and DOCS (packaging + `ha-addon-earnie`). Credentials stay in-app / `config.json`.
- [x] **HA self-discovery + Supervisor-Proxy auth** — `homeassistant_api: true`; `integrations/ha_supervisor.py` probes `http://supervisor/core/api/` with `SUPERVISOR_TOKEN`; preferred before mDNS in `discover_home_assistant()`. `get_ha_adapter` / hub ready-check resolve empty URL→`http://supervisor/core` and empty token→`SUPERVISOR_TOKEN` in add-on context (token not persisted). HA connection form makes LLAT optional in add-on.

### VMware Workstation vctl (Windows-PC) (2026-09-18)

- [x] **Earnie install path via VMware `vctl` (no Docker Desktop)** — German user doc [`docs/einrichtung/vmware-vctl.md`](../docs/einrichtung/vmware-vctl.md); helper [`scripts/run_earnie_vctl.ps1`](../scripts/run_earnie_vctl.ps1) (`up`/`start`/`stop`/`update`/…). Cross-links: `container.md`, `streamlit-ports.md`, `docker/README.md`, handbook, root/`docs` README. Same GHCR image as Synology/Proxmox prod.

### Bugfix EHAL-Com HTTP-Probe proposals overwrite existing mappings (2026-09-17)

- [x] **EHAL-Com HTTP-Probe proposals overwrite existing mappings** — Field selects used `proposal or existing binding`, so heuristic proposals could displace saved Merker when widgets were first created; Save then wrote the UI map for that entity. Fix: `resolve_field_select_default` prefers existing binding; proposal only fills unbound fields. Test: `test_resolve_field_select_default_keeps_existing_over_proposal`. Live acceptance verified (`e_auto` after HTTP-Probe).

### Bugfix EV incomplete charge (wrong EHAL bindings) (2026-09-17)

- [x] **EV not fully charged 17.09.26 ~07:45** — Prod `e_auto` ehal_bindings collided / mis-mapped: `set_evcs_mode`→`SOCMinSofort`, `set_evcs_max_current`→`MaxStrom`, `sens_evcs_active_power`→`Angeschlossen`. Overnight history showed remaining ~4 kWh at unplug while Earnie wrote mode enum into SOC-min and current into the nominal-current Merker. Fix: productive bindings corrected to `Modus` / `Soll_A` / `P_act` (reads stay on `MaxStrom` / `SOCMinSofort`); EHAL-Com label `Setpoint Wallbox-Sollstrom (A)`; Loxone verify warns on EV binding collisions (`ev_ehal_binding_collisions`). Live acceptance verified.

### 2.5.3-alpha.1 quality gate snapshot (2026-09-16)

- [x] **Quality checks before pre-release `2.5.3-alpha.1`** (`main` @ feature commit + follow-up)
  - [x] Coverage baseline — 2372 passed / 6 skipped; overall **80.5%** (`data` 73.4, `ehal` 88.8, `house_config` 78.8, `optimizer` 85.7, `runtime_store` 80.8, `settings` 77.5, `simulation` 86.5); no package &lt; 40%
  - [x] Dead-code / obsolete-test — vulture `--min-confidence 80`: **0** hits; `--dead-fixtures`: all fixtures used
  - [x] Simplification — no functional removals this pass; triage deferred
  - [x] KPI — split `house_config/profiles_thermal_annual.py` from `profiles_store.py` (**592**/600 LOC); no core/UI file &gt; 600 after split
  - [x] Official docs — absent-mode user docs already in session commit; no new Doc Review Findings
  - [x] SonarCloud — Actions run failed mid-suite (open-meteo ReadTimeout on absent normalize tests); QG **ERROR** informational (leak-period workflow/devcontainer security + coverage 75.1%); deferred items in `Backlog-Bugfixes.md`. Absent normalize tests now install Open-Meteo climate mock.

### Remove EHAL-Com "Smarthome-Merker testen" (2026-09-16)

- [x] **Remove button "Smarthome-Merker testen" on EHAL-Com** — Dropped `render_loxone_verify_results` from Live-Lesen (`ui/loxone_debug.py`); helper remains on Smarthome-Backend credentials. Docs: `docs/ui/ehal-com.md`. Backlog **2.5.3**.

### Bugfix EHAL Live-Lesen absent + SOC-Min Sofort binding (2026-09-16)

- [x] **EHAL binding / Live-Lesen for `sens_absent_mode` and `get_evcs_soc_min_immediate`** — Live-Lesen omitted plant `sens_absent_mode` despite mapping (`collect_read_checks`); heuristic hints missed `Earnie_EAuto_SOCMinSofort`. Probe 404 = Merker title missing on Miniserver (VO CmdOn URL ≠ Merker pull). Fix: plant absent in Live-Lesen; heuristic `socminsofort` hints. Tests: `test_loxone_connectivity`, `test_loxone_ehal_mapping`. Live acceptance verified.

### Bugfix Known consumers in absent mode (2026-09-16)

- [x] **Consumer "Kochen" still planned in absent mode** — Live absent only filtered MILP flex; `earnie_role: known` stayed in baseload overlay + Chart-1 peel. Fix: `resolve_live_absent_skip_ids` / `live_absent_skip_fixed_ids` skip opted-in non–Haus-Wärme IDs in `data/profile_manager.py` live overlay and `house_config/known_chart_display.py`. Tests: `tests/test_absent_mode.py`. Live acceptance verified (local_env).

### Bugfix Absent-mode labels + Haus-Wärme delta (2026-09-16)

- [x] **Absent-mode UI labels + Haus-Wärme temperature delta** — Consumer opt-in „Inaktiv wenn abwesend“; Haus Wärme „Solltemperatur“ + `absent_temp_reduction_c` („Temperaturabsenkung wenn abwesend“) with legacy `absent_temp_c` migrate; EV „Prognose, wenn nicht angeschlossen“. Docs: handbook, `flexible-verbraucher.md`. Tests: `tests/test_absent_mode.py`. Live acceptance verified.

### Holiday / absent mode (live-only) (2026-09-16)

- [x] **Add holiday / absent mode for consumers with no consumption** — HK master `absent_mode` OR plant EHAL `sens_absent_mode` (`Earnie_Abwesend`); per-consumer `absent_mode_enabled`; Haus-Wärme `absent_temp_c` + persons/WW=0; non–Haus-Wärme dropped from live MILP only. HK status + Monitor hint. VO + greenfield auto-bind. Docs: handbook, `flexible-verbraucher.md`, `ehal-com.md`, `loxone-signals.md`, `betriebsmodi.md`. Runtime: `optimizer/absent_mode.py`. Tests: `tests/test_absent_mode.py`. Backlog **2.+1**.

### Remove EHAL-Com Energieflussmonitor → Verbraucher (2026-09-16)

- [x] **Remove redundant EFM HITL chapter on EHAL-Com** — Dropped UI `ui/ehal_efm_import.py` and EHAL-Com expander; EFM meter → consumers/plant stays in Smarthome-Backend **Loxone-Import** via `merge_efm` / `integrations/loxone_efm_meters.py`. Docs retargeted: `docs/ui/ehal-com.md`, `docs/konfiguration/verbrauchs-csv.md`, `docs/referenz/loxone-signals.md`, `docs/dev/done/efm-auto-sync.md`, `docs/spec/ehal.md`, `docs/spec/loxone-meter-energy-slot-ist.md`. Backlog **2.+1**.

### Loxone auth gate on HTTP 401/403 (2026-09-16)

- [x] **main.py pauses Miniserver access on Loxone 401/403** — Auth failure persisted to `runtime/loxone_auth_error.json`; `main.py` skips optimization runs until credentials recover; Streamlit banner (`ui/loxone_auth_banner.py`) and **Smarthome-Backend → Anbindung** credential update path. Startup checks skip marker verify on auth failure. Delivered **v2.5.1**; backlog item under Version 2.6 was duplicate.

### HK copy-on-add PV / Batterie (2026-09-16)

- [x] **UI: add PV-Anlage / Batterie by copying last selected** — Hauskonfigurator `— neu —` clones last selected entity (label `{source} copy`), fallback Live refs then hard defaults; same pattern as scenarios. `ui/planning_pv_form.py` (`new_pv_system_template`), `ui/planning_battery_form.py` (`new_battery_template`). Tests: `tests/test_planning_editors.py`. Backlog **2.+1**.

### Battery efficiency & standby recommendation (2026-09-16)

- [x] **Calculate battery efficiency from charge/discharge** — Analyse Verbrauch & Kosten: `η = √(E_discharge/E_charge)`; Standby (HK `standby_power_kw` × Fenster) on Entladen bar; caption recommends measured η vs nominal and compares standby A vs residual B (hint if &gt;20%); removed „Kleine Abweichungen…“. Helpers: `ui/consumer_cost_battery_metrics.py`. Docs: `docs/ui/charts.md`. Tests: `tests/test_consumer_cost_analysis.py`. Backlog **2.+1**.

### Energy counters flex Meter Loxone slot Ist (2026-09-16)

- [x] **Energy counters (ΔkWh) for slot Ist — Loxone flex consumers** — `integrations/loxone_meter_energy.py`: `consumer.loxone_meter_energy`, `flex_energy_meter_*`, flex overlay on `closed_interval.flex_kw`; EFM consumer import bind; `profiles_store` normalize; sampler `energy_anchors.open.flex`. Merker-only and shared-meter (`subtract_consumer_ids`) stay sample mean; battery out of scope. Docs: `docs/spec/loxone-meter-energy-slot-ist.md`, `docs/ui/charts.md`, `docs/ui/ehal-com.md`. Tests: `tests/test_loxone_meter_energy.py`, `tests/test_power_interval_sampler.py`, `tests/test_loxone_efm_meters.py`. Backlog **2.+1**.

### Energy counters plant PV/grid Loxone + Chart 1 QH slot-mean (2026-09-15)

- [x] **Chart 1 / Produktiv-Log: QH slot-mean sampling** — `runtime_store/power_interval_sampler.py` (30 s ticks in daemon wait), `closed_interval` on QH Produktiv-Log; Chart 1 / Verbrauch & Kosten / Soll–Ist prefer mean when `sample_count ≥ 3`; SoC↔Ist reconcile only as low-sample fallback. Docs: `docs/ui/charts.md`, `docs/einrichtung/betrieb.md`. Tests: `tests/test_power_interval_sampler.py`, `tests/test_slot_ist_mean_consumers.py`. Live acceptance: sampler state fills mid-slot samples; **v2.5.3**.
- [x] **Energy counters (ΔkWh) for slot Ist — Loxone plant PV/grid** — `integrations/loxone_meter_energy.py`: HTTP `/all` parses `total`/`totalNeg` and Meter abbreviations `Mr`/`Mrc`/`Mrd`; `plant.loxone_meter_energy` preserved in `house_config/profiles_store.py`; EFM bind + sampler `energy_anchors` → ΔE→avg kW overlay on `closed_interval` (`ist_power_source` counter). Spec: `docs/spec/loxone-meter-energy-slot-ist.md`. Tests: `tests/test_loxone_meter_energy.py`. Live: open anchors with PV/grid totals. Flex consumer counters remain open under Backlog **2.+1**. **v2.5.3**.

### Bugfix Chart 1 evening Grundlast hides Haus Wärme (2026-09-15)

- [x] **Chart 1: evening Grundlast hides Haus Wärme** — Dump `debug_dump_20260915_154542`. Live `_apply_house_profile_baseload_overlay` overlaid `thermal_annual` into `Verbrauch-Prognose` when raw `flexible_consumers` was empty, even though resolved MILP flex includes Haus Wärme. Fix: skip `milp_flex_thermal_ids` (SE parity) in `data/profile_manager.py`. Test: `tests/test_profile_manager_baseload_overlay.py`. Live acceptance verified.

### Bugfix Monitor S₀→S₂ desktop plot hide on phones (2026-09-15)

- [x] **Monitor S₀→S₂ desktop plot (hide on phones)** — `ui/s2_viewport.py`: phones keep 24h segments; tablets/desktop get full SA₀→SA₂ span; navigation switch still 24h-based. Live acceptance verified (phone UA must not show full S₀→S₂; desktop/tablet unchanged).

### Bugfix Chart 1 Ist battery vs SoC direction interim (2026-09-15)

- [x] **Chart 1 Ist battery vs SoC direction (interim)** — `_reconcile_history_battery_with_soc` replaces `Ist Batterie-Leistung` when sign opposes the SoC step to the next present slot (`runtime_store/history_chart_rows.py`, `soc_plausibility.py`). Docs: `docs/ui/charts.md`. Tests: `tests/test_soc_battery_reconcile.py`. **v2.5.2**. Live acceptance verified (dump slot 14.09. 13:00 discharge bar while SoC 42%→50%). Durable QH energy path: slot-mean + plant Meter counters in **v2.5.3** (flex counters still open).

### Analyse rolling 7/28-day windows (2026-09-14)

- [x] **Changes in analysis chart view / summaries** — Analyse Verbrauch & Kosten uses rolling **7** / **28** days (←/→ by window length) instead of calendar ISO weeks; shared `ui/consumption_display/period.py` + generic nav; KPIs = selected window + trailing 365 days of log; SE/HK keep ISO-week browsing via the same API. Docs: `docs/ui/betriebsmodi.md`, `docs/ui/charts.md`, `docs/user-manual/Benutzer-Handbuch-Earnie.md`. Tests: `tests/test_consumption_display.py`, `tests/test_consumer_cost_analysis.py`. (12-month chart mode / SE-HK rolling opt-in left for later.)

### Hausprofil timezone from Land (DACH) + Dev tooling (2026-09-14)

- [x] **Timezone without timezonefinder** — `house_config/geo_timezone.py` maps AT/DE/CH → Europe/Vienna|Berlin|Zurich (`timezone_for_land`); removed `timezonefinder` from `pyproject.toml`; callers/schema/tests updated
- [x] **Dev tooling** — `scripts/run_pytest.py`; `.devcontainer` Dockerfile + post-create; Cursor skills/rules for pytest/Unicode; pre-commit uses `run_pytest`

### Bugfix Chart-1 empty history bars after dead EHAL read (2026-09-14)

- [x] **Chart 1 empty history bars after all-zero EHAL live read** — (`debug_dump_20260820_191521`). Root cause: poisoned all-zero `consumption_snapshot` from EHAL/Loxone outage emptied Chart 1 history bars. Fix: `data/live_consumption.py::is_dead_telemetry_snapshot` detects all-zero meter reads; `main.py` skips applying/writing poisoned snapshots to optimizer matrix and prod log; `runtime_store/history_chart_rows.py` sanitizes dead telemetry and hold-forwards load after dead slot. Tests: `tests/test_live_consumption.py`, `tests/test_history_timeline.py`. Live acceptance verified.

### Miniserver HTTP port / GitHub issue #9 (2026-09-14)

- [x] https://github.com/JochenTCC/Earnie/issues/9 — optional HTTP port on Miniserver IP (`LOXONE_IP` as `IPv4` or `IPv4:port`)
  - `runtime_store/dotenv_io.py` `validate_loxone_ip` accepts port 1–65535; Streamlit **Smarthome-Backend → Anbindung** help/caption; docs (`.env.example`, `loxone-anbindung`, SB page, HA add-on `loxone_ip`); tests in `tests/test_dotenv_io.py` / `tests/test_loxone_client.py`
  - HA/OpenEMS port UX left as open `2.+1` follow-up in [Backlog.md](Backlog.md)

### Bugfix Chart-1 SoC jump between S-2 cycle charts (2026-08-20)

- [x] **SoC jump >10% yesterday vs today chart** — S-2 cycle navigation showed e.g. 62.6% vs 29.0% at the same slot on 20.08. 06:15 (`debug_dump_20260820_093415`). Root cause: history SoC sanitizer kept a stale high chain after bad ESS reads (81%→55% latch, then rejected true low readings while integration drifted upward overnight). Fix: `runtime_store/soc_plausibility.py` — accept repeated ESS plateaus (≥2 identical raw readings) and readings contradicting battery-integration direction; `runtime_store/history_chart_rows.py` tracks consecutive raw values. Tests: `tests/test_soc_plausibility.py`. Live acceptance verified (Streamlit S-2 cycle navigation).

### HA Add-on auto-publish on release (2026-08-19)

- [x] **`scripts/bump_ha_addon.py`** — idempotent pin of `build.yaml`, `config.yaml`, `Dockerfile` ARG, `CHANGELOG.md`; add-on `version:` mirrors Earnie app release
- [x] **Release CI** — `.github/workflows/release.yml` job `publish_ha_addon` (lint → commit Earnie `main` → mirror `ha-addon-earnie` `main`); manual retry via `.github/workflows/ha-addon-publish.yml`
- [x] **Add-on CI lint** — `frenck/action-addon-linter` in publish job + `ha-addon-earnie/.github/workflows/hassfest.yml` on push/PR
- [x] **Docs** — `packaging/homeassistant-addon/README.md`, `earnie/CHANGELOG.md`, `docs/einrichtung/homeassistant-addon.md`, `ha-addon-earnie/README.md`
- [x] **Prerequisite (maintainer):** repo secret `HA_ADDON_REPO_TOKEN` on `JochenTCC/Earnie` (PAT `contents:write` on Earnie + ha-addon-earnie) — required before first tagged publish

### Official release 2.5.0 (2026-08-19)

- [x] Official `2.5.0` — GitHub Latest + GHCR `:2.5.0` and `:latest`; tag `v2.5.0` on `main` after community alpha line (`2.5.0-alpha.9`); release notes [`.github/release-notes/v2.5.0.md`](../.github/release-notes/v2.5.0.md); alpha compose stays pinned to `2.5.0-alpha.9`

### 2.5.r pre-official quality gate re-check (2026-08-19)

- [x] **2.5.r re-check** on `main` @ `492d02c` (after EHAL-Com Loud/Silent + `silent_mode` rename; no `version.py` bump)
  - [x] Coverage baseline — 2279 passed / 6 skipped; overall **80.6%** (`data` 73.2, `ehal` 88.8, `house_config` 80.6, `optimizer` 85.8, `runtime_store` 80.0, `settings` 77.4, `simulation` 86.5); no package &lt; 40% (vs 2.5.r 79.9% / 2132 passed)
  - [x] Dead-code / obsolete-test audit — `vulture` (confidence 80) clean; `pytest --dead-fixtures` clean; health-report flags unchanged (mock-heavy cons_data/dotenv + expected fail-fast `legacy_id` / `pv_follow_name`)
  - [x] Simplification triage — no functional removals this pass; `load_loxone_silent_mode` / `is_loxone_silent_mode` kept as intentional legacy aliases; deferred deeper MILP/UI god-function splits (see KPI)
  - [x] KPI — **0** core/UI files &gt; 600 LOC (mega-file splits from 2026-08-16 hold); **62** functions &gt; 60 LOC remain (structural: `simulate_horizon`, `run_simulation`, MILP build/solve, planning PV/battery tabs, chart builders) — defer post-`2.5.0` unless a letter chapter targets them
  - [x] Official docs — `Doc-Review-Checklist.md` 2.5.0 QH items still complete; this session updated `docs/ui/ehal-com.md` + `docs/einrichtung/betrieb.md` for `silent_mode` (already on `492d02c`)
  - [x] SonarCloud snapshot (`492d02c`, [Actions run 32254786683](https://github.com/JochenTCC/Earnie/actions/runs/32254786683)) — Quality Gate **Passed**; new code: **0** bugs, **0** vulnerabilities, **0** security hotspots; new coverage **83.8%**; dashboard overall coverage **75.3%** (informational vs health-report 80.6%)

### Bugfix EHAL-Com Loud/Silent status banner (2026-08-19)

- [x] **Misleading status text on EHAL-Com** — banner combined Loud mode with “Optimierer läuft nicht” in one sentence (`Loud-Modus - Optimierer läuft nicht - daher werden keine Daten gesendet`) even when Loud was only configured and `main.py` was stopped. Fix: `ui/loxone_debug_rows.py::status_strip_banner` separates configured mode from optimizer service state; Loud+stopped now prompts to start `main.py` under Daemon Control. Renamed setting **`silent_mode`** (primary in `runtime/local_settings.json`; legacy `loxone_silent_mode` still read). Run state writes `silent_mode`. Docs: `docs/ui/ehal-com.md`, `docs/einrichtung/betrieb.md`. Tests: `tests/test_loxone_debug.py`, `tests/test_local_settings.py`. Live acceptance verified (NAS / EHAL-Com).

### Bugfix SB Loxone password save corrupts .env on NAS (2026-08-19)

- [x] Changing Loxone credentials on **Smarthome-Backend → Anbindung** could leave `config/.env` empty on NAS/SMB when `os.replace` failed or wrote invalid content (missing write permissions). Fix: `runtime_store/dotenv_io.py::write_loxone_dotenv` — pre-check config dir writable / target not a directory, backup existing `.env`, verify temp + final content, restore backup on failure, clean up `.env.tmp`; `ui/setup_dotenv.py` — explicit German error when save is not possible (no success toast). Tests: `tests/test_dotenv_io.py` (`test_write_loxone_dotenv_preserves_original_when_replace_fails`, `test_write_loxone_dotenv_restores_when_post_replace_content_invalid`). Live acceptance verified (Streamlit SB save + read-only simulation).

### Bugfix Chart-1 implausible SOC peak at midnight (2026-08-19)

- [x] **Unplausible SOC peak around 0:00** — Chart-1 showed a ~51% SoC spike at 18.08. 00:15 with no matching battery charge/discharge bars (`debug_dump_20260819_135605`). Root cause: bad Miniserver ESS read logged to `optimization_history.jsonl` (`soc_percent` 51.2 with `battery_plan_kw` 0). Fix: `runtime_store/soc_plausibility.py` (physics envelope + battery-power integration); sanitize history chart rows in `runtime_store/history_chart_rows.py`; correct live SoC before MILP in `main.py` (`optimization_history.latest_logged_soc_percent`). Tests: `tests/test_soc_plausibility.py`, `tests/test_chart_history.py::test_build_chart_history_sanitizes_implausible_soc_spike`. Live acceptance verified (S-2 past cycle, midnight window).

### Batterien tab: Verschleiß editierbar (2026-08-19)

- [x] Checkbox **„Verschleiß berücksichtigen“** auf dem Hauskonfigurator-Tab **Batterien** (`[ui/planning_battery_form.py](../ui/planning_battery_form.py)`) — aktiviert schaltet drei Felder frei (Ersatzkosten €, Erwartete Vollzyklen, Anteil zyklenbedingter Kosten, Defaults 1500/6000/0.5), persistiert in den bereits vorhandenen `battery_wear`-Block je Batterie (Backend/Validierung/Schema unverändert). Tests: `[tests/test_planning_editors.py](../tests/test_planning_editors.py)`. Doku: `[docs/konfiguration/batterie-pv.md](../docs/konfiguration/batterie-pv.md)`. Verified live (Streamlit, isolierte Testkonfiguration).

### SonarCloud in CI + quality-gate snapshot (2026-08-18)

- [x] Adding SonarQube/SonarCloud analysis into the commit workflow — scan on `push`/`pull_request` to `main` ([`.github/workflows/sonarcloud.yml`](../.github/workflows/sonarcloud.yml), [`sonar-project.properties`](../sonar-project.properties)); doc-only skip archived 2026-08-17.
- [x] Remaining “integration into release quality gate” is not a 2.5.0 checkbox: from the **next** `X.Y.r`, skill `quality-gate` step 6 is a SonarCloud snapshot (new bugs/vulnerabilities vs last `.r`; gate status informational). Do not re-run Sonar locally; do not make the Sonar Quality Gate a required GitHub check.

### Home Assistant Supervisor Add-on MVP 0.1 — M3 persistence proof (2026-08-18)

- [x] M3 on a real Supervisor: add-on restart, add-on update, and Supervisor backup-restore keep `config.json`, sidecars, and `runtime/` (Entwicklungsplan MVP 0.1). Walkthrough: [`docs/einrichtung/homeassistant-addon-testumgebung.md`](../docs/dev/homeassistant-addon-testumgebung.md) (WSL2 Supervised and Pi 4 HA OS). M1/M2/M4/M5 already archived 2026-08-17.

### SB / HK follow-ups (2026-08-18)

- [x] On SB page — Loxone-Import success text hints to check created consumers on **Hauskonfigurator** and signal mapping on **EHAL-Com** (`ui/ehal_greenfield_import.py` `_IMPORT_SAVED_FLASH`; regression in `tests/test_ehal_greenfield_import_ui.py`).
- [x] Move **Anbindung** (credentials) from EHAL-Com to Smarthome-Backend: configured SB order is Anbindung → **Backend ändern** → Loxone-Import; EHAL-Com keeps live debug/mapping only (`ui/ehal_connection.py::render_anbindung_section`, `ui/pages/page_smarthome_backend.py`, `ui/pages/page_loxone_debug.py`).
- [x] Hausprofil **Entfernen** beside the Profil select (`ui/house_config_profile_form.py`); `delete_house_profile` refuses the Live-Szenario profile and any profile still referenced by other scenarios (`ui/house_config_io.py`).
- [x] LoxBerry plugin and Home-Assistant add-on store icons now use `docs/assets/Earnie-Logo-Simple-Light.png` (`packaging/loxberry/icons/`, `packaging/homeassistant-addon/earnie/icon.png`+`logo.png`, mirrored to `ha-addon-earnie`).

### Bugfix SB Loxone-Import → extra Hausprofil on HK (2026-08-18)

- [x] Do not automatically add another House profile when switching from SB page to HK page — HK now defaults to an existing profile (`live` / Live-Szenario) instead of `— neu —`; Loxone-Import sets pending HK select to the imported profile (`ui/house_config_profile_session.py`, `ui/ehal_greenfield_import.py`). Live acceptance verified.
- [x] SB success text after Loxone-Import: hint to check created consumers on Hauskonfigurator (and EHAL-Com signal mapping).

### Bugfix EV short unplug before FertigUm skipped today's cycle (2026-08-18)

- [x] EV short unplug before FertigUm skipped today's cycle (`debug_dump_20260808_102915`) — `open_charging_deadlines` latch keeps `available_from=now` until deadline/fulfill; tests in `test_charging_session.py` / `test_charging_context.py`. Live acceptance verified.

### Smarthome-Backend (SB) page — M1/M2/M3/M4/M5/M6 (2026-08-18)

Dev plan drafted and implemented same day, 2026-08-18: [docs/dev/done/smarthome-backend-page.md](../docs/dev/done/smarthome-backend-page.md) (see its §5 "Implementation notes" for deviations from the original plan found during implementation). Detection design draft: [backlog/SB-Identification-Draft.md](SB-Identification-Draft.md).

- [x] **M1 — `integrations/integration_scanner.py`** (detection engine): passive mDNS (Home Assistant, `_home-assistant._tcp.local.`) and SSDP/UPnP (Loxone, `239.255.255.250:1900`) discovery, verified live against a real Miniserver-Gen2 and a real HA 2026.8 instance on the user's LAN; opt-in active TCP port scan (8080/8085) for OpenEMS with a best-effort Felix-console signature check. `scan_for_backends(mode, only_kinds=...)` dispatches `targeted` / `full_passive` / `full_active`. New dependency `zeroconf` (`pyproject.toml`). The proprietary Loxone UDP-broadcast protocol (port 7070) was tried against the real Miniserver and got no response on any tested payload — dropped in favor of the (confirmed-working) SSDP path rather than shipped unverified.
- [x] **M2 — install-context detection + readiness predicate**: `runtime_store/install_context.py` (`EARNIE_INSTALL_CONTEXT` — `loxberry` / `homeassistant_addon`, unset = `manual`) narrows the targeted scan; set in the LoxBerry plugin compose, the two `docker/compose/loxberry-*.yml` files, and the Home-Assistant add-on `run.sh`. `ui/setup_readiness.py::is_sb_configured()` / `needs_sb_setup()` — thin wrapper over the existing `hub_credentials_configured()`, no new persisted flag.
- [x] **M3 — SB page + navigation wiring**: new `ui/pages/page_smarthome_backend.py` (nav: Daemon Control → Smarthome-Backend, `live_environment`): scan → 0/1/many-result handling with a manual-selection fallback → reuses the existing Loxone/HA/OpenEMS credential forms (no duplicated forms) → configured-summary state. The pre-nav blocking first-run screen (`ui/setup_dotenv.py::render_ehal_setup_page`, shown once planning is complete and no backend is configured) now delegates to the same SB page implementation instead of its own hand-rolled backend selector — one place to pick a backend, not two. During greenfield onboarding, Optimierer-Dienst/EHAL-Com stay hidden until a backend is chosen (`ui/navigation.py::_echtzeit_page_specs(include_daemon_pages=...)`, scoped to the onboarding-forced nav path — see the dev-plan doc for the narrower-than-literal interpretation and a documented residual edge case outside onboarding).
- [x] **M4 — move Loxone Import HK → SB**: import moved from the Hauskonfigurator (Hausprofil tab) to Smarthome-Backend (shown once Loxone is connected); `ui/ehal_greenfield_import.py` itself unchanged, only its call site moved.
- [x] **M5 — remove EHAL-Com's backend selector**: `ui/ehal_connection.py::render_backend_selector` deleted (dead code, no callers left); the page reads the already-active backend via `active_ehal_backend()` instead — credentials re-entry/re-verify and Loxone/HA mapping sections stay on EHAL-Com.
- [x] **M6 — tests**: `tests/test_integration_scanner.py` (26), `tests/test_install_context.py` (5), `tests/test_setup_readiness.py` additions, `tests/apptest/test_page_smarthome_backend_apptest.py` (new) plus updated `test_page_loxone_debug_apptest.py` / `test_page_house_config_apptest.py` / `test_navigation_setup.py`. Full suite: 2223 passed / 3 skipped (was 2192 before this item).
- Docs updated to point backend selection at the new page: new `docs/ui/smarthome-backend.md`; `docs/ui/ehal-com.md`, `docs/ui/betriebsmodi.md`, `docs/einrichtung/smarthome-backend-wahl.md`, `docs/README.md`.

Known residual gap (documented, not fixed at the time): a "mature" config that never had a backend configured could still reach Optimierer-Dienst/EHAL-Com outside the onboarding path. Closed same day — see below.

### SB page follow-up: close daemon-page bypass for mature configs without a backend (2026-08-18)

Closed the residual gap noted above: `ui/navigation.py::_echtzeit_page_specs(include_daemon_pages=...)` was previously gated only under `force_echtzeit` (the greenfield-onboarding forced-nav path), so a "mature" config (`needs_planning_onboarding()` false, e.g. non-empty `flexible_consumers`) that had never had any backend configured could still reach Optimierer-Dienst/EHAL-Com — the blocking pre-nav gate (`runtime_store/dotenv_io.py::loxone_setup_deferred()`) intentionally stays deferred in exactly that state, so it didn't cover this either.

- [x] `ui/navigation.py::_append_konfiguration_and_echtzeit()` now derives `include_daemon_pages` from `ui.setup_readiness.needs_sb_setup()` unconditionally whenever daemon pages would otherwise show, not just under `force_echtzeit`. `loxone_setup_deferred()` itself is unchanged (still deliberately deferred there, still covered by `tests/test_dotenv_io.py::test_require_loxone_credentials_for_prod_without_onboarding`) — the nav layer now closes the gap independently.
- [x] Test-hygiene audit of the ~9 test files touching Optimierer-Dienst/EHAL-Com nav visibility, to check whether their passing status depended on a developer's real local `.env` Loxone credentials (loaded process-wide by `tests/conftest.py`) rather than on an explicit, deterministic environment. Only `tests/test_ui_navigation.py` needed fixing — 3 tests (`test_default_pages_include_core_and_scenario_explorer`, `test_only_sunset_hides_dev_and_scenario_explorer`, `test_sections_are_assigned`) asserted daemon pages were shown without pinning `LOXONE_IP`/`LOXONE_USER`/`LOXONE_PASS`; `test_sections_are_assigned` would have hard-failed with a `KeyError` once the general-case gating went live. Fixed with explicit `monkeypatch.setenv(...)`, mirroring the existing pattern in `tests/test_loxone_connectivity.py::TestLoxoneEnvHelpers`. The remaining candidates (`test_navigation_setup.py`, `test_cloud_demo.py`, `test_house_config_markers_ui.py`, `test_setup_progress.py`, `test_doc_links.py`, `test_daemon_log_tail.py`, the `apptest` files) were already hermetic or structurally unaffected by the gating change.
- [x] New regression coverage in `tests/test_navigation_setup.py`: `test_general_nav_hides_daemon_pages_for_mature_config_without_backend` / `..._once_sb_configured` — exercises the exact "mature config, no backend ever configured, `live_environment` mode" case. Verified the new test actually fails against the pre-fix code (reverted `navigation.py` locally, ran it, confirmed the `AssertionError`, then restored the fix) before trusting it as real coverage.
- [x] Full suite before/after (`pytest tests -q -k "not slow"`): 2217 → 2219 passed / 8 skipped, both runs with the same single pre-existing flaky failure (`tests/test_main_daemon.py::test_start_stop_with_stub_script`, a Windows PID-liveness race unrelated to this change). No regressions.
- Doc updated: [docs/dev/done/smarthome-backend-page.md](../docs/dev/done/smarthome-backend-page.md) §5.

### Home Assistant Supervisor Add-on MVP 0.1 — M1/M2/M4/M5 (2026-08-17)

- [x] Add-on skeleton under `packaging/homeassistant-addon/earnie/` — image-wrapper `Dockerfile` (`FROM ghcr.io/jochentcc/earnie-energy:${EARNIE_VERSION}`, pinned `2.4.0`), `config.yaml` manifest (ports 8501/8541, `/data` volume, optional options/schema), `build.yaml` (arch mapping, build args), `run.sh` (`/data/options.json` → `EARNIE_*` env via `jq`, hands off to the existing `docker/entrypoint.sh`), `DOCS.md`, `CHANGELOG.md`, `translations/en.yaml`, `icon.png`/`logo.png`.
- [x] Persistence wired to the standard `/data` add-on convention (`EARNIE_ENV_PATH=/data/earnie_env`) instead of `/config` (corrects the original HA-Green sketch). Local Docker smoke test (bind-mounted `/data`, simulated `options.json`) confirmed config/runtime survive a container restart and caught/fixed a real bug: `jq -r '.auto_start_main // empty'` treated JSON `false` like `null` (jq's `//` falsy-boolean trap), silently ignoring `auto_start_main: false`.
- [x] User doc [`docs/einrichtung/homeassistant-addon.md`](../docs/einrichtung/homeassistant-addon.md) (install, options, ports, data paths, limitations) plus a Supervisor test-environment walkthrough for M3 (now archived 2026-08-18). Cross-linked from `docker/README.md` and `docs/referenz/streamlit-ports.md`.
- [x] Published add-on repository [`github.com/JochenTCC/ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie) (public) — `repository.yaml`, mirrored `earnie/`, `README.md`, `LICENSE.md` (carried over verbatim per license terms), `.gitattributes`. New sync script `packaging/homeassistant-addon/sync-to-ha-addon-repo.sh` mirrors the dev-source folder into a checkout of that repo (manual-copy sync mechanism, per the Entwicklungsplan's decision for 0.1 — no GitHub Action needed).
- [x] Maintainer-facing release-workflow doc [`packaging/homeassistant-addon/README.md`](../packaging/homeassistant-addon/README.md) (analogous to `packaging/loxberry/README.md`): version-bump checklist (`build.yaml` `EARNIE_VERSION` + `config.yaml` `version`), sync-script usage, local build/test steps — notes that add-on updates need no GitHub Release/tag in `ha-addon-earnie`, just a commit to `main` (Supervisor reads the tracked branch directly).

M3 (persistence proof on real Supervisor) archived 2026-08-18 — see section above.

### CI: skip SonarCloud on doc-only changes (2026-08-17)

- [x] `paths-ignore` (`**/*.md`, `**/*.png`, `docs/**`) added to the SonarCloud workflow's `push`/`pull_request` triggers ([`.github/workflows/sonarcloud.yml`](../.github/workflows/sonarcloud.yml)) — pure documentation commits no longer trigger a full `pytest --cov` + scan run. Deliberately narrower than the local pre-commit hook's skip list (`.github/**`/`.githooks/**` still trigger a real run, so CI/hook changes stay validated).

### Streamlit AppTest page coverage + script path guards (2026-08-16)

- [x] First automated UI smoke set with Streamlit AppTest for remaining pages (Config, Daemon, Loxone Debug, Price Forecast, Consumer Analysis, Backtesting) plus earlier Cockpit / Devices / House Config / Scenario Editor — import bugs found during the runs were fixed in the same wave.
- [x] Remote backtesting and SE matrix writers reject path escape (`..` / absolute); SE `materialize_cell` only accepts `M0`–`M4`; CLI `main()` helpers flattened.

### 2.5.r Quality / release hardening (2026-08-16)

- [x] **2.5.r — Quality / release hardening** (same shape as `2.4.r`)
  - [x] Coverage baseline (`test_health_report run --coverage`) — 2132 passed / 3 skipped; overall **79.9%** (`data` 73.2, `ehal` 87.4, `house_config` 80.4, `optimizer` 83.9, `runtime_store` 79.4, `settings` 77.3, `simulation` 86.6); no package &lt; 40%
  - [x] Dead-code / obsolete-test audit — `vulture` (confidence 80) clean; `pytest --dead-fixtures` clean; health-report flags are expected fail-fast `legacy_id` / `pv_follow_name` + mock-heavy cons_data/dotenv (same class as `2.4.r`)
  - [x] KPI refactor (incl. mega-file splits; do not defer) — files over hard limit 600 LOC and functions > 60 LOC in core/UI; skill `quality-gate`
    - [x] Wave 1 (deferred `2.4.r` mega-files): `planning_flex_bridge`, `optimizer/simulation`, `simulation/engine`, `loxone_structure`, `loxone_client`, `loxone_greenfield_import` — facades + siblings ≤ 600 LOC; original import paths stable
    - [x] Wave 2 mega-files (14): facades + topic siblings ≤ 600 LOC; original import paths stable (`house_config_profile_form`, `chart_soc`, `chart_flow_balance`, `page_scenario_editor`, `house_config_historical_csv`, `backtesting`, `house_config_io`, `loxone_debug`, `backtesting_display_bundle`, `simulation_results`, `ehal_loxone_mapping`, `charging_context`, `milp_consumers`, `history_timeline`)
    - [x] God-function splits (Wave-2 modules) — listed bodies now ≤ 40 (ramps 41/43, under hard 60): `_render_scenarios_tab` → `scenario_editor_sections` (`_prepare_scenario_tab`, `_render_scenario_identity_fields`, `_render_scenario_entity_picks`, `_render_scenario_tariff_block`, `_persist_or_delete_scenario`); `_render_consumer_form_body` → `_render_thermal_annual_fields`; `render_house_profile_tab` → `_render_profile_selector` / `_edit_and_sync_consumers` / `_render_baseload_preview`; `_render_generic_fields` → `_render_generic_role_schedule`; `build_flow_balance_segments` → `_primary_up_segments` / `_primary_down_segments` / `_assemble_balanced_slot`; SE run → `_prepare_backtesting_run_context` / `_render_backtesting_progress` / `_render_season_mirror_toggle` / `_render_horizon_select` / `_render_run_buttons`; SoC → `_add_optimized_soc_segment` / `_add_counterfactual_soc_segment` / `_ramp_before_ys` / `_ramp_end_point` / `_ramp_start_soc` / `_add_underlay_part`; `build_optimization_display_bundle` → `_merge_chart_into_bundle` / `_resolve_bundle_headers`. Facades unchanged.
  - [x] Official docs: landing/handbook/charts no longer claim hourly MILP; issue-template version pin; swimspa-filter / UI-spec QH granularity

### Bugfix Pool heating at band max / QH RC horizon (2026-08-16)

- [x] Planned pool heating although Ist at band max (`debug_dump_20260816_140828`) — QH matrix length (162) was passed as hourly RC horizon → 28 kWh / `Earnie_Pool_Freigabe=1` while actual 35.5 °C = band_max (Soll 34.0, tol 1.5). Fix: `thermal_horizon_hours_from_slots` (162 → 40 h → 0 kWh) in `main.py` / `optimizer/targets.py` / `data/consumer_targets.py`. Tests in `test_thermal_targets.py` / `test_thermal_model.py` / `test_consumer_targets_thermal.py`. Live acceptance verified.

### Bugfix Pool filter Ist with alternate-only binding (2026-08-16)

- [x] Pool filter Ist not assigned when only `sens_filter_active` is bound (`debug_dump_20260808_232225`) — binary meter accepts alternate-only; regression in `test_loxone_client.py`. Live acceptance verified.

### Bugfix earnie.log unbounded growth (2026-08-16)

- [x] earnie.log unbounded growth — `SizeAndTimeRotatingFileHandler` (5 MB or weekly `W0`, backupCount 8, rename→copy/truncate fallback); tests in `test_logger_config_rotation.py`. Live acceptance verified.

### Pre-release 2.5.0-alpha.6 (2026-08-15)

- [x] Community pre-release `2.5.0-alpha.6`: hourly EPEX settlement (aWATTar HOURLY/SUNNY), full-catalog `settlement_mtu`, analog Zähler consumers, SE plausibility vs ESS standby; alpha compose + container docs pin `ghcr.io/jochentcc/earnie-energy:2.5.0-alpha.6`.

### Bugfix SE plausibility after QH / mean-h (2026-08-14)

- [x] SE calculation after qh / mean-h-Fix (local-env Scenarios) marked every window as a consumption issue. Cause: Verbrauch-Prognose includes ESS standby (`standby_power_kw` 0.026 → 0.624 kWh/day) while cons_data baseload does not; 0.5 kWh / 5% check failed on all 31 days. Fix: peel standby from optimized baseload in `validate_window_consumption` (`simulation/engine.py`). Also: Energy-Charts first for native QH prices (aWATTar hourly only on Charts failure); SE loads prices with the live import tariff `market_zone`. Tests in `test_baseload_validation.py`. Live/local-env SE acceptance verified.


### Bugfix Zähler-wired consumers shown as nominal/binary (2026-08-14)

- [x] Consumer Geschirrspüler (and other Zähler-wired manuals / Wärmepumpe) shown as Nennleistung or 0 although Loxone Zähler should be monitored — `planning_consumer_to_milp` / `planning_thermal_to_milp` forced `signal_type: binary`, so analog kW below 0.5 became 0 and at/above 0.5 became nominal. Fix: live/log `signal_type: power` when `flex.{id}.sens_power_act` or `power_name` is bound. Tests in `test_loxone_client.py` / `test_thermal_flex_bridge.py`. Live acceptance verified.


### settlement_mtu full-catalog research pass — no more silent 15min default (2026-08-14)

- [x] Every `spot_hourly` tariff in `share/config/tariffs.json` (26 import + 3 export ids) researched individually via official Preisblatt/Tarifblatt/product pages (web research, three parallel agents + manual follow-up) and given an explicit `settlement_mtu` + `notes` citation, instead of silently relying on the `"15min"` schema default. Result: 20 tariffs confirmed `"15min"` (native EPEX-QH pass-through), 10 confirmed `"60min"` (genuine hourly billing, several suppliers — `at_pullstrom_pullstrom_ora`, `at_smartenergy_smartcontrol`, `at_wuesterstrom_wuesterstrom_spot`, `at_wien_energie_optima_voll_aktiv`, `at_stadtwerke_klagenfurt_ekg_strom_flex`, `at_energie_steiermark_first_energy_steirerstrom_spot` — deliberately kept hourly billing after the Oct-2025 EPEX MTU switch despite marketing as "spot"). Two ids (`at_schlau_pv_gmbh_spot`, `at_energie_steiermark_e1_floater`) stayed genuinely unresolved (site down / likely supplier-id mismatch) and are flagged in `notes` rather than defaulted silently. CH tariffs (`ch_ekz_…`, `ch_groupe_e_vario`) set to `"60min"`: EPEX-CH day-ahead itself is still hourly-only until the planned 2026-11-03 MTU switch, so there is no native QH series to pass through even though both suppliers run their own 15-min retail pricing engines. Notable finds: `at_avia_energy_avia_strom_plus_stundenfloater` was renamed "15min FLOATER" and switched to QH billing despite the legacy "Stundenfloater" id/label; `at_smartenergy_smartsun_spot`'s current official product name is "smartSUNHOURLY" (label/id not updated here). Spec updated: `docs/spec/quarter-hour-slots.md` §3.3 (full table replacing the prior "mostly unclear, default unchanged" state). Tests unchanged/still green (`test_house_config.py`, `test_tariff_pricing.py`, `test_backtesting_prices.py`, `test_feed_in_prices.py`).

### Hourly-settlement EPEX tariffs — average QH slots for genuinely hourly-billed products (2026-08-14)

- [x] Tariffs genuinely settled **hourly** (aWATTar HOURLY `awattar_at`/`de_awattar_de_hourly_de`, SUNNY Spot `dynamic_epex`) now use the EPEX SDAC "average rule" (hourly price = arithmetic mean of the 4 QH clearing prices, structurally enforced by Euphemia market coupling since the 2025-10-01 15-min MTU transition) instead of each QH's individual spot price — matches real supplier billing. New `settlement_mtu` field (`"15min"` default / `"60min"`) in `share/config/tariffs.json` + `tariffs.schema.json`, normalized through `house_config/tariffs_store.py::_normalize_dach_fields`; averaging in `data/market_prices.py::hourly_settlement_epex_values`, wired into `data/backtesting_prices.py::import_brutto_cent_for_slots` and `data/feed_in_prices.py::enrich_matrix_feed_in_prices` (the two actual `k_act`/`k_push_act` choke points — covers Live and SE identically). "Likely hourly" tariffs (AAE, AVIA, smartSUN SPOT) intentionally left unflagged, not yet Tarifblatt-verified. Tests in `test_tariff_pricing.py` / `test_market_prices.py` / `test_backtesting_prices.py` / `test_feed_in_prices.py` / `test_house_config.py`. Spec updated: `docs/spec/quarter-hour-slots.md` §3.2–3.4. Sources: SDAC 15-min MTU transition writeups (Dexter Energy, N-SIDE, EPEX SPOT), aWATTar tariff pages.

### Bugfix EV early stop / shrunk session target (2026-08-14)

- [x] EV stopped at ~58% SOC with no error (`debug_dump_20260813_075350`) — plugged-in remaining subtracted booked kWh from Ist-SOC remaining (double count → MILP leftover 0.5 kWh); session `target_kwh` overwritten each QH with shrinking Ist-SOC need until `plug_cycle_fulfilled`. Fix: keep original session target; remaining = Ist-SOC need while plugged in. Tests in `test_charging_session.py`. Live acceptance verified.
- [x] EV stopped at ~80% SOC afternoon (`debug_dump_20260813_144852`) — shrunk session target 7.167 latched `plug_cycle_fulfilled` while Ist-SOC still ~4 kWh short. Fix: heal target to `max(prev, delivered+Ist)` while plugged in; do not latch/clear stale latch while open session still has Ist remaining. Tests in `test_charging_session.py`. Live acceptance verified.


### Bugfix Chart 1 ESS hold underlay after 16:00 (2026-08-13)

- [x] Chart 1 shows no ESS hold SoC underlay after 16:00 while table shows Entladesperre / Zwangsladen ~0 kW and live sends `set_ess_mode==1` — underlay runs now cover the full last slot (1-slot MILP hold visible); `chart_now` ramps align underlay with SoC. Tests in `test_ess_mode_soc_underlay.py`. Live acceptance verified.


### Sankey EV SoC on charging node label (2026-08-13)

- [x] Current EV SoC on the Sankey charging-path description while the EV is charging — shown in the flex node label (not hover). Tests in `test_sankey_produktiv.py`; docs `docs/ui/charts.md`.


### Runtime filenames: drop `_hourly` (2026-08-13)

- [x] Canonical runtime names are `cons_data.csv` / `cons_data.meta.json` and `backtesting.csv` (log field `series_file`). Legacy `*_hourly*` still loads if the new file is missing. Fixtures, docs, compose comments, schema, and `.gitignore` exceptions updated.


### Bugfix SE calc non-optimized costs after QH (2026-08-13)

- [x] SE calc costs much too high for non-optimized scenarios after QH-change — `_hour_cost_parts_without_optimization` treated each QH slot as 1 h (kW as kWh, ~4×). Fix: energy is `kW * dt_h`. Tests `test_reference_slot_cost_scales_with_dt_h` / `test_step_cost_parts_import_and_export`. Live acceptance verified. SE progress now reports wall-clock hours (`wall_hours_from_slots`).


### Bugfix Manuelle Geräte 30-min start slots (2026-08-13)

- [x] Time slots on Manuelle Geräte always showed `x.00` with duplicate checks per hour — snapshot loader floored QH `slot_datetime` to the hour and `recommend_start_times` treated `horizon_h` as a slot count. Fix: keep sub-hour timestamps; current slot plus `:00`/`:30` starts across the consumer wall-clock horizon; schedule overlay uses real slot duration. Tests in `test_appliance_recommendation.py` / `test_appliance_schedule.py` / `test_live_display_loader.py`. Live acceptance verified.


### Bugfix Chart-1 SoC vs underlay / BL anchor (2026-08-12)

- [x] Chart-1 SoC implausible vs ESS underlay (`debug_dump_20260812_191122`, 19:00–20:00) — current-hour ramp no longer wipes later MILP quarters; Jetzt-Anker uses MILP polyline when later QH exist (BL met Opt ~93%, not Ist-extrapolation ~82.5%); underlay `bridge_left=False`. Tests in `test_charts_soc_tail.py`. Live acceptance verified.


### Bugfix Pool/SwimSpa temperatures EHAL-Com Live-Lesen (2026-08-12)

- [x] Pool/SwimSpa temperatures missing in EHAL-Com Live-Lesen — thermal_rc rows now include `sens_temperature_water` / Soll / Toleranz / `sens_heating_active` (`ehal_debug_mapping` + `loxone_connectivity`); tests in `test_loxone_connectivity.py` / `test_loxone_debug.py`. Live acceptance verified.


### Bugfix Live main.py hang after control MILP (2026-08-12)

- [x] Live `main.py` hang after control MILP — `calculate_optimization_savings` now open-loop `commit_hours=len(matrix)` (was per-slot MPC on ~188 QH); test `test_calculate_optimization_savings_uses_open_loop_commit`. Live acceptance verified.


### Bugfix Chart-1 SoC ESS underlay thicker (2026-08-12)

- [x] Monitor Chart-1 SoC ESS-mode underlay thicker — `_ESS_UNDERLAY_LINE_WIDTH` 7.5→16.0, `_ESS_UNDERLAY_OPACITY` 0.4→0.2 in `ui/chart_soc.py`. Live acceptance verified.


### Bugfix EV Modus B QH preset power (2026-08-12)

- [x] Unsteady night EV / not max at cheapest (`debug_dump_20260812_054310`) — Modus B still treated `remaining_kwh` as hourly kW after QH (`dt_h=0.25`): preset `clamp(remaining)` and `rem > P_nom` for MILP-B. Fix: `ev_preset_charge_kw` / `ev_modus_b_uses_milp` use `remaining/dt_h` and `P_nom·dt_h`; tests in `test_eauto_milp_mode.py`. Verified.


### Version 2.5 — feature items (2026-08-11)

- [x] Battery standby power as 24/7 consumer (`standby_power_kw` on battery; Live + SE)
- [x] Netznutzungsentgelte MVP — import tariff Arbeitspreis (ct/kWh) into `k_act`; fake-invoice Netzentgelt split (Jahr + ## Netznutzung)
- [x] Quieter MILP INFO chatter; Optimierer-Dienst log-level filter ([INFO] / [WARNING] / …)
- [x] Monitor Chart-1 SoC ESS-mode underlay (Automode none; Zwangsladen cyan≈0 / blue charging)


### Version 2.5.d–h — Full QH MILP implementation (2026-08-11)

- [x] **2.5.d** Explicit `dt_h` plumbing (SoC, objective, wear, delivery energy, EV slot math, sim)
- [x] **2.5.e** QH planning window + prices; Live Energy-Charts with aWATTar expand fallback; `DEFAULT_DT_H = 0.25`
- [x] **2.5.f** Flex: `min_on`/`max_on_quarterhours` as real slots; thermal/generic day caps slot-aware
- [x] **2.5.g** Downstream: cons_data hour-hold, PV/outdoor/feature hold, chart 1:1 QH, `commit_hours`→slots, `loxone-signale.md`
- [x] **2.5.h** Soak (Live-sized HiGHS) + German user-doc note (`docs/konfiguration/preise.md`); spec status implemented


### Version 2.5.a–c — Quarter-hour migration study → decide B (2026-08-11)

- [x] **2.5.a** Data & tariff fidelity (Energy-Charts AT/DE-LU QH post‑2025‑10; CH hourly; catalog settlement map)
- [x] **2.5.b** MILP `dt_h` impact + light HiGHS N vs ~4N probe
- [x] **2.5.c** Owner decision **B** (full 15‑min MILP); closed research “quarterly-hour EPEX…” / **2.3.2**; implementation **2.5.d–h** archived below
- [x] Decision brief [`docs/spec/quarter-hour-slots.md`](../docs/spec/quarter-hour-slots.md)


### EV SOC-Min-Immediate ASAP floor (2026-08-11)

- [x] EV charged immediately to a min SOC independent from regular schedule — EHAL `get_evcs_soc_min_immediate` / VO `Earnie_EAuto_SOCMinSofort`; MILP ASAP delivery to floor then price-optimize remainder to Limit-SOC (not Sofortladen)


### Manual consumers opportunity-cost fictitious price (2026-08-11)

- [x] Manual appliance Startempfehlung: combined fictitious price (PV surplus × `k_push_act` + remainder × `k_act`); stars on same series; UI/docs; merged duplicate “PV into account” item from Version 2.+1


### Bugfix Chart 1 QH tariff plotted hourly (2026-08-11)

- [x] Chart 1 Preis/Einspeisepreis only stepped hourly with QH tariff (`debug_dump_20260811_203552`, VKW Dynamisch). Cause: `_hour_prices_from_df` / `_hourly_price_hv_xy` collapsed to one price per clock hour. Fix: per-slot HV steps; tests in `test_chart_mixed_resolution_traces.py`. Live acceptance verified.

### Bugfix Chart 1 phantom Kochen + missing battery export (2026-08-11)

- [x] Monitor Chart 1 phantom Kochen + missing battery export (`debug_dump_20260810_212549`) — skip known schedule peel on history Ist slots (`house_config/known_chart_display.py`); test `test_history_ist_slots_skip_known_schedule_peel`. Live acceptance verified.

### Bugfix BL Ziel €/kW ~4× too high with QH (2026-08-11)

- [x] BL Ziel €/kW ~4× too high with QH (`debug_dump_20260811_195848`) — matched baseline scaled full SwimSpa target onto single `live_snapshot` QH (`target/dt_h`); exclude live snapshot from profile shape. Live acceptance verified.

### Bugfix Chart 1 empty MILP gap after Ist (QH ≥:15) (2026-08-11)

- [x] Chart 1 empty MILP gap after Ist when `now.minute≥15` (`debug_dump_20260811_203552` 20:30–20:45) — `_milp_tail_rows` now prefers exact QH sim row (`_milp_row_for_quarter_slot`); test `test_build_chart_display_qh_milp_uses_exact_slots_not_missing_hour_zero`. Live acceptance verified.

### Bugfix SE battery standby ignored (2026-08-11)

- [x] Battery Standby Power not calculated correctly in SE — low vs high standby same result (`earnie_env`). Cause: `_scenario_to_battery_params` dropped `standby_power_kw`. Fix: pass standby through; regression in `tests/test_battery_standby.py`. Live path already OK. Verified (SE 1-month test).


### Bugfix HK analog numbers 3 decimals (2026-08-11)

- [x] Analog number in HK shown with only 2 digits → three — `labeled_number_input` defaults float widgets to `%.3f` (ints / explicit `format` unchanged); NNE AP `step=0.001`; tariff preview Cent values use 3 decimals. UI acceptance verified.


### Version 2.4.0 — Official release (2026-08-07)

EHAL foundation, DACH docking & Loxone on EHAL. Letter steps (`2.4.a`–`2.4.q`, …) archived under their own sections below / earlier in this file.

- [x] **2.4.r — Release** → official `2.4.0` (from `2.4.0-alpha.6`)
  - Sidebar logos (light/dark); greenfield Loxone import without `BRIDGE_DEFAULTS`; residual Merker → `ehal_bindings` only
  - EHAL-Com pool_filter field mapping; GitHub ticket intake & Streamlit Kontakt → Issues
  - Code quality (legacy/soft-compat + dual-key bridges fail-fast; coverage / obsolete tests / KPI refactor)
  - Official docs update + manual Doc-Review-Checklist
  - Ship gate accepted: EHAL frozen; OpenEMS / HA+evcc / Loxone via config; LoxBerry Scope A MVP; Path A2 messaging


### Pre-release 2.4.0-alpha.6 (2026-08-07)

- [x] Bump `version.py` to `2.4.0-alpha.6`; sync `docker/compose/*-alpha.yml` + `docs/einrichtung/container.md` example pins; GitHub Pre-release tag `v2.4.0-alpha.6`


### Docs Netznutzungsentgelte disclaimer (2026-08-06)

- [x] Document that **Netznutzungsentgelte** are currently **not** included in Live/SE costs: German docs (`tarife-quellen`, `preise`, handbook, `betriebsmodi`), SE UI captions, Szenarienkonfigurator info, Fake-Jahresrechnung Hinweise; invoice test updated. Feature work to model them remains open in `Backlog.md`.


### Bugfix history chart Strompreis EPEX vs retail k_act (2026-08-06)

- [x] `debug_dump_20260806_181907`: History logged `price_buy` (EPEX) as `market_price_cent` while live/plan used retail `k_act` → fake ~0.6 ct import/export gap then jump at boundary. Fix: log `k_act` (+ `epex_price_cent`); `_import_price_cent_from_entry` converts legacy EPEX rows for chart/cost analysis.


### Bugfix Bilanz Netz-Leistung dual-kWh CSV (2026-08-06)

- [x] **Bilanz Netz-Leistung dual-kWh CSV** — first value column `[kW]` stays bipolar power; `[kWh]` requires second `[kWh]` (Bezug − Einspeisung via ΔE/Δt); lone Netz energy counter rejected. Docs: `docs/konfiguration/verbrauchs-csv.md`. Tests: `tests/test_energy_counter_csv.py`. Verified.


### Document Review Loxone-Signale + Library merge (2026-08-06)

- [x] in loxone-signale.md: add motivation; replace user-facing "Greenfield" with "Default"; merge `loxone-earnie-library.md` into `docs/referenz/loxone-signale.md` (deleted library path); retarget TOC/UI/tests/templates README


### Document Review abbreviations glossary (2026-08-06)

- [x] Create a document with explanation of abbreviations — `docs/referenz/abkuerzungen.md`; linked from `docs/README.md`, handbook, and root `README.md`
- [x] Extended glossary from Doc-Review-Checklist Priority-1 docs (missing terms: B2C, BL, DACH, DSGVO, evcc, FTP, GHCR, Greenfield, GX, HITL, kWp, LoxAPP3, LoxBerry, LXC, MCP, Modbus, NAS, OpenEMS, RefMarkt, REST, SaaS, SG-Ready, SSD, VE, WR, …)


### Bugfix HK mobile Streamlit chunk load (duplicate) (2026-08-06)

- [x] **HK mobile `TypeError: Failed to fetch dynamically imported module` (`/static/js/ButtonGroup.<hash>`)** — same Streamlit stale/flaky JS-chunk class as Monitor (2026-07-17): phone keeps old hashed `/static/js` imports after upgrade, or a one-off fetch fails via DDNS/mobile; HK surfaces it when widgets lazy-load `ButtonGroup`. Already covered by global `ui/chunk_load_recovery.py` (injected from `app.py`). Error vanished after reload / side change — no new Earnie code fix. Not an HK logic bug.


### Bugfix HK Bilanz charts time horizon without battery CSV (2026-08-06)

- [x] **Mismatch in time-horizons of CSV files and weekly plot in HK charts** — Bilanz (`historical_csv_source=balance`) required PV+Batterie+Netz; with PV+Netz only (no battery), Gesamt-Lastverhalten fell back to synthetic modeled year 2023 (monthly Jan–Dec 2023, weekly KW 52/2022) while import QC showed the real CSV span. Fix: battery optional (0 kW); derive/persist/chart on PV∩Netz. Dump: `debug-dumps/users/UserA/earnie_env`. Tests: `test_derive_total_from_balance_without_battery`. Verified.


### 2.4.r Code Quality — coverage / obsolete tests / KPI refactor (2026-08-05)

- [x] **Coverage baseline** — added `ehal` to `[tool.coverage.run]` + `COV_SOURCE_PACKAGES`; refreshed `LEGACY_TEST_SYMBOLS` for 2.4 removals; `test_health_report run --coverage` → overall **79.7%** (`data` 73.3, `ehal` 87.3, `house_config` 80.3, `optimizer` 83.3, `runtime_store` 79.3, `settings` 77.4, `simulation` 86.5); no package &lt; 40%; workflow docs in `.cursor/rules/test-health.mdc`
- [x] **Obsolete-test / dead-code audit** — `pytest --dead-fixtures` clean; vulture unused imports removed (`bootstrap` schema-template imports, `KIND_EXPORT_BATTERY`, `loxone_log_import`, `build_chart_history` in diag); rewrote obsolete `legacy_id` matrix soft-bridge test → canonical keys; mock-heavy / fail-fast `pv_follow_name`/`legacy_id` flags kept (manual triage)
- [x] **KPI refactor (bounded)** — split hard-limit funcs in `settings/flexible_consumers.py` (`normalize_thermal_control`, `normalize_consumer`) and `house_config/profiles_store.py` (`_normalize_consumer`, `_normalize_profile`); deferred mega-file splits (`optimizer/simulation.py`, `simulation/engine.py`, `integrations/loxone_*.py`, `planning_flex_bridge.py`)
- [x] Pytest: 2026 passed / 3 skipped after changes


### Bugfix EV min_power_kw > nominal_power_kw (2026-08-05)

- [x] **EV `min_power_kw` > `nominal_power_kw` crashes SE Live** — normalize rejects min>nominal and negative min; EV `min_on_quarterhours` default/coercion 4; UI seeds EV defaults on type switch; Loxone-Import EV stub `3.5`/`1.4`/`min_on` 4. Verified.


### Bugfix Streamlit UI HTTP 500 GZipResponder (2026-08-05)

- [x] **Streamlit UI HTTP 500 on NAS/Docker (`GZipResponder` / `thread_minimum_size`)** — pin `starlette>=0.46.0,<1.4` in `pyproject.toml`; retag/overwrite pre-release `v2.4.0-alpha.5` (image rebuild). Verified.


### Bugfix SE crash when cons_data missing/empty (2026-08-05)

- [x] **SE crash when `cons_data_hourly.csv` missing/empty** — Backtesting time-range help no longer raises via `resolve_simulation_window`; guard empty cons_data (`1987684`, `v2.4.0-alpha.5`). Handbook: no-PV/no-battery baseline is automatic **Historisch** (no extra scenario). Tests: `tests/test_backtesting_time_ranges.py`. Verified.


### Bugfix SwimSpa filter power also on heating Ist (2026-08-05)

- [x] **SwimSpa filter power also on heating Ist** — shared meter: auto `subtract_consumer_ids` + native-filter inference over shared-meter heating ids (`v2.4.0-alpha.4`). Verified.


### Bugfix EVCS set_evcs_mode with max current (2026-08-05)

- [x] **EVCS `set_evcs_mode` with max current** — fixed current charging wrote mode `0`; now `2` (`now`) with `set_evcs_max_current`, PV surplus `1`, idle `0` (`698fc6a`, `v2.4.0-alpha.2`). Verified.


### EHAL-Com Silent/Loud status vs daemon (2026-08-05)

- [x] EHAL-Com status bar combines Silent-/Loud-Modus with Optimierer-Dienst running state (`ui/loxone_debug.py`); no longer implies writes when `main.py` is stopped. Docs `ehal-com.md`; tests `test_loxone_debug.py`.


### Plant-owned sens_temperature_outside (2026-08-05)

- [x] Außentemperatur only on `plant.ehal_bindings.sens_temperature_outside` — no runtime consumer/legacy dual-read; migrate promotes then strips leftover consumer keys; Live-Lesen includes plant ambient; docs C.1 / C.5 / C.6.


### HK/SE path caption + scenario copy-on-new (2026-08-05)

- [x] Show used config path in HK and SE as information — `st.caption` with `resolve_house_profiles_json_path()` / `resolve_backtesting_scenarios_json_path()` after page title.
- [x] When adding a new scenario, copy the last selected scenario as template and take the label + "copy" — `new_scenario_template` deep-clones last real selection (fallback Live); unique `{label} copy`.


### Bugfix HK consumer remove stale labels (2026-08-05)

- [x] **Consumer „Energiebezug“ not removable on Hauskonfigurator** — After Loxone Import, `Entfernen` deleted the session entry but index-scoped `hc_*` widgets kept old Bezeichnung values; sync + auto-persist renamed shifted consumers. Fix: `_clear_consumer_widget_keys` before rerun. Verified.


### Drop synthetic SwimSpa filter bridge (2026-08-04)

- [x] **2.4.r — Review old `*_BRIDGE_DEFAULTS` / Remove legacy defaults** — Deleted `SWIMSPA_FILTER_BRIDGE_DEFAULTS` and thermal_rc auto-inject; MILP filter is house-profile `pool_filter` only (`planning_pool_filter_to_milp`); removed synthetic EHAL entity / `swimspa_filter_bindings`; migration `scripts/migrate_pool_filter_milp.py`; deviation scopes → `pool_filter`; docs updated.


### EHAL-Com pool_filter field mapping (2026-08-04)

- [x] **2.4.r — map pool_filter EHAL fields in EHAL-Com** — HITL exposes `flex.pool_filter.sens_power_act`, `get_filter_remaining_hours`, `sens_filter_active`, native start/duration (+ Freigabe) on greenfield `pool_filter`; MILP overlay remaps flex keys onto bridged `swimspa_filter`; docs `ehal-com.md` §C.6. Tests: `test_ehal_loxone_mapping_entities.py`, `test_house_config.py`.


### EHAL-Com manual Merker mapping (2026-08-03)

- [x] **2.4 polishing — manual Merker in EHAL mapping** — Per-field creatable selectboxes on EHAL-Com (`accept_new_options`); confirm dialog saves new Merker into options and maps the EHAL field to `house_profiles.json`; optional HTTP probe; Live table column titles `Mapping auf Loxone` / Home Assistant / OpenEMS. Docs `ehal-com.md`; tests `test_ehal_loxone_mapping_entities.py`, `test_loxone_debug.py`.


### entity-scoped pool Freigabe + Live-Schreiben flex (2026-08-01)

- [x] **status.json pool VI Check keys** — bare `Earnie_Pool_Freigabe` / `Earnie_Pool_Filter_Freigabe`; legacy SwimSpa enable Merkers dual-read onto those keys; VI templates `Analog=true` (sticky).
- [x] **Greenfield `pool_filter` Freigabe → MILP bridge** — overlay enable onto filter bridge; auto `subtract_consumer_ids` for shared SwimSpa meter; native filter inference uses shared-meter heating ids.
- [x] **EHAL-Com Live-Schreiben** — flex Freigabe / `set_enable` (+ optional power setpoint) in write table; drop bridged `swimspa_filter` row when greenfield `pool_filter` exists; docs §C.6 / Live-Schreiben.


### EHAL-Com get_filter_remaining_hours mapping (2026-08-01)

- [x] **Pool / SwimSpa Filter mapping in EHAL-Com** — synthetic entity `swimspa_filter` for `get_filter_remaining_hours` (plus filter power/Freigabe/aktiv/native window); persist under `swimspa_filter_bindings`; dual-read via `marker_get_filter_remaining_hours`; remove hard-coded `Ernie_Swimspa_Filter_Sollstunden` bridge default. Live-Lesen + docs (§C.6 / flexible-verbraucher / loxone-signale). Tests: mapping, resolve, consumer targets, planning bridge.


### entity-scoped Virtual In status.json (2026-08-01)

- [x] **Daemon `GET /ehal/loxone/status.json` (port 8541)** — entity-scoped VI payload from last-run `loxone_sent` (plant `set_ess_*` in kW, EV/flex namespaced Check keys, pool Freigaben) plus live `heartbeat_ts`; VI templates/docs retargeted from Streamlit `:8501` to daemon `:8541`. Tests: `tests/test_loxone_status_json.py`, `tests/test_loxone_request_http.py`.


### Bugfix Chart 2 flat Verbrauch optimiert (2026-08-01)

- [x] **Chart 2 „Verbrauch optimiert“ constant** — snapshot reload rebuilt costs + matched consumption but omitted `hourly_optimized_consumption_kwh`; alignment filled zeros → flat cumulative at Ist offset. Fix: `_attach_hourly_series_from_rows` also recomputes optimized consumption from `simulation_rows`. Test: `tests/test_live_display_loader.py`. Verified live.


### Bugfix Chart 1 oversized EV ghost bar (2026-08-01)

- [x] **Oversized EV ghost outline on Chart 1** — matched-baseline flex scaled remaining EV target into one profile hour (~10.87 kW vs `nominal_power_kw` 3.5). Ghost outlines in `add_matched_flex_ghost_traces` capped to `nominal_power_kw`; matched-baseline energy/simulation unchanged. Dump: `chart_debug_review/debug_dump_20260801_080011`; verified.


### Bugfix Missing monthly tariff warning timing (2026-08-01)

- [x] **Show warning for missing monthly tariff only at end of month** — UI (sidebar + Szenarienkonfigurator) for missing next-month `monthly_table` rates only in the last 2 calendar days (`is_within_days_of_next_month`); pricing fallback/log unchanged. Tests: `tests/test_tariff_pricing.py`. Docs: `docs/konfiguration/preise.md`. Verified.


### 2.4.q Hardware registry first approach (2026-08-01)

- [x] **2.4.q — Hardware registry first approach** *(before release; builds on `2.4.i` spike)*
  - [x] End-to-end soft registration for 2.4 community / official images: fingerprint visible + copyable under Info / About; mailto request with fingerprint; drop-in `earnie_registry.json`; status caption (`unbound` / `valid` / `mismatch` / `invalid_sig`)
    - [x] Harden issuer path for real hand-outs: verify Earnie-Projekt `Entwicklungsplan/Hardware-Registry-Ausstellung.md` against `scripts/issue_dev_registry_token.py` + `share/registry/`; document where the HMAC secret lives (operator-only, never in image/git)
    - [x] Optional mild UX: stronger Info / About note on `mismatch` / `invalid_sig` — still **no** refuse-to-start, still **no** Cosign/Sigstore (full Layer C stays under `2.+1`)
    - [x] Spec / handbook touch-up if the first approach changes the user flow: [`docs/spec/hardware-registry-layer-c.md`](../docs/spec/hardware-registry-layer-c.md), handbook § Hardware-Registry
    - [x] Acceptance: one real fingerprint → issued file → bound status on a lab install; `unbound` remains allowed private use
  - [x] Add information about registry status in hints in streamlit app "Earnie · privat, nicht-kommerziell · https://github.com/JochenTCC/Earnie ..."
    - [x] Make it red, when not bound
    - [x] Make it green, when bound


### 2.4.q Chart / ESS test / Request Optimize (2026-08-01)

- [x] **Batterie-Energieflüsse** stacked Laden (PV/Netz) + Entladen (Verbrauch/Einspeisung) with balance caption
- [x] Remove **ESS-Schnittstelle testen** from Optimierer-Dienst (UI + `force_write_ess_test_setpoints` helpers)
- [x] Remove Merker event-trigger polling; wake via `Earnie_Request_Optimize` → daemon HTTP `:8541` (`POST /ehal/loxone/request_optimize`)


### Bugfix Monitor consumers not identified (2026-08-01)

- [x] **Consumers are not identified properly in charts on Monitor page but all power signals are available** — live meter read used only legacy `loxone_inputs.power_name`, so EHAL-only bindings were never measured (power still visible on debug). Fix: `_read_consumer_meter_kw` dual-reads EHAL markers (`marker_flex_power` / EVCS active power); known house-profile meters included in live flex/Sankey. Tests: `tests/test_loxone_client.py` (`test_resolve_live_power_reads_ehal_bindings_without_legacy_power_name`, known-meter coverage). Live verified.


### 2.4.p UI polishing + pre-release 2.4.0-alpha.1 (2026-07-31)

- [x] **2.4.p — UI polishing**
  - [x] Show `earnie.log` tail on Optimierer-Dienst (expander)
  - [x] LoxBerry plugin: change Streamlit IP port
  - [x] Merge NAS/current config parameters into greenfield import (markers from greenfield kept)
  - [x] At start: send all virtual inputs / `earnie_set` values once (not only on change)
  - [x] Pre-release **2.4.0-alpha.1**


### Bugfix EV absent daytime plan after overnight ready_by (2026-07-31)

- [x] **EV absent daytime plan after overnight ready_by** — dumps `debug_dump_20260731_075323` / `091219`: FertigUm kept overnight open past config `ready_by` → daytime Smart plan while unplugged. Fix: `resolve_absent_availability` (config `ready_by` bound). Also shipped on `hotfix/2.3.2` (`v2.3.2`) with Ist-SOC config-path port. Tests: `TestAbsentAvailability`, `TestLoxoneAbsentForecast`. Live verified: unplugged daytime → no EV plan before next `car_available_from`.


### Bugfix Live-Schreiben summary vs table (2026-07-31)

- [x] **Live Schreiben said 8 signals written, but only 6 shown** — banner counted raw `loxone_writes` (incl. Freigabe/`charge_immediate`); table is `set_*` only. Summary now from table rows; caption for omitted Freigabe/Legacy. Tests: `tests/test_loxone_debug.py`. Live verified.


### Bugfix EV re-plan after charge complete (2026-07-31)

- [x] **EV still connected after charge → re-planned full charge** — config-path house-profile EVs now honor Ist-SOC complete; `plug_cycle_fulfilled` latch survives deadline purge while plugged (cleared on unplug). Real SOC (or equivalent complete signal) remains necessary when Earnie has no fulfillment memory and Rest-/Ist-SOC stay stuck at plug-in values. Tests: `tests/test_charging_session.py`, `tests/test_charging_context.py::TestPluggedInChargeComplete`. Live verified.


### Bugfix Missing next-month monthly_table rate (2026-07-31)

- [x] **Missing next-month `monthly_table` rate** — pricing falls back to same month prior year, else prior calendar month (log warning); Szenarienkonfigurator warns + appends Cent/kWh into `earnie_env/config/tariffs.json`; `reload_config` / `reinit_config` reread disk. Tests: `tests/test_tariff_pricing.py`, `tests/test_feed_in_prices.py`, `tests/test_append_monthly_rate.py`. Live verified.


### 2.4.o Changes / EHAL-Com cleanup (2026-07-31)

- [x] **2.4.o — changes**
  - [x] Move button "Nein - manuell fortfahren" at same row as "Loxone-Import"; move hint "Neues Hausprofil ..." accordingly
  - [x] Include the consumer type in label of consumers expander (like "Verbraucher 1 (Haus Wärme): ...")
  - [x] Change "Loxone-Import (Merker + EFM → Hausprofil / EHAL-Bindings)" label on HK page to chapter size
  - [x] Merge Loxone-Import hints into one with Anleitung link
  - [x] Button "Loxone-Import" disabled until Loxone credentials/access work; hint otherwise
  - [x] EHAL-Com: remove MCP mapping source UI, Ollama UI, Quellenvergleich, Quellen selection — HTTP-Probe only for mapping names; MCP/Ollama code kept in `integrations/` for later re-integration; docs `ehal-com.md` / `ehal.md`


### 2.4.o Tuning Greenfield Import (2026-07-31)

- [x] **2.4.o — Tuning Greenfield Import** — Merker↔Zähler merge (strip Zähler/Zaehler; slug/aliases pool↔swimspa, e_auto↔wallbox); same-id merge ev/thermal_rc; **Loxone-Import** on Hauskonfigurator above Verbraucher (replaces EHAL-Com Greenfield button); EHAL-Com mapping hint; docs `ehal-com.md` / `loxone-earnie-library.md`.


### 2.4.n Greenfield Loxone Import - Workflow (2026-07-31)

- [x] **2.4.n — Greenfield Loxone Import - Workflow** — P1 naming freeze + entity-scoped full draft set under `share/loxone/templates/` (`VI_`/`VO_` Plant, EV, Heatpump, Consumer, Pool, Status); P2 `integrations/loxone_greenfield_import.py` (exact + Prefix+Slug casefold, EFM merge, HTTP probe); P3 HK onboarding → EHAL-Com **Greenfield importieren**; P4 German how-to [`docs/einrichtung/loxone-earnie-library.md`](../docs/einrichtung/loxone-earnie-library.md) + TOC/EHAL-Com/HK links; ehal-com **C.5** Wärmepumpe / **C.6** Pool + Aussentemp; Plant VI ESS Design C1 (`Earnie_Batterie_Sollleistung` + sticky `set_ess_mode`). Plans: `.cursor/plans/greenfield_loxone_import_303f8861.plan.md`, `.cursor/plans/vo_sens_get_templates_9cbef698.plan.md`, `.cursor/plans/ehal_ess_design_c1_9ae0ebdd.plan.md`. Config **Als Vorlage speichern** canonical re-export closed with chapter (drafts ship as library).


### 2.4.o EHAL ESS active power Design C1 (2026-07-31)

- [x] **2.4.o — EHAL ESS active power (Design C1)** — Portable `set_ess_active_power` (signed W); charge/discharge = true caps; `schema_version` 3; OpenEMS Equals + limits; Loxone/HA Merker/entity; greenfield `Earnie_Batterie_Sollleistung`; sticky-Merker docs (`set_ess_mode=0` = Automatik); Optimierer-Dienst ESS force-test presets via `force_write_ess_test_setpoints`; Plant VI Titles aligned; plan `.cursor/plans/ehal_ess_design_c1_*.plan.md`.


### 2.4.l EFM auto-sync Interpretation C (2026-07-30)

- [x] **2.4.l — EFM auto-sync (interpretation C)** — Lab: LoxAPP3 Meter/EFM `nodes` + live `/jdev/sps/io/{name}` as `flex.power_name`; MCP has no `control_bind`. Research note [`docs/dev/done/efm-auto-sync.md`](../docs/dev/done/efm-auto-sync.md); HITL [`integrations/loxone_efm_meters.py`](../integrations/loxone_efm_meters.py) + [`ui/ehal_efm_import.py`](../ui/ehal_efm_import.py) on EHAL-Com; CSV still manual; enable/setpoint not from Zähler; German [`docs/ui/ehal-com.md`](../docs/ui/ehal-com.md) + [`docs/konfiguration/verbrauchs-csv.md`](../docs/konfiguration/verbrauchs-csv.md).


### Bugfix LoxBerry Plugin Stop button (2026-07-30)

- [x] **LoxBerry Plugin — Button "Stop" not working** — ctl lived under non-installed `sbin/` with invalid `REPLACELBPSBINDIR`; moved to `bin/earnie_ctl.sh`, PHP uses `$lbpbindir` + plugin `sudoers`, start/stop/restart wait before redirect so status updates on first reload.


### Bugfix Hausprofil Verbraucher expander kWh/a (2026-07-29)

- [x] **Displaying annual consumption of consumer in expander isn't updated after editing parameters** — expander title now overlays live widget values, session syncs full edited consumer fields, and expander `key` includes rounded annual kWh so Streamlit refreshes the label while open/closed state is preserved separately (`ui/house_config_profile_form.py`).


### 2.4.m Remove obsolete FTP log + PV-tuning config (2026-07-29)

- [x] **2.4.m** — Dropped `loxone_blocks.log_filename` / `pv_tuning_log_file` (schema, examples, env configs); removed `fetch_loxone_csv_file` + loader attrs; strip drops empty `loxone_blocks`; German docs updated (consumption via CSV/cons_data; no Miniserver FTP).


### EHAL-Com Live-Lesen / Live-Schreiben EHAL columns (2026-07-29)

- [x] Update Chapter "Live-Lesen" in EHAL-Com with EHAL value names and actual mapping to smarthome backend — Live-Lesen only `sens_*`/`get_*` (no PV-Zähler / `set_*`); Live-Schreiben `set_*` with columns EHAL-Feld + Mapping; UI [`ui/loxone_debug.py`](../ui/loxone_debug.py), probes [`integrations/loxone_connectivity.py`](../integrations/loxone_connectivity.py), helpers [`integrations/ehal_debug_mapping.py`](../integrations/ehal_debug_mapping.py); German [`docs/ui/ehal-com.md`](../docs/ui/ehal-com.md)


### 2.4.j / 2.4.k EHAL wire + entity mapping (2026-07-29)

- [x] **2.4.j — EHAL wire & core semantics** — `schema_version` 2; §C `sens_*` / `set_*` / `get_*` in schemas, roles, adapters (Loxone/HA/OpenEMS), `ehal_live`; PV ∫ power → `pv_kwh_interval`; drop ESS `target_soc` / EV plug-in Rest-SOC / Sofortladen countdown Merker; `set_ess_mode`, `set_evcs_current`, `set_evcs_mode`, `get_evcs_nominal_current`, `sens_power_consumers` (Merker or derive); docs [`docs/spec/ehal.md`](../docs/spec/ehal.md).
- [x] **2.4.k — Entity-centric EHAL mapping** — `house_profiles` `plant` / `consumers[].ehal_bindings` + entity `event_triggers` (out of `config.json`); migrator/aggregate [`house_config/ehal_bindings.py`](../house_config/ehal_bindings.py); EHAL-Com entity HITL save; remove scattered Merker editors; German [`docs/ui/ehal-com.md`](../docs/ui/ehal-com.md).


### 2.4.i Hardware registry + Layer C research spike (2026-07-28)

- [x] **2.4.i** — Clarified one-time hardware-bound registry UX + Layer C prerequisites in [`docs/spec/hardware-registry-layer-c.md`](../docs/spec/hardware-registry-layer-c.md); spike: `runtime_store/hardware_identity.py`, `runtime_store/registry_entitlement.py` (dev HMAC), `share/registry/`, CLI `scripts/print_hardware_fingerprint.py` / `scripts/issue_dev_registry_token.py`, soft Info/About caption (no refuse-to-start, `release.yml` unchanged). Full Layer C enforcement deferred to `2.+1`.


### 2.4.h Multi-system field test (2026-07-28)

- [x] **2.4.h — Multi-system field test (Phase 4)** *(was 2.5.d)* — Automated config-switch proof OpenEMS ↔ HA+evcc ↔ Loxone (`tests/test_ehal_contract_backends.py`: routing, power parity, ESS write asymmetry, capabilities); German adapter choice [`docs/einrichtung/adapter-wahl.md`](../docs/einrichtung/adapter-wahl.md); expanded connector recipe [`CONTRIBUTING.md`](../CONTRIBUTING.md) §3 + [`docs/spec/ehal.md`](../docs/spec/ehal.md). Live compose/HITL deferred (soft check for `2.4.0`).


### 2.4.g Device / hardware profile schemas (2026-07-28)

- [x] **2.4.g — Device / hardware profile schemas (M2 slice)** *(was 2.5.c)* — EHAL device-role templates (`share/ehal/device_roles.schema.json`, `share/ehal/roles/`); Modbus/SunSpec outline (`share/hardware_profiles/`); Loxone JSON Merker recipes (`share/loxone/recipes/`); loader `ehal/profiles.py` + `tests/test_ehal_profiles.py`; HITL role grouping on EHAL-Com; docs [`docs/spec/ehal.md`](../docs/spec/ehal.md), [`CONTRIBUTING.md`](../CONTRIBUTING.md) §4, [`docs/ui/ehal-com.md`](../docs/ui/ehal-com.md).


### 2.4.f Loxone one-click mapping + structure research (2026-07-28)

- [x] **2.4.f — Loxone one-click mapping + structure research (§3.1)** *(was 2.5.b)* — Structure **compare-all** `integrations/loxone_structure.py` (LoxAPP3.json + MCP 17.1 `tools/list`; no first-wins cascade); EHAL↔`loxone_blocks` + optional Ollama `integrations/loxone_ehal_mapping.py`; HITL `ui/ehal_loxone_mapping.py` on EHAL-Com; docs [`docs/ui/ehal-com.md`](../docs/ui/ehal-com.md) + [`docs/spec/ehal.md`](../docs/spec/ehal.md). Production structure source TBD after lab. EFM interpretation C split to open **2.4.i**.
- [x] **2.4.f follow-up — drop HTTP probe** (2026-07-29) — Removed `http_probe` from one-click structure sources (only re-validates already-mapped markers; no new names). Default compare-all: LoxAPP3 + optional MCP 17.1.


### 2.4.e Loxone-EHAL adapter extraction (2026-07-28)

- [x] **2.4.e — Loxone-EHAL adapter extraction (Phase 3)** *(was 2.5.a)* — `integrations/loxone_adapter.py` emits M1 EHAL telemetry/setpoints/capabilities from `loxone_blocks` / `LOXONE_*` markers; default `ehal.backend=loxone` via `ehal_live.get_adapter()`; Huawei extras + flex remain on `loxone_client` (`is_ehal_network_backend` still openems|ha only). Spec notes in [`docs/spec/ehal.md`](../docs/spec/ehal.md); tests: `test_loxone_adapter.py`, contract/live/setup + main harness.


### 2.4.d LoxBerry plugin Scope A MVP (2026-07-28)

- [x] **2.4.d — LoxBerry plugin Scope A MVP (thin Docker wrapper)** — In-repo [`packaging/loxberry/`](../packaging/loxberry/) (plugin `0.1.0`): hooks + systemd + compose for `ghcr.io/jochentcc/earnie-energy:latest`, minimal Plugin Admin UI, healthcheck, `release.cfg` stubs; German docs [`docs/einrichtung/loxberry-plugin.md`](../docs/einrichtung/loxberry-plugin.md); uninstall keeps `earnie_env` policy documented. Hardware ZIP install on LB 4.x still optional for live acceptance.


### EHAL-Com unified smarthome connection (2026-07-28)

- [x] **EHAL-Com** — Renamed Loxone-Com; removed sidebar Loxone credentials; backend selector (Loxone / HA / OpenEMS) + connection forms; backend-aware first-run; EHAL Live-Lesen telemetry + `ehal_writes` Live-Schreiben parity; German docs (`docs/ui/ehal-com.md`)


### 2.4.c HA-EHAL + evcc under HA (2026-07-28)

- [x] **2.4.c — HA-EHAL + evcc under HA (Phase 2b / M1.5, DACH default)** — REST-only `integrations/ha_adapter.py` + Live bridge; Compose [`docker/compose/ha-lab.yml`](../docker/compose/ha-lab.yml) (Earnie :8506 + HA :8123 + evcc :7070); HITL entity→EHAL mapping UI; exclusivity/Modbus docs ([`docs/dev/ha-lab-setup.md`](../docs/dev/ha-lab-setup.md), [`docs/einrichtung/ha-evcc.md`](../docs/einrichtung/ha-evcc.md)); contract-tests vs OpenEMS; lab stub `ha_lab/evcc/evcc.yaml` (demo charger)
- [x] **HA lab smoke (Path A helpers)** — Earnie ↔ HA REST via helpers / LLAT path exercised
- [x] **Follow-up — Lab HA ↔ evcc entity exposure** — marq24 ha-evcc (`http://evcc:7070`) entities in HA; mapped in Earnie HITL; Compose `hacs-init` + docs §5.1 / [`ha-evcc.md`](../docs/einrichtung/ha-evcc.md) (MQTT discovery path documented as alternative, not required once marq24 is connected)


### Bugfix SoC spike at SA₁ (2026-07-27)

- [x] **SoC spike at SA₁ (night grid charge → forced dump)** — Live hourly MPC charged before sunrise SOC_min for later EV, then re-opt moved EV and forced export. Mitigations: (1) PV-only charge through sunrise; (2) drop hard `e_batt[SA₁]==SOC_min` (residual dump; floor stays via bounds). Spec: `docs/spec/planning-horizon-sunset.md`. Tests: `tests/test_milp_sunrise_soc.py`. Live verified (NAS main + Chart 1).
- [x] **Chart 1 SA₀→SA₁ flat last-hour SoC** — live current-hour ramp cleared horizon SoC tail (`seg_tail_for_line=None`); keep end-of-hour tail so 05:00→06:00 slope shows. Fix: `ui/chart_soc.py`; test: `tests/test_charts_soc_tail.py::test_horizon_soc_tail_kept_when_current_hour_ramp_active`


### 2.4.b OpenEMS EHAL prototype (2026-07-27)

- [x] **2.4.b — OpenEMS EHAL prototype (Phase 2 / M1)** — REST-only `integrations/openems_adapter.py` + thin Live bridge `integrations/ehal_live.py` (`ehal.backend=openems`); lab Compose [`docker/compose/openems-lab.yml`](../docker/compose/openems-lab.yml); write-lock degrade → `runtime/ehal_write_error.json` + Streamlit hint; config schema/snippet; mocked tests; no OpenEMS libs in-repo (→ 2.4.c / 2.4.e)
- [x] **OpenEMS lab acceptance (combined Compose)** — Pi/lab host `192.168.178.34`: Earnie ↔ OpenEMS REST communication verified per [`docs/dev/openems-lab-setup.md`](../docs/dev/openems-lab-setup.md); Live-Cockpit Loxone-marker gate still stubbed (expected)


### 2.4.a EHAL specification (2026-07-27)

- [x] **2.4.a — EHAL specification (Phase 1 / M1 spec)** — Freeze Telemetry / Setpoint / Capability-Flags (+ Write-Error) JSON Schemas (`share/ehal/`), thin Python package `ehal`, connector-author spec [`docs/spec/ehal.md`](../docs/spec/ehal.md), CONTRIBUTING adapter outline; sign/units/60 s/degrade frozen; no Live/Loxone wiring (→ 2.4.b / 2.4.e)


### Bugfix SE Fake-Jahresrechnung Verbrauch vs Gesamtkosten (2026-07-27)

- [x] **SE Fake-Jahresrechnung Verbrauch ≠ Gesamtkosten Jahres Verbrauch** — Invoice used `sum(consumption_kw)` (sunrise gaps/overlaps); SE used window plausibility totals. Shared `simulation/jahres_verbrauch.py`; invoices get `verbrauch_info_kwh_by_scenario` from the same map. Tests: `tests/test_monthly_fees.py`


### Bugfix EPEX tariff VAT / monthly fees (2026-07-27)

- [x] **EPEX tariff VAT / monthly fees** — Spot tariffs store settlement + `monthly_fee_eur` **net** with `prices_include_vat: false`; export `monthly_table` (+ VKW PV Dynamisch) use `vat_percent: 0` (ohne USt). Catalogs: `share/config/tariffs.json`, `earnie_env`, `earnie_env_se_m2`. Docs: `tarife-quellen.md` §3/§4/§7, `preise.md`


### Bugfix Detaillierte Simulationsansicht day UX + SA preselect (2026-07-27)

- [x] **Detaillierte Simulationsansicht day-change / UX** — Δ% in header; default SA₁→SA₂; ⚪ = ≤5% rel.; snapshot JSONL mtime index + session bundle cache (`bundle_ms` ~170→~18 warm)
- [x] **SA segment preselect by date overlap** — on Charts & Diagnose laden, prefer SA₀→SA₁ vs SA₁→SA₂ by hourly overlap with the selected calendar date (`preferred_sa_segment_toggle`)


### Bugfix SE Detail Chart missing Smart EV (2026-07-27)

- [x] Small EV Modus-B presets in SE open-loop (`logged_day`/`profile_spec`) place at cheapest eligible hour across horizon (`optimizer/eauto_milp.py`), not only slot 0
- [x] SA segment auto-preselect prefers the segment with more flex energy so deadline-EV in SA₀→SA₁ is visible (`preferred_sa_segment_toggle`)
- [x] Tests: `test_eauto_milp_mode.py` (open-loop cheapest hour), `test_backtesting_display_bundle.py` (segment preference)


### Bugfix Detaillierte Simulationsansicht render profiling (2026-07-26)

- [x] Profiled SE detail view: bottleneck was `_run_anchors_for_meta` rescanning cons_data via `list_simulation_anchors` (~90–150 s per Streamlit rerun)
- [x] Derive in-run anchors from already-loaded `hourly_df` (+ session cache, cons_data fallback); overview ~65 ms / charts total ~228 ms
- [x] Test: `test_run_anchors_from_hourly_uses_last_slot_presence`


### 2.3.1 Detaillierte Simulationsansicht colors (2026-07-26)

- [x] Calendar severity markers remapped: 🟢 ohne Abweichung · ⚪ Verbrauchstoleranz / feasible CBC · 🟡 darüber · 🔴 CBC/MILP Problem (`ui/backtesting_deviation_calendar.py`)


### Bugfix SE sunrise_window spill months / fees > 12 (2026-07-26)

- [x] Clip SE/backtesting result hours to period `[start, end]` (`simulation/period_clip.py`); applied in `save_backtesting_log` and Fake-Jahresrechnung (not in `run_simulation` — book-window hours stay intact)
- [x] Monthly fees only for in-scope months (12 for last-12-months), not sunrise/fixed_24h spill stubs
- [x] Test: `test_clip_results_drops_spill_months_for_fees`


### 2.3.1 Fake SE annual invoices (2026-07-26)

- [x] Per-scenario German markdown Fake-Jahresrechnung after SE (`{log}/invoices/{label}_jahresrechnung.md`) with tariff names
- [x] Import/export € + kWh split; monthly table with Verbrauch (info), Bezug, Einspeisung; year totals
- [x] Separate Bezug/Einspeisung monthly tables with Ø Tarif (`Summe(k_act)/N`) and Ø Ist (`€/kWh×100`); catalog parameter tables at end; persist `k_act`/`k_push_act` on SE results
- [x] DACH fixed-fee schema slots (`grid_monthly_fee_eur`, `metering_monthly_fee_eur`, `other_monthly_fee_eur`) + Lieferant `monthly_fee_eur`; SE fee breakdown in log
- [x] Docs (`tarife-quellen.md`, `preise.md`, Handbuch) + tariff preview + tests


### Version 2.3 — Enhance consumer visualization and cost analysis - sharpen tariffs handling (2026-07-26)

Year-1 product depth (trust / What-If / churn). **Good-enough €** for SE and demos — invoice-grade bill reconciliation out of scope. Thin marker/data-model prep for SAM (`2.3.f`) done; connector rewrite remains `2.4`. Letter steps (`2.3.c`–`2.3.g`, CSV/Basislast, UI polish, EFM, Land/`supplier_id`, SE/SK polish, VKW Duo, …) archived under their own sections below / earlier in this file.

- [x] **2.3.0 — Release**
  - Finalize after SCC / community test of `2.3.0-alpha.3`; update German docs as needed (carry-over from 2.2.0 finalize)


### Bugfix HK Leistungsprofil labels (2026-07-26)

- [x] Replace Verbrauchsprofil / Historische Jahresprofile / PV-Ertrag UI labels with Leistungsprofil / Lastprofil / PV-Erzeugungsprofil [kW]; Gesamtverbräuche → Gesamt-Lastverhalten; Energiemonitor/Bilanz radio wording; clear buttons shortened; power-preferred + kWh-counter import hint; German user docs (Profil = kW, Verbrauch/Erzeugung = kWh)


### VKW Strom Duo catalog + monthly_table triples (2026-07-26)

- [x] Catalog import tariff `at_vkw_strom_duo` (`monthly_table` blended winter/summer rates; monthly fee 3,00 € netto)
- [x] `tariff_pricing._monthly_table_lookup` accepts normalized `(year, month, cent)` triples; clearer missing-month errors
- [x] Docs `tarife-quellen.md`; catalog count test + pricing unit test


### SK UI polish — static list + 2×3 matrix (2026-07-24)

- [x] Szenario selection: dropdown → static list; ↑/↓ in same row right of the list
- [x] 2×3 edit matrix (tariff-edit style): Bezeichnung / Aktiv für SE / Eigene Referenz; Hausprofil / Batterie / PV


### Remove SoC bei Opt-Last chart curve (2026-07-24)

- [x] Drop third Live Chart-1 SOC line **SoC bei Opt-Last** (UI/docs/tests); keep `baseline_same_flex_rows` for cost paths


### SK scenario order + own_reference (2026-07-24)

- [x] Scenarios order editable in SK (↑/↓; `scenarios[]` array order; Live pinned first) for user-centric SE visualization
- [x] Per-scenario `own_reference` toggle (heuristic default; force on/off) for non-optimized reference calculation; `enabled` pass-through in `normalize_scenario`


### Bugfix SE Season-Mirror page hang (2026-07-24)

- [x] SE rendering of subpage will not finish after mirroring for months was activated — `season_mirror_to_last_month` was written to `config.json` but omitted from `load_sim_path_params` / `scenario_explorer_conf_snapshot`, so `is_season_mirror_enabled()` stayed false and the checkbox path infinite-`st.rerun()`’d
- [x] Season-Mirror raised `Quellstunden fehlen` on incomplete newest calendar month (e.g. partial July 2026) — source year now prefers the most recent year that fully covers required target days


### SE / SK polish (Backlog L22–30) (2026-07-24)

- [x] HK Standort: Breitengrad / Längengrad / Land in one row
- [x] Rename Szenarieneditor → **Szenarienkonfigurator** (SK; user-facing; routes unchanged)
- [x] Verbrauchsdaten: synthesis fingerprint (profile + PV_KWP); hard-block SE runs on mismatch; no blanket meta invalidate on every HK save
- [x] Season-Mirror checkbox above Planungshorizont (`season_mirror_to_last_month`); remap by calendar month to wall-clock last 12 months
- [x] Scenario `enabled` for SE; SK checkbox; full SE log stale on toggle


### Mandatory Land + supplier_id monthly fees (2026-07-24)

- [x] House profile `land` (AT/DE/CH) in HK Standort; soft-default AT; SE Land filter mandatory (no Alle), seeded from profile
- [x] Required `supplier_id` on all tariffs (schema + catalogs); SE monthly fee once per supplier (`max` within group, sum across)
- [x] Docs: `preise.md`, `ueberblick.md`, `tarife-quellen.md`; tests for fees / land / catalog pair


### aWATTar SUNNY Spot catalog check (2026-07-24)

- [x] Confirmed official SUNNY Spot 60 min = EPEX − 19% × |EPEX| (no flat 1 ct/kWh); catalog id `dynamic_epex` already used `feed_in_fee_factor` 0.19
- [x] Added `monthly_fee_eur` 4.79 and corrected notes; env seeds overwritten from share


### Basislast Jahres-/Monats-Rest (Gesamtverbräuche + SE path A) (2026-07-24)

- [x] Radio in HK Gesamtverbräuche: **Jahres-Rest gleichmäßig** vs **Monats-Rest je Monat** (`baseload_distribution` on house profile)
- [x] Monats-Rest also used for SE path A when Gesamt-CSV present; path B (all controllable have CSV) unchanged
- [x] Docs: `verbrauchs-csv.md`, Handbuch, `scenario-explorer-consumption.md`


### UI polish (2026-07-24)

- [x] **Loxone-Com** (rename from Loxone-Kommunikation): Live-Lesen / Live-Schreiben at top of page; Anlagen-Merker + Event-Trigger chapter titles with edit fields in expanders; HK-style Entfernen beside Event-Trigger expanders; German docs / doc_links updated
- [x] **Szenarieneditor:** disable `— neu —` when `EARNIE_UI_MODES` lacks `scenario_explorer`; Land / Bezug Typ / Einspeise Typ in one row; Bezugstarif / Einspeisetarif and tariff parameters in matching columns (top-left empty)


### Pre-release 2.3.0-alpha.3 (2026-07-23)

- [x] Pre-release `2.3.0-alpha.3` for SCC / community test (GHCR `:<version>` only; alpha compose pinned)


### SE calc test max workers (2026-07-23)

- [x] `scripts/se_calc_test_run.py`: default `--workers` = max useful (`min(CPU, parallel jobs)`), Live-only ≈ 3
- [x] Cursor rule `.cursor/rules/backtesting-max-workers.mdc` for SE / backtesting worker choice
- [x] Spec note in `docs/dev/done/se-calculation-test-plan.md` after Live `export_tariff_id` re-run


### Energieflussmonitor → Hausprofil blueprint research (2026-07-23)

- [x] Add Energieflussmonitor Baustein and Zähler to own Loxone Config to test csv-data-export (closed with research outcome below)
- [x] Research whether own Loxone Energieflussmonitor + Zähler setup can blueprint Verbraucher-Konfiguration in Hausprofil (incl. CSVs)
  - **A (process blueprint):** yes — map Netz/Erzeuger/Speicher/Verbraucher/Rest → `grid_profile_csv` / `pv_profile_csv` / `battery_profile_csv` / consumer `profile_csv` + Basislast residual; plan `.cursor/plans/energieflussmonitor_hausprofil_blueprint_a.plan.md`
  - **C (auto-create consumers + CSV attach):** not officially feasible now (no structure export) — deferred under Version **2.4** MCP item in [Backlog.md](Backlog.md)
  - **Follow-up abandoned (same day):** HK multi-column Energieflussmonitor CSV import + exclusive Zähler↔Verbraucher mapping (plan `.cursor/plans/efm_meter_mapping_ui_9107b317.plan.md`, branch `feature/efm-meter-mapping-ui` deleted) — Loxone EFM does **not** export a multi-column Statistik-CSV with all Leistungsflüsse; idea was a dead end. Manual per-series / Energiemonitor (alt) / Bilanz remains the CSV path.


### SE calculation test plan (2026-07-23)

- [x] Comprehensive SE calculation test plan for Live/`example_efh` (path-A matrix; path B blocked until manuals have CSV)
- [x] Scripts: `se_calc_test_matrix` / `se_calc_test_run` / `se_calc_test_compare` (+ `se_calc_test_common`)
- [x] Executed M0/M1/M2 × months 2025-01/04/07/10; actual vs Live-ref vs optimized recorded in `docs/dev/done/se-calculation-test-plan.md` + `se-calc-test-results.json`


### Consumer editors UI polish (2026-07-23)

- [x] Change plots in "importierte Leistung" to rectangular style
- [x] Collect all marker settings in consumption editors into an expander that is hidden when `EARNIE_UI_MODES` is not `live_environment`
- [x] Put all buttons "Verbraucher-CSV entfernen" in all consumption editors right of upload in the same row (similar to historical profiles)


### Streamlit → docs deep-links (2026-07-23)

- [x] Add links to chapters in Streamlit that land on respective parts in various docs `.md` files (registry `ui/doc_links.py`, book icon + help popover, captions clickable)
- [x] Continuous maintenance skill: `.cursor/skills/streamlit-doc-links/SKILL.md`


### CSV / Basislast / earnie_role alignment (2026-07-23)

- [x] Clarify „Läufe pro Woche“ (=0 hint; allow 0 only for Bekannt+CSV; Gesteuert/Manual ≥1)
- [x] Rename checkbox to **„Von Basis-Last abziehen“**; role×HK/SE/Live usage documented
- [x] Hybrid SE Basislast: path **B** (meter residual) when Gesamt-CSV + all controllable generics have CSV; else path **A** (flat `baseload_kwh`); clip ≥ 0
- [x] Bekannt+CSV → fixed CSV overlay; Gesteuert/Manual → MILP (CSV window energy or schedule); Live Manual = user day-plan only
- [x] Bilanz import: `P_Ges = P_PV + P_Batt + P_Grid` (+ = into system) → derived `total_profile_csv`
- [x] Docs: `verbrauchs-csv.md`, Handbuch, SE consumption spec, `flexible-verbraucher.md`


### Import power plot & SE 12-month horizon (2026-07-23)

- [x] After importing either Verbrauch (Gesamt) or PV-Ertrag add a plot for the power for manual control of values and time interval. Plot shows complete time horizon of both imports.
  - If time horizon is less then 12 months give a warning, that Szenario-Explorer is needing at least 12 months
  - If time horizon is >= 12 months take the closest 12 month to now as time horizon for SE and the march in this range for SE test calculation


### Bugfix Hausprofil first-click tab key (2026-07-23)

- [x] Greenfield: first click on subpage **Hausprofil** raised `StreamlitAPIException` — `st.session_state.house_config_active_tab` cannot be modified after widget with key `house_config_active_tab` is instantiated (`page_house_config.py`); verified live


### 2.3.g — SE sunrise-booked steps (ready_by → SA₂) (2026-07-24)

- [x] **`sunrise_window` product path** — one SE step per ready_by day; SA₂ = first sunrise after ready_by; MILP SA₀→SA₂; book **[SA₁, SA₂)**; SoC chain at sunrise junctions; `charging_anchor = ready_by`
- [x] **Eliminates 7↔10 wall-clock gaps/overlaps** — abutting sunrise books independent of ready_by hour (length = astronomy/DST only)
- [x] **Subsumes `sunrise_full_horizon_trial`** — flag kept as deprecated config shim (ignored by engine); flex_book + SA₁ SoC hold are the default
- [x] Progress / CSV on booked hours (not `N×24`); docs: `planning-horizon-sunset.md` §4.2, SE user notes
- [x] Tests: `tests/test_sunrise_book_steps.py`; horizon-mode / flex_book adaptations

### 2.3.c.0a–2.3.c.3 — SE MILP speed & tuning (2026-07-23)

- [x] **2.3.c.0a — SE: one MILP per window (or commit-K) instead of hourly re-solve**
  - Open-loop / commit-K for SE perfect foresight; Live stays on periodic re-opt
  - **TAKEAWAY** — SE defaults: `sunrise_window` (sunset2sunset) + `commit_hours=24`
- [x] **2.3.c.0b — Trial: HiGHS vs CBC for SE**
  - **TAKEAWAY** — Differences negligible → **HiGHS is the new default** (Live + SE). CBC fallback via `EARNIE_MILP_SOLVER=cbc` / SE `milp_solver`. Artifacts: `backtesting_logs/solver_ab_m03`, `solver_ab_last12m`
- [x] **2.3.c.1 — Trial: fast paths for reference / trivial windows**
  - **TAKEAWAY** — Historisch/`ref:*` already closed-form. Optimized path skips solver when `battery_capacity_kwh<=0` and remaining flex=0 (`ENERGY_OPTIMIZER_MILP_TRIVIAL_FAST_PATH`, default on). Fixture A/B dEUR=0; `python -m scripts.ab_se_trivial_fast_path`
- [x] **2.3.c.2 — Tuning MILP for SE and Live**
  - **TAKEAWAY (SOC anchors)** — `disable_horizon_soc_anchor`; small € win on `sunrise_window`; mixed on `fixed_24h`. **Keep product anchors on**. Artifacts: `backtesting_logs/soc_anchor_ab_last12m/`
  - **TAKEAWAY (full SA_0-->SA_2)** — `sunrise_full_horizon_trial` without flexbook collapsed plaus (~127/365). Artifacts: `backtesting_logs/sunrise_full_ab_last12m/`
  - **TAKEAWAY (variable sample time)** — **hard — defer** (implicit `dt ≡ 1 h`; Live already re-opts ~15 min on hourly plan)
- [x] **2.3.c.3 — Full SA_0-->SA_2: force flex into booked slice**
  - Clamp `flex_indices` via `flex_book_hours` when full-horizon trial on
  - **TAKEAWAY** — last12m plaus restored 344/365; € Δ ≈ −7…−18 €/y vs truncated. **Product default (then):** `sunrise_full_horizon_trial` **true** (full SA_0-->SA_2 + flexbook + free SOC anchors). **Superseded by 2.3.g** (sunrise-booked [SA₁, SA₂) steps). Artifacts: `backtesting_logs/sunrise_full_flexbook_ab_last12m/`


### Energy-counter CSV import (PV / Verbrauch / consumers) (2026-07-23)

- [x] New import for cumulative `Counter [kWh]` (Date;Time or combined) → interval-average kW via \(P=\Delta E/\Delta t\)
- [x] Auto-detect (no radio): `[kWh]` / Zähler / Counter / Ertrag, else monotonic large-value heuristic; `[kW]` / Leistung stays power path
- [x] Counter drop: warn and ignore interval (`P=0`); wired into `detect_and_load_raw_series`; round-trip tests + German docs (`verbrauchs-csv.md`)


### 2.3.f — Thin marker / data-model prep (SAM optionality) (2026-07-22)

- [x] Role↔entity catalog + “Smarthome-Merker” wording (docs/schema); JSON keys `loxone_*` / `*.loxone` unchanged; Loxone sole live backend
- [x] Hauskonfigurator: editable marker assignments for EV / WP / SwimSpa / generic; optional `swimspa_filter_bindings` → `planning_filter_to_milp`
- [x] Loxone-Kommunikation: `loxone_blocks` + `event_triggers` forms; tests + German UI/signal docs
- Out of scope left for `2.4` / nested-models `2.+1` (connectors, HTTP extraction, device templates, full nesting)


### 2.3.e — Analyse Verbrauch & Kosten (2026-07-22)

- [x] Live-Cockpit rename **Verbraucheranalyse → Analyse Verbrauch & Kosten** (`consumer-analysis`)
- [x] Weekly consumer usage vs price/PV from `optimization_history.jsonl`; PV/battery/grid pro-rata via `allocate_slot_flows`
- [x] Point-of-use costs (grid share × import price only; PV/battery discharge = 0 €); rough KW/month/year KPIs with log coverage caption
- [x] Battery charge/discharge energy sums; manuals (`earnie_role: manual`) included (measured or schedule peel)
- [x] Swimspa temp/filter charts kept as secondary section; tests + German docs


### 2.3.d — Scenario Explorer polish (2026-07-22)

- [x] SE progress bars: ETA (“time left until finished”) during scenario simulation — `ProgressEtaTracker` / caption helpers in `simulation/backtesting_progress.py`; UI in `ui/backtesting.py` (reopened from 2026-07-16 baseline progress)
- [x] Stable progress-bar order during run — snapshot keyed by `result_id`; fixed preferred-id slots with placeholders; drop UI-side `prepare_progress_dir` before spawn (`ui/backtesting_runner.py`)
- [x] SE calculation speed deferred to **2.3.c.0a** / **2.3.c.0b** / **2.3.c.1** (not duplicated here)


### 2.3.c — Plan / SOC plausibility (2026-07-22)

- [x] Live Monitor Chart 1: explain SoC vs **SoC BL Ziel** (Lastverschiebung + Batteriestrategie) via caption/`?` + German handbook section
- [x] Third SOC line **SoC bei Opt-Last** from `baseline_same_flex_rows` (opt flex, BL battery), Jetzt onward
- [x] Ghost outline bars (**Original-Schedule**) for matched/BL-Ziel flex vs filled optimized bars
- [x] Chart-1 docs (`docs/ui/charts.md`); ghost filter energy-equivalent `< 1 kWh` (later: bar heights restored to **kW** — see Bugfix Chart 1 kW axis restore)
- [x] Known-generic duty cycle: fractional `duration_h` (e.g. Swimspa Jets) → average kW so Chart energy matches `nominal × planned duration`
- SE MILP speed/tuning (**2.3.c.0a**–**2.3.c.3**) archived separately above (2026-07-23)


### 2.3.b — Approximate cost model (monthly fees) (2026-07-22)

- [x] Optional `monthly_fee_eur` on import/export tariffs; SE `total_eur` / `monthly_eur` add one full fee per calendar month (not MILP / not hourly `sim_cost`)
- [x] Catalog seeds + VKW export VAT hygiene; Scenario Editor / SE captions label fees as approximate
- [x] User how-to [`docs/referenz/tarife-quellen.md`](../docs/referenz/tarife-quellen.md) (Nachrechnen + sources/audit)


### 2.3.a — Tariff hygiene (good-enough €) (2026-07-21)

- [x] Provider-independent AT Day-Ahead via Energy-Charts (`bzn=AT`), aWATTar fallback
- [x] OeMAG 2025 hygiene + `econtrol_referenzmarktwert_pv_monthly`; docs `docs/referenz/oemag-referenzmarktwert.md` + `tarife-quellen.md`
- [x] VKW Strom Dynamisch (import) + PV Dynamisch/Flex (export) in tariff catalog
- [x] Unify export `monthly_float` → `monthly_table` with owned `monthly_rates`; shared curves as maintenance seeds


### SE data-model hygiene + month horizon + v3 path-pair (2026-07-21)

- [x] Rename `file_paths_battery_simulation` → `scenario_explorer_conf` (kept in `config.json`; accessors `get_scenario_explorer_conf`; legacy key rejected; `earnie_data_model` → **3**)
- [x] Data-model hygiene after `scenario_explorer_conf` rename — three CSV layers in schema/docs; root `appliance_recommendation` = scoring; `flexible_consumers: []` Legacy overlay
- [x] Soft migrate — `resolve_simulation_window` month-aligned from cons_data (last complete month, 12 months back); drop `path_consumption`/`path_production` / `loxone_logs` bounds
- [x] Define SE overall horizon on recent complete cons_data month (then backwards for span); day iteration stays chronological (SoC chain)
- [x] Migration helper v2→v3 — bootstrap + `ensure_compatible` rename block / strip path pair / stamp 3; fail-fast gate for leftover path keys; schema/docs omit pair


### Version 2.2.0 — Official release (2026-07-22)

- [x] **Finalize Version 2.2.0 after test usage and make a release** — `version.py` `2.2.0`; tag `v2.2.0` (GitHub Latest + GHCR `2.2.0` / `:latest`); chapter archived from open backlog
  - German docs polish carry-over → open `2.3.0` in [Backlog.md](Backlog.md)


### Bugfix Chart 1 kW axis restore (2026-07-22)

- [x] **Chart 1 Monitor: restore kW axis (undo global kWh bar scaling)** — heights = power again; bar width carries duration; sub-hour future consumers stay duty-cycle averaged (`nominal × duration_h` in `generic_schedule`); grey 15‑min slots unscaled (`b2a4efc`); verified live


### Bugfix Verbrauch CSV import path + `_resampled` name (2026-07-22)

- [x] **Verbrauch CSV import path + `_resampled` name** — existence check uses `resolve_config_prefixed_path`; upload target `{original}_resampled.csv` (e.g. `BEZUG-2025-22.7.2026_resampled.csv`); was: false “nicht gefunden” on `config/uploads/…` + stable `{profile}_verbrauch.csv` name (`e21e3e3`); verified live


### Bugfix legacy export monthly_float abort (2026-07-22)

- [x] **Streamlit abort: `export_tariffs[…]` unknown type `monthly_float`** — soft-migrate on load + bootstrap persist to `monthly_table` with OeMAG-seeded `monthly_rates`; live packs still on pre-2.3.a catalog no longer crash


### Bugfix Verbraucher expander Bezeichnung label refresh (2026-07-22)

- [x] **Changed Bezeichnung in Verbraucher Edit is not updating the collapse label instantly (on first Verbraucher)** — already fixed via `_consumer_expander_title` (live `hc_label_*` session) + stable `hc_consumer_expander_{index}` key; re-verified live (not reproducible); runtime logs showed title matching Bezeichnung on rename for Verbraucher 1 and 2


### Bugfix NAS Chart 1 history without EARNIE_RUNTIME_PATH (2026-07-21)

- [x] **NAS launch: Chart 1 Monitor missing past data without `EARNIE_RUNTIME_PATH`** — `optimization_history` / `run_state` / `live_optimization_debug` / `single_instance` bound runtime via `read_runtime_path_or("runtime")` (ignored `EARNIE_ENV_PATH`); now use `persist_paths.runtime_dir()` / `runtime_path()` so `{ENV_PATH}/runtime` alone loads NAS `optimization_history.jsonl`; regression test; verified live on NAS :8503


### Bugfix Chart 1 PV *:00 seasonal spikes (2026-07-21)

- [x] **Chart 1 PV forecast spikes at *:00** — dump `chart_debug_review/debug_dump_20260721_165852`: gray-area `forecast_pv_kw` at *:00 matched seasonal synthetic (`kwp=6` summer) while :15/:30/:45 used forecast.solar. Fix: keep warm API cache on timeout/HTTP/429 instead of discarding it (`data/pv_forecast.py`); tests in `tests/test_pv_forecast.py`. Closed for now (user); intermittent failure-path live proof not pursued.


### Bugfix Hauskonfigurator Verbraucher expander on Bezeichnung (2026-07-21)

- [x] **Verbraucher editor collapsed after Bezeichnung change (e.g. E-Auto)** — expander title includes live Bezeichnung but had no stable `key`, so Streamlit remounted it collapsed on rename + auto_persist `st.rerun()`; fixed with `key=hc_consumer_expander_{index}`; verified live


### Bugfix Remove Live-Konfiguration page (2026-07-21)

- [x] **Remove Live-Konfiguration page** — page + `ui/config_forms.py` removed; nav no longer registers it; Live scenario Bezeichnung locked (UI + `upsert_scenario`); delete already blocked; docs updated to Szenarieneditor; greenfield: Live-Cockpit stays gated on Loxone markers with notice on **Loxone-Kommunikation**; verified live


### Version 2.2.0 — SCC per-session Greenfield (2026-07-21)

- [x] **App on Streamlit cloud should start always with Greenfield** — `EARNIE_CLOUD_DEMO=1`: per-browser-session temp env (`runtime_store/cloud_demo.py`), session-aware `persist_paths`, skip offline seed, restricted nav opens Hauskonfigurator without Live/Daemon, German intro banner; docs `private-env.md` / `betrieb.md`; tests `tests/test_cloud_demo.py`


### Bugfix Debug-Dump ZIP optimization_history (2026-07-21)

- [x] **Debug-Dump ZIP: `optimization_history.jsonl` fehlt (NAS/Docker)** — dump used baked `earnie_env/runtime` while history lives on volume `/app/runtime`; fixed via `resolve_history_src()` fallback + `EARNIE_RUNTIME_PATH: runtime` in compose; verified live (alpha.8, local IP and reverse proxy)


### Bugfix Manual WM/Trockner phantom Chart-1 bars (2026-07-21)

- [x] **Manual WM/Trockner phantom Chart-1 bars** — `apply_known_generic_to_chart_rows` peeled assumed weekly `earnie_role: manual` schedules into named bars (`phantom_kw` when live baseload lacked that energy). Fix: peel only `known`; manuals via `appliance_schedules.json` only (`house_config/known_chart_display.py`). Dump: `chart_debug_review/debug_dump_20260720_171718`; verified live


### Bugfix oemag_monthly_feed_in_rates in tariffs.json (2026-07-21)

- [x] **`oemag_monthly_feed_in_rates` moved to `tariffs.json`** — shared OeMAG reference + `monthly_float_reference_cent_kwh` now live in `tariffs*.json` (not `backtesting_scenarios`); bootstrap migrates v1→v2 (copy/strip/stamp); verified live


### Bugfix SE monthly_float missing month (2026-07-21)

- [x] **SE `Kein Monatseintrag für 2025-02 im Export-Tarif`** — OeMAG curve was only Jul 2025–Jun 2026 while SE needed earlier months; extended `oemag_monthly_feed_in_rates` (≥12 months allowed), clearer range error; verified live


### Bugfix scenario editor Land filter reset on auto_persist (2026-07-21)

- [x] **Country filter in scenario editor must also filter export tariffs** — regression: `Land` reset to `Alle` after tariff auto-save because `file_changed` cleared scoped widgets; fix: refresh file stamp + baseline after own write, preserve Land/Typ filter keys on file reload (`page_scenario_editor.py`, `scenario_form_helpers.py`); test `test_sync_scenario_file_changed_preserves_land_filter`; verified live


### Bugfix scenario editor Land filter for export tariffs (2026-07-21)

- [x] **Country filter in scenario editor must also filter export tariffs** — shared `Land` already applied to both Bezug and Einspeise via `render_shared_land_filter` + `render_tariff_type_filter(..., land=shared_land)` (`ui/tariff_filter_helpers.py`, Szenarieneditor); verified live (later regression: Land reset on auto_persist — see chapter above)


### Bugfix cloud-demo ghost scenarios (2026-07-21)

- [x] **Greenfield/`EARNIE_CLOUD_DEMO=1`: ghost scenarios not in session** — SE child inherited host `earnie_env` path overrides and listed scenarios outside the per-session workspace; `_apply_cloud_session_env` clears path overrides and points the subprocess at the session root (`ui/backtesting_runner.py`); test `test_subprocess_env_passes_cloud_session_root`; verified live


### Bugfix SE sunrise_window TypeError (2026-07-20)

- [x] **SE `sunrise_window`: `TypeError` on `effective_sunrise_soc_min_index(None)`** — `_simulate_anchor_step` no longer re-applies `effective_*` on the already-effective index from `build_sunrise_window_matrix`; `effective_sunrise_soc_min_index` is idempotent for `None`. Unit: `TestEffectiveSunriseSocMinIndex`; verified live (full-year / Sep-2025 `sunrise_window` backtesting)


### Research Loxone Energiemonitor statistics (2026-07-20)

- [x] Check if Loxone's Energiemonitor provides statistics to import in Earnie
  - Energiemonitor logs statistics
  - [x] Check how data looks like — data is usable


### Bugfix Battery remove button missing (2026-07-20)

- [x] **Battery: no remove button in UI** — added `delete_battery` (scrubs scenario `battery_id`) + **Batterie entfernen** with same pending/fallback + suppress-autopersist-on-last-delete pattern as PV (`ui/house_config_io.py`, `ui/planning_battery_form.py`); verified live


### Bugfix PV remove still shows removed params (2026-07-20)

- [x] **After removing a PV-Anlage the editor still showed its parameters** — delete always selected `— neu —` (ghost draft / same slug); now pending falls back to a remaining PV, clears scoped keys + selected id + auto_persist fingerprint, and suppresses one auto_persist when deleting the last PV (`ui/planning_pv_form.py`); verified live


### Bugfix EV charge while unplugged config path (2026-07-20)

- [x] **EV charge while unplugged (config path)** — house-profile EV (`daily_target_source=config`) sent `Earnie_EAuto_Ziel_kW` > 0 with `eauto_plugged_in: false`; config path now sets `anticipated`/`plugged_in` like Loxone path (`optimizer/charging_context.py::_config_path_with_plugged_in`). Dump: `chart_debug_review/debug_dump_20260720_094034`; verified live


### Bugfix Hauskonfigurator second PV select jump (2026-07-20)

- [x] **After adding a second PV-Anlage the editor jumped back to the first** — pending select stored entity id; `align_label_select_session` preferred stale `selected_id` over that id; fix: prefer current value when it is already a known entity id (`ui/label_select.py`); verified greenfield


### Version 2.2.0 — Merge streamlitcloud → main (2026-07-20)

- [x] Merge `streamlitcloud` into `main` (PR #6) — Community Cloud / offline SE, sidebar, Banner, Alpha/productive compose


### Docker compose Alpha / Productive + Streamlit ports (2026-07-20)

- [x] Split host compose into `*_productive.yml` (`earnie-productive`, :8501) and `*-alpha.yml` (`earnie-alpha`, :8511, `earnie_env_alpha/`)
- [x] Align ports scheme B: local Docker :8521, local venv :8531, greenfield venv :8532 (`docs/referenz/streamlit-ports.md`, `dev.yml`, `.vscode/launch.json`)
- [x] Docs/README/proxmox bootstrap updated; session-abschluss Alpha compose sync rule
- [x] `.gitignore` for `earnie_env_alpha` config/runtime


### Bugfix config import page jump to SE (2026-07-20)

- [x] **After „Importieren und neu laden“ (and other cases) app jumped to SE** — live verification: current page preserved after import (no auto-switch to Szenario-Explorer)


### Bugfix SE Live vs Referenz Jahres Verbrauch (2026-07-20)

- [x] **Live ≈½ Referenz after 1 month** (`chart_debug_review/earnie_config_20260719_081454`) — thermal MILP applied full HDD targets to each calendar day in midnight-spanning 07:00 windows → Infeasible with `max_on_quarterhours=16` → Automatik fallback (only last ~4 h EV+Haus); fix: prorate thermal day targets + operational ON-slot cap (`optimizer/thermal_flex_context.py`); mini-scenario `thermal_pulse_tight`; verified live (Referenz ≈ Live ≈1092 kWh)


### Bugfix SE EV Jahres Verbrauch vs Historisch (2026-07-20)

- [x] **consumption mismatch in SE with `chart_debug_review/earnie_config_20260719_081454`** — non-CSV `planning_ev_daily_targets` used uncapped SOC `ev_daily_kwh` (~44 kWh/d) while Historisch/synthetic used power-capped hourly (~13 kWh/d at `nominal_power_kw=1`); fix: slot-modeled window kWh (same as CSV EV / thermal); verified live (Historisch ≈ Referenz)


### Bugfix SE monthly_float OeMAG rates missing (2026-07-20)

- [x] **Error during SE with `chart_debug_review/earnie_config_20260719_050759`** — `get_backtesting_feed_in_settings` raised because `oemag_monthly_feed_in_rates` / `monthly_float_reference_cent_kwh` missing while live export was `monthly_float`; rates + reference cent added to pack (and `earnie_env`) `backtesting_scenarios.json` — verified live


### Bugfix SE Verbrauchsdaten warning wording (2026-07-20)

- [x] **Warning still said „Backtesting“** — empty cons_data warning in `ui/backtesting_cons_data.py` now: „… bevor du Szenario-Explorer startest.“


### Bugfix shared Land tariff filter (2026-07-19)

- [x] **"Bezug Land" / "Einspeise Land" must not differ** — single shared **Land** filter for Bezug + Einspeise in Szenarieneditor and Live-Konfiguration; separate Typ filters kept; `render_shared_land_filter` + `render_tariff_type_filter` in `ui/tariff_filter_helpers.py`; docs `docs/konfiguration/ueberblick.md`; tests `lands_union` — verified live


### Bugfix Bezeichnung dropdown / unique defaults (2026-07-19)

- [x] **Bezeichnung not updated in entity/select dropdowns after change** — Streamlit `format_func` kept stale labels when option IDs stayed the same; options are now Bezeichnung strings (`ui/label_select.py`) for Hausprofil, PV, Batterie, Szenario, entity pickers, Tarife, Live-Szenario; auto-persist triggers `st.rerun()`; Verbraucher expander titles use live widget state — verified live
- [x] **Unique Bezeichnung defaults** — `allocate_unique_label` for new Hausprofil / PV / Batterie / Szenario / extra Verbraucher (`Mein Haushalt 2`, …) — verified live


### Version 2.2.0 — Sanitize private NAS hostname (2026-07-19)

- [x] Replace `DS-KO-DO-2` with dummy `YOUR-NAS` in `.env.example`, `.vscode/launch.json`, `share/config/remote_backtesting.example.json`, `scripts/_diag_swimspa_nas.py`, plan note; example SSH host/user/path also dummy placeholders


### Version 2.2.0 — Banner der Wahrheit A + light B (2026-07-19)

- [x] Attribution banner in UI (`ui/truth_banner.py`): Earnie, non-commercial note, official repo, version; sidebar + main; also on Loxone setup path
- [x] Best-effort unofficial origin labeling (`EARNIE_BUILD_ORIGIN` / git remote); calm when origin unknown (Docker/SCC)
- [x] LICENSE §4.3 keep banner; handbook note; tests `tests/test_truth_banner.py`
- [x] Layer C deferred to `2.+1` (signed builds / registry) — not implemented


### Version 2.+1 — Offline demo seed for Community Cloud (2026-07-18)

- [x] `EARNIE_OFFLINE=1`: bootstrap fills empty live-scenario entity IDs from catalogs (`runtime_store/offline_demo_seed.py`); never overwrites non-empty refs
- [x] Config load defers runtime params when offline and live refs incomplete (UI can open for house/scenario setup)
- [x] Docs: `EARNIE_OFFLINE` in `docs/einrichtung/betrieb.md`; tests `tests/test_offline_demo_seed.py`


### Version 2.+1 — Save / Load configurations (2026-07-18)

- [x] Move `./config` and `./runtime` into `./earnie_env` (analog greenfield); code/settings/env vars updated; Compose mounts Host-`earnie_env` → `/app/config` + `/app/runtime`
- [x] Auto-Save after valid changes in Hauskonfigurator / Szenarieneditor
- [x] Sidebar **Konfiguration speichern / laden** — ZIP of `config.json`, sidecars (`backtesting_scenarios`, `components`, `deviation_rules`, `house_profiles`, `tariffs`), `uploads/`; `earnie_data_model` tag + compatibility check (converters later); `.env` excluded
- [x] Update docs — `docs/konfiguration/speichern-laden.md`, German user-doc path sync (`earnie_env`), handbook/UI notes


### Bugfix min_on_quarterhours SwimSpa / Wärmepumpe (2026-07-18)

- [x] **min_on_quarterhours not visible for SwimSpa / missing for Wärmepumpe** — Hauskonfigurator field for `thermal_rc` + `thermal_annual`; normalize/serialize for WP; default `4` in `house_profiles.json`; verified live


### Bugfix CSV-Pfad (Verbraucher) UI sync (2026-07-18)

- [x] **CSV-Pfad (Verbraucher) not updated after upload/removal** — Streamlit dual key (`path_key` vs text_input widget); pending sync + uploader nonce; `use_profile_csv` checkbox hidden when path empty; same pattern for Gesamt Verbrauch/PV; verified live


### Bugfix checkbox visibility (2026-07-18)

- [x] **Checkbox „Aus Gesamt-CSV abziehen / echtes Profil nutzen“ hardly visible** — `labeled_checkbox` used collapsed label in a column split (tiny square only); now native visible checkbox; grey theme-compatible highlight via `inject_checkbox_highlight_css` for all checkboxes; verified live


### Bugfix SE mixed CSV Jahres Verbrauch gap (2026-07-18)

- [x] **Historical total vs scenarios with mixed CSV/non-CSV consumers** — `planning_thermal_daily_targets` summed full calendar days for cross-midnight 24h windows (WP ~2× vs cons_data); CSV `thermal_rc` still added `swimspa_filter` flex (meter already includes filter); fix: slot-aligned window kWh + filter only for MILP thermal_rc; tests; verified live


### Bugfix SwimSpa Verbrauchszähler CSV upload (2026-07-18)

- [x] **SwimSpa Verbrauchszähler CSV upload** — failed with „Profil-CSV nicht gefunden: config/uploads/example_efh_swimspa.csv“ for `Miniserver-Gen2_VerbrauchszählerSwim-Spa_Leistung_…`; verified live
- [x] **Consumption CSV import rejected despite correct format** — same class of Verbraucher-CSV upload failure; import works; verified live


### Organizational: remove silent-migration-test (2026-07-18)

- [x] **Remove `silent-migration-test/`** — deleted local stack folder; launch configs / setup+deploy scripts / docs already gone (2.2 cleanup); dropped `.gitignore` entry and `LEGACY_TEST_SYMBOLS` for `setup_silent_migration` / `deploy_silent_migration`


### Bugfix remove scenarios (2026-07-18)

- [x] **No way to remove scenarios** — Szenarieneditor: `delete_scenario` + button **Szenario entfernen** (Live protected); tests in `test_planning_editors.py`; docs `docs/konfiguration/speichern-laden.md`; verified live


### Bugfix SE simulation window 8760 h (2026-07-18)

- [x] **SE `last_12_months` ~8800 h / ~370 Fenster** — root cause: Monday week snap + calendar `DateOffset(months=12)` inclusive span; fix: exactly 365 inclusive days (8760 h), no Monday pullback; UI time-range help + tests updated; verified live

### Bugfix config ZIP import UI / chart_color_index (2026-07-18)

- [x] Config pack import left stale Hauskonfigurator/live session state when the imported profile had more consumers; Live Chart 1 crashed on discovered columns (e.g. `fernsehen`) missing `chart_color_index`. Clear editor/live session on import; allocate palette indices for discovered flex columns.

### Bugfix SE profile_spec Jahres Verbrauch vs Historisch (2026-07-18)

- [x] **Investigate Gesamtkosten Jahres Verbrauch gap Historisch vs others** — root cause: `profile_spec` omitted CSV `thermal_rc` / used schedule targets for CSV EV·WP, and excluded `earnie_role: manual` from overlay; fix: CSV before climate, CSV thermal_rc → overlay, CSV EV/WP window targets, manuals as fixed overlay like known (recommendation UI unchanged); docs + tests; verified live (~11600 vs Historisch ~11700)
- [x] **Same gap with no `use_profile_csv`** — non-CSV `thermal_rc` stayed MILP-flex but got no window target (flat override → 0); fix: `planning_thermal_rc_daily_targets` + bridge-only filter `daily_target_kwh` fallback; docs + tests; verified live

### Bugfix Hauskonfigurator CSV / SE Kosten-Legende (2026-07-18)

- [x] **Single CSV upload (Verbrauch / Verbraucher)** — Hauskonfigurator: `accept_multiple_files=False` via `single_csv_upload`; stable overwrite path under `config/uploads/`; hide Streamlit „Add files“ (+) via CSS (`inject_single_file_uploader_css`); verified live
- [x] **SE monthly cost chart legend below** — `scenario_monthly_cost_chart`: Plotly legend `y < 0` (below chart), increased bottom margin; verified live


### Bugfix Scenario selector order (2026-07-18)

- [x] **Scenario selector order (stable Live + A–Z)** — Szenarieneditor: `— neu —` → Live (`live_scenario_id`) → remaining by label (case-insensitive); same display order for SE „Konfigurierte Szenarien“ and Live-Umgebung picker via `ordered_user_scenario_ids`; JSON file order unchanged; historical/reference chart order untouched; tests in `test_scenario_form_helpers.py`; verified live


### Bugfix SE Jahres Verbrauch Historisch vs rest (2026-07-18)

- [x] **SE Gesamtkosten `Jahres Verbrauch` differs for Historisch** — intentional: Historisch = `cons_data` Ist-Summe; refs/optimized = profile_spec / MILP window sums; UI caption under Gesamtkosten; docs in Benutzer-Handbuch, `docs/ui/betriebsmodi.md`, `docs/ui/charts.md`, `docs/spec/scenario-explorer-consumption.md`


### Bugfix SE / Hauskonfigurator labels (2026-07-18)

- [x] **SE Gesamtkosten Δ vs Referenz Live** — delta always vs Live-Referenz row (`_live_reference_total_eur`); columns `Jahres Verbrauch [kWh]`, `Jahres Kosten [€]` (with `€`), `Δ vs Referenz [€]`
- [x] **SE Verbrauchsvergleich (Debug)** — column 2 → `Ohne PV und Speicher [kWh]` (table title kept as Verbrauchsvergleich)
- [x] **Hauskonfigurator tab PV-Anlagen** — tab label `"PV-Anlage"` → `"PV-Anlagen"`
- [x] **Verbraucher 1 expander** — first consumer stays collapsed on load when it already has a saved `id`
- [x] **Stündlicher Verlauf Ist-Verbrauch** — actual consumption series `"Ist (CSV)"` → `"Ist-Verbrauch"` (Monatsverbrauch validation bar aligned)


### Import historical Data (2026-07-18)

- [x] **Energiemonitor / PV CSV import** — Hauskonfigurator separate CSVs or Energiemonitor multi-column; SOC out of scope; per-scenario `use_imported_pv`; dotted PV overlay on charts
- [x] **Test export script** — `scripts/export_historical_test_csvs.py` builds PV-Ertrag + Energiemonitor CSVs from Live `cons_data_hourly.csv` for import round-trip tests


### Historical CSV profiles (2026-07-17)

- [x] **Reactivate linking historical data to consumers as .csv-file** — column structure for overall consumption; UI upload + subtract-from-total checkbox (else synthetic profile); shared normalizer (unit/sign, 1h resample, ≥12 months); same pipeline per consumer type; Verbrauchsprofil all-vs-CSV-instrumented toggle; Scenario Explorer honors synthetic vs real
- [x] **Digital CSV × nominal power** — on import inspection, confirm then multiply 0/1 signals by `nominal_power_kw`


### Chart 1 export tariff line (2026-07-17)

- [x] **Add export tariff into Chart 1 of Monitor** — dashed orange `Einspeisepreis` HV steps on right axis `y2` (Cent/kWh, same scale as import `Preis`); column `Einspeisevergütung (Cent/kWh)`; helpers parameterized in `ui/chart_trace_segments.py`; `add_export_price_on_soc_axis_trace` in `ui/chart_soc.py`; docs `docs/ui/charts.md`; tests in `test_chart_ui_bugs.py`


### Streamlit control of main.py + single container (2026-07-17)

- [x] **Make main.py controllable from Streamlit** — lifecycle Start/Stop/Restart on **Echtzeit-Umgebung → Optimierer-Dienst**; `runtime_store/main_daemon.py` + `probe_instance` / `main.pid` sidecar (Windows-safe); `EARNIE_AUTO_START_MAIN` in `scripts.run_streamlit`; Docker collapsed to one service `earnie` (all compose files + Dockerfile CMD); docs updated


### Bugfix EV FertigUm ignored on config path (2026-07-17)

- [x] **EV FertigUm ignored on config path** — house-profile EV (`daily_target_source=config`) kept `ready_by_hour` deadline and ignored `Earnie_EAuto_FertigUm`; later FertigUm still forced early charge (`must_start` for old deadline). Fix: `resolve_charging_context` uses `resolve_charging_deadline` (FertigUm wins, `use_time_window=False`); tests `TestConfigPathFertigUm`. Dump: `chart_debug_review/chart_debug_20260716_065036`. Live verified: changing FertigUm later while EV needs charge updates `charging_contexts.ev.deadline`; no early force-charge for the old deadline.


### Bugfix Greenfield Loxone SoC 404 (2026-07-17)

- [x] **Greenfield live abort: `Battery_SOC` 404** — after Live-Konfiguration, worker called real Miniserver with placeholder `loxone_blocks` from `config.minimal.json` (`Battery_SOC` → HTTP 404, „Kein Zugriff auf Loxone SoC“); aligned `greenfield/config/config.json` `loxone_blocks` to Earnie/Miniserver names (e.g. `B004-Battery_SOC`); verified local greenfield silent run


### Version 2.2 — Quality epic / post-migration cleanup (2026-07-17)

- [x] **Coverage + legacy/obsolete audit tooling** — `vulture` / `pytest-deadfixtures` in `pyproject.toml` `[dev]`; refined `LEGACY_TEST_SYMBOLS`; per-package coverage aggregation in `scripts/test_health_report.py`; baseline ~79.5% overall (`optimizer`/`data`/`house_config`/`simulation`/`settings`/`runtime_store`); workflow in `.cursor/rules/test-health.mdc`
- [x] **Remove V1→2.0 migration toolchain** — deleted `migrate_runtime_entities`, `migrate_flex_consumers`, `migrate_components_sidecar`, silent-migration setup/deploy, `patch_swimspa_filter_config`, `resolve_legacy_runtime_settings`, related tests/docs/launch configs/`migrated/`; kept live `legacy_id` bridges + dump/history readers
- [x] **Hard-reject soft pre-1.26 / root fallbacks** — root `eauto_milp` / `appliances[]` fail on load (`settings/legacy_config_gates.py`); MILP only from `charging_schedule.milp`; removed `get_swimspa_settings` / `get_eauto_milp_params` / `PATH_*` aliases; schema + fixtures updated
- [x] **Legacy test / fixture audit** — removed dead `fixture_prices_df`; protected `test_loxone_integration.py`; health report skips missing test files; mock-heavy unit tests kept (manual triage)
- [x] **KPI refactor (bounded)** — split `_load_static_params`; removed unused `spa_cfg`; gates extracted; full `config.py` file split deferred → follow-up below
- [x] **Split `config.py` further** — extracted `settings/config_loaders.py` + `settings/live_scenario.py` (plus flex/appliance load helpers); `config.py` ~492 code LOC (was ~872; hard limit 600); public `import config` facade unchanged
- [x] **Widen `mutmut.ini`** — added `settings/legacy_config_gates.py` + reject/unit tests; `scripts/mutmut_pytest_runner.py` normalizes pytest exit codes; pin `mutmut>=2.4,<3` (ini format); run via Linux/Docker (not a release gate)
- [x] **Rewrite mock-heavy main() orchestration tests** — shared `tests/main_run_harness.py` (`patch_main_run` / `sample_planning_window`) aligned to current `main.py` seams (`prepare_optimization_matrix`, flex live power, thermal/savings); slimmed `tests/test_main_charging_trigger.py` + `tests/test_main_loxone_writes.py` (7 contracts preserved)
- [x] **German user handbook** — `docs/user-manual/Benutzer-Handbuch-Earnie.md` improved (post-install user perspective)


### Bugfix EV charge while not connected (2026-07-17)

- [x] **EV charge planned while not connected** — Earnie scheduled/sent Smart charge setpoints although the car was unplugged (`eauto_plugged_in: false` but `Earnie_EAuto_Ziel_kW` > 0). Dump: `chart_debug_review/debug_dump_20260717_105429` (config-path charging context `active` without `plugged_in`/`anticipated`). Live verified fixed.


### Community pre-release 2.1.0-alpha.2 (2026-07-17)

- [x] **Bump + Synology debug image** — `version.py` → `2.1.0-alpha.2`; chunk-load recovery for hostname Monitor failures; tagged pre-release (no `:latest`)


### Bugfix Monitor mobile chunk load (2026-07-17)

- [x] **Hostname Monitor `Failed to fetch dynamically imported module`** — phone kept stale Streamlit `/static/js` chunk hashes after upgrade (LAN IP OK; obsolete hashes returned `index.html`). Fix: one-shot reload in `ui/chunk_load_recovery.py`; temporary debug probe removed after live verification



### Synology UI Streamlit bind (2026-07-17)

- [x] **Synology compose UI listen address** — `optimizer-ui` now passes `--server.port 8501` and `--server.address 0.0.0.0` so Streamlit is reachable on the published host port (`docker/compose/synology.yml`)


### Community pre-release path + 2.1.0-alpha.1 (2026-07-17)

- [x] **Pre-release SemVer on `main`** — `version.py` may hold `X.Y.Z-alpha.N` / `-rc.N`; rules/skill (`versioning.mdc`, session-abschluss) guide A/B/C/D publish choices
- [x] **CI / tags** — `release.yml` detects `-` → `--prerelease` (no `--latest`); `build_container.default_tags` omits `:latest` for pre-releases; docs in `DEVELOPER.md` / `docs/einrichtung/container.md`
- [x] **First community build** — `version.py` → `2.1.0-alpha.1` (multi-PV, compact editors, SE order/disclaimer, tariff Land/Typ filters, debug dump schema v3, Hauskonfigurator PV-switch fix)


### Bugfix Debug-Dump download + dialog close (2026-07-17)

- [x] **„ZIP erstellen und herunterladen“ saved but did not download / left dialog open** — `st.components.v1.html` / `st.download_button` inside `@st.dialog` could not both download and dismiss the modal; dialog now saves + `st.rerun()` like „ZIP erstellen“, then auto-download on the main page via `st.html(..., unsafe_allow_javascript=True)` (`ui/chart_debug_capture.py`); verified in Monitor UI


### Debug dump schema v3 — single type (2026-07-17)

- [x] **Unified dump type `debug` (schema v3)** — dropped Chart/Prod split; one ZIP `debug_dump_YYYYMMDD_HHMMSS.zip` with full `optimization_history.jsonl`, optional `manifest.chart` when Live bundle present, `manifest.meta` (title/symptom/case_id); writer/normalize/validate in `runtime_store/debug_dump_archive.py`; legacy v1 chart and v2 chart/prod still readable
- [x] **UI dialog** — Cockpit „Debug-Dump speichern“ → dialog with optional Titel/Symptom; „ZIP erstellen“ or „ZIP erstellen und herunterladen“ (save + browser download in one step); no Dump-Typ selector (`ui/chart_debug_capture.py`)
- [x] **Replay / fixture promotion** — `scripts/replay_debug_dump.py` for `debug` (+ legacy chart/prod); `scripts/archive_prod_dump.py` reads `manifest.meta` (fallback `prod`)
- [x] **Docs / tests** — [`docs/einrichtung/betrieb.md`](../docs/einrichtung/betrieb.md), [`tests/fixtures/prod_dumps/README.md`](../tests/fixtures/prod_dumps/README.md); `tests/test_debug_dump_archive.py` / `test_chart_debug_capture.py`


### Bugfix Hauskonfigurator PV switch tab jump (2026-07-17)

- [x] **PV switch jumped to Hausprofil** — switching PV in Hauskonfigurator reset `st.tabs` to Hausprofil; replaced with session-keyed `st.segmented_control` + conditional section render in `ui/pages/page_house_config.py`; verified in UI


### Tariff filters Land + type (2026-07-16)

- [x] **Tariff filter Land + Typ** — `ui/tariff_filter_helpers.py`; Bezugs-/Einspeisetarif pickers in Szenarieneditor + Live-Konfiguration; cascading Typ after Land; current selection kept if outside filters; tests in `test_tariff_filter_helpers.py`; note in `docs/konfiguration/ueberblick.md`
- [x] **Region filter (`einzugsbereich`)** — closed without implementation (not in `tariffs.json` catalog; Land + Typ sufficient for now)


### SE progress and result order (2026-07-16)

- [x] Order of all SE results (tables, charts)
  - 1. Historisch - ohne Optimierung
  - 2. Live - Ohne Optimierung
  - 3.- Other PV-settings - Ohne Optimierung
  - x.- Repeat order from 2., 3. ... - Optimiert
  - Canonical `ordered_backtesting_result_ids` / reorder before `save_backtesting_log`; Live-first in `_annual_cost_row_order`
  - Progress-bar order during run: closed in **2.3.d** (2026-07-22)


### SE results disclaimer (2026-07-16)

- [x] Add a hint text to SE that there is no guarantee for the results — `st.info` on Szenario-Explorer (`ui/pages/page_backtesting.py`); wording aligned with Benutzer-Handbuch


### Compact editors (2026-07-16)

- [x] **Make editors more compact** — label|field side by side via `ui/form_layout.py` (`labeled_*` + `label_visibility="collapsed"`); rolled through SE, House Config (PV/Batterie/Hausprofil + nested consumers), Live entity pickers (`scenario_form_helpers`)
  - Follow-ups in same pass: hide entity-ID captions/select suffixes; hide number-input ± steppers (CSS); unique Bezeichnung on save (`house_config/label_uniqueness.py`)


### Multi-PV scenarios (2026-07-16)

- [x] **Enable Scenarios with multiple PVs** — `pv_system_ids[]` in scenario settings; resolve → `_planning_pv_systems` + summed `pv_kwp`
  - [x] Similar to consumers in Hauskonfigurator — SE/Live multiselect; HK PV tab **Entfernen**
  - [x] Multiple PVs counted in production — `ModeledClimateContext` multi-surface sum; live `pv_forecast` N× forecast.solar, sum for MILP
  - [x] Weekly SE charts: per-PV traces; other charts: sum only (`pv_by_system` / `pv_kw_by_system_for_slots`)
  - [x] Loxone yielded energy remains plant sum (no per-PV markers) — unchanged, matches model


### Standort-Override removed (2026-07-16)

- [x] **Standort-Override can be removed** — Scenario Editor no longer offers lat/lon override; `resolve_scenario_settings` always takes geo/timezone from `house_profile_id`; form save/normalize strips leftover scenario `latitude`/`longitude`/`timezone_name`; schema + example/fixture cleanup; tests in `test_scenario_form_helpers.py` / `test_house_config.py`


### Version 2.0.0 — GitHub Release + tag automation (2026-07-16)

- [x] **Real 2.0.0 release** — `version.py` `2.0.0`; annotated tag `v2.0.0`; GitHub Release notes; multi-arch GHCR (`earnie-energy` / legacy `ernie-energy`)
- [x] **Tag-triggered CI** — `.github/workflows/release.yml` (version gate, tariff gate, buildx push, `gh release create`); notes in `.github/release-notes/v2.0.0.md`
- [x] **Docs / session skill** — release runbook in `DEVELOPER.md`, pointer in `docs/einrichtung/container.md`, session-abschluss Phase 2 → push tag (local `--push` fallback)
- [x] Post-release cleanup (dead code / obsolete tests / migration leftovers) remains open under [Backlog.md](Backlog.md) § Version 2.+1 — Quality epic


### Bugfix Monatlicher Kostenvergleich bar order (2026-07-16)

- [x] **Monatlicher Kostenvergleich bar order** — bars follow Gesamtkosten order (historisch → scenario refs e.g. Referenz (Live) → optimized) via `ordered_monthly_chart_labels` + `scenario_order` on `scenario_monthly_cost_chart`; tests in `test_backtesting_charts.py` / `test_backtesting_results_helpers.py`; verified on SE page after reload


### Bugfix Earnie Monitor consumer color palette (2026-07-16)

- [x] **Consumer colors in Charts (Earnie Monitor)** — verified still the same as defined: fixed 8-color `CONSUMER_PALETTE` / `chart_color_index` via `consumer_chart_color()` in `ui/chart_colors.py` (Chart 1 + Sankey); unchanged from Consumer colors P1 (2026-07-07)


### Proxmox LXC deployment (2026-07-16)

- [x] **Proxmox LXC + Docker Compose** — `docker/compose/proxmox.yml`, bootstrap/lxc example under `docker/proxmox/`; user doc [`docs/einrichtung/proxmox-lxc.md`](../docs/einrichtung/proxmox-lxc.md); cross-links in `docs/README.md`, `docs/einrichtung/container.md`, `DEVELOPER.md`, `README.md`, `docker/README.md`, streamlit-ports


### Feed-in: scenario fixed monthly rates removed (2026-07-16)

- [x] **Drop `fixed_monthly_feed_in_rates` from backtesting scenarios** — rates come from export tariff `monthly_table` / `monthly_float` only; schema + example cleaned; `Config.get_backtesting_feed_in_settings` / `get_backtesting_fixed_monthly_feed_in_rates` path removed; SUNNY `monthly_rates` updated in `config/tariffs.json`; docs `docs/konfiguration/preise.md`


### Version 2.0 — README snapshots (2026-07-16)

- [x] Pimp README.md with snapshots


### Minor changes in Version 1.99 (2026-07-16)

- [x] Rearrange Verbrauchsvergleich (Debug) table
  - Add a column (Verbrauch ohne PV und Speicher)
  - Change name of column "Baseline Spec kWh" to "Reference (Live) - ohne Optimierung [kWh]"
  - Change name of column "delta kWh (Opt-Baseline)" to "delta kWh (Ref. ohne Optimierung)"
  - Remove rows for "Historisch (ohne Optimierung, ohne PV/Batterie)" and "Referenz (Live) — ohne Optimierung"
  - Write consumption of scenario "Historisch ..." in all cells of column "Verbrauch ohne PV und Speicher"
  - Write consumption of scenario "Reference (Live) - ohne Optimierung [kWh]" in all cells of column with this name
- [x] Modify Gesamtkosten table
  - Fill all cells of column "Jahres-kWh" with appropriate values


### Bugfix SE baseline progress + parallel workers (2026-07-16)

- [x] **SE baseline/reference progress bar** — reference simulations report hourly progress (`phase: reference`) via per-worker JSON snapshots; Streamlit shows per-task bars including historical reference (`scripts/run_backtesting.py` `_run_reference_worker`, `ui/backtesting.py`)
- [x] **Run-time progress feedback** — active tasks show `current/total h` (and `Referenz` label for baseline phase) during parallel runs
  - ETA (“time left until finished”): closed in **2.3.d** (2026-07-22)
- [x] **Worker count matches all parallel tasks** — `count_backtesting_parallel_tasks` = main reference + per-scenario extra references + optimized scenarios; `auto_backtesting_workers` uses `min(task_count, cpu_count − 1)`; references run in the same `ProcessPoolExecutor` as scenarios (`ui/backtesting_runner.py`, `_run_parallel_backtesting`); test `test_count_backtesting_parallel_tasks_includes_reference`


### Bugfix Detaillierte Simulationsansicht CBC severity (2026-07-16)

- [x] **Detaillierte Simulationsansicht marks feasible CBC/MILP windows yellow instead of red** — backtesting critical cases now carry the window plausibility result (`window_consumption_ok`, `window_consumption_diff_kwh`); `ui/backtesting_deviation_calendar.py` classifies `strict_fallback` / `milp_no_optimal` / `strict_slow` as yellow when the 24h result stayed within tolerance, otherwise red; deviation detail keeps showing the actual 24h Δ kWh for CBC cases
- [x] **Runtime verification** — March 2025 silent-migration-test rerun (`written_at 2026-07-16T10:37:17`) shows 31/31 plausibility OK; former red windows `2025-03-01T12:00:00` and `2025-03-15T12:00:00` remain CBC/MILP events but classify yellow because the 24h result is feasible (`Δ ≈ +0.01 kWh`)


### Debug dump phase 2 — unified archive + replay (2026-07-16)

- [x] **Unified debug dump (schema v2)** — one ZIP layout with `dump_type: chart | prod`; shared `inputs/` via `runtime_store/debug_dump_inputs.py`; writer `runtime_store/debug_dump_archive.py`; chart payload under `manifest.chart`, prod metadata under `manifest.prod`
- [x] **UI trigger for both types** — Cockpit „Debug-Dump speichern“ with Chart/Prod selector (optional title/symptom for prod); same enable gate `ui.chart_debug_capture_enabled` / env / local_settings
- [x] **Required/optional files per profile** — chart: `optimization_history_window.jsonl` (±2 h); prod: full `optimization_history.jsonl`; optional runtime state files documented in ZIP README + [`docs/einrichtung/betrieb.md`](../docs/einrichtung/betrieb.md)
- [x] **Partial replay** — `python -m scripts.replay_debug_dump` (chart Chart-1 rebuild smoke; prod history/state smoke; schema v1 chart ZIPs still accepted)
- [x] **Fixture promotion** — `scripts/archive_prod_dump.py` ingests unified `debug_dump_prod_*.zip` (prefers dump `inputs/`); [`tests/fixtures/prod_dumps/README.md`](../tests/fixtures/prod_dumps/README.md) updated
- [x] **Tests** — `tests/test_debug_dump_archive.py`; chart capture tests updated for schema v2 filenames


### Bugfix Chart 1 EV as Einspeisung (PV) (2026-07-16)

- [x] **Chart 1 — EV charging shown as Einspeisung (PV)** — history→chart flex lookup used canonical id `ev` while live log keys (`flex_measured_ids`, `flex_live_kw`, `consumption_snapshot.flex_kw`) still use `legacy_id` `eauto`, so `Smart (kW)` was `None` and residual grid import was labeled surplus PV export; `_consumer_kw_from_entry` now bridges runtime/canonical ids via `runtime_consumer_id` / `flex_kw_lookup` (`runtime_store/history_timeline.py`); test `tests/test_history_timeline.py::test_entry_to_chart_row_bridges_legacy_measured_flex_id`; dump `chart_debug_review/chart_debug_20260716_065036`
- [x] **Live verification** — Chart 1 night window shows Smart bars instead of Einspeisung (PV)


### Bugfix Hauskonfigurator / Szenarieneditor stale widget state (2026-07-16)

- [x] **Hauskonfigurator / Szenarieneditor stale widget state after page navigation** — Bezeichnung empty and entity fields showed defaults (`— keine —` / implausible values) after switching pages; disk data unchanged. Fix: `_widget_state_missing` reseed in `_sync_pv_session`, `_sync_scenario_session`, `_sync_battery_session` (Hausprofil already had `_profile_widget_state_missing`). Tests: `test_sync_pv_session_reseeds_when_widget_keys_missing`, `test_sync_scenario_session_reseeds_when_widget_keys_missing`, `test_sync_battery_session_reseeds_when_widget_keys_missing`
- [x] **Live verification** — PV, Batterie, and Szenarieneditor fields show saved values after page navigation (prod)


### Bugfix Loxone marker Earnie_WP_Freigabe not sent (2026-07-15)

- [x] **Loxone marker `Earnie_WP_Freigabe` not sent anymore** — heat-pump enable output restored via house-profile `wp_heating` / `loxone_outputs.enable_name` (migration/bridge keeps marker wired); live verification confirms marker is sent again


### Bugfix Chart 1 generic `known` consumers (2026-07-15)

- [x] **Chart 1 — generic `known` consumers as separate Down-traces** — still Grundlast for optimization (`house_profile_baseload_overlay`); display peels schedule kW into named columns (`house_config/known_chart_display.py`, `_finalize_chart_rows_for_display`, Chart 1 stack in `ui/chart_consumer_stack.py`); tests `tests/test_known_chart_display.py`
- [x] **Live verification** — Monitor Chart 1 shows Kochen/Fernsehen (and peers) as separate bars, not only inside Grundlast


### Bugfix Chart 2 SA₁→SA₂ empty curves (2026-07-15)

- [x] **Chart 2 SA₁→SA₂ not populated** — persisted live snapshot omitted hourly cost/consumption series and often `planning_matrix`; `savings_info_from_snapshot` now recomputes hourlies from simulation/matched rows and falls back matrix from `simulation_rows` (`runtime_store/live_display_loader.py`); regression via `chart_debug_review/chart_debug_20260715_191843` in `tests/test_live_display_loader.py`

_Effort: 32.657.443 Cursor tokens (2.669.630 excl. cache · CSV open window after 1.99 through 2026-07-15 21:09)_


### Version 2.0 — README expansion (2026-07-15)

- [x] Expand README with motivation / benefits / features — sensible order of use; less technical background than install/configuration hints
- [x] Extract developer content to [DEVELOPER.md](../DEVELOPER.md); product-first [README.md](../README.md)
- [x] Monitor screenshot in `docs/assets/monitor-sunset2sunset.png`; cross-link update in [docs/README.md](../docs/README.md)


### New features — Generic `earnie_role` (known / flex / manual) (2026-07-15)

Plan [`.cursor/plans/earnie_consumer_roles_1dc94070.plan.md`](../.cursor/plans/earnie_consumer_roles_1dc94070.plan.md) — consolidates „Manuelles Gerät“, „known by Earnie“, and „controlled by Earnie (flex)“; supersedes the `start_shift_h=0` proxy ([Backlog-Erledigt.md](Backlog-Erledigt.md) § New features — fixed generic Grundlast in live optimization).

- [x] **`earnie_role` on generic consumers** — `known` (default, Grundlast overlay) / `flex` (MILP shift window) / `manual` (Betrieb → Manuelle Geräte); schema + `house_config/profiles_store.py` normalization with legacy inference
- [x] **Backend routing** — `house_config/earnie_role.py`, `split_planning_generic_consumers` by role; manual appliances excluded from MILP; `recommendation_horizon_h` on runtime appliance spec
- [x] **Hauskonfigurator UI** — „Earnie-Berücksichtigung“ selectbox; Verschiebung (flex) vs Empfehlungshorizont (manual); `known` hides shift and persists `start_shift_h: 0`
- [x] **Manuelle Geräte** — per-device recommendation horizon from Hausprofil (`ui/pages/page_devices.py`)
- [x] **Migration & examples** — `scripts/migrate_flex_consumers.py` sets `earnie_role: manual`; `config/house_profiles.example.json` updated
- [x] **Tests & docs** — `tests/test_earnie_role.py` and related updates; [`docs/konfiguration/flexible-verbraucher.md`](../docs/konfiguration/flexible-verbraucher.md), [`docs/spec/scenario-explorer-consumption.md`](../docs/spec/scenario-explorer-consumption.md)

_Live verification: pending (Hauskonfigurator save on existing profiles to persist explicit roles)._


### New features — Consumer roles follow-up (loxone_inputs + Manuelle Geräte) (2026-07-15)

Plan [`.cursor/plans/consumer_roles_follow-up_08c02579.plan.md`](../.cursor/plans/consumer_roles_follow-up_08c02579.plan.md) — follow-up to Generic `earnie_role`.

- [x] **Unified Loxone Leistungsquelle** — `loxone_inputs.power_name` for `earnie_role: known` and `manual`; legacy `appliance_recommendation.loxone_power_name` migrates on normalize; schema + `profiles_store` + `settings/appliances.py`
- [x] **Hauskonfigurator** — shared Leistungsquelle UI for `known` and `manual`; marker stored in `loxone_inputs`
- [x] **Manuelle Geräte read-only** — Nennleistung/Laufzeit from Hausprofil only; per-device Empfehlungshorizont; no save form on page
- [x] **Examples & migration** — `house_profiles.example.json`, `migrate_flex_consumers.py`
- [x] **Tests & docs** — `test_earnie_role.py`, `test_appliance_config.py`, `test_page_devices_display.py`; [`docs/konfiguration/flexible-verbraucher.md`](../docs/konfiguration/flexible-verbraucher.md), [`docs/dev/done/ui-menu-structure.md`](../docs/dev/done/ui-menu-structure.md)


### New features — PV tuning removal + Simulations-Details columns (2026-07-15)

- [x] **Remove adaptive PV tuning** — forecast vectors no longer scaled by `calculate_tuning_factor` (`data/pv_forecast.py`); optimization no longer aborts when PV counter delta unavailable (`main.py`); `pv_tuner.py` trimmed to counter delta only (Adaptation P2 replaces full path); UI already clean (`app.py`, UI S-2 P1)
- [x] **Simulations-Details column rename** — non-EV immediate-charge columns `{name} Aktiv`; EV keeps `{name} sofort_laden` (`optimizer/targets.py`, `ui/simulation_results.py`, `ui/chart_flow_balance.py`); tests updated


### Version 1.99 — Live cutover (P6b) (2026-07-15)

Plan [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md) — Phase **1.99** prod cutover. Runbook [`docs/einrichtung/nas-live-cutover-1.99.md`](docs/einrichtung/nas-live-cutover-1.99.md). Prerequisite: [Backlog-Erledigt.md](Backlog-Erledigt.md) § NAS migration plan — manual validation (2026-07-14).

- [x] **P6b — Non-silent NAS live cutover** — legacy `docker/earnie/` stopped; prod on migrated 2.0 stack with `loxone_silent_mode: false`; manual acceptance per runbook (SwimSpa, EV, Haus Wärme, Chart 1/Sankey, Loxone-Kommunikation writes)

Loxone debug page → [Backlog-Erledigt.md](Backlog-Erledigt.md) § Version 1.99 — Loxone debug UI (2026-07-14).

**Next:** propose `version.py` **`2.0.0`** (user approval) → [Backlog.md](Backlog.md) § Version 2.0.


### Version 2.0 — release gate context (2026-07-15)

Archived from [Backlog.md](Backlog.md).

**Goal:** Legacy data model gone — see plan end state and [`docs/spec/nas-consumer-migration-1.95-1.99.md`](../docs/spec/nas-consumer-migration-1.95-1.99.md).

**Prerequisite chain:** **1.93** ✓ → **1.95–1.97** ✓ → **1.99** P6b ✓ → propose `version.py` **`2.0.0`** (user approval).

Open → [Backlog.md](Backlog.md) § Version 2.0 (Expand README; post-release cleanup in **2.+1** chapters).


### NAS consumer migration — feature backlog index (2026-07-15)

Archived from [Backlog.md](Backlog.md) when migration **1.95–1.99** closed (P6b live cutover ✓).

Szenario-Explorer consumption model → [Backlog-Erledigt.md](Backlog-Erledigt.md) (2026-07-13). Spec: [`docs/spec/scenario-explorer-consumption.md`](../docs/spec/scenario-explorer-consumption.md).

Version **1.93** (unified scenario model) → [Backlog-Erledigt.md](Backlog-Erledigt.md) (2026-07-14). **1.99** live cutover (P6b) ✓ (2026-07-15).

Recommended order: **1.95–1.96** legacy flex / thermal migration (**1.96** ✓ · **1.97** ✓) · **1.99** P6b live cutover ✓ → propose `version.py` → **`2.0.0`** (user approval; **real** 2.0 — legacy data model gone).

Critical path **1.95–1.97** ✓ · **1.99** P6b ✓ → [Backlog-Erledigt.md](Backlog-Erledigt.md). Open bugs → [Backlog-Bugfixes.md](Backlog-Bugfixes.md).

**Implementation plan (1.95–1.99):** [`docs/spec/nas-consumer-migration-1.95-1.99.md`](../docs/spec/nas-consumer-migration-1.95-1.99.md) — prod consumer matrix, phased deliverables, acceptance, NAS cutover runbook.


### Version 1.95

_Completed → [Backlog-Erledigt.md](Backlog-Erledigt.md) § Version 1.95 — Thermals P1 (2026-07-14)._


### Version 1.98

_Completed → [Backlog-Erledigt.md](Backlog-Erledigt.md) § Version 1.96 — Consumers P1 (2026-07-14)._


### Execution of plan [`docs/spec/nas-consumer-migration-1.95-1.99.md`](../docs/spec/nas-consumer-migration-1.95-1.99.md)

Silent local abnahme stack → [Backlog-Erledigt.md](Backlog-Erledigt.md) (2026-07-14).

Manual validation (dynamic tariff, fixed tariff Δ€, SE `live`) → [Backlog-Erledigt.md](Backlog-Erledigt.md) § NAS migration plan — manual validation (2026-07-14).

Suggested next steps (SE progress, diag tooling, 1.96d code, cutover runbook) → [Backlog-Erledigt.md](Backlog-Erledigt.md) § NAS migration plan — suggested next steps (2026-07-14).

Silent-stack debug sessions (Hausconfig, Chart 1, `main.py` SwimSpa, config drift) → [Backlog-Erledigt.md](Backlog-Erledigt.md) § Silent-stack debug sessions (2026-07-14). Open regressions → [Backlog-Bugfixes.md](Backlog-Bugfixes.md).

**2026-07-15 session:** Generic `earnie_role` + consumer-roles follow-up → [Backlog-Erledigt.md](Backlog-Erledigt.md) § Generic `earnie_role` + Consumer roles follow-up. UI architecture (Cockpit from `main.py` snapshot, matched-baseline SoC BL Ziel fixes, forecast.solar 429) → [Backlog-Erledigt.md](Backlog-Erledigt.md) (2026-07-15 sections). PV tuning removal + Simulations-Details columns → [Backlog-Erledigt.md](Backlog-Erledigt.md) § PV tuning removal. Bugfix live verifications (S-2 navigation, Cockpit persistence, EV FertigUm, SoC BL Ziel segment) ✓ (2026-07-15).


### Bugfix SoC BL Ziel matched baseline (silent stack) (2026-07-15)

Plan [`.cursor/plans/soc_bl_ziel_debug_handoff_20260715.md`](../.cursor/plans/soc_bl_ziel_debug_handoff_20260715.md) — inflated SoC BL Ziel on earnie silent stack vs legacy reference.

- [x] **Flex CSV export / regen** — export grouped by display label broke column lookup (`SwimSpa Filter`); regen via `profile_column_id()` / `runtime_consumer_id`; INFO `Profil-Check` / `Flex-Profile im Planungshorizont` (`data/profile_manager.py`; tests `tests/test_profile_manager_flex_export.py`, `tests/test_profile_manager_flex_bridge.py`)
- [x] **ID bridge `ev` / `eauto`** — `expected_flex_kw` and live flex dicts normalized to canonical ids (`settings/flexible_consumers.py`; boundaries in `data/live_consumption.py`, `optimizer/charging_context.py`, `optimizer/charge_immediate.py`, `optimizer/__init__.py`, `data/consumer_targets.py`; tests `tests/test_flexible_consumers_bridge.py`, `tests/test_live_consumption.py`)
- [x] **Matched baseline horizon targets** — config appliances with `daily_target_kwh=0` use profile-sum targets in BL Ziel (`resolve_matched_baseline_horizon_targets` in `optimizer/targets.py`; test `tests/test_matched_baseline.py::test_matched_baseline_uses_profile_targets_for_config_appliances`)
- [x] **Cockpit reads main.py snapshot** — Chart 1 SoC BL Ziel from `matched_baseline_rows` in `live_optimization_debug.json` (no default UI Live-MILP); see [Backlog-Erledigt.md](Backlog-Erledigt.md) § Bugfix UI: Cockpit from main.py persistence (2026-07-15)
- [x] **Silent-stack verification** — Wed noon BL Ziel model-consistent; Thu 13:00 **42%** with appliance profile (matched baseline); Simulation-Details table correctly shows optimized MILP (separate path) — caption follow-up → [Backlog.md](Backlog.md) New features

_NAS earnie deploy + prod CSV regen: pending._


### Bugfix Earnie Monitor S-2 chart navigation (2026-07-15)

- [x] **SA₀→SA₁ → SA₁→SA₂ navigation showed stale charts** — snapshot display cache key omitted `cycle_offset` / `segment_index`; `_refresh_snapshot_bundle` skipped rebuild after **→**. Fix: include `s2:{cycle_offset}:{segment_index}` in `_snapshot_cache_key` (`ui/live_mode.py`); test `tests/test_live_mode_snapshot_cache.py`.
- [x] **Live verification** — **→** switches both charts to SA₁→SA₂; **←** returns to SA₀→SA₁.


### Bugfix forecast.solar 429 Retry-At (2026-07-15)

Plan [`.cursor/plans/forecast.solar_retry-at_72a2f487.plan.md`](../.cursor/plans/forecast.solar_retry-at_72a2f487.plan.md) — respect rate-limit retry timestamp; debug log in `main.py` (429 mitigation during debug runs).

- [x] **Parse Retry-At on HTTP 429** — `X-Ratelimit-Retry-At` header or JSON `message.ratelimit.retry-at`; skip HTTP until timestamp passed (`data/pv_forecast.py`)
- [x] **Fix `_LAST_API_CALL` only on 200** — failed/429 requests no longer block retries for 15 min
- [x] **`get_api_status()`** — exposes `retry_at`, `source`, `cache_available`, `using_synthetic_fallback`
- [x] **main.py debug log** — WARNING with next allowed API call when rate-limited or synthetic PV fallback active
- [x] **Tests** — `tests/test_pv_forecast.py` (429 header/body, retry blocking, 15-min cache, `_LAST_API_CALL` regression)

_Live verification: pending (trigger 429 during debug run, confirm log line `Nächster API-Aufruf erlaubt ab …`)._


### Bugfix SoC BL Ziel segment before Jetzt (Chart 1) (2026-07-15)

- [x] **Dotted baseline trace extended into quarter-hour before Jetzt** — matched-baseline SoC segment no longer drawn left of the Jetzt marker; anchor at log-SOC via `_anchor_baseline_soc_at_now` (`ui/chart_soc.py`); test `tests/test_charts_soc_tail.py::test_baseline_soc_has_no_points_before_now`.
- [x] **Live verification** — dotted SoC BL Ziel baseline stops at Jetzt marker (Chart 1).


### Bugfix EV FertigUm when fully charged (plugged in) (2026-07-15)

- [x] **`fetch_loxone_charging_context` ignores FertigUm when charge complete** — plugged-in + `actual_soc_name` at target → `_loxone_plugged_in_complete_context()` (`optimizer/charging_context.py`); unplug re-reads FertigUm via absent forecast; tests `tests/test_charging_context.py::TestPluggedInChargeComplete`; docs [`docs/referenz/loxone-signale.md`](../docs/referenz/loxone-signale.md).
- [x] **Live verification** — plugged-in full SOC ignores FertigUm; unplug restores absent-forecast path.


### Bugfix UI: Cockpit from main.py persistence (2026-07-15)

Plan [`.cursor/plans/ui_relies_on_main.py_a1f9f67e.plan.md`](../.cursor/plans/ui_relies_on_main.py_a1f9f67e.plan.md) — architecture revision: no default UI Live-MILP / forecast.solar (429 mitigation).

- [x] **main.py writes display snapshot** — after `calculate_optimization_savings`, hour-0 overlay via `overlay_main_run_on_rows`, persist `live_optimization_debug.json` with `source: main.py`, `planning_matrix`, `planning_window` (`main.py`, `runtime_store/live_optimization_debug.py`)
- [x] **UI reads persisted snapshot** — `runtime_store/live_display_loader.py`; `build_optimization_display_bundle_from_snapshot` in `ui/simulation_results.py`
- [x] **Cockpit (`ui/live_mode.py`)** — snapshot by default; `wait_main` shows last plan; `main_down` + fresh snapshot (≤ 1 h) with notice; stale/missing → opt-in **Einmalige Simulation starten** only
- [x] **Manuelle Geräte (`ui/pages/page_devices.py`)** — last-known `planning_matrix` from snapshot; no live matrix build
- [x] **Sync semantics** — `live_simulation_readiness`: `main_synced` / `wait_main` / `main_down`; removed auto-`fallback` UI MILP (`optimizer/schedule.py`, `PERSISTED_DISPLAY_MAX_AGE_SECONDS = 3600`)
- [x] **Help text** — `ui/main_py_sync.py`, `ui/countdown.py` (no “Fallback mit Altplan nach 30 s”)
- [x] **Tests** — `tests/test_schedule.py`, `tests/test_live_display_loader.py`, `tests/test_main_py_sync_ui.py`, `tests/test_main_loxone_writes.py` (debug snapshot on run)
- [x] **Docs** — [`docs/einrichtung/betrieb.md`](../docs/einrichtung/betrieb.md), [`docs/ui/betriebsmodi.md`](../docs/ui/betriebsmodi.md), [`docs/spec/ui-sunset2sunset.md`](../docs/spec/ui-sunset2sunset.md) v0.8.0, [`docs/dev/done/ui-menu-structure.md`](../docs/dev/done/ui-menu-structure.md) §6
- [x] **Live verification** — Cockpit + Manuelle Geräte after one `main.py` quarter-hour run on silent stack / NAS.


### Bugfix Hauskonfigurator Verschiebung 0.0 (2026-07-15)

- [x] **Verschiebung (± h) showed 12 h when `start_shift_h` was 0.0** — `_schedule_defaults` treated `0.0` as falsy via `or 12.0`; only default to 12 when key is missing (`None`). Fix in `ui/house_config_profile_form.py`; test `tests/test_planning_editors.py::test_schedule_defaults_preserves_zero_start_shift_h`.


### Bugfix EV MILP stripped on Hauskonfigurator save (2026-07-15)

- [x] **MILP settings lost when editing EV consumers** — `_render_ev_fields` rebuilds `charging_schedule` from UI widgets only; `_merge_passthrough_consumer_fields` preserved `charging_schedule.loxone` but not `milp` → save dropped `live_modus_a_min_remaining_kwh` / tie-break epsilons; downstream `planning_ev_to_milp` abort (`charging_schedule.milp fehlt` when `power_setpoint_name` set). Fix: passthrough merge copies `charging_schedule.milp` like `loxone` (`ui/house_config_profile_form.py`); test `tests/test_house_config.py::test_house_profile_save_preserves_loxone_bindings`; silent-migration-test verified.


### New features — fixed generic Grundlast in live optimization (2026-07-15)

Superseded by **Generic `earnie_role`** ([Backlog-Erledigt.md](Backlog-Erledigt.md) § New features — Generic `earnie_role` (2026-07-15)).

- [x] **Fixed-start generic → Grundlast (live)** — `type: generic` with `start_shift_h: 0` from `_house_profile` added to `expected_p_act` via `fixed_generic_hourly_overlay` even when root `flexible_consumers[]` is set; greenfield path unchanged (full `house_profile_baseload_overlay`); tests `tests/test_profile_manager_baseload_overlay.py`; user doc [`docs/konfiguration/flexible-verbraucher.md`](docs/konfiguration/flexible-verbraucher.md)


### Version 1.99 — File structure hygiene (2026-07-14)

- [x] **Docker bundle** — `docker/` with `Dockerfile`, `entrypoint.sh`, `compose/{dev,synology,loxberry,greenfield}.yml`, `build-container.ps1`, `docker/README.md`; build context stays repo root; `.dockerignore` remains at root
- [x] **Backlog directory** — `backlog/Backlog.md`, `Backlog-Bugfixes.md`, `Backlog-Erledigt.md`; Cursor rules/skills and doc cross-links updated
- [x] **Root Python cleanup** — keep `main.py`, `app.py`, `config.py`, `version.py`, `logger_config.py`; remove legacy wrappers `run_backtesting.py`, `GenerateConsData.py`; move dev dashboard to `ui/dev/app_test_data.py`


### Version 1.99 — Loxone debug UI (2026-07-14)

Plan [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md) — cutover validation tooling. Runbook [`docs/einrichtung/nas-live-cutover-1.99.md`](docs/einrichtung/nas-live-cutover-1.99.md).

- [x] **Loxone-Kommunikation debug page** — Streamlit page **Echtzeit-Umgebung → Loxone-Kommunikation**: live read table with timestamps (fragment refresh), last-run write trace (`loxone_writes` in `optimizer_run_state.json` when not silent; intended `loxone_sent` in silent mode); `integrations/loxone_comm_trace.py`, traced sends in `loxone_client.py` / `main.py` (`ui/loxone_debug.py`, `ui/pages/page_loxone_debug.py`, `ui/navigation.py`; tests `tests/test_loxone_debug.py`, `tests/test_main_loxone_writes.py`, `tests/test_loxone_client.py`, navigation tests)
- [x] **Sidebar Merker test → debug page** — removed **Loxone-Merker testen** from sidebar expander; button on debug page; sidebar hint to **Loxone-Kommunikation** (`ui/setup_progress.py`, `ui/loxone_debug.py`; test `tests/test_setup_progress.py`)
- [x] **User doc** — [`docs/ui/loxone-kommunikation.md`](docs/ui/loxone-kommunikation.md); TOC + cutover checklist cross-links


### Version 1.96 — Consumers P1 (2026-07-14)

Plan [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md) — Phase **1.96** (P1a–P1d) + **1.96d** silent-stack prod migration.

- [x] **P1a — Resolved flex registry** — `simulation.engine.resolved_flexible_consumers()`; `consumer_has_daily_target()` for `generic_flex_window`, `thermal_annual`, EV `charging_schedule` (`settings/flexible_consumers.py`)
- [x] **P1b — Backtesting Chart 1** — display bundle / `flex_consumers_from_snapshot` → `chart_flex_consumers_context`; bridged generics in down-stack (`ui/backtesting_display_bundle.py`, `ui/chart_consumer_stack.py`)
- [x] **P1c — Live cockpit + Sankey** — Chart 1 + Sankey use resolved flex when `house_profile_id` set; Sankey `flex_kw` via `runtime_consumer_id` / `legacy_id` (`ui/sankey.py`, `ui/charts.py`)
- [x] **P1d — Tests & docs** — `tests/test_chart_consumer_stack.py`; [`docs/spec/scenario-explorer-consumption.md`](docs/spec/scenario-explorer-consumption.md) UI discovery section
- [x] **Bugfix `config.reload` circular import** — lazy `hour_in_charging_window` import in `house_config/ev_profile.py` (Sankey/countdown fragments on `reload_runtime_config()`)
- [x] **EV bridge Loxone passthrough** — `planning_ev_to_milp` copies `loxone_inputs` / `loxone_outputs` / `charging_schedule.loxone` from house profile (`house_config/planning_flex_bridge.py`; tests `tests/test_planning_matrix_profile_spec.py`)
- [x] **1.96d prod migration (silent stack)** — `migrate_flex_consumers` on `silent-migration-test`; `appliances[]` retired; WM/Trockner/GS as profile `generic` consumers; manual Chart 1 / Sankey parity confirmed


### Silent-stack debug sessions (2026-07-14)

Local abnahme stack (`silent-migration-test`, Streamlit `:8512`, `main.py`). Plan [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md). Open follow-ups → [Backlog.md](Backlog.md) § **Version 2.0**; [Backlog-Bugfixes.md](Backlog-Bugfixes.md).

- [x] **Betrieb / Cockpit unlock after 2.0 migration** — empty root `flexible_consumers[]` wrongly triggered greenfield onboarding → Cockpit hidden while `main.py` ran; `needs_planning_onboarding` now treats house-profile consumers with Loxone wiring as live stack (`ui/setup_readiness.py`, `ui/setup_progress.py`; tests `tests/test_setup_readiness.py`, `tests/test_setup_progress.py`)
- [x] **Config drift false positives** — `config/config.example.json` still had pre-2.0 keys (`eauto_milp`, `appliances[]`, `system.loxone_silent_mode`) → 3 drift items vs migrated silent stack; examples aligned to 2.0 shape (`config.example.json`, `config.minimal.json`, `config/house_profiles.example.json`; tests `tests/test_config_drift.py`, `tests/test_greenfield_bootstrap.py`; docs [`docs/konfiguration/ueberblick.md`](docs/konfiguration/ueberblick.md))
- [x] **Hauskonfigurator Loxone bindings stripped on save** — form rebuild + `profiles_store` dropped `loxone_inputs` / `loxone_outputs` / `charging_schedule.loxone` / `thermal_control.loxone`; passthrough merge + EV normalize preserve bindings (`ui/house_config_profile_form.py`, `house_config/profiles_store.py`, `house_config/ev_profile.py`; test `test_house_profile_save_preserves_loxone_bindings`)
- [x] **Bugfix SwimSpa `main.py` — Ist-Temperatur** — bridged `thermal_rc` lacked Loxone thermal wiring at runtime; restored SwimSpa bindings in silent stack + copy profile Loxone fields through `planning_flex_bridge` (`silent-migration-test/config/house_profiles.json`, `house_config/planning_flex_bridge.py`, `house_config/profiles_store.py`)
- [x] **Bugfix `thermal_rc` nested save round-trip** — UI saves nested `thermal_rc.*` only; `_normalize_thermal_rc` read top-level → `water_volume_liters` 0 on save; normalize/serialize from `_thermal_rc_source` (`house_config/profiles_store.py`)
- [x] **Bugfix `thermal_rc` annual consumption 0 kWh** — no `thermal_rc` branch in `consumer_annual_kwh` / hourly profile builders → SwimSpa omitted from totals; RC model path + UI geo injection for preview (`house_config/thermal_rc_profile.py`, `house_config/baseload.py`, `data/consumption_profiles.py`, `data/modeled_climate.py`, `ui/house_config_profile_form.py`; tests `test_consumer_annual_kwh_thermal_rc_with_geo`, `test_silent_migration_profile_includes_swimspa_annual`, `test_inject_profile_geo_adds_thermal_rc_coordinates`)
- [x] **Bugfix Chart 1 PV-Ist flex discovery** — `PV-Ist (kW)` log column discovered as synthetic flex consumer `pv_ist` → `chart_color_index fehlt`; reserved column via `PV_IST_COLUMN` (`ui/chart_consumer_stack.py`; test `test_pv_ist_column_not_discovered_as_flex_consumer`)


### Version 1.95 — Thermals P1 (2026-07-14)

Plan [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md) — Phases **1.95a–c**. Core bridge (migrate_flex, SwimSpa 1.94, silent stack) → prior Erledigt entries.

- [x] **1.95a** — `legacy_id` bridge + EV MILP on house-profile consumer (`planning_flex_bridge`, `eauto_milp`, tests)
- [x] **1.95b** — `type: thermal_rc` schema/bridge, SwimSpa/filter bindings, variable heat paths (`optimizer/thermal_model.py`, `data/thermal_power.py`)
- [x] **1.95c** — `scripts/migrate_flex_consumers.py` + silent-stack integration
- [x] **Freezer reference model** — second `thermal_rc` fixture (`tests/fixtures/thermal_rc_reference.py`, Freezer CSVs, calibration warming phases, `tests/test_thermal_rc_freezer.py`)
- [x] **UI** — `thermal_rc` fields in Hauskonfigurator (`ui/house_config_profile_form.py`)
- [x] **Gate (documented):** Chart/Sankey parity → **Consumers P1 (1.96)** before prod cutover


### Research items (2026-07-14)

- [x] **Review Smart Energy app** for comparison
- [x] **Review other providers** with flexible prices


### Version 1.97 — Thermals P1a (2026-07-14)

Plan [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md) — Phase **1.97**.

- [x] **Haus Wärme MILP flex bridge** — `planning_thermal_to_milp`, `thermal_annual` daily targets, pulse constraints (`optimizer/thermal_flex_context.py`, `house_config/planning_flex_bridge.py`)
- [x] **Retire prod `waermepumpe`** from `flexible_consumers[]` — `wp_heating` + `legacy_id: waermepumpe` via `migrate_flex_consumers`
- [x] **Tests** — `tests/test_thermal_flex_bridge.py`, `tests/test_price_pipeline_p3.py`


### NAS migration plan — manual validation (2026-07-14)

Plan [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md) — execution block *Validation* (greenfield / Szenario-Explorer).

- [x] **Dynamic tariff** — heating shifts vs PWM reference (`haus` thermal, `optimizer_flex=false`; optional retest with `optimizer_flex=true`)
- [x] **Full-year SE `live`** — 2026-05-14 EV deadline / MILP Infeasible resolved (→ § Bugfix EV Modus B preset deadline); optional full SE re-run to confirm `failed_count: 0`
- [x] **Fixed tariff** — Δ€ ≈ 0 vs reference across backtesting scenarios (`fixed_25ct` / `fixed_37ct` in `greenfield/config/backtesting_scenarios.json`)


### Bugfix EV Modus B preset deadline (2026-07-14)

Full-year Szenario-Explorer (`live`, greenfield): sole MILP failure on **2026-05-14** — `Infeasible` at 06:00, **−5.84 kWh** EV gap (other flex on target).

- [x] **Root cause** — after MILP partial delivery (11 kWh at 18:00), Modus B preset charged only when `t=0` was the cheapest eligible hour; 5.84 kWh tail never delivered overnight → last-hour MILP infeasible
- [x] **Fix** — `ev_preset_power_now` also charges under deadline pressure (`must_start`) or when remaining eligible slots ≤ delivery slots needed (`optimizer/eauto_milp.py`)
- [x] **diag_single_window** — `--anchor` price load uses anchor calendar year (was hardcoded 2025 → false negatives for 2026 windows)
- [x] **Test + repro** — `test_preset_charges_when_deadline_slots_exhausted`; `scripts/repro_may14_ev.py` (chained SOC replay → `plausibility_ok=True`, EV 16.84 kWh)


### Dev — Windows Unicode console (2026-07-14)

- [x] **Agent skill** — `.cursor/skills/windows-unicode-console/SKILL.md` (`PYTHONIOENCODING` / `PYTHONUTF8` before shell Python on Windows)
- [x] **pytest** — `tests/conftest.py` reconfigures stdout/stderr to UTF-8 at import (→, subscripts, umlauts)


### NAS migration plan — suggested next steps (2026-07-14)

Plan [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md).

- [x] **SE per-worker progress** — `.backtesting_progress/` directory with one JSON per worker; Streamlit shows a bar per active scenario (`simulation/backtesting_progress.py`, `scripts/run_backtesting.py`, `ui/backtesting.py`)
- [x] **diag_single_window `--hour-offset`** — anchor window uses `BACKTESTING_YEAR` instead of hardcoded 2025
- [x] **1.96d appliances unify (code)** — `appliance_recommendation` on house-profile `generic` consumers; `get_appliances()` reads profile first; `migrate_flex_consumers` retires `appliances[]`; legacy schedule key remap (`settings/appliances.py`, `runtime_store/appliance_schedules.py`). Silent-stack prod migration → § Version 1.96 — Consumers P1
- [x] **1.99 P6b cutover runbook** — [`docs/einrichtung/nas-live-cutover-1.99.md`](docs/einrichtung/nas-live-cutover-1.99.md)


### 1.96 — migration validation minor changes (2026-07-14)

Plan [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md) — UX and tooling around silent stack and Szenario-Explorer.

- [x] **migrate_flex_consumers** — integrated in `setup_silent_migration_test`; `thermal_annual` ordered first; local silent stack migrated + `startup_checks` OK
- [x] **Chart 1 Haus Wärme** — `wp_heating` MILP display name via `planning_thermal_to_milp` → „Haus Wärme“
- [x] **Detaillierte Simulationsansicht** — charts/diagnose only after radio „Charts & Diagnose laden“ (`ui/backtesting_deviation_list.py`)
- [x] **Deviation calendar** — auto-open month with most deviation days (`month_with_most_deviation_days`)
- [x] **Verbrauchsdaten staleness** — Hauskonfigurator save invalidates meta; `house_profile_fingerprint` in `.meta.json` (`data/cons_data_store.py`, `ui/house_config_io.py`)
- [x] **Backtesting test month** — `suggest_test_month()` prefers March when data overlaps
- [x] **Parallel backtesting progress** — progress file + hourly updates from parallel workers (`scripts/run_backtesting.py`, `ui/backtesting.py`)


### Silent migration test — local abnahme (2026-07-14)

Backlog path **1.93 P6a** / plan **1.99** prerequisite — prod NAS already on **2.0** entity model (`live_scenario_id`, `components.json` sidecar). Docs: [`docs/einrichtung/silent-migration-test.md`](docs/einrichtung/silent-migration-test.md), [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md).

- [x] **`setup_silent_migration_test`** — NAS **2.0** direct sync (no P5 `runtime_settings`); split `batteries[]`/`pv_systems[]` → `components.json`; repo DACH tariff catalog when NAS has prod subset; graceful `.env` copy on permission denied
- [x] **VS Code** — silent-migration launch configs (`validate_tariffs`, `startup_checks`, `main.py`, Streamlit `:8512`); all `EARNIE_*` paths local under `silent-migration-test/`
- [x] **Local validation** — `validate_tariffs --check-catalog`, `startup_checks` (tariffs + 36× Loxone read), `main.py` optimization loop, Streamlit Chart 1 in silent mode
- [x] **Import fixes** — `data/cons_data_house_profile.py` (`import config`); `ui/chart_decorations.py` (`import pandas as pd`)
- [x] **Config drift** — silent-migration `config.json` aligned with `config.example.json` (`loxone_silent_mode`, SwimSpa `heating_active_name`, EV `actual_soc_name` + nominal voltage/phases)


### SwimSpa case B — indicator-based attribution (2026-07-14)

Backlog **1.94** — shared total meter + binary indicators (no separate Loxone heating-kW marker). Spec/docs: [swimspa-filter.md](docs/spec/swimspa-filter.md), [loxone-signale.md](docs/referenz/loxone-signale.md).

- [x] **Decision documented** — keep `Earnie_Swim-Spa-P_act` (heating + filter + jets/other); filter via `homie_bwa_spa_filter*`, heating via `homie_bwa_spa_heating`; jets unmodelled residual
- [x] **Live wiring** — `thermal_control.loxone.heating_active_name`, `fetch_thermal_readings`, thermal observability (`readings_kw.heating`), `verify_loxone_setup`; `patch_swimspa_filter_config` idempotent for heating indicator
- [x] **Historical calibration** — `data/thermal_power.py`; `tune_thermal_model` / backtest prefer `heating_active_csv` (+ optional `filter_active_csv`); threshold fallback when indicator CSVs absent
- [x] **Config/schema/docs** — `config.example.json`, `config.schema.json`, `flexible-verbraucher.md`
- [x] **Migration notes** — Thermals P1 + real 2.0 binding table in `Backlog.md`



## EV: urgent rule, prod dump, PWM
Related topics — prioritize and work through together.

- [x] **Urgent rule observability review** (by approx. **2026-07-12**, after prod acceptance)
  - Constraint removed → evaluate `urgent_rule_observability` in log + `optimization_history.jsonl` (`role`: expected `redundant`)
  - Acceptance: consistently `redundant` over several charge cycles → close review, simplify observability logging if applicable
- [x] **PWM for EV charging** — only for currents < A_min; otherwise minimum charge amount per h (count down meter, reset on each charge → at zero charge charge five minutes at minimum current)


### Version 1.93 — Unified Open-Meteo solar (2026-07-13)

PV (`pv_kw`) and Solar-Kollektor (Haus Wärme) share the **same Open-Meteo archive weather** on the **same calendar hours** — no static `heating_climate_default.json` fixture, no `2023-01-01 % 8760` slot mapping, no measured Loxone PV in backtesting/synthesis paths. Commit `575c610`.

**Decisions:**


| Topic | Decision |
| ----- | -------- |
| PV source (backtesting + synthetic `cons_data`) | **Open-Meteo only** |
| Open-Meteo API failure | **Fail hard** — no fixture/synthetic fallback on this path |
| Hauskonfigurator annual preview | **Last full archive calendar year** at profile lat/lon |


- [x] **Step 1 — Bundle + `heating_need` hourly path** — `OpenMeteoClimateBundle`, `irradiance_wm2_to_thermal_kwh`, `daily_electric_kwh(..., hourly_collector_wm2=…)`; tests with mocked HTTP
- [x] **Step 2 — cons_data synthesis + backtesting overlay** — [`data/modeled_climate.py`](data/modeled_climate.py), [`data/cons_data_house_profile.py`](data/cons_data_house_profile.py), [`scripts/generate_cons_data.py`](scripts/generate_cons_data.py), slot-aligned thermal in [`house_config/planning_flex_bridge.py`](house_config/planning_flex_bridge.py) / [`data/consumption_profiles.py`](data/consumption_profiles.py); Open-Meteo PV in [`simulation/engine.py`](simulation/engine.py) when `scenario_params` set
- [x] **Step 3 — Hauskonfigurator preview + cache** — `thermal_annual_kwh_from_archive()`; JSON cache under `data/cache/open_meteo/`; WP metric caption with reference year
- [x] **Tests** — [`tests/test_open_meteo_solar_archive.py`](tests/test_open_meteo_solar_archive.py), [`tests/test_modeled_climate.py`](tests/test_modeled_climate.py), [`tests/test_heating_need_solar.py`](tests/test_heating_need_solar.py), [`tests/test_cons_data_calendar_alignment.py`](tests/test_cons_data_calendar_alignment.py); offline mock [`tests/fixtures/open_meteo_mock.py`](tests/fixtures/open_meteo_mock.py)

**Smoke verification (manual):** Phase A complete → *Smoketest Phase A — Open-Meteo solar* below.

**Deferred to other chapters:** **Thermals P1a** (MILP pulse timing, **1.98**) · **P6b** (live `main.py` Loxone `cons_data` append cutover, **1.94**)


### Version 1.93 — Szenario-Explorer consumption model (2026-07-13)

Baseline vs optimized load separation for SE / greenfield backtesting. Spec: [`docs/spec/scenario-explorer-consumption.md`](docs/spec/scenario-explorer-consumption.md).

- [x] **Step 1 — Targets & matrix input** — `consumer_daily_targets_kwh` from `planning_flex_daily_targets`; baseload from house-profile overlay; `consumption_source=profile_spec` default for greenfield/SE
- [x] **Step 2 — Plausibility & reference** — plausibility vs profile-spec totals; `compute_historical_reference_costs` with scenario tariffs; `build_per_scenario_reference_costs` + `reference_by_scenario`
- [x] **Step 3 — UI** — baseline (dashed) vs optimized per scenario; consumption debug Δ kWh (`ui/backtesting_scenario_consumption.py`)
- [x] **Step 4 — Greenfield flex registration** — `standard`, `waschmaschine`, `ev` MILP-flex documented; scenarios `live` / `s3-no-battery` in greenfield matrix
- [x] **Window-aware targets** — partial-day generic/EV flex at 07:00 anchors (`generic_flex_target_kwh_for_window`, `planning_ev_daily_targets`); tests [`tests/test_generic_flex_window_targets.py`](tests/test_generic_flex_window_targets.py)
- [x] **Tests** — [`tests/test_planning_matrix_profile_spec.py`](tests/test_planning_matrix_profile_spec.py), [`tests/test_consumption_display_integration.py`](tests/test_consumption_display_integration.py), backtesting smoke extensions

**Enables:** meaningful battery/PV scenario comparison; remaining plausibility gaps → smoke-test Phase B in [`Backlog-Erledigt.md`](Backlog-Erledigt.md).


### Version 1.93 — smoke-test follow-ups (2026-07-14)

Greenfield smoke **2026-07-12**; backtesting iteration **2026-07-13**; chapter closed **2026-07-14**. Related smoketest phases A–C → sections above in this archive.

- [x] **Szenario-Explorer without PV** — optimization/backtesting path complete when `pv_system_id` unset (battery-only MILP/simulation gaps closed on top of P1 optional-PV baseline)
- [x] **EV nominal voltage for power calculation** — configurable per EV consumer (`charging_schedule.nominal_power_voltage_v` / `nominal_power_phases`, house profile + `flexible_consumers`); shared helper [`settings/ev_power.py`](settings/ev_power.py) for live (`integrations/loxone_client.py`) and planning (`house_config/planning_flex_bridge.py`); default 230 V / 1 phase when unset; schemas, Hauskonfigurator UI, [`docs/referenz/loxone-signale.md`](docs/referenz/loxone-signale.md); tests [`tests/test_ev_power.py`](tests/test_ev_power.py)

Components (`components.json` sidecar) → *Version 1.93 Components* below.


### Version 1.93 — Unified scenario model (closure) (2026-07-14)

Former backlog **2.0 P1–P7**; chapter closed **2026-07-14**. Implementation phases → sections below in this archive (P1–P5, P6a, Components, Open-Meteo solar, SE consumption model, smoke-test A–C, follow-ups). Branding → *Earnie rename* below.

- [x] **P1–P5, P6a, Components, Open-Meteo solar, SE consumption model** — done
- [x] **Smoke-test Phase A–C + follow-ups** — done (2026-07-12 … 2026-07-14)
- [x] **Deferred:** **P6b live cutover** → [Backlog-Erledigt.md](Backlog-Erledigt.md) § Version 1.99 — Live cutover (P6b) (2026-07-15); legacy flex/thermal migration → **1.95–1.97**

**Decisions (2026-07-11, retained for reference):**


| Topic | Decision |
| ----- | -------- |
| `EARNIE_UI_MODES` key | Hard rename `backtesting` **→** `scenario_explorer` — no alias (P2) |
| Scenario id `runtime_settings` | **Removed in 1.93 P2** — live baseline via `live_scenario_id` (default `live`) (P2) |
| Battery without PV | **Allowed** — battery required for MILP; PV optional (P1) |
| **7g-a** before P6 | **Skip for 1.93** — parallel NAS after local silent acceptance; 7g-a stays in Packaging backlog |
| **P6 NAS deploy** | **Done** — P6a silent trial; **P6b** live cutover ✓ (2026-07-15) |
| `sunrise_window` rename (P4) | Hard rename `sunset_window` **→** `sunrise_window` — no alias |
| **Real 2.0 release gate** | `version.py` **→** `2.0.0` after **1.99** P6b ✓ + legacy data model removed (user approval) |
| `components.json` sidecar | **Hard cutover in 1.93** — `batteries[]` / `pv_systems[]` only in sidecar; startup error if keys remain in `config.json` |


### Smoketest backtesting — greenfield runs (2026-07-13)

- [x] **Jan 2025 `fixed_24h` run** — `live` + `s3-no-battery`, 31 windows; `reference_by_scenario` populated; optimization < reference € on `awattar_at` import
- [x] **cons_data + Open-Meteo cache** — greenfield synthesis regenerated; cache entry under `data/cache/open_meteo/`


### Smoketest Phase B — fixed tariffs & plausibility (2026-07-13)

Greenfield matrix: `greenfield/config/backtesting_scenarios.json` — `live`, `s2-kein-pv`, `s3-no-battery`, `s1-kein-pv-keine-battery`.

- [x] **Fixed-tariff scenario matrix in greenfield** — `live` (full), `s2-kein-pv` (no PV), `s3-no-battery` (no battery), `s1-kein-pv-keine-battery` (no PV, no battery) with `fixed_25ct` / `fixed_37ct` in `greenfield/config/backtesting_scenarios.json`; run `--horizon-mode fixed_24h`
  - Created all scenarios in local greenfield env
  - Made test backtesting calculation (January 2025)
  - Finding: `s2-kein-pv` / `s1-kein-pv-keine-battery` show higher costs than baseline that is with PV --> Take PV out of baseline
  - Notice: "Zeitverschiebung (Energie ≈ Spec)" - what does that mean? --> More precise wording
- [x] **Bulk classify** — per scenario: plausibility ok/total, Δ€ vs matched reference, deviation kinds; tool: `scripts/analyze_plausibility_failures.py`
- [x] **Structural flex under-delivery (`s2-kein-pv` Jan 2 & 7)** — Phase 1 done: rolling `min_on` continuation in MILP. Spec: [`docs/dev/done/backtesting-plausibility-s2-kein-pv-jan-2-7.md`](docs/dev/done/backtesting-plausibility-s2-kein-pv-jan-2-7.md#phase-1-implementation-2026-07-13)


### Smoketest Phase B — Variable tariff scenario (2026-07-13)

- [x] **Check scenario results**
  - [x] one deviation - to be checked (5.10.25)
    - Fenster: 2025-10-04 07:00 – 2025-10-05 07:00 · Szenario: S2-kein-PV · Art: CBC strict (langsam) · Δ kWh (Soll/Ist): —
    - Fenster: 2025-10-04 07:00 – 2025-10-05 07:00 · Szenario: Live · Art: CBC strict (langsam) · Δ kWh (Soll/Ist): —
    - Issues arise from very flat and low price line
  - [x] Chart 1 — house-profile flex consumers not shown separately (**investigated 2026-07-13**)
    - **Calculation OK** — snapshot/matrix columns (`Standard (kW)`, `Waschmaschine (kW)`, `EV (kW)`) and plausibility targets correct; `meta._flexible_consumers` populated
    - **UI gap** — Chart 1 uses `get_flexible_consumers(optimizer_only=True)`; bridged generics fail `consumer_has_daily_target()` → only EV rendered; hidden flex misattributed in flow-balance down-stack (thermal `haus` correctly in Grundlast)
    - **Fix** — **1.96 Consumers P1** (with **Thermals P1** migration); not automatic after storage consolidation alone


### Smoketest Phase C — polish follow-ups (2026-07-13)

- [x] **Live scenario default** — `Detaillierte Simulationsansicht` wählt `live_scenario_id`, wenn am Tag keine Abweichung markiert ist (`ui/backtesting_deviation_list.py`)
- [x] **Hauskonfigurator Speichern** — sticky Speichern-Leiste + doppeltes Speichern vor Vorschau-Charts (Hausprofil); sticky auf PV/Batterien (`ui/house_config_sticky_save.py`)
- [x] **Loxone Ist-SOC E-Auto** — optionales `charging_schedule.loxone.actual_soc_name` (z. B. `Ernie-SOC-Ist-EAuto`); Vergleich mit berechnetem Session-SOC; bei Ziel-SOC keine weitere Ladung (`optimizer/ev_soc_tracking.py`, `optimizer/delivery_tracking.py`)


### Smoketest Phase C — SE layout polish (2026-07-13)

- [x] Remove Referenz-Jahresverbrauch (nicht optimiert) charts from SE
- [x] Remove Optimierter Verbrauch vs. Profil-Baseline charts from SE
- [x] Move Monatlicher Kostenvergleich directly below Gesamtkosten
- [x] Move Abweichungsliste to the bottom of SE
- [x] Add Referenz and Ohne Optimierung to Gesamtkosten table


### Smoketest Phase A — Open-Meteo solar (2026-07-13)

Manual acceptance on greenfield venv (:8511); implementation in *Unified Open-Meteo solar* above.

- [x] **Regenerate `cons_data` + Open-Meteo cache** — `data/cache/open_meteo/` populated (greenfield 2026-07-13)
- [x] **Backtesting smoke** — Jan 2025 `fixed_24h`, scenarios `live` + `s3-no-battery` (31 windows; optimization cheaper than reference on `awattar_at`)
- [x] **July 2024 calendar alignment** — spot-check `cons_data_hourly.csv`: `pv_kw` / `haus_kw` peaks on 2024-07 hours (no modulo drift)
- [x] **Solar-Kollektor** — `solar_thermal_area_m2` > 0 lowers summer midday `haus_kw` vs 0 m²
- [x] **Hauskonfigurator WP preview** — caption shows Open-Meteo archive year; collector area reduces estimated kWh/a
- [x] **Fail-hard (offline)** — internet disabled before `cons_data` generation: `requests.ConnectionError` on `archive-api.open-meteo.com` (DNS `getaddrinfo failed`); no fallback to `heating_climate_default.json`; surfaces at config reload via `thermal_annual_kwh_from_archive()` during profile normalization


### cons_data PV via Open-Meteo Solar Archive (2026-07-13, superseded)

Superseded for SE/backtesting/synthesis by *Unified Open-Meteo solar* above. Legacy `build_open_meteo_pv_lookup` fallback curve remains only on old cons_data paths.

- [x] **Backtesting cons_data PV** — initial `data/open_meteo_solar_archive.py` + `scripts/generate_cons_data.py` integration
- [x] **Tests** — `tests/test_open_meteo_solar_archive.py` (extended in unified chapter)


### Smoketest bugfix — Hausprofil Bezeichnung (2026-07-12)

- [x] **Bezeichnung** empty when switching Szenario-Explorer → Hauskonfigurator — greenfield smoke 2026-07-12
- [x] **Fix:** `_sync_profile_session` re-seeds scoped widget state when keys are dropped after page navigation (`_profile_widget_state_missing` in `ui/house_config_profile_form.py`)
- [x] **Tests:** `tests/test_planning_editors.py` (`test_sync_profile_session_reseeds_when_widget_keys_missing`, `test_seed_profile_widget_state_uses_existing_annual_kwh`)


### Smoketest UX — Szenarieneditor (2026-07-12)

- [x] **Move "Hausprofil" to top of Szenarieneditor** — field order in `ui/pages/page_scenario_editor.py` (Hausprofil before Batterie/PV/Tarife)
- [x] **Enable saving new scenarios** — session-scoped widget keys + live-scenario template for `— neu —`; duplicate-ID guard; select switches to saved scenario (`ui/scenario_form_helpers.py`, `ui/pages/page_scenario_editor.py`)
- [x] **Tests:** `tests/test_scenario_form_helpers.py`, `tests/test_planning_editors.py` (`test_upsert_scenario_appends_new_entry`)


### Smoketest UX — Szenario-Explorer copy (2026-07-12)

- [x] **Rename user-visible "Backtesting" → "Szenario-Explorer"** — `ui/pages/page_backtesting.py`, `ui/backtesting.py` (page title, buttons, status, warnings, log captions); file/script/module names unchanged


### Smoketest UX — remove Auflösung testen (2026-07-12)

- [x] **Remove button "Auflösung testen"** — removed from `ui/pages/page_scenario_editor.py`; `ui/scenario_runtime_form.py` already absent (unified editor); entity resolution unchanged on save and in `tests/test_house_config.py`, `tests/test_config_runtime_resolution.py`


### OFFLINE gated by Live-Konfiguration (2026-07-12)

- [x] **Greenfield/planning stays offline until Live-Konfiguration complete** — `is_effective_offline()` in `runtime_store/env_vars.py` (explicit `EARNIE_OFFLINE` / auto gate via `is_live_configuration_complete()`); `dotenv_io` uses effective offline for setup blocking / config credential requirement, explicit offline only for sidebar deferral bypass; worker `main.py` waits on `is_planning_offline_gated()`; `config.py` default credential requirement aligned
- [x] **Acceptance:** greenfield without `OFFLINE=1` env behaves offline until entity refs saved on Live-Konfiguration; after save, Loxone paths active (deferred sidebar, worker proceeds when planning ready)
- [x] **Tests:** `tests/test_env_vars.py`, `tests/test_dotenv_io.py`, `tests/test_setup_readiness.py`, `tests/test_greenfield_bootstrap.py`


### Bugfix Greenfield Loxone credential sidebar (2026-07-12)

- [x] **Greenfield: Loxone credential sidebar disappears before credentials saved** — greenfield smoke 2026-07-11; re-opened and **verified 2026-07-12**
- [x] **Root cause:** `scripts/run_backtesting.py` set `ENERGY_OPTIMIZER_OFFLINE=1` at **import** time when Szenario-Explorer loaded; next rerun `loxone_setup_deferred()` returned false → sidebar expander hidden
- [x] **Fix:** `OFFLINE` only when backtesting runs as `__main__` + explicit flag in `ui/backtesting_runner._subprocess_env()`; `render_deferred_loxone_sidebar()` from `app.py` (decoupled from setup notices); hardened `loxone_setup_deferred()` / explicit empty `flexible_consumers` check in `ui/setup_readiness.py`
- [x] **Tests:** `tests/test_setup_progress.py`, `tests/test_setup_readiness.py`, `tests/test_backtesting_ui_helpers.py` (`test_run_backtesting_module_import_does_not_force_offline`)
- [x] **Acceptance:** greenfield — navigate Szenario-Explorer ↔ Szenarieneditor ↔ Hauskonfigurator before `.env` save; expander **"Loxone-Zugang (Live / Silent-Modus)"** persists until credentials saved



### Version 1.93 Components — `components.json` sidecar (2026-07-12)

Completes entity-catalog split from 1.26.0 / 1.93 P2: `batteries[]` and `pv_systems[]` moved from `config.json` into `config/components.json` (sidecar next to `tariffs.json`, `house_profiles.json`). Scenarios keep referencing `battery_id` / `pv_system_id` only. Hard cutover — startup error if legacy keys remain in `config.json`; no alias/fallback.

- [x] **Components P1 — Sidecar infrastructure** — `config/components.schema.json`, `components.minimal.json`, `components.example.json`; `[house_config/components_store.py](house_config/components_store.py)`; `[runtime_store/persist_paths.py](runtime_store/persist_paths.py)` `resolve_components_json_path()`; `[runtime_store/bootstrap.py](runtime_store/bootstrap.py)` `_bootstrap_components_json()`
- [x] **Components P2 — Config load & scenario resolution** — `config.py` `components_path`, `get_batteries()` / `get_pv_systems()` from sidecar; `_reject_legacy_config_blocks`; `[house_config/scenario_resolution.py](house_config/scenario_resolution.py)`; `[ui/setup_readiness.py](ui/setup_readiness.py)`; `batteries` / `pv_systems` removed from `config.schema.json`, `config.minimal.json`, `config.example.json`
- [x] **Components P3 — UI & editors** — `[ui/house_config_io.py](ui/house_config_io.py)` `upsert_battery` / `upsert_pv_system`; help strings in `[ui/config_forms.py](ui/config_forms.py)`
- [x] **Components P4 — Migration & fixtures** — `[scripts/migrate_components_sidecar.py](scripts/migrate_components_sidecar.py)`; `[house_config/migrate_runtime_entities.py](house_config/migrate_runtime_entities.py)` writes components sidecar; `silent-migration-test/config/` + fixtures updated
- [x] **Components P5 — Tests, debug dumps, docs** — `tests/test_components_store.py`, `tests/test_persist_paths_sidecars.py`, planning/setup/runtime resolution tests; `[runtime_store/debug_dump_inputs.py](runtime_store/debug_dump_inputs.py)`; user docs `[docs/konfiguration/ueberblick.md](docs/konfiguration/ueberblick.md)`, `[docs/konfiguration/batterie-pv.md](docs/konfiguration/batterie-pv.md)`, `[docs/einrichtung/greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)`
- [x] **Acceptance** — greenfield bootstrap creates empty `components.json`; Hauskonfigurator persists battery/PV there; live + Szenario-Explorer resolve entity IDs; battery-only (no PV) setup passes readiness; startup fails clearly if legacy keys remain in `config.json`



### Bugfix EV urgent constraint removed (2026-07-12)

- [x] **EV: urgent constraint removed** — MILP: separate `urgent >= target` constraint removed; deadline still enforced via `eligible` slots until completion time
- [x] Observability retained (`role` post-hoc); ISO deadline parsing added
- [x] Regression: `eauto_urgent_deferred_cheap_hours_2026-06-28`, new `eauto_urgent_deferred_cheap_hours_2026-07-09`; `xfail` removed
- [x] **Prod acceptance** — charge cycle with deadline 07:45 uses cheap night hours (02–04); `urgent_rule_observability.eauto.role == redundant`
- [x] **Szenario-Explorer: cons_data ID mismatch after regenerate** (greenfield smoke 2026-07-11)
  - Fix: `expected_cons_data_consumer_ids()` uses raw `config.json` IDs or full house-profile set (not `_planning_flex_consumers` merge); meta `consumer_ids` aligned on save



### Version 1.93 P6a — Parallel NAS stack (silent trial) (2026-07-12)

- [x] **Parallel stack** — validated `silent-migration-test/config/` + `runtime/` deployed to new NAS folder (`docker/earnie-2.0/`); legacy `docker/earnie/` unchanged (rollback)
- [x] **Migration review** — `[silent-migration-test/config/MIGRATION_REVIEW.md](silent-migration-test/config/MIGRATION_REVIEW.md)` and entity IDs checked; migration via `[house_config/migrate_runtime_entities.py](house_config/migrate_runtime_entities.py)` (1.26.0 P5 + 1.93 P6a)
- [x] **Compose** — distinct container names, UI port ≠ 8501 (8503), image pinned to 2.0.x
- [x] **Silent mode** — `runtime/local_settings.json`: `{"loxone_silent_mode": true}`; legacy prod worker kept running (no dual writes)
- [x] **Acceptance** — `validate_tariffs --check-catalog`, `startup_checks`, worker/UI on new stack; guide: [Silent Migration Test Stack](docs/einrichtung/silent-migration-test.md)
- [x] **Scope split** — non-silent live cutover deferred to **1.94 P6b** (not a real 2.0 release gate)



### Version 1.93 P5 — Tariffs & deploy gate (2026-07-11)

- [x] **Tariff plausibility** — `[house_config/tariff_plausibility.py](house_config/tariff_plausibility.py)`: Normalisierung, JSON-Schema, Szenario-Referenzen; CLI `[scripts/validate_tariffs.py](scripts/validate_tariffs.py)` (`earnie-validate-tariffs`)
- [x] **Runtime gates** — Szenario-Explorer UI + `[scripts/run_backtesting.py](scripts/run_backtesting.py)`; Worker-Start `[scripts/startup_checks.py](scripts/startup_checks.py)` (`EARNIE_STRICT_TARIFF_VALIDATE` in Prod-Compose)
- [x] **Deploy gate** — `[scripts/build_container.py](scripts/build_container.py)` prüft vor `--push`; `[tools/convert_dach_tariffs.py](tools/convert_dach_tariffs.py)` `--check` für DACH-Vollständigkeit
- [x] **Catalog** — DACH-Quellen abgedeckt; `fixed_37ct` (Greenfield-Beispiel) in `[config/tariffs.json](config/tariffs.json)`
- [x] **Deploy docs** — `[docs/einrichtung/container.md](docs/einrichtung/container.md)`, `[docker-compose-synology.yml](docker-compose-synology.yml)`, `[docker-compose-loxberry.yml](docker-compose-loxberry.yml)`: `tariffs.json` Sidecar + Strict-Validate
- [x] **Tests** — `tests/test_tariff_plausibility.py`, `tests/test_validate_tariffs_cli.py`, Erweiterung `tests/test_startup_checks.py`



### Version 1.93 P4 — `sunrise_window` rename (2026-07-11)

- [x] **Hard rename** — `sunset_window` → `sunrise_window` in schema, config templates, fixtures, CLI `--horizon-mode`, live `planning_horizon.mode`; no alias
- [x] **Internal symbols** — `SUNRISE_WINDOW`, `is_sunrise_planning_horizon`, `build_sunrise_window_matrix`, `compute_sunrise_planning_at_anchor`, `log_supports_sunrise_chart_view`, `VIEW_MODE_SUNRISE`
- [x] **Docs** — `[docs/spec/planning-horizon-sunset.md](docs/spec/planning-horizon-sunset.md)`, `[docs/konfiguration/batterie-pv.md](docs/konfiguration/batterie-pv.md)`
- [x] **Out of scope** — live `planning_horizon.mode` branching (`fixed_24h` | `sunrise_window`) remains **2.+1**; historical backtesting log filenames unchanged



### Version 1.93 P3 — Configuration UI restructure (2026-07-11)

- [x] **Nav sections** — `Planung` (Hauskonfigurator, Szenarieneditor) + `Echtzeit-Umgebung` (`[ui/navigation.py](ui/navigation.py)`); raw JSON editor not in main nav
- [x] **Echtzeit-Umgebung page** — `[ui/pages/page_live_environment.py](ui/pages/page_live_environment.py)`: `live_scenario_id` picker, resolved snapshot, comfort form from `[ui/config_forms.py](ui/config_forms.py)`
- [x] **Onboarding hints** — `[ui/setup_readiness.py](ui/setup_readiness.py)` sidebar copy aligned to new page names and order
- [x] **Tests & docs** — `tests/test_navigation_setup.py`, `tests/test_setup_readiness.py`; `[docs/einrichtung/greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)` acceptance table
- [x] **Acceptance** — greenfield smoke: onboarding → live selection → Szenario-Explorer unlock (follow-ups → [Backlog-Erledigt.md](Backlog-Erledigt.md) *Version 1.93 — smoke-test follow-ups*)
- [x] **Batterien tab** — entity CRUD moved to Hauskonfigurator (`[ui/pages/page_house_config.py](ui/pages/page_house_config.py)`); Szenarieneditor scenario CRUD only; onboarding copy + tests updated



### Version 1.93 P1 — Optional consumers (2026-07-11)

- [x] **Haus Wärme optional** — `thermal_annual` not mandatory (`[house_config/profiles_store.py](house_config/profiles_store.py)`, Hauskonfigurator)
- [x] **PV optional** — `[ui/setup_readiness.py](ui/setup_readiness.py)`, `[ui/planning_pv_form.py](ui/planning_pv_form.py)`
- [x] **Battery without PV** — battery required for MILP / `is_planning_ready()`; unset `pv_system_id` → zero PV forecast
- [x] **Optimizer/simulation tolerance** — `[house_config/entity_resolution.py](house_config/entity_resolution.py)`, `[config.py](config.py)`, `[house_config/baseload.py](house_config/baseload.py)`, `[house_config/planning_flex_bridge.py](house_config/planning_flex_bridge.py)`
- [x] **Tests** — greenfield bootstrap, setup readiness, house profiles without thermal/PV



### Version 1.93 P2 — Unified scenario model (2026-07-11)

- [x] **Live baseline as normal scenario** — `live_scenario_id` in `config.json` (default `live`); unified resolution in `[house_config/scenario_resolution.py](house_config/scenario_resolution.py)`; `config.py` rejects `runtime_settings` block
- [x] **UI mode rename** — `backtesting` → `scenario_explorer` (`[ui/mode_selector.py](ui/mode_selector.py)`, `[ui/navigation.py](ui/navigation.py)`, compose, VS Code launch); user-facing label **Szenario-Explorer**
- [x] **Szenarieneditor** — unified editor (`[ui/pages/page_scenario_editor.py](ui/pages/page_scenario_editor.py)`); removed orphaned `ui/scenario_runtime_form.py`; live scenario via `[ui/house_config_io.py](ui/house_config_io.py)`
- [x] **Templates & schema** — `config.example.json`, `backtesting_scenarios.example.json` (`live` entry), `config.schema.json` without `runtime_settings`
- [x] **Scripts & tests** — dev scripts default to `live`; backtesting tests use scenario id `live`; `[tests/config_fixtures.py](tests/config_fixtures.py)`
- [x] **Docs (DE)** — `[docs/konfiguration/ueberblick.md](docs/konfiguration/ueberblick.md)`, `[docs/ui/betriebsmodi.md](docs/ui/betriebsmodi.md)`, greenfield/container/betrieb, PV/preise specs
- [x] **Tests** — 143 passed locally (P2 subset); `migrate_runtime_entities` output update deferred to **1.93 P6a**



### Earnie rename (2026-07-11)

- [x] **Version 1.93 — branding** — UI/docs Ernie→Earnie; Loxone signal names (`Earnie_`*) unchanged in production config
- [x] **Packaging** — `pyproject` package `earnie`; CLI `earnie-`* with legacy `ernie-`* aliases
- [x] **Env vars** — canonical `EARNIE_`* with `ENERGY_OPTIMIZER_`* fallback (`runtime_store/env_vars.py`)
- [x] **Docker** — `ghcr.io/jochentcc/earnie-energy` image and `earnie-`* container names; dual-tag transition (`ernie-energy` alias)
- [x] **Runtime paths** — log file `earnie.log`; NAS path docs `docker/earnie`
- [x] **GitHub** — rename repository to `Earnie` on GitHub (Settings → General), then update remotes: `git remote set-url origin https://github.com/JochenTCC/Earnie.git` *(manual step — repo still* `Energy-Optimizer` *until renamed on GitHub)*



### Version 1.26.0 — Runtime entities & tariffs (release) (2026-07-11)

- [x] **Release 1.26.0** — Greenfield-first P0–P4, prod migration P5, legacy removal P6; live + backtesting share ID-only `runtime_settings` resolution; `version.py` → 1.26.0
- [x] **Acceptance** — greenfield smoke; migration draft + manual review path; no flat-field fallbacks; per-tariff aWATTar; `battery_wear` on selected battery only



### Version 1.26.0 P6 — Legacy removal (2026-07-11)

- [x] **P6 — Legacy removal (no fallbacks)**
  - Removed flat-field fallback in entity/tariff resolution (`house_config/entity_resolution.py`, `config.py` `_lookup_runtime_value`)
  - Removed global `battery_wear` and top-level `awattar` block support; pricing via `tariffs.json` only; API URL from `import_tariff_id` → `land` (`house_config/awattar_api.py`)
  - Schema: ID-only `runtime_settings`; removed deprecated flat fields from `config.schema.json`
  - Updated `config/config.example.json`, `config.minimal.json`, greenfield fixture, backtesting fixture to ID-only `runtime_settings`



### Version 1.26.0 P5 — Prod cutover (migration, tests, docs) (2026-07-11)

- [x] **Migration script** — `[house_config/migrate_runtime_entities.py](house_config/migrate_runtime_entities.py)`, CLI `[scripts/migrate_runtime_entities.py](scripts/migrate_runtime_entities.py)` (`ernie-migrate-runtime`): flache `runtime_settings` → Entwurf mit ID-only refs, `batteries[]`/`pv_systems[]`, Geo auf `house_profiles.json`, `battery_wear` auf Batterie-Eintrag, aWATTar-Felder in Tarife; `MIGRATION_REVIEW.md` — manuelle Prüfung vor NAS-Deploy
- [x] **Tests** — `tests/test_house_config.py`: Migration, Auflösungs-Parität, CLI-Entwurf
- [x] **Docs (DE)** — `[docs/konfiguration/ueberblick.md](docs/konfiguration/ueberblick.md)`, `[preise.md](docs/konfiguration/preise.md)`: ID-only `runtime_settings`, Migration, Konfigurations-UI
- [x] **Backlog** — P5 ohne 7g-a (NAS-Abnahme); Follow-up: Version 1.+1 „Include tariffs.json in deploy“



### Version 1.26.0 P4 — UI live configuration (2026-07-11)

- [x] **Runtime entity UI** — `[ui/config_forms.py](ui/config_forms.py)`, `[ui/scenario_runtime_form.py](ui/scenario_runtime_form.py)`: ID dropdowns (battery, PV, tariffs, house profile); resolved PV/battery/tariff read-only; `[ui/pages/page_config.py](ui/pages/page_config.py)` expander renamed
- [x] `update_runtime_settings()` — IDs only in `[config.py](config.py)`; rejects flat PV/battery and geo fields
- [x] `save_runtime_scenario_refs()` — entity IDs only; strips legacy geo from `runtime_settings` (`[ui/house_config_io.py](ui/house_config_io.py)`)
- [x] **Geo on house profile** — `latitude`/`longitude`/`timezone_name` resolved from `house_profile_id` (`[house_config/scenario_resolution.py](house_config/scenario_resolution.py)`); removed from greenfield `runtime_settings`
- [x] **Timezone derivation** — `timezonefinder` + `[house_config/geo_timezone.py](house_config/geo_timezone.py)`; no manual timezone entry in Hauskonfigurator; optional geo override in Szenarieneditor “Weitere Szenarien”
- [x] **Tests** — `tests/test_config_runtime_resolution.py`, `tests/test_geo_timezone.py`; greenfield ID-only keys in `tests/test_greenfield_bootstrap.py`
- [x] **Docs** — `[docs/einrichtung/greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)` acceptance table updated



### Version 1.26.0 P3 — Price pipeline live (2026-07-11)

- [x] **Import pricing live** — shared `import_brutto_cent_for_slots` / `enrich_slots_import_prices` in `data/backtesting_prices.py`; live matrix + historical day via `profile_manager.py`; reference costs in `simulation/engine.py`
- [x] **Parity test** — same tariff IDs → identical import cent/kWh live vs backtesting (`tests/test_price_pipeline_p3.py`)
- [x] **P3a — Backtesting window** — `resolve_simulation_window()` snaps start to Monday of week with `(today − 12 months)`; documented in `ui/backtesting_time_ranges.py`
- [x] **P3b — Minimal thermal bridge** — `thermal_on_off_hourly_profile` in `data/heating_need.py`; on/off at `nominal_power_kw` in `data/consumption_profiles.py`; `house_profile_baseload_overlay` (generic + thermal) in `house_config/planning_flex_bridge.py` for live + backtesting
- [x] **Tests** — `tests/test_price_pipeline_p3.py`



### Version 1.26.0 P0 — Greenfield onboarding deferrals (2026-07-11)

- [x] **Deferred runtime params** — incomplete Greenfield planning no longer crashes `import config`; PV/battery/tariff params load after Szenarieneditor; `main.py` waits until planning complete (`config.py`, `main.py`, `ui/config_forms.py`, `tests/test_config_runtime_resolution.py`)
- [x] **Deferred Loxone credentials** — `.env` entry no longer blocks UI/worker during planning; optional sidebar form + Merker test when going live (Silent-Modus) or verifying aliases (`runtime_store/dotenv_io.py`, `ui/setup_dotenv.py`, `ui/setup_progress.py`, `app.py`, `main.py`)
- [x] **Tests** — `test_config_runtime_resolution.py`, `test_dotenv_io.py`, `test_greenfield_bootstrap.py`



### Version 1.26.0 P2 — Central resolution in config.py (2026-07-11)

- [x] `resolve_runtime_settings()` — unified live + backtesting baseline in `house_config/scenario_resolution.py`
- [x] `_load_dynamic_params()` — loads PV/battery/tariff/geo from resolved dict (ID wins, legacy flat fallback)
- [x] `get_battery_wear_cent_per_kwh()` — from `_battery_wear` on selected `batteries[]` entry; global fallback only without `battery_id`
- [x] `get_backtesting_scenarios()` — baseline via same `_resolve_runtime_settings_dict()` path
- [x] **Flex bridge** — `get_flexible_consumers()` merges `_planning_flex_consumers`; live baseload overlay via `fixed_generic_hourly_overlay` in `profile_manager.py`
- [x] `get_feed_in_settings()` — uses resolved runtime incl. `_monthly_fixed_tariffs`
- [x] **Tests** — `tests/test_config_runtime_resolution.py`



### Version 1.26.0 P1 — Data model & schema (2026-07-11)

- [x] **Schema** — `config.schema.json`: `battery_wear` on `battery_entity`, `house_profile_id` + deprecated flat `runtime_settings`; `tariffs.schema.json`: import `monthly_table`, per-tariff aWATTar surcharges
- [x] `battery_wear` **on** `batteries[]` — normalized in `house_config/entity_resolution.py`; resolved as `_battery_wear` (P2 wires MILP)
- [x] **Import** `monthly_table` — `tariffs_store.py`, `data/tariff_pricing.py`, `data/backtesting_prices.py`
- [x] **aWATTar surcharges per tariff** — import `awattar` + export `dynamic_epex` fields in `tariffs.json` / examples; legacy `config.json` awattar block still fallback until P6
- [x] **Example configs** — `config.example.json`, `tariffs.example.json`, greenfield battery/tariffs, backtesting fixture
- [x] **Tests** — `test_tariff_pricing.py`, `test_house_config.py`



### Version 1.26.0 P0 — Greenfield pilot (strict target config) (2026-07-11)

- [x] **ID-only** `runtime_settings` — `greenfield/config/config.json` and `config/config.minimal.json` stripped of flat PV/battery/tariff duplicates; IDs only (geo/timezone on house profile since P4)
- [x] **Sunset-2-Sunset on greenfield** — `ENERGY_OPTIMIZER_UI_MODES=sunset2sunset,backtesting` in `docker-compose-greenfield.yml` and VS Code Greenfield launch
- [x] **Acceptance checklist** — Live-path smoke steps in `[docs/einrichtung/greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)` (execution blocked until **1.26.0 P2**)
- [x] **Tests** — `tests/test_greenfield_bootstrap.py`: ID-only runtime_settings assertions for minimal template and greenfield config



### Bugfix EV absence vs. live control (2026-07-10)

- [x] **EV unplugged: no charge setpoint to Loxone** — With `anticipated` + `plugged_in: false`, `_effective_consumer_power_kw` suppresses output; `booking_power_kw` books no fictitious energy (v1.24.3)
- [x] `available_from` **during actual absence** — Same-day late return does not count as immediately available; overnight window preserved (`resolve_absent_availability`)
- [x] **Tests** — `test_charging_context`, `test_delivery_tracking`, `test_loxone_client`; reference dump `chart_debug_20260710_111939`



### Version 1.25.0 — UI follow-up close-out (2026-07-10)

- [x] **Backtesting UI — explain time ranges** — Caption + expander in `ui/backtesting_cons_data.py` and `ui/backtesting.py` (`ui/backtesting_time_ranges.py`): `cons_data_retention_months` vs. `price_range` simulation window vs. sliced reference consumption vs. Hauskonfigurator 8760 h
- [x] **PV in consumption UI** — `pv_kw` as own trace **PV-Erzeugung** (not in consumption stack); monthly line + weekly line in `ui/consumption_display/charts.py`; test `test_cons_data_bundle_pv_not_in_stack`



### Version 1.25.0 — UI follow-up decisions & clarifications (2026-07-10)

**Scope:** Close-out of planning notes from `Backlog.md` § Version 1.25.0 UI follow-up; implementation in 1.25.a–1.25.f.

#### Decisions recorded

- [x] **Consumption UI data mode (Mode A):** House configurator = actual CSV vs. model; backtesting = `cons_data` only (historical); scenario editor = modeled house profile only — no actual-vs-model on backtesting/scenario editor
- [x] **Monthly view timeline:** dropped — timeline only ISO week, hourly
- [x] **Weekly view timeline:** ISO week, hourly; navigation ←/→; datetime X-axis, lines per consumer
- [x] **Deviation detail:** full cockpit Chart1/2 in 24h and SA_0–SA_2 (1.25.f)
- [x] **Monthly cost table:** dataframe table dropped; Plotly monthly chart remains
- [x] **Total costs:** compact annual table (all scenarios incl. reference) instead of metric columns alone
- [x] **Δ vs. reference:** cost change (`scenario € − reference €`); negative = cheaper, positive = more expensive



#### Clarifications resolved

- [x] **"Non-optimized annual consumption"** — reference/`cons_data` (historical without optimization), not non-optimized scenarios
- [x] **Test run (1 month):** consumption UI limited to test month (`nav_bounds` + sliced `cons_data`)
- [x] **Scenario editor:** modeled house profile of assigned profile only (no `cons_data`, no CSV actual) — per Mode A
- [x] **Total cost table columns:** Scenario | Annual kWh | Annual € | Δ vs. reference



#### Delivered code state (at close-out)

- [x] `ui/consumption_display/` (three modes); backtesting page: cons_data section, total cost table, deviation list with Chart1/2 (1.25.f), window snapshots (`backtesting_window_snapshots.jsonl`), horizon-mode UI (`fixed_24h` / `sunset_window`), reference consumption, monthly cost chart
- [x] Plausibility false positives with house profile fixed (bugfix → `Backlog-Erledigt.md` § Bugfix — Backtesting plausibility)



### Version 1.26.0 P2b — Smoketest follow-ups (UX) (2026-07-11)

- [x] **Hauskonfigurator:** modeled consumption chart without Jahres-Verbrauchs-CSV (`ConsumptionDisplayMode.MODELED_PROFILE`; scenario-editor pattern in `ui/house_config_profile_form.py`)
- [x] **ISO week jump:** week number only — year inferred from data range (`ui/consumption_display/navigation.py`: `parse_iso_week_number_only`, `resolve_iso_week_jump_target`)
- [x] **New PV-Anlage / Solarkollektor:** inherit profile `default_pv_tilt` / `default_pv_azimuth` (18°/0° fallback; PV profile picker updates tilt/azimuth via `on_change`)



### SE Abweichungs-Kalender — polish (2026-07-13)

- [x] **Calendar navigator:** single-month view with Zurück/Vor; color-coded deviation days; on-demand Chart1/2 (`ui/backtesting_deviation_calendar.py`, `ui/backtesting_deviation_list.py`)
- [x] **Snapshot cache:** on-demand windows appended to `backtesting_window_snapshots.jsonl` (`append_window_snapshot`)
- [x] **diag_single_window:** CLI command + optional run from detail expander (`ui/backtesting_diag_single_window.py`)
- [x] **Scenario picker:** radio list with deviation markers; single scenario detail/charts
- [x] **Spec:** `docs/dev/done/backtesting-deviation-calendar.md`



### Version 1.25.f follow-ups — deviation list & week navigation (2026-07-10)

- [x] **Deviation dedup:** `dedupe_critical_cases_by_window()` — per `(scenario_id, window_anchor)` keep most critical (`milp_no_optimal` > `strict_slow` > `strict_fallback` > `consumption_tolerance`)
- [x] **Row selection → Chart1/2:** `st.dataframe` single-row selection replaces separate selectbox (`ui/backtesting_deviation_list.py`)
- [x] **ISO week jump:** direct KW entry (`12/2025`, `KW 12/2025`, `2025-W12`) in `ui/consumption_display/navigation.py`
- [x] **Tests:** `test_backtesting_critical_cases.py`, `test_backtesting_deviation_list.py`, `test_consumption_display.py`



### Version 1.25.f — Chart1/2 detail for deviations (2026-07-10)

**Scope (after 1.25.e smoketest ✅):** full — 24h + SA_0–SA_2 with cockpit Chart1/2; window snapshots for failed windows + on-demand fallback.

- [x] **Persistence:** `simulation/backtesting_snapshots.py` — JSONL sidecar `backtesting_window_snapshots.jsonl` (`chart_rows`, `matrix`, `meta`, `horizon_mode`, scenario ID)
- [x] **Engine:** snapshot collection on plausibility failure and on-demand paths (`simulation/engine.py`)
- [x] **Adapter:** `ui/backtesting_display_bundle.py` — `build_backtesting_display_bundle` / `load_backtesting_display_bundle` → `OptimizationDisplayBundle`
- [x] **UI:** `ui/backtesting_deviation_list.py` — `render_optimization_chart1/2` below deviation list; toggle 24h | SA_0–SA_2 (disabled when log `fixed_24h`)
- [x] **Fallback:** on-demand re-simulation of a window when no snapshot exists
- [x] **Tests:** `test_backtesting_display_bundle.py`, `test_backtesting_snapshots.py`, `test_backtesting_snapshot_collector.py`, `test_backtesting_deviation_list.py`, `test_backtesting_ui_helpers.py`

**Manual acceptance**

- [x] Select deviation → Chart1 energy balance (PV, battery, consumer stack, zones per scope)
- [x] Chart2 cost lines target/actual
- [x] Toggle 24h ↔ SA_0–SA_2



### Version 1.25.e — Smoketest backtesting `sunset_window` (2026-07-10)

**Purpose:** Verify `sunset_window` backtesting (Now→SA₂) is stable — prerequisite for Chart1/2 SA zones (1.25.f).

**Result: ✅ stable** — June 2025, 30 windows, plausibility 30/30 both modes, no CBC aborts. Sunset ~0.37 € higher than `fixed_24h` on scenario `fixture_5kwh_fixed` (10.74 € vs 10.37 €); reference 36.03 €. Protocol: `backtesting_logs/smoketest_125e/protocol.md`.

- [x] **CLI smoketest:** `scripts/run_backtesting.py --horizon-mode sunset_window --start-month <M> --end-month <M>` — exit 0, `"horizon_mode": "sunset_window"` in log, plausibility/CBC without unexpected aborts
- [x] **UI:** `--horizon-mode` on `build_backtesting_command` / run controls (`ui/backtesting_runner.py`)
- [x] **Document result:** ✅ stable — full 1.25.f scope approved

**Manual acceptance**

- [x] Smoketest protocol: command, config path, month, duration, exit code, `horizon_mode` in log
- [x] No blocker for 1.25.f full scope



### Bugfix — Backtesting plausibility (deviation list overfilled) (2026-07-10)

**Trigger:** Manual acceptance **1.25.d** — deviation list ~934 entries; `runtime_settings` failed in every window (`optimized_flex_kwh = 0` despite historical flex target values).

**Root cause:** For house-profile backtesting (`flexible_consumers: []`), consumer columns were missing from the profile DataFrame; `delivered_flex_kwh_from_rows` and `resolve_horizon_consumer_targets_kwh` only considered config consumers; planning target values incorrectly overwrote cons_data history on days without flex consumption.

- [x] **Diagnosis:** Greenfield runtime; flex-only failure pattern (`diff_kwh = 0`, `flex_diff > 0`, `optimized_flex = 0`) verified
- [x] `data/profile_manager.py`**:** House-profile consumers from `cons_data` (`expected_cons_data_consumer_ids`) into profile format
- [x] `simulation/engine.py`**:** Flex/baseload from cons_data (MILP scope); `_flexible_consumers` in meta; no planning-target fallbacks when cons_data = 0
- [x] `optimizer/targets.py` **+** `optimizer/simulation.py`**:** `flexible_consumers` parameter for horizon limits and flex delivery
- [x] `scripts/analyze_plausibility_failures.py`**:** Time range from log `meta.period`
- [x] **Regression:** `tests/test_baseload_validation.py` (planning flex plausibility)

**Manual acceptance**

- [x] Greenfield backtesting recalculated; deviation list without systematic filling of all windows
- [x] Acceptance 1.25.d “clean run” completed



### Version 1.25.d — Deviation list (cost comparison) (2026-07-10)

- [x] Unified list of notable cases (basis: `extract_critical_cases()` — plausibility + CBC events)
- [x] Columns: window, scenario, type, Δ kWh (target/actual)
- [x] Selecting an entry → detail area (placeholder until 1.25.f)
- [x] Reference scenario: no deviation list

**Manual acceptance**

- [x] Run with deviations: sorted list; selection highlights window + scenario
- [x] Clean run: empty list / info notice (after plausibility bugfix)
- [x] Chart “window end”: placeholder (plausibility chart) until 1.25.f, no cockpit Chart1/2



### Version 1.25.c — Backtesting page layout (2026-07-10)

Target order: cons_data (status/generation/consumption UI) → scenarios + run buttons → total cost table → reference consumption → monthly cost chart (without dataframe/hourly chart).

- [x] Page order (`ui/backtesting.py`, `ui/backtesting_cons_data.py`, `ui/backtesting_results_helpers.py`)
- [x] Removed: scenario/month selectbox, hourly cost chart, monthly dataframe in cost comparison
- [x] Test-run caption + `nav_bounds` for calendar-week navigation
- [x] Total cost table with Δ as cost change (`scenario € − reference €`)
- [x] Consumption UI in cons_data section and in results (log period, period-appropriate subheader)
- [x] Synthetic `cons_data` from house profile when `flexible_consumers` empty (`data/cons_data_house_profile.py`)
- [x] Warning when `{verbraucher_id}_kw` missing or only 0
- [x] Tests: `test_backtesting_results_helpers.py`, `test_cons_data_house_profile.py`

**Manual acceptance**

- [x] Full run: no scenario/month selectbox, no hourly cost chart
- [x] Total cost table with reference + scenarios + Δ
- [x] Test run: charts/navigation only test month; consumers visible in timeline



### Version 1.25.b — Consumption UI on three pages (2026-07-10)

- [x] **House configurator** — `render_consumption_comparison_panel` via core, mode `csv_validation`
- [x] **Backtesting** — `render_cons_data_section`: keep status/generation, visualization via core (`cons_data`)
- [x] **Scenario editor** — section “Consumption profile (model)” for runtime house profile, mode `modeled_profile`

**Manual acceptance**

- [x] Three pages: same layout, navigation, legend colors
- [x] Scenario editor without actual data; backtesting without model comparison



### Version 1.25.a — Consumption UI core (2026-07-10)

- [x] **Three modes** in `ui/consumption_display/`: `csv_validation`, `cons_data`, `modeled_profile`
- [x] **Monthly overview:** separate bar per consumer; sum = total consumption; baseload as residual on its own track
- [x] **Timeline:** ISO calendar week, hourly; navigation ←/→ (no month toggle; follow-up: datetime X-axis, lines per consumer)
- [x] **Data layer:** `build_modeled_hourly_kw_by_consumer()` in `data/consumption_profiles.py`
- [x] **Tests:** `tests/test_consumption_display.py`, `tests/test_consumption_display_integration.py`

**Manual acceptance**

- [x] House configurator + CSV: monthly bars actual vs. model; calendar-week navigation; consumers + baseload visible in weekly timeline
- [x] Synthetic `cons_data`: stacked monthly bars sum ≈ `total_kw`
- [x] ←/→ calendar week: correct ISO week boundaries; readable hourly timeline



### Version 1.25.0 — Backtesting with house configuration (2026-07-10)

- [x] **House configurator** — optional annual total consumption CSV (format check: monthly bars + hourly timeline)
- [x] **Scenario editor** — subpage under configuration; house configurator only consumers + PV; battery/tariffs in scenario editor; default scenario runtime (required before backtesting/operation); additional scenarios with different batteries/tariffs
- [x] **Backtesting from configuration** — data from house configuration + scenarios; load run when fingerprint matches, otherwise recalculate
- [x] **Consumption data (**`cons_data_hourly.csv`**)** — visualization, synthetic generation (`scripts.generate_cons_data`), consumer ID match status, backtesting start disabled without valid file
- [x] **cons_data plot** — navigation like annual CSV; column timelines `total_kw` / `baseload_kw` / `pv_kw`
- [x] **Backtesting runner** — test run (one month), progress bar (`--progress-file`), grouped scenario bars in monthly cost comparison
- [x] **Sidecar paths** — `tariffs.json` / `house_profiles.json` / `backtesting_scenarios.json` next to per-ENV `config.json` (`persist_paths`)
- [x] **Fingerprint** — tariff specs and aWATTar pricing block in scenario fingerprint; export tariff alias `awattar_sunny_float` → `dynamic_epex`
- [x] **Tests** — `test_backtesting_cons_data`, `test_backtesting_charts`, `test_backtesting_plausibility_charts`, `test_backtesting_ui_helpers`, `test_persist_paths_sidecars`

**Manual acceptance (Greenfield, Streamlit :8511 or container :8502)**

- [x] Greenfield reset; only house configurator + configuration visible; sidebar shows missing steps
- [x] **House configurator** — save thermal house profile + PV system; optionally upload annual CSV → monthly bars and hourly timeline (actual vs. model)
- [x] **Scenario editor** appears after house profile + PV — create battery, save runtime (battery, tariffs, house profile, geo)
- [x] **Backtesting** appears after complete runtime scenario — configured scenarios displayed
- [x] **Consumption data (**`cons_data_hourly.csv`**)** — without valid file: section with notice, **Start backtesting** button disabled
- [x] Button **Generate consumption data (synthetic)** — `runtime/cons_data_hourly.csv` + `.meta.json` with data rows
- [x] Monthly bars and calendar-week hourly timeline (actual vs. model) in consumption data section
- [x] Consumer ID match status — matches current config (green) or warning on mismatch or missing meta file
- [x] Button **Start backtesting** — run completes successfully; costs, months, plausibility and hourly chart visible
- [x] After change to runtime/scenario — warning “Run does not match configuration” + **Recalculate**
- [x] Merge PR #4



### Bugfix runtime scenario save (2026-07-09)

- [x] **KeyError on empty entity lists** — safe ID resolution in `scenario_form_helpers.py`; disabled selectboxes for empty PV/battery lists in runtime and scenario editor
- [x] **PV/battery form state** — seed widget state from saved values (`planning_pv_form.py`, `planning_battery_form.py`)
- [x] **Tests** — `tests/test_scenario_form_helpers.py`, extension `tests/test_planning_editors.py`



### hausconfig: solar thermal, profile location (2026-07-09)

- [x] **Solar thermal collector** — heating need model with solar thermal in `data/heating_need.py`; validation charts and tests (`tests/test_heating_need_solar.py`)
- [x] **Profile location** — `latitude`/`longitude` and PV defaults at profile level (`house_profiles.schema.json`, `house_config_profile_form.py`)
- [x] **Consumption validation** — extended charts and tests for thermal profile with solar thermal



### Bugfix native filter window log spam (main.py) (2026-07-09)

- [x] `filter_contexts` **once per run** — `main.py` resolves before `get_consumer_remaining_kwh` and passes through to MILP, remaining-target adjustment and `calculate_optimization_savings`
- [x] **Horizon simulation** — `simulate_horizon` / `_simulate_single_hour_optimizer` / `calculate_optimization_savings` accept prebuilt `filter_contexts`; no repeated Loxone read per MILP hour
- [x] **Logging** — INFO “native filter window Start=…” only at `resolve_filter_context`, not on every indirect call
- [x] **CBC log spam** — `record_cbc_event` no longer logs per slot during active collection (`begin_cbc_event_collection`); `simulate_horizon` summarizes at end as one INFO line (`summarize_cbc_events`); live MILP in `main.py` unchanged at INFO
- [x] **Tests** — `TestFilterContextCaching` in `tests/test_filter_context.py`; CBC suppression/summary in `tests/test_cbc_events.py`



### Bugfix UI bugs 1.23.1 (2026-07-09)

- [x] **Ranking table compact on mobile** — 3 columns (checkbox before time, quality, delta); cost column removed (`ui/pages/page_devices.py`)
- [x] **Cockpit Chart 1/2 legend** — variant A (unified collapsible): `showlegend=False`, `margin.b` ≈ 55, HTML `<details>` on all viewports (`ui/chart_legend_mobile.py`, `ui/charts.py`)
- [x] **Rated power/runtime with active plan** — input fields and save button disabled with notice text
- [x] **SOC BL target bridge at zone boundaries** — `bridge_left=(index > 0)` in `add_baseline_soc_traces`
- [x] **Price curve continuous** — single trace instead of segmented HV lines (`add_price_on_soc_axis_trace`)
- [x] **Manual appliances hatching** — stable patterns per `appliance_id` (`manual_appliance_pattern_shape` in `ui/chart_colors.py`)



### Bugfix mobile legend cockpit (Chart 1/2) (2026-07-09)

- [x] **Mobile legend cockpit (Chart 1/2)** — Plotly legend hidden below 768px via CSS; colored `<details>` as replacement (mobile only). Desktop: Plotly legend only, no expander (`ui/chart_legend_mobile.py`). Prod acceptance confirmed.



### Bugfix Sankey SwimSpa/filter case B (total meter) (2026-07-09)

- [x] **Sankey + Chart 1 SwimSpa/filter (total meter case B)** — fix **v1.24.1**: Sankey/live UI load flex power when `optimizer_run_state` stale (>120 s) with `filter_contexts` + `slot_datetime` (`fetch_live_flex_kw_for_ui` in `data/live_consumption.py`); filter inference as in `main.py`. Prod acceptance: native window 10–14 — two Sankey flows (SwimSpa + SwimSpa filter), filter power correctly assigned, no misleading target/actual mismatch color at target 0. Reference dumps: `chart_debug_20260708_114712`, `chart_debug_20260709_120500`.



### Version 1.24.g — monthly_float feed-in tariff (OeMAG reference curve) (2026-07-09)

- [x] **Schema** — export type `monthly_float` in `tariffs.schema.json`; `oemag_monthly_feed_in_rates` + `monthly_float_reference_cent_kwh` in `backtesting_scenarios.schema.json`
- [x] **Pricing pipeline** — `data/monthly_float_rates.py` (OeMAG scaling); `tariff_pricing.export_cent_kwh`; `get_backtesting_feed_in_settings()` builds scaled monthly table at runtime
- [x] **Catalog & converter** — `tools/convert_dach_tariffs.py` from `einspeisetarife_dach_erweitert.json`; 5 `monthly_float` export tariffs in `config/tariffs.json`
- [x] **OeMAG reference data** — 12 months Jul 2025–Jun 2026 in `backtesting_scenarios.example.json`; `fixed_monthly_feed_in_rates` (aWATTar-SUNNY) unchanged
- [x] **Tests & docs** — `tests/test_monthly_float_rates.py`; extension of `test_tariff_pricing` / `test_house_config`; `docs/konfiguration/preise.md`



### Version 1.24.f — DACH tariff catalog & pricing model (backtesting) (2026-07-09)

- [x] **P1 — Schema & pricing functions** — `tariffs.schema.json` (DACH types + `catalog_as_of`); `house_config/tariffs_store.py` (`_import_tariff_spec`, `_export_tariff_spec`, scenario specs); `data/tariff_pricing.py` (`import_cent_kwh` / `export_cent_kwh`, legacy `awattar`/`dynamic_epex`)
- [x] **P2 — Backtesting pipeline & market zones** — `data/data_loader.py` (AT / `DE-LU` / CH); tariff-aware pricing in `simulation/engine.py`, `data/backtesting_prices.py`, `data/feed_in_prices.py`
- [x] **P3 — DACH converter & catalog** — `tools/convert_dach_tariffs.py`; `config/tariffs.json` with 44 tariffs (`catalog_as_of=2026`)
- [x] **P4 — Planning UI** — `ui/planning_tariff_form.py`, `ui/pages/page_scenario_editor.py` (type labels, country/currency/notes, `catalog_as_of`, DE grid-fee override)
- [x] **P5 — Tests & docs** — `tests/test_tariff_pricing.py`, extension of `tests/test_house_config.py`; `docs/konfiguration/preise.md`



### Version 1.24.e — Planning editors & house configurator UX (2026-07-09)

- [x] **P1 — Config drift** — `should_show_config_drift()` suppresses notice during `needs_planning_onboarding()`; empty `flexible_consumers` ignored in drift check
- [x] **P2 — House configurator UX** — auto IDs (`house_config/id_slug.py`); type label “Haus Wärme”; building classes with HWB; optional `hwb_kwh_m2`
- [x] **P3 — Planning configuration** — PV/battery/tariff tabs in house configurator; bootstrap `tariffs.json` from `tariffs.example.json`; tariff selection → `runtime_settings.import/export_tariff_id` (no tariff editor)
- [x] **P4 — Tests & docs** — `tests/test_planning_editors.py`; setup/navigation/drift adjustments; `[greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)`



### Version 1.24.d — Greenfield onboarding (minimal config + UI unlock) (2026-07-09)

- [x] **P1 — Minimal bootstrap** — `config.minimal.json` + empty templates for `house_profiles`, `tariffs`, `backtesting_scenarios`; bootstrap uses minimal instead of example files; `config.example.json` remains reference
- [x] **P2 — Runtime UI gating** — `ui/setup_readiness.py`, `ui/setup_progress.py`, `ui/navigation.py`: after Loxone setup only house configurator + configuration until planning complete
- [x] **P3 — Backtesting unlock** — unlock with thermal house profile + PV + battery + import/export tariff; scenario editor locked for now (follow-up)
- [x] **Tests + docs** — `tests/test_setup_readiness.py`, `tests/test_navigation_setup.py`; `[greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)`



### Version 1.24.c — Greenfield dev stack (2026-07-09)

- [x] **P1 — Greenfield compose** — `docker-compose-greenfield.yml` with `greenfield/config` + `greenfield/runtime`, container `ernie-greenfield-`*, UI port **8502**, Loxone verify off
- [x] **P2 — Acceptance helpers** — checklist in `[docs/einrichtung/greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)`; smoke test `tests/test_greenfield_bootstrap.py` (without fixture snapshot `tests/fixtures/greenfield/`)
- [x] **Follow-up during walkthrough** — `Dockerfile`: `share/config/` extended with tariff, house profile and backtesting scenario templates (bootstrap on empty volume)



### Version 1.24.0 — House configurator UX & EV profile (2026-07-09)

- [x] **P1 — Data model** `ev` — type `ev` in `house_profiles.schema.json` and `house_config/profiles_store.py`; planning subset from live `eauto` without `loxone`; `house_profiles.example.json` with EV as `ev`
- [x] **P2 — UI add/remove** — `ui/house_config_profile_form.py` (tab in `page_house_config.py`): `st.session_state` consumer list, “Add consumer” / “Remove”, type dropdown incl. “E-Auto” with conditional fields
- [x] **P3 — Annual and hourly profile** — `house_config/ev_profile.py` (`estimate_ev_annual_kwh`, `ev_hourly_kw_for_day`); `baseload.py` and `data/consumption_profiles.py` with window-based `ev` branch
- [x] **P4 — Tests** — `tests/test_house_config.py`: normalization, annual kWh, hourly profile only in charging window, `build_hourly_kw_profile`
- [x] **P5 — Tariff list date in UI** — implemented with **1.24.f** (`catalog_as_of` in `planning_tariff_form.py` and `page_scenario_editor.py`)



### Version 1.24.b — LOC refactoring top 3 (2026-07-09)

- [x] **Epic 1 —** `optimizer/milp.py` (~991 → ~170) — `milp_consumers.py`, `milp_horizon.py`, `milp_result.py`; `_derive_control_from_milp` → `optimizer/battery.py`; re-exports for tests
- [x] **Epic 2 —** `config.py` (~1543 → ~720) — package `settings/` (`json_io`, `flexible_consumers`, `appliances`, `scenarios`, `system_settings`); `config.py` as orchestrator facade
- [x] **Epic 3 —** `ui/charts.py` (~2822 → ~400) — `chart_slot_axis`, `chart_trace_segments`, `chart_soc`, `chart_cumulative`, `chart_decorations`, `chart_consumer_stack`; thin facade + re-exports



### Version 1.24.a — House configurator and scenarios (2026-07-09)

- [x] **P1 — Battery & PV as entities** — `batteries[]` / `pv_systems[]` in `config.json`; scenario selects one ID each; backward compatible with flat `runtime_settings`
- [x] **P2 — Electricity tariffs** — `config/tariffs.json` with import/export tariffs; scenario references `import_tariff_id` / `export_tariff_id`
- [x] **P3 — Consumers & baseload** — `config/house_profiles.json`; generic, thermal, baseload with 5% lower bound
- [x] **P4 — Composite scenario** — `backtesting_scenarios.json`; resolution in `config.py` for `simulation/engine.py`
- [x] **P5 — UI** — house configurator (`page_house_config.py`) and scenario editor (`page_scenario_editor.py`)



### Bugfix Chart 1 PV line = actual (forecast_pv after overlay) (2026-07-08)

- [x] **Log** `forecast_pv_kw` **before live overlay** — `main.py` stores Forecast.Solar value, not `consumption_snapshot.pv_kw`; chart line vs. actual bars distinguishable
- [x] **NaN** `PV-Ist` **in MILP rows** — flow balance falls back to forecast (`chart_flow_balance.py`)



### UI S-2 — Chart 1 PV line continuous (2026-07-08)

- [x] **PV forecast line continuous** — one yellow line (`CHART_PV_LINE_COLOR`) over gray/neutral/green; overlay “PV-Prognose (Log)” removed
- [x] **Data model** — `PV-Prognose (kW)` = forecast; `PV-Ist (kW)` only for flow-balance bars in log
- [x] Tests + `docs/ui/charts.md`



### Manual appliances — Chart 1 cockpit (follow-up phase 5) (2026-07-08)

- [x] **Dedicated named traces in Chart 1 flex stack** — planned appliances from `appliance_schedules.json` as flex bars (washing machine, dryer, …), not only in `expected_p_act`/`Grundlast`; `apply_appliance_schedules_to_chart_rows` + `_finalize_chart_rows_for_display`
- [x] **Shared color, appliance-specific hover** — `COLOR_MANUAL_APPLIANCE` / `flex_bar_chart_color`; stack order in `ordered_active_consumers_for_stack`
- [x] **Live cache on plan checkbox** — `invalidate_live_optimization_cache()` on “Manuelle Geräte” after saving/deleting plan



### Version 1.23 — Manual appliances, consumer analysis & charts (2026-07-08)

- [x] **Appliance parameters in config.json** — `update_appliance_defaults()`, save form on “Manuelle Geräte”
- [x] **Star thresholds** — combined k_act/percent rule; config block `appliance_recommendation` + UI expander
- [x] **PV actual + forecast in gray area** — column `PV-Prognose-Log (kW)`, muted chart trace
- [x] **Mobile legend** — CSS + expander below Chart 1/2 (`ui/chart_legend_mobile.py`)
- [x] **Manual appliance planning → optimization** — `appliance_schedules.json`, matrix injection on `expected_p_act`, checkbox in recommendation table (immediate adoption); SMB fallback on write
- [x] **Consumer analysis Swimspa** — temperature actual/target + filter autonomous/Ernie (`page_consumer_analysis.py`)
- [x] **Version 1.23.0** — minor bump



### Bugfix Chart 1 SoC current hour before now + BL target (2026-07-08)

- [x] **Chart 1: SoC before now without MILP constant** — ramp first MILP quarter-hour → now from log extrapolation (`_current_hour_soc_ramp_before_now`, `_soc_from_history_extrapolation`); test `test_soc_intra_hour_ramp_before_now_replaces_flat_milp_head`
- [x] **Chart 1: SoC BL target not in gray area** — BL target trace only from log boundary, no bridge into gray; test `test_baseline_soc_trace_starts_at_history_boundary_not_in_gray`
- [x] **Chart 1: BL target and SoC meet at now** — shared anchor `soc_at_now` from log data; test `test_baseline_soc_meets_optimized_soc_at_now`
- [x] **Live acceptance confirmed**
- [x] **Version 1.22.5** — patch bump



### Bugfix savings manual appliances (2026-07-08)

- [x] **Delta to best time instead of savings** — column/caption “Delta to best time (€)” (`cost − cheapest`); sign `+`/`-`; red when positive, green when negative (`ui/pages/page_devices.py`, `tests/test_page_devices_display.py`)
- [x] **Rated power always editable** — `number_input` for all `power_source`; `default_power_kw` from config only as default/hint caption
- [x] **Version 1.22.2** — patch bump



### Bugfix charging_context timezone-aware live (2026-07-08)

- [x] **Streamlit TypeError naive/aware datetime** — `_align_like` in `optimizer/charging_context.py`; config windows (`car_available_from_hour`, Loxone FertigUm) aligned to timezone-aware matrix slots; tests timezone-aware horizon
- [x] **Version 1.22.1** — patch bump



### Loxberry container multi-arch (2026-07-08)

- [x] **7f — Loxberry container** — multi-arch build (`--target all`) via buildx; `docker-compose-loxberry.yml`; go/no-go in README and `container.md`; Dockerfile platform-neutral
- [x] **Version 1.22.0** — minor bump



### Bugfix Chart 1 SoC current hour (2026-07-08)

- [x] **Chart 1: extrapolate SoC after now until end of hour** — no horizontal step in neutral MILP area of current hour; ramp now → `_soc_tail_y_from_row` (`ui/charts.py`, `chart_now` passed through); live acceptance confirmed; test `test_soc_intra_hour_ramp_replaces_flat_milp_tail`
- [x] **Version 1.21.5** — patch bump



### Bugfix version display sidebar (2026-07-08)

- [x] **Version display at top of sidebar** instead of cockpit title — `app.py` (`_render_sidebar_version`), `version` parameter removed from `render_page_title_with_help`
- [x] **Version 1.21.1** — patch bump



### Bugfix Chart 2 gray/neutral bridge (2026-07-08)

- [x] **Chart 2: cost and consumption connected at gray|neutral boundary** — forecast curves accumulate from actual sum (`_bridged_forecast_cumulative_series` in `ui/charts.py`); metrics BL target / optimized / savings unchanged horizon SA₀→SA₂; tests `test_bridged_forecast_cumulative_continues_from_history`, `test_chart2_prognose_bridges_at_history_boundary`
- [x] **Version 1.21.4** — patch bump



### UI menu structure & recommendation mode manual appliances (2026-07-07)

Spec: [docs/dev/done/ui-menu-structure.md](docs/dev/done/ui-menu-structure.md). `### Version 1.21` feature block completed together.

- [x] **Menu structure as sidebar replacement** (`st.navigation` + `st.Page`) — `app.py` as router, `ui/pages/`; existing modes (cockpit, backtesting, price forecast dev) as pages (env gating preserved); raw JSON config editor (`page_config.py`); mockup pages (scenario editor, house configurator, consumer analysis); backtesting/price forecast controls moved to page body
- [x] **Recommendation mode manual appliances** — `optimizer/appliance_recommendation.py` (pure start-time/cost logic: ranking of start hours in 6-h horizon by grid import cost, 1–5 stars linear, savings vs. immediate) + tests
- [x] `ui/pages/page_devices.py` — per appliance (washing machine, dryer, dishwasher) rated power + runtime → start-time recommendation; advisory only, no Loxone switch signal
- [x] **Config** `appliances` **block** — `config.get_appliances()` + normalization, schema + `config.example.json`; `default_power_kw` as rated power for cost evaluation (required for `power_source=loxone`), `loxone_power_name` reserved for later adaptation algo
- [x] **Version 1.21.0** — minor bump



### Optimize Swimspa filter usage (2026-07-07)

Spec: [docs/spec/swimspa-filter.md](docs/spec/swimspa-filter.md). Goal: cost-optimal **supplementary** filter runtime; `Sollstunden` (debt in h) long-term → 0; native duty cycle independent.

- [x] **Code phases 1–4** — `loxone_remaining_hours`, `filter_context`/MILP blocking, schema/`config.example.json`/docs, live parser + `verify_swimspa_filter_live` / `patch_swimspa_filter_config`
- [x] **Live acceptance (user)** — prod `config.json` patched; formats `filter1hour` and `Sollstunden` confirmed on miniserver
- [x] **Deviation rules SwimSpa filter (S8–S10)** — `swimspa_filter_should_run_missing`, `swimspa_filter_runs_unexpectedly` (only outside native window), `swimspa_filter_over_nominal`; new predicates `power_ist_without_soll`, `slot_outside_native_filter_window`, `ist_power_above_nominal`; native window logged as `filter_contexts` in `optimization_history.jsonl`
- [x] **Actual power heating/filtering checked separately + case B corrected** — separate Loxone markers/keys/charts confirmed; heating meter `Earnie_Swim-Spa-P_act` measures incl. filter → `subtract_consumer_ids` subtracts filter share from heating actual (no double counting in `flex_sum_kw`/`baseload_kw`); `patch_swimspa_filter_config` extended idempotently. Follow-up (historical logs / Loxone separation) as separate 1.+1 item
- [x] **Version 1.20.0** — minor bump



### Chart 1 forecast saturation PV & baseload (2026-07-07)

- [x] **Chart 1: forecast saturation reduced for PV and baseload too** — zone logic extended from flex consumers to `PV` and `Grundlast`; history remains fully saturated, neutral and green area use same saturation factor as flex; regression tests for color derivation and zone-specific buckets added
- [x] **Version 1.19.0** — minor bump



### Debug dump preparatory work (2026-07-07)

- [x] **Reproducible repro inputs for debug dumps centralized** — shared collection in `runtime_store/debug_dump_inputs.py`; `chart_debug_capture` and `archive_prod_dump` now secure active `config.json`, `deviation_rules.json`, optional `local_settings.json`, relevant env overrides and resolved paths
- [x] **Explicitly configured additional files included in dumps** — price forecast model (`forecast_model_path`) and `cons_data_hourly.csv` archived when active reference present; focused tests for ZIP and prod dump archive added



### Consumer colors P1 — NAS deploy cleanup (2026-07-07)

- [x] **Reverted temporary local** `chart_color_index` **test** — local `config/config.json` removed; NAS path `ENERGY_OPTIMIZER_CONFIG_PATH` per `.env.example` authoritative again, local override no longer active



### Consumer colors P2 — Zone-dependent saturation (2026-07-07)

- [x] **P2 — Zone-dependent saturation (Chart 1 flex bars only)** — history full palette; neutral + forecast shared `CONSUMER_CHART_SATURATION_MUTED` (0.6); slot → zone via `chart_zone_kind_for_slot_start`; flex color per slot/bucket; legend full color (`legendonly`); Sankey unchanged; tests and `docs/ui/charts.md`
- [x] **Version 1.18.0** — minor bump



### Consumer colors P1 — 8-color palette & chart_color_index (2026-07-07)

- [x] **P1 — Fixed 8-color palette &** `chart_color_index` — `CONSUMER_PALETTE` (H 260→40, S=90, L=50); `color_from_hsl()` with optional alpha; base colors as `_HSL_`* + `_ALPHA_`*; `consumer_chart_color()` central for Chart 1 (`chart_flow_balance`) and Sankey; `chart_color` removed, schema/`config.example.json` with indices SwimSpa=0, E-Auto=2, Wärmepumpe=7; tests and `docs/ui/charts.md`



### Centralize chart colors (2026-07-07)

- [x] **Phases 1–4** `ui/chart_colors.py` — single source for zones, energy balance bars, Chart 1 lines/overlays, Chart 2 costs, Sankey, flex palette, legacy control-command bars; `chart_flow_balance`, `charts`, `sankey`, `sankey_produktiv`, `planning_window` consumers only
- [x] **Version 1.17.3** — patch bump



### Bugfix Chart 1 zones & bar X (2026-07-07)

- [x] **Bars invisible in green zone SA₀→SA₁** — `ChartSlotAxis.at()` ignored `slice(start, end)`; extrapolation bars landed at chart start instead of green zone (`ui/charts.py`); regression tests
- [x] **Zone colors gray/green centralized & more contrast** — `ui/chart_colors.py` with `hsl`, `blend_hsl`, `rgba_from_hsl`, `CHART_ZONE_HISTORY_FILL`, `CHART_ZONE_FORECAST_FILL`; forecast deliberately yellow-green (H≠120) instead of material green; connection `data/planning_window.py`
- [x] **Version 1.17.2** — patch bump (two bugfixes)



### Chart 1 up/down energy balance (2026-07-06)

- [x] **Better visualize discharge lock** — yellow-black striped band below SoC (`ui/charts.py`)
- [x] **Up/down bars** instead of battery/consumer bars — basis `ui/chart_flow_balance.py`, `ui/flow_balance_allocate.py`
- [x] **Color palette grid & battery** — grid blue, battery flows muted (HSL in `ui/chart_colors.py`); scenarios A–I, `docs/ui/charts.md`
- [x] **PV surplus & full battery** — SoC edge correction (MILP); scenario I; prod log: actual `battery_kw` from `consumption_snapshot` → `Ist Batterie-Leistung (kW)` (`runtime_store/history_timeline.py`)
- [x] **Grid and baseload lines removed** — display only via up/down bars (`ui/charts.py`)
- [x] **SoC timeline** — shared color optimized + “SoC BL Ziel” via `_HSL_SOC` in `ui/chart_colors.py`
- [x] **Version 1.17.0** — minor bump after completed Version-0.+1 block Chart 1



### UI S-2 cold start & price forecast logging (2026-07-06)

- [x] **Initial UI rendering (SA-2-SA)** — cold start ~112 s → ~7 s: archive EU feature fetch for future slots skipped (`_archive_covers_slot_range` in `data/price_forecast_live.py`); JSONL in-memory cache in `runtime_store/optimization_history.py`
- [x] **Terminal warning EU features (Open-Meteo 400)** — `print()` replaced by `logging`; expected live case only `logger.debug`, API errors as compact `logger.warning` without full URL



### Price forecast (EU weather & generation) epic completed (2026-07-06)

- [x] **Price forecast (EU weather & generation):** correlation model for green zone (no day-ahead until SA₂) instead of mirroring — wind + solar at EU level; spec [price-forecast-renewables.md](docs/spec/price-forecast-renewables.md)
- [x] **Phase 0:** scope defined (AT day-ahead, EU countries, OLS, acceptance)
- [x] **Phase 1:** dataset pipeline `data/eu_market_features.py`, `scripts/build_price_training_dataset.py`, `data/cache/price_training_*.csv`
- [x] **Phase 2:** OLS + walk-forward; **extended** (+ EU load/residual load) via `enrich_price_training_dataset` + `compare_price_forecast_features`; bias correction (non-peak P90)
- [x] **Phase 3:** UI eval (`ui/price_forecast.py`); live in `resolve_market_slots` (`data/price_forecast_live.py`, `data/profile_manager.py`); `config.market_prices.missing_price_strategy` (`mirror`  `forecast`, default **forecast**)
- [x] **Annual comparison 2025:** `run_price_strategy_backtests` (333 windows, `sunset_window`, all scenarios); report `backtesting_logs/price_strategy_compare/comparison.md` — forecast vs. mirroring marginal (±0.1–0.6%), go-live with `forecast`
- [x] **Rolling bias recalibration** — deferred; static P90 bias correction at training remains active for live



### Price forecast backtesting annual comparison (2026-07-06)

- [x] **Backtesting annual comparison (infrastructure):** green zone in `sunset_window` — day-ahead cutoff, mirroring vs. OLS (`data/backtesting_prices.py`, `resolve_market_slots` forecast); `--price-strategy` / `--output-dir` in `run_backtesting`; orchestrator `run_price_strategy_backtests` + `compare_price_strategy_backtests`; tests



### Price forecast UI via config.json (2026-07-06)

- [x] **Extra UI page for price model activatable via config.json** — `ui.price_forecast_page_enabled` (default: `false`); without `ENERGY_OPTIMIZER_UI_MODES` only Sunset-2-Sunset + backtesting, price forecast (dev) optional via config; env variable still takes precedence (`ui/mode_selector.py`, `config.py`, schema/example, tests `tests/test_mode_selector.py`)



### Bugfixes: test fixtures & heat pump (2026-07-06)

- [x] **Test data executable on fresh checkout** — prod dump fixtures added (`.gitignore` exceptions, `scripts/complete_prod_dump_fixtures.py`), thermal CSV fixtures (`tests/fixtures/thermal/`), smoke tests on `tests/fixtures/historical/cons_data_hourly.csv`; **551 passed** (commit `71a4764`)
- [x] **Heat pump restored in** `config.json` — entry `flexible_consumers[id=waermepumpe]` from production backup (`config_back.json`, commit `3b7fa1c`): `Earnie_WP_Freigabe`, `Earnie_WP_P_act`, historical daily target, `chart_color` `#ff9800`; also `config.example.json`
- [x] **Target/actual notice: heat pump did not start** — rule `waermepumpe_enable_no_start` (category notice), docs/scenario S5, seed script and tests



### Chart 1 stacked flex consumers (2026-07-06)

- [x] **Chart 1: variable flex consumers as stacked negative bars** — one bar per slot (same X position as battery, `barmode=overlay`, stacking via `base`); sort by horizon energy SA₀…SA₂, cache until next SA₀; colors via `flexible_consumers.chart_color` in `config.json`; tests `tests/test_chart_consumer_stack.py` (`ui/charts.py`, `config.py`)
- [x] **Version 1.15.0** — minor bump after completed Version-0.+1 item; rule `.cursor/rules/versioning.mdc` (minor vs. patch)



### UI S-2 nav & help icons mobile (2026-07-06)

- [x] **Compact S-2 navigation** — `←` / `Heute` / calendar icon / `→` in `st.container(horizontal=True)`; date selection in popover (only SA₀ days with log); `Heute` and cycle logic in `ui/s2_navigation.py`, `ui/chart_context.py`, `ui/history_navigation.py`
- [x] **Mini help icons** — material icon + tertiary popover instead of `?` button; horizontal layout without extra row on mobile; CSS in `ui/styles.py` (`inject_help_hint_css`); `ui/help_hint.py`, `ui/countdown.py`



### Discharge lock: grid trickle charging (2026-07-06)

- [x] **Bugfix: SOC rose when holding from grid (05.07. ~22–23 h)** — prod log (`runtime-prod/runtime.zip`): PV=0, `battery_plan_kw=0`, measured ~0.2 kW charging + grid import; cause `target_soc_percent=100` with Huawei control command 1; fix: at `MODE_ENTLADESPERRE` `target_soc = current_soc` (`optimizer/milp.py`); test `test_entladesperre_target_soc_matches_current_soc`



### Migration script removed (2026-07-05)

- [x] `scripts.migrate_persist_layout` **deleted** — one-time migration config/ + runtime/ no longer needed; script, test, `ernie-migrate-layout` entrypoint and doc references removed



### Chart 1 target/actual markers NAS (2026-07-05)

- [x] **Bugfix: Chart 1 target/actual markers missing on NAS despite same** `optimization_history.jsonl` — cause missing `config/deviation_rules.json` (and templates) on NAS config volume; without rules file `deviation_timeline` suppresses all events silently. Fix: files manually copied to NAS; bootstrap creates `deviation_rules.example.json`, `deviation_rules.schema.json` and `deviation_rules.json` from image template; Dockerfile `share/config/` extended (`runtime_store/bootstrap.py`)



### UI S-2 Chart 2 savings text (2026-07-05)

- [x] **UI S-2 Chart 2: savings text annotations in both segments** — `show_cost_summary` no longer tied to `not split_mode`; annotations (`BL Ziel`, `Optimiert`, `Ersparnis`) in SA₀→SA₁ and SA₁→SA₂ with full-horizon values from `_cost_totals_from_savings`; test `test_chart2_s2_split_mode_shows_cost_summary_annotations` (`ui/charts.py`)



### Chart 2 actual cost log area (2026-07-05)

- [x] **Bugfix Chart 2: actual cost in gray log area constantly 0 €** — `entry_to_chart_row` uses `consumption_snapshot.grid_kw` for grid import when snapshot present instead of target balance (PV + `battery_plan_kw`); `_netzbezug_kw_from_entry` in `runtime_store/history_timeline.py`; regression test `test_build_chart_history_uses_snapshot_grid_kw_for_slot_cost`



### UI Chart 1 SoC bridge log/MILP (2026-07-05)

- [x] **Bugfix Chart 1: SoC gap gray → neutral (log/MILP boundary)** — `add_optimized_soc_trace` incorrectly disabled `bridge_left` at `history_slot_count`; bridge point like neutral→green active again; test `test_soc_trace_bridges_at_history_boundary` (`ui/charts.py`)



### UI Chart PV time base (2026-07-05)

- [x] **PV power correctly positioned on X-axis** — cause: smooth linear interpolation between slot starts let PV rise before sunrise (raw hourly data from slot start was plausible); fix: PV anchors at **slot center** (`_LINE_ANCHOR_SLOT_CENTER` in `_add_pv_trace`, `ui/charts.py`); regression test `test_chart1_pv_center_anchor_avoids_early_morning_ramp`; S-2 nav between Chart 1/2 extracted from fragment (`StreamlitFragmentWidgetsNotAllowedOutsideError`, `ui/live_mode.py`)



### UI fragment refresh (2026-07-05)

- [x] **UI: fragment refresh separately configurable** — `ui/fragment_refresh.py`; Charts 1+2 **60 s** (`ui/live_mode.py`), Sankey/countdown **10 s** (`ui/sankey.py`, `ui/countdown.py`); optional `config.json` → `ui.fragment_refresh_charts_sec` / `ui.fragment_refresh_status_sec` or env `ENERGY_OPTIMIZER_UI_FRAGMENT_CHARTS_SEC` / `ENERGY_OPTIMIZER_UI_FRAGMENT_STATUS_SEC`; schema/example, tests `tests/test_fragment_refresh.py`



### Historical tests & energy balance (2026-07-05)

- [x] **stderr warning** `Keine historischen Daten in cons_data_hourly` — `profile_manager.get_historical_day_data`: `cons_data_hourly.csv` missing or empty (date in message = requested day, typically today via `consumer_targets` in live UI); output via `print()` → stderr; fallback baseload 0.5 kW/h, consumer daily targets 0; remedy: maintain `runtime/cons_data_hourly.csv` (`main.py` or `scripts/generate_cons_data.py`)
- [x] **Pre-commit / validate historical test suite** — catch-up after `--no-verify` (commit `8721df2`): `pytest tests` incl. 25× `test_historical_24h_consistency` green; pre-commit hook usable again for code changes
- [x] `runtime/cons_data_hourly.csv` regenerated from Loxone logs (≥12 months retention)
- [x] **Test fixture** `tests/fixtures/historical/cons_data_hourly.csv` + `scripts/extract_historical_fixtures.py` (isolated from runtime)
- [x] `test_historical_24h_consistency.py`**:** fixture path, parametrized consistency runs green
- [x] **Bugfix** `simulate_horizon`: `finalize_chart_row_energy` after each hour — grid import consistent with rounded flex columns (Δ 8 W on case `2026-03-21_high_pv`)
- [x] **Test suite inventory (optional / env, no blocker):** Loxone integration (`test_loxone_integration.py`, 5× skip without env), thermal CSV fixtures (`tests/fixtures/thermal/` missing, 2× skip) — deliberately left open unchanged



### UI main.py sync (2026-07-05)

- [x] **Clarify duplicate UI wait time after main.py run**
  - Cause: fixed 60-s phase (`delay`) without `completed_at` check, then up to 120 s grace (`wait_main`) — felt like waiting twice
  - Fix: early exit on sync in current slot; max. 60+30 s wait; UNC read fix in `run_state`; unified UI notice; tests `tests/test_schedule.py`
- [x] **UI: main.py sync faster after run** — fallback **15+15 s** (`optimizer/schedule.py`); display “next sync at latest in X s” instead of full fallback countdown (`sync_ui_countdown_seconds`, `ui/main_py_sync.py`); 15-s poll fragment `poll_main_py_sync_if_pending` + footer (`ui/countdown.py`, `app.py`); config `ui.main_sync_poll_sec` / env `ENERGY_OPTIMIZER_UI_MAIN_SYNC_POLL_SEC`; tests `tests/test_schedule.py`, `tests/test_main_py_sync_ui.py`



### UI Sunset-2-Sunset epic completed (2026-07-05)

- [x] Prod cockpit **Sunset-2-Sunset** (`ENERGY_OPTIMIZER_UI_MODES=sunset2sunset,backtesting`); replaces realtime, historical day, production archive
- [x] Phases 1–3 UI + follow-up layout; phase 4 P4a–P4c (operating modes docs, deployment cross-references, navigation tests); P4d dropped
- [x] Spec [docs/spec/ui-sunset2sunset.md](docs/spec/ui-sunset2sunset.md) **v0.7.0**; app version **1.14.0**

- Follow-ups (standalone in Backlog): target/actual deviation, backtesting recalculation, price mirroring, optional layout/mobile



### UI Sunset-2-Sunset — Phase 4 P4d dropped (2026-07-05)

- [x] **P4d** removed — dedicated missing-slots tests dropped; coverage via existing chart/table tests (spec §6)



### UI Sunset-2-Sunset — Phase 4 P4c navigation tests (2026-07-05)

- [x] **P4c** `tests/test_s2_navigation.py`: `segment_navigation_label`, `max_sunrise_cycle_offset`, `build_live_chart_context` (segment/cycle window, zone_reference, max_cycle ↔ nav); spec §4



### UI Sunset-2-Sunset — Phase 4 P4b deployment & cross-references (2026-07-05)

- [x] **P4b** `docker-compose-synology.yml` confirmed (`sunset2sunset,backtesting`); `betrieb.md`, `container.md`, `docs/README.md`, `charts.md`, `ueberblick.md`, `preise.md`, `batterie-pv.md`; spec status phases 1–3 completed



### UI Sunset-2-Sunset — Phase 4 P4a operating modes docs (2026-07-05)

- [x] **P4a** `docs/ui/betriebsmodi.md` per spec v0.6.2: Sunset-2-Sunset (prod), backtesting (dev); SA₀→SA₁/SA₁→SA₂, navigation, panels, metrics now→SA₂; dropped modes; env var `sunset2sunset,backtesting`



### UI Sunset-2-Sunset — Follow-up layout (2026-07-05)

- [x] **Layout-a** navigation compact between Chart 1 and Chart 2; segment label in Chart 1 heading (`ui/history_navigation.py`, `ui/charts.py`, `ui/simulation_results.py`, `ui/live_mode.py`)
- [x] **Layout-b** help “?” (`ui/help_hint.py`, `st.popover`): zones (Chart 1), Chart 2 actual/forecast, sync wait time, mode scope at page title; version as caption next to title
- [x] **Data basis** expander in footer below separator, before optimization cadence (`ui/countdown.py`, `app.py`)
- [x] **H2/H6/H7** deliberately unchanged (no “current hour” notice; table/energy comparison expanders unchanged)
- [x] Docs: `docs/ui/charts.md`, spec §7.1 in `docs/spec/ui-sunset2sunset.md`



### UI Sunset-2-Sunset — Phase 3 charts & metrics completed (2026-07-05)

- [x] **Phase 3 (P3a–P3d)** — Chart 2 actual/forecast, SA markers, legacy cleanup prod UI, metrics horizon now→SA₂; details in sub-items below



### UI Sunset-2-Sunset — Phase 3 P3d metrics horizon now→SA₂ (2026-07-05)

- [x] **P3d** savings/cost metrics and energy comparison over full matrix (now→SA₂), not chart segment; labels “(24h)” removed; `[:24]` cleaned up for baseload/profile targets (`ui/chart_context.py`, `ui/simulation_results.py`, `ui/charts.py`, `optimizer/targets.py`, `data/consumer_targets.py`); tests `test_horizon_targets.py`, `test_chart_context.py`



### UI Sunset-2-Sunset — Phase 3 P3c legacy paths removed (2026-07-05)

- [x] **P3c** `history_offset_days`, production archive navigation, mode “Historischer Tag” and `render_historical_`* removed from prod UI; S-2 only `render_s2_navigation` (`ui/history_navigation.py`, `ui/live_mode.py`, `app.py`, `ui/mode_selector.py`); `ui/historical.py` deleted; tests `test_mode_selector.py`



### UI Sunset-2-Sunset — Phase 3 P3a Chart 2 actual/forecast (2026-07-05)

- [x] **P3a** Chart 2: “actual so far” (log) and “optimized forecast” (MILP) separated, no bridge at log/MILP boundary; matrix index fix for SA₁→SA₂; matched baseline over full matrix (`ui/chart_context.py`, `ui/charts.py`, `optimizer/simulation.py`); tests `test_chart2_s2_split.py`, `test_chart_context.py`



### UI Sunset-2-Sunset — Phase 3 P3b SA markers (2026-07-05)

- [x] **P3b** vertical markers SA₀/SA₁/SA₂ in chart (anchors only in visible window); **now** only live segment SA₀→SA₁ (`ui/charts.py`, `ui/simulation_results.py`); tests `test_chart_ui_bugs.py`



### UI Sunset-2-Sunset — Chart display (2026-07-05)

- [x] **SOC jumps / missing log slots (spec §6)** — orange vrect in chart and table rows for `SLOT_MISSING`; visible SoC gaps at log/MILP boundary (no false bridge point) and neutral→green (extrap start); no more UTC offset on SoC/price X
- [x] **SoC gap at neutral→green transition** — extrapolated segment without bridge point (`bridge_left` incorrectly disabled for entire MILP); fix: only at log/MILP boundary (`abs_start == history_slot_count`); test `test_soc_trace_bridges_extrapolation_start`
- [x] **No line style/opacity change in green zone** — dotted price line and 50% opacity extrapolated traces removed (marking only green background, spec §5)
- [x] **SoC/price time reference in chart** — Plotly X for SOC and price traces incorrectly created as `datetime64[ns, UTC]` (+2 h offset in CEST, looked like missing lines to axis edge); fix: `_chart_time_series()` in `ui/charts.py`; test `test_soc_and_price_traces_align_with_slot_datetimes`
- [x] **Gray/green zone at X-axis edges** — variable slot duration in `ChartSlotAxis`; zones on display slots (`ui/simulation_results.py`); window edge SA₀/SA₁ via `x_range(range_start=chart.start)`; full gray zone for past cycles (`is_live_segment=False`)
- [x] **15-min → 1-h mixed axis** — price hourly HV step at slot boundaries; bar width per slot (`_bar_widths_ms`); zones/vrect on `display_ctx.slot_datetimes`
- [x] **SU marker removed** — only now + SA (SOC)
- [x] **Tests:** `tests/test_chart_ui_bugs.py`, `tests/test_chart_mixed_resolution_traces.py` (time reference, zones, extrap bridge, mixed axis)



### UI Sunset-2-Sunset — Navigation SA cycles (2026-07-04)

- [x] **Symmetric cycle navigation** — `ui/s2_navigation.py` (pure state logic); `ui/history_navigation.py`: “Vor →” at `cycle_offset > 0` one cycle toward live, at `cycle_offset == 0` switch SA₁→SA₂; cycle back sets segment to SA₀→SA₁ — **in prod fundamentally ok** (2026-07-04)
- [x] **Crash on cycle back fixed** — missing SoC in history window (`TypeError` in `_soc_tail_y_from_row`); baseline SoC from `history_only`; `None`/NaN-safe SoC lines (`ui/charts.py`, `ui/simulation_results.py`)
- [x] **Tests:** `tests/test_s2_navigation.py`, `test_soc_tail_y_returns_none_for_missing_soc`



### Simulation table & data basis UI (2026-07-04)

- [x] **Freeze header and time column** — scrollable HTML table with CSS freeze panes (`ui/simulation_table_view.py`); orange rows via Pandas Styler
- [x] **Data basis notice as expander** — collapsed only production log path, expanded full merge/runtime text
- [x] **Layout:** simulation table directly below chart, before energy comparison
- [x] **Tests:** `test_simulation_results_table`, `test_production_log_source`



### UI Sunset-2-Sunset Phase 2 — fill past (2026-07-04)

- [x] **Data layer v0.6.1:** `build_chart_history`, `build_chart_display_context` — 15-min production log (no hold-forward in live chart), MILP tail (1 h or 15-min target from x:15)
- [x] **Chart + table:** shared merge path (`display_ctx`), target from `consumer_powers_kw`; data basis notice (runtime path, merge status)
- [x] **Simulation results table:** log/MILP mix, data source column, `st.table`, flex kW columns moved forward; orange for missing log slots
- [x] **Chart vs. table gray area:** deviation was display type (`st.dataframe`, column mix-up); `chart_key` for live chart
- [x] **Production log:** `k_push_act`, feed-in compensation and `sofort_laden` in table rows; TZ fix for `completed_at` lookup
- [x] **Tests:** `test_chart_history`, `test_simulation_results_table`, `test_production_log_source`
- [x] **Diagnosis:** `scripts/_diag_swimspa_nas.py` (NAS `optimization_history.jsonl`)



### Dev environment NAS production log (2026-07-04)

- [x] **VS Code launch “Streamlit app.py (NAS Produktiv-Log)”** — `ENERGY_OPTIMIZER_RUNTIME_PATH` and `ENERGY_OPTIMIZER_CONFIG_PATH` to NAS paths (`.vscode/launch.json`)
- [x] **Local production runtime cleaned up** — accidental use of local logs excluded; historical EV baseline test skips without local `cons_data`



### UI Sunset-2-Sunset Phase 1 (2026-07-04)

- [x] **Phase 1 — Mode & window:** `mode_selector`, `app.py`, sidebar without adaptive PV tuning; Sunset-2-Sunset mode in UI
- [x] **Phase 1b — MILP until SA₂ (spec correction):** `compute_planning_window` — horizon end sunrise SA₂; tests and spec adjusted



### Live chart IndexError cumulative costs (2026-07-04)

- [x] **IndexError in production UI fixed** (`_segment_connected_line_xy`, cumulative costs/consumption)
  - Cause: hourly cost lists shorter than sunrise→sunrise chart window (matrix vs. `display_df`)
  - `align_hourly_values_to_chart_slots` in `ui/chart_context.py`; padding in `ui/charts.py`
  - Release **1.13.1**



### Cursor session conclusion (2026-07-04)

- [x] **Automate two-phase session conclusion**
  - Phase 1: maintain `Backlog.md`, commit and push all open changes (ask about local/temporary files)
  - Phase 2: optionally build Docker image and push to ghcr.io (`python -m scripts.build_container --push`)
  - Skill: `.cursor/skills/session-abschluss/SKILL.md`; rule: `.cursor/rules/session-abschluss.mdc`
  - Hook: `docker push` requires explicit confirmation (`.cursor/hooks/approve_docker_push.py`)
  - Trigger: “end session”, “backlog sync”, “commit and push”



### Configuration dev/prod (2026-07-04)

- [x] **Central** `config.json` **addressable via NAS path**
  - Path via `ENERGY_OPTIMIZER_CONFIG_PATH` (in `.env`, see `.env.example`)
  - Fallback unchanged: `config/config.json` → legacy `config.json` in project root
  - Docker/Synology: volume `./config` → `config/config.json` in container
- [x] `loxone_silent_mode` **moved to local file**
  - Machine-specific: `runtime/local_settings.json` (template `runtime/local_settings.example.json`)
  - Optional: `ENERGY_OPTIMIZER_LOCAL_SETTINGS_PATH`; bootstrap creates missing file
  - Removed from central `config.json` / schema / example; remaining key there → clear error message
  - Tests: `tests/test_local_settings.py`



### Sunset planning horizon + SOC_min at sunrise (2026-07-04)

- [x] **Main feature completed** (branch `feature/sunset-planning-horizon`, merged)
  - Spec: [docs/spec/planning-horizon-sunset.md](docs/spec/planning-horizon-sunset.md)
  - Window: now→SA₁ + SA₁→SA₂; hard SOC boundary at next sunrise; then free until SA₂
  - Replaces `battery_end_soc_equals_start` in live operation
  - Backtesting: EV `ready_by_hour` anchor; `--horizon-mode fixed_24h|sunset_window`
  - Decision: **live** `sunset_window`; **backtesting reference** `fixed_24h` (10 kWh dyn. ~779 € vs. sunset ~784 €/yr; earlier sunset advantage was plausibility artifact)
- [x] **Phase 1:** `data/planning_window.py` + tests
- [x] **Phase 2:** generalize matrix/prices/PV, MILP SOC anchor
  - Day-ahead for variable window length (`resolve_market_slots`); aWATTar fetch until SA₂
  - Price mirroring: same time of day, up to 7 days back; aWATTar lookback for mirror sources
  - Timezone alignment planning slots ↔ aWATTar (`Europe/Vienna`)
  - Loxone verify: missing EV completion time only **warning** (not connected)
- [x] **Phase 3:** `main.py`, live simulation — **live run verified 2026-07-04**
- [x] **Phase 4:** UI sunrise→sunrise with zone colors — **verified 2026-07-04** (replaced by epic **UI Sunset-2-Sunset**: SA₀→SA₁/SA₁→SA₂, new zone logic)
  - UI live: sunrise→sunrise; zones gray (past) / neutral (now→SA) / green (remainder)
  - `ui/chart_context.py`: chart window, row alignment, cost sum only over sunrise→sunrise
  - Live navigation ←/→; button **Produktiv-Archiv** for 24h history (Sankey/countdown disabled there)
  - Placeholder slots in chart: NaN-safe helpers in `ui/charts.py`
  - Debug snapshot: `slot_datetime` (pandas Timestamp) JSON-serializable; persist after chart render
  - Sankey **energy flow (live)** unchanged below charts in `app.py`
- [x] **Phase 5:** backtesting comparison fixed_24h vs sunset_window — **completed 2026-07-04**
  - CLI `--horizon-mode`; log field `period.horizon_mode`; backtesting default `fixed_24h`
  - No rolling re-optimization in backtesting (1× MILP per anchor step; spec section 4.2)
  - Sunset path in `simulation/engine.py` (MILP now→SA₂, 24h output/step)
  - Performance: sunset matrix truncated to 24 h before `simulate_horizon` (full SA₂ matrix would be ~36–39 MILP/step)
  - Annual backtest 2025 both modes; plausibility sunset **333/333** after baseload overlay fix
  - **Baseload overlay** in `build_sunset_window_matrix`: 24h `expected_p_act` from step matrix
  - Diagnosis scripts: `scripts/diagnose_sunset_plausibility.py`, `scripts/debug_sunset_matrix_alignment.py`
  - Annual run log: `backtesting_logs/horizon_compare_2025_full_sunset_window_v3.log`
  - Cost comparison: reference 1,195 €; fixed_24h 10 kWh dyn. 779 €; sunset 784 € (savings vs. historical 416 € or 411 €)



### Config cleanup planning horizon (2026-07-04)

- [x] `battery_end_soc_equals_start` **removed** (NAS config, schema, example, `get_battery_params`, test fixtures)
  - Terminal SOC only via `terminal_soc_percent` (backtesting `fixed_24h`) or sunrise anchor (live `sunset_window`)
  - No separate config parameter anymore



### Epic target/actual (2026-07-05)

- [x] **Target/actual deviation in Chart 1** — notice / warning / error icons in gray production log area
  - Spec [docs/spec/soll-ist-abweichung.md](docs/spec/soll-ist-abweichung.md) v0.2 · rules `config/deviation_rules.json`
  - P1–P4: facts, rule engine, slot evaluation, chart markers, scenario catalog S1–S7, [docs/ui/charts.md](docs/ui/charts.md)
  - Dev test: `scripts/seed_deviation_test_log.py`, VS Code launch **Streamlit app.py (Deviation-Test)**



### Consumption history live (2026-07-04)

- [x] **First step** of consumption history in live mode (production archive, 96×15 min) — full integration → epic **UI Sunset-2-Sunset**



### EV MILP (2026-07-04)

- [x] **Hybrid delivery / preset rest:** experimentally discarded (annual backtest 2025)



### Optimization & feed-in (2026-07-03)

- [x] **Battery degradation as penalty factor in MILP objective**
  - `optimizer/battery_wear.py`, config block `battery_wear`; throughput model (2.5 ct/kWh at 5 kWh: 1500 € / 6000 cycles / 50% cycle-related)
  - Annual backtest 2025: ~33 €/yr less net benefit vs. without wear; savings ~416 € (10 kWh dynamic) — parameters **plausible**
- [x] **Monthly fixed feed-in tariffs in backtesting**
  - `fixed_monthly_feed_in_rates` in `backtesting_scenarios.json`; tariff = calendar month of hour
  - `get_backtesting_feed_in_settings()`; edge window Dec 2024 added
  - Annual backtest 2025: **333/333** plausibility (log `backtesting_logs/backtesting_2025_wear_monthly.log`)



### Backtesting & CBC (2026-07-03)

- [x] **Baseload validation (backtesting)**
  - `simulation/baseload_validation.py`; separate plausibility baseload + flex + total
  - `scripts/analyze_plausibility_failures.py`
- [x] **EV MILP (phases 1–4)**
  - Phases 1–4: logged_day binary, preset, live mode A/B, tie-break; config `eauto_milp`
  - Annual backtest 2025 (phases 3+4): 303/333 plausibility, 10 kWh dynamic 774.51 € (`backtesting_logs/backtesting_2025_phase34.log`)
- [x] **UTF-8 for backtesting logs**
- [x] **CBC two-stage solver** (`cbc_gap_rel`, strict timeout 3 s)
- [x] **CBC gap diagnosis** (`scripts/bench_cbc_gaps.py`, `analyze_benchmark_window.py`)
- [x] **Backtesting urgent / time window** (logged_day without urgent constraint)
- [x] `run_backtesting` **parallelized** (`--workers N`)
- [x] **Dynamic feed-in (Awattar SUNNY Spot)** + MILP `k_push_act` from matrix



### Bugfix EV config-path Ist-SOC ignored when plugged in (2026-07-29)

- [x] Config-path (`daily_target_source=config`) used `daily_rest_soc` for energy even while plugged in with 99% Ist-SOC → planned full charge. Fix: `_config_path_apply_live_ist_soc` overrides `target_kwh` with live Ist-SOC when plugged. Test: `test_charging_context.py::TestPluggedInChargeComplete::test_config_path_plugged_in_uses_ist_soc_not_daily_rest`.

### Older milestones (brief)

- [x] MILP optimization (PV/consumption), NAS deployment, Sankey/UI, versioning
- [x] Flexible consumers (EV, SwimSpa, HP), historical simulation, 24 h test suite
- [x] EV: variable power, PV follow, event trigger, SOFORT-LADEN, Loxone debug
- [x] Charts (savings, feed-in), silent mode, 24h horizon, refactoring
- [x] Thermal models (Swim-Spa prio1, HP indirect), dynamic feed-in (preliminary stage)
- [x] Packaging 7a–7d (pyproject, bootstrap, build, Streamlit external)