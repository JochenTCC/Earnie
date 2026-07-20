# Docker — Earnie Container

Alle Container-Artefakte liegen unter `docker/`. Der **Build-Kontext bleibt das Repo-Root** (`.`), damit `COPY optimizer/` usw. im Dockerfile funktionieren.

## `.dockerignore` am Repo-Root

Die Ignore-Datei **bleibt** in der Projektwurzel (`.dockerignore`). Docker wertet sie relativ zum Build-Kontext aus, nicht relativ zum Dockerfile.

## Build

```powershell
python -m scripts.build_container --target synology
python -m scripts.build_container --target all --push
.\docker\build-container.ps1 --target synology --push
```

Dockerfile: `docker/Dockerfile` · Entrypoint: `docker/entrypoint.sh`

## Compose-Stacks

Jeder Stack hat **einen** Service (Streamlit + Auto-Start von `main.py` via `EARNIE_AUTO_START_MAIN=1`). Prod und Alpha sind **getrennte Compose-Dateien** (nicht parallel im selben File).

Immer vom **Repo-Root** mit `--project-directory .`, damit Volume-Pfade (`./earnie_env/…`, `./earnie_env_alpha/…`, `./greenfield/…`) korrekt aufgelöst werden:

| Stack | Datei | Host-Port (UI) | Volumes |
|-------|-------|----------------|---------|
| Lokaler Dev | `docker/compose/dev.yml` | 8521 → 8501 | `earnie_env/` |
| Synology (Prod) | `docker/compose/synology_productive.yml` | 8501 | `earnie_env/` |
| Synology (Alpha) | `docker/compose/synology-alpha.yml` | 8511 → 8501 | `earnie_env_alpha/` |
| LoxBerry (Prod) | `docker/compose/loxberry_productive.yml` | 8501 | `earnie_env/` |
| LoxBerry (Alpha) | `docker/compose/loxberry-alpha.yml` | 8511 → 8501 | `earnie_env_alpha/` |
| Proxmox LXC (Prod) | `docker/compose/proxmox_productive.yml` | 8501 | `earnie_env/` |
| Proxmox LXC (Alpha) | `docker/compose/proxmox-alpha.yml` | 8511 → 8501 | `earnie_env_alpha/` |
| Greenfield | `docker/compose/greenfield.yml` | 8502 → 8501 | `greenfield/` |

Port-Übersicht (venv, NAS-UI): [`docs/referenz/streamlit-ports.md`](../docs/referenz/streamlit-ports.md)

```powershell
docker compose --project-directory . -f docker/compose/dev.yml up -d --build
docker compose --project-directory . -f docker/compose/greenfield.yml up -d --build
docker compose --project-directory . -f docker/compose/synology_productive.yml pull
docker compose --project-directory . -f docker/compose/synology_productive.yml up -d
# Alpha parallel (Image-Tag in der YAML pinnen; eigener Projektname earnie-alpha):
docker compose --project-directory . -f docker/compose/synology-alpha.yml pull
docker compose --project-directory . -f docker/compose/synology-alpha.yml up -d
```

Ausführliche Anleitung: [`docs/einrichtung/container.md`](../docs/einrichtung/container.md)

## Migration vom flachen Root-Layout

Früher lagen `Dockerfile`, `docker-compose*.yml` und `docker-entrypoint.sh` im Repo-Root.

**Entwickler:** Befehle wie oben mit `-f docker/compose/...` und `--project-directory .` verwenden.

**Synology NAS:** Die produktive Datei heißt auf dem Gerät oft `compose.yaml`. Nach einem Repo-Update Inhalt aus `docker/compose/synology_productive.yml` dorthin kopieren. Alten Container `earnie` stoppen/entfernen, dann `docker compose pull && docker compose up -d` (neuer Name: `earnie-productive`).

**LoxBerry:** Entsprechend `docker/compose/loxberry_productive.yml` verwenden.

**Proxmox LXC:** `docker/compose/proxmox_productive.yml` plus LXC-Hilfen unter `docker/proxmox/` — Anleitung: [`docs/einrichtung/proxmox-lxc.md`](../docs/einrichtung/proxmox-lxc.md).
