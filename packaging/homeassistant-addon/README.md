# Home Assistant Add-on (Earnie) — packaging notes

Thin Docker wrapper (image-wrapper, not git-clone-build) for the Home Assistant Supervisor, primarily HA Green (`aarch64`; `amd64` for dev/test VMs). Source tree: `earnie/` in this folder — the **development source**. Published add-on repository: [`https://github.com/JochenTCC/ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie).

Add-on `version:` in `earnie/config.yaml` / `earnie_prerelease/config.yaml` **mirrors** the Earnie app release (`version.py` / GHCR tag). Official releases bump **both** add-ons; pre-releases bump **only** `earnie_prerelease`. The Supervisor watches `version:` to show **Update available**. Prebuilt images: `ghcr.io/jochentcc/earnie-addon-{arch}:<version>` (`image:` in config.yaml — no on-device build).

## Release workflow (automatic)

Every Earnie git tag triggers [`.github/workflows/release-publish.yml`](../../.github/workflows/release-publish.yml):

1. **Candidate** (job `release`): build and push `ghcr.io/jochentcc/earnie-energy:<version>` (multi-arch, `:<version>` only) and HA add-on images `ghcr.io/jochentcc/earnie-addon-{amd64,aarch64}:<version>` (H6); create the GitHub Release as **draft**.
2. **Pre-gate checks:** `addon_smoke` (`python -m scripts.ha_addon_smoke` — starts the add-on image with `/data/options.json` + `/config`, waits for Streamlit health, checks `config.json` lands in `/config`; amd64 blocking, aarch64 under QEMU soft), `addon_lint` (pin bump + addon-linter in the workspace, no commit), `qemu_smoke` (soft).
3. **Approval** (job `promote`, environment `release-approval`): waits until you approve in the Actions run (*Review deployments*). Test the candidate on your own HA first (below). Approve → `:next` (official also `:latest`) and the GitHub Release is published. Reject → nothing user-visible happened.
4. Job **`publish_ha_addon`** (after approval only): bump add-on trees (`auto` channel), lint, commit Earnie `main`, mirror to **`ha-addon-earnie` `main`** — from this moment HA offers the update.
   - Official → `earnie/` + `earnie_prerelease/`
   - Pre-release → `earnie_prerelease/` only

**No GitHub Release/tag is needed in `ha-addon-earnie`.** The Supervisor reads the tracked branch and detects updates from `config.yaml` `version:`.

The tagged commit itself does not contain the new add-on pins — the bot commit lands on `main` right after approval. That is intentional: pins are add-on metadata, not app source.

### Test a release candidate on your own HA (before approving)

While `promote` waits, the candidate images already exist on GHCR but no user is offered them. Install them on your HA as a **local add-on** (visible on this instance only). Full per-release checklist incl. test points: [docs/spec/release-checklist.md](../../docs/spec/release-checklist.md).

1. Copy `earnie_prerelease/` to `/addons/local/earnie_dev/` on the HA host (Samba or SSH add-on; share `addons`).
2. In the copy's `config.yaml` set `slug: earnie_dev`, `name: "Earnie (Dev)"` and `version: "<candidate version>"`. Keep `image:` — the Supervisor then **pulls** `earnie-addon-{arch}:<version>`, i.e. exactly the artifact users will get (no local build).
3. Apps / Add-on store → ⋮ → *Check for updates* → *Local add-ons* → **Earnie (Dev)** → install/update, start.
4. Stop the regular Earnie add-on first — `run.sh` only guards the `earnie` ↔ `earnie_prerelease` pair, not `earnie_dev`.
5. OK → approve `promote`; broken → reject, fix, bump to the next version and tag again.

Next candidate: only bump `version:` in `/addons/local/earnie_dev/config.yaml` and *Check for updates*.

Local smoke without HA (same check as CI): `python -m scripts.ha_addon_smoke --image ghcr.io/jochentcc/earnie-addon-amd64:<version>`.

### Prerequisites (one-time)

Repository secret **`HA_ADDON_REPO_TOKEN`** on `JochenTCC/Earnie`:

- Fine-grained or classic PAT with **`contents: write`** on **`JochenTCC/Earnie`** and **`JochenTCC/ha-addon-earnie`**
- Without this secret, a release still publishes GHCR + GitHub Release, but `publish_ha_addon` fails with a clear error

### Manual override

**Bump pins locally** (wrapper-only change or retry after a failed publish job):

```bash
python -m scripts.bump_ha_addon --version 2.6.0          # both channels
python -m scripts.bump_ha_addon --version 2.6.0-alpha.2  # prerelease only
packaging/homeassistant-addon/sync-to-ha-addon-repo.sh <path-to-ha-addon-earnie-checkout>
# commit + push both repos
```

**Republish without re-tagging:** Actions → **HA Add-on publish** → enter version (official → both; pre-release → `earnie_prerelease` only). GHCR app + add-on images must already exist. This manual workflow has **no approval gate** — starting it is the approval.

Dry-run locally:

```bash
python -m scripts.bump_ha_addon --version 2.5.0 --dry-run
```

## Local build/test

**Wozu:** Ein schneller, Supervisor-unabhängiger Rauchtest für `Dockerfile` und `run.sh` — Image bauen und direkt per `docker run` starten, ganz ohne HA OS/Supervised und ohne die Apps-Oberfläche (bis HA 2026.1: „Add-on Store"). Nützlich beim Iterieren an `Dockerfile`, `run.sh` oder der Optionen-Auswertung (`config.yaml` → `options`), weil ein Build-and-Restart-Zyklus hier Sekunden dauert statt der Minuten, die ein Reinstall/Update über die Apps-Oberfläche bräuchte. **Was es nicht testet:** die eigentliche Supervisor-Add-on-Lebensdauer (Apps-Bereich, Optionen-UI, Ingress, Backup/Restore) — dafür braucht es einen echten Supervisor, siehe unten.

**Wie:**

```bash
cd packaging/homeassistant-addon/earnie
docker build --build-arg EARNIE_VERSION=2.5.0 -t earnie-addon-test:local .
docker run -d --name earnie-addon-test -p 18501:8501 -v <host-dir>:/data earnie-addon-test:local
```

`<host-dir>` stands in for the Supervisor's per-add-on `/data` volume (options + runtime). For a realistic `addon_config` test also mount a config dir to `/config`:

```bash
docker run -d --name earnie-addon-test -p 18501:8501 \
  -v <host-data>:/data -v <host-config>:/config earnie-addon-test:local
```

`run.sh` sets `EARNIE_CONFIG_PATH=/config` and `EARNIE_RUNTIME_PATH=/data/earnie_env/runtime`.

Windows / Git Bash: prefix `docker run`/`docker exec` calls that pass `/data`-style paths with `MSYS_NO_PATHCONV=1`, otherwise MSYS mangles the path and silently mounts an empty volume instead of `<host-dir>`.

**Erwartetes Ergebnis:**

- `docker build` läuft ohne Fehler durch und erzeugt `earnie-addon-test:local`.
- `docker ps` zeigt den Container als laufend (keine Restart-Schleife). `docker logs earnie-addon-test` zeigt, wie `run.sh` durchläuft (ohne `/data/options.json` greifen einfach die Defaults: `TZ=Europe/Vienna`, Port `8501`, alle drei UI-Modi, Auto-Start an) und danach an den normalen App-Entrypoint (`docker/entrypoint.sh` → Bootstrap → Streamlit) übergibt.
- Im Browser unter `http://localhost:18501` (gemappter Host-Port) erscheint die normale Earnie-Streamlit-Oberfläche.
- In `<host-dir>` tauchen nach dem ersten Start automatisch `earnie_env/config/config.json` und weitere Dateien auf — Beleg dafür, dass `EARNIE_ENV_PATH=/data/earnie_env` korrekt greift und der Bootstrap fehlende Dateien selbst anlegt.
- Bleibt `<host-dir>` leer, ist das meist nicht ein App-Fehler, sondern das MSYS-Pfad-Problem oben (`MSYS_NO_PATHCONV=1` vergessen).

Dieser Test beweist: Image baut, `run.sh`/`jq` funktionieren, Optionen-Defaults greifen korrekt, UI ist erreichbar, Persistenzpfad stimmt — **nicht** Supervisor-Verhalten (Apps-Bereich, Optionen-UI, Backup/Restore), siehe dazu unten.

Für die reguläre Installation des Add-ons in eine echte Home-Assistant-Instanz (Apps-Bereich, Optionen-UI — bis HA 2026.1 „Add-on Store" genannt) siehe [`docs/einrichtung/homeassistant-addon.md`](../../docs/einrichtung/homeassistant-addon.md#installation) — der lokale Docker-Build hier ersetzt das nicht, sondern ergänzt es nur für schnelle Entwicklungs-Iterationen.

Full Supervisor-lifecycle verification (restart/update/backup-restore) needs a real Supervisor (HA OS/Supervised) — a local Docker run only proves the persistence *mechanism* (`EARNIE_ENV_PATH`, bootstrap idempotency), not Supervisor update/backup-restore itself. See [`docs/einrichtung/homeassistant-addon-testumgebung.md`](../../docs/einrichtung/homeassistant-addon-testumgebung.md) for a WSL2-Supervised walkthrough (Option A) and a Raspberry-Pi-4-SD-card walkthrough (Option B).

## Sync mechanism

CI mirrors `earnie/` and `earnie_prerelease/` to [`ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie) (official → both; pre-release → prerelease only). For local dev or manual recovery:

```bash
packaging/homeassistant-addon/sync-to-ha-addon-repo.sh <path-to-ha-addon-earnie-checkout>
```

## CI lint

- **Earnie release:** `publish_ha_addon` runs `frenck/action-addon-linter` on the bumped tree(s) before push.
- **`ha-addon-earnie`:** [`.github/workflows/hassfest.yml`](https://github.com/JochenTCC/ha-addon-earnie/blob/main/.github/workflows/hassfest.yml) lints both add-ons on push/PR to `main`.

## Repository split

| Repo | Contents | Purpose |
|---|---|---|
| `Earnie` (this repo) | `packaging/homeassistant-addon/earnie/` + `earnie_prerelease/` | Development source |
| [`ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie) | `repository.yaml`, both add-on trees (mirrored), `README.md`, `LICENSE.md` | Supervisor repository URL |
