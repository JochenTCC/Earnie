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

- [ ] **Debug-Dump ZIP: `optimization_history.jsonl` fehlt (NAS/Docker)** — dump used baked `earnie_env/runtime` while history lives on volume `/app/runtime`; fixed via `resolve_history_src()` fallback + `EARNIE_RUNTIME_PATH: runtime` in compose. Compose workaround verified on NAS; code/image acceptance pending.
- [ ] **Manual WM/Trockner phantom Chart-1 bars** — `apply_known_generic_to_chart_rows` peeled assumed weekly `earnie_role: manual` schedules into named bars (`phantom_kw` when live baseload lacked that energy). Fix: peel only `known`; manuals via `appliance_schedules.json` only (`house_config/known_chart_display.py`). Dump: `chart_debug_review/debug_dump_20260720_171718`. Dump repro OK — live acceptance pending.
- [ ] **`oemag_monthly_feed_in_rates` moved to `tariffs.json`** — shared OeMAG reference + `monthly_float_reference_cent_kwh` now live in `tariffs*.json` (not `backtesting_scenarios`); bootstrap migrates v1→v2 (copy/strip/stamp). Live acceptance pending.
  - Error in SE: tariffs.json entspricht nicht dem Schema (earnie_env\config\tariffs.json): 1 was expected
    - All .json files are expected to upgrade automatically
- [ ] Testing greenfield / saving / importing data in Streamlit Cloud


## New Bugs (Do not remove this chapter — even if empty)


## Organizational Changes - no bugs (but still no development issue)

