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


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **EHAL-Com — HA credentials editable without dedicated save.** On the EHAL-Com HA mapping UI (`ui/ehal_ha_mapping.py`), URL / token / `adapter_id` can be changed and used immediately for **Entities scannen** / live read, but they are only persisted into `ehal.ha` when the **entity mapping** is saved (`_save_entity_mapping`). There is no standalone “Speichern” for credentials on that page (unlike `ui/ehal_connection.py` on Smarthome-Backend). Reload or leave page → edited credentials are lost; easy to think “binding worked” when only the widget value changed. Fix: add explicit credentials save (and ideally a short connectivity probe), or stop duplicating credential fields on EHAL-Com and deep-link to the connection form.
- [ ] "debug-dumps\debug_dump_20260923_201155"
- [ ] Kosten Chart on page Monitor shows cost for the entire optimization horizon (SA_0 - SA_2). This is ambigous because when switching between days (at least in mobile mode) the user does not know if the values belong to the shown day or to the optimization horizon. The other ambiguity comes from the fact that during the day the already achieved cost reduction is "eaten" by the past grey area. 
  - Show cost reduction always on a daily basis. When complete horizon is shown - split it into two value columns
  - Show already achieved daily cost reductions in a separate line

## Document Review Findings (Do not remove this chapter — even if empty)
