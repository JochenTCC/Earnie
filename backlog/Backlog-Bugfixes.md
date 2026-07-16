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

- [ ] **EV FertigUm ignored on config path** — house-profile EV (`daily_target_source=config`) kept `ready_by_hour` deadline and ignored `Ernie_EAuto_FertigUm`; later FertigUm still forced early charge (`must_start` for old deadline). Fix: `resolve_charging_context` uses `resolve_charging_deadline` (FertigUm wins, `use_time_window=False`); tests `TestConfigPathFertigUm`. Dump: `chart_debug_review/chart_debug_20260716_065036`. Live check: change FertigUm later while EV needs charge → `charging_contexts.ev.deadline` matches new time, no early force-charge for old deadline.

## New Bugs (Do not remove this chapter — even if empty)

- [ ] Is color palette for consumers in Charts (Earnie Monitor) used still the same as defined in the past

- [ ] Order of scenarios in Monatlicher Kostenvergleich bar chart should be the same as in Gesamtkosten and Verbrauchsvergleich

- [ ] Check if there is a special issue on weekends, when time-to-be ready is set to 12:00 (Start/ End-SOC constraints)