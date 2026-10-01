---
name: bugfix-regression-test
description: >-
  After each code bugfix, remind to add a regression test and propose a concrete
  test (prefer a dedicated regression file; cite GitHub issue when available).
  Use when implementing a bugfix from backlog/Backlog-Bugfixes.md, fixing a
  GitHub issue, moving a fix to Bugfix Verifications Pending, or during
  session-abschluss if the session included a code bugfix.
---

# Bugfix Regression Test

Soft gate: for every **code** bugfix, remind and **propose** an appropriate
regression test so the same failure cannot silently return. Do **not** block
the fix or backlog move if the user declines — record the skip reason briefly.

## When this skill applies

- Implementing or finishing a code bugfix (`backlog/Backlog-Bugfixes.md`, GitHub issue, or ad-hoc prod deviation)
- Session-abschluss Phase 1 if the session included a code bugfix (see [session-abschluss](../session-abschluss/SKILL.md))

## Exceptions (no new test required)

State the exception once; do not invent a worthless test:

| Exception | Action |
|-----------|--------|
| `## Document Review Findings` | Docs-only — skill `doc-review-findings`; skip |
| Pure config / env / deployment mistake (wrong host path, mis-edited live JSON, compose pin) with **no** wrong code path | Note in backlog / reply; skip |
| Live Miniserver / hardware-only (credentials, physical device) | Prefer `pytest.mark.skip` / existing live pattern if a thin unit edge exists; otherwise skip with reason |
| User explicitly declines a regression test | Note decline; continue |

## Workflow (remind + propose)

Copy and track:

```
Bugfix regression:
- [ ] 1. Identify the failure (symptom, wrong values, trigger inputs)
- [ ] 2. Decide: new regression file vs extend existing test module
- [ ] 3. Propose the test to the user (name, assertion, fixture/inputs)
- [ ] 4. If accepted: implement, run focused pytest, then continue backlog move
- [ ] 5. If declined / exception: one-line reason in chat (and backlog note if useful)
```

### Step details

1. **Reproduce in the test** — Prefer the smallest inputs that failed before the fix (CSV snippet, synthetic series, config fragment). If a user dump exists under `debug-dumps/`, use **anonymized / minimal** fixtures under `tests/fixtures/` — do not commit secrets or full customer dumps.

2. **Where to put the test**
   - **Prefer a dedicated regression file** when the case is dump/fixture-driven or spans modules, e.g. `tests/test_<topic>_regression.py` (see `tests/test_prod_dump_regression.py`).
   - Extend an existing focused `tests/test_*.py` only when the bug is clearly local to that module’s suite.
   - Name the test function after the bug, not the fix method.

3. **GitHub / backlog reference** — In the module or test docstring, cite when available:
   - GitHub: `#N` or full issue URL (`https://github.com/JochenTCC/Earnie/issues/N`)
   - Backlog wording or short symptom line if no issue

   Example:

   ```python
   def test_hourly_baseload_held_across_qh_slots():
       """Regression: #24 hourly Gesamt-CSV must ZOH into 15-min slots (not ÷4 energy)."""
       ...
   ```

4. **Propose before writing (default)** — In chat, propose:
   - Target file path
   - One-sentence failure mode the test locks in
   - Key assertion(s)
   - Fixture source (inline / `tests/fixtures/…`)

   Then implement only if the user accepts, or if they already asked to fix *and* add a test in the same turn.

5. **Run** — After adding the test:

   ```powershell
   $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
   .venv\Scripts\python.exe -m scripts.run_pytest tests/test_<file>.py -q --tb=short
   ```

6. **Backlog** — When moving the item to `## Bugfix Verifications Pending`, briefly note the regression test path (or “no test: &lt;exception&gt;”).

## Quality bar

- The test should fail on the **pre-fix** behavior (conceptually) and pass after the fix.
- Avoid mock-only “tests” that never exercise the buggy path.
- Prefer deterministic unit/integration over live network.
- Do not invent large generated datasets — ask first (test-data-generation rule).

## Related

- Bugfix lifecycle: [`.cursor/rules/backlog.mdc`](../../rules/backlog.mdc)
- Test health / protected regressions: [`.cursor/rules/test-health.mdc`](../../rules/test-health.mdc)
- Session check: [session-abschluss](../session-abschluss/SKILL.md)
