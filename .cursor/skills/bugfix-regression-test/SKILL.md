---
name: bugfix-regression-test
description: >-
  After each code bugfix, remind to add a regression and propose a concrete one:
  a pytest regression (A; prefer a dedicated regression file, cite the GitHub
  issue) and/or, when a debug dump with recorder/ shows the bug in a compared
  metric, a private golden case (B) in Earnie-regression-private with a
  red→green proof. Use when implementing a bugfix from backlog/Backlog-Bugfixes.md,
  fixing a GitHub issue, intaking a customer debug dump as a regression case,
  moving a fix to Bugfix Verifications Pending, or during session-abschluss if
  the session included a code bugfix.
---

# Bugfix Regression Test

Soft gate: for every **code** bugfix, remind and **propose** an appropriate
regression so the same failure cannot silently return. Do **not** block the fix,
commit, or backlog move if the user declines — record the skip reason briefly.

Two kinds of regression (spec: [regression-suite.md §3a](../../../docs/spec/regression-suite.md)):

| Kind | Where | Runs |
|------|-------|------|
| **A — Pytest regression** | Public `tests/test_*_regression.py` (or focused module), small scrubbed / synthetic inputs | Every commit |
| **B — Golden case** | Private `Earnie-regression-private` (`REG-<issue>-<slug>`) for customer data; public `tests/regression/cases/` (`REG-O-` / `REG-S-`) only for synthetic or explicitly accepted own data | Before release (`run_regression`) |

## When this skill applies

- Implementing or finishing a code bugfix (`backlog/Backlog-Bugfixes.md`, GitHub issue, or ad-hoc prod deviation)
- A customer / production debug dump should become a regression case
- Session-abschluss Phase 1 if the session included a code bugfix (see [session-abschluss](../session-abschluss/SKILL.md))

## Exceptions (no new test required)

State the exception once; do not invent a worthless test:

| Exception | Action |
|-----------|--------|
| `## Document Review Findings` | Docs-only — skill `doc-review-findings`; skip |
| Pure config / env / deployment mistake (wrong host path, mis-edited live JSON, compose pin) with **no** wrong code path | Note in backlog / reply; skip |
| Live Miniserver / hardware-only (credentials, physical device) | Prefer `pytest.mark.skip` / existing live pattern if a thin unit edge exists; otherwise skip with reason |
| User explicitly declines a regression | Note decline; continue |

## Triage: A, B, both, or neither

Decide before fixing — golden **B** needs a baseline recorded on the **unfixed** code.

- **B** only when **all** hold:
  1. A debug dump with `recorder/` exists (schema v3, cycle recorder on).
  2. The bug is plan / optimizer behaviour.
  3. It shows up in something the suite compares ([regression-suite.md §7](../../../docs/spec/regression-suite.md)): a hard invariant (SoC limits, energy balance, EV deadline, export limit, write to unavailable functions) or a metric (total cost, grid import / export, self-sufficiency, battery cycles, per-consumer energy).

  A bug visible only elsewhere (heat-store temperature curve, UI value, live write) passes a golden unchanged → **A**. Not every dump becomes a case: a recorder dump carries days of load profile, so archive customer data only when it adds a check (data minimisation).
- **A** for logic bugs reproducible with small scrubbed inputs, and for anything golden **B** cannot see.
- **Both** when the dump-level behaviour should be locked *and* a fast per-commit guard is cheap.
- **Neither**: an exception from the table above; note the reason.

**Own data** (maintainer installation, e.g. NAS productive) follows the same rules and still contains a real load profile → **private** by default. A public `REG-O-` case only from data the maintainer explicitly accepts as public (until the P3 scrubber exists).

## Checklist (bug → release)

Copy and track; skip the B steps when triage says A only:

```
Bug → release:
- [ ] 0. Issue URL (B: mandatory) / backlog entry / dump path known?
- [ ] 1. Triage: pytest A / golden B / both / exception (B only if visible in compared metrics)
- [ ] 2. If B: pick cycle; --intake --private + selector; pre-fix baseline reproduces symptom?
- [ ] 3. Fix code; propose pytest A; propose PATCH; commit + push Earnie (user OK)
- [ ] 4. If B: red on expected metric only → --update-golden; private commit with delta + Earnie SHA; push (user OK)
- [ ] 5. Full run_regression --workers N: no unexpected deltas
- [ ] 6. Move to Verifications Pending (note commit + test paths)
- [ ] 7. After live OK: Erledigt + issue comment
- [ ] 8. Remind: private repo clean/pushed + run_regression before next tag
```

All PowerShell blocks assume the UTF-8 env in the same shell:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
```

## A — Pytest regression (remind + propose)

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
   .venv\Scripts\python.exe -m scripts.run_pytest tests/test_<file>.py -q --tb=short
   ```

## B — Golden case (private intake → red→green → lock)

Propose the B path in chat first (case ID, chosen cycle, metric expected to move); continue only after the user agrees. Never commit or push either repo without the user's OK.

### B1. Issue number

The private case ID is `REG-<issue>-<slug>`; `--intake` rejects any other shape. If the report came by mail or Streamlit Kontakt without an issue, the maintainer opens a public issue first — **symptom + version only**, no names, addresses or load profiles. You may draft the issue text; opening it is the user's action (or needs their explicit OK). Cite the issue `JochenTCC/Earnie#N` in the `Backlog-Bugfixes.md` entry; person names → stable aliases (`backlog-anonymize-users.mdc`).

### B2. Pick the cycle

Each entry in the dump's `recorder/cycles_*.jsonl.gz` carries `planning_window.seed_anchor`. Choose the cycle closest to the symptom time from the issue / report. No listing command exists yet; to print the anchors:

```powershell
.venv\Scripts\python.exe -c "import gzip,json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); [print((json.loads(l).get('planning_window') or {}).get('seed_anchor')) for n in sorted(x for x in z.namelist() if 'recorder/cycles_' in x and x.endswith('.jsonl.gz')) for l in gzip.decompress(z.read(n)).decode('utf-8').splitlines() if l.strip()]" DUMP.zip
```

Prefer `--seed-anchor` (exact). `--cycle-index N` (0-based over all segments, sorted) is the fallback. An unknown anchor or out-of-range index fails loud and prints the cycle count.

### B3. Intake (private)

```powershell
.venv\Scripts\python.exe -m scripts.run_regression --intake DUMP.zip --id REG-<issue>-<slug> --private --seed-anchor "<anchor>" --issue JochenTCC/Earnie#<issue>
```

- `--private` is mandatory for customer dumps — never `tests/regression/cases/` or `scripts/archive_prod_dump.py` for personal data.
- Optional: `--title "..."` (default: dump `meta.title`), `--force` to overwrite an existing case dir.
- Dump without `recorder/` fails loud → ask for a newer dump or fall back to **A** only. No synthetic fallback.
- Intake does **not** write `expected.json`.

### B4. Pre-fix baseline (uncommitted)

On the **unfixed** code, record a throwaway golden:

```powershell
.venv\Scripts\python.exe -m scripts.run_regression --update-golden --case REG-<issue>-<slug>
```

- Do **not** commit this `expected.json`.
- Check that the baseline actually shows the symptom (wrong metric / violated invariant). If it does not, the case cannot guard this bug → drop **B**, use **A**, and tell the user (and whether to keep or delete the intaken case dir).
- Optionally commit only `case.yaml` + `recorder/` in `Earnie-regression-private` now (separate repo, user OK), or defer the whole case to B6.

### B5. Fix (Earnie)

1. Implement the code fix; propose pytest **A** as well if useful (§A).
2. Focused pytest green.
3. Propose a **PATCH** bump of `version.py` (completed bugfix → PATCH only) and wait — **never change `version.py` without explicit approval** (`versioning.mdc`).
4. Commit (and push) the Earnie fix **before** the private golden commit, so the golden can cite an existing public SHA.

### B6. Red → green proof, then lock

```powershell
.venv\Scripts\python.exe -m scripts.run_regression --case REG-<issue>-<slug>
```

1. Against the pre-fix baseline the run must differ **exactly** on the metric that carried the symptom (or the invariant violated in the baseline now passes). Unexpected extra deltas → understand them with the user before going on.
2. Lock the corrected behaviour:

   ```powershell
   .venv\Scripts\python.exe -m scripts.run_regression --update-golden --case REG-<issue>-<slug>
   ```

3. Commit `expected.json` (plus `case.yaml` / `recorder/` if not yet committed) in **`Earnie-regression-private`**. Message: the behaviour now locked, the metric delta from step 1 and the Earnie commit SHA, e.g.

   ```text
   REG-142-eauto-deadline: lock EV full at deadline.

   ev_1 energy 18.2 → 24.0 kWh, grid import +5.8 kWh (pre-fix baseline → fix).
   Earnie 1a2b3c4d.
   ```

   Then push (user OK).

### B7. Full suite

Run public + private, so other goldens shifted by the fix surface now, not at release (`--workers N` = largest useful N, `backtesting-max-workers.mdc`):

```powershell
.venv\Scripts\python.exe -m scripts.run_regression --workers N
```

Every red case → fix, or a conscious `--update-golden` with its own rationale commit. Pytest **A** only: skip B1–B6, still run B7 when the fix touches optimizer / plan code.

## Backlog and issue

- When moving the item to `## Bugfix Verifications Pending`, note commit / version and the regression paths: pytest file and/or `REG-…` case (or “no test: &lt;exception&gt;”).
- After live / prod acceptance: archive to `backlog/Backlog-Erledigt.md` (dated heading).
- Close or comment on the public issue (user OK): “Fixed in v…; guarded by private case REG-… / pytest …” — case ID only, no customer data.
- Remind before the next tag: `Earnie-regression-private` clean and pushed, `run_regression` run ([release-checklist.md §1](../../../docs/spec/release-checklist.md)).

## Quality bar

- The regression must fail on the **pre-fix** behaviour and pass after the fix — for **A** conceptually, for **B** demonstrated by the B6 metric delta, not just by recording a new golden.
- Avoid mock-only “tests” that never exercise the buggy path.
- Prefer deterministic unit/integration over live network.
- Do not invent large generated datasets — ask first (test-data-generation rule).
- Customer data stays private: public tree / issue get case IDs and scrubbed fixtures only ([regression-suite.md §6](../../../docs/spec/regression-suite.md)).

## Related

- Golden suite spec: [`docs/spec/regression-suite.md`](../../../docs/spec/regression-suite.md)
- Release gate: [`docs/spec/release-checklist.md`](../../../docs/spec/release-checklist.md) §1
- Bugfix lifecycle: [`.cursor/rules/backlog.mdc`](../../rules/backlog.mdc)
- Test health / protected regressions: [`.cursor/rules/test-health.mdc`](../../rules/test-health.mdc)
- Session check: [session-abschluss](../session-abschluss/SKILL.md)
