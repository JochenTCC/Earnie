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


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **NAS launch: Chart 1 Monitor missing past data without `EARNIE_RUNTIME_PATH`** — VS Code “Streamlit app.py (NAS :8503)” with only `EARNIE_ENV_PATH` pointing at NAS `earnie_env` loads config correctly, but Chart 1 past/history series are incomplete or empty. Setting `EARNIE_RUNTIME_PATH` to the same share’s `…/earnie_env/runtime` restores full Chart 1. Expected: `runtime_dir()` from `{EARNIE_ENV_PATH}/runtime` alone should match an explicit `EARNIE_RUNTIME_PATH`; investigate path resolution / history readers vs. UNC share (related: `persist_paths.runtime_dir`, Monitor Chart 1 data sources).
- [ ] Changed Bezeichnung in Verbraucher Edit is not updating the collapse label instantly (on first Verbraucher)

## Organizational Changes - no bugs (but still no development issue)
