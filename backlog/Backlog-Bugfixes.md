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


- [ ] **Regression: possible private case from the issue #50 reporter:** the reporter's configuration (HA backend, fixed import tariff + spot-indexed export, Netznutzung) is a typical constellation that the public cases did not cover. Ask for an anonymised config/debug dump (question list in the private business backlog); if it arrives, intake it as a private L1 case (`python -m scripts.run_regression --intake DUMP.zip --id REG-50-<slug> --private`, repo `Earnie-regression-private`). Meanwhile public L2 case `REG-S-gross-tariff-netznutzung` pins the VAT-on-Netznutzung rule (k_act 18 ct = 12 + 5 × 1.2).


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Recorder replay plan differs from the live plan in 7 of 16 NAS cycles (found 2026-10-28):** all 16 cycles of the 2.7.0-beta.1 dump `debug_dump_20261028_103550` replay offline, but 7 plan hashes differ from the recorded ones (e.g. 09:44 replay runs `pool_swimspa` at 2.8 kW, live did not; 10:29 replay charges the battery at 2.745 kW, live mode 2). Suspected: inputs the replay still reads fresh instead of from the recording (outdoor forecast in `optimizer/thermal_targets.py`), and the recorder reading the thermal values a second time after the live run. Not investigated. The plan is info-level in the regression suite; the private case `REG-76-nas-thermal-replay` uses a matching cycle (09:59).

## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] Set default "Temperaturabsenkung" in annual-rc to 2.5°C
- [ ] Review and modify text in SE review pop-up dialogue
- [ ] **[GitHub #59](https://github.com/JochenTCC/Earnie/issues/59) — decide on a config option to switch the EU features off** (reporter's request), now that failures are cached for one hour; `missing_price_strategy: mirror` already switches the EU requests off. Close #59 after the decision.


## Document Review Findings (Do not remove this chapter — even if empty)

