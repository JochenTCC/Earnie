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
- [ ] **Monitor mobile chunk load (hostname)** — `TypeError: Failed to fetch dynamically imported module` for old `/static/js/TextInput.*` / `Selectbox.*` hashes. LAN IP works; hostname serves current chunks as JS but obsolete hashes return `index.html`. Cause: phone cache after Streamlit upgrade. Mitigation in `2.1.0-alpha.2`: `ui/chunk_load_recovery.py` one-shot reload + temporary `ui/chunk_load_debug.py` probe. Live check on Synology via hostname: UI recovers without clearing site data; then remove debug probe.

## New Bugs (Do not remove this chapter — even if empty)

- [ ] **EV charge planned while not connected** — Earnie schedules/tries to charge Smart although the car is not connected. Local dump (not in repo): `chart_debug_review/debug_dump_20260717_105429` (meta title/symptom from Cockpit).
