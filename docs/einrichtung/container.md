# Container-Betrieb (Synology / Docker)

## Persistente Daten

Diese Verzeichnisse liegen **außerhalb des Images** und überleben Image-Updates:

| Mount (Host) | Inhalt |
|--------------|--------|
| `./config/config.json` | Haus-Konfiguration (wird nie überschrieben) |
| `./config/config.example.json` | Optional auf dem Host; fehlt sie, kopiert der Entrypoint die Vorlage aus dem Image (`share/config/`) für Drift-Hinweise |
| `./runtime/` | `cons_data_hourly.csv`, Zustands-JSONs, Profile, Logs |
| `./.env` | Loxone-Zugangsdaten |

Umgebungsvariable in Compose: `ENERGY_OPTIMIZER_CONFIG_PATH=config/config.json`

## Erstinstallation (NAS)

1. Projektordner mit `docker-compose-synology.yml` und `.env` anlegen
2. `mkdir -p config runtime`
3. Container starten — der **Entrypoint** legt fehlende Dateien an (`config/config.example.json` → `config/config.json`, Vorlagen aus `share/config/` falls nötig, leere Runtime-Dateien)
4. `config/config.json` anpassen (Loxone-Namen, Verbraucher)
5. Optional: historische `cons_data` aus Dev nach `runtime/cons_data_hourly.csv` kopieren

## Migration vom alten Layout

Wenn Dateien noch im Projektroot liegen (ältere Deployments):

```powershell
python -m scripts.migrate_persist_layout          # Vorschau
python -m scripts.migrate_persist_layout --apply
```

Anschließend Compose mit den drei Mounts (`config/`, `runtime/`, `.env`) verwenden.

## Config-Updates nach Programm-Upgrade

Neue Einträge in `config/config.example.json` werden **nicht** automatisch in die Anwender-Config geschrieben.

- Beim Start von `main.py`: Hinweis im Log
- In der Streamlit-App: gelbes Banner mit fehlenden Pfaden und Beispielwerten
- Fehlende Keys manuell in `config/config.json` ergänzen

## Bootstrap manuell

```powershell
python -m scripts.bootstrap_runtime
```

Legt nur fehlende Dateien an; bestehende bleiben unverändert.

## Image bauen und auf die NAS bringen

### 1. Build (Entwicklungsrechner)

Kanonischer Befehl — baut für **linux/amd64** (Synology):

```powershell
python -m scripts.build_container
# oder unter Windows:
.\build-container.ps1
```

Erzeugt standardmäßig zwei Tags:

- `ghcr.io/jochentcc/ernie-energy:latest`
- `ghcr.io/jochentcc/ernie-energy:<version>` (aus `version.py`)

Nach `docker login ghcr.io`:

```powershell
python -m scripts.build_container --push
```

Nur ein bestimmter Tag:

```powershell
python -m scripts.build_container --tag ghcr.io/jochentcc/ernie-energy:latest --push
```

### 2. Deploy (Synology)

Im Projektordner auf der NAS (nur Compose + persistente Daten, kein Quellcode nötig):

```bash
docker compose -f docker-compose-synology.yml pull
docker compose -f docker-compose-synology.yml up -d
```

`docker-compose-synology.yml` referenziert `ghcr.io/jochentcc/ernie-energy:latest`.

### 3. Lokaler Test vor dem NAS-Deploy

```powershell
docker compose build
docker compose up -d
```

Nutzt `docker-compose.yml` mit lokalem Build und denselben Mounts (`config/`, `runtime/`, `.env`).
