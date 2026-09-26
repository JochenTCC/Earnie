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

- [ ] **False “Zwangs-Entladen nicht ausgeführt”** (`debug_dump_20260923_201155`) — Fix implemented: deviation uses full-entry `closed_by` (not `by_slot` winners); `battery_power_below_tolerance` = Ist ≤ tol only (S6 “nicht ausgeführt”). Tests: `test_deviation_timeline` / `test_deviation_eval`. Dump evening 19:15–19:45 cleared; live Monitor acceptance still pending. Commit/PATCH when ending session.
- [ ] **SonarCloud leak-period QG** — Re-check 2026-09-26 on `main` @ `64b151c` (Actions [36225774457](https://github.com/JochenTCC/Earnie/actions/runs/36225774457)): QG **ERROR** — `new_bugs` **1**, `new_vulnerabilities` **19**, `new_reliability_rating` C, `new_security_rating` C, `new_coverage` ≈ **66%** (need ≥ 80%). Local remediations pending push/scan:
  - [x] Cleared previously: `bump_ha_addon.py` python:S3923; secrets:S7636; `.devcontainer` docker/shell
  - [x] Fixed locally (await analysis): `ha_units.py` S1244; Actions SHA pins + job permissions (`qemu-image-smoke` / `release-publish`); `report_repo_stats.py` path/URL guards; intentional NOSONAR for mock HTTP + add-on root
  - [x] Accepted (CLI threat model): `pythonsecurity:S8707` / `S8705` ignored project-wide via `sonar.issue.ignore.multicriteria` in `sonar-project.properties` (also `scripts.sonar_ignore_llm_cli_rules` + `SONAR_TOKEN` to mirror in SonarCloud Analysis Scope); `# NOSONAR` on scripts/tools remains as belt-and-suspenders until next scan confirms
  - [x] Dockerfile S6470: replace `COPY . .` with explicit package/app copies; tighten `.dockerignore`
  - [x] `remote_backtesting_support` S2083: validate absolute share roots + relative `result_dir`
  - [ ] Still failing / accept after scan: `release-publish.yml` `pip install -r requirements.txt` (S8541 / S8544 — `--only-binary=:all:` breaks local package `.`); `new_coverage` informational
  - Optional follow-ups: raise new-code coverage; `ui/chart_trace_segments.py` S3923 if still open; confirm S8707/S8705 gone after next Sonar analysis
- [ ] **Monitor Chart 2 daily Kosten KPIs** — Implemented: SA-day annotation columns (full span = two cols; segment = visible day); plan-based **Ersparnis bisher** line in gray zone (`ui/chart_day_costs.py`). Live Monitor acceptance pending.


## New Bugs (Do not remove this chapter — even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)

