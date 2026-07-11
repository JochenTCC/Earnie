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

- [x] **EV: urgent constraint removed** (2026-07-09)
  - MILP: separate `urgent >= target` constraint removed; deadline still enforced via `eligible` slots until completion time
  - Observability retained (`role` post-hoc); ISO deadline parsing added
  - Regression: `eauto_urgent_deferred_cheap_hours_2026-06-28`, new `eauto_urgent_deferred_cheap_hours_2026-07-09`; `xfail` removed
  - **Prod acceptance:** next charge cycle with deadline 07:45 — plan uses cheap night hours (02–04), `urgent_rule_observability.eauto.role == redundant`

## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Scenario-Exploration: cons_data ID mismatch warning persists after regenerate** (greenfield smoke 2026-07-11)
  - UI: warning *„Verbraucher-IDs in den gespeicherten Daten weichen von der aktuellen Konfiguration ab — bitte neu generieren.“* stays after **Verbrauchsdaten generieren** on Scenario-Exploration page
  - Likely: `expected_cons_data_consumer_ids()` vs meta `consumer_ids` after house-profile synthesis — see `data/cons_data_house_profile.py`, `data/cons_data_store.py`, `ui/backtesting_cons_data.py`
- [ ] **Greenfield: Loxone credential sidebar disappears before credentials saved** (greenfield smoke 2026-07-11)
  - Sidebar expander *Loxone-Zugang* vanishes on page navigation before user entered data; see `ui/setup_progress.py` (`needs_planning_onboarding` gate, `expanded=` logic)

- [ ] Add allowed tolerance / threshold parameter to deviations that can be changed in deviation_rules.json
- [ ] Add nominal voltage to ev consumer for power calculation purposes (instead of constant 230V)


## EV: urgent rule, prod dump, PWM
Related topics — prioritize and work through together.

- [ ] **Urgent rule observability review** (by approx. **2026-07-12**, after prod acceptance)
  - Constraint removed → evaluate `urgent_rule_observability` in log + `optimization_history.jsonl` (`role`: expected `redundant`)
  - Acceptance: consistently `redundant` over several charge cycles → close review, simplify observability logging if applicable
- [ ] **PWM for EV charging** — only for currents < A_min; otherwise minimum charge amount per h (count down meter, reset on each charge → at zero charge charge five minutes at minimum current)
