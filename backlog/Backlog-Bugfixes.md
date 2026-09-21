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

- [ ] **SonarCloud leak-period QG** — Named remediations verified on post-fix scans (`ccebfcf` → e.g. Actions [35350702620](https://github.com/JochenTCC/Earnie/actions/runs/35350702620)); gate still **ERROR** (do not archive until QG OK or explicitly accepted as informational):
  - [x] Verified cleared: `bump_ha_addon.py` python:S3923; secrets:S7636 (`HA_ADDON_REPO_TOKEN` via `env:`); `.devcontainer` docker:S6471 / shell:S8541; `new_reliability_rating` = A
  - [ ] Still failing QG: `new_security_rating` = C; `new_coverage` ≈ 76.7% (need ≥ 80%)
  - Accepted (not separate New Bugs): `release-publish.yml` floating action tags `@v4`/`@v5` (`e796a01`; SHA pins blocked tag runs); `ha-addon-publish.yml` stays SHA-pinned; bulk other new-code findings (Actions smells, `pythonsecurity` on CLI scripts, etc.) — triage only when opening a concrete fix item
  - Optional follow-ups (open New Bug only if planned): raise new-code coverage; reopen Actions hardening beyond the accepted exception; specific high-signal leftovers (`docker/Dockerfile` root / `ui/chart_trace_segments.py` S3923)
- [ ] **HA add-on Ingress start abort (`20b22c55_…` log)** — `packaging/.../run.sh` used invalid GNU sed that aborted start under `set -e`. Fix: Python `str.replace` for nginx conf (`v2.5.3-alpha.6`). Test: `tests/test_ha_addon_ingress_nginx.py`. Dogfood: Synology HAOS Ingress OPEN WEB UI after add-on update.


## New Bugs (Do not remove this chapter — even if empty)

## Document Review Findings (Do not remove this chapter — even if empty)
