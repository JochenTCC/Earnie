---
name: regression-triage
description: >-
  Analyse red golden-master regression cases and decide bug vs. intended behaviour
  change vs. test-data / environment problem. Reads regression_report.md (baseline
  drift, input fingerprint verdict, bisect commands), runs
  `run_regression --compare-at <sha>` for per-slot CSVs and a plot, bisects in a
  separate worktree, and ends with a per-case verdict and next action (fix,
  --update-golden with justification, or environment fix). Use when
  scripts.run_regression or the pre-push hook reports failed cases, or when the user
  asks whether a regression failure is a bug or new behaviour.
---

# Regression Triage

Goal: for every red case a **verdict with evidence** — never "re-record and move on".
Spec: [regression-suite.md](../../../docs/workflow/regression-suite.md) (§7 tiers, §8 runner).
Creating new cases after a bugfix is skill [bugfix-regression-test](../bugfix-regression-test/SKILL.md).

Commands below assume the Earnie root and the UTF-8 env:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
```

## Checklist

```
Regression triage:
- [ ] 1. Re-run only the red cases (--case X) — still red? (rules out a one-off)
- [ ] 2. Read each red case in regression_report.md: tiers, inputs verdict, baseline drift
- [ ] 3. Branch on the verdict (table below)
- [ ] 4. --compare-at <baseline sha> --case X → summary.md / diff.csv / plot.html
- [ ] 5. Code change? → bisect in a separate worktree → first bad commit + its diff
- [ ] 6. Classify: bug / intended / test-data-or-environment — with evidence
- [ ] 7. Report to the user; act only after their OK (fix, golden, environment)
```

## 1–2. Read the report

`backtesting_logs/regression/regression_report.md`, per red case:

- **invariants** FAIL → hard rule broken (SoC limits, energy balance, EV deadline …). Almost always a bug.
- **metrics** FAIL → which metrics, how far. Patterns help: Δ cost% == Δ export% means cost is export revenue only, so the energy quantity moved, not the price logic.
- **baseline** → golden commit, commits since (total / code paths), bisect commands.
- **inputs** (informational) → files / effective series changed, sums (`pv_kwh` …), `engine: earnie_version a → b`, and the **verdict** line.
- An `ImplausiblePvInputError` instead of a result → PV input is not a day curve (L2 guard, `tests/regression/pv_shape.py`).

## 3. Branch on the verdict

| Verdict / symptom | Meaning | Next |
|---|---|---|
| `ImplausiblePvInputError` / PV shape guard | PV input broken (cache, mock leak, climate fixture) | Environment / data — find where the climate came from; no bisect of optimizer code |
| *effective inputs changed* (series listed) | The optimizer saw different inputs | compare-at: which series, which slots. Then: deliberate fixture/input change (→ intended, re-record) or broken input preparation (→ bug) |
| *input files changed but effective inputs identical* | Files moved, inputs the same → output change comes from code | compare-at + bisect |
| *inputs identical* | Pure code behaviour change | compare-at + bisect |
| *no input fingerprint in expected.json* | Golden predates fingerprints | compare-at against the baseline gives both sides |
| only `highspy` / solver differs in the engine fingerprint | Solver determinism | regression-suite.md §16 before anything else |

## 4. Compare against the baseline

```powershell
.venv\Scripts\python.exe -m scripts.run_regression --compare-at <baseline-sha> --case REG-X
```

Output in `backtesting_logs/regression/compare/REG-X__<sha8>/`: `summary.md`, `base_slots.csv`, `head_slots.csv`, `diff.csv`, `plot.html` (base dotted, head solid). The head side is the **working tree** (summary says "+ uncommitted changes" when dirty).

Read `summary.md` in this order:

1. **Inputs** — files vs. effective series. Series identical ⇒ inputs ruled out.
2. **Per-slot series** — time axis first (`slots only in base/head` ⇒ window / horizon logic changed), then input series (`pv_kw`, `baseload_kw`, `k_act`, `k_push_act`), then decisions (`batt_action_kw`, `sim_soc`, `export_kwh`, `import_kwh`).
3. **Physical plausibility** of the head series: PV at night, constant values, SoC outside limits, export while importing. Implausible ⇒ bug, regardless of commit messages.

L1 cases have no per-slot trace (replay exposes slot 0); compare metrics, `plan_hash` and input files.

## 5. Bisect (code changes only)

Never bisect in the main checkout (other sessions / uncommitted work). Use a worktree **next to the repo** — short enough for Windows MAX_PATH; never directly under a drive root (`C:\…`), never under the deep temp/scratchpad dirs:

```powershell
git worktree add --detach ..\earnie-bisect-wt HEAD
cd ..\earnie-bisect-wt
git bisect start HEAD <baseline-sha>
git bisect run <earnie-root>\.venv\Scripts\python.exe -m scripts.run_regression --case REG-X --workers 1 --report backtesting_logs/regression/bisect_report.md
git bisect reset
cd <earnie-root>; git worktree remove --force ..\earnie-bisect-wt
```

- Exit 1 = bad, 0 = good; **any other error also counts as bad** (e.g. a commit where the case could not run). Confirm the reported first bad commit by checking that its metric moves like the red case (compare-at that commit vs. its parent).
- Old commits may need `earnie_env/config` (gitignored); `--compare-at` does not (it binds the offline fixtures).

## 6. Classify

| Class | Evidence needed | Action (after user OK) |
|---|---|---|
| **Bug** | Implausible series, or behaviour change not intended by the causing commit (message, backlog item, docs) | Fix; skill bugfix-regression-test; golden stays |
| **Intended change** | Causing commit / backlog item states the new behaviour; series plausible | `--update-golden --case X` from a clean tree (refuses otherwise); commit message with reason, metric delta (from summary.md) and causing commit |
| **Test data / environment** | Inputs changed without a code reason (cache, mock leak, fixture drift) | Fix isolation / fixture; golden stays |

## 7. Report

One block per case: verdict, evidence (2–3 numbers or series from summary.md), causing commit (if any), recommended action. Link `summary.md` / `plot.html`.

## Don'ts

- No `--update-golden` before the cause is classified; no widening tolerances to turn a case green.
- No `git push --no-verify` past a red pre-push without the user's explicit OK.
- Never create worktrees or output directories directly under a drive root.
- Do not delete caches or fixtures to "fix" a case without saying what they contained (move aside, keep evidence).
