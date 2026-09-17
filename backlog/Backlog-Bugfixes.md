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

- [ ] **SonarCloud new-code security/reliability debt** — Code remediations in; confirm on next SonarCloud scan (leak-period QG / ratings):
  - [x] `scripts/bump_ha_addon.py` python:S3923 — already fixed (`return 0`; no same-value conditional)
  - [x] S7636 secrets-in-run — `HA_ADDON_REPO_TOKEN` via `env:` in `ha-addon-publish.yml` + `release-publish.yml` (require-token step)
  - [x] docker:S6471 / shell:S8541 — `.devcontainer` non-root `vscode` user; `pip … --only-binary=:all:`
  - Accepted: `release-publish.yml` keeps floating action tags (`@v4`/`@v5`); SHA pins blocked tag runs (`e796a01`). `ha-addon-publish.yml` remains SHA-pinned.


## New Bugs (Do not remove this chapter — even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)
