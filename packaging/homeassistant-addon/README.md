# Home Assistant Add-on (Earnie) — packaging notes

Thin Docker wrapper (image-wrapper, not git-clone-build) for the Home Assistant Supervisor, primarily HA Green (`aarch64`; `amd64` for dev/test VMs). Source tree: `earnie/` in this folder — the **development source**. Published add-on repository: [`https://github.com/JochenTCC/ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie).

Add-on `version:` in `earnie/config.yaml` **mirrors** the Earnie app release (`version.py` / GHCR tag) — e.g. app `2.5.0-alpha.9` → add-on `2.5.0-alpha.9`. This is what the Supervisor watches to show **Update available**.

## Release workflow (automatic)

Every Earnie git tag (`vX.Y.Z`, including alpha/rc) triggers [`.github/workflows/release.yml`](../../.github/workflows/release.yml):

1. Build and push `ghcr.io/jochentcc/earnie-energy:<version>` (multi-arch).
2. Create the GitHub Release.
3. Job **`publish_ha_addon`** (same workflow): bump `packaging/homeassistant-addon/earnie/`, lint with [`frenck/action-addon-linter`](https://github.com/frenck/action-addon-linter), commit to **`main`** here, mirror to **`ha-addon-earnie` `main`**.

**No GitHub Release/tag is needed in `ha-addon-earnie`.** The Supervisor reads the tracked branch and detects updates from `config.yaml` `version:`.

The tagged commit itself does not contain the new add-on pins — the bot commit lands on `main` immediately after the release job. That is intentional: pins are add-on metadata, not app source.

### Prerequisites (one-time)

Repository secret **`HA_ADDON_REPO_TOKEN`** on `JochenTCC/Earnie`:

- Fine-grained or classic PAT with **`contents: write`** on **`JochenTCC/Earnie`** and **`JochenTCC/ha-addon-earnie`**
- Without this secret, the release still publishes GHCR + GitHub Release, but `publish_ha_addon` fails with a clear error

### Manual override

**Bump pins locally** (wrapper-only change or retry after a failed publish job):

```bash
python -m scripts.bump_ha_addon --version 2.5.0-alpha.9
packaging/homeassistant-addon/sync-to-ha-addon-repo.sh <path-to-ha-addon-earnie-checkout>
# commit + push both repos
```

**Republish without re-tagging:** Actions → **HA Add-on publish** ([`.github/workflows/ha-addon-publish.yml`](../../.github/workflows/ha-addon-publish.yml)) → enter the Earnie version (must already exist on GHCR).

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

`<host-dir>` stands in for the Supervisor's per-add-on `/data` volume — mirrors what `run.sh` expects (`EARNIE_ENV_PATH=/data/earnie_env`, options read from `<host-dir>/options.json`).

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

CI mirrors `earnie/` to [`ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie) on every release tag. For local dev or manual recovery, use:

```bash
packaging/homeassistant-addon/sync-to-ha-addon-repo.sh <path-to-ha-addon-earnie-checkout>
```

## CI lint

- **Earnie release:** `publish_ha_addon` runs `frenck/action-addon-linter` before push.
- **`ha-addon-earnie`:** [`.github/workflows/hassfest.yml`](https://github.com/JochenTCC/ha-addon-earnie/blob/main/.github/workflows/hassfest.yml) on push/PR to `main`.

## Repository split

| Repo | Contents | Purpose |
|---|---|---|
| `Earnie` (this repo) | `packaging/homeassistant-addon/earnie/` | Development source, code review via the normal PR process |
| [`ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie) | `repository.yaml`, `earnie/` (mirrored), `README.md`, `LICENSE.md` | What users actually add as a Supervisor repository URL |
