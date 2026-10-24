# Branching & Hotfix Playbook

**Status:** current  

How Earnie splits **continuing development** on `main` from **finalizing and maintaining** a planned MINOR on a release branch, including later bugfixes and PATCH releases.

Related: [DEVELOPER.md](../../DEVELOPER.md) (tag → GHCR), [CONTRIBUTING.md](../../CONTRIBUTING.md) (PRs), `.cursor/rules/versioning.mdc` (`version.py` approval), `.cursor/rules/branching-hotfix-playbook.mdc` (agent warns before violations).

---

## Model

| Line | Purpose |
|------|---------|
| **`main`** | Ongoing development. Features for the *next* MINOR (and anything that must **not** ship in the release being finalized). |
| **`release/…`** | Long-lived **release line** for a product MINOR. Opened when the official release is **near** and development should continue on `main`. The planned release is **moved** here and finalized (remaining alpha → beta → rc → official). After the official, this branch also carries **bugfixes** and **PATCH / minor maintenance releases**. |
| **Annotated tags** (`vX.Y.Z`, `vX.Y.Z-alpha.N` / `-beta.N` / `-rc.N`) | Immutable shipped builds. Tag must equal `version.py` (no leading `v`). While a release branch is open for that MINOR, cut its tags from that branch, not from a diverged `main`. |
| **Short-lived `hotfix/…`** | Only when users need a build **now** from an older tag and even the release branch must not ship as-is (rare). |

There is **no** permanent `develop` or `alpha` branch. Pre-release is a **version channel** (`version.py` + tag + `*-alpha.yml` pins) on the active ship line (the release branch once opened, otherwise `main`).

### Branch naming

| Repo kind | Pattern | Example |
|-----------|---------|---------|
| **Single-product** repo (Earnie, edbert, earnie-server) | `release/x.y` | `release/2.7`, `release/0.1` |
| **Multi-product** side repo (shared by several products) | `release/<product>/x.y` | `release/earnie/2.7`, `release/edbert/0.1` |

**Products so far:** `earnie`, `edbert`, and private `earnie-server` (slug = lowercase product id in the path).

**Multi-product side repos** (use the product prefix when that product’s release line lives there): e.g. Earnie-Projekt, Earnie-env-home. Until a side repo actually hosts more than one product’s lines, `release/x.y` is acceptable; prefer `release/<product>/x.y` as soon as a second product appears (or immediately for clarity).

```text
main ── features / next MINOR ──────────────────────────────────────►
         \
          (official near + keep developing)
               \
                release/x.y  (or release/<product>/x.y)
                     ── finalize (beta/rc/official)
                     ── later bugfixes + PATCH tags
                     ── PRs / cherry-picks → main (as needed)
```

---

## When to open the release branch

Open when **both** are true:

1. The **planned official** for that product MINOR is near (hardening / beta / rc territory), and  
2. **Development should continue** on `main` (next features must not block or pollute the release).

Then **move** that planned release onto the branch:

1. Choose the freeze commit (usually the latest community tag on `main`, e.g. `v2.7.0-alpha.9`, or an agreed `main` tip).
2. Create and push the correctly named release branch from that commit on **every** participating repo for that product (Earnie + its side repos; same for edbert when applicable).
3. From then on, **finalize** on that branch only: remaining pre-releases, official `X.Y.Z`, then bugfixes and PATCH releases.
4. Keep `main` free for the next MINOR. Bring single release-line fixes into `main` by **cherry-pick** (`git cherry-pick -x <sha>` on a branch from `main`, then PR) so bugs do not return. The release branch itself **never** merges back into `main` as a whole (see [Release branch never merges back](#release-branch-never-merges-back)). Do **not** rewind `main`’s `version.py` to an older PATCH while `main` already targets a newer pre-release / next MINOR.

`main` alone is enough **before** this split (early alphas while everyone still ships from `main`). After the split, do not cut that MINOR’s release tags from dirty `main`.

Keep the release branch for as long as you still ship PATCH / maintenance for that MINOR. The next MINOR gets its own `release/x.y+1` (or `release/<product>/x.y+1`) when that official becomes near and development must continue again.

---

## What lives on the release branch

| Phase | On `release/…` |
|-------|----------------|
| **Finalize** | Last alphas, beta, rc, official `X.Y.0` (or `X.Y.Z`) |
| **Maintain** | Bugfixes; PATCH bumps (`X.Y.Z+1`, …) after approval |
| **Back to `main`** | PR (or cherry-pick) of fixes that `main` still needs |

Do **not** merge unfinished next-MINOR features from `main` into the release branch. Flow is release → main for single cherry-picked fixes, not main → release for features (unless you explicitly cherry-pick a needed fix the other way).

---

## Release branch never merges back

`release/…` is the ship line of a MINOR: finalize, tag, maintain. It is **not** merged into `main` — neither by PR nor locally. Only single bugfixes travel to `main`, as cherry-picks (new SHAs):

```text
git switch -c fix/<name> origin/main
git cherry-pick -x <sha-on-release>      # -x records the source commit
# push, PR to main
```

Enforced in Earnie by [`scripts/check_no_release_merge.sh`](../../scripts/check_no_release_merge.sh):

- `.githooks/pre-push` rejects a push to `main` that brings in commits living on a `release/*` branch.
- Workflow `Release branch guard` fails a PR from `release/**` (or a branch cut from it) and a push to `main` containing release commits. Make it a required check if direct pushes to `main` are ever disabled.

Docs that exist only on a release branch reach `main` the same way (cherry-pick).

## Decision tree

### 1. Official near + continue developing — open / use `release/…`

```text
freeze → branch release/x.y (or release/<product>/x.y) → finalize & tag there
main continues next MINOR
cherry-pick single fixes → PR to main (never merge release/…)
```

### 2. Default while the release branch is open — fix and release there

```text
fix on release/… → D (if needed) → B (pre-release) or C (official / PATCH)
→ PR (or cherry-pick) code fix to main
```

- Before official: next **`X.Y.Z-alpha.N+1`** / `-beta.N` / `-rc.N`.
- After official: **PATCH** on the release branch after explicit approval, then port code to `main`.

### 3. No release branch yet — fix and publish on `main`

```text
fix on main → D (if needed) → B or C
```

### 4. Urgent — testers/prod stuck on a **tag**; even the release branch is dirty

Use when both are true:

1. Users need the fix **before** unfinished commits on the ship line, and  
2. The ship line already contains commits that must **not** be in that patch.

```text
git checkout -b hotfix/<short-name> <base-tag>
# fix + tests only; D: bump version.py; sync *-alpha.yml if pre-release
# tag from hotfix tip → B or C
# cherry-pick into release/… and (as a separate cherry-pick) onto a branch from main → PR
```

After tagging, delete the hotfix branch.

### 5. Urgent — **prod** (`:latest`) broken; ship line already past that official

```text
git checkout -b hotfix/X.Y.Z+1 vX.Y.Z
# fix + tests; D: version.py → X.Y.Z+1; tag → C
# port *code* to release/… and main; leave their version.py on the ongoing target if already past the PATCH
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
- While a release branch owns that MINOR, cut its tags from that branch.
- After an alpha/beta/rc tag, leave that string on the ship line until the next approved bump.
- Before **B**: `synology-alpha.yml` / `loxberry-alpha.yml` / `proxmox-alpha.yml` must pin `ghcr.io/jochentcc/earnie-energy:<version.py>`.
- **B** and **C** are two-step: the tag builds a *candidate*; users see it only after approving job `promote` ([release-checklist.md](release-checklist.md)). A rejected candidate is not re-tagged; fix and tag the next version.

---

## Hotfix / PATCH checklist

1. Confirm the **base tag** users run.
2. Prefer the open **`release/…`** branch for that product MINOR; otherwise `main`. Use `hotfix/…` only for Case 4/5.
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

- Long-lived `alpha` or `develop` (use `release/…` when the official is near and `main` must continue)
- Tag a commit whose `version.py` does not match the tag
- Force-push or rewrite published tags
- Finalize the planned MINOR on dirty `main` after its release branch exists
- Merge next-MINOR feature work from `main` into the release branch
- Leave a release-line fix only on the release branch when `main` still has that code path (cherry-pick it to `main`)
- Merge `release/…` (or a branch cut from it) into `main`, by PR or locally; only cherry-pick single fixes
- Use a flat `release2.7`-style name (legacy); use `release/x.y` or `release/<product>/x.y`

---

## Satellite / side repos

When opening a release line for a product, create the matching branch from the freeze tag on every participating repo. For multi-product side repos, use `release/<product>/x.y` so Earnie and edbert (and later others) can coexist. Keep tips aligned for that cycle’s tags.
