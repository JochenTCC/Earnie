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

Immer vom **Repo-Root** mit `--project-directory .`, damit Volume-Pfade (`./config`, `./runtime`, `./greenfield/...`) korrekt aufgelöst werden:

| Stack | Datei | Port (UI) |
|-------|-------|-----------|
| Lokaler Dev | `docker/compose/dev.yml` | 8501 |
| Synology (Prod) | `docker/compose/synology.yml` | 8501 |
| LoxBerry (Prod) | `docker/compose/loxberry.yml` | 8501 |
| Proxmox LXC (Prod) | `docker/compose/proxmox.yml` | 8501 |
| Greenfield | `docker/compose/greenfield.yml` | 8502 |

```powershell
docker compose --project-directory . -f docker/compose/dev.yml up -d --build
docker compose --project-directory . -f docker/compose/greenfield.yml up -d --build
docker compose --project-directory . -f docker/compose/synology.yml pull
docker compose --project-directory . -f docker/compose/synology.yml up -d
```

Ausführliche Anleitung: [`docs/einrichtung/container.md`](../docs/einrichtung/container.md)

## Migration vom flachen Root-Layout

Früher lagen `Dockerfile`, `docker-compose*.yml` und `docker-entrypoint.sh` im Repo-Root.

**Entwickler:** Befehle wie oben mit `-f docker/compose/...` und `--project-directory .` verwenden.

**Synology NAS:** Die produktive Datei heißt auf dem Gerät oft `compose.yaml`. Nach einem Repo-Update Inhalt aus `docker/compose/synology.yml` dorthin kopieren und `docker compose pull && docker compose up -d` ausführen.

**LoxBerry:** Entsprechend `docker/compose/loxberry.yml` verwenden.

**Proxmox LXC:** `docker/compose/proxmox.yml` plus LXC-Hilfen unter `docker/proxmox/` — Anleitung: [`docs/einrichtung/proxmox-lxc.md`](../docs/einrichtung/proxmox-lxc.md).
