# Container-Betrieb (Synology / LoxBerry / Docker)

**Streamlit-Ports aller Stacks:** [streamlit-ports.md](../referenz/streamlit-ports.md)

## Persistente Daten

Diese Verzeichnisse liegen **außerhalb des Images** und überleben Image-Updates:

| Mount (Host) | Inhalt |
|--------------|--------|
| `./config/config.json` | Haus-Konfiguration (wird nie überschrieben) |
| `./config/tariffs.json` | Tarif-Katalog (Bezug/Einspeise); Sidecar neben `config.json` |
| `./config/backtesting_scenarios.json` | Szenarien inkl. Live-Baseline |
| `./config/house_profiles.json` | Hausprofile (Sidecar) |
| `./config/deviation_rules.json` | Soll/Ist-Regeln für Chart-Marker (Bootstrap legt an) |
| `./config/config.example.json` | Optional auf dem Host; fehlt sie, kopiert der Entrypoint die Vorlage aus dem Image (`share/config/`) für Drift-Hinweise |
| `./runtime/` | `cons_data_hourly.csv`, Zustands-JSONs, Profile, Logs |
| `./runtime/local_settings.json` | Lokale Einstellungen (z. B. Silent-Mode) |
| `./config/.env` | Loxone-Zugangsdaten |

Umgebungsvariable in Compose: `EARNIE_CONFIG_PATH=config/config.json`

## Erstinstallation (NAS)

1. Projektordner mit `docker-compose-synology.yml` anlegen
2. `mkdir -p config runtime`
3. Container starten — der **Entrypoint** legt fehlende Dateien an (`config/.env`, `config.json`, `tariffs.json`, weitere Sidecars, Vorlagen aus `share/config/` falls nötig, leere Runtime-Dateien)
4. `config/.env`, `config/config.json` und **`config/tariffs.json`** anpassen (Loxone-Zugang, Entitäten, Tarif-IDs der Szenarien)
5. Optional: historische `cons_data` aus Dev nach `runtime/cons_data_hourly.csv` kopieren

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

## Image bauen und deployen

Das Image ist ein **Multi-Arch-Manifest** (`linux/amd64` für Synology, `linux/arm64` für LoxBerry). Beide Hosts referenzieren denselben Tag `ghcr.io/jochentcc/earnie-energy:latest`.

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
.\build-container.ps1
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

Vor `--push` prüft der Build automatisch den gebündelten Tarifkatalog (`config/tariffs.json`: Schema, Beispiel-Szenario-Referenzen, DACH-Vollständigkeit). Manuell:

```powershell
python -m scripts.validate_tariffs --check-catalog
```

Auf der NAS vor dem ersten Prod-Cutover (Backlog **2.0 P6**) die produktive Sidecar-Datei prüfen:

```powershell
python -m scripts.validate_tariffs --tariffs config/tariffs.json --check-catalog
```

Bei Fehlern bricht der Worker mit `EARNIE_STRICT_TARIFF_VALIDATE=1` ab (siehe Compose).

Erzeugt standardmäßig vier Tags (kanonisch + Legacy-Alias für Übergang):

- `ghcr.io/jochentcc/earnie-energy:latest`
- `ghcr.io/jochentcc/earnie-energy:<version>` (aus `version.py`)
- `ghcr.io/jochentcc/ernie-energy:latest` (Legacy-Alias, gleicher Digest)
- `ghcr.io/jochentcc/ernie-energy:<version>` (Legacy-Alias)

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
docker compose -f docker-compose-synology.yml pull
docker compose -f docker-compose-synology.yml up -d
```

Der **optimizer-worker** führt beim Start automatisch Tarif-Plausibilität und `verify_loxone_setup` aus. Ergebnis steht in `runtime/earnie.log` (`Tarif-Startup-Prüfung`, `[loxone-verify]`).

**Log-Datei nach Upgrade:** Ab Version 2.0 heißt die Worker-Logdatei `earnie.log` (früher `energy_optimizer.log`). Beim ersten Start nach dem Upgrade entsteht eine neue Datei; optional die alte manuell umbenennen oder archivieren.

Optional:

| Variable | Wirkung |
|----------|---------|
| `EARNIE_VERIFY_LOXONE_ON_START=0` | Prüfung aus |
| `EARNIE_SKIP_LOXONE_VERIFY=1` | Prüfung aus |
| `EARNIE_STRICT_LOXONE_VERIFY=1` | Container startet nicht, wenn eine Prüfung fehlschlägt |

Manuell (z. B. nach Config-Änderung ohne Neustart):

```powershell
python -m scripts.verify_loxone_setup
```

`docker-compose-synology.yml` referenziert `ghcr.io/jochentcc/earnie-energy:latest`.

### 3. Lokaler Test vor dem NAS-Deploy

```powershell
docker compose build
docker compose up -d
```

Nutzt `docker-compose.yml` mit lokalem Build und denselben Mounts (`config/`, `runtime/`).

### Greenfield Dev-Stack (Ersteinrichtung)

Für Abnahme von Hauskonfigurator und Backtesting auf **leeren** Volumes (Port **8502**, getrennte Container-Namen): [greenfield-dev-stack.md](greenfield-dev-stack.md) und `docker-compose-greenfield.yml`.

## LoxBerry (RPi 4B, arm64)

### Voraussetzungen

- LoxBerry **4.x** (64-bit), Raspberry Pi 4B
- Docker-Plugin installiert und aktiv
- Empfohlen: mind. **4 GB RAM**, SSD statt reiner SD-Karte

### Erstinstallation

1. Projektordner anlegen (z. B. `/opt/earnie-energy/`) mit `docker-compose-loxberry.yml`
2. `mkdir -p config runtime`
3. Container starten — der **Entrypoint** legt fehlende Dateien an (`config/.env`, `config/config.json`, …)
4. `config/.env`, `config/config.json` und **`config/tariffs.json`** anpassen (Loxone-Zugang, Entitäten, Tarif-IDs der Szenarien)
5. Optional: historische `cons_data` nach `runtime/cons_data_hourly.csv` kopieren

### Deploy (LoxBerry)

Im Projektordner auf dem LoxBerry (nur Compose + persistente Daten, kein Quellcode nötig):

```bash
docker compose -f docker-compose-loxberry.yml pull
docker compose -f docker-compose-loxberry.yml up -d
```

`docker-compose-loxberry.yml` referenziert dasselbe Multi-Arch-Image wie Synology; Docker wählt automatisch `linux/arm64`.

### UI-Zugriff

Im Hausnetz: `http://<loxberry-ip>:8501`

Von außen gibt es keinen eingebauten Reverse Proxy wie bei Synology DSM. Externer Zugriff nur mit eigenem Reverse Proxy, VPN oder vergleichbarem Setup — Port 8501 nicht ungeschützt in der Fritzbox freigeben.

### Go/No-Go (LoxBerry)

| Kriterium | Go | No-Go |
|-----------|-----|-------|
| LoxBerry-Version | 4.x, Docker-Plugin aktiv | LoxBerry 3.x oder ohne Docker |
| Architektur | 64-bit (aarch64) | 32-bit-Image |
| RAM | mind. 4 GB empfohlen | unter 2 GB |
| Speicher | SSD empfohlen | nur langsame SD ohne Puffer |
| MILP-Performance | langsamer als NAS akzeptabel, Log prüfen | Erwartung identischer Laufzeit wie x86-NAS |

Vor Produktivbetrieb: Worker-Log (`runtime/earnie.log`) auf CBC-Timing und Startfehler prüfen. Optionaler Follow-up: natives `coinor-cbc` im Image für kürzere MILP-Läufe.

## Streamlit-UI extern (Synology Reverse Proxy)

Produktion nutzt zwei Compose-Services:

| Service | Rolle | Port nach außen |
|---------|--------|-----------------|
| `optimizer-worker` | `python main.py` (Steuerung) | — |
| `optimizer-ui` | Streamlit Sunset-2-Sunset-Cockpit | **8501** nur im LAN (Compose-Mapping) |

Im Hausnetz: `http://<NAS-IP>:8501`

Von außen: HTTPS über den **Synology Reverse Proxy** (kein direktes Freigeben von Port 8501 in der Fritzbox).

### Voraussetzungen

1. **Let's-Encrypt-Zertifikat** in der DSM für den externen Hostnamen (z. B. `*.myfritz.net` oder `*.synology.me`)
2. **Fritzbox:** Port **80** und **443** → NAS-IP (80 für Zertifikatserneuerung)
3. **DSM-HTTPS** idealerweise auf Port **5001**, nicht 443 — sonst Konflikt mit dem Reverse Proxy
4. Bei myfritz: **IPv6 für Dynamic DNS deaktivieren**, falls Let's Encrypt die Domain nicht validieren kann (AAAA-Eintrag)

### Reverse-Proxy-Regel (DSM)

**Systemsteuerung → Anmeldeportal → Erweitert → Reverse Proxy**

| | Quelle | Ziel |
|--|--------|------|
| Protokoll | HTTPS | HTTP |
| Hostname | externer Hostname | `127.0.0.1` |
| Port | 443 | 8501 |

- Tab **Erweitert:** Let's-Encrypt-Zertifikat zuweisen
- Tab **Benutzerdefinierte Kopfzeile → Erstellen → WebSocket** (für Streamlit)

Optional: **Zugriffssteuerungsprofil** mit DSM-Anmeldung — Streamlit hat keine eigene Login-Abfrage.

### Streamlit hinter dem Proxy

`docker-compose-synology.yml` startet die UI mit Proxy-tauglichen Flags:

```yaml
command: >
  python -m scripts.run_streamlit
  --
  --server.enableCORS false
  --server.enableXsrfProtection false
```

Port in `config/config.json` → `ui.streamlit_port` (Standard 8501). Das Compose-Mapping `ports` muss denselben Wert verwenden.

Nach Änderung an der Compose-Datei: `docker compose -f docker-compose-synology.yml up -d optimizer-ui` (kein neues Image nötig).

Produktion: `EARNIE_UI_MODES=sunset2sunset,scenario_exploration` (in `docker-compose-synology.yml` am Service `optimizer-ui`). Nur Sunset-2-Sunset ohne Scenario-Exploration: `sunset2sunset`. Details: [Betriebsmodi](../ui/betriebsmodi.md).

### Typische Probleme

| Symptom | Prüfen |
|---------|--------|
| Seite von außen nicht erreichbar | Fritzbox **443 → NAS**; DSM nicht auf 443 |
| 502 Bad Gateway | `earnie-optimizer-ui` läuft? `http://<NAS-IP>:8501` im LAN |
| UI leer / verbindet nicht | WebSocket-Header am Reverse Proxy |
| Let's Encrypt schlägt fehl | Port 80 erreichbar; IPv6/AAAA bei myfritz; ggf. Synology DDNS |
