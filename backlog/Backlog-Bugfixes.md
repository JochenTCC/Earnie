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

- [ ] **Negative export tariff + battery discharge -- Still open:** PV curtailment var so hard cap stays feasible when SoC full. Soft pay-to-export live dogfood closed with **2.7.a** (2026-09-30). Open question: Monitor plan vs live discharge after `k_push` already negative.


## New Bugs (Do not remove this chapter — even if empty)

- [ ] huawei derating function is actually reducing PV yielding - not exporting as expected - this is a Loxone config implementation issue - no Earnie bug.
- [ ] "debug-dumps\debug_dump_20260930_182138"
- [ ] check if for tariff forecast the individual tariff extra cost + volumetric Netzentgelt are also added (like the known tariff) or if forecast has to be updated (because it seems to be quite lower as actual tariff all the time)

## Minor changes (no bugs - do not remove this chapter - even if empty)

- [ ] Übernimm im HA-Addon die Positionsdaten aus HA, wenn möglich

## Document Review Findings (Do not remove this chapter — even if empty)
