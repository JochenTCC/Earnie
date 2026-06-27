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

Der **optimizer-worker** führt beim Start automatisch `verify_loxone_setup` aus (alle konfigurierten Merker inkl. neuer E-Auto-Signale). Ergebnis steht in `runtime/energy_optimizer.log` unter `[loxone-verify]`. Optional:

| Variable | Wirkung |
|----------|---------|
| `ENERGY_OPTIMIZER_VERIFY_LOXONE_ON_START=0` | Prüfung aus |
| `ENERGY_OPTIMIZER_SKIP_LOXONE_VERIFY=1` | Prüfung aus |
| `ENERGY_OPTIMIZER_STRICT_LOXONE_VERIFY=1` | Container startet nicht, wenn eine Prüfung fehlschlägt |

Manuell (z. B. nach Config-Änderung ohne Neustart):

```powershell
python -m scripts.verify_loxone_setup
```

`docker-compose-synology.yml` referenziert `ghcr.io/jochentcc/ernie-energy:latest`.

### 3. Lokaler Test vor dem NAS-Deploy

```powershell
docker compose build
docker compose up -d
```

Nutzt `docker-compose.yml` mit lokalem Build und denselben Mounts (`config/`, `runtime/`, `.env`).

## Streamlit-UI extern (Synology Reverse Proxy)

Produktion nutzt zwei Compose-Services:

| Service | Rolle | Port nach außen |
|---------|--------|-----------------|
| `optimizer-worker` | `python main.py` (Steuerung) | — |
| `optimizer-ui` | Streamlit Live-Cockpit | **8501** nur im LAN (Compose-Mapping) |

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
  streamlit run app.py
  --server.port 8501
  --server.address 0.0.0.0
  --server.enableCORS false
  --server.enableXsrfProtection false
```

Nach Änderung an der Compose-Datei: `docker compose -f docker-compose-synology.yml up -d optimizer-ui` (kein neues Image nötig).

Produktion zeigt nur den Live-Modus (`ENERGY_OPTIMIZER_UI_MODES=live`).

### Typische Probleme

| Symptom | Prüfen |
|---------|--------|
| Seite von außen nicht erreichbar | Fritzbox **443 → NAS**; DSM nicht auf 443 |
| 502 Bad Gateway | `ernie-optimizer-ui` läuft? `http://<NAS-IP>:8501` im LAN |
| UI leer / verbindet nicht | WebSocket-Header am Reverse Proxy |
| Let's Encrypt schlägt fehl | Port 80 erreichbar; IPv6/AAAA bei myfritz; ggf. Synology DDNS |
