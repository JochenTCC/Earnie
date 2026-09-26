# Earnie unter VMware Workstation (`vctl`)

Earnie auf einem **Windows-PC** mit **VMware Workstation Pro** (oder Player for Windows) über die mitgelieferte Container-CLI **`vctl`** — ohne Docker Desktop und ohne eigene Linux-VM.

Gleiches Image und gleiche Persistenz wie Synology/Proxmox: `ghcr.io/jochentcc/earnie-energy:latest`, Ordner `earnie_env/config/` und `earnie_env/runtime/`, UI-Port **8501**.

**Hilfsskript:** [`scripts/run_earnie_vctl.ps1`](../../scripts/run_earnie_vctl.ps1)  
**Ports:** [streamlit-ports.md](../referenz/streamlit-ports.md)  
**Allgemeiner Container-Betrieb:** [container.md](container.md)  
**Hintergrund (VMware):** [vctl-Dokumentation (Broadcom)](https://techdocs.broadcom.com/us/en/vmware-cis/desktop-hypervisors/workstation-pro/17-0/using-vmware-workstation-pro/using-vctl-command-to-manage-containers-and-run-kubernetes-cluster/using-the-vctl-utility.html)

## Wann dieser Weg?

| Passend | Weniger passend |
|---------|-----------------|
| Windows-PC mit VMware Workstation, kein Docker Desktop gewünscht | Dauerbetrieb 24/7 wie NAS/Proxmox (besser: Compose auf Linux/NAS) |
| Live oder Was-wäre-wenn auf dem Desktop-PC | Automatischer Start mit Windows ohne Extra-Arbeit |
| Schneller Zugriff auf das veröffentlichte GHCR-Image | Erwartung von `docker compose up` (vctl hat **kein** Compose) |
| `vctl system start` lädt `crx.vmdk` erfolgreich | DNS/Download von `download3.vmware.com` schlägt fehl (häufig seit Broadcom-Migration) |

`vctl` startet jeden Container in einer leichten **CRX-VM** und braucht dafür die Datei **`crx.vmdk`** (Download beim ersten `vctl system start` / `vctl kind`). Der Runtime-Dienst startet **nicht** automatisch mit Workstation — nach jedem Reboot einmal `vctl system start` (bzw. Skript `-Action start`).

**Wichtig:** Wenn der Download von `crx.vmdk` fehlschlägt, ist das ein **VMware-/Broadcom-Problem**, kein Earnie-Fehler. Siehe [Troubleshooting](#troubleshooting-crxvmdk).

## Voraussetzungen

| Kriterium | Go | No-Go |
|-----------|----|-------|
| Windows | 10 1809+ / 11 | ältere Windows-Versionen ohne `vctl` |
| VMware | Workstation Pro oder Player for Windows **mit** `vctl` | reines ESXi / nur klassische VMs ohne `vctl` |
| Architektur Image | `linux/amd64` (wie Synology) | ARM-only-Host |
| Disk | SSD empfohlen | sehr langsame HDD als Systemplatte |
| Netz | PC erreicht Loxone/HA im LAN | Port 8501 ungeschützt ins Internet |

## 1. Runtime starten

PowerShell:

```powershell
vctl system info
vctl system start
vctl system info
```

Erwartung: **Container runtime is running**.

`vctl.exe` liegt typisch unter:

`C:\Program Files (x86)\VMware\VMware Workstation\bin\vctl.exe`

## 2. Persistente Ordner

Standardpfad des Hilfsskripts: `%USERPROFILE%\Earnie\earnie_env\…`

```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\Earnie\earnie_env\config"
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\Earnie\earnie_env\runtime"
```

`vctl`-Volumes: nur **absolute Ordnerpfade** (keine relativen Pfade, keine einzelnen Dateien, keine Docker-Named-Volumes).

## 3. Mit Hilfsskript (empfohlen)

Vom Repo-Root (oder Skript-Pfad anpassen):

```powershell
# Erststart: Runtime + Image-Pull + Container anlegen
.\scripts\run_earnie_vctl.ps1 -Action up

# Status
.\scripts\run_earnie_vctl.ps1 -Action status

# Nach Reboot (Runtime + vorhandener Container)
.\scripts\run_earnie_vctl.ps1 -Action start

# Stoppen
.\scripts\run_earnie_vctl.ps1 -Action stop

# Image aktualisieren und Container neu anlegen (Daten bleiben)
.\scripts\run_earnie_vctl.ps1 -Action update

# Ohne Loxone-Smoke-Test (z. B. nur Was-wäre-wenn)
.\scripts\run_earnie_vctl.ps1 -Action up -SkipLoxoneVerify

# Bestimmte Version
.\scripts\run_earnie_vctl.ps1 -Action up -Image ghcr.io/jochentcc/earnie-energy:2.5.2
```

Bei Auth-Fehler beim Pull:

```powershell
.\scripts\run_earnie_vctl.ps1 -Action login
# GitHub-Benutzer + PAT mit read:packages
```

Weitere Parameter: `-DataRoot`, `-ContainerName`, `-UiPort`, `-DaemonPort` — siehe Kommentarblock im Skript.

## 4. Manuell mit `vctl` (ohne Skript)

```powershell
vctl system start
vctl pull ghcr.io/jochentcc/earnie-energy:latest

$cfg = "$env:USERPROFILE\Earnie\earnie_env\config"
$run = "$env:USERPROFILE\Earnie\earnie_env\runtime"

vctl run --name earnie-productive -d `
  --publish 8501:8501 `
  --publish 8541:8541 `
  --volume "${cfg}:/app/config" `
  --volume "${run}:/app/runtime" `
  -e TZ=Europe/Vienna `
  -e EARNIE_ENV_PATH=. `
  -e EARNIE_STRICT_TARIFF_VALIDATE=1 `
  -e EARNIE_VERIFY_LOXONE_ON_START=1 `
  -e EARNIE_AUTO_START_MAIN=1 `
  -e EARNIE_UI_MODES=sunset2sunset,live_environment `
  ghcr.io/jochentcc/earnie-energy:latest `
  python -m scripts.run_streamlit -- --server.enableCORS false --server.enableXsrfProtection false
```

## 5. Konfiguration nach dem ersten Start

1. UI öffnen: `http://localhost:8501`
2. Auf dem Windows-Host anpassen:
   - `earnie_env\config\.env` — Backend-Zugang (z. B. Loxone)
   - `earnie_env\config\config.json`, `tariffs.json` — Haus und Tarife
3. Container neu starten:

```powershell
.\scripts\run_earnie_vctl.ps1 -Action restart
```

Fehlende Dateien legt der Image-Entrypoint an; bestehende werden nicht überschrieben. Details: [container.md](container.md).

Log-Datei: `%USERPROFILE%\Earnie\earnie_env\runtime\earnie.log`

```powershell
.\scripts\run_earnie_vctl.ps1 -Action logs-hint
```

## 6. Update

```powershell
.\scripts\run_earnie_vctl.ps1 -Action update
```

Entspricht: Runtime starten → Image pullen → Container entfernen → mit gleichen Volume-Mounts neu anlegen. Persistente Daten unter `earnie_env\` bleiben erhalten.

Vorabversionen (Community): Image-Tag pinnen, z. B. `ghcr.io/jochentcc/earnie-energy:2.5.3-alpha.2` — **nicht** `:latest` (bleibt auf der letzten offiziellen Version).

## Einschränkungen

- **Kein Docker Compose** — Start/Stop/Update über `vctl` bzw. das Hilfsskript.
- **Kein Auto-Start** mit Windows — nach Reboot Runtime + Container starten (Taskplaner optional selbst einrichten).
- **LAN / Loxone** — Ports liegen auf dem Windows-Host; Erreichbarkeit des Miniservers zuerst vom PC aus prüfen. Der Miniserver muss Earnie auf Port **8541** erreichen können — dafür braucht die VM **Bridged**-Netz (nicht NAT) und eine **feste IP** bzw. DHCP-Reservierung für den Earnie-Host (siehe [container.md](container.md) § Netzwerk). Bei Problemen alternativ Linux-VM mit bridged Netz + Compose ([proxmox-lxc.md](proxmox-lxc.md) als Muster).
- Compose-Äquivalent Prod: [`docker/compose/proxmox_productive.yml`](../../docker/compose/proxmox_productive.yml) / [`synology_productive.yml`](../../docker/compose/synology_productive.yml).

## Troubleshooting: `crx.vmdk`

### Symptome

```text
Error downloading from https://download3.vmware.com/software/fusion/file/crx.vmdk:
  dial tcp: lookup download3.vmware.com: no such host
…
ERROR failed to create container: require file crx.vmdk, check if it has been downloaded correctly
```

Danach meldet `-Action start` oft: Container existiert nicht — weil `-Action up` den Container nie anlegen konnte.

### Ursache

`vctl` muss die CRX-Festplatte `crx.vmdk` von Broadcom/VMware herunterladen. Der Hostname **`download3.vmware.com`** löst bei vielen Installationen **nicht mehr auf** (bekanntes Community-Thema; betraf auch aktuelle Workstation 17.6.x). Earnie und GHCR sind dabei nicht beteiligt.

Erwarteter Speicherort nach erfolgreichem Download:

`%USERPROFILE%\.vctl\bin\crx.vmdk`

### Prüfungen

```powershell
Resolve-DnsName download3.vmware.com
Test-Path "$env:USERPROFILE\.vctl\bin\crx.vmdk"
Get-Item "$env:USERPROFILE\.vctl\bin\crx.vmdk" -ErrorAction SilentlyContinue |
  Select-Object FullName, Length, LastWriteTime
vctl system start
```

### Was versuchen (vctl retten)

1. **Workstation aktualisieren** auf die neueste verfügbare Version (Broadcom Support/Portal).
2. **Anderes DNS / Netz** — z. B. anderer Resolver, VPN aus, Firmen-Proxy prüfen; danach erneut `vctl system start`.
3. **Datei von einem funktionierenden PC übernehmen** — wenn ein anderer Rechner bereits `%USERPROFILE%\.vctl\bin\crx.vmdk` hat (gleiche Workstation-Major-Version): Ordner `.vctl\bin\` mit `crx.vmdk` (und ggf. mitgelieferten Tools) auf den Ziel-PC kopieren, dann `vctl system start` und erneut `.\scripts\run_earnie_vctl.ps1 -Action up`.
4. **Broadcom Community / Support** — Stichwort `vctl crx.vmdk download3.vmware.com`.

Es gibt **keinen** offiziellen Earnie-Workaround, der `crx.vmdk` selbst bereitstellt (Lizenz/Distribution der VMware-Datei).

### Empfohlener Ausweichweg (Earnie trotzdem betreiben)

Gleiches Image, ohne `vctl`:

**Option A — Docker Desktop auf dem Windows-PC**

```powershell
mkdir earnie_env\config, earnie_env\runtime
docker compose --project-directory . -f docker/compose/synology_productive.yml pull
docker compose --project-directory . -f docker/compose/synology_productive.yml up -d
```

UI: `http://localhost:8501` — Details: [container.md](container.md).

**Option B — kleine Linux-VM in VMware** (bridged Netz) mit Docker Engine + Compose — Muster wie [proxmox-lxc.md](proxmox-lxc.md), nur als volle VM statt LXC.

Bestehende Daten unter `%USERPROFILE%\Earnie\earnie_env\` können bei Option A nach `.\earnie_env\` im Compose-Projektordner kopiert werden (gleiche Unterordner `config/` und `runtime/`).
