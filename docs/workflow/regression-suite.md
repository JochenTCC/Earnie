# Specification: Release Regression Suite (golden-master cases)

**Version:** 0.5 (P2 private + intake)  
**Status:** R-Rec + R0 (reduced) + P1 + **P2** done in Version 2.7; L3 and P3 follow in Version 2.8  
**Epic short name:** **Regression** (phases **R0**, **R-Rec**, **P1**–**P3**, **L3**)  
**Related:** [Release Checklist](release-checklist.md), [House simulator](../dev/house-sim.md), [Shadow Mode](../dev/shadow-mode.md), `tests/fixtures/prod_dumps/README.md`, `.cursor/rules/test-health.mdc`, `optimizer/cbc_solver.py`

## 1. Goal

Make sure Earnie's **behaviour does not change unnoticed or unintentionally** between releases.

- A **case** fixes the inputs of an optimizer run (config, consumption, prices, PV forecast, start state). L1 cases freeze them in a recorder cycle; **L2 cases share `tests/fixtures/backtesting/`, derive prices in code and read PV / temperature from a frozen Open-Meteo fixture (§8)**, so their effective inputs can still drift through code changes — the input fingerprint (§7, tier 4) makes that visible.
- The runner executes Earnie offline and deterministically, condenses the result into a few numbers, and compares them against a committed **golden** reference.
- A deviation is not automatically a bug. The maintainer decides at release time: *bug* → fix; *intended change* → re-record the golden with a justification in the commit.
- Cases may contain **customer data**. Those cases never enter the public repository, but each can still be referenced from a public issue.

The suite is **not** part of the pytest run. It runs **before a release / publish**, and until further notice also in the pre-push hook (§8).

## 2. Scope

| In scope | Out of scope |
|---|---|
| Case format, runner, golden compare, report | Replacing the unit test suite or `test_prod_dump_regression.py` invariants (kept, see §10) |
| Public cases (synthetic / own data) and private cases (customer data) | Live comparison Prod vs. Shadow per slot (see Shadow **S4**) |
| Intake script: debug-dump ZIP → case folder | Performance / load benchmarks |
| Scrub / anonymization script (phase **P3**) | Storing customer data in any public repo or public CI artifact |
| Release gate (checklist first, CI job later) | UI screenshot comparison (covered by AppTest) |

## 3. Terms

| Term | Meaning |
|---|---|
| **Case** | Folder with frozen inputs + `expected.json` (§5). |
| **Golden** | The committed `expected.json`. Changed only on purpose. |
| **L1 — cycle replay** | One optimizer cycle with a given state (what the prod-dump replay does today). |
| **L2 — backtest window** | Several days to weeks via the backtesting engine (behaviour over time, simulated state carried through the window). |
| **L3 — live replay** | A sequence of *recorded* production cycles replayed one by one, each starting from the **measured** state of that cycle (§15). Not the same as L2: no simulated state, no accumulated drift. |
| **Recorder** | Always-on production component that stores the inputs and outputs of every optimizer cycle in a ring buffer (§14). |
| **Public case** | Synthetic or maintainer-owned data; lives in the main repo. |
| **Private case** | Customer data; lives in the private repo `Earnie-regression-private`. |

### 3a. Pytest regression (A) vs. golden case (B)

A bugfix can be guarded in two ways. Keep both; do not collapse them.

| Kind | Where | When to use |
|---|---|---|
| **A — Pytest regression** | Public `tests/test_*_regression.py` (or a focused module) | Small, scrubbed / synthetic inputs; runs every commit. Prefer for logic bugs that do not need full customer matrices, and for bugs that are **not visible in the compared metrics** (below). |
| **B — Golden case** | Public `tests/regression/cases/` (`REG-O-` / `REG-S-`) or private `Earnie-regression-private` (`REG-<issue>-<slug>`) | Behaviour lock across releases; customer data → **private only**. Runs before release (`run_regression`), not per commit. |

**A golden only guards what §7 compares:** hard invariants (SoC limits, energy balance, EV deadline, export limit, unavailable functions) and metrics (total cost, grid import / export, self-sufficiency, battery cycles, per-consumer energy). A bug that only shows up elsewhere (heat-store temperature curve, UI value, live write) passes a golden unchanged — use **A** for it.

**Minimum bar for B:** the debug dump has `recorder/` (§14), the bug is plan / optimizer behaviour, **and** it is visible in a compared invariant or metric. A **B** case is locked only after a red→green proof: a pre-fix baseline (uncommitted) reproduces the symptom, and the fixed run differs exactly on that metric before `--update-golden`.

The step-by-step agent workflow (triage, intake, baseline, fix, lock, full run, Verifications Pending) lives in skill `bugfix-regression-test` (`.cursor/skills/bugfix-regression-test/SKILL.md`); analysing a red case (bug vs. intended change vs. test data) in skill `regression-triage` (`.cursor/skills/regression-triage/SKILL.md`); release reminders in [release-checklist.md](release-checklist.md) §1.

## 4. Repository split

| What | Where | Content |
|---|---|---|
| Runner, case schema, marker | Public `Energy-Optimizer` | `scripts/run_regression.py`, `tests/regression/` |
| Public cases | Public, `tests/regression/cases/` | HouseSim output, own data |
| Private cases | Private repo `Earnie-regression-private`, sibling checkout | raw or scrubbed customer data |

A plain private Git repo is enough: a case is about 1 MB (CSV + JSON). Switch to Git LFS only if the repo grows noticeably. No DVC / object store.

The runner reads **two roots**: `tests/regression/cases/` and `$EARNIE_REGRESSION_PRIVATE_DIR` (default: `..\Earnie-regression-private\cases`, analogous to `link_private_env.ps1`). If the private root is missing, private cases are **skipped** (reported as skipped, not silently dropped) so external contributors can still run the public part.

**Hard rules**

- Raw customer data never enters `Energy-Optimizer`, not even temporarily on a branch (the public history was scrubbed once already).
- CI artifacts / logs of a run that included private cases must not be published; the report only contains aggregated numbers and case IDs.

## 5. Case format

```
<case-id>/
  case.yaml        # metadata
  inputs/          # config.json, components.json, consumption csv, prices, pv forecast, start state
  expected.json    # golden metrics + tolerances
```

`case.yaml`:

```yaml
id: REG-142-eauto-deadline        # see §6
title: E-car not full at deadline
level: L1                          # L1 | L2
source: customer                   # synthetic | own | customer
anonymized: false
issue: JochenTCC/Earnie#142        # optional, public issue reference
app_version: 2.6.0                 # version the inputs were recorded with
window: {start: "2026-06-26T18:00", end: "2026-06-27T10:00"}   # L2 / L1 context
```

`expected.json` holds the result tiers of §7 plus the engine fingerprint used for the golden (Earnie version, CBC/solver version), and optionally:

- `baseline` — `{git_sha, recorded_at, source}`: the public commit the golden was recorded from. `source: update-golden` (written by the runner) or `git-log-backfill` (last commit touching `expected.json`, for goldens older than this field; public cases only).
- `inputs` — `{files, series, sums}`: input fingerprint of the golden run (tier 4). Written by `--update-golden`; never backfilled.

Existing `tests/fixtures/prod_dumps/<id>/` cases are migrated into this format in **P1**; their hand-written invariants become tier-1 checks.

## 6. Case IDs and issue references

- Schema: `REG-<issue-number>-<slug>` for issue-driven cases, `REG-S-<slug>` for synthetic ones, `REG-O-<slug>` for own data.
- **Issue number is mandatory** for private customer cases: `--intake` rejects IDs that do not match `REG-<number>-<slug>`. A report without an issue (mail, Streamlit Kontakt) first gets a public issue from the maintainer — symptom + version only.
- A **public issue** only says: *"Reproduced in private case REG-142"*. No customer name, no addresses, no load profiles, no data.
- **Public issue / public Earnie tree:** case IDs and scrubbed pytest fixtures only.
- **Private repo:** raw customer recorder data with `source: customer`, `anonymized: false`.
- **Own data** (maintainer installation) still carries a real load profile → private by default; a public `REG-O-` case only from data the maintainer explicitly accepts as public (until the P3 scrubber exists).
- The mapping from case to customer lives **only** in the private repo (`cases/REG-142/case.yaml` + a local alias, same stable aliases as `.cursor/rules/backlog-anonymize-users.mdc`). Real-name ↔ alias maps stay local and are never committed.
- **Data minimisation:** intake a dump only when it adds a check (§3a minimum bar) — not every dump is archived.
- Every report records the **commit SHA of the private repo** (and the public commit) so a release can later be traced to the exact data state. The SHA is taken from `HEAD` only: uncommitted case or golden changes are not visible in it, so the private repo must be clean and pushed before a release run.

## 7. What is compared

Slot-exact equality would break on every solver or float-level change. Three tiers:

1. **Hard invariants** — always fail: SoC within limits, energy balance closes, EV full at deadline, export limit respected, no write to unavailable functions.
2. **Metrics with tolerance** — fail when exceeded: total cost (€), grid import / export (kWh), self-sufficiency, battery cycles, per-consumer energy. Default tolerance **±0.05 %** after R0 (was ±0.5 % placeholder); overridable per metric in `expected.json`.
3. **Plan diff** — informational only: number of slots whose setpoint differs and a plan hash. Shown in the report, never fails. L2 has no plan hash (`n/a`).
4. **Inputs** — informational only, answers *"bug or changed inputs?"* for a red case. Two layers (`tests/regression/fingerprint.py`):
   - `files`: digests of the input files (L2: every file in `tests/fixtures/backtesting/`, recursively — incl. the frozen climate in `open_meteo/` — with canonicalized JSON, plus the case's `inputs:` block; L1: the recorder cycle and its config snapshot).
   - `series`: digests of the per-slot inputs the optimizer actually saw (L2: `pv_kw`, `baseload_kw`, `k_act`, `k_push_act` from the simulation result, rounded to 1e-6), plus readable `sums` (`pv_kwh`, `baseload_kwh`, `k_act_mean`, `n_slots`). L1 has no series layer: matrix preparation runs inside the replay.

   When metrics fail, the report adds a verdict: *effective inputs changed* (check data / input preparation first), *input files changed but effective inputs identical* or *inputs identical* (behaviour change in code → bisect from the baseline).

The solver and its settings must be identical for golden recording and verification; the engine fingerprint in `expected.json` makes a mismatch visible instead of producing phantom diffs. **Note:** the production default solver is **HiGHS** (`DEFAULT_MILP_SOLVER`), not CBC, and the production path is wall-clock dependent — see §16 before choosing tolerances or the regression solver mode.

## 8. Runner

```
python -m scripts.run_regression [--cases-dir PATH]... [--case ID] [--workers N]
python -m scripts.run_regression --update-golden --case REG-142-eauto-deadline
python -m scripts.run_regression --compare-at <sha> --case REG-O-summer-june [--keep-worktree]
python -m scripts.run_regression --intake <debug_dump.zip> --id REG-142-eauto-deadline --private \
    --seed-anchor "..." | --cycle-index N
```

- Pytest marker `regression`, **deselected by default** (`tests/conftest.py` removes marked items unless `-m regression` or `EARNIE_RUN_REGRESSION=1`), so the normal suite does not run it. **Until further notice** `.githooks/pre-push` runs `python -m scripts.run_regression` and blocks the push on a red case (skipped when the pushed range only touches docs/PNG/YAML/workspace/Cursor/GitHub/hooks, same list as pre-commit). It tests the working tree, so it refuses — fail loud — when the pushed commit is not `HEAD` or tracked files have uncommitted changes. `.githooks/pre-commit` runs pytest only. Before a release run it explicitly as well; `-m regression` also works.
- `--workers N` per `.cursor/rules/backtesting-max-workers.mdc` (largest useful N). Runtime budget: ≤ 15 min parallel.
- `--update-golden` rewrites `expected.json` only for the selected cases (incl. `baseline` and `inputs`); the commit message must explain the intended behaviour change. It **refuses to run** when the public worktree has uncommitted or untracked changes outside `tests/regression/cases/` — commit the code first, so `baseline.git_sha` is reproducible.
- `--backfill-baseline` adds `baseline` (source `git-log-backfill`) to public goldens that lack it; it runs no cases. Private goldens are skipped: their public code SHA is only known from `--update-golden`.
- `--compare-at <ref>` (with `--case`, L1 / L2 only) checks `<ref>` out into a temporary git worktree (`$EARNIE_COMPARE_WORKTREE_ROOT`, default `..\earnie-compare-wt` next to the repo — short on purpose for Windows MAX_PATH, never directly under a drive root; `--worktree-root` overrides, `--keep-worktree` keeps it) and runs each case there and on the working tree, each in its own process (`tests/regression/trace.py`; Earnie code from that tree, offline fixture config — no `earnie_env` needed; `pv_kw` is added for trees that predate it; the PV-shape guard is recorded, not raised). Output per case in `backtesting_logs/regression/compare/<case>__<sha8>/`: `summary.md` (metrics base / head / Δ, input fingerprint diff, time axis, per-series slots differing and max Δ), `base_slots.csv`, `head_slots.csv`, `diff.csv` and `plot.html` (Plotly overlay, L2 only). Triage workflow: skill `regression-triage` (`.cursor/skills/regression-triage/SKILL.md`).
- Output: console table + `regression_report.md` (Δ per case, tier-3/4 summary, public + private SHA, skipped private-root note, engine fingerprint). Per case: baseline SHA → HEAD with the commit count (total and in code paths); for a red case also the `git bisect start` / `git bisect run` commands for that single case.
- **Climate input is frozen** (`tests/regression/climate_fixture.py`): Open-Meteo irradiance/temperature come only from committed archive responses — L2 from `tests/fixtures/backtesting/open_meteo/`, L1 from `tests/regression/fixtures/open_meteo/` (the replayed MILP's thermal flex context models heat-pump / pool consumers from a calendar-year climate bundle at the config snapshot's lat/lon; the recorded cycle does not carry it). `EARNIE_OPEN_METEO_CACHE_PATH` is ignored inside the block, with the wall clock frozen at `CLIMATE_FIXTURE_NOW` because cache keys contain the last archive day / last full archive year. A missing key raises `ClimateFixtureMissingError` — no network, no `data/cache/open_meteo`. Re-record only deliberately (needs network): `EARNIE_REGRESSION_RECORD_CLIMATE=1 python -m scripts.run_regression --workers 1`, then bump `CLIMATE_FIXTURE_NOW` to the recording date if the keys changed. `assert_pv_day_shape` (`tests/regression/pv_shape.py`) fails an L2 run whose PV is non-zero at night or constant. The input fingerprint digests the climate files: L2 every file under the fixture root, L1 the files the replay actually read (`inputs.files["open_meteo/<file>"]`), so changed climate shows up as an input change, not as a code behaviour change.
- Default roots: `tests/regression/cases/` plus `$EARNIE_REGRESSION_PRIVATE_DIR` (or sibling `..\Earnie-regression-private\cases`). Missing private root → reported as skipped (`private-root-missing`), not silent.

## 9. Intake and anonymization

**Intake (P2)** — `--intake` turns a unified debug-dump ZIP (schema v3, see `scripts/replay_debug_dump.py`) into a private L1 case folder (`source: customer`), assigns the ID and writes `case.yaml` + case-local `recorder/`. Requires `--private` and an explicit cycle selector (`--seed-anchor` or `--cycle-index`). Does not scrub. Does not write `expected.json` (follow with `--update-golden`). Dump without `recorder/` **fails loud** (no synthetic fallback).

**Scrub (P3)** — only needed when a customer case should become public (e.g. as a minimal repro). Whitelist-based: unknown fields are dropped, not copied.

| Data | Treatment |
|---|---|
| Config names, entity IDs, UUIDs, IPs, tokens | replaced by generic identifiers (`battery_1`, `ev_1`); secrets removed |
| Location | free text / address removed; if forecast and prices are frozen in the case the location is not needed in the run; otherwise shift longitude and round latitude to 0.5° |
| Time series | dates stay (prices and PV depend on them); column names / metadata cleaned |
| Load profile | kept (needed for behaviour) — see privacy note |

**Privacy note:** household load profiles are personal data (GDPR). Even scrubbed, they go public only with the customer's documented consent. The default path for customer data is the private repo.

A scrubbed case is a **new** case (`anonymized: true`) with its own golden — scrubbing changes behaviour slightly, so its golden is never reused from the raw case.

## 10. Relationship to existing tests

| Existing | Role afterwards |
|---|---|
| `tests/test_prod_dump_regression.py` + `tests/fixtures/prod_dumps/` | Migrated to cases (P1); the per-commit invariant tests may stay as fast guards |
| Backtesting engine + `backtesting_fingerprint` | Execution engine for L2 cases |
| `house_sim` | Source for synthetic public cases |
| `.cursor/rules/test-health.mdc` | Regression cases are not mutation-tested; the suite stays out of the quality gate |

Before P1 ships, check that `tests/fixtures/prod_dumps/` and `tests/fixtures/backtesting/uploads/` contain no entity names, location or third-party data that must not be public.

## 11. Release integration

- **Initial (P1):** a checklist item in [release-checklist.md](release-checklist.md) §1 *Prepare*: "Regression suite green locally (public + private), report attached to the release notes draft". Data lives on the maintainer machine, so this fits.
- **Later (P3):** a job `regression` in `release-publish.yml` with `needs: release`, listed in `promote`'s `needs`. The private repo is checked out via a deploy key stored as an Actions secret.
- **Gate strength:** starts **soft** (red report, maintainer approves consciously via `promote`); becomes **hard** after a few releases once tolerances have settled.

## 12. Phases

| Phase | Content |
|---|---|
| **Regression R0** (spike) | Solver-determinism / tolerance study (§16). **Done 2026-10-14 (reduced):** strict HiGHS goldens, ±0.05 % default tolerance, `highspy==1.15.1` pin. Full §16 factor matrix optional follow-up. |
| **Regression R-Rec** (recorder) | Always-on cycle recorder with ring buffer (§14), capture-point test (record → replay == live). Prerequisite for R0 and L3; also feeds debug dumps. |
| **Regression P1** (MVP) | Case format + schema, runner (L1 + L2), `--update-golden`, report; 4–6 public cases (winter, summer, negative prices, EV deadline, heat storage); migrate existing prod-dump cases; tolerances and solver mode from R0; checklist item. **Done 2026-10-15:** `scripts/run_regression.py`, `tests/regression/`; prod_dumps as `L1-invariants` only (MILP goldens from recorder-shaped / backtesting fixtures); pytest marker `regression` deselected by default via `tests/conftest.py`. |
| **Regression P2** (customer data) | Private repo `Earnie-regression-private`, private-root support + skip logic, `--intake`, case-ID / issue-reference convention, SHA in report. **Done 2026-10-15:** dual roots + skip, case-local `recorder.root`, `--intake --private` with mandatory selector, public+private SHA in report. |
| **Regression P3** (gate + scrub) | CI job before `promote`, scrubber script + tests, optional metric trend across releases |
| **Regression L3** (live replay) | Replay runner for recorder windows, case creation from a time window (§15). After R-Rec and P1. |

Order: **R-Rec → R0 → P1 → P2 → L3 → P3.**

**Release scope (decided 2026-10-14):** R-Rec, R0 (reduced), P1 and P2 ship with Version 2.7; L3 and P3 follow in Version 2.8. Reason: P1 alone has no safe place for customer data (P2) and no inputs for problems noticed days later (R-Rec); L3 and the CI gate are comfort on top.

## 13. Open decisions

1. Soft vs. hard release gate (§11) — **Decided (P2):** stay **soft** (checklist + maintainer `promote`); hard CI gate is P3.
2. Customer-facing data-handling wording beyond the private repo — **Decided (P2):** dump dialog + `docs/einrichtung/betrieb.md` already disclose recorder contents in dumps and require sharing only with the maintainer; no extra consent prose in P2. Broader contract wording stays out of scope until legal review.
3. Solver pinning: **Decided (R0, 2026-10-14):** pin `highspy==1.15.1` in `pyproject.toml` (local install verified 1.15.1; Docker/CI install from the same pin). Re-verify after any intentional HiGHS bump before trusting goldens.
4. Regression solver mode (§16): **Decided (R0, 2026-10-14):** goldens use deterministic **`EARNIE_CBC_STRICT=1`** (HiGHS, no wall-clock limit). Production-path sample stays open as a follow-up (not required for P1 goldens).
5. Recorder defaults (§14): retention days (default 7). **Decided:** debug dumps include the matching recorder window automatically. **Decided (R-Rec):** default dump window = the **whole ring buffer** (retention days); no UI narrowing in R-Rec (optional narrowing later with L3). ZIP size is accepted as a consequence (~7–14 MB for 7 days).
6. Intake cycle selection / no-recorder fallback — **Decided (P2):** `--seed-anchor` or `--cycle-index` required; dump without `recorder/` fails loud.
7. Bug → golden workflow — **Decided (2026-10-15):** golden **B** is a branch of skill `bugfix-regression-test` (no separate skill); skill `session-abschluss` **warns, never blocks** when a Verifications Pending item cites a `REG-\d+-` case and the private repo is missing, dirty or unpushed (hard gate is P3); minimum bar per §3a. Open follow-ups: a `--list-cycles` helper for the intake selector; a dirty-tree flag next to public / private SHA in the report; deleting a customer's data on request (cases live in private git **history**, so removal needs a history rewrite of `Earnie-regression-private` — process to be defined with the legal review).

## 14. Cycle recorder (R-Rec)

**Purpose:** provide the *complete inputs* of real cycles. `optimization_history.jsonl` only holds results and display values (SoC, mode, target power, current price, forecast values, plan), not the price/PV vectors over the horizon, the configuration or the start state, so it cannot drive a replay on its own.

**Capture point:** the central input is `optimization_matrix` in `main.py` (per slot: `k_act`, `expected_p_pv`, `expected_p_act`, …) plus `planning_window`. Live snapshot / thermal prep run **before** this hook; afterwards the matrix is still modified (`prepare_optimization_matrix`, standby relief), so it is captured **directly before `prepare_optimization_matrix`** — a well-defined replay entry point. The debug snapshot already serializes `planning_matrix` / `planning_window`; the recorder does the same every cycle.

**Entry per cycle:** timestamp, `app_version`, config hash; matrix + window (columnar arrays, not row dicts); start state (SoC, `flexible_consumers_state`, charging contexts, run state, PV counter state); **outputs:** setpoints actually written, plan hash, flags (override, immediate charging, outage, manual intervention).

**Storage:** one gzip JSONL segment per day, `runtime/recorder/cycles_YYYY-MM-DD.jsonl.gz`; ring buffer = delete segments older than N days. Configuration snapshots are stored once per hash and referenced from cycles. Estimate (to be measured): ~10–20 KB per cycle compressed, ~1–2 MB/day, 7–14 MB for 7 days.

**Configuration:** `recorder_retention_days` (default 7), on/off switch; **on by default in production**.

**Robustness:** a recorder failure must never affect the production run (same try/except pattern as `append_production_run`), with a log entry and a counter of lost cycles.

**Privacy:** entries contain load profiles → local only, never uploaded, documented as opt-out in `docs/einrichtung/betrieb.md`. Same line as §9.

**Acceptance test:** record a cycle, replay it offline from the recording, and assert the replay produces the same plan as the live run (under the solver mode of §16). This doubles as the first determinism evidence.

**Debug-dump integration (decided):** the unified debug-dump ZIP (schema v3) automatically contains the matching recorder window (`recorder/` segments plus the referenced config snapshots) — **whole ring buffer** by default. Consequence: **every user report becomes a potential golden case.** `--intake` (P2) turns such a ZIP into a case folder; L3 (§15) cuts the relevant time window from the recorded cycles. The dump manifest records the window (`recorder.from`, `recorder.to`, cycle count, config hashes) as an **optional** `manifest.recorder` block (no schema bump). Dumps without recorder data (older versions, recorder off) stay valid for replay, but `--intake` rejects them (fail loud, no synthetic fallback — §9, §13.6); such reports get a pytest regression instead. Privacy: a dump now carries up to N days of load profile; the dump dialog and `docs/einrichtung/betrieb.md` disclose this and require sharing only with the maintainer.

## 15. L3 live replay

**Question answered:** would the new version have decided differently than the old one in *real* cycles?

- Each cycle is replayed from its recorded inputs and **measured** start state, so every difference is attributable to one cycle (no drift as in L2).
- **Case creation:** select a time window `[t0, t1]` from the recorder ring buffer → cut the cycles → store as a case folder (sequence of L1 cycles, each with inputs, state, recorded outputs).
- **Two comparisons:** (a) replay vs. *recorded* (behaviour change vs. production), (b) replay vs. *golden replay* (behaviour change vs. the last release).
- **Metrics:** share of cycles with a different setpoint, cost Δ over the window, number of mode changes (flapping); plan diff is the primary information here.
- **Caveat:** production decisions are not always pure optimizer decisions (overrides, manual intervention, Loxone immediate charging as in `eauto_false_complete_2026-06-29`, outages). Such cycles are flagged by the recorder and excluded or reported separately.

## 16. Solver determinism and tolerance (R0)

Frozen inputs remove time and price as sources of deviation. What remains is the MILP solver. Findings from `optimizer/cbc_solver.py`:

1. Default solver is **HiGHS** (`threads=1`); CBC is optional. Spec text and fingerprint must name the solver actually used.
2. `solve_with_strict_fallback` is two-stage: a **strict** attempt with a **3 s wall-clock limit**; if not `Optimal`, a fallback with **`gapRel = 10 %`**. Consequences: which stage produces the plan depends on CPU speed and load (also on the same machine, e.g. parallel workers; dev machine vs. NAS), and stage 2 may return any feasible plan within 10 % of the optimum.
3. `optimizer/cbc_events.py` already logs slow strict runs; production logs show how often the fallback occurs.
4. The existing `tests/test_prod_dump_regression.py::_solve_urgent_dump_milp` calls `PULP_CBC_CMD(msg=False)` directly, not the production path.

**Study design (once recordings exist):**

| Factor | Levels |
|---|---|
| Solver | HiGHS (default), CBC for comparison |
| Mode | production path (3 s → 10 %), strict without limit, `gapRel` 1 % |
| Load | idle, N parallel workers |
| Repetitions | 20 per case |
| Input perturbation | none, prices ±0.1 ct |

Per run: stage reached, runtime, objective value, cost (€), plan hash, number of slots differing from the reference (strict without limit). Cases: full 96-slot problems with several consumers and battery (recorder windows or backtesting engine with HouseSim fixtures; **not** the hourly prod-dump scenarios).

**Expected decision:** if strict without limit finishes in acceptable time, goldens use that deterministic mode and tolerances can be tight; otherwise a small `gapRel` with no wall-clock limit as a dedicated regression solver mode, plus a production-path sample so the real path is still exercised. Per-metric tolerances in `expected.json` are derived from the measured spread, not guessed (the ±0.5 % default of §7 is a placeholder until then).

### R0 reduced study result (2026-10-14)

Harness: `scripts/run_regression_r0_study.py` + offline replay `runtime_store/recorder_replay.py`. Cases: 3× 96-slot recorder cycles (seeded via recorder API from historical windows into recorder format; no live prod recorder yet on this machine). Factors: HiGHS only; modes production vs `EARNIE_CBC_STRICT=1`; load idle vs 3 parallel workers; 5 reps.

**Follow-up (from now on):** replace those historical `--seed` windows with **live `runtime/recorder/` cycles as soon as they exist** (re-run the study / refresh P1 public cases from real recordings). Do not keep historical backtesting seed as the long-term case source.

| Observation | Result |
|---|---|
| Strict plan hash (Optimal cases) | Stable across idle + parallel (1 hash / group) |
| Strict cost spread | **0.0 %** on Optimal groups |
| Production path (same inputs) | Same plan hash as strict on Optimal groups (≤ ~1 s wall time; no fallback observed) |
| One seeded window | `no_optimal` offline (excluded from tolerance derivation) |
| `highspy` | **1.15.1** pinned in `pyproject.toml` |

**Decisions for P1:** regression solver mode = **strict** (`EARNIE_CBC_STRICT=1`); default metric tolerance **±0.05 %** (2× measured spread with floor); production-path sample remains open follow-up; full §16 factor matrix remains optional follow-up.
