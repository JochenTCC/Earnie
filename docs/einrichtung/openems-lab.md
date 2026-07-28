# OpenEMS-Lab (Earnie ↔ OpenEMS)

Lokaler Compose-Stack für den OpenEMS-EHAL-Prototyp (**2.4.b**): Earnie + OpenEMS Edge + OpenEMS UI. Einordnung gegenüber Loxone und HA+evcc: [Adapter wählen](adapter-wahl.md).

| Service | URL |
| --- | --- |
| Earnie Streamlit | http://localhost:8503 |
| OpenEMS UI | http://localhost:8088 |
| Felix configMgr | http://localhost:8080/system/console/configMgr |
| REST | http://localhost:8084/rest/… |

## Start

```powershell
mkdir openems_lab\config, openems_lab\runtime
docker compose --project-directory . -f docker/compose/openems-lab.yml up -d --build
```

Persistenz: `openems_lab/config/` und `openems_lab/runtime/` (Earnie); OpenEMS-Plant in Docker-Volumes.

## Einrichtung und Kommunikationscheck

Die Schritt-für-Schritt-Anleitung (Earnie-`ehal`-Block, Simulator-Plant, REST-Checks Host + Container) steht in der Entwickler-Spec:

**[docs/spec/openems-lab-setup.md](../spec/openems-lab-setup.md)**

OpenEMS-Plant-Details (Kanal-Tabelle, Pi-Ersttest): [docs/spec/openems-testing-platform-todo.md](../spec/openems-testing-platform-todo.md).

## Stop

```powershell
docker compose --project-directory . -f docker/compose/openems-lab.yml down
```
