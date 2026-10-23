# Branching & Hotfix Playbook

**Status:** current  

How to run a **MINOR release line** (`releaseX.Y`) for alpha → beta → official while `main` continues feature work, and how to ship urgent patches from a **tagged** build.

Related: [DEVELOPER.md](../../DEVELOPER.md) (tag → GHCR), [CONTRIBUTING.md](../../CONTRIBUTING.md) (PRs), `.cursor/rules/versioning.mdc` (`version.py` approval), `.cursor/rules/branching-hotfix-playbook.mdc` (agent warns before violations).

---

## Model

| Line | Purpose |
|------|---------|
| **`main`** | Default long-lived branch. Next-MINOR features and work that must **not** ship in the current release line. |
| **`releaseX.Y`** | Long-lived **ship line** for that MINOR (e.g. `release2.7`). Fixes, beta, rc, and the official `X.Y.Z` tags for that cycle. Created from the community tag that starts the freeze (e.g. `v2.7.0-alpha.9`). |
| **Annotated tags** (`vX.Y.Z`, `vX.Y.Z-alpha.N` / `-beta.N` / `-rc.N`) | Immutable shipped builds. Tag must equal `version.py` (no leading `v`). For the active MINOR, tags are cut from **`releaseX.Y`**, not from dirty `main`. |
| **Short-lived `hotfix/…`** | Only when users need a build **now** from an older tag and even `releaseX.Y` must not ship as-is (rare). |

There is **no** permanent `develop` or `alpha` branch. Pre-release remains a **version channel** (`version.py` + tag + `*-alpha.yml` pins) on the active ship line (`releaseX.Y` or `main` when no release branch is open).

Naming: `release` + major + `.` + minor, **no slash** — e.g. `release2.7`, `release2.8`. Same name on Earnie and satellite repos that share the cycle.

```text
main ──────────────── next-MINOR features ───────────────────────────
         \
          tag vX.Y.Z-alpha.N  (freeze point)
               \
                releaseX.Y ── fix / beta / rc / official tags ──► (merge back to main as needed)
```

---

## When to open `releaseX.Y`

Open once for a MINOR when you want to **freeze** that ship line while `main` keeps moving:

1. Tag the freeze commit on the then-current line (usually `main`) — e.g. `v2.7.0-alpha.9`.
2. Create and push `releaseX.Y` from that tag on **every repo** that participates in the release (Earnie, env, workspace, …).
3. Further `X.Y` alphas / betas / rc / official tags for that MINOR → commit and tag on **`releaseX.Y`**.
4. Port release-line fixes to `main` (merge or cherry-pick) so the next MINOR does not reintroduce bugs. Do **not** rewind `main`’s `version.py` to an older PATCH while `main` already targets a newer pre-release.

Close or stop using `releaseX.Y` after the official `X.Y.Z` (and any agreed PATCH train) is done; next MINOR gets a new `releaseX.Y+1` when needed.

---

## Decision tree

### 1. Default during an open release line — fix on `releaseX.Y`

Use for bugs and hardening that should ship in the current MINOR (next alpha/beta/rc/official).

```text
fix on releaseX.Y → session publish: D (if needed) → B (alpha/beta/rc) or C (official)
# then port the code fix to main
```

- Mid cycle: prefer next **`X.Y.Z-alpha.N+1`** / `-beta.N` / `-rc.N`, not a PATCH on the last official.
- After official: **PATCH** (`X.Y.Z` → `X.Y.Z+1`) on `releaseX.Y` after explicit approval, then port code to `main`.

### 2. Default when no `releaseX.Y` is open — fix on `main`

```text
fix on main → session publish: D (if needed) → B or C
```

### 3. Urgent — testers stuck on a **tag**; even `releaseX.Y` is dirty

Use when both are true:

1. Community/prod must get the fix **before** unfinished commits on the ship line, and  
2. The ship line (`releaseX.Y` or `main`) already contains commits that must **not** be in that patch.

```text
git checkout -b hotfix/<short-name> vX.Y.Z-alpha.N   # or last official tag
# fix + tests only
# D: bump version.py → next pre-release or PATCH
# sync docker/compose/*-alpha.yml image pins if pre-release
# tag from the hotfix tip → B or C
# merge/cherry-pick into releaseX.Y (and into main)
```

After tagging, delete the hotfix branch.

### 4. Urgent — **prod** (`:latest` / last official) broken; ship line already on next pre-release

```text
git checkout -b hotfix/X.Y.Z+1 vX.Y.Z          # last official tag
# fix + tests
# D: version.py → X.Y.Z+1 (PATCH)
# tag from that line → C (updates :latest)
# port the *code* fix onto releaseX.Y and main; leave their version.py on the ongoing pre-release if that is the next intended publish
```

Do **not** rewind the ship line’s `version.py` to the PATCH string if that line is already past it.

---

## Publish choices (session end)

Same letters as the session-conclusion guide:

| Choice | Meaning |
|--------|---------|
| **A** | No tag |
| **B** | Community pre-release (GitHub Pre-release; GHCR `:<version>` only) |
| **C** | Official (Latest; GHCR `:<version>` + `:latest`) |
| **D** | Approve and set `version.py` first, then B or C |

Rules that matter for branching:

- Never change `version.py` without explicit approval.
- Tag only when `version.py` on the tagged commit equals the tag without `v`.
- While `releaseX.Y` is the ship line for that MINOR, cut tags from **`releaseX.Y`** (not from unrelated `main` tips).
- After an alpha/beta/rc tag, leave that string on the ship line until the next approved bump.
- Before **B**: `synology-alpha.yml` / `loxberry-alpha.yml` / `proxmox-alpha.yml` must pin `ghcr.io/jochentcc/earnie-energy:<version.py>`.
- **B** and **C** are two-step: the tag builds a *candidate* (`:<version>` images, draft release); users see it only after approving job `promote` (environment `release-approval`) — test on your own HA / LoxBerry in between ([release-checklist.md](release-checklist.md)). A rejected candidate is not re-tagged; fix and tag the next version.

---

## Hotfix checklist

1. Confirm the **base tag** users run (`git tag -l` / GitHub Releases / compose pin).
2. Prefer fixing on **`releaseX.Y`** if that MINOR’s ship line is open; otherwise `main`. Use `hotfix/<name>` only for Case 3/4.
3. Ship **only** the fix (+ tests). No drive-by features.
4. Get approval for the new `version.py` string (**D**).
5. If pre-release: sync all three `*-alpha.yml` image lines.
6. Land the same fix on every active long-lived line that needs it (`releaseX.Y` and/or `main`). Align `version.py` only when that string is the next intended publish on that line.
7. Push commits; push annotated tag with a `targets: both|docker|ha` line in the message → CI (`.github/workflows/release-publish.yml`); test the candidate, then approve `promote`.
8. Delete any short-lived hotfix branch; move bugfix backlog item to **Verifications Pending** until live OK.

---

## Bugfix backlog vs branches

| Backlog state | Git / publish |
|---------------|---------------|
| Open in `Backlog-Bugfixes.md` | Work not done yet |
| **Verifications Pending** | Fix committed (and usually tagged); live acceptance still open |
| `Backlog-Erledigt.md` | Only after successful verification |

Branching does not replace this lifecycle.

---

## Do not

- Long-lived `alpha` or `develop` parallel to `main` (use `releaseX.Y` for the ship line)
- Tag a commit whose `version.py` does not match the tag
- Force-push or rewrite published tags
- Cut the current MINOR’s release tags from a dirty `main` while `releaseX.Y` exists
- Leave a fix only on the release tip without porting to `main` when `main` will keep that code path

---

## Satellite repos

When opening `releaseX.Y` for a cycle, create the same branch name from the matching tag on every participating repo (e.g. Earnie, Earnie-env-home, earnie-workspace, earnie-server, Earnie-Projekt, edbert). Keep their tips aligned for that cycle’s tags.
