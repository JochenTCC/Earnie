# Parallel agent sessions: shared checkout and the test queue

Several Claude Code / Cursor sessions often work on this repo at the same time on one PC. Two things keep them from tripping over each other:

1. **Test queue** – heavy test runs (pytest suite, regression suite) run one after another, machine-wide.
2. **Shared checkout** – parallel sessions edit disjoint files and run targeted tests only; the parent session runs one joint full suite at the end.

Rule for agents: `.cursor/rules/parallel-sessions.mdc`.

## 1. Test queue (`scripts/suite_queue.py`)

`scripts.run_pytest` and `scripts.run_regression` enter a machine-wide FIFO queue before they start. Only one heavy run executes at a time, with full `-n auto` / `--workers`; others wait and print their position and the run ahead of them:

```text
[test-queue] waiting (position 2/2) - pytest -n auto tests -q --tb=short [Earnie]
[test-queue]   ahead: pytest -n auto tests -q --maxfail=5 ... [Earnie] (pid 4711, running 1:12, cwd <earnie-root>)
[test-queue] starting after 1:40 wait - pytest -n auto tests -q --tb=short [Earnie]
```

| Run | Queued? | Default workers |
|-----|---------|-----------------|
| `run_pytest` with no target or any **directory** target (`tests`, `tests/regression`) | yes | `-n auto` |
| `run_pytest` with ≤ 3 explicit **files / node ids** (`tests/test_x.py::test_y`) – fast lane | no | `-n 2` |
| `run_pytest --collect-only` / `--dead-fixtures` | no | sequential |
| `run_regression` (suite and `--compare-at`) | yes | `--workers` (default min(CPU, case count)) |
| git hooks (`pre-commit`, `pre-push`) | yes (they call the two scripts) | as above |

Overrides (wrapper flags, not passed to pytest): `--queue` forces queueing (e.g. a large single file), `--no-queue` skips it. `EARNIE_TEST_QUEUE=off` disables the queue entirely (CI containers).

Mechanics:

- Queue directory: `%LOCALAPPDATA%\earnie\test-queue` (Windows), `~/.cache/earnie/test-queue` otherwise; override with `EARNIE_TEST_QUEUE_DIR`. It is outside the repo on purpose, so all clones share one queue.
- Each waiting/running process owns a ticket file (FIFO by creation time) and refreshes it every 5 s. The running process also holds an OS file lock (`run.lock`), which is the hard guarantee that only one run executes.
- A ticket whose process is gone or whose heartbeat is older than 60 s is removed by the next waiter: a killed or crashed run never blocks the queue for longer than that.
- Nested runs do not queue again: the running process exports `EARNIE_TEST_QUEUE_HELD=1`, and `tests/conftest.py` sets it for every test session.

Inspect the queue:

```powershell
.venv\Scripts\python.exe -m scripts.suite_queue status
```

### Agents: long waits and the Bash tool timeout

A queued full run can take queue wait + ~2.5 min. Claude Code's Bash tool stops foreground commands after at most 10 min, so start the full suite with `run_in_background: true` and wait for the completion notice (no sleep/poll loop). A killed run frees its slot automatically (see above).

## 2. Parallel sessions in one checkout

There is one clone per line (`main`, and one per open `release/x.y`) and no worktrees: parallel sessions on a line share its checkout. A full test run therefore sees the half-finished edits of the other sessions, and several `-n auto` runs at once fight over the CPU. One joint run at the end is the only meaningful one. Canonical rules and the brief block to paste: skill `parallel-sessions` (`earnie-workspace/ai/skills/parallel-sessions/SKILL.md`).

Child sessions:

- edit only the files and functions named in their brief; two sessions never edit the same function;
- put new tests into a new test file of their own;
- run only their new tests and the existing tests of the code they change: no full suite, no `scripts.run_regression`, no backtesting / Scenario Explorer runs;
- do not commit, push or switch branches;
- report changed files, the targeted test result and open questions.

Parent session: wait until every child reported, check `git status` for foreign changes, run the full suite and `scripts.run_regression` once, send red tests back to the owning session, then ask the user the commit target once for all changes.

Work for another line (e.g. a cherry-pick onto `release/x.y`) is done in that line's clone, not here. Regression triage with `--compare-at` creates a temporary worktree under `..\earnie-compare-wt` and removes it afterwards (skill `regression-triage`).

After changing `requirements*.txt` / `pyproject.toml` dependencies, the shared venv changes for every session: say so and coordinate with the user before installing.
