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

- [ ] **Verbrauch CSV import path + `_resampled` name** — existence check uses `resolve_config_prefixed_path`; upload target `{original}_resampled.csv` (e.g. `BEZUG-2025-22.7.2026_resampled.csv`); was: false “nicht gefunden” on `config/uploads/…` + stable `{profile}_verbrauch.csv` name
- [ ] **Chart 1 Monitor: restore kW axis (undo global kWh bar scaling)** — heights = power again; bar width carries duration; sub-hour future consumers stay duty-cycle averaged (`nominal × duration_h` in `generic_schedule`); grey 15‑min slots unscaled


## New Bugs (Do not remove this chapter — even if empty)

## Organizational Changes - no bugs (but still no development issue)
