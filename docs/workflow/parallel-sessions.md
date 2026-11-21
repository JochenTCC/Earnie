# Parallel agent sessions: worktrees and the test queue

Several Claude Code / Cursor sessions often work on this repo at the same time on one PC. Two things keep them from tripping over each other:

1. **Test queue** – heavy test runs (pytest suite, regression suite) run one after another, machine-wide.
2. **Worktree per session class** – sessions that change code (or must see a fixed code state) work in their own git worktree, so a test run never sees another session's half-finished edits.

Rule for agents: `.cursor/rules/parallel-sessions.mdc`.

## 1. Test queue (`scripts/suite_queue.py`)

`scripts.run_pytest` and `scripts.run_regression` enter a machine-wide FIFO queue before they start. Only one heavy run executes at a time, with full `-n auto` / `--workers`; others wait and print their position and the run ahead of them:

```text
[test-queue] waiting (position 2/2) - pytest -n auto tests -q --tb=short [earnie-wt\fix-pv-cap]
[test-queue]   ahead: pytest -n auto tests -q --maxfail=5 ... [Earnie] (pid 4711, running 1:12, cwd C:\dev\Earnie)
[test-queue] starting after 1:40 wait - pytest -n auto tests -q --tb=short [earnie-wt\fix-pv-cap]
```

| Run | Queued? | Default workers |
|-----|---------|-----------------|
| `run_pytest` with no target or any **directory** target (`tests`, `tests/regression`) | yes | `-n auto` |
| `run_pytest` with ≤ 3 explicit **files / node ids** (`tests/test_x.py::test_y`) – fast lane | no | `-n 2` |
| `run_pytest --collect-only` / `--dead-fixtures` | no | sequential |
| `run_regression` (suite and `--compare-at`) | yes | `--workers` as given |
| git hooks (`pre-commit`, `pre-push`) | yes (they call the two scripts) | as above |

Overrides (wrapper flags, not passed to pytest): `--queue` forces queueing (e.g. a large single file), `--no-queue` skips it. `EARNIE_TEST_QUEUE=off` disables the queue entirely (CI containers).

Mechanics:

- Queue directory: `%LOCALAPPDATA%\earnie\test-queue` (Windows), `~/.cache/earnie/test-queue` otherwise; override with `EARNIE_TEST_QUEUE_DIR`. It is outside the repo on purpose, so all worktrees share one queue.
- Each waiting/running process owns a ticket file (FIFO by creation time) and refreshes it every 5 s. The running process also holds an OS file lock (`run.lock`), which is the hard guarantee that only one run executes.
- A ticket whose process is gone or whose heartbeat is older than 60 s is removed by the next waiter: a killed or crashed run never blocks the queue for longer than that.
- Nested runs do not queue again: the running process exports `EARNIE_TEST_QUEUE_HELD=1`, and `tests/conftest.py` sets it for every test session.

Inspect the queue:

```powershell
.venv\Scripts\python.exe -m scripts.suite_queue status
```

### Agents: long waits and the Bash tool timeout

A queued full run can take queue wait + ~2.5 min. Claude Code's Bash tool stops foreground commands after at most 10 min, so start the full suite with `run_in_background: true` and wait for the completion notice (no sleep/poll loop). A killed run frees its slot automatically (see above).

## 2. Worktrees per session class

The main checkout (`<earnie-root>`, e.g. `C:\dev\Earnie`) is the **integration checkout**: the user's own working copy, backlog maintenance, docs-only work, session conclusion. Sessions of the classes below work in their own worktree **next to** the repo:

| Class | When | Worktree | Branch |
|-------|------|----------|--------|
| `review` | Code review of a branch, PR or commit range | `..\earnie-wt\review-<slug>` | none: `--detach` on the reviewed ref; read-only |
| `fix` | Bugfix (backlog `Backlog-Bugfixes.md`, user report) | `..\earnie-wt\fix-<slug>` | `fix/<slug>` from `main` – or from `release/x.y` per the hotfix playbook |
| `hotfix` | Urgent patch for a tagged build | `..\earnie-wt\hotfix-<slug>` | `hotfix/<slug>` from the tag (`docs/workflow/branching-hotfix-playbook.md`) |
| `feat` | Backlog feature / refactoring with code changes | `..\earnie-wt\feat-<slug>` | `feat/<slug>` from `main` |
| `port` | Cherry-pick fixes onto a release line | `..\earnie-wt\port-<slug>` | `port/<slug>` from `release/x.y` |
| `spike` | Experiment / prototype that may be thrown away | `..\earnie-wt\spike-<slug>` | `spike/<slug>` |
| `bisect` / `compare` | Regression triage | `..\earnie-bisect-wt`, `..\earnie-compare-wt` (existing, see skill `regression-triage`) | detached |

**Stays in the main checkout:** docs-only and backlog edits, questions and analysis without edits, release-notes drafts, session conclusion / merge of finished branches, and any work while it is the only active session.

`<slug>`: short kebab-case, preferably with the backlog ID (`fix-b123-pv-cap`). Keep paths short (Windows MAX_PATH) and never directly under a drive root. Do not use Claude Code's built-in `--worktree` / `.claude/worktrees/` location – it nests worktrees inside the repo with long paths.

### Create

```powershell
cd <earnie-root>
git fetch origin
git worktree add -b fix/b123-pv-cap ..\earnie-wt\fix-b123-pv-cap origin/main
cd ..\earnie-wt\fix-b123-pv-cap
```

Review (no branch):

```powershell
git worktree add --detach ..\earnie-wt\review-pr42 origin/<branch-under-review>
```

### Python / tests inside a worktree

A worktree has no `.venv`; use the main checkout's interpreter, **started from the worktree root** (so the worktree's code is imported, not the main checkout's):

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
<earnie-root>\.venv\Scripts\python.exe -m scripts.run_pytest tests -q --tb=short
```

The git hooks find the main checkout's `.venv` themselves. The default test configuration uses fixtures (`tests/fixtures/backtesting/config.json`), so the gitignored `earnie_env/` is not needed; only live-config tests (`EARNIE_TEST_USE_LIVE_CONFIG=1`) are skipped there.

After changing `requirements*.txt` / `pyproject.toml` dependencies in a worktree, the shared venv changes for every session: say so and coordinate with the user before installing.

### Finish

1. Commit and push the branch from the worktree (hooks run there, queued).
2. Integrate per the branching playbook (PR to `main`, or merge in the main checkout at session conclusion – ask the user which).
3. Remove the worktree once the branch is merged or abandoned:

```powershell
cd <earnie-root>
git worktree remove ..\earnie-wt\fix-b123-pv-cap
git branch -d fix/b123-pv-cap
```

`git worktree list` shows leftovers; `git worktree prune` cleans entries whose directory is gone.
