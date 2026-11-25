# Private site config (Earnie-env-home)

Site files under `earnie_env/config/` do **not** belong in the public Earnie repository. Templates and the published tariff catalog live under `share/config/`.

## Split

| Location | Content |
|----------|---------|
| `share/config/` (public) | `*.minimal.json`, `*.example.json`, `*.schema.json`, **`tariffs.json`** |
| private repo `Earnie-env-home` | `config.json`, scenarios, `house_profiles.json`, `components.json`, `deviation_rules.json`, `uploads/`, optional **`vscode/launch.json`** |
| `earnie_env/config/` (local) | Windows **junction** to the private `config/` |
| `.vscode/launch.json` (local) | machine-specific, gitignored in the public repo; optionally from the private `vscode/launch.json` (hardlink or copy via the link script) |
| `earnie_env/runtime/` | runtime data, local (gitignored) |

`.env` (Loxone credentials) is never versioned.

## Setup (Windows)

1. Put the private repo next to the Earnie clone, e.g. `..\Earnie-env-home` (private repo on GitHub).
2. Run the link script in the Earnie root:

```powershell
.\scripts\link_private_env.ps1
```

If a real folder `earnie_env\config` already exists on the first run, `-Force` is needed; the script then keeps a backup `config.bak-…`.

If the private repo has a `vscode/launch.json`, the script also installs it as `.vscode/launch.json` (hardlink when possible, otherwise a copy); without one it skips this step. This restores the launch config after switching branch or tag without versioning it in the public repo.

If `tariffs.json` is missing in the link target, the script copies it from `share/config/tariffs.json`. That copy stays local and does not belong in the private repo.

## Bootstrap / Community Cloud

Without the private repo and junction, an empty `earnie_env/config/` plus the templates in `share/config/` is enough. The bootstrap then creates minimal site files and takes the tariff and grid fee catalogs from `share/config/tariffs.json` and `share/config/grid_fees.json`. Useful together with `EARNIE_OFFLINE=1` and possibly `EARNIE_UI_MODES=scenario_explorer`.

The public demo on Streamlit Community Cloud adds **`EARNIE_CLOUD_DEMO=1`**. In this mode:

- **Own workspace:** every browser session gets its own temporary Greenfield workspace with an empty minimal config.
- **Start:** the session starts in the **Hauskonfigurator** with a short welcome note.
- **Rating:** once a Szenario-Explorer run was started, leaving the page may show an anonymous star rating dialog once per browser session (state in the session's temporary workspace). **Senden** sends the rating to the built-in Earnie server; **Abbrechen** ends the prompt without sending anything.
- **No offline seed:** the offline demo seed of the live-scenario IDs is skipped.
- **No usage statistics, only a session counter:** the consent dialog does not appear and no install ping is sent. Every new browser session counts once, anonymously, at the Earnie server; the welcome note says so (see [usage-ping.md](../workflow/usage-ping.md)).

Recommended secrets: `EARNIE_CLOUD_DEMO=1`, `EARNIE_OFFLINE=1`, `EARNIE_UI_MODES=scenario_explorer`.

## Publish the tariff catalog

The UI auto-saves to `earnie_env/config/tariffs.json` (junction). Update the public copy with:

```powershell
Copy-Item earnie_env\config\tariffs.json share\config\tariffs.json -Force
```

Then commit the change in the Earnie repo. Before a deploy, check the catalog: `python -m scripts.validate_tariffs --tariffs share/config/tariffs.json --check-catalog`.

## Private regression cases (Earnie-regression-private)

Customer data for the release regression lives in the private sibling repo `Earnie-regression-private` (folder `cases/`), **not** in the public repo.

| Setting | Meaning |
|---------|---------|
| default path | `..\Earnie-regression-private\cases` next to the Earnie clone |
| `$EARNIE_REGRESSION_PRIVATE_DIR` | overrides the cases root (no junction needed) |

Without the private root, `python -m scripts.run_regression` skips the private cases and the report records `private-root-missing`, so they never drop out silently. Add a case (intake):

```powershell
.venv\Scripts\python.exe -m scripts.run_regression --intake DUMP.zip `
  --id REG-142-eauto-deadline --private --seed-anchor "2026-06-26T18:00:00"
```

Details: [`docs/workflow/regression-suite.md`](../workflow/regression-suite.md) §4 / §9.
