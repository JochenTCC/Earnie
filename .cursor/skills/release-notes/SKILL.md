---
name: release-notes
description: >-
  Drafts Earnie release notes: collects changes since the last productive release
  (vX.Y.Z, not alpha/beta/rc/dev) into an evidence pack, writes a German draft
  with features, fixes, data model / migration and platform sections (Home
  Assistant, LoxBerry, Synology/Docker, Proxmox), then stops for maintainer
  review. Never for -dev versions. Use before a pre-release or official tag
  (session-abschluss B/C) or when the user asks for release notes / changelog.
---

# Release notes (draft → review → final)

Rule: `.cursor/rules/release-notes.mdc` · Spec: `docs/spec/release-notes-workflow.md`.

## 1. Preconditions

- Read `version.py`. `-dev.` in the version → **stop**: no release notes for dev versions.
- Target = `version.py` unless the user names another version (e.g. a planned bump — do not edit `version.py`).

## 2. Collect

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m scripts.release_notes_collect [--target <version>]
```

Output (local, gitignored): `backtesting_logs/release_notes/release_notes_evidence.md` (+ `.json`). Read it fully. Exit code 2 = refused (dev version, no baseline) — report, do not work around.

If the evidence shows a **WARNING about unmerged productive tags**, read their `.github/release-notes/v….md` and exclude fixes already shipped there from the "new" list.

## 3. Draft

Write `.github/release-notes/drafts/v<target>.draft.md` (create the folder). Never `v<target>.md`.

```markdown
<!-- status: DRAFT — not reviewed. Generated from <baseline>..<sha> on <date>. -->
## Earnie <target>

<First prose line: ONE German end-user sentence (becomes the HA add-on Änderungsprotokoll).>

### Breaking / Bitte prüfen      (UNRELEASED.md hints + sign/unit/config changes — first)
### Highlights
### Neue Funktionen
### Verbesserungen & Korrekturen
### Datenmodell & Migration      (only if migration steps are new — German `## Migration` text from the helper, edited)
### Plattformhinweise            (only affected: Home Assistant · LoxBerry · Synology/Docker · Proxmox)
### Bekannte Einschränkungen     (optional, from Verifications Pending)
### Docker images                (English boilerplate as in v2.6.0.md; pre-release: banner + no :latest)
```

Classify each evidence item: Highlight / Feature / Improvement / Fix / Data model / Platform / **Internal (omit)** — internal = refactor, tests, backlog bookkeeping, sonar, spikes, research. Archived backlog items are the best wording source; rewrite for end users (no backlog IDs, no real names). Uncertain items → `<!-- REVIEW: … -->`. Add `<!-- src: <sha> -->` comments for traceability (removed on finalize).

- **Pre-release:** keep short; add the "not an official release — use `:next` or pin the tag" banner; still cumulative since the last productive release.
- **Official:** full set.

## 4. Hand over for review — then stop

Tell the maintainer: draft path, baseline, counts per section, **list of `REVIEW` markers**, platforms covered, whether a Migration section was included. Ask for review. Do not tag, do not copy to `v<target>.md`, do not commit unless asked.

Changes requested → edit the **draft**. Explicit approval for this version in chat → run (only now, never before the approval):

```powershell
.venv\Scripts\python.exe -m scripts.release_notes_finalize --version <target> --approved
```

It strips status / `src` comments, fails on unresolved `REVIEW` markers, refuses `-dev` and an existing `v<target>.md`, writes `.github/release-notes/v<target>.md`, and resets `UNRELEASED.md` to its header for official releases only. Then continue with `session-abschluss` Phase 2 (commit of the notes needs the usual approval).

## 5. Not in scope

Backlog bookkeeping (`backlog.mdc`), `version.py` bumps (`versioning.mdc`), tagging (`session-abschluss` Phase 2).
