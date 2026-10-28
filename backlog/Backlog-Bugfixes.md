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


- [ ] **Config migration 2.6 → 2.7 applied η_inv twice on the storage path:** reported 2026-10-28 by the issue #61 reporter (2.6.2 → 2.7.0-alpha.9, HA backend): `dm4.conversion_efficiency` was not in the wizard's step list; afterwards `inverters[].efficiency` 0.97 next to the unchanged lumped `batteries[].battery_efficiency` 0.97 (path 0.94 instead of 0.97 per direction). Cause: `migrate_components_inverters` (run by `dm4.v3_to_v4` and `dm4.inverters`) already wrote `efficiency: 0.97` on the inverters it created, so `needs_conversion_efficiency_migration` was false and the split step never ran on a 2.6 pack; only the `v4_pre_conversion` fixture (inverters without η) reached it. The goldens `v3_single_battery`, `v3_pre_ehal`, `v4_pre_quellenwahl`, `v4_pre_inverter_gridfee` had frozen the double η. Fix (no version bump): new inverters get no `efficiency`, so `dm4.conversion_efficiency` runs and splits η_batt = η_old / η_inv; the step leaves a to-do per battery (old value → η_inv × η_batt, where to adjust). Goldens updated (only η values changed); tests `tests/test_migration_registry.py::test_v3_path_splits_lumped_battery_efficiency`, `::test_conversion_todo_absent_when_nothing_was_split`. Packs already migrated with an alpha are not repaired (the step detects nothing): hint in `.github/release-notes/UNRELEASED.md`. **Pending:** wizard run on a real 2.6 pack (step listed, to-do shown, η_inv × η_batt = old value).

- [ ] **Regression: possible private case from the issue #50 reporter:** the reporter's configuration (HA backend, fixed import tariff + spot-indexed export, Netznutzung) is a typical constellation that the public cases did not cover. Ask for an anonymised config/debug dump (question list in the private business backlog); if it arrives, intake it as a private L1 case (`python -m scripts.run_regression --intake DUMP.zip --id REG-50-<slug> --private`, repo `Earnie-regression-private`). Meanwhile public L2 case `REG-S-gross-tariff-netznutzung` pins the VAT-on-Netznutzung rule (k_act 18 ct = 12 + 5 × 1.2).


- [ ] **SE reference (non-optimized) run booked the battery standby twice:** `simulation/reference_costs.py::_reference_window_inputs` added `reference_standby_power_kw` to the reference load twice in a row (and `reference_standby_power_kw` was defined twice), while the MILP adds the standby once per slot (`optimizer/battery.py`) and `booked_consumption_totals` subtracts it once for scenario and reference. Effect: Szenario-Explorer references with storage showed one standby too much in import cost and Jahres Verbrauch (e.g. 26 W ≈ 228 kWh/a). Cause: both blocks were duplicated by the release commit `28f756e9` (v2.7.0-alpha.8, docs/Loxone), present on `release/2.7` since alpha.8. Fixed on `release/2.7` ([#73](https://github.com/JochenTCC/Earnie/pull/73)) and cherry-picked to `main` (no version bump); test `tests/test_se_consumption_accounting.py::test_reference_window_load_adds_standby_once` (red before: 0.552 instead of 0.526 kW). Golden-master regression unchanged (no case runs references). **Pending:** SE run with a storage scenario — reference Gesamtverbrauch drops by exactly the standby kWh, optimized side unchanged.


## New Bugs (Do not remove this chapter — even if empty)

Findings from the viability study (house generator and offline runs, 2026-10-23/24; code in `studies/viability` and `studies/poc_cloud`).

Source of the next three items: [issue #50](https://github.com/JochenTCC/Earnie/issues/50) (live feedback, AT, HA backend, Docker image digest = `v2.6.2`; fixed import tariff + spot-indexed export). Findings were checked against `release/2.7` (2.7.0-alpha.9).

- [ ] **Issue #50 / 4 ([#57](https://github.com/JochenTCC/Earnie/issues/57)) — "Zwangsladen nicht ausgeführt" (deviation S3, `battery_power_below_tolerance`):** reporter's data (2.6.2, 3 slots, no restart, `the HA battery power sensor` positive while charging, 2.6.2 ran with `ehal.ha.sign: negate`) does **not yet show a sign bug**: `closed_interval` of a log entry at T covers the *previous* slot [T-15, T), so pairing it with that entry's `target_power_kw` (Soll for the *new* slot) is misleading; e.g. 11:47 shows snapshot -1.24 / closed -1.156 for a plan of 1.247 → consistent. **Next:** ask for the `closed_interval` of the *following* entry (T+15 min) for the three slots, plus `sample_count`; the 09:30 row (snapshot -2.49 but closed mean 0.0 over 23 samples) and the 11:32 row (snapshot -0.0 shortly after the slot start) stay unexplained until then. Candidates unchanged: decision-time snapshot fallback (`MIN_SAMPLE_COUNT_FOR_MEAN`), sign handling of the sampler vs. snapshot. Decision so far: do **not** harden the sampler state across restarts. **Mail of the reporter, 2026-10-24: no new data** (the mail does not mention forced charging or the `closed_interval` of the following entries); still waiting for the requested log entries.
- [ ] **Issue #50 / [#58](https://github.com/JochenTCC/Earnie/issues/58) — Forced-charge target stuck at 0.624 kW in many slots:** reporter sees `target_power_kw` exactly 0.624 across many slots and concludes the cap comes from the optimizer, not the inverter. **Next:** ask for the battery entry (max charge power, `conversion`/η, SoC window) from `components.json` / `house_profiles.json` and a few slots; check `optimizer/battery.py` and the MILP charge bounds (SoC headroom, inverter clipping, `battery_max_power_kw` vs. DC/AC conversion) for a limit that yields 0.624 kW. **Mail of the reporter, 2026-10-24: no new data** (battery entry, `conversion`/η and sample slots still requested).
- [ ] **Recorder replay plan differs from the live plan in 7 of 16 NAS cycles (found 2026-10-28):** all 16 cycles of the 2.7.0-beta.1 dump `debug_dump_20261028_103550` replay offline, but 7 plan hashes differ from the recorded ones (e.g. 09:44 replay runs `pool_swimspa` at 2.8 kW, live did not; 10:29 replay charges the battery at 2.745 kW, live mode 2). Suspected: inputs the replay still reads fresh instead of from the recording (outdoor forecast in `optimizer/thermal_targets.py`), and the recorder reading the thermal values a second time after the live run. Not investigated. The plan is info-level in the regression suite; the private case `REG-76-nas-thermal-replay` uses a matching cycle (09:59).



## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Set default "Temperaturabsenkung" in annual-rc to 2.5°C
- [ ] Review and modify text in SE review pop-up dialogue
- [ ] **Issue #50 — release notes for the next version:** the Netznutzung now receives VAT on gross import tariffs (`prices_include_vat: true`), so computed import prices rise by the VAT share of the grid fee (e.g. +1.0 ct at 5 ct grid fee, 20 %). Also mention the new load warnings and the recompute button. Draft only, per `release-notes.mdc`; not started yet (no draft in `.github/release-notes/`, `UNRELEASED.md` only has the HA sign hint and the removed `flexible_consumers`). Also mention the new migration question `dm4.ha_sign` (leftover `ehal.ha.sign`, #56) the EU feature pause after an unreachable host (#59), the new HA package automation `earnie_watchdog_release_force` (default on, 300 s; #60), the templated `set_value` action for `input_number` targets (#60) and the report page / daemon start after the migration (#61).
- [ ] **Issue #50 — confirm the version handling (`version.py`):** the fixes of #50 / #56 / #59 / #60 / #61 were merged to `main` (#62, #63) without a version bump; `main` still has `2.7.0-alpha.9`. On `release/2.7` they were cherry-picked (#65) and the version was bumped to `2.7.0-beta.1` (#66). Confirm that this covers the intended bump (rule: never change `version.py` without the maintainer's approval; completed bugfixes -> PATCH only); otherwise propose a PATCH bump before the next release.
- [ ] **Issue #50 — tell the reporter what changed:** the reporter has only the mail reply of 2026-10-24. New since then: the migration report page and daemon start (#61), `dm4.ha_sign` (#56), the EU retry pause (#59), the HA package fixes and watchdog (#60). Reply once the PRs are merged / released, and ask again for `EARNIE_AUTO_START_MAIN`, the `main_stdio.log` after a migration and the `Address` line of a VI/VO XML.


## Document Review Findings (Do not remove this chapter — even if empty)

