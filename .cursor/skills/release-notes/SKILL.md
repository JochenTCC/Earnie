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

Rule: `.cursor/rules/release-notes.mdc` · Spec: `docs/workflow/release-notes-workflow.md`.

## 1. Preconditions

- Read `version.py`. `-dev.` in the version → **stop**: no release notes for dev versions.
- Target = `version.py` unless the user names another version (e.g. a planned bump — do not edit `version.py`).

## 1b. Narrative baseline — last **public** release only (hard rule)

Release notes are always written **for users on the last official / public release** (`vX.Y.Z` on `:latest`), never as a delta from the previous alpha / beta / rc.

| Do | Do not |
|----|--------|
| Cumulative story since the newest **published productive** tag (`2.6.2`, `2.6.0`, …) | Structure the draft as “NEW since alpha.5 / beta.1” |
| Pre-release banner may say “follows `2.7.0-alpha.5`” as orientation only | Use a prior alpha/beta/rc as the change baseline or omit 2.7 features already in earlier alphas |
| If evidence warns of **unmerged** productive tags (hotfix line): read that GitHub Release body / notes and **exclude** those fixes from “new” | Re-announce hotfix PATCH items as if they were new on `main` |

The collect script’s git ancestor baseline may be older than `:latest` when a hotfix tag is not merged into `HEAD` — that is fine for the evidence pack. The **draft prose** still addresses the last public release the community actually runs. When in doubt, ask which productive version is on `:latest`.

## 1c. Pre-release template (2.7 line)

For further **alpha / beta / rc** notes on the current 2.7 cycle (until the next official `2.7.0` or the maintainer names a new template):

1. **Copy structure and tone** from [`.github/release-notes/v2.7.0-alpha.6.md`](../../../.github/release-notes/v2.7.0-alpha.6.md) — opening sentence, HA summary bullets, pre-release banner (vs last **public** release), section order, platform blocks, Docker boilerplate.
2. **Update in place:** title/version, banner “folgt auf …” to the previous pre-release tag, image tags, and any new or changed bullets from the evidence pack (still cumulative vs the public baseline, §1b).
3. **Do not** invent a shorter “delta-only” layout or restart from an older alpha (`alpha.1`…`alpha.5`) as the skeleton.
4. After an official `2.7.0` (or when the user designates another file), use that release’s notes as the new template instead.

## 2. Collect

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m scripts.release_notes_collect [--target <version>]
```

Output (local, gitignored): `backtesting_logs/release_notes/release_notes_evidence.md` (+ `.json`). Read it fully. Exit code 2 = refused (dev version, no baseline) — report, do not work around.

If the evidence shows a **WARNING about unmerged productive tags**, read their GitHub Release notes (or `.github/release-notes/v….md` if present) and exclude fixes already shipped there from the "new" list. Still draft **cumulative since that public release**, not since the last pre-release.

## 3. Draft

Write `.github/release-notes/drafts/v<target>.draft.md` (create the folder). Never `v<target>.md`.

```markdown
<!-- status: DRAFT — not reviewed. Generated from <baseline>..<sha> on <date>. -->
## Earnie <target>

<First prose line: ONE German end-user sentence (becomes the HA add-on Änderungsprotokoll).>

- <Kurzliste: 4–7 Stichpunkte, je max. ~10 Wörter, direkt unter dem Satz (wird mit in das HA-Änderungsprotokoll übernommen).>
- <Reihenfolge: Breaking / Nutzeraktion zuerst, dann Highlights; keine Details, keine Backlog-IDs, kein Markdown-Fett.>

### Breaking / Bitte prüfen      (UNRELEASED.md hints + sign/unit/config changes — first)
### Highlights
### Neue Funktionen
### Verbesserungen & Korrekturen
### Qualität & Stabilität          (only `[qual]` items, 1–3 lines)
### Datenmodell & Migration      (only if migration steps are new — German `## Migration` text from the helper, edited)
### Plattformhinweise            (only affected: Home Assistant · LoxBerry · Synology/Docker · Proxmox)
### Bekannte Einschränkungen     (optional, from Verifications Pending)
### Docker images                (English boilerplate as in v2.6.0.md; pre-release: banner + no :latest)
```

Use the audience markers of the evidence pack (`backlog.mdc` §7): `feat` -> Highlights / Neue Funktionen; `qual` -> section "Qualität & Stabilität" (1–3 lines, no details); `fix` -> Verbesserungen & Korrekturen; `dev` -> **omit completely** (also in user docs). **`unmarked` entries: ask the maintainer first** (propose a marker per entry, wait for the answer, and offer to write the marker into `Backlog-Erledigt.md`) — never guess. Further internal material (refactors, tests, backlog bookkeeping, sonar, spikes, research) is omitted as well. Archived backlog items are the best wording source; rewrite for end users (no internal backlog version IDs such as 2.7.n / 2.+1 / P5 in visible text — only inside `<!-- src: -->` comments; finalize rejects them — and no real names). Uncertain items → `<!-- REVIEW: … -->`. Add `<!-- src: <sha> -->` comments for traceability (removed on finalize).

- **Summary list:** the contiguous `- ` bullets right below the first prose line (before the banner / first `###`) are copied by `bump_ha_addon` into the HA CHANGELOG as nested bullets — single-line items only, nothing else may sit between sentence and list. Derive the items from Breaking + Highlights (+ the most important Neue Funktionen); each must be backed by a longer entry further down. Omit when there is nothing worth listing.
- **Pre-release:** keep short; add the "not an official release — use `:next` or pin the tag" banner; **always cumulative since the last public productive release** (§1b) — never a changelog against the previous alpha/beta/rc. **Skeleton:** start from `v2.7.0-alpha.6.md` (§1c), then fold in new evidence.
- **Official:** full set.
- **Forbidden in drafts:** section comments or headings like `NEW since alpha.N`, `Delta vs beta.1`, or omitting earlier-alpha features because “they were already in alpha.5”.

## 4. Hand over for review — then stop

Tell the maintainer: draft path, baseline, counts per section, **list of `REVIEW` markers**, platforms covered, whether a Migration section was included. Ask for review. Do not tag, do not copy to `v<target>.md`, do not commit unless asked.

Changes requested → edit the **draft**. Explicit approval for this version in chat → run (only now, never before the approval):

```powershell
.venv\Scripts\python.exe -m scripts.release_notes_finalize --version <target> --approved
```

It strips status / `src` comments, fails on unresolved `REVIEW` markers, refuses `-dev` and an existing `v<target>.md`, writes `.github/release-notes/v<target>.md`, and resets `UNRELEASED.md` to its header for official releases only. Then continue with `session-abschluss` Phase 2 (commit of the notes needs the usual approval).

## 5. Not in scope

Backlog bookkeeping (`backlog.mdc`), `version.py` bumps (`versioning.mdc`), tagging (`session-abschluss` Phase 2).
