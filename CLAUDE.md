# CLAUDE.md — Earnie (Energy-Optimizer)

Project rules live in `.cursor/rules/*.mdc` and `.cursor/skills/*/SKILL.md` (written for Cursor). They apply to Claude Code too — read the matching rule before acting in its area. This file only lists the essentials and points there.

## Tests

- Always run pytest through the wrapper, never plain `python -m pytest`:

  ```powershell
  $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
  .venv\Scripts\python.exe -m scripts.run_pytest tests -q --tb=short
  ```

  The wrapper adds `-n auto` (pytest-xdist) unless `-n` is given — full suite ≈ 2.5 min in parallel vs. > 10 min sequential. Use it for small subsets too (`... -m scripts.run_pytest tests/test_ha_adapter.py -q`). Sequential (`-n 0`) only for debugging, `--dead-fixtures`, mutmut.
- UTF-8 env is required on Windows (cp1252 console crashes on `→`, umlauts). See `.cursor/skills/windows-unicode-console/`.
- Test health / quality gate: `.cursor/rules/test-health.mdc`, `.cursor/skills/quality-gate/`.
- Backtesting / SE runs: always `--workers N` with the largest useful N (`.cursor/rules/backtesting-max-workers.mdc`).

## Shell

Windows PowerShell 5.x: no `&&` / `||` (`.cursor/rules/powershell-shell.mdc`). In the Bash tool (Git Bash) POSIX syntax is fine.

## Versioning, backlog, branching

- **Never change `version.py` without explicit user approval** — propose and ask (`versioning.mdc`).
- Backlog IDs and hierarchy: `roadmap-nomenclature.mdc`, `backlog.mdc`. Backlog files are **English**; done items go to `backlog/Backlog-Erledigt.md` (newest on top, dated heading).
- Before committing `Backlog-Bugfixes.md` / `Backlog-Erledigt.md`: scrub real user/customer names with stable aliases (`backlog-anonymize-users.mdc`; local map `.cursor/user-aliases.local.md`, never committed).
- Branching / hotfix / tagging: `branching-hotfix-playbook.mdc` — warn before long-lived branches or tag rewrites.

## Chat language

Reply in **German** in Claude Code chat (the user switches language spontaneously when needed — follow that). `.cursor/rules/english-chat.mdc` applies to Cursor only. Commit messages, backlog and `docs/spec/` stay English as in the rules below.

## Docs language

- User docs (`docs/README.md`, `docs/user-manual/`, `docs/einrichtung/`, `docs/konfiguration/`, `docs/ui/`, `docs/referenz/`) are **German**; update them in the same change when behaviour changes (`german-user-docs.mdc`).
- `docs/spec/` and backlog: English.

## Area notes

- **Streamlit UI state:** `.cursor/rules/streamlit-ui-state.mdc`, skills `streamlit-ui-state`, `streamlit-apptest`.
- **HouseSim** (`house_sim/`, spec `docs/spec/house-sim.md`): after changing `house_sim/core/` or `house_sim/fixtures/`, run `python -m scripts.sync_house_sim_integration` (UTF-8 env) — the S4 integration copy is generated and checked by `tests/test_house_sim_s4_packaging.py`.
- **HA mapping:** units via `integrations/ha_units.py` (only physically compatible bindings, factor from `unit_of_measurement` at runtime); function completeness via `ehal/functions.py` (a function is unavailable until all its fields are mapped).
- `.cursorignore`: if something is blocked, ask the user instead of guessing (`cursorignore-access.mdc`).
