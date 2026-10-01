# Specification: Release Regression Suite (golden-master cases)

**Version:** 0.1 (proposal)  
**Status:** Not implemented — backlog **2.7.i**  
**Epic short name:** **Regression** (phases **P1**–**P3**)  
**Related:** [Release Checklist](release-checklist.md), [House simulator](house-sim.md), [Shadow Mode](shadow-mode.md), `tests/fixtures/prod_dumps/README.md`, `.cursor/rules/test-health.mdc`

## 1. Goal

Make sure Earnie's **behaviour does not change unnoticed or unintentionally** between releases.

- A **case** freezes all inputs of an optimizer run (config, consumption, prices, PV forecast, start state).
- The runner executes Earnie offline and deterministically, condenses the result into a few numbers, and compares them against a committed **golden** reference.
- A deviation is not automatically a bug. The maintainer decides at release time: *bug* → fix; *intended change* → re-record the golden with a justification in the commit.
- Cases may contain **customer data**. Those cases never enter the public repository, but each can still be referenced from a public issue.

The suite is **not** part of the per-commit pytest run. It runs **before a release / publish**.

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
| **L2 — backtest window** | Several days to weeks via the backtesting engine (behaviour over time). |
| **Public case** | Synthetic or maintainer-owned data; lives in the main repo. |
| **Private case** | Customer data; lives in the private repo `Earnie-regression-private`. |

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

`expected.json` holds the three result tiers of §7 plus the engine fingerprint used for the golden (Earnie version, CBC/solver version).

Existing `tests/fixtures/prod_dumps/<id>/` cases are migrated into this format in **P1**; their hand-written invariants become tier-1 checks.

## 6. Case IDs and issue references

- Schema: `REG-<issue-number>-<slug>` for issue-driven cases, `REG-S-<slug>` for synthetic ones, `REG-O-<slug>` for own data.
- A **public issue** only says: *"Reproduced in private case REG-142"*. No customer name, no data.
- The mapping from case to customer lives **only** in the private repo (`cases/REG-142/case.yaml` + a local alias, same stable aliases as `.cursor/rules/backlog-anonymize-users.mdc`).
- Every report records the **commit SHA of the private repo** (and the public commit) so a release can later be traced to the exact data state.

## 7. What is compared

Slot-exact equality would break on every solver or float-level change. Three tiers:

1. **Hard invariants** — always fail: SoC within limits, energy balance closes, EV full at deadline, export limit respected, no write to unavailable functions.
2. **Metrics with tolerance** — fail when exceeded: total cost (€), grid import / export (kWh), self-sufficiency, battery cycles, per-consumer energy. Default tolerance ±0.5 %, overridable per metric in `expected.json`.
3. **Plan diff** — informational only: number of slots whose setpoint differs and a plan hash. Shown in the report, never fails.

The solver version (CBC) must be pinned identically for golden recording and verification; the engine fingerprint in `expected.json` makes a mismatch visible instead of producing phantom diffs.

## 8. Runner

```
python -m scripts.run_regression [--cases-dir PATH]... [--case ID] [--workers N]
python -m scripts.run_regression --update-golden --case REG-142-eauto-deadline
python -m scripts.run_regression --intake <debug_dump.zip> --id REG-142-eauto-deadline --private
```

- Pytest marker `regression`, **deselected by default** (`addopts = -m "not regression"` in `pyproject.toml`), so neither the pre-commit hook nor the normal suite runs it. The runner or `-m regression` selects it.
- `--workers N` per `.cursor/rules/backtesting-max-workers.mdc` (largest useful N). Runtime budget: ≤ 15 min parallel.
- `--update-golden` rewrites `expected.json` only for the selected cases and prints the metric delta; the commit message must explain the intended behaviour change.
- Output: console table + `regression_report.md` (Δ per case, tier-3 summary, public + private SHA, engine fingerprint).

## 9. Intake and anonymization

**Intake (P2)** — `--intake` turns a unified debug-dump ZIP (schema v3, see `scripts/replay_debug_dump.py`) into a case folder, assigns the ID and writes `case.yaml`. With `--private` it targets the private repo and does not scrub.

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
| **Regression P1** (MVP) | Case format + schema, runner (L1 + L2), `--update-golden`, report; 4–6 public cases (winter, summer, negative prices, EV deadline, heat storage); migrate existing prod-dump cases; solver-determinism check (same case twice, two machines); checklist item |
| **Regression P2** (customer data) | Private repo `Earnie-regression-private`, private-root support + skip logic, `--intake`, case-ID / issue-reference convention, SHA in report |
| **Regression P3** (gate + scrub) | CI job before `promote`, scrubber script + tests, optional metric trend across releases |

## 13. Open decisions

1. Soft vs. hard release gate (§11) — default proposal: soft first.
2. Whether a customer-facing statement about data handling is needed beyond the private repo (consent / contract wording).
3. Solver pinning: CBC version identical on dev machine, Docker image and CI — verified in P1 before any golden is trusted.
