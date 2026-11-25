# Container-Betrieb (Synology / LoxBerry / Proxmox / Docker)

**Streamlit-Ports aller Stacks:** [streamlit-ports.md](../dev/streamlit-ports.md) (Entwickler-Doku auf Englisch)

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

## Healthcheck (Docker `HEALTHCHECK`)

Das Image enthält einen `HEALTHCHECK` auf `http://127.0.0.1:<Streamlit-Port>/_stcore/health` (Standard **8501**; im HA-Add-on intern **8502**). Läuft der Optimierer-Dienst (`main.py`), muss zusätzlich die Datei `runtime/daemon_heartbeat.json` frisch sein, sonst meldet der Container `unhealthy`.

Status abfragen (Compose/Synology): `docker inspect --format='{{.State.Health.Status}}' <container>`.

## Persistente Daten

Diese Verzeichnisse liegen **außerhalb des Images** und überleben Image-Updates:


| Mount (Host)                          | Inhalt                                                                                                                  |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `./earnie_env/config/config.json`                | System-Einstellungen (Smarthome-Backend, Oberfläche, Live-Szenario); wird nie überschrieben |
| `./earnie_env/config/tariffs.json`               | Mitgelieferter Tarif-Katalog (Bezug/Einspeise); Sidecar neben `config.json`; nicht von Hand ändern                      |
| `./earnie_env/config/user_tariffs.json`          | Eigene Tarife (Benutzertarife) aus der Seite **Tarife**                                                                 |
| `./earnie_env/config/grid_fees.json`             | Netzentgelt-Katalog (Netzbereiche / Zeitregeln); Sidecar; Bootstrap aus `share/config/`                                 |
| `./earnie_env/config/backtesting_scenarios.json` | Szenarien inkl. Live-Baseline                                                                                           |
| `./earnie_env/config/house_profiles.json`        | Hausprofile (Sidecar)                                                                                                   |
| `./earnie_env/config/components.json`            | Gerätekomponenten (`inverters[]`, `batteries[]`, `pv_systems[]` und `wallboxes[]` inkl. `ehal_bindings`; `heating_systems[]`) |
| `./earnie_env/config/deviation_rules.json`       | Soll/Ist-Regeln für Chart-Marker (Bootstrap legt an)                                                                    |
| `./earnie_env/config/config.example.json`        | Nur zum Nachschlagen; fehlt sie, kopiert der Entrypoint die Vorlage aus dem Image (`share/config/`). Nach Updates wird sie nicht aufgefrischt |
| `./earnie_env/runtime/`                          | `cons_data.csv`, Zustands-JSONs, Profile, Logs                                                                   |
| `./earnie_env/runtime/local_settings.json`       | Lokale Einstellungen (z. B. Silent-Mode)                                                                                |
| `./earnie_env/config/.env`                       | Loxone-Zugangsdaten (`LOXONE_*`); optional `EARNIE_LAN_SUBNET` |


Umgebungsvariable in Compose: `EARNIE_ENV_PATH=.`. Daraus leitet Earnie `/app/config` und `/app/runtime` ab; die Host-Mounts lauten `./…/config` → `/app/config` und `./…/runtime` → `/app/runtime`.

## Netzwerk: Docker-Bridge, Heimnetz und Miniserver-Rückkanal

Earnie läuft in Compose **ohne** `network_mode: host`. Die Container-IP liegt typischerweise in `172.16.0.0/12` (Docker-Bridge). Das hat zwei Folgen:

- **mDNS/SSDP** (Suche nach Home Assistant / Loxone) erreicht das Heimnetz oft nicht.
- Ein aktiver Portscan ohne Angabe würde fälschlich das **Docker-Netz** durchsuchen.

**Heimnetz für die erweiterte Suche:** `EARNIE_LAN_SUBNET` als `/24`-CIDR setzen, z. B. `192.168.178.0/24`. Dafür gibt es zwei Wege:

- in `earnie_env/config/.env` bzw. in der Compose-`.env`,
- auf der Seite **Smarthome-Backend**, wenn Earnie nach dem LAN fragt.

LoxBerry setzt `EARNIE_LAN_SUBNET` bei Installation und Upgrade aus der Host-IP. Im HA-Add-on ermittelt Earnie die LAN-IP des Hosts über die Supervisor-API (`/network/info`).

**Home Assistant als Backend (nicht Add-on):** Bleibt die Suche leer, auf **Smarthome-Backend** direkt **Home Assistant** wählen, statt auf mDNS zu warten.

**Miniserver → Earnie (Port 8541):** Der Miniserver muss den Earnie-Host unter einer stabilen Adresse erreichen (Virtual Inputs / Outputs → Host:8541). Dazu:

- VM bzw. Container im **Bridged**-LAN betreiben (nicht NAT).
- Dem Earnie-Host eine **feste IP** oder **DHCP-Reservierung** geben, damit die Adresse in der Loxone Config gültig bleibt.

Auf **Smarthome-Backend** und **EHAL-Com** zeigt Earnie „Letzter Aufruf vom Miniserver: vor X min von IP Y“. Damit lässt sich der Rückkanal ohne zusätzliche Werkzeuge prüfen.

## Erstinstallation (NAS)

1. Projektordner mit `docker/compose/synology_productive.yml` anlegen (auf der NAS oft als `compose.yaml` kopiert).
2. Verzeichnisse anlegen: `mkdir -p earnie_env/config earnie_env/runtime`.
3. Container starten. Der **Entrypoint** legt fehlende Dateien an: `.env`, `config.json`, `tariffs.json`, weitere Sidecars, bei Bedarf Vorlagen aus `share/config/` sowie leere Runtime-Dateien.
4. Zugangsdaten in `earnie_env/config/.env` eintragen (Loxone-Zugang). Haus, Szenarien und Tarife in der Oberfläche einrichten: **Hauskonfigurator**, **Szenarienkonfigurator** und **Tarife**. Eigene Tarife speichert Earnie in `user_tariffs.json`; den mitgelieferten Katalog `tariffs.json` nicht von Hand ändern.
5. Optional: historische `cons_data` aus Dev nach `earnie_env/runtime/cons_data.csv` kopieren.



## Config-Updates nach Programm-Upgrade

Neue Einträge in `share/config/config.example.json` (Image-Vorlage) übernimmt Earnie in der Regel **nicht** automatisch in die Anwender-Config. Stattdessen weist Earnie auf fehlende Einträge hin:

- **Beim Start von `main.py`:** Hinweis im Log.
- **In der Streamlit-App:** gelbes Banner mit den fehlenden Pfaden und Beispielwerten.

Die fehlenden Keys manuell in `earnie_env/config/config.json` ergänzen.

Earnie vergleicht immer mit der Vorlage im Image, nicht mit der Kopie `earnie_env/config/config.example.json`. Diese Kopie kann nach einem Update veraltet sein, etwa wenn eine Migration einen Key entfernt hat. Sie löst dann keinen Hinweis aus.

> **Ausnahme `scenario_explorer_conf`:** Fehlende Keys unter `scenario_explorer_conf` ergänzt die Config-Migration (Migrations-Assistent oder `python -m scripts.migrate_config`) mit den Standardwerten aus `config.example.json`. Bereits vorhandene Keys bleiben unverändert. Alle anderen fehlenden Keys bleiben wie oben beschrieben Handarbeit.

Der Drift-Hinweis ist vom Migrations-Assistenten für das Datenmodell (Pack-JSON-Form) zu unterscheiden. Zeigt Earnie nach einem Image-Update diesen Assistenten, beschreibt [Betrieb → Update und Migration](betrieb.md#update-und-migration) das Vorgehen, auch für die CLI. Backups liegen dann unter `earnie_env/config/backups/pre-migration-…/`.



## Bootstrap manuell

```powershell
python -m scripts.bootstrap_runtime
```

Der Befehl legt nur fehlende Dateien an; bestehende bleiben unverändert.

## Images und Updates

Das Image `ghcr.io/jochentcc/earnie-energy` gibt es für `linux/amd64` (Synology, Proxmox, PC) und `linux/arm64` (LoxBerry). Die Tags:

| Tag | Inhalt |
| --- | --- |
| `:latest` | letzte offizielle Version; Standard in den Compose-Dateien `*_productive.yml` |
| `:next` | neueste Vorabversion (Beta / Release-Kandidat) oder, wenn es keine neuere gibt, die letzte offizielle Version |
| `:<version>` | genau diese Version, z. B. zum Festhalten einer Version |

Zum Testen einer Vorabversion in der Compose-Datei (`*_productive.yml`) `image:` von `:latest` auf `:next` oder auf den Versions-Tag `:<version>` stellen und den Container neu erstellen. Zurück zur offiziellen Version geht es mit `:latest`; hat die Vorabversion die Konfiguration migriert, vorher das Backup zurückkopieren (siehe [Update und Migration](betrieb.md#update-und-migration)).

### Aktualisieren (Synology)

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

Beim Start von `main.py` (auch nach Auto-Start aus der UI) laufen automatisch die Tarif-Plausibilitätsprüfung und, sofern die Loxone-Zugangsdaten gesetzt sind, `verify_loxone_setup`. Das Ergebnis steht in `runtime/earnie.log` (`Tarif-Startup-Prüfung`, `[loxone-verify]`).

Optional:


| Variable                          | Wirkung                                                |
| --------------------------------- | ------------------------------------------------------ |
| `EARNIE_VERIFY_LOXONE_ON_START=0` | Prüfung aus                                            |
| `EARNIE_SKIP_LOXONE_VERIFY=1`     | Prüfung aus                                            |
| `EARNIE_STRICT_LOXONE_VERIFY=1`   | Der Optimierer-Dienst bricht ab, wenn eine Prüfung fehlschlägt (die Oberfläche läuft weiter) |


Manuell (z. B. nach einer Config-Änderung ohne Neustart):

```powershell
python -m scripts.verify_loxone_setup
```

`docker/compose/synology_productive.yml` referenziert `ghcr.io/jochentcc/earnie-energy:latest`.

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
4. Zugangsdaten in `earnie_env/config/.env` eintragen (Loxone-Zugang). Haus, Szenarien und Tarife in der Oberfläche einrichten: **Hauskonfigurator**, **Szenarienkonfigurator** und **Tarife**. Eigene Tarife speichert Earnie in `user_tariffs.json`; den mitgelieferten Katalog `tariffs.json` nicht von Hand ändern.
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
