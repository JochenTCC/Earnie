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

- [ ] EV short unplug before FertigUm skipped today's cycle (`debug_dump_20260808_102915`) — `open_charging_deadlines` latch keeps `available_from=now` until deadline/fulfill; tests in `test_charging_session.py` / `test_charging_context.py`. Live acceptance pending.
- [ ] Pool filter Ist not assigned when only `sens_filter_active` is bound (`debug_dump_20260808_232225`) — binary meter accepts alternate-only; regression in `test_loxone_client.py`. Live acceptance pending.
- [ ] earnie.log unbounded growth — `SizeAndTimeRotatingFileHandler` (5 MB or weekly `W0`, backupCount 8, rename→copy/truncate fallback); tests in `test_logger_config_rotation.py`. Live acceptance pending.
- [ ] Live `main.py` hang after control MILP — `calculate_optimization_savings` now open-loop `commit_hours=len(matrix)` (was per-slot MPC on ~188 QH); test `test_calculate_optimization_savings_uses_open_loop_commit`. Restart debug `main.py` and confirm `Durchlauf erfolgreich` appears promptly.


## New Bugs (Do not remove this chapter — even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)


## Organizational Changes - no bugs (but still no development issue)
