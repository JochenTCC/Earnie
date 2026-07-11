---
name: session-abschluss
description: >-
  Ends a development session: maintain Backlog.md, Backlog-Bugfixes.md, and
  Backlog-Erledigt.md,
  commit and push all open changes, optionally build a Docker image
  and push it to ghcr.io.
  Use for "end session", "backlog sync", "commit and push", or
  an explicit request to conclude the session.
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

Keep the schema from `Backlog.md` / `Backlog-Bugfixes.md` / `Backlog-Erledigt.md` (see also `.cursor/rules/backlog.mdc`, chapter nomenclature in `roadmap-nomenclature.mdc`):

- **Letter chapters** (`1.24.a` … `1.24.g`): when done → `Backlog-Erledigt.md`; **do not change `version.py` automatically** (see `versioning.mdc`)
- **Release chapters** (`1.24.0`, `1.25.0`): backlog progress as usual; version bump **only after explicit user approval**
- **`version.py` ≠ backlog state:** backlog chapters mark development steps; `version.py` stays stable during a MINOR cycle until the user approves a bump

- **Do not strikethrough completed items** — remove them from the respective open file and add them to `Backlog-Erledigt.md` with `- [x]`
- **Backlog-Bugfixes.md:** open prod bugs/regressions; when done **suggest PATCH only** and ask the user — do not change silently
- **`## Bugfix Verifications Pending`:** implemented fixes awaiting live verification — move here after commit, **not** to `Backlog-Erledigt.md`; archive only after successful verification (see `.cursor/rules/backlog.mdc`)
- **Backlog.md:** feature backlog (version blocks), packaging, reference — only remaining open phases/sub-items
- **Backlog-Erledigt.md:** New section `### <Topic> (YYYY-MM-DD)` with date **today** (local time Europe/Vienna)
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

### 6. Phase 1 report

Briefly summarize:

- Backlog changes
- Commit hash and message
- Push status
- Excluded files (if any)

Close with:

> Should I now build the Docker image and push it to ghcr.io?

**Do not** automatically proceed to Phase 2.

---

## Phase 2 — Build & push Docker (on request only)

Start **only** on explicit "Yes" / "build Docker" / "push image" after Phase 1.

### 1. Check version

Read `version.py`. **Never change without explicit user approval** (see `versioning.mdc`).

During an active MINOR cycle (`1.24.a` … `1.24.g`, release `1.24.0`): **no automatic bump** — also do not "reset" or catch up PATCH.

If a release seems appropriate: **once** suggest (target version + rationale) and ask the user. On "no" or no response: leave unchanged.

### 2. Build & push

Canonical command for release (Synology + LoxBerry, multi-arch):

```powershell
python -m scripts.build_container --target all --push
```

Synology only (amd64):

```powershell
python -m scripts.build_container --target synology --push
```

Alternative Windows wrapper: `.\build-container.ps1 --target all --push`

Default tags:

- `ghcr.io/jochentcc/earnie-energy:latest`
- `ghcr.io/jochentcc/earnie-energy:<version>` from `version.py`

Details: `docs/einrichtung/container.md`

### 3. Prerequisites

- Docker is running; for `--target all`: `docker buildx create --use` (once, see container.md)
- `docker login ghcr.io` successful — on auth error stop and give guidance
- Hook may mark `docker push` for confirmation — wait for user approval

### 4. Phase 2 report

- Built/pushed tags
- Version from `version.py`
- Deploy notes:
  - Synology: `docker compose -f docker-compose-synology.yml pull && ... up -d`
  - LoxBerry: `docker compose -f docker-compose-loxberry.yml pull && ... up -d`

---

## Error handling

- No empty commits
- No force push without explicit user instruction
- No commit of secrets or gitignored runtime files
- On hook prompt for `docker push`: wait for user decision
