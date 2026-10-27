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

- [ ] **Regression: possible private case from the issue #50 reporter:** the reporter's configuration (HA backend, fixed import tariff + spot-indexed export, Netznutzung) is a typical constellation that the public cases did not cover. Ask for an anonymised config/debug dump (question list in the private business backlog); if it arrives, intake it as a private L1 case (`python -m scripts.run_regression --intake DUMP.zip --id REG-50-<slug> --private`, repo `Earnie-regression-private`). Meanwhile public L2 case `REG-S-gross-tariff-netznutzung` pins the VAT-on-Netznutzung rule (k_act 18 ct = 12 + 5 × 1.2).

- [ ] **Issue #50 / 1 — `settlement_fee_cent_kwh` ignored on `fixed_cent` / `monthly_table`:** committed in `3acd09ac` (no version bump): one load warning per tariff when the fee is non-zero on these types, pointing at `netznutzung` in the house profile (`house_config/tariffs_store.py`, `_warn_ignored_settlement_fee`); the tariff UI does not expose the field. Tests: `tests/test_tariff_settlement_fee_warning.py`. **Pending:** live check that the warning shows once in the daemon log for a fixed tariff with a fee.
- [ ] **Issue #50 / 1b — VAT on the net `netznutzung` for gross import tariffs:** committed in `3acd09ac` (no version bump): grid fee gets `vat_percent` on gross tariffs (`data/tariff_pricing.py`, `grid_fee_on_tariff_basis`), same rule in the SE invoice breakout (`simulation/se_invoice_netznutzung.py`), user-fixed import gets the land VAT (`apply_land_vat_to_user_fixed_import`), warning for gross import tariffs without `vat_percent`, `share/config/tariffs.example.json` completed. Tests in `tests/test_tariff_pricing.py`, `tests/test_user_fixed_tariffs.py`, `tests/test_monthly_fees.py`; public L2 case `REG-S-gross-tariff-netznutzung` (`1472fa17`). Private regression cases not run yet. Follow-up VAT model: feature item in `Backlog.md` (Version 2.+1). **Pending:** run the private golden-master cases; live check of the import price on a gross catalog tariff (e.g. 12 ct gross + 9.08 ct net grid fee → 22.896 ct at 20 % VAT).
- [ ] **Issue #50 / 3 — "Jetzt neu berechnen" button on the Optimierer-Dienst page:** committed in `b8af316c`: posts the existing Request-Optimize route to the local daemon; enabled only while the daemon runs and a plan-input file is newer than the last finished run (`runtime_store/optimize_request.py`, `ui/pages/page_daemon.py`). Tests: `tests/test_optimize_request.py`. **Pending:** live check (Docker + local) that the button triggers a run and disables itself afterwards.
- [ ] **Issue #50 (2.7 migration, GitHub #56) — leftover 2.6 `ehal.ha.sign` flips push values twice:** `ehal.ha.sign` stays a valid 2.7 option (the carrier YAML converts units, not signs), so there is no blanket removal. Migration step `dm4.ha_sign` (from model 3, HA backend, non-empty `sign`) asks keep/remove; removing leaves a to-do to check Live-Lesen (`e2044c7b`, PR #65). Live-Lesen now shows pushed values after `sign` with Detail "Vorzeichen gedreht (ehal.ha.sign: negate)"; Live-Lesen and the live read path share `push_sign_mode` / `apply_push_sign` (`integrations/ha_push_read.py`, `ui/loxone_debug.py`, `ui/loxone_debug_rows.py`; commit `4befbb27`). Tests: `tests/test_migration_registry.py` (fixture `v3_ha_sign`), `tests/test_loxone_debug.py`, `tests/test_ha_push_read.py`. **Pending:** wizard question with a 2.6 HA pack; on an HA install with `negate`, Live-Lesen and the live power line agree.
- [ ] **Loxone export: strip scheme from the Earnie host field:** committed in `ee27503e` (no version bump): `normalize_export_host` (`ehal/signal_export.py`) strips a pasted `http(s)://` and trailing `/` and fails loud on a port or path; used by the Loxone VO/VI export (`ui/ehal_signal_list.py`) and the HA YAML download (`ui/ha_carrier_download.py`), with a caption when the address was shortened. Tests in `tests/test_ehal_signal_list.py`. **Pending:** check the export form in the UI with a pasted browser address.
- [ ] **[GitHub #59](https://github.com/JochenTCC/Earnie/issues/59) — EU power data retry loop without failure cache:** committed in `bcb064f9` (PR #65): connection errors and timeouts raise `ApiUnreachableError` at the first attempt, `fetch_eu_power_hourly` stops instead of asking the remaining countries, and a failed live feature load is paused for one hour per mode (`data/eu_market_features.py`, `data/price_forecast_live.py`). Tests: `tests/test_eu_market_features.py`, `tests/test_price_forecast_live.py`. **Pending:** live check with energy-charts unreachable (cycle stays short, heartbeat fresh). **Still open:** config option to switch the EU features off (reporter's request) — decide whether it is needed now that failures are cached.
- [ ] **[GitHub #60](https://github.com/JochenTCC/Earnie/issues/60) — HA YAML package:** committed in `3c6e9270` + `b6b3b173` (PR #65): the export section points to the YAML package (stale P5c hint gone), `input_number` targets use `input_number.set_value`, and the package contains the watchdog `earnie_watchdog_release_force` (status sensor unavailable for 300 s → active power 0, or `huawei_solar.stop_forcible_charge` with `ha_ess_force`; `ha_carrier_yaml_gen --watchdog-s`, 0 = off). Tests: `tests/test_ha_carrier_yaml_gen.py`, `tests/apptest/test_persist_signal_list_apptest.py`. **Pending:** check on a real HA install (input_number target, watchdog after stopping Earnie).
- [ ] **[GitHub #61](https://github.com/JochenTCC/Earnie/issues/61) — Config migration assistant hints:** committed in `ac21bdc6`, `611ed38c`, `7f31aed7` (PR #65): the wizard says how it assigned the PV systems (also on the 2.6 path) and when `main.py` starts, starts `main.py` right after a successful migration when auto start is on, and shows the migration report after the run. Tests: `tests/apptest/test_page_config_migration_apptest.py`. **Pending:** run the wizard on a 2.6 pack with standalone inverters (Docker, auto start on).


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Open-Meteo forecast calls also get one fixed UTC offset (found 2026-10-25, same cause as the archive fix):** the forecast endpoint answers `timezone=<zone>` with ONE `utc_offset_seconds` for the whole response (checked: 48 hourly rows for a 25 h DST day), so within +-16 days of a clock change the hours on the other side of the change are 1 h off. Affected: `data/eu_market_features.py` (`_fetch_open_meteo_forecast_*`, price-forecast features) and `data/outdoor_forecast.py` (`timezone=auto`, live outdoor temperature / PV forecast). **Next:** request `timezone=UTC` and convert like the archive (`utc_hourly_index_to_local_naive`); mind the shadow recorder keys (`feed_key` hashes the params, so recorded payloads would not replay).
- [ ] **Frozen climate test fixtures carry the old fixed-offset alignment (found 2026-10-25):** the frozen climate fixtures under `tests/` were recorded before the UTC fix; their stamps are shifted by the UTC offset of the recording day. Tests only need them to be consistent, but re-recording changes the input fingerprint and thus the golden cases (`EARNIE_REGRESSION_RECORD_CLIMATE=1`, then `--update-golden` after `regression-triage`). Decide when to re-record.


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Set default "Temperaturabsenkung" in annual-rc to 2.5°C
- [ ] Review and modify text in SE review pop-up dialogue


## Document Review Findings (Do not remove this chapter — even if empty)

