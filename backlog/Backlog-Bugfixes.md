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

- [ ] **Recorder replay fails offline for installations with an EV `get_evcs_limit_soc` binding:** fixed in `runtime_store/cycle_recorder.py` + `runtime_store/recorder_replay.py` (no version bump): the recorder now stores the resolved limit SoC per EV in `start_state.ev_limit_soc_percent`; replay serves it for the bound marker and fails loud (`ValueError`) for cycles recorded without it. Tests in `tests/test_recorder_replay.py`. **2026-10-28, checked with the NAS debug dump of 2026-10-28 (2.7.0-alpha.8):** the EV part works (cycles from 2026-10-23 on carry `ev_limit_soc_percent`, older ones fail loud), but replay then hit two more gaps, both fixed (no version bump): (1) the thermal daily target reads `fetch_thermal_readings` live, so the recorder now also stores `start_state.thermal_readings` per consumer with enabled `thermal_control` and replay serves them (fails loud without); (2) `_coerce_matrix_datetimes` stripped the UTC offset from the restored matrix while the recorded `open_charging_deadlines` keep it (`TypeError` naive vs aware in `ev_connect_prognosis`; replay only, the live matrix is tz-aware) — replay now keeps the recorded offset. With injected thermal readings, cycles of 2026-10-27/28 replay (`strict_only`); all public golden cases unchanged. **Pending:** deploy to the NAS, then verify with a fresh dump recorded by this version (`--intake ... --update-golden`); cycles up to 2026-10-28 stay unreplayable.

- [ ] **Regression: possible private case from the issue #50 reporter:** the reporter's configuration (HA backend, fixed import tariff + spot-indexed export, Netznutzung) is a typical constellation that the public cases did not cover. Ask for an anonymised config/debug dump (question list in the private business backlog); if it arrives, intake it as a private L1 case (`python -m scripts.run_regression --intake DUMP.zip --id REG-50-<slug> --private`, repo `Earnie-regression-private`). Meanwhile public L2 case `REG-S-gross-tariff-netznutzung` pins the VAT-on-Netznutzung rule (k_act 18 ct = 12 + 5 × 1.2).

- [ ] **Issue #50 (2.7 migration, GitHub #56) — leftover 2.6 `ehal.ha.sign` flips push values twice:** `ehal.ha.sign` stays a valid 2.7 option (the carrier YAML converts units, not signs), so there is no blanket removal. Migration step `dm4.ha_sign` (from model 3, HA backend, non-empty `sign`) asks keep/remove; removing leaves a to-do to check Live-Lesen (`e2044c7b`, PR #65). Live-Lesen now shows pushed values after `sign` with Detail "Vorzeichen gedreht (ehal.ha.sign: negate)"; Live-Lesen and the live read path share `push_sign_mode` / `apply_push_sign` (`integrations/ha_push_read.py`, `ui/loxone_debug.py`, `ui/loxone_debug_rows.py`; commit `4befbb27`). Tests: `tests/test_migration_registry.py` (fixture `v3_ha_sign`), `tests/test_loxone_debug.py`, `tests/test_ha_push_read.py`. The migration question was verified on `main` on 2026-10-24 (see `Backlog-Erledigt.md` on `main`). **Pending:** the Live-Lesen part (`4befbb27`, `release/2.7` only): on an HA install with `negate`, Live-Lesen and the live power line agree.
- [ ] **SE reference (non-optimized) run booked the battery standby twice:** `simulation/reference_costs.py::_reference_window_inputs` added `reference_standby_power_kw` to the reference load twice (and the function was defined twice), while the MILP adds the standby once per slot. Szenario-Explorer references with storage showed one standby too much in import cost and Jahres Verbrauch (e.g. 26 W ≈ 228 kWh/a). Cause: duplicated by the release commit `28f756e9` (v2.7.0-alpha.8). Fix `f3b752cc` (PR #73, closed unmerged on 2026-10-27; on `main` via #74) cherry-picked to `release/2.7` on 2026-10-28 (`c8b365da`, no version bump); test `tests/test_se_consumption_accounting.py::test_reference_window_load_adds_standby_once`. Golden-master regression unchanged. **Pending:** SE run with a storage scenario: reference Gesamtverbrauch drops by exactly the standby kWh, optimized side unchanged.
- [ ] **Loxone export: strip scheme from the Earnie host field:** committed in `ee27503e` (no version bump): `normalize_export_host` (`ehal/signal_export.py`) strips a pasted `http(s)://` and trailing `/` and fails loud on a port or path; used by the Loxone VO/VI export (`ui/ehal_signal_list.py`) and the HA YAML download (`ui/ha_carrier_download.py`), with a caption when the address was shortened. Tests in `tests/test_ehal_signal_list.py`. **Pending:** check the export form in the UI with a pasted browser address.
- [ ] **[GitHub #61](https://github.com/JochenTCC/Earnie/issues/61) — Config migration assistant hints:** committed in `ac21bdc6`, `611ed38c`, `7f31aed7` (PR #65): the wizard says how it assigned the PV systems (also on the 2.6 path) and when `main.py` starts, starts `main.py` right after a successful migration when auto start is on, and shows the migration report after the run. Tests: `tests/apptest/test_page_config_migration_apptest.py`. On `main` the missing report page was reproduced and fixed in a local live run on 2026-10-24 (isolated pack, Streamlit, browser). **Pending:** run the wizard on a 2.6 pack with standalone inverters (Docker, auto start on).


## New Bugs (Do not remove this chapter — even if empty)



## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Set default "Temperaturabsenkung" in annual-rc to 2.5°C
- [ ] Review and modify text in SE review pop-up dialogue
- [ ] **[GitHub #59](https://github.com/JochenTCC/Earnie/issues/59) — decide on a config option to switch the EU features off** (reporter's request), now that failures are cached for one hour; `missing_price_strategy: mirror` already switches the EU requests off. Close #59 after the decision.


## Document Review Findings (Do not remove this chapter — even if empty)

