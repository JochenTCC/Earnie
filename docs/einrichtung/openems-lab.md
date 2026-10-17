# OpenEMS-Lab (Earnie ↔ OpenEMS)

Das OpenEMS-Lab ist ein lokaler Compose-Stack für den OpenEMS-Prototyp der EHAL-Anbindung. Er besteht aus Earnie, OpenEMS Edge und OpenEMS UI. Wie sich OpenEMS von Loxone und HA+evcc abgrenzt, erklärt [Smarthome-Backend wählen](smarthome-backend-wahl.md).

| Service | URL |
| --- | --- |
| Earnie Streamlit | http://localhost:8503 |
| OpenEMS UI | http://localhost:8088 |
| Felix configMgr | http://localhost:8080/system/console/configMgr |
| REST | http://localhost:8084/rest/… |

## Start

Verzeichnisse anlegen und den Stack starten:

```powershell
mkdir openems_lab\config, openems_lab\runtime
docker compose --project-directory . -f docker/compose/openems-lab.yml up -d --build
```

**Persistenz:** Earnie speichert seine Daten in `openems_lab/config/` und `openems_lab/runtime/`. Die OpenEMS-Plant liegt in Docker-Volumes.

## Einrichtung und Kommunikationscheck

Die Schritt-für-Schritt-Anleitung steht in der Entwickler-Spezifikation. Sie umfasst den `ehal`-Block in Earnie, die Simulator-Plant und die REST-Checks von Host und Container aus:

**[docs/dev/openems-lab-setup.md](../dev/openems-lab-setup.md)**

Details zur OpenEMS-Plant (Kanal-Tabelle, Ersttest auf dem Pi): [docs/dev/openems-testing-platform-todo.md](../dev/openems-testing-platform-todo.md).

**Abwesenheitsmodus (optional):** In `house_profiles.json` unter `plant.ehal_bindings.sens_absent_mode` einen Kanal im Format `componentId/ChannelId` eintragen (z. B. `ctrlHoliday0/HolidayMode`). Für OpenEMS gibt es noch keine Zuordnung in der Oberfläche (HITL-Mapper). Der Kanal wird deshalb direkt im Hausprofil (JSON) gepflegt. Details: [Flexible Verbraucher](../konfiguration/flexible-verbraucher.md#abwesenheitsmodus-live).

## Stop

Stack beenden:

```powershell
docker compose --project-directory . -f docker/compose/openems-lab.yml down
```
