# Branching & Hotfix Playbook

**Status:** current  

How to develop features on `main` while still shipping bugfixes for a **tagged** official or community pre-release.

Related: [DEVELOPER.md](../../DEVELOPER.md) (tag → GHCR), [CONTRIBUTING.md](../../CONTRIBUTING.md) (PRs), `.cursor/rules/versioning.mdc` (`version.py` approval), `.cursor/rules/branching-hotfix-playbook.mdc` (agent warns before violations).

---

## Model (keep it simple)

| Line | Purpose |
|------|---------|
| **`main`** | Only long-lived branch. Features, normal fixes, publish source. |
| **Annotated tags** (`vX.Y.Z`, `vX.Y.Z-alpha.N`) | Immutable shipped builds. Tag must equal `version.py` (no leading `v`). |
| **Short-lived `hotfix/…`** | Only when users need a build **now** and `main` has commits you refuse to ship. |

There is **no** permanent `develop`, `alpha`, or `release/*` branch. Pre-release is a **version channel** (`version.py` + tag + `*-alpha.yml` pins), not a second git line.

```text
main ──────────────── feature / normal fix ── tag (B or C)
         \
          tag v… (what testers/prod run)
               \
                hotfix/… ── bump version.py ── tag ── merge/cherry-pick → main
```

---

## Decision tree

### 1. Default — fix on `main`, ship with the next build

Use when the bug can wait for the next community or official publish.

```text
fix on main → session publish: D (if needed) → B (alpha/rc) or C (official)
```

- Mid MINOR / alpha cycle: prefer next **`X.Y.Z-alpha.N+1`**, not a PATCH on the last official.
- Official cycle / prod-only patch: **PATCH** (`X.Y.Z` → `X.Y.Z+1`) after explicit approval.

### 2. Urgent — testers stuck on the last **pre-release** tag; `main` is dirty

Use when both are true:

1. Community builds must get the fix **before** unfinished `main` work, and  
2. `main` already contains commits that must **not** be in that patch.

```text
git checkout -b hotfix/<short-name> vX.Y.Z-alpha.N
# fix + tests only
# D: bump version.py → X.Y.Z-alpha.N+1
# sync docker/compose/*-alpha.yml image pins
# commit, push, merge (or PR) into main — or cherry-pick fix commits onto main
# ensure origin/main has matching version.py, then tag → B
```

After tagging, delete the hotfix branch.

### 3. Urgent — **prod** (`:latest` / last official) broken; `main` is already on alpha

```text
git checkout -b hotfix/X.Y.Z+1 vX.Y.Z          # last official tag
# fix + tests
# D: version.py → X.Y.Z+1 (PATCH)
# tag from that line → C (updates :latest)
# port the *code* fix onto main; leave main’s version.py on the ongoing alpha/rc
```

Do **not** rewind `main` to the PATCH version string.

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
- After an alpha/rc tag, leave that string on `main` until the next approved bump.
- Before **B**: `synology-alpha.yml` / `loxberry-alpha.yml` / `proxmox-alpha.yml` must pin `ghcr.io/jochentcc/earnie-energy:<version.py>`.

---

## Hotfix checklist

1. Confirm the **base tag** users run (`git tag -l` / GitHub Releases / compose pin).
2. Branch from that tag: `hotfix/<name>` or `hotfix/X.Y.Z+1`.
3. Ship **only** the fix (+ tests). No drive-by features.
4. Get approval for the new `version.py` string (**D**).
5. If pre-release: sync all three `*-alpha.yml` image lines.
6. Land the same fix on `main` (merge hotfix branch or cherry-pick). Align `version.py` on `main` only when that string is the next intended publish; for official PATCH while `main` is alpha, port **code** only.
7. Push commits; push annotated tag → CI (`.github/workflows/release.yml`).
8. Delete the hotfix branch; move bugfix backlog item to **Verifications Pending** until live OK.

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

- Long-lived `alpha` or `develop` parallel to `main`
- Tag a commit whose `version.py` does not match the tag
- Force-push or rewrite published tags
- Fix prod only on `main` and hope the next full release is “soon enough” when Case 2/3 applies
- Leave a hotfix only on the release tip without porting to `main`

---

## When to add a lasting `release/X.Y` later

Only if you must support an **older official minor for months** while `main` moves to the next minor. Until then, **tag + temporary hotfix** is enough.
