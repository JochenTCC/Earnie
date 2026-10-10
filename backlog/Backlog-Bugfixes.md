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

- **Note:** **2.7.h** productive dogfood still pending (2026-10-10): Pattern B Quellenwahl landed — re-open after operator rewires the Loxone ↔ HA EcoFlow bypass bridge to `ess.<id>.set_ess_source_select`.

- [ ] **Virtual reserve: `advance_reserve_after_slot` / `set_trigger` wiped `target_kwh` to 0** — fix implemented (2026-10-10); live acceptance pending
  - Symptom (Nas productive, Geschirrspüler / `virtual_gs`): dishwasher running, MILP ZWANGSLADEN toward ~11.8% (≈1 kWh refill), but `powerstation_reserves.json` stayed `empty` / `stored_kwh=0` / `target_kwh=0`.
  - Cause: `get_or_init_state(..., target_kwh=0.0)` always overwrote the configured target on every slot advance / trigger latch, so charge credit was capped at `min(0, …)`.
  - Fix: `update_target=False` for advance + trigger; collect/learn still refresh the target.
  - Tests: `tests/test_powerstation_2_7_p.py` (`test_advance_and_trigger_preserve_target_kwh`).

## New Bugs (Do not remove this chapter — even if empty)

- [ ] Don't show "main.py nicht aktiv" on Monitor page while main.py is running and currently optimizing

- [ ] EcoFlow Delta 3 bridge: Miniserver self-write of a Virtual Input is overwritten by HA (2026-10-07, not analysed yet)
  - Setup: the Miniserver writes its own Virtual Input via a Virtual Output command (`/dev/sps/io/<Input>/\v`, device = the Miniserver itself), e.g. bypass state (`Delta3_Grid_ByPass`) and charge limit (`Delta3_P_ChargeLimit`). HA mirrors these inputs through the Loxone integration (PyLoxone) and drives the EcoFlow entities from automations (`docs/einrichtung/ecoflow-delta3-loxone.md`, steps 5/6).
  - Symptom: in between, the input value changes to a different value that the Miniserver logic did not write; HA seems to set it. Which writer and when is unknown.
  - To check: (1) does an HA `rest_command` (SoC / power / SOC min/max pushes) target the same input name, or does a name collision exist between inputs; (2) does the HA start trigger or a state-trigger automation push a value back into an input; (3) does the Virtual Output command repeat or fire on every cycle (Repeat setting); (4) does the Loxone integration write entity states back to the Miniserver; (5) compare timestamps of the HA log (`rest_command`) with the Miniserver's online monitor.
  - Fix idea if confirmed: let HA only read these inputs (no `rest_command` to them) or switch the bridge to the webhook variant (step 5/6, variant B). Update the guide's "Hinweis zum Eingang" once the cause is known.


## Minor changes (no bugs - do not remove this chapter - even if empty)

- [ ] Übernimm im HA-Addon die Positionsdaten aus HA, wenn möglich

## Document Review Findings (Do not remove this chapter — even if empty)
