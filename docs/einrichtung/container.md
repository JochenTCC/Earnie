# Container-Betrieb (Synology / LoxBerry / Proxmox / Docker)

**Streamlit-Ports aller Stacks:** [streamlit-ports.md](../dev/streamlit-ports.md)

**Proxmox VE (LXC + Docker Compose):** [proxmox-lxc.md](proxmox-lxc.md)

**Windows-PC mit VMware Workstation (`vctl`):** [vmware-vctl.md](vmware-vctl.md)

**Docker-Artefakte:** [docker/README.md](../../docker/README.md). Dockerfile, Compose-Dateien und Build-Skripte liegen unter `docker/`. Compose-Befehle immer vom Repo-Root mit `--project-directory .` ausführen.

## CPU-Voraussetzung (amd64)

Auf x86 (`amd64`: Synology, Proxmox, VMware, HA-Add-on) braucht Earnie eine CPU mit dem Befehlssatz **x86-64-v2** (u. a. SSE4.2, POPCNT – jede x86-CPU ab ca. 2009). Die mitgelieferten Bibliotheken NumPy und pyarrow laufen ohne diese Befehle nicht. Auf `arm64` (LoxBerry, Home Assistant Green) spielt das keine Rolle.

Der Container prüft das beim Start (`docker/preflight.sh`). Fehlt x86-64-v2, bricht er mit einer klaren Meldung ab statt mit einem Python-Traceback: `earnie: FEHLER - die CPU unterstützt den Befehlssatz x86-64-v2 nicht`. Dieselbe Startprüfung bricht auch in diesen Fällen ab:

- Das Config- oder Runtime-Verzeichnis ist nicht beschreibbar.
- Die Systemuhr liegt vor dem Build-Datum des Images (kurz auf NTP warten).

Bei wenig RAM (< 2 GB) oder wenig freiem Speicher (< 500 MB) erscheint nur eine Warnung.

Meist liegt die Ursache nicht in der Hardware. Häufiger steckt eine **VM mit CPU-Typ `kvm64`/`qemu64`** dahinter (bei älteren Proxmox-VMs Standard). Abhilfe in Proxmox:

1. VM herunterfahren (**Shutdown**).
2. VM → **Hardware** → **Prozessoren** → **Bearbeiten**.
3. **Typ** `host` wählen (alternativ `x86-64-v2-AES`) → **OK**.
4. VM wieder starten. Ein Neustart aus der VM heraus reicht nicht, sie muss aus- und wieder eingeschaltet werden.

Proxmox-**LXC** nutzt die CPU des Hosts direkt; dort tritt das Problem nur bei sehr alter Hardware auf. Zur Prüfung muss `grep -o -w -E 'sse4_2|popcnt' /proc/cpuinfo | sort -u` beide Begriffe ausgeben.

## Gesundheitsprüfung (Docker HEALTHCHECK)

Das Image enthält einen `HEALTHCHECK` auf `http://127.0.0.1:<Streamlit-Port>/_stcore/health` (Standard **8501**; im HA-Add-on intern **8502**). Läuft der Optimierer-Dienst (`main.py`), muss zusätzlich die Datei `runtime/daemon_heartbeat.json` frisch sein, sonst meldet der Container `unhealthy`.

Status abfragen (Compose/Synology): `docker inspect --format='{{.State.Health.Status}}' <container>`.

## Persistente Daten

Diese Verzeichnisse liegen **außerhalb des Images** und überleben Image-Updates:


| Mount (Host)                          | Inhalt                                                                                                                  |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `./earnie_env/config/config.json`                | Haus-Konfiguration (wird nie überschrieben)                                                                             |
| `./earnie_env/config/tariffs.json`               | Tarif-Katalog (Bezug/Einspeise); Sidecar neben `config.json`                                                            |
| `./earnie_env/config/grid_fees.json`             | Netzentgelt-Katalog (Netzbereiche / Zeitregeln); Sidecar; Bootstrap aus `share/config/`                                 |
| `./earnie_env/config/backtesting_scenarios.json` | Szenarien inkl. Live-Baseline                                                                                           |
| `./earnie_env/config/house_profiles.json`        | Hausprofile (Sidecar)                                                                                                   |
| `./earnie_env/config/components.json`            | Gerätekomponenten (`batteries[]`, `pv_systems`, `inverters[]` inkl. `ehal_bindings`)                                    |
| `./earnie_env/config/deviation_rules.json`       | Soll/Ist-Regeln für Chart-Marker (Bootstrap legt an)                                                                    |
| `./earnie_env/config/config.example.json`        | Optional auf dem Host; fehlt sie, kopiert der Entrypoint die Vorlage aus dem Image (`share/config/`) für Drift-Hinweise |
| `./earnie_env/runtime/`                          | `cons_data.csv`, Zustands-JSONs, Profile, Logs                                                                   |
| `./earnie_env/runtime/local_settings.json`       | Lokale Einstellungen (z. B. Silent-Mode)                                                                                |
| `./earnie_env/config/.env`                       | Loxone- und HA-Zugangsdaten (`LOXONE_*` / `EHAL_HA_*`); optional `EARNIE_LAN_SUBNET` |


Umgebungsvariable in Compose: `EARNIE_ENV_PATH=.`. Daraus leitet Earnie `/app/config` und `/app/runtime` ab; die Host-Mounts lauten `./…/config` → `/app/config` und `./…/runtime` → `/app/runtime`.

## Netzwerk: Docker-Bridge, Heimnetz und Miniserver-Rückkanal

Earnie läuft in Compose **ohne** `network_mode: host`. Die Container-IP liegt typischerweise in `172.16.0.0/12` (Docker-Bridge). Das hat zwei Folgen:

- **mDNS/SSDP** (Suche nach Home Assistant / Loxone) erreicht das Heimnetz oft nicht.
- Ein aktiver Portscan ohne Angabe würde fälschlich das **Docker-Netz** durchsuchen.

**Heimnetz für die erweiterte Suche:** `EARNIE_LAN_SUBNET` als `/24`-CIDR setzen, z. B. `192.168.178.0/24`. Dafür gibt es zwei Wege:

- in `earnie_env/config/.env` bzw. in der Compose-`.env`,
- auf der Seite **Smarthome-Backend**, wenn Earnie nach dem LAN fragt.

LoxBerry setzt `EARNIE_LAN_SUBNET` bei Installation und Upgrade aus der Host-IP. Im HA-Add-on ermittelt Earnie die LAN-IP des Hosts über die Supervisor-API (`/network/info`).

**Home Assistant als Backend (nicht Add-on):** Bleibt die Suche leer, auf **Smarthome-Backend** direkt `EHAL_HA_BASE_URL` und Long-Lived Token eintragen, statt auf mDNS zu warten.

**Miniserver → Earnie (Port 8541):** Der Miniserver muss den Earnie-Host unter einer stabilen Adresse erreichen (`VO_Earnie_Status` / Virtual In → Host:8541). Dazu:

- VM bzw. Container im **Bridged**-LAN betreiben (nicht NAT).
- Dem Earnie-Host eine **feste IP** oder **DHCP-Reservierung** geben, damit die Adresse in der Loxone Config gültig bleibt.

Auf **Smarthome-Backend** und **EHAL-Com** zeigt Earnie „Letzter Aufruf vom Miniserver: vor X min von IP Y“. Damit lässt sich der Rückkanal ohne zusätzliche Werkzeuge prüfen.

## Erstinstallation (NAS)

1. Projektordner mit `docker/compose/synology_productive.yml` anlegen (auf der NAS oft als `compose.yaml` kopiert).
2. Verzeichnisse anlegen: `mkdir -p earnie_env/config earnie_env/runtime`.
3. Container starten. Der **Entrypoint** legt fehlende Dateien an: `.env`, `config.json`, `tariffs.json`, weitere Sidecars, bei Bedarf Vorlagen aus `share/config/` sowie leere Runtime-Dateien.
4. `earnie_env/config/.env`, `earnie_env/config/config.json` und `earnie_env/config/tariffs.json` anpassen (Loxone-Zugang, Entitäten, Tarif-IDs der Szenarien).
5. Optional: historische `cons_data` aus Dev nach `earnie_env/runtime/cons_data.csv` kopieren.



## Config-Updates nach Programm-Upgrade

Neue Einträge in `share/config/config.example.json` (Image-Vorlage) übernimmt Earnie **nicht** automatisch in die Anwender-Config. Stattdessen weist Earnie auf fehlende Einträge hin:

- **Beim Start von `main.py`:** Hinweis im Log.
- **In der Streamlit-App:** gelbes Banner mit den fehlenden Pfaden und Beispielwerten.

Die fehlenden Keys manuell in `earnie_env/config/config.json` ergänzen.

Davon zu unterscheiden ist der Migrations-Assistent für das Datenmodell. Zeigt Earnie nach einem Image-Update nur diesen Assistenten (Pack-JSON-Form), beschreibt [Betrieb → Update und Migration](betrieb.md#update-und-migration) das Vorgehen. Backups liegen dann unter `earnie_env/config/backups/pre-migration-…/`.



## Bootstrap manuell

```powershell
python -m scripts.bootstrap_runtime
```

Der Befehl legt nur fehlende Dateien an; bestehende bleiben unverändert.

## Image bauen und deployen

Das Image ist ein **Multi-Arch-Manifest** (`linux/amd64` für Synology, `linux/arm64` für LoxBerry). Beide Hosts referenzieren denselben Tag `ghcr.io/jochentcc/earnie-energy:latest`.

**Veröffentlichte Images** entstehen über GitHub Actions. Ein Tag `vX.Y.Z` (passend zu `version.py`) startet [`.github/workflows/release-publish.yml`](../../.github/workflows/release-publish.yml). Der Workflow baut zuerst nur den **Release-Kandidaten** `ghcr.io/jochentcc/earnie-energy:X.Y.Z`; der Tag allein setzt weder `:latest` noch `:next`. Nach manueller Freigabe des Jobs `promote` (Environment `release-approval`) folgen `:latest` (nur offizielle Versionen) bzw. `:next` sowie die veröffentlichte GitHub Release. Details: [DEVELOPER.md](../../DEVELOPER.md) § Release.

**Vorabversionen (Community-Test):** Ein Tag `vX.Y.Z-alpha.N`, `vX.Y.Z-beta.N` bzw. `vX.Y.Z-rc.N` (ebenfalls passend zu `version.py`) durchläuft denselben Ablauf. Zuerst entsteht der Kandidat `:<version>`, nach `promote` zusätzlich `:next` und ein GitHub **Pre-release**, jedoch **kein** `:latest`.

Zum Testen entweder `:next` verwenden (nach Freigabe) oder den Versions-Tag aus der Alpha-Compose pinnen (aktuell in den Dateien: `2.7.0-alpha.2`). Der Pin wird erst mit der nächsten Vorabversion aktualisiert und kann daher älter sein als die letzte offizielle Version. Die produktiven Compose-Dateien (`*_productive.yml`) mit `:latest` bleiben auf der letzten offiziellen Version.

### Alpha parallel zur Produktion (Port 8511)

Für die Alpha gibt es eigene Compose-Dateien, getrennt von der Prod-YAML: `docker/compose/synology-alpha.yml`, `loxberry-alpha.yml`, `proxmox-alpha.yml`.

- **Container:** `earnie-alpha`, Host-Port **8511**, Volumes unter `./earnie_env_alpha/`.
- **Compose-Projektname:** `earnie-alpha`; er kollidiert nicht mit dem Prod-Projekt `earnie-productive`.
- **Image-Tag:** in der YAML an die gewünschte Pre-release anpassen (aktuell in den Dateien: `2.7.0-alpha.2`).

```powershell
mkdir -p earnie_env_alpha/config earnie_env_alpha/runtime
docker compose --project-directory . -f docker/compose/synology-alpha.yml pull
docker compose --project-directory . -f docker/compose/synology-alpha.yml up -d
```

UI: `http://<host>:8511`. Ports: [streamlit-ports.md](../dev/streamlit-ports.md).

> **Hinweis:** Zwei Optimierer-Dienste dürfen nicht gleichzeitig mit Schreibzugriff auf denselben Miniserver laufen, außer mit Silent-Mode oder nach Absprache.

### Einmaliges buildx-Setup (Entwicklungsrechner)

Für Multi-Arch-Builds unter Windows oder Linux:

```powershell
docker buildx create --name earnie-builder --use
docker buildx inspect --bootstrap
```

Unter Windows nutzt Docker Desktop QEMU für arm64-Cross-Builds automatisch.

### 1. Build (Entwicklungsrechner)

Standardbefehl, baut wie bisher nur für Synology (amd64):

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

Auf der NAS vor der ersten Umstellung auf den Produktivbetrieb die produktive Sidecar-Datei prüfen:

```powershell
python -m scripts.validate_tariffs --tariffs share/config/tariffs.json --check-catalog
```

Mit `EARNIE_STRICT_TARIFF_VALIDATE=1` bricht `main.py` bei Fehlern ab (siehe Compose).

Ein lokaler `build_container` (ohne CI) setzt Standard-Tags aus `version.py`, jeweils für den kanonischen Namen und den Legacy-Alias:

- **Jede Version:** `:next` und `:<version>` für `earnie-energy` und Legacy `ernie-energy`.
- **Offizielle Version (`X.Y.Z`):** zusätzlich `:latest`.
- **Vorabversion (`X.Y.Z-alpha.N` / `-beta.N` / `-rc.N`):** kein `:latest`.

Im **CI-Release** (Tag → `release-publish.yml`) gilt abweichend: Der Tag-Build setzt nur `:<version>`; `:next` / `:latest` folgen erst nach dem Job `promote`.

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

Im Projektordner auf der NAS (nur Compose und persistente Daten, kein Quellcode nötig):

```bash
docker compose --project-directory . -f docker/compose/synology_productive.yml pull
docker compose --project-directory . -f docker/compose/synology_productive.yml up -d
```

Liegt auf der NAS nur `compose.yaml` im Projektordner (ohne Repo-Checkout):

```bash
docker compose pull
docker compose up -d
```

Beim Start von `main.py` (auch nach Auto-Start aus der UI) laufen automatisch die Tarif-Plausibilitätsprüfung und `verify_loxone_setup`. Das Ergebnis steht in `runtime/earnie.log` (`Tarif-Startup-Prüfung`, `[loxone-verify]`).

Optional:


| Variable                          | Wirkung                                                |
| --------------------------------- | ------------------------------------------------------ |
| `EARNIE_VERIFY_LOXONE_ON_START=0` | Prüfung aus                                            |
| `EARNIE_SKIP_LOXONE_VERIFY=1`     | Prüfung aus                                            |
| `EARNIE_STRICT_LOXONE_VERIFY=1`   | Container startet nicht, wenn eine Prüfung fehlschlägt |


Manuell (z. B. nach einer Config-Änderung ohne Neustart):

```powershell
python -m scripts.verify_loxone_setup
```

`docker/compose/synology_productive.yml` referenziert `ghcr.io/jochentcc/earnie-energy:latest`.

### Live-Zyklus-Profiling (NAS-Einmal-Test)

Phasen-Timing und optional `cProfile` lassen sich über Umgebungsvariablen einschalten (`EARNIE_CYCLE_TIMING` / `EARNIE_CYCLE_PROFILE`, siehe [betrieb.md](betrieb.md) § Live-Zyklus-Profiling). Die Compose-Dateien im Repository bleiben unverändert; die Variablen nur auf der NAS für das Testfenster setzen.

**1. Image lokal bauen** (Entwicklungsrechner, Synology amd64, ohne GHCR-Push):

```powershell
python -m scripts.build_container --target synology
```

Die Tags kommen aus `version.py` (u. a. `:next` und `:<version>`; bei Dev-Versionen kein `:latest`).

**2. Image auf die NAS bringen** (Beispiel mit `docker save` / `load`; Tag ggf. anpassen):

```powershell
docker save -o earnie-timing.tar ghcr.io/jochentcc/earnie-energy:next
# Datei auf die NAS kopieren, dann:
docker load -i earnie-timing.tar
```

**3. Produktiv-Compose auf der NAS** vorübergehend anpassen:

- `image:` auf den geladenen Tag zeigen lassen (z. B. `…:next` oder `…:<version>`). Alternativ das lokal geladene Image als `…:latest` retaggen, wenn die Compose-Datei `:latest` behalten soll.
- Unter `environment:` für das Testfenster ergänzen:

```yaml
EARNIE_CYCLE_TIMING: "1"
# optional nur 1–2 Zyklen:
# EARNIE_CYCLE_PROFILE: "1"
```

Danach `docker compose up -d` ausführen. Nach einigen Viertelstunden aufräumen:

1. `EARNIE_CYCLE_PROFILE` entfernen (falls gesetzt).
2. `timing/` und ggf. `profile/` aus `earnie_env/runtime/` kopieren.
3. Die Flags entfernen und das Image wieder auf den vorherigen Stand stellen.

**4. Auswerten:**

```powershell
python -m scripts.summarize_cycle_timing path/to/cycles.jsonl
```

### 3. Lokaler Test vor dem NAS-Deploy

```powershell
docker compose --project-directory . -f docker/compose/dev.yml build
docker compose --project-directory . -f docker/compose/dev.yml up -d
```

Dieser Test nutzt `docker/compose/dev.yml` mit lokalem Build und denselben Mounts (`./earnie_env/config` → `/app/config`, `./earnie_env/runtime` → `/app/runtime`).

### Greenfield Dev-Stack (Ersteinrichtung)

Für die Abnahme von Hauskonfigurator und Backtesting auf **leeren** Volumes (Port **8502**, getrennte Container-Namen): [greenfield-dev-stack.md](greenfield-dev-stack.md) und `docker/compose/greenfield.yml`.

## LoxBerry (RPi 4B, arm64)

**Empfohlen für die meisten Installationen:** das [LoxBerry-Plugin](loxberry-plugin.md) (ZIP in der Plugin-Verwaltung). Die folgenden Abschnitte beschreiben die **manuelle** Compose-Installation, z. B. unter `/opt/earnie-energy/`.

> **Hinweis:** Plugin und manuelle Compose-Installation nicht parallel betreiben. Beide nutzen denselben Container-Namen `earnie-productive` und Port 8501.

### Voraussetzungen

- LoxBerry **4.x** (64-bit), Raspberry Pi 4B
- Docker-Plugin installiert und aktiv
- Empfohlen: mind. **4 GB RAM**, SSD statt reiner SD-Karte



### Erstinstallation

1. Projektordner anlegen (z. B. `/opt/earnie-energy/`) mit `docker/compose/loxberry_productive.yml`.
2. Verzeichnisse anlegen: `mkdir -p earnie_env/config earnie_env/runtime`.
3. Container starten. Der **Entrypoint** legt fehlende Dateien im gemounteten Volume an (`earnie_env/config/.env`, `config.json`, …).
4. `earnie_env/config/.env`, `earnie_env/config/config.json` und `earnie_env/config/tariffs.json` anpassen (Loxone-Zugang, Entitäten, Tarif-IDs der Szenarien).
5. Optional: historische `cons_data` nach `earnie_env/runtime/cons_data.csv` kopieren.



### Deploy (LoxBerry)

Im Projektordner auf dem LoxBerry (nur Compose und persistente Daten, kein Quellcode nötig):

```bash
docker compose --project-directory . -f docker/compose/loxberry_productive.yml pull
docker compose --project-directory . -f docker/compose/loxberry_productive.yml up -d
```

`docker/compose/loxberry_productive.yml` referenziert dasselbe Multi-Arch-Image wie Synology; Docker wählt automatisch `linux/arm64`.

### UI-Zugriff

Im Hausnetz: `http://<loxberry-ip>:8501`

Anders als Synology DSM bringt LoxBerry keinen eingebauten Reverse Proxy mit. Externer Zugriff ist nur über einen eigenen Reverse Proxy, ein VPN oder ein vergleichbares Setup möglich. Port 8501 nicht ungeschützt in der Fritzbox freigeben.

### Go/No-Go (LoxBerry)


| Kriterium        | Go                                       | No-Go                                      |
| ---------------- | ---------------------------------------- | ------------------------------------------ |
| LoxBerry-Version | 4.x, Docker-Plugin aktiv                 | LoxBerry 3.x oder ohne Docker              |
| Architektur      | 64-bit (aarch64)                         | 32-bit-Image                               |
| RAM              | mind. 4 GB empfohlen                     | unter 2 GB                                 |
| Speicher         | SSD empfohlen                            | nur langsame SD ohne Puffer                |
| MILP-Performance | langsamer als NAS akzeptabel, Log prüfen | Erwartung identischer Laufzeit wie x86-NAS |


Vor dem Produktivbetrieb das Daemon-Log (`runtime/earnie.log`) auf MILP-Laufzeiten und Startfehler prüfen. Standard-Solver ist **HiGHS** (`highspy`); CBC bleibt als Fallback über `EARNIE_MILP_SOLVER=cbc` bzw. SE-`milp_solver` verfügbar.

## Proxmox LXC (amd64)

Unprivilegierter LXC mit Docker (`nesting=1`, `keyctl=1`), Compose [`docker/compose/proxmox_productive.yml`](../../docker/compose/proxmox_productive.yml), Bootstrap und `pct`-Beispiel: [proxmox-lxc.md](proxmox-lxc.md).

Kurzform nach dem Anlegen des Containers (CT):

```bash
pct enter <VMID>
# Bootstrap (siehe proxmox-lxc.md) → /opt/earnie mit compose.yaml
cd /opt/earnie
docker compose --project-directory . -f compose.yaml pull
docker compose --project-directory . -f compose.yaml up -d
```

UI: `http://<lxc-ip>:8501`

## Windows-PC mit VMware Workstation (`vctl`)

Ohne Docker Desktop läuft das veröffentlichte Image über VMware **`vctl`**; die Daten liegen unter `%USERPROFILE%\Earnie\earnie_env\`. Hilfsskript und Schritt-für-Schritt-Anleitung: [vmware-vctl.md](vmware-vctl.md).

```powershell
.\scripts\run_earnie_vctl.ps1 -Action up
```

UI: `http://localhost:8501`
