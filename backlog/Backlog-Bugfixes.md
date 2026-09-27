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

- [ ] **False “Zwangs-Entladen nicht ausgeführt”** (`debug_dump_20260923_201155`) — Fix implemented: deviation uses full-entry `closed_by` (not `by_slot` winners); `battery_power_below_tolerance` = Ist ≤ tol only (S6 “nicht ausgeführt”). Tests: `test_deviation_timeline` / `test_deviation_eval`. Dump evening 19:15–19:45 cleared; live Monitor acceptance still pending. Commit/PATCH when ending session.
- [ ] **Monitor Chart 2 daily Kosten KPIs** — Implemented: SA-day annotation columns (full span = two cols; segment = visible day); plan-based **Ersparnis bisher** line in gray zone (`ui/chart_day_costs.py`). Live Monitor acceptance pending.


## New Bugs (Do not remove this chapter — even if empty)

- [ ] Tariff preview seems to not work with the model - just by mirroring existing tariff data. Check reasons

## Minor changes (no bugs - do not remove this chapter - even if empty)

- [ ] Change order on Monitor side: Place sankey diagram right under Chart 1 - then Chart 2 with cost and consumption - then Simulation Details und Energievergleich

## Document Review Findings (Do not remove this chapter — even if empty)

