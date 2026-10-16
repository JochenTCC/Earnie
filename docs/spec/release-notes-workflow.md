# Release Notes Workflow (DRAFT — decisions recorded, not yet implemented)

Status: **draft for maintainer review**. Nothing described here exists yet except the pieces marked *(exists)*.

## 1. Goals

1. The AI collects everything since the **last productive release** (`vX.Y.Z` — never alpha / beta / rc / dev) and derives a structured change list (features, fixes, data model / migration, config, per-platform impact).
2. From that it writes a **draft** of the release notes (platform-specific sections where relevant).
3. The draft goes to the **maintainer for review**. Only after explicit approval does it become the real release notes used by the release.
4. **No release notes for `-dev.N` versions.**

Cursor is master: rule + skill live in `.cursor/`; Claude Code follows them via the pointer in `CLAUDE.md`.

## 2. Current state (findings)

| Piece | State |
|-------|-------|
| `.github/release-notes/v<tag>.md` | Hand/AI-written per tag *(exists)*; CI `release-publish.yml` step "Prepare release notes" **silently falls back** to generic boilerplate when the file is missing → violates `no-implicit-fallbacks.mdc` |
| `.github/release-notes/UNRELEASED.md` | Manual collector for breaking / user-action items *(exists)* |
| `scripts/migration_release_notes.py --since <tag>` | Drafts the `## Migration` section from the step registry *(exists)* |
| `scripts/bump_ha_addon.py` | Copies the **first prose line** of the notes into the HA add-on `CHANGELOG.md` *(exists)* |
| `docs/spec/release-checklist.md` §1 | Lists "write notes before tag" but no drafting / review gate |
| `session-abschluss` skill | Checklist item "release notes exist or default notes are OK" — the "default OK" is the loophole |
| Tags | Productive `vX.Y.Z`; pre-release `vX.Y.Z-alpha.N/-beta.N/-rc.N`; dev tags `2.7.0-dev.N` (**no `v`**, no CI trigger) |

## 3. Definitions

- **Baseline** = newest tag matching `^v\d+\.\d+\.\d+$` that is an ancestor of `HEAD` **and has a published (non-draft) GitHub Release** (`gh release list`; declined candidates such as `v2.6.1` stay drafts and are skipped; without `gh` the script aborts — pass `--since <tag>` explicitly). Tag ancestry via (`git describe --tags --match "v[0-9]*.[0-9]*.[0-9]*" --exclude "*-*"`). Hotfix branches: ancestor, not "newest by date" (`branching-hotfix-playbook.mdc`).
- **Target version** = `version.py` (or the version the maintainer names). If it contains `-dev.` → workflow stops: *no notes for dev*.
- **Channel of target**: `official` (`X.Y.Z`) or `pre-release` (`-alpha/-beta/-rc`).
  - Pre-release notes are **cumulative since the last productive release** (same baseline), shorter, with the pre-release banner. Official notes are the full, reviewed set.

## 4. Pipeline

```
 collect (script)  ->  draft (AI, skill)  ->  REVIEW (maintainer)  ->  finalize (script)  ->  tag / CI gate
 facts, no prose       prose from facts       edits + "freigegeben"     draft -> v<ver>.md    fails if missing/draft
```

### 4.1 Collect — `scripts/release_notes_collect.py` (new, deterministic, no LLM)

`python -m scripts.release_notes_collect [--since auto|<tag>] [--target <version>] [--out <dir>]`

Refuses with exit 2 when target contains `-dev.`. Writes an **evidence pack** (`release_notes_evidence.md` + `.json`, in a gitignored scratch dir, not committed) containing:

1. Baseline tag + date, target version, channel, commit count.
2. Commits since baseline, grouped by subject prefix (`fix`, `bugfix`, `feat`, `ehal`, `binding`, `thermals`, `runtime`, `configmigration`, `ha-addon`, `docs(spec)`, …), merges and `backlog:`-only commits split out as noise. GitHub issue refs `#N` extracted.
3. Items archived in `backlog/Backlog-Erledigt.md` dated after the baseline date (primary source for *feature wording* — already user-readable) and `Backlog-Bugfixes.md` entries closed since (aliases only, see `backlog-anonymize-users.mdc`).
4. **Data model / config**: output of `migration_release_notes` (new `MigrationStep`s since baseline), plus changed files under `runtime_store/migration/`, `house_config/`, `settings/`, `share/config/` (tariffs catalog) with a flag "structural".
5. **User-facing docs touched**: changed files under `docs/user-manual`, `docs/einrichtung`, `docs/konfiguration` (hint: feature is user-visible).
6. **Platform impact** from paths (heuristic, AI must confirm):
   | Paths | Platform section |
   |-------|------------------|
   | `packaging/homeassistant-addon/**`, `integrations/ha_*`, `ehal/` HA parts | Home Assistant |
   | `packaging/loxberry*`, `integrations/loxone*`, Loxone EHAL | LoxBerry / Loxone |
   | `docker/compose/synology*`, `docker/**` | Synology / Docker |
   | `docker/compose/proxmox*`, `scripts/*qemu*` | Proxmox |
7. Verbatim content of `.github/release-notes/UNRELEASED.md` (maintainer's manual hints — **must appear** in the draft, breaking items on top).
8. Regression report summary if `backtesting_logs/regression/regression_report.md` exists; open `## Bugfix Verifications Pending` (candidates for "known issues").

### 4.2 Draft — skill `.cursor/skills/release-notes/SKILL.md` (new)

AI steps:

1. Run collect; read evidence pack. Read `docs/spec/release-checklist.md` §1 for required sections.
2. Classify every evidence item: **Highlight / Feature / Improvement / Fix / Data model & migration / Platform-specific / Internal (omit)**. Internal = refactors, tests, backlog bookkeeping, sonar, spikes. When unsure: list under a separate `<!-- REVIEW: … -->` marker rather than guessing.
3. Write the draft to **`.github/release-notes/drafts/v<target>.draft.md`** (never directly to `v<target>.md`). Structure:

   ```markdown
   <!-- status: DRAFT — not reviewed. Generated from <baseline>..<sha> on <date>. -->
   <!-- ha_changelog: one German sentence for end users (no pin/latest/channel jargon, no backlog IDs) -->
   ## Earnie <target>
   <1–2 sentence summary>
   ### Breaking / Bitte prüfen        (from UNRELEASED.md + sign/unit/config changes)
   ### Highlights
   ### Neue Funktionen
   ### Verbesserungen & Korrekturen
   ### Datenmodell & Migration       (only if registry gained steps — German, per config-migration.mdc)
   ### Plattformhinweise             (HA add-on · LoxBerry · Synology/Docker · Proxmox — only platforms actually affected)
   ### Bekannte Einschränkungen      (from Verifications Pending, optional)
   ### Docker images / Deploy        (boilerplate block as in v2.6.0.md)
   ```
4. Every bullet traceable to evidence (commit sha or backlog ID in an HTML comment, stripped on finalize). No invented features; no backlog IDs or customer names in the visible text.
5. Show the maintainer a **summary of the draft + list of open `REVIEW` markers**, then **stop**. The AI never marks its own draft as reviewed.

### 4.3 Review gate (maintainer)

- Maintainer edits the draft file (or tells the AI what to change; AI edits the draft, never the final).
- Approval = explicit chat statement ("Release Notes freigegeben" or equivalent). Approval is per version and not reused for later alphas.
- Untouched `REVIEW` markers or `status: DRAFT` block finalization.

### 4.4 Finalize — `scripts/release_notes_finalize.py` (new)

`python -m scripts.release_notes_finalize --version <target>`

- Fails if draft missing, `status: DRAFT` header still present *and* `--approved` not passed, or `REVIEW` markers remain.
- Moves draft → `.github/release-notes/v<target>.md` (strips status/evidence comments, keeps `ha_changelog` for `bump_ha_addon` — or writes it as first prose line, see open question 3).
- Resets `UNRELEASED.md` to its header **only for official releases** (pre-release keeps hints for the final).
- Commit is separate and goes through normal approval.

### 4.5 CI gate — `release-publish.yml` (change)

Replace the silent generic-notes fallback in step "Prepare release notes":

- Tag without `.github/release-notes/v<ver>.md` → **fail the job early** (before building images), message points to the skill.
- Notes containing `status: DRAFT` / `REVIEW:` → fail.
- Dev versions never reach this workflow (no `v` tag); additionally `version.py` containing `-dev.` → fail with "no notes/release for dev".

## 5. Rules and skill changes

| File | Change |
|------|--------|
| `.cursor/rules/release-notes.mdc` (new, `alwaysApply: false`, description-triggered by "release notes / Release-Notes / changelog / tag / publish") | Baseline definition, no notes for `-dev`, AI writes **drafts only**, review gate, German user text / backlog IDs & names excluded, pointer to skill + scripts |
| `.cursor/skills/release-notes/SKILL.md` (new) | Section 4.1–4.4 as agent procedure |
| `.cursor/rules/versioning.mdc` | One line: pre-release / official publish requires reviewed notes; `-dev` has none |
| `.cursor/skills/session-abschluss/SKILL.md` | Publish guide **B/C**: first step = run `release-notes` skill if no reviewed `v<ver>.md`; **A / dev bump**: skip. Replace checklist item "or default notes are OK" with "reviewed notes exist (finalized)" |
| `docs/spec/release-checklist.md` §1 | Replace manual "write notes" bullets with the pipeline; keep Migration + HA-changelog bullets as review criteria |
| `.github/release-notes/UNRELEASED.md` | Header text: now explicitly "maintainer hints, input for the draft" |
| `CLAUDE.md` | Pointer line under *Versioning, backlog, branching*: "Release notes: `.cursor/rules/release-notes.mdc` — drafts only, never final without review" |
| `scripts/migration_release_notes.py` | Unchanged; imported by collect |
| Tests | `tests/test_release_notes_collect.py` (baseline selection excludes alpha/beta/rc/dev; dev refusal; prefix grouping), `tests/test_release_notes_finalize.py` (blocks DRAFT/REVIEW, keeps `ha_changelog`) |

## 6. Rollout order

1. `release_notes_collect.py` + tests (pure facts; usable immediately by hand).
2. Rule + skill (`.cursor`), `CLAUDE.md` pointer.
3. `release_notes_finalize.py` + tests.
4. `session-abschluss` / `versioning.mdc` / checklist updates.
5. CI gate (last, so existing flow is not broken before the tooling exists).
6. Dry run against `v2.6.1..v2.6.2` (compare the generated draft with the notes that were actually published).

## 7. Decisions (maintainer, 2026-10-16)

1. **Pre-releases:** notes required, short and cumulative since the last productive release, with pre-release banner.
2. **Language:** German body for end users; only the Docker/deploy boilerplate stays English.
3. **HA changelog:** `bump_ha_addon` keeps taking the first prose line; the draft places the end-user sentence there (no `ha_changelog:` marker; drop it from the template in 4.2/4.4).
4. **CI:** fail loud for **all** tags without reviewed notes (no generic fallback, also for pre-releases).
5. **Baseline on hotfix branches:** nearest productive ancestor tag.
6. **Evidence pack:** local only (gitignored), not committed.
