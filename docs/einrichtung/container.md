# Container-Betrieb (Synology / LoxBerry / Proxmox / Docker)

**Streamlit-Ports aller Stacks:** [streamlit-ports.md](../referenz/streamlit-ports.md)

**Proxmox VE (LXC + Docker Compose):** [proxmox-lxc.md](proxmox-lxc.md)

**Docker-Artefakte:** `[docker/README.md](../../docker/README.md)` — Dockerfile, Compose-Dateien und Build-Skripte liegen unter `docker/`. Compose-Befehle immer vom Repo-Root mit `--project-directory .`.

## Persistente Daten

Diese Verzeichnisse liegen **außerhalb des Images** und überleben Image-Updates:


| Mount (Host)                          | Inhalt                                                                                                                  |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `./earnie_env/config/config.json`                | Haus-Konfiguration (wird nie überschrieben)                                                                             |
| `./earnie_env/config/tariffs.json`               | Tarif-Katalog (Bezug/Einspeise); Sidecar neben `config.json`                                                            |
| `./earnie_env/config/backtesting_scenarios.json` | Szenarien inkl. Live-Baseline                                                                                           |
| `./earnie_env/config/house_profiles.json`        | Hausprofile (Sidecar)                                                                                                   |
| `./earnie_env/config/deviation_rules.json`       | Soll/Ist-Regeln für Chart-Marker (Bootstrap legt an)                                                                    |
| `./earnie_env/config/config.example.json`        | Optional auf dem Host; fehlt sie, kopiert der Entrypoint die Vorlage aus dem Image (`share/config/`) für Drift-Hinweise |
| `./earnie_env/runtime/`                          | `cons_data_hourly.csv`, Zustands-JSONs, Profile, Logs                                                                   |
| `./earnie_env/runtime/local_settings.json`       | Lokale Einstellungen (z. B. Silent-Mode)                                                                                |
| `./earnie_env/config/.env`                       | Loxone-Zugangsdaten                                                                                                     |


Umgebungsvariable in Compose: `EARNIE_CONFIG_PATH=config` (Config-Verzeichnis im Container, gemountet als `/app/config`)

## Erstinstallation (NAS)

1. Projektordner mit `docker/compose/synology_productive.yml` anlegen (auf der NAS oft als `compose.yaml` kopiert)
2. `mkdir -p earnie_env/config earnie_env/runtime`
3. Container starten — der **Entrypoint** legt fehlende Dateien an (`.env`, `config.json`, `tariffs.json`, weitere Sidecars, Vorlagen aus `share/config/` falls nötig, leere Runtime-Dateien)
4. `earnie_env/config/.env`, `earnie_env/config/config.json` und `earnie_env/config/tariffs.json` anpassen (Loxone-Zugang, Entitäten, Tarif-IDs der Szenarien)
5. Optional: historische `cons_data` aus Dev nach `earnie_env/runtime/cons_data_hourly.csv` kopieren



## Config-Updates nach Programm-Upgrade

Neue Einträge in `share/config/config.example.json` (Image-Vorlage) werden **nicht** automatisch in die Anwender-Config geschrieben.

- Beim Start von `main.py`: Hinweis im Log
- In der Streamlit-App: gelbes Banner mit fehlenden Pfaden und Beispielwerten
- Fehlende Keys manuell in `earnie_env/config/config.json` ergänzen



## Bootstrap manuell

```powershell
python -m scripts.bootstrap_runtime
```

Legt nur fehlende Dateien an; bestehende bleiben unverändert.

## Image bauen und deployen

Das Image ist ein **Multi-Arch-Manifest** (`linux/amd64` für Synology, `linux/arm64` für LoxBerry). Beide Hosts referenzieren denselben Tag `ghcr.io/jochentcc/earnie-energy:latest`.

**Veröffentlichte Images** kommen von GitHub Releases: ein Tag `vX.Y.Z` (passend zu `version.py`) startet [`.github/workflows/release.yml`](../../.github/workflows/release.yml) und pusht u. a. `ghcr.io/jochentcc/earnie-energy:X.Y.Z` sowie `:latest`. Details für Entwickler: [DEVELOPER.md](../../DEVELOPER.md) § Release.

**Vorabversionen (Community-Test):** Tag `vX.Y.Z-alpha.N` bzw. `vX.Y.Z-rc.N` (ebenfalls passend zu `version.py`) erzeugt ein GitHub **Pre-release** und nur den Image-Tag `:<version>` — **nicht** `:latest`. Zum Testen den Versions-Tag pinnen, z. B. `ghcr.io/jochentcc/earnie-energy:2.2.0-alpha.5`. Prod-Compose (`*_productive.yml`) mit `:latest` bleibt auf der letzten offiziellen Version.

### Alpha parallel zur Produktion (Port 8511)

Eigene Compose-Dateien (nicht in der Prod-YAML): `docker/compose/synology-alpha.yml`, `loxberry-alpha.yml`, `proxmox-alpha.yml`.

- Container `earnie-alpha`, Host-Port **8511**, Volumes unter `./earnie_env_alpha/`
- Compose-Projektname `earnie-alpha` (kollidiert nicht mit Prod `earnie-productive`)
- Image-Tag in der YAML an die gewünschte Pre-release anpassen (aktuell in den Dateien: `2.2.0-alpha.5`)

```powershell
mkdir -p earnie_env_alpha/config earnie_env_alpha/runtime
docker compose --project-directory . -f docker/compose/synology-alpha.yml pull
docker compose --project-directory . -f docker/compose/synology-alpha.yml up -d
```

UI: `http://<host>:8511`. Ports: [streamlit-ports.md](../referenz/streamlit-ports.md). **Nicht** zwei Daemonen mit Schreibzugriff auf denselben Miniserver ohne Silent-Mode / Absprache.

### Einmaliges buildx-Setup (Entwicklungsrechner)

Für Multi-Arch-Builds von Windows/Linux:

```powershell
docker buildx create --name earnie-builder --use
docker buildx inspect --bootstrap
```

Unter Windows nutzt Docker Desktop QEMU für arm64-Cross-Builds automatisch.

### 1. Build (Entwicklungsrechner)

Kanonischer Befehl — nur Synology (amd64), wie bisher:

```powershell
python -m scripts.build_container
# oder unter Windows:
.\docker\build-container.ps1
```

Zielplattform wählen:

```powershell
# Synology (amd64)
python -m scripts.build_container --target synology

# LoxBerry (arm64, lokaler Test)
python -m scripts.build_container --target loxberry

# Beide Plattformen publizieren (buildx, erfordert --push)
python -m scripts.build_container --target all --push
```

Vor `--push` prüft der Build automatisch den gebündelten Tarifkatalog (`share/config/tariffs.json`: Schema, Beispiel-Szenario-Referenzen, DACH-Vollständigkeit). Manuell:

```powershell
python -m scripts.validate_tariffs --check-catalog
```

Auf der NAS vor dem ersten Prod-Cutover (Backlog **2.0 P6**) die produktive Sidecar-Datei prüfen:

```powershell
python -m scripts.validate_tariffs --tariffs share/config/tariffs.json --check-catalog
```

Bei Fehlern bricht `main.py` mit `EARNIE_STRICT_TARIFF_VALIDATE=1` ab (siehe Compose).

Erzeugt standardmäßig Tags aus `version.py` (kanonisch + Legacy-Alias für Übergang):

- Offizielle Version (`X.Y.Z`): `:latest` und `:<version>` für `earnie-energy` und Legacy `ernie-energy`
- Vorabversion (`X.Y.Z-alpha.N` / `-rc.N`): nur `:<version>` (kein `:latest`)

Nach `docker login ghcr.io`:

```powershell
# Einzelplattform
python -m scripts.build_container --target synology --push

# Release für Synology + LoxBerry
python -m scripts.build_container --target all --push
```

Nur ein bestimmter Tag:

```powershell
python -m scripts.build_container --target all --tag ghcr.io/jochentcc/earnie-energy:latest --push
```

Manifest prüfen:

```bash
docker manifest inspect ghcr.io/jochentcc/earnie-energy:latest
```



### 2. Deploy (Synology)

Im Projektordner auf der NAS (nur Compose + persistente Daten, kein Quellcode nötig):

```bash
docker compose --project-directory . -f docker/compose/synology_productive.yml pull
docker compose --project-directory . -f docker/compose/synology_productive.yml up -d
```

Auf der NAS (nur `compose.yaml` im Projektordner, ohne Repo-Checkout):

```bash
docker compose pull
docker compose up -d
```

Beim Start von `main.py` (auch nach Auto-Start aus der UI) laufen automatisch Tarif-Plausibilität und `verify_loxone_setup`. Ergebnis steht in `runtime/earnie.log` (`Tarif-Startup-Prüfung`, `[loxone-verify]`).

**Log-Datei nach Upgrade:** Ab Version 2.0 heißt die Daemon-Logdatei `earnie.log` (früher `energy_optimizer.log`). Beim ersten Start nach dem Upgrade entsteht eine neue Datei; optional die alte manuell umbenennen oder archivieren.

Optional:


| Variable                          | Wirkung                                                |
| --------------------------------- | ------------------------------------------------------ |
| `EARNIE_VERIFY_LOXONE_ON_START=0` | Prüfung aus                                            |
| `EARNIE_SKIP_LOXONE_VERIFY=1`     | Prüfung aus                                            |
| `EARNIE_STRICT_LOXONE_VERIFY=1`   | Container startet nicht, wenn eine Prüfung fehlschlägt |


Manuell (z. B. nach Config-Änderung ohne Neustart):

```powershell
python -m scripts.verify_loxone_setup
```

`docker/compose/synology_productive.yml` referenziert `ghcr.io/jochentcc/earnie-energy:latest`.

### 3. Lokaler Test vor dem NAS-Deploy

```powershell
docker compose --project-directory . -f docker/compose/dev.yml build
docker compose --project-directory . -f docker/compose/dev.yml up -d
```

Nutzt `docker/compose/dev.yml` mit lokalem Build und denselben Mounts (`./earnie_env/config` → `/app/config`, `./earnie_env/runtime` → `/app/runtime`).

### Greenfield Dev-Stack (Ersteinrichtung)

Für Abnahme von Hauskonfigurator und Backtesting auf **leeren** Volumes (Port **8502**, getrennte Container-Namen): [greenfield-dev-stack.md](greenfield-dev-stack.md) und `docker/compose/greenfield.yml`.

## LoxBerry (RPi 4B, arm64)



### Voraussetzungen

- LoxBerry **4.x** (64-bit), Raspberry Pi 4B
- Docker-Plugin installiert und aktiv
- Empfohlen: mind. **4 GB RAM**, SSD statt reiner SD-Karte



### Erstinstallation

1. Projektordner anlegen (z. B. `/opt/earnie-energy/`) mit `docker/compose/loxberry_productive.yml`
2. `mkdir -p earnie_env/config earnie_env/runtime`
3. Container starten — der **Entrypoint** legt fehlende Dateien an (`earnie_env/config/.env`, `config.json`, … im gemounteten Volume)
4. `earnie_env/config/.env`, `earnie_env/config/config.json` und `earnie_env/config/tariffs.json` anpassen (Loxone-Zugang, Entitäten, Tarif-IDs der Szenarien)
5. Optional: historische `cons_data` nach `earnie_env/runtime/cons_data_hourly.csv` kopieren



### Deploy (LoxBerry)

Im Projektordner auf dem LoxBerry (nur Compose + persistente Daten, kein Quellcode nötig):

```bash
docker compose --project-directory . -f docker/compose/loxberry_productive.yml pull
docker compose --project-directory . -f docker/compose/loxberry_productive.yml up -d
```

`docker/compose/loxberry_productive.yml` referenziert dasselbe Multi-Arch-Image wie Synology; Docker wählt automatisch `linux/arm64`.

### UI-Zugriff

Im Hausnetz: `http://<loxberry-ip>:8501`

Von außen gibt es keinen eingebauten Reverse Proxy wie bei Synology DSM. Externer Zugriff nur mit eigenem Reverse Proxy, VPN oder vergleichbarem Setup — Port 8501 nicht ungeschützt in der Fritzbox freigeben.

### Go/No-Go (LoxBerry)


| Kriterium        | Go                                       | No-Go                                      |
| ---------------- | ---------------------------------------- | ------------------------------------------ |
| LoxBerry-Version | 4.x, Docker-Plugin aktiv                 | LoxBerry 3.x oder ohne Docker              |
| Architektur      | 64-bit (aarch64)                         | 32-bit-Image                               |
| RAM              | mind. 4 GB empfohlen                     | unter 2 GB                                 |
| Speicher         | SSD empfohlen                            | nur langsame SD ohne Puffer                |
| MILP-Performance | langsamer als NAS akzeptabel, Log prüfen | Erwartung identischer Laufzeit wie x86-NAS |


Vor Produktivbetrieb: Daemon-Log (`runtime/earnie.log`) auf CBC-Timing und Startfehler prüfen. Optionaler Follow-up: natives `coinor-cbc` im Image für kürzere MILP-Läufe.

## Proxmox LXC (amd64)

Unprivileged LXC mit Docker (`nesting=1`, `keyctl=1`), Compose [`docker/compose/proxmox_productive.yml`](../../docker/compose/proxmox_productive.yml), Bootstrap und `pct`-Beispiel: [proxmox-lxc.md](proxmox-lxc.md).

Kurzform nach CT-Erstellung:

```bash
pct enter <VMID>
# Bootstrap (siehe proxmox-lxc.md) → /opt/earnie mit compose.yaml
cd /opt/earnie
docker compose --project-directory . -f compose.yaml pull
docker compose --project-directory . -f compose.yaml up -d
```

UI: `http://<lxc-ip>:8501`