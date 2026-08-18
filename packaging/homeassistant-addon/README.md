# Home Assistant Add-on (Earnie) — packaging notes

Thin Docker wrapper (image-wrapper, not git-clone-build) for the Home Assistant Supervisor, primarily HA Green (`aarch64`; `amd64` for dev/test VMs). Source tree: `earnie/` in this folder — the **development source**. Published add-on repository: [`https://github.com/JochenTCC/ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie), kept in sync via `sync-to-ha-addon-repo.sh`.

Add-on SemVer (`earnie/config.yaml` `version`) is independent of the Earnie app version (`version.py`) — same principle as the LoxBerry plugin (`packaging/loxberry/`).

## Release workflow

The add-on wraps an already-published Earnie release; it doesn't rebuild the app itself. Releasing a new add-on version never triggers [`.github/workflows/release.yml`](../../.github/workflows/release.yml) — that only runs on Earnie git tags (`vX.Y.Z`) in this repo and is what actually produces the `ghcr.io/jochentcc/earnie-energy` image the add-on pulls.

1. Confirm the target Earnie version is already released (GHCR tag exists, e.g. `ghcr.io/jochentcc/earnie-energy:2.5.0`).
2. **In the `Earnie` repo (this repo):** `earnie/build.yaml` — bump `build_from` (both `aarch64` and `amd64` — same multi-arch tag) and `args.EARNIE_VERSION` to that version.
3. **In the `Earnie` repo:** `earnie/config.yaml` — bump `version:` (add-on SemVer, e.g. `0.1.0` → `0.2.0`) — this is what the Supervisor watches to show **Update available**. Bumping only this without step 2 would show an update that rebuilds the exact same underlying image.
4. **In the `Earnie` repo:** add an entry to `earnie/CHANGELOG.md`.
5. **In the `Earnie` repo:** commit and push steps 2–4 as usual (normal PR process) — this lands `packaging/homeassistant-addon/earnie/` in `Earnie`'s own GitHub history. Nothing is pushed to `ha-addon-earnie` yet, but skipping the push here leaves `Earnie`'s GitHub state out of sync with what step 6 is about to copy from your local checkout.
6. **From the `Earnie` repo, targeting a separate local checkout of `ha-addon-earnie`:** run the sync script, pointing it at that checkout:
   ```bash
   packaging/homeassistant-addon/sync-to-ha-addon-repo.sh <path-to-ha-addon-earnie-checkout>
   ```
   This copies `Earnie`'s `packaging/homeassistant-addon/earnie/` into `<ha-addon-earnie-checkout>/earnie/` — a plain file copy, no git operation. Nothing is committed or pushed by the script itself.
7. **In the `ha-addon-earnie` checkout (not `Earnie`):** review the diff the sync produced, then commit and push `main` there — this is the push that the Supervisor actually picks up as an update.

**No GitHub Release/tag is needed in `ha-addon-earnie`.** Unlike the LoxBerry plugin's ZIP-asset AUTOUPDATE, the Supervisor reads custom-repository add-ons directly off the tracked branch and detects updates purely from the `version:` field in `config.yaml` — a plain commit + push is sufficient.

## Local build/test

```bash
cd packaging/homeassistant-addon/earnie
docker build --build-arg EARNIE_VERSION=2.4.0 -t earnie-addon-test:local .
docker run -d --name earnie-addon-test -p 18501:8501 -v <host-dir>:/data earnie-addon-test:local
```

`<host-dir>` stands in for the Supervisor's per-add-on `/data` volume — mirrors what `run.sh` expects (`EARNIE_ENV_PATH=/data/earnie_env`, options read from `<host-dir>/options.json`).

Windows / Git Bash: prefix `docker run`/`docker exec` calls that pass `/data`-style paths with `MSYS_NO_PATHCONV=1`, otherwise MSYS mangles the path and silently mounts an empty volume instead of `<host-dir>`.

Full Supervisor-lifecycle verification (restart/update/backup-restore) needs a real Supervisor (HA OS/Supervised) — a local Docker run only proves the persistence *mechanism* (`EARNIE_ENV_PATH`, bootstrap idempotency), not Supervisor update/backup-restore itself. See [`docs/einrichtung/homeassistant-addon.md`](../../docs/einrichtung/homeassistant-addon.md#testumgebung-für-m3-persistenz-nachweis) for a WSL2-Supervised walkthrough (Option A) and a Raspberry-Pi-4-SD-card walkthrough (Option B).

## Sync mechanism

For 0.1, sync is a manual script run (`sync-to-ha-addon-repo.sh`), not a GitHub Action — decided in the Entwicklungsplan as sufficient for the first release; revisit only if manual syncing becomes a bottleneck.

## Repository split

| Repo | Contents | Purpose |
|---|---|---|
| `Earnie` (this repo) | `packaging/homeassistant-addon/earnie/` | Development source, code review via the normal PR process |
| [`ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie) | `repository.yaml`, `earnie/` (mirrored), `README.md`, `LICENSE.md` | What users actually add as a Supervisor repository URL |
