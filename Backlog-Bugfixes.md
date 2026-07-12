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

- [ ] **Scenario-Exploration: cons_data ID mismatch after regenerate** (greenfield smoke 2026-07-11)
  - Fix: `expected_cons_data_consumer_ids()` uses raw `config.json` IDs or full house-profile set (not `_planning_flex_consumers` merge); meta `consumer_ids` aligned on save
  - **Verify:** greenfield Scenario-Exploration → generate cons_data → success, no ID warning

## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Greenfield: Loxone credential sidebar disappears before credentials saved** (greenfield smoke 2026-07-11; **re-opened 2026-07-12**)
  - Prior fix insufficient: `loxone_setup_deferred()` + sidebar expander in `ui/setup_progress.py` — verification **failed** (expander still missing on navigation before `.env` save)
  - **Reproduce:** greenfield — planning complete, Scenario-Exploration unlocked, no Loxone credentials saved → navigate Hauskonfigurator ↔ Scenario-Exploration → expander **"Loxone-Zugang (Live / Silent-Modus)"** must persist
  - **Investigate:** `runtime_store/dotenv_io.py` (`loxone_setup_deferred`), `ui/setup_readiness.py` (planning unlock path), `app.py` → `render_setup_progress_notice()`
  - **Acceptance:** expander visible on all relevant pages until credentials saved; regression test; then → *Bugfix Verifications Pending*


## EV: urgent rule, prod dump, PWM
Related topics — prioritize and work through together.

- [ ] **Urgent rule observability review** (by approx. **2026-07-12**, after prod acceptance)
  - Constraint removed → evaluate `urgent_rule_observability` in log + `optimization_history.jsonl` (`role`: expected `redundant`)
  - Acceptance: consistently `redundant` over several charge cycles → close review, simplify observability logging if applicable
- [ ] **PWM for EV charging** — only for currents < A_min; otherwise minimum charge amount per h (count down meter, reset on each charge → at zero charge charge five minutes at minimum current)
