---
name: session-abschluss
description: >-
  Ends a development session: maintain backlog/Backlog.md, backlog/Backlog-Bugfixes.md, and
  backlog/Backlog-Erledigt.md,
  commit and push all open changes, then guide the user through publish choices
  (A skip / B community pre-release / C official / D bump version.py first)
  before any tag (GitHub Actions → GHCR + GitHub Release; local Docker push as fallback).
  On version bump / pre-release publish, sync docker/compose/*-alpha.yml image tags to version.py.
  Use for "end session", "backlog sync", "commit and push", or an explicit request to conclude the session.
---

# Session Conclusion

Two-phase workflow. **Start Phase 2 only after explicit user confirmation.**

## Phase 1 — Backlog, Commit, Push

### 1. Gather context

Run in parallel:

- `git status`
- `git diff` (unstaged + staged)
- `git diff --cached`
- `git log -5 --oneline` (commit style)
- Chat history for this session: what was completed, what remains open?

### 2. Classify changes

**Default:** Commit all tracked and meaningful untracked changes.

**Ask before staging** for files/groups that are local-only or possibly temporary:

| Category | Examples | Approach |
|----------|----------|----------|
| IDE/dev local | `.vscode/launch.json`, `.vscode/settings.json` with personal paths | Present individually, commit yes/no |
| Local paths | UNC paths (`\\NAS\...`), absolute user paths, debug ports | Ask |
| Experimental | Scratch scripts, `tmp/`, `*.bak`, leftover comments | Ask |
| Runtime/secrets | `.env`, `runtime/*`, `config/config.json` | **Do not** commit (gitignored); warn if visible |
| Unclear | Large diff without clear session context | Briefly describe and ask |

If multiple questionable files: **one compact list** with recommendation (commit / skip / later).

Stage only after the user responds. Do not commit excluded files.

### 3. Update backlog

Keep the schema from `backlog/Backlog.md` / `backlog/Backlog-Bugfixes.md` / `backlog/Backlog-Erledigt.md` (see also `.cursor/rules/backlog.mdc`, chapter nomenclature in `roadmap-nomenclature.mdc`):

- **Letter chapters** (`1.24.a` … `1.24.g`): when done → `backlog/Backlog-Erledigt.md`; **do not change `version.py` automatically** (see `versioning.mdc`)
- **Release chapters** (`1.24.0`, `1.25.0`): backlog progress as usual; version bump **only after explicit user approval**
- **`version.py` ≠ backlog state:** backlog chapters mark development steps; `version.py` stays stable during a MINOR cycle until the user approves a bump

- **Do not strikethrough completed items** — remove them from the respective open file and add them to `backlog/Backlog-Erledigt.md` with `- [x]`
- **backlog/Backlog-Bugfixes.md:** open prod bugs/regressions; when done **suggest PATCH only** and ask the user — do not change silently
- **`## Bugfix Verifications Pending`:** implemented fixes awaiting live verification — move here after commit, **not** to `backlog/Backlog-Erledigt.md`; archive only after successful verification (see `.cursor/rules/backlog.mdc`)
- **backlog/Backlog.md:** feature backlog (version blocks), packaging, reference — only remaining open phases/sub-items
- **backlog/Backlog-Erledigt.md:** New section `### <Topic> (YYYY-MM-DD)` with date **today** (local time Europe/Vienna)
- Document only what was actually completed in the session/diff — do not invent items
- Leave open next steps for partially completed items
- **Effort line per new completed section (optional):** Ask the user for Cursor token usage and relevant chat UUID(s), and add as the last line:
  `_Effort: <value> Cursor tokens · Chats: <uuid>[, <uuid>…]_`
  - Value comes **manually** from the Cursor usage dashboard (not in transcripts, not auto-detectable) — if "don't know"/no value, **omit** the line, do not estimate
  - **Approximation by time window:** `scripts/token_commit_report.py` correlates a Cursor usage CSV export with minor-bump commits (= chapters) and reports events/total tokens/tokens w/o cache/cost per chapter. Time-based (no chat ID in export). Invoke:
    `.venv\Scripts\python.exe -m scripts.token_commit_report --usage-csv "<path>\usage-events-*.csv"`
  - Format details see `.cursor/rules/backlog.mdc`

Include changed backlog file(s) in the commit.

### 4. Commit

- Stage all **approved** changes (`git add` selectively or `-A` minus excluded paths)
- Commit message in repo style: short, German, period at end, focus on **why/what** (see `git log`)
- Multiple thematically separate blocks → one commit with bullet lines in the body is ok; prefer **one session commit** over many mini-commits
- **Commit only when the user triggered Phase 1** (explicit end-session request = approval)

### 5. Push

```powershell
git push
```

On failure (upstream, auth): state the cause, do not blindly retry.

### 6. Phase 1 report + publish decision guide

Briefly summarize:

- Backlog changes
- Commit hash and message
- Push status
- Excluded files (if any)

Then **always** present the publish decision guide below (read `version.py` first; fill in concrete values). Do **not** skip this block after Phase 1 — even if publish seems unlikely; the user may still choose **D**.

**Do not** automatically proceed to Phase 2.

---

## Publish decision guide (present to the user)

After Phase 1, show this decision block with **live values** substituted:

```text
### Publish? (choose one)

Current version.py: <ACTUAL>
Channel if tagged as-is: Official | Pre-release
(main is the publish branch — no separate alpha branch)

A) Skip publish — stop here (default if unsure)
B) Community pre-release — GitHub Pre-release + GHCR :<version> only (no :latest)
C) Official release — GitHub Latest + GHCR :<version> and :latest
D) Bump version.py first, then publish (you approve the new string)

If B or C with current version: I will tag v<ACTUAL> on main after your OK.
If D: propose the exact new version string and wait for approval before editing version.py.
```

### How to choose (tell the user briefly)

| Choice | Use when | Effect |
|--------|----------|--------|
| **A** | Dev-only session; not ready for community/prod | No tag, no GHCR update |
| **B** | Community / forum testers should try a build; prod `:latest` must stay | Pre-release Release; pin `ghcr.io/jochentcc/earnie-energy:<version>`; alpha compose files must match |
| **C** | Feature set is ready for everyone on `:latest` | Latest Release; `*_productive.yml` can pull `:latest` |
| **D** | Need a new number first (e.g. start `X.Y.Z-alpha.1`, bump `alpha.N`→`alpha.N+1`, or go to final `X.Y.Z`) | Edit `version.py` only after explicit approval → sync alpha compose if pre-release → commit → push → then B or C |

### Agent rules for the guide

1. Read `version.py`. Detect pre-release with `-` in the string (`2.2.0-alpha.1` → B path; `2.2.0` → C path).
2. Suggest **one** recommended letter (**A** / **B** / **C** / **D**) with a one-line rationale from this session (e.g. “infra for alphas landed → recommend **B** once `version.py` is the intended alpha string”).
3. If `version.py` is already a pre-release and the user wants community test: recommend **B** (tag as-is), not a silent bump.
4. If mid MINOR backlog cycle and community test is desired: recommend **D** then **B** with target `X.Y.Z-alpha.N` of the *upcoming* release — not a PATCH on the last official.
5. Never bump `version.py` or push a tag until the user picks a letter (or equivalent clear wording: “publish alpha”, “official release”, “skip”).
6. After **D**: propose exact string → wait → edit `version.py` → **run Alpha compose sync** (below) when the new string is a pre-release → commit (include synced YAML) → push → re-show the guide with the new `version.py` → user picks **B** or **C** (or **A**).
7. Before **B**: **run Alpha compose sync** (or verify already matching). Do not tag until the three `*-alpha.yml` files pin `version.py`.

---

## Alpha compose sync (`version.py` → `*-alpha.yml`)

Keep community Alpha stacks pointing at the current pre-release image.

**Files (always all three):**

- `docker/compose/synology-alpha.yml`
- `docker/compose/loxberry-alpha.yml`
- `docker/compose/proxmox-alpha.yml`

**When to run**

| Trigger | Action |
|---------|--------|
| **D** bump — new `version.py` contains `-` (alpha/rc) | Set each file’s `image:` to `ghcr.io/jochentcc/earnie-energy:<version.py>` |
| **D** bump — new `version.py` is clean `X.Y.Z` (official) | **Do not** change alpha compose (leave last pre-release pin); `*_productive.yml` stay on `:latest` |
| Before **B** publish | Verify all three `image:` lines equal `ghcr.io/jochentcc/earnie-energy:<version.py>`; if not, sync, then commit + push before tagging |
| **C** / **A** | No alpha compose edit required |

**How**

1. Read `__version__` from `version.py` (no `v` prefix).
2. Replace the image line in each alpha compose file with exactly:  
   `image: ghcr.io/jochentcc/earnie-energy:<version>`  
   (preserve indentation; only change the tag after the last `:`).
3. If `docs/einrichtung/container.md` (or similar) hardcodes an example pre-release tag for Alpha, update that example to the same `<version>` in the same change set.
4. Include the synced files in the **same commit** as the `version.py` bump when doing **D**; for a late fix before **B**, a small follow-up commit is OK.
5. Never point alpha compose at `:latest`. Never edit `*_productive.yml` image tags in this sync (they stay `:latest`).

---

## Phase 2 — Publish (only after user picks B, C, or D→B/C)

Start **only** on explicit **B** / **C** / “publish alpha” / “official release” / “tag …” after Phase 1 (and after any approved **D** bump is on `origin/main`).

### Checklist before tagging (confirm with user)

- [ ] `version.py` on `origin/main` equals the intended tag without `v`
- [ ] Channel correct: `-` in version → pre-release (**B**); clean `X.Y.Z` → official (**C**)
- [ ] **If B:** all three `docker/compose/*-alpha.yml` have `image: ghcr.io/jochentcc/earnie-energy:<version.py>`
- [ ] Optional notes file exists or default notes are OK: `.github/release-notes/v….md`
- [ ] User confirmed tag name (e.g. `v2.1.0-alpha.1` or `v2.1.0`)

### 1. Check version

Read `version.py`. **Never change without explicit user approval** (see `versioning.mdc`).

Prefer publishing from `main`. After an alpha/rc tag, leave that pre-release string on `main` until the next approved bump — do **not** bump back to the previous official version.

If publishing **B** and alpha compose is out of date: run **Alpha compose sync**, commit, push, then continue.

### 2. Primary: push version tag (CI)

```powershell
# B — community pre-release
git tag -a vX.Y.Z-alpha.N -m "Pre-release vX.Y.Z-alpha.N"
git push origin vX.Y.Z-alpha.N

# C — official
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

- Tag must match `version.py` exactly.
- **B:** Actions → `--prerelease`, GHCR `:<version>` only  
- **C:** Actions → `--latest`, GHCR `:<version>` + `:latest`  
- Watch Actions; confirm Release page (Pre-release vs Latest) and GHCR tags

### 3. Fallback: local build & push

Only if the user asks to skip CI or Actions is unavailable:

```powershell
python -m scripts.build_container --target all --push
```

Default tags follow `version.py` (pre-release omits `:latest`). Details: `docs/einrichtung/container.md` · `DEVELOPER.md`.

### 4. Phase 2 report (guide the user after publish)

- Tag pushed / Actions run URL
- Channel + `version.py` value
- **If B (pre-release):**
  - Testers: `docker compose --project-directory . -f docker/compose/<host>-alpha.yml pull` then `up -d`  
    (Synology / LoxBerry / Proxmox: `synology-alpha.yml` / `loxberry-alpha.yml` / `proxmox-alpha.yml` — already pin `:<version>`)
  - Or pin manually: `ghcr.io/jochentcc/earnie-energy:<version>`
  - Prod `*_productive.yml` with `:latest` is unchanged — last official
- **If C (official):** deploy with usual compose pull of `:latest` or `:<version>`
  - Synology / LoxBerry / Proxmox: `docker compose --project-directory . -f docker/compose/<host>_productive.yml pull` then `up -d`
- Remind: next session end will ask **A/B/C/D** again; alpha stays on `main` until the next approved bump

---

## Error handling

- No empty commits
- No force push without explicit user instruction
- No commit of secrets or gitignored runtime files
- On hook prompt for `docker push` or tag push: wait for user decision
