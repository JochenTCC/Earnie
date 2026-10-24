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
