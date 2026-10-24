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

- [ ] **Recorder replay fails offline for installations with an EV `get_evcs_limit_soc` binding:** fixed in `runtime_store/cycle_recorder.py` + `runtime_store/recorder_replay.py` (no version bump): the recorder now stores the resolved limit SoC per EV in `start_state.ev_limit_soc_percent`; replay serves it for the bound marker and fails loud (`ValueError`) for cycles recorded without it. Tests in `tests/test_recorder_replay.py`. **Pending:** old cycles (e.g. the productive-NAS dump) stay unreplayable — verify with a fresh dump from the NAS (`--intake ... --update-golden`).


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **CI job `ui-e2e` is red on every run (found 2026-10-24):** `tests/apptest/e2e/test_smoke.py::test_house_config_first_edit_after_open_is_kept` fails in the GitHub runner at the first `_wait_until_idle` (line 143): `stStatusWidget` stays present for 60 s. It passes locally (Windows, Streamlit 1.66.0, page idle after ~5 s), and it has never been green in CI since the workflow was added (2026-10-22; CI installs the latest Streamlit, currently 1.66.1). The Playwright trace (artifact `playwright-traces`) shows the house-config page rendered but the status stuck on `CONNECTING`: the browser first asks `/house-config/_stcore/health` (404), 114 ms later `/_stcore/health` answers 200 and the WebSocket connects (101). Cause still unknown (script blocked on the server vs. frontend connection state). Next steps: (1) run the test locally against Streamlit 1.66.1 in an isolated environment to check a version regression; (2) print the Streamlit server output on failure in `tests/apptest/e2e/conftest.py` (`AppServer`) so CI shows what the script does; (3) if it is the deep-link start, open `/` first and navigate to the page by click; (4) then decide whether the wait helper or the test needs a CI-specific change. Until fixed the failing check does not block merges (not a required check).
Found by the HA testbed baseline run (2026-10-21; evidence and finding ids F1–F18 in [`docs/dev/ha-contract-testbed.md`](../docs/dev/ha-contract-testbed.md) §3a):


Found by the first live run of the bench (2026-10-22; finding ids L1–L13 in the same doc, § 3f):

- [ ] **Live cycle spins without an SoC (L12):** with no `ess.<id>.sens_ess_soc` in the push inbox every cycle aborts (`Optimierung abgebrochen: Kein Zugriff auf EHAL SoC`) and the scheduler plans the next run "in 0 s" again: ~900 cycles and ~950 ERROR lines in 20 minutes until HA pushed the SoC. Add a backoff (no faster than the push interval) and a "waiting for SoC" message instead of an ERROR per cycle; also `Durchlauf erfolgreich beendet` is logged for aborted cycles.
- [ ] **Carrier skip message names the wrong cause (L13):** `integrations/ha_carrier_yaml.py` logs `unknown or incompatible unit_of_measurement … (need numeric)` when the published setpoint value is not numeric; the generated template never reads the unit for that decision. Fix the wording (+ test on the YAML).
- [ ] **`set_ess_mode` skipped for activation-only HA bindings (L9, question first):** `HaWriteMixin._write_ess_setpoints` tests `not self.cfg.entities.get("set_ess_mode")` (value), the push bindings are empty activation flags, so the mode is never published. Decide whether the mode belongs to the YAML (`ha_ess_force`) or should be published like the export limit (fixed to a key-presence test in the live run).
- [ ] **EHAL-Com Schreibtest: the expander closes and ticked rows reset on the 10 s refresh (B2):** the table fragment re-renders every ~10 s (`ui/fragment_refresh.py`); an open `Schreibtest` expander is collapsed again (`details.open=false`) and the `Senden` ticks are lost, so a value can hardly be sent by hand and not at all by automation. Keep the expander state and the row selection in `st.session_state` (skill `streamlit-ui-state`) or move the Schreibtest out of the refreshing fragment.
- [ ] **UI reports `Auto-Start OK` although the daemon can die right after (B3, split from F2):** `Streamlit maybe_auto_start` prints `main.py Auto-Start OK` right after the spawn; a startup crash (F2) is then only visible in the terminal / `earnie.log`. Check after the spawn that the daemon is alive (e.g. the lock / the listener) before reporting OK.
- [ ] **Konfiguration: `Neu laden (Datei)` raises an exception (found 2026-10-22, reproduced with AppTest):** `ui/pages/page_config.py::_render_editor` assigns `st.session_state["config_json_editor"]` in the button branch, after the `st.text_area` with that key was instantiated, so Streamlit raises `StreamlitWidgetAlreadyInstantiatedError` and the editor is never reset to the file content. Move the reload into an `on_click` callback (skill `streamlit-ui-state`) and add an AppTest regression (edit text → `Neu laden (Datei)` → no exception, editor equals file).
- [ ] **HA backend does not publish `set_evcs_mode` (B4, split from B1, from code reading, not verified live):** the HA cycle writes the EV current through `write_evcs_max_current_from_consumers` (current only); the mode (off / pv / now) is produced only by the flex path (`_evcs_current_output_values`, `_immediate_skip_output_values` in `integrations/loxone_writes.py`) that the HA branch does not call for EVs, although `docs/ui/ehal-com.md` lists `evcs.<id>.set_evcs_mode` as a write field and the Schreibtest offers it. Decide whether the HA contract needs the mode and publish it next to the current (no second current).

Findings from the viability study (house generator and offline runs, 2026-10-23/24; code in `studies/viability` and `studies/poc_cloud`).

- [ ] **Example pack is inconsistent and outdated:** `share/config/house_profiles.example.json` (`example_efh`) declares `annual_kwh` 4500, but its consumers sum to about 18.7 MWh/a, so `scripts.generate_cons_data` aborts with `BaseloadOverAllocatedError`. The manual appliances `waschmaschine` and `trockner` use `appliance_recommendation.power_source: "loxone"` without `loxone_inputs.power_name`, which fails in `house_config/profiles_consumers.py` (`_normalize_earnie_role`). The example pack also needs a config migration before use (`dm4.required_signal_activation`, `dm4.consumer_flex_bindings`, `dm4.se_conf_defaults`). Fix the examples (consistent kWh, `power_source: "manual"`, migrated shape) and add a test that loads every `share/config/*.example.json` end to end.
- [ ] **Automatic `own_reference` ignores the battery:** `default_own_reference` (`simulation/reference_costs.py`) shares a reference by a tariff + `pv_kwp` fingerprint. Scenarios that differ in battery size (or have no battery) or in PV layout silently reuse `ref:<live>`, so "optimised minus reference" mixes the hardware effect with the optimisation effect (seen with `no_battery`, `battery_10kwh`, `pv_east_west`). Include batteries and PV layout in the fingerprint, or warn/fail loud when a reference is shared. Studies set `own_reference: true` explicitly.
- [ ] **Monthly tariff table must reach one day before the period:** the sunrise-window horizon starts on the last day of the previous year (2024-12-31 for a run from 2025-01-01). `lookup_monthly_cent` (`data/tariff_pricing.py`) then raises "Kein Monatseintrag für 2024-12 …" for `monthly_table` tariffs that start in January (catalogue `at_vkw_strom_duo` starts 2025-01); the documented fallbacks (same month prior year, previous month) do not help. Make catalogue and window handling consistent (extend the catalogue or define the fallback explicitly), no silent default.
- [ ] **Backtesting `price_source: csv` hard-codes the zone column:** `_prepare_energy_charts_prices` (`data/data_loader.py`) reads only the column `Day Ahead Auktion (DE-LU)`, so AT or CH prices must be written under a DE-LU header, and `market_zone` is ignored for csv. Detect the price column (or derive it from the zone) so the zone stays visible in the data.
- [ ] **Profiles without controllable consumers get generic synthetic consumption:** `scripts/generate_cons_data.py` (`build_synthetic`) uses the generic baseload curve when a profile has no consumers and ignores `annual_kwh` (a 3500 kWh/a profile yields 4768 kWh/a; the backtest warns "+55.9 %"). Scale to the profile's `annual_kwh`, or use the profile path for every profile.
- [ ] **Open-Meteo cache key changes daily for the current year:** `build_open_meteo_climate_bundle` caps the end date at "yesterday" (`_cap_inclusive_end`) and `open_meteo_cache_path` embeds that end date, so a frozen bundle for the current year never matches on another day. Offline studies need a rename shim (`studies/poc_cloud/run_poc.py`, `_install_weather_cache`). Allow an explicit pinned as-of date (fail loud on a miss) or key the cache by year only.
- [ ] **Duo 2025 monthly rates look like placeholders:** `share/config/tariffs.json` `at_vkw_strom_duo` has identical monthly values for 2025 and 2026 (9.40 / 9.15 ct net). Verify against the VKW price sheets of 2025; the baseline cost of the viability study depends on it.
- [ ] **Offline runs write a usage ping and flood the log:** a backtest run writes `runtime/usage_ping.json` (`consent: unset`) and logs `EHAL push: no value for 'sens_absent_mode'` for every cycle. Suppress both for `EARNIE_OFFLINE` runs without hiding real errors (decide with the maintainer).
- [ ] **`tests/test_ha_testbed_live.py` fails instead of skipping without a running testbed:** the module skips only when `HA_TESTBED_TOKEN` is unset. With the variable set and no testbed it fails 7 checks and blocks the pre-commit hook. Skip with a reason when the testbed is not reachable.

## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Set default "Temperaturabsenkung" in annual-rc to 2.5°C
- [ ] Review and modify text in SE review pop-up dialogue


## Document Review Findings (Do not remove this chapter — even if empty)
