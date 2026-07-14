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

- [ ] **EV FertigUm when fully charged (plugged in)** — `fetch_loxone_charging_context` omits FertigUm when `actual_soc_name` reports charge complete; unplug re-reads FertigUm via absent forecast. Fix in `optimizer/charging_context.py`; tests `test_charging_context.py::TestPluggedInChargeComplete`.
- [ ] **SoC BL Ziel segment before Jetzt (Chart 1)** — dotted baseline trace no longer extends into the quarter-hour before the Jetzt marker; anchored at log-SOC via `_anchor_baseline_soc_at_now` in `ui/chart_soc.py`; test `test_baseline_soc_has_no_points_before_now`.

## New Bugs (Do not remove this chapter — even if empty)
