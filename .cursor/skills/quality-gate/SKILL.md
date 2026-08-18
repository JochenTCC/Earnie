---
name: quality-gate
description: >-
  Runs the Earnie MINOR release quality / hardening gate (same shape as 2.4.r /
  2.5.r): coverage baseline, dead-code and obsolete-test audit, identify
  redundant / unnecessarily complex / unneeded code without changing
  functionality, KPI refactor including mega-file splits, official-docs
  review, then a SonarCloud snapshot. Use when the user asks for a quality gate,
  quality/release hardening, 2.X.r, coverage/KPI audit before official release,
  or to repeat the 2.4.r / 2.5.r checklist.
---

# Quality / release hardening gate

Canonical shape: **coverage → dead-code / obsolete tests → simplify redundant/complex/unneeded code (no behavior change) → KPI refactor (incl. mega-file splits) → official docs → SonarCloud snapshot**. Do **not** tag, bump `version.py`, or publish; that is [session-abschluss](../session-abschluss/SKILL.md).

Never auto-delete tests, fixtures, or vulture hits — triage with the user.

## When this skill applies

- User asks for a quality gate, “quality / release hardening”, or `MAJOR.MINOR.r`
- Preparing an official MINOR (`X.Y.0`) after community soak
- Repeating the 2.4.r / 2.5.r checklist

Copy and track:

```
Quality gate:
- [ ] 1. Coverage baseline (`test_health_report run --coverage`)
- [ ] 2. Dead-code / obsolete-test audit (vulture, --dead-fixtures, health-report)
- [ ] 3. Identify redundant, unnecessarily complex, or unneeded code without changing functionality
- [ ] 4. KPI refactor — functions + files over hard limits; do not defer mega-file splits
- [ ] 5. Official docs (landing/handbook/charts/specs vs this MINOR)
- [ ] 6. SonarCloud snapshot (new issues vs last .r; record gate status)
- [ ] 7. Record results in the open `X.Y.r` backlog chapter (do not bump version.py)
```

Windows: prefix every Python/pytest command with `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1';` ([windows-unicode-console](../windows-unicode-console/SKILL.md)). PowerShell 5.x: no `&&`. Commands: [`.cursor/rules/test-health.mdc`](../../rules/test-health.mdc).

## 1. Coverage baseline

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m scripts.test_health_report run --coverage
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m scripts.test_health_report report
```

Packages: `optimizer`, `data`, `house_config`, `simulation`, `settings`, `runtime_store`, `ehal` (`pyproject.toml` / `COV_SOURCE_PACKAGES`). Flag any package **< 40%** as a test gap (report only — not a CI fail). Record overall line-rate and per-package rates vs the previous `.r` if present.

## 2. Dead-code / obsolete-test audit

Requires `pip install -e ".[dev]"`.

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m vulture optimizer data house_config simulation settings runtime_store ehal scripts --min-confidence 80
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m pytest --dead-fixtures
```

Triage `health-report.md` flags. **Protected** files in `scripts/test_health_report.py` stay unflagged. Fail-fast tests that mention `LEGACY_TEST_SYMBOLS` (`legacy_id`, `pv_follow_name`, …) are expected — keep unless the user agrees to rewrite. Remove unused imports / dead helpers only after confirming no callers. Do not treat `subtract_consumer_ids` as legacy.

## 3. Identify redundant, unnecessarily complex, or unneeded code without changing functionality

Separate from vulture (unused symbols) and from KPI splits (size). Walk recently touched and high-churn packages (`optimizer/`, `simulation/`, `house_config/`, `integrations/`, `ui/`, `data/`) and list candidates **before** deleting or rewriting.

Look for:

| Kind | Examples |
|------|----------|
| Redundant | Duplicate helpers, parallel wrappers that only forward, copy-paste branches that already share a helper, unused re-exports, dual code paths that always take one branch |
| Unnecessarily complex | Extra abstraction layers with one caller, nested conditionals that flatten, flags that no longer change outcomes, compatibility shims for removed APIs |
| Unneeded | Commented-out blocks, `_backup.py` / `_tmp_*` leftovers, dead feature flags, unused config keys that still branch, tests that only re-assert another test |

Rules:

- **No functional change.** Same public APIs, same MILP/simulation/pricing results, same Streamlit widget keys and persisted JSON shapes.
- Propose a short triage list (file, what, why safe). Apply only items the user accepts, or clearly mechanical ones (unused import, identical duplicate).
- Prefer delete/inline over a new helper if the helper exists only to wrap one call.
- Do not “simplify” by changing defaults, rounding, or fallbacks that alter numbers.
- Re-run the smallest pytest set that covers the touched module after each accepted change.

Record what was removed vs deferred in the `X.Y.r` chapter.

## 4. KPI refactor — do not defer mega-file splits

Limits (from project Python structure rules):

| KPI | Target | Hard limit |
|-----|--------|------------|
| Function body LOC (no blanks/comments; docstrings excluded) | ≤ 40 | Split before feature work if **> 60** |
| Core packages (`optimizer/`, `data/`, `runtime_store/`, plus `house_config/`, `settings/`, `simulation/`, `ehal/`, `integrations/`) | ≤ 300 file LOC | **600** |
| UI (`ui/`) | ≤ 400 file LOC | **600** |

**Do not defer mega-file splits.** Files over the hard limit, and functions **> 60** LOC in those packages, are in-gate work. Do not copy 2.4.r’s “deferred mega-file splits” (`optimizer/simulation.py`, `simulation/engine.py`, `integrations/loxone_*.py`, `house_config/planning_flex_bridge.py`, or later equivalents).

How to split:

1. Measure (count code LOC, not blank/comment-only lines). List every file over 600 and every function > 60 in core/UI.
2. Split in bounded steps: **≤ 3 files per step**, public import facades unchanged where callers rely on them (same pattern as `config.py` → `settings/config_loaders.py`).
3. Ask only about **order / API surface** if a split would change call sites across many packages — not whether to skip the split.
4. Re-run pytest for the touched packages after each step.

Keep cyclomatic complexity ≤ 10 and nesting ≤ 3; extract named helpers instead of growing existing bodies.

## 5. Official docs

Walk [`backlog/Doc-Review-Checklist.md`](../../../backlog/Doc-Review-Checklist.md) for this MINOR. User docs stay **German** (`german-user-docs.mdc`). Fix landing (`README.md`, `docs/README.md`), handbook, charts, issue templates, and specs that still describe the **previous** planning granularity or removed features.

New findings that are not fixed in this pass go under `## Document Review Findings` in `backlog/Backlog-Bugfixes.md` (skill [doc-review-findings](../doc-review-findings/SKILL.md)). If headings/nav change, [streamlit-doc-links](../streamlit-doc-links/SKILL.md).

## 6. SonarCloud snapshot

CI already scans `main`/PRs ([`.github/workflows/sonarcloud.yml`](../../../.github/workflows/sonarcloud.yml)). **Do not** re-run Sonar or `pytest --cov` locally for this step. Open the SonarCloud project (`JochenTCC_Earnie`) on the `main` commit this `.r` is based on.

Record in the `X.Y.r` chapter:

| Record | Rule |
|--------|------|
| Sonar Quality Gate | Passed / Failed — **informational** (not a required GitHub check; not a merge blocker) |
| New issues since last `.r` | Bugs, vulnerabilities, and security hotspots only — **new**, not the whole historical backlog |
| Code smells | Triage like vulture: list candidates; fix only what the user accepts |
| Coverage | Note dashboard % vs health-report; **do not** chase alignment as in-gate work |

**Fail the `.r` chapter** only if there are **new bugs or vulnerabilities** on `main` that are not deferred with an explicit item in `backlog/Backlog-Bugfixes.md`. Smells and old debt stay triage.

Do not enable SonarCloud’s Quality Gate as a required GitHub status check in this skill.

## 7. Backlog — no version bump

Tick the open `X.Y.r` items in `backlog/Backlog.md` with measured numbers (pytest count, coverage, vulture/dead-fixtures, simplification removals vs deferred, which files were split, Sonar gate status + new-issue counts). Leave live-verification bugs in `Backlog-Bugfixes.md`. **Never** change `version.py` in this skill.

## Do not

- Defer mega-file splits to a later letter or `2.+1`
- Auto-delete tests/fixtures from the health report
- Change behavior while simplifying (defaults, numerics, APIs, persisted keys)
- Tag / GHCR / `:latest` (session-abschluss)
- Treat “never failed” tests as ineffective
- Re-run Sonar locally or treat Sonar coverage as a second coverage baseline
- Make the Sonar Quality Gate a required GitHub check from this skill
