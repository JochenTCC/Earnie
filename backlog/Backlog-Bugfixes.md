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

## Bugfix Verifications Pending (Do not remove this chapter — even if empty)

- [ ] **EV charge while unplugged (config path)** — house-profile EV (`daily_target_source=config`) sent `Ernie_EAuto_Ziel_kW` > 0 with `eauto_plugged_in: false`; config path now sets `anticipated`/`plugged_in` like Loxone path (`optimizer/charging_context.py::_config_path_with_plugged_in`). Dump: `chart_debug_review/debug_dump_20260720_094034`. Dump repro OK — live acceptance pending.

## New Bugs (Do not remove this chapter — even if empty)


## Organizational Changes - no bugs (but still no development issue)

