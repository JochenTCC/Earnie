# Release Checklist (candidate → test → approve)

Per-release checklist for the maintainer. Copy the checklist part into a scratch note (or the release notes draft) and tick it off.

Background: a tag push builds a **candidate** only; nothing reaches users until you approve job `promote` in the Actions run. Workflow: [`.github/workflows/release-publish.yml`](../../.github/workflows/release-publish.yml) · reference: [DEVELOPER.md](../../DEVELOPER.md) (*Candidate → approve → publish*) · branching: [branching-hotfix-playbook.md](branching-hotfix-playbook.md) · agent flow: skill `session-abschluss` Phase 2.

| Who sees what, when | Before approval | After approval |
|---|---|---|
| GHCR `:<version>` (app + `earnie-addon-{arch}`) | yes (pinned users only) | yes |
| GHCR `:next` / `:latest` (LoxBerry, Watchtower, compose) | no | yes (`:latest` official only) |
| GitHub Release | draft | published |
| HA add-on update (`earnie` / `earnie_prerelease`) | no | yes |
| `streamlitcloud` branch | unchanged | reset to the tag (manual step) |

---

## One-time setup (done 2026-09-27)

- [x] GitHub environment `release-approval` with required reviewer `JochenTCC` (prevent self-review **off**, no branch restriction). Check: `gh api repos/JochenTCC/Earnie/environments/release-approval --jq '[.protection_rules[].type] | join(",")'` → `required_reviewers`.
- [x] Local HA test add-on **Earnie (Dev)**: `\\HOMEASSISTANT\addons\earnie_dev` (copy of `packaging/homeassistant-addon/earnie_prerelease/`, `slug: earnie_dev`, host ports `null`, `image:` unchanged → Supervisor pulls the published candidate image). HA slug `local_earnie_dev`, config dir `\\HOMEASSISTANT\addon_configs\local_earnie_dev`.
- [ ] Optional: seed the dev config from the real add-on — copy `\\HOMEASSISTANT\addon_configs\20b22c55_earnie_prerelease\*` → `\\HOMEASSISTANT\addon_configs\local_earnie_dev\` (runtime history under `/data` is not reachable via Samba and starts empty).

Re-create the dev add-on after larger wrapper changes (`run.sh`, `config.yaml` options/schema): copy the folder again and re-apply the four edits above.

---

## Checklist per release

### 1. Prepare

- [ ] `version.py` bump approved and on `origin/main` (tag = `version.py` without `v`)
- [ ] Pre-release: `docker/compose/{synology,loxberry,proxmox}-alpha.yml` pin `ghcr.io/jochentcc/earnie-energy:<version>`
- [ ] Release notes: `.github/release-notes/v<version>.md` — write (or rewrite) them **before** the tag
- [ ] Merge pending items from `.github/release-notes/UNRELEASED.md` into `v<version>.md` (breaking / user-action items near the top), then reset `UNRELEASED.md` to its header
- [ ] **HA add-on Änderungsprotokoll (user-facing):** after `promote`, `bump_ha_addon` copies the **first non-heading prose line** of those release notes into `packaging/homeassistant-addon/earnie[_prerelease]/CHANGELOG.md` (what HA shows as Änderungsprotokoll). Edit that first line for end users: short German, no pin/`latest`/channel jargon, no internal backlog IDs — use Highlights-style bullets users can understand. Optional: after a local `python -m scripts.bump_ha_addon --version <version> --dry-run`, sanity-check the planned CHANGELOG blurb; if the auto blurb is still too technical, expand the first line (or first paragraph as one line) before tagging.
- [ ] `git status` clean, `main` == `origin/main`

### 2. Build the candidate

- [ ] Push the annotated tag:
  ```powershell
  git tag -a v<version> -m "Pre-release v<version>"   # official: "Release v<version>"
  git push origin v<version>
  ```
- [ ] Actions run **Release**: `release` green (fails early if the approval environment is missing)
- [ ] `addon_smoke` (amd64) and `addon_lint` green — if red: candidate failed → step 5 *Reject path*
- [ ] `addon_smoke` (aarch64) / `qemu_smoke`: soft — glance at the logs, investigate if red
- [ ] `promote` shows **Waiting for review**

### 3. Test on the target platforms

**Home Assistant (Earnie (Dev))**

- [ ] `\\HOMEASSISTANT\addons\earnie_dev\config.yaml` → `version: "<version>"`
- [ ] HA: Settings → Add-ons → Add-on Store → ⋮ → **Check for updates** → Earnie (Dev) → **Update**
- [ ] **Stop Earnie (Vorabversion)** (both would drive the same devices; the sibling guard does not cover `earnie_dev`)
- [ ] Start Earnie (Dev), log shows no traceback; version in the UI = `<version> (candidate)` for pre-releases (or `<version>` for official)
- [ ] UI opens via Ingress (sidebar) — no "Not found", no endless starting page
- [ ] Configuration present (house, components, tariffs) — or deliberately fresh
- [ ] Smarthome backend / EHAL: HA entities resolve, live values arrive
- [ ] Daemon runs (auto start) and completes an optimization cycle; plan chart plausible
- [ ] Feature-specific checks for this release (from the release notes / backlog items): …
- [ ] Afterwards: **stop Earnie (Dev), start Earnie (Vorabversion)** again

**Synology (maintainer productive stack)**

In-place pin on the live `earnie-productive` compose (NAS project folder; often `compose.yaml` from `docker/compose/synology_productive.yml`). Candidate images exist as `:<version>` before approval — do **not** use `:next` / `:latest` yet. Do **not** run `earnie-alpha` in parallel if both would write to the same Miniserver / backend.

- [ ] Set `image:` to `ghcr.io/jochentcc/earnie-energy:<version>` (replace `:latest`)
- [ ] `docker compose --project-directory . -f compose.yaml pull` then `up -d` (adjust `-f` if the file name differs)
- [ ] UI on port **8501**; version in the UI = `<version> (candidate)` for pre-releases (or `<version>` for official); no traceback in the container log
- [ ] Daemon runs (auto start) and completes an optimization cycle; plan chart plausible
- [ ] Loxone / EHAL smoke: live values arrive, control path OK for this release
- [ ] Feature-specific checks for this release (from the release notes / backlog items): …
- [ ] Afterwards:
  - **Reject** → restore `image: ghcr.io/jochentcc/earnie-energy:latest`, `pull` + `up -d`
  - **Approve** → leave the pin for now; after step 6 (`:next` / `:latest` updated) switch back to `:latest` (or `:next` if you stay on the pre-release channel) and `pull` + `up -d`

**LoxBerry (optional, if the release touches it)**

- [ ] Plugin settings: channel `pinned`, `EARNIE_PINNED_VERSION=<version>` → *Image aktualisieren*
- [ ] Earnie starts, UI reachable, daemon cycle OK
- [ ] Switch back to channel `stable` / `prerelease`

**Quick local start test without HA (optional)**

- [ ] `python -m scripts.ha_addon_smoke --image ghcr.io/jochentcc/earnie-addon-amd64:<version>`

### 4. Decide

- [ ] Actions run → **Review deployments** → tick `release-approval` →
  - **Approve and deploy** — everything in step 3 OK → continue with step 6
  - **Reject** — anything broken → step 5

### 5. Reject path (failed candidate)

- [ ] Note what failed (backlog bugfix item)
- [ ] Fix on `main`, approve the next version (`alpha.N+1` / PATCH) — **never** re-tag or force-push the rejected tag
- [ ] Optional: delete the draft release of the rejected candidate
- [ ] Start again at step 1

### 6. After approval

- [ ] `promote` and `publish_ha_addon` green
- [ ] GitHub Release published (Pre-release vs Latest correct)
- [ ] GHCR: `:next` (official also `:latest`) point to `<version>`
- [ ] HA: **Earnie (Vorabversion)** (pre-release) / **Earnie** (official) offers the update → install on your own system
- [ ] Reset `streamlitcloud` to the tag:
  ```powershell
  git fetch origin tag v<version>
  git checkout streamlitcloud
  git reset --hard v<version>
  git push --force-with-lease origin streamlitcloud
  git checkout main
  ```
- [ ] Backlog: release entry in `backlog/Backlog-Erledigt.md`
