# Open Bugs

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md) (sections `### Bugfix …` / regressions)

Feature roadmap → [Backlog.md](Backlog.md)

## Classification

**Here:** Prod deviation, regression (`xfail`), known misbehavior, review with clear fix/remove outcome.
**Not here:** New behavior, UX, models, research — see feature backlog in `Backlog.md`.
**Versioning:** completed bugfixes → **PATCH** only in `version.py` (no minor bump).

### `## Bugfix Verifications Pending`

Fix is **implemented** (code + tests + optional PATCH in `version.py`), but **prod/live acceptance** is still pending.

- Move item from the thematic bugfix chapter here once the fix is committed — **not** directly to `Backlog-Erledigt.md`.
- Briefly note what changed (commit/version) if helpful.
- After successful verification: remove from this chapter → `Backlog-Erledigt.md` (`### Bugfix …`) with `- [x]`.
- If verification fails: return to open bugfix chapter or formulate follow-up; document PATCH if applicable, but do not archive as done.

## Bugfix Verifications Pending

- [ ] **EV: urgent constraint removed** (2026-07-09)
  - MILP: separate `urgent >= target` constraint removed; deadline still enforced via `eligible` slots until completion time
  - Observability retained (`role` post-hoc); ISO deadline parsing added
  - Regression: `eauto_urgent_deferred_cheap_hours_2026-06-28`, new `eauto_urgent_deferred_cheap_hours_2026-07-09`; `xfail` removed
  - **Prod acceptance:** next charge cycle with deadline 07:45 — plan uses cheap night hours (02–04), `urgent_rule_observability.eauto.role == redundant`

## New Bugs (Do not remove this chapter — even if empty)

## Bugs after testing 1.25.0
- [ ] Query Loxone credentials only when live operation is enabled and markers should be verified (defer to later)


## EV: urgent rule, prod dump, PWM
Related topics — prioritize and work through together.

- [ ] **Urgent rule observability review** (by approx. **2026-07-12**, after prod acceptance)
  - Constraint removed → evaluate `urgent_rule_observability` in log + `optimization_history.jsonl` (`role`: expected `redundant`)
  - Acceptance: consistently `redundant` over several charge cycles → close review, simplify observability logging if applicable
- [ ] **PWM for EV charging** — only for currents < A_min; otherwise minimum charge amount per h (count down meter, reset on each charge → at zero charge charge five minutes at minimum current)
