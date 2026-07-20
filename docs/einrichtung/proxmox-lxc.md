# Proxmox LXC + Docker Compose

Earnie auf einem **Proxmox VE**-Host in einem **unprivileged LXC** mit Docker Compose — gleiches Image und gleiche Persistenz wie Synology/LoxBerry (`earnie_env/config/`, `earnie_env/runtime/`, UI-Port **8501**).

**Compose (Prod):** [`docker/compose/proxmox_productive.yml`](../../docker/compose/proxmox_productive.yml)  
**Compose (Alpha, Port 8511):** [`docker/compose/proxmox-alpha.yml`](../../docker/compose/proxmox-alpha.yml)  
**LXC-Hilfen:** [`docker/proxmox/`](../../docker/proxmox/)  
**Ports:** [streamlit-ports.md](../referenz/streamlit-ports.md)  
**Allgemeiner Container-Betrieb:** [container.md](container.md)

## Voraussetzungen

| Kriterium | Go | No-Go |
|-----------|----|-------|
| Proxmox | VE 7/8, amd64 | — |
| CT | Debian 12 (oder Ubuntu LTS), **unprivileged** | privileged nur wenn bewusst nötig |
| Features | `nesting=1`, `keyctl=1` | Docker ohne Nesting |
| RAM | mind. **2 GB** (4 GB empfohlen bei Backtesting) | unter 1 GB |
| Disk | mind. **8 GB** Rootfs (+ optional Bind-Mount für Daten) | sehr knappe Rootfs |
| Netz | Bridge (`vmbr0`), Port **8501** im LAN erreichbar | Port 8501 ungeschützt ins Internet |

Das Image `ghcr.io/jochentcc/earnie-energy:latest` liefert `linux/amd64` (wie Synology).

## 1. LXC anlegen (Proxmox-Host)

Beispiel mit `pct` (VMID, Storage, Template und Netz anpassen):

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

Feldliste und Kommentare: [`docker/proxmox/lxc.conf.example`](../../docker/proxmox/lxc.conf.example).

Optional Persistenz auf dem Host (Pfad zuerst anlegen):

```text
mp0: /mnt/pve/data/earnie,mp=/opt/earnie
```

Dann liegen `earnie_env/config/` und `earnie_env/runtime/` auf dem Host-Storage und überleben CT-Neuaufbau.

## 2. Bootstrap im LXC

```bash
pct enter 120
# im CT:
curl -fsSL https://raw.githubusercontent.com/JochenTCC/Earnie/main/docker/proxmox/bootstrap.sh -o /tmp/bootstrap.sh
chmod +x /tmp/bootstrap.sh
/tmp/bootstrap.sh
```

Ohne Internetzugriff auf Raw-GitHub: `docker/compose/proxmox_productive.yml` als `/opt/earnie/compose.yaml` und `bootstrap.sh` manuell kopieren (z. B. `pct push`).

Skript-Standardverzeichnis: **`/opt/earnie`**. Umgebungsvariablen:

| Variable | Bedeutung | Default |
|----------|-----------|---------|
| `EARNIE_DIR` | Installationsverzeichnis | `/opt/earnie` |
| `COMPOSE_URL` | URL der Compose-Datei | Raw `…/docker/compose/proxmox_productive.yml` |
| `IMAGE` | Image-Hinweis in der Ausgabe | `ghcr.io/jochentcc/earnie-energy:latest` |

Falls `docker info` fehlschlägt: Features prüfen, CT neu starten (`pct reboot <VMID>`).

Privates GHCR-Image: vor `pull` im CT `echo "$TOKEN" | docker login ghcr.io -u USER --password-stdin`.

## 3. Konfiguration

Wie bei Synology/LoxBerry:

1. `earnie_env/config/.env` — Loxone-Zugang  
2. `earnie_env/config/config.json`, `earnie_env/config/tariffs.json` — Haus und Tarife  
3. Container neu starten nach Config-Änderungen:

```bash
cd /opt/earnie
docker compose --project-directory . -f compose.yaml restart earnie
```

Bootstrap und Entrypoint legen fehlende Dateien an; bestehende werden nicht überschrieben. Details: [container.md](container.md).

## 4. Deploy / Update

```bash
cd /opt/earnie
docker compose --project-directory . -f compose.yaml pull
docker compose --project-directory . -f compose.yaml up -d
```

UI: `http://<lxc-ip>:8501`  
Log: `earnie_env/runtime/earnie.log` bzw. `docker compose … logs -f earnie`

## UI-Zugriff

Im Hausnetz Port **8501**. Extern nur über Reverse Proxy, VPN o. Ä. — nicht ungeschützt freigeben (wie LoxBerry).

## Go/No-Go

| Kriterium | Go | No-Go |
|-----------|----|-------|
| Nesting | `nesting=1` + `keyctl=1` | Docker startet nicht / keine Nested Container |
| Architektur | amd64 CT | arm64-CT ohne passendes Image-Manifest |
| Persistenz | `earnie_env/config/` + `earnie_env/runtime/` außerhalb des Images | nur flüchtige Rootfs ohne Backup |
| MILP | CBC-Läufe im Log ok | dauerhafte Timeouts bei zu wenig RAM/CPU |

## Siehe auch

- [Container](container.md) — Image-Build, Bootstrap, Config-Drift  
- [Betrieb](betrieb.md) — Worker vs. Streamlit  
- [Streamlit-Ports](../referenz/streamlit-ports.md)
