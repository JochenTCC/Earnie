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

- [ ] **Virtual reserve: `advance_reserve_after_slot` / `set_trigger` wiped `target_kwh` to 0** — fix implemented (2026-10-10); live acceptance pending
  - Symptom (Nas productive, Geschirrspüler / `virtual_gs`): dishwasher running, MILP ZWANGSLADEN toward ~11.8% (≈1 kWh refill), but `powerstation_reserves.json` stayed `empty` / `stored_kwh=0` / `target_kwh=0`.
  - Cause: `get_or_init_state(..., target_kwh=0.0)` always overwrote the configured target on every slot advance / trigger latch, so charge credit was capped at `min(0, …)`.
  - Fix: `update_target=False` for advance + trigger; collect/learn still refresh the target.
  - Tests: `tests/test_powerstation_2_7_p.py` (`test_advance_and_trigger_preserve_target_kwh`).

## New Bugs (Do not remove this chapter — even if empty)

- [ ] "debug-dumps\debug_dump_20261015_222809"

## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)


