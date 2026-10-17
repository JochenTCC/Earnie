# Proxmox LXC + Docker Compose

Diese Anleitung beschreibt den Betrieb von Earnie auf einem **Proxmox VE**-Host in einem **unprivileged LXC** mit Docker Compose. Image und Persistenz sind dieselben wie bei Synology und LoxBerry (`earnie_env/config/`, `earnie_env/runtime/`, UI-Port **8501**).

**Compose (Produktivbetrieb):** [`docker/compose/proxmox_productive.yml`](../../docker/compose/proxmox_productive.yml)  
**Compose (Alpha, Port 8511):** [`docker/compose/proxmox-alpha.yml`](../../docker/compose/proxmox-alpha.yml)  
**LXC-Hilfen:** [`docker/proxmox/`](../../docker/proxmox/)  
**Ports:** [streamlit-ports.md](../dev/streamlit-ports.md)  
**Allgemeiner Container-Betrieb:** [container.md](container.md)

## Voraussetzungen

| Kriterium | Geeignet | Nicht geeignet |
|-----------|----------|----------------|
| Proxmox | VE 7/8, amd64 | – |
| CT | Debian 12 (oder Ubuntu LTS), **unprivileged** | privileged, außer wenn bewusst nötig |
| Features | `nesting=1`, `keyctl=1` | Docker ohne Nesting |
| RAM | mind. **2 GB** (4 GB empfohlen für Backtesting) | unter 1 GB |
| Disk | mind. **8 GB** Rootfs (optional zusätzlich ein Bind-Mount für Daten) | sehr knappe Rootfs |
| Netz | Bridge (`vmbr0`), Port **8501** im LAN erreichbar; für den Miniserver-Rückkanal Port **8541** und eine feste IP bzw. DHCP-Reservierung (kein NAT), siehe [container.md](container.md) § Netzwerk | Port 8501 ungeschützt im Internet |

Das Image `ghcr.io/jochentcc/earnie-energy:latest` liefert `linux/amd64` (wie bei Synology).

## 1. LXC anlegen (Proxmox-Host)

Beispiel mit `pct` (VMID, Storage, Template und Netz an die eigene Umgebung anpassen):

```bash
pct create 120 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname earnie --cores 2 --memory 2048 --swap 512 \
  --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --features nesting=1,keyctl=1 \
  --unprivileged 1 --onboot 1 \
  --ostype debian \
  --tags earnie
pct start 120
```

Alle Felder mit Kommentaren stehen in [`docker/proxmox/lxc.conf.example`](../../docker/proxmox/lxc.conf.example).

Optional lassen sich die Daten auf dem Host ablegen. Den Host-Pfad vorher anlegen:

```text
mp0: /mnt/pve/data/earnie,mp=/opt/earnie
```

Damit liegen `earnie_env/config/` und `earnie_env/runtime/` auf dem Host-Storage und bleiben bei einem Neuaufbau des CT erhalten.

## 2. Bootstrap im LXC

```bash
pct enter 120
# im CT:
curl -fsSL https://raw.githubusercontent.com/JochenTCC/Earnie/main/docker/proxmox/bootstrap.sh -o /tmp/bootstrap.sh
chmod +x /tmp/bootstrap.sh
/tmp/bootstrap.sh
```

Ohne Zugriff auf Raw-GitHub die Dateien manuell kopieren (z. B. mit `pct push`): `docker/compose/proxmox_productive.yml` als `/opt/earnie/compose.yaml` sowie `bootstrap.sh`.

Das Skript installiert standardmäßig nach **`/opt/earnie`**. Folgende Umgebungsvariablen passen das Verhalten an:

| Variable | Bedeutung | Standard |
|----------|-----------|----------|
| `EARNIE_DIR` | Installationsverzeichnis | `/opt/earnie` |
| `COMPOSE_URL` | URL der Compose-Datei | Raw `…/docker/compose/proxmox_productive.yml` |
| `IMAGE` | Image-Hinweis in der Ausgabe | `ghcr.io/jochentcc/earnie-energy:latest` |

Falls `docker info` fehlschlägt: die Features des CT prüfen und den CT neu starten (`pct reboot <VMID>`).

Für ein privates GHCR-Image vor dem `pull` im CT anmelden: `echo "$TOKEN" | docker login ghcr.io -u USER --password-stdin`.

## 3. Konfiguration

Die Konfiguration funktioniert wie bei Synology und LoxBerry:

1. **Loxone-Zugang:** in `earnie_env/config/.env` eintragen.
2. **Haus und Tarife:** in `earnie_env/config/config.json` und `earnie_env/config/tariffs.json` pflegen.
3. **Neustart:** nach Änderungen an der Konfiguration den Container neu starten:

```bash
cd /opt/earnie
docker compose --project-directory . -f compose.yaml restart earnie-productive
```

Bootstrap und Entrypoint legen fehlende Dateien an, bestehende Dateien bleiben unverändert. Details stehen in [container.md](container.md).

<a id="4-deploy--update"></a>

## 4. Starten und aktualisieren

```bash
cd /opt/earnie
docker compose --project-directory . -f compose.yaml pull
docker compose --project-directory . -f compose.yaml up -d
```

- **Oberfläche:** `http://<lxc-ip>:8501`
- **Log:** `earnie_env/runtime/earnie.log` oder `docker compose … logs -f earnie-productive`

## UI-Zugriff

Im Hausnetz ist die Oberfläche über Port **8501** erreichbar. Von außen nur über Reverse Proxy, VPN o. Ä. zugreifen und den Port nicht ungeschützt freigeben (wie bei LoxBerry).

<a id="gono-go"></a>

## Betriebs-Check (Go/No-Go)

| Kriterium | Go | No-Go |
|-----------|----|-------|
| Nesting | `nesting=1` und `keyctl=1` gesetzt | Docker startet nicht bzw. keine Nested Container möglich |
| Architektur | amd64-CT | arm64-CT ohne passendes Image-Manifest |
| Persistenz | `earnie_env/config/` und `earnie_env/runtime/` liegen außerhalb des Images | nur flüchtige Rootfs ohne Backup |
| Optimierung (MILP) | HiGHS-Läufe im Log ohne Auffälligkeiten (Ausweichlösung CBC per Umgebungsvariable) | dauerhafte Timeouts wegen zu wenig RAM oder CPU |

## Siehe auch

- [Container](container.md): Image-Build, Bootstrap, Config-Drift
- [Betrieb](betrieb.md): Worker und Streamlit-Oberfläche
- [Streamlit-Ports](../dev/streamlit-ports.md)
