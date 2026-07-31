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


## Bugfix Verifications Pending (Do not remove this chapter — even if empty) + Testing Todos

- [ ] **EV absent daytime plan after overnight ready_by** — dumps `debug_dump_20260731_075323` / `091219`: FertigUm kept overnight open past config `ready_by` → daytime Smart plan while unplugged. Fix: `resolve_absent_availability` (config `ready_by` bound). Also shipped on `hotfix/2.3.2` (`v2.3.2`) with Ist-SOC config-path port. Tests: `TestAbsentAvailability`, `TestLoxoneAbsentForecast`. Live verify: unplugged daytime → no EV plan before next `car_available_from`.


## New Bugs (Do not remove this chapter — even if empty)

- [ ] Zähler Energiebezug can be ignored for consumers (not an Earnie issue)

## Organizational Changes - no bugs (but still no development issue)
