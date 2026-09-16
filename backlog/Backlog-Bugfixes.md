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


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **SonarCloud new-code security/reliability debt (defer past 2.5.3-alpha.1)** — QG ERROR: new reliability rating 3, security rating 5, new coverage 75.1% (&lt;80). Open leak-period items (triage before official 2.5.3):
  - `scripts/bump_ha_addon.py` python:S3923 (conditional same value — verify still present after recent edit)
  - `.github/workflows/ha-addon-publish.yml` / `release.yml`: secrets-in-run (S7636), remaining SHA pins if any
  - `.devcontainer/Dockerfile` root user (docker:S6471); `.devcontainer/post-create.sh` pip without `--only-binary` (shell:S8541)


## Document Review Findings (Do not remove this chapter — even if empty)
