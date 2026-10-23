# Branching & Hotfix Playbook

**Status:** current  

How Earnie splits **continuing development** on `main` from **finalizing and maintaining** a planned MINOR on a release branch, including later bugfixes and PATCH releases.

Related: [DEVELOPER.md](../../DEVELOPER.md) (tag → GHCR), [CONTRIBUTING.md](../../CONTRIBUTING.md) (PRs), `.cursor/rules/versioning.mdc` (`version.py` approval), `.cursor/rules/branching-hotfix-playbook.mdc` (agent warns before violations).

---

## Model

| Line | Purpose |
|------|---------|
| **`main`** | Ongoing development. Features for the *next* MINOR (and anything that must **not** ship in the release being finalized). |
| **`releaseX.Y`** | Long-lived **release line** for MINOR `X.Y` (e.g. `release2.7`). Opened when the official release is **near** and development should continue on `main`. The planned release is **moved** here and finalized (remaining alpha → beta → rc → official). After the official, this branch also carries **bugfixes** and **PATCH / minor maintenance releases** (`X.Y.Z+1`, …). |
| **Annotated tags** (`vX.Y.Z`, `vX.Y.Z-alpha.N` / `-beta.N` / `-rc.N`) | Immutable shipped builds. Tag must equal `version.py` (no leading `v`). While `releaseX.Y` is open for that MINOR, cut its tags from **`releaseX.Y`**, not from a diverged `main`. |
| **Short-lived `hotfix/…`** | Only when users need a build **now** from an older tag and even `releaseX.Y` must not ship as-is (rare). |

There is **no** permanent `develop` or `alpha` branch. Pre-release is a **version channel** (`version.py` + tag + `*-alpha.yml` pins) on the active ship line (`releaseX.Y` once opened, otherwise `main`).

Naming: `release` + major + `.` + minor, **no slash** — e.g. `release2.7`, `release2.8`. Same name on Earnie and satellite repos that share the cycle.

```text
main ── features / next MINOR ──────────────────────────────────────►
         \
          (official near + keep developing)
               \
                releaseX.Y ── finalize (beta/rc/official)
                           ── later bugfixes + PATCH tags
                           ── PRs / cherry-picks → main (as needed)
```

---

## When to open `releaseX.Y`

Open when **both** are true:

1. The **planned official** for MINOR `X.Y` is near (hardening / beta / rc territory), and  
2. **Development should continue** on `main` (next features must not block or pollute the release).

Then **move** that planned release onto the branch:

1. Choose the freeze commit (usually the latest community tag on `main`, e.g. `v2.7.0-alpha.9`, or an agreed `main` tip).
2. Create and push `releaseX.Y` from that commit on **every** participating repo (Earnie, env, workspace, …).
3. From then on, **finalize** on `releaseX.Y` only: remaining pre-releases, official `X.Y.Z`, then bugfixes and PATCH releases.
4. Keep `main` free for the next MINOR. Bring release-line fixes into `main` via **PR** (preferred) or cherry-pick so bugs do not return. Do **not** rewind `main`’s `version.py` to an older PATCH while `main` already targets a newer pre-release / next MINOR.

`main` alone is enough **before** this split (early alphas while everyone still ships from `main`). After the split, do not cut that MINOR’s release tags from dirty `main`.

Keep `releaseX.Y` for as long as you still ship PATCH / maintenance for that MINOR. The next MINOR gets its own `releaseX.Y+1` when that official becomes near and development must continue again.

---

## What lives on `releaseX.Y`

| Phase | On `releaseX.Y` |
|-------|-----------------|
| **Finalize** | Last alphas, beta, rc, official `X.Y.0` (or `X.Y.Z`) |
| **Maintain** | Bugfixes; PATCH bumps (`X.Y.Z+1`, …) after approval |
| **Back to `main`** | PR (or cherry-pick) of fixes that `main` still needs |

Do **not** merge unfinished next-MINOR features from `main` into `releaseX.Y`. Flow is release → main for fixes, not main → release for features (unless you explicitly cherry-pick a needed fix the other way).

---

## Decision tree

### 1. Official near + continue developing — open / use `releaseX.Y`

```text
freeze → branch releaseX.Y → finalize & tag there
main continues next MINOR
PRs: release fixes → main
```

### 2. Default while `releaseX.Y` is open — fix and release on that branch

```text
fix on releaseX.Y → D (if needed) → B (pre-release) or C (official / PATCH)
→ PR (or cherry-pick) code fix to main
```

- Before official: next **`X.Y.Z-alpha.N+1`** / `-beta.N` / `-rc.N`.
- After official: **PATCH** on `releaseX.Y` after explicit approval, then port code to `main`.

### 3. No release branch yet — fix and publish on `main`

```text
fix on main → D (if needed) → B or C
```

### 4. Urgent — testers/prod stuck on a **tag**; even `releaseX.Y` is dirty

Use when both are true:

1. Users need the fix **before** unfinished commits on the ship line, and  
2. The ship line already contains commits that must **not** be in that patch.

```text
git checkout -b hotfix/<short-name> <base-tag>
# fix + tests only; D: bump version.py; sync *-alpha.yml if pre-release
# tag from hotfix tip → B or C
# merge/cherry-pick into releaseX.Y and PR to main
```

After tagging, delete the hotfix branch.

### 5. Urgent — **prod** (`:latest`) broken; ship line already past that official

```text
git checkout -b hotfix/X.Y.Z+1 vX.Y.Z
# fix + tests; D: version.py → X.Y.Z+1; tag → C
# port *code* to releaseX.Y and main; leave their version.py on the ongoing target if already past the PATCH
```

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
- While `releaseX.Y` owns that MINOR, cut its tags from **`releaseX.Y`**.
- After an alpha/beta/rc tag, leave that string on the ship line until the next approved bump.
- Before **B**: `synology-alpha.yml` / `loxberry-alpha.yml` / `proxmox-alpha.yml` must pin `ghcr.io/jochentcc/earnie-energy:<version.py>`.
- **B** and **C** are two-step: the tag builds a *candidate*; users see it only after approving job `promote` ([release-checklist.md](release-checklist.md)). A rejected candidate is not re-tagged; fix and tag the next version.

---

## Hotfix / PATCH checklist

1. Confirm the **base tag** users run.
2. Prefer **`releaseX.Y`** if that MINOR’s line is open; otherwise `main`. Use `hotfix/…` only for Case 4/5.
3. Ship **only** the fix (+ tests).
4. Get approval for the new `version.py` string (**D**).
5. If pre-release: sync all three `*-alpha.yml` image lines.
6. Open a **PR to `main`** (or cherry-pick) so the fix is not lost. Align `version.py` on `main` only when that string is the next intended publish there.
7. Push; annotated tag with `targets: both|docker|ha` → CI; test candidate; approve `promote`.
8. Delete any short-lived hotfix branch; backlog → **Verifications Pending** until live OK.

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

- Long-lived `alpha` or `develop` (use `releaseX.Y` when the official is near and `main` must continue)
- Tag a commit whose `version.py` does not match the tag
- Force-push or rewrite published tags
- Finalize the planned MINOR on dirty `main` after `releaseX.Y` exists
- Merge next-MINOR feature work from `main` into `releaseX.Y`
- Leave a release-line fix only on `releaseX.Y` when `main` still has that code path (use a PR)

---

## Satellite repos

When opening `releaseX.Y`, create the same branch from the matching freeze tag on every participating repo (Earnie, Earnie-env-home, earnie-workspace, earnie-server, Earnie-Projekt, edbert). Keep tips aligned for that cycle’s tags.
