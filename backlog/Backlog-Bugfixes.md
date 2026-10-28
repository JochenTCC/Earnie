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

- [ ] **SE reference (non-optimized) run booked the battery standby twice:** `simulation/reference_costs.py::_reference_window_inputs` added `reference_standby_power_kw` to the reference load twice (and the function was defined twice), while the MILP adds the standby once per slot. Szenario-Explorer references with storage showed one standby too much in import cost and Jahres Verbrauch (e.g. 26 W ≈ 228 kWh/a). Cause: duplicated by the release commit `28f756e9` (v2.7.0-alpha.8). Fix `f3b752cc` (PR #73, closed unmerged on 2026-10-27; on `main` via #74) cherry-picked to `release/2.7` on 2026-10-28 (`c8b365da`, no version bump); test `tests/test_se_consumption_accounting.py::test_reference_window_load_adds_standby_once`. Golden-master regression unchanged. **Pending:** SE run with a storage scenario: reference Gesamtverbrauch drops by exactly the standby kWh, optimized side unchanged.


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Recorder replay plan differs from the live plan in 7 of 16 NAS cycles (found 2026-10-28):** all 16 cycles of the 2.7.0-beta.1 dump `debug_dump_20261028_103550` replay offline, but 7 plan hashes differ from the recorded ones (e.g. 09:44 replay runs `pool_swimspa` at 2.8 kW, live did not; 10:29 replay charges the battery at 2.745 kW, live mode 2). Suspected: inputs the replay still reads fresh instead of from the recording (outdoor forecast in `optimizer/thermal_targets.py`), and the recorder reading the thermal values a second time after the live run. Not investigated. The plan is info-level in the regression suite; the private case `REG-76-nas-thermal-replay` uses a matching cycle (09:59).

## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Set default "Temperaturabsenkung" in annual-rc to 2.5°C
- [ ] Review and modify text in SE review pop-up dialogue
- [ ] **[GitHub #59](https://github.com/JochenTCC/Earnie/issues/59) — decide on a config option to switch the EU features off** (reporter's request), now that failures are cached for one hour; `missing_price_strategy: mirror` already switches the EU requests off. Close #59 after the decision.


## Document Review Findings (Do not remove this chapter — even if empty)

