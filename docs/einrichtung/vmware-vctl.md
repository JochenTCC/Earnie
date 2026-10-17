# Earnie unter VMware Workstation (`vctl`)

Earnie läuft auf einem **Windows-PC** mit **VMware Workstation Pro** (oder Player for Windows) über die mitgelieferte Container-CLI **`vctl`**. Docker Desktop und eine eigene Linux-VM sind dafür nicht nötig.

Image und Persistenz sind dieselben wie bei Synology und Proxmox: `ghcr.io/jochentcc/earnie-energy:latest`, die Ordner `earnie_env/config/` und `earnie_env/runtime/`, UI-Port **8501**.

**Hilfsskript:** [`scripts/run_earnie_vctl.ps1`](../../scripts/run_earnie_vctl.ps1)  
**Ports:** [streamlit-ports.md](../referenz/streamlit-ports.md)  
**Allgemeiner Container-Betrieb:** [container.md](container.md)  
**Hintergrund (VMware):** [vctl-Dokumentation (Broadcom)](https://techdocs.broadcom.com/us/en/vmware-cis/desktop-hypervisors/workstation-pro/17-0/using-vmware-workstation-pro/using-vctl-command-to-manage-containers-and-run-kubernetes-cluster/using-the-vctl-utility.html)

## Wann dieser Weg?

| Passend | Weniger passend |
|---------|-----------------|
| Windows-PC mit VMware Workstation, kein Docker Desktop gewünscht | Dauerbetrieb rund um die Uhr wie auf NAS oder Proxmox (besser: Compose auf Linux oder NAS) |
| Live oder Was-wäre-wenn auf dem Desktop-PC | Automatischer Start mit Windows ohne Zusatzaufwand |
| Schneller Zugriff auf das veröffentlichte GHCR-Image | Erwartung von `docker compose up` (`vctl` hat **kein** Compose) |
| `vctl system start` lädt `crx.vmdk` erfolgreich | DNS-Auflösung oder Download von `download3.vmware.com` schlägt fehl (häufig seit der Broadcom-Migration) |

`vctl` startet jeden Container in einer leichten **CRX-VM**. Dafür braucht es die Datei **`crx.vmdk`**, die beim ersten `vctl system start` bzw. `vctl kind` heruntergeladen wird. Der Runtime-Dienst startet nicht automatisch mit Workstation. Nach jedem Neustart des PCs daher einmal `vctl system start` ausführen (bzw. das Skript mit `-Action start`).

> **Hinweis:** Schlägt der Download von `crx.vmdk` fehl, liegt ein Problem bei VMware bzw. Broadcom vor, kein Earnie-Fehler. Siehe [Troubleshooting](#troubleshooting-crxvmdk).

## Voraussetzungen

| Kriterium | Geeignet | Nicht geeignet |
|-----------|----------|----------------|
| Windows | 10 1809+ / 11 | ältere Windows-Versionen ohne `vctl` |
| VMware | Workstation Pro oder Player for Windows **mit** `vctl` | reines ESXi bzw. nur klassische VMs ohne `vctl` |
| Architektur Image | `linux/amd64` (wie Synology) | Host nur mit ARM |
| Disk | SSD empfohlen | sehr langsame HDD als Systemplatte |
| Netz | PC erreicht Loxone bzw. HA im LAN | Port 8501 ungeschützt im Internet |

## 1. Runtime starten

In PowerShell:

```powershell
vctl system info
vctl system start
vctl system info
```

Erwartete Ausgabe: **Container runtime is running**.

`vctl.exe` liegt üblicherweise unter:

`C:\Program Files (x86)\VMware\VMware Workstation\bin\vctl.exe`

## 2. Persistente Ordner

Das Hilfsskript verwendet standardmäßig den Pfad `%USERPROFILE%\Earnie\earnie_env\…`.

```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\Earnie\earnie_env\config"
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\Earnie\earnie_env\runtime"
```

`vctl`-Volumes akzeptieren nur **absolute Ordnerpfade**. Relative Pfade, einzelne Dateien und Docker-Named-Volumes funktionieren nicht.

## 3. Mit Hilfsskript (empfohlen)

Aus dem Repo-Root aufrufen (oder den Skript-Pfad anpassen):

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
.\scripts\run_earnie_vctl.ps1 -Action up -Image ghcr.io/jochentcc/earnie-energy:2.6.2
```

Bei einem Authentifizierungsfehler beim Pull zuerst anmelden:

```powershell
.\scripts\run_earnie_vctl.ps1 -Action login
# GitHub-Benutzer + PAT mit read:packages
```

Der Kommentarblock im Skript beschreibt die weiteren Parameter `-DataRoot`, `-ContainerName`, `-UiPort` und `-DaemonPort`.

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
2. Auf dem Windows-Host diese Dateien anpassen:
   - `earnie_env\config\.env`: Zugang zum Backend (z. B. Loxone).
   - `earnie_env\config\config.json` und `tariffs.json`: Haus und Tarife.
3. Container neu starten:

```powershell
.\scripts\run_earnie_vctl.ps1 -Action restart
```

Fehlende Dateien legt der Entrypoint des Images an, bestehende Dateien bleiben unverändert. Details: [container.md](container.md).

Die Log-Datei liegt unter `%USERPROFILE%\Earnie\earnie_env\runtime\earnie.log`.

```powershell
.\scripts\run_earnie_vctl.ps1 -Action logs-hint
```

## 6. Update

```powershell
.\scripts\run_earnie_vctl.ps1 -Action update
```

Das Skript startet die Runtime, lädt das Image neu, entfernt den Container und legt ihn mit denselben Volume-Mounts wieder an. Die persistenten Daten unter `earnie_env\` bleiben erhalten.

Für Vorabversionen (Community) den Image-Tag fest angeben, z. B. `ghcr.io/jochentcc/earnie-energy:X.Y.Z-alpha.N`. Der Tag `:latest` zeigt weiterhin auf die letzte offizielle Version.

## Einschränkungen

- **Kein Docker Compose:** Start, Stopp und Update laufen über `vctl` bzw. das Hilfsskript.
- **Kein Auto-Start mit Windows:** Nach einem Neustart Runtime und Container von Hand starten. Ein Eintrag im Taskplaner lässt sich optional selbst einrichten.
- **LAN und Loxone:** Die Ports liegen auf dem Windows-Host. Die Erreichbarkeit des Miniservers zuerst vom PC aus prüfen. Der Miniserver muss Earnie auf Port **8541** erreichen. Dafür braucht die VM ein **Bridged**-Netz (kein NAT) und der Earnie-Host eine **feste IP** bzw. DHCP-Reservierung (siehe [container.md](container.md#netzwerk-docker-bridge-heimnetz-und-miniserver-rückkanal)). Bei Problemen ist eine Linux-VM mit Bridged-Netz und Compose die Alternative ([proxmox-lxc.md](proxmox-lxc.md) als Muster).
- **Compose-Entsprechung für den Produktivbetrieb:** [`docker/compose/proxmox_productive.yml`](../../docker/compose/proxmox_productive.yml) bzw. [`synology_productive.yml`](../../docker/compose/synology_productive.yml).

## Troubleshooting: `crx.vmdk`

### Symptome

```text
Error downloading from https://download3.vmware.com/software/fusion/file/crx.vmdk:
  dial tcp: lookup download3.vmware.com: no such host
…
ERROR failed to create container: require file crx.vmdk, check if it has been downloaded correctly
```

Danach meldet `-Action start` oft, dass der Container nicht existiert. Der Grund: `-Action up` konnte den Container nie anlegen.

### Ursache

`vctl` muss die CRX-Festplatte `crx.vmdk` von Broadcom bzw. VMware herunterladen. Der Hostname **`download3.vmware.com`** lässt sich bei vielen Installationen nicht mehr auflösen. Das Problem ist in der Community bekannt und betraf auch aktuelle Versionen von Workstation 17.6.x. Earnie und GHCR sind daran nicht beteiligt.

Nach einem erfolgreichen Download liegt die Datei hier:

`%USERPROFILE%\.vctl\bin\crx.vmdk`

### Prüfungen

```powershell
Resolve-DnsName download3.vmware.com
Test-Path "$env:USERPROFILE\.vctl\bin\crx.vmdk"
Get-Item "$env:USERPROFILE\.vctl\bin\crx.vmdk" -ErrorAction SilentlyContinue |
  Select-Object FullName, Length, LastWriteTime
vctl system start
```

### Lösungsversuche für `vctl`

1. **Workstation aktualisieren:** auf die neueste verfügbare Version (Broadcom Support bzw. Portal).
2. **Anderes DNS oder Netz probieren:** z. B. einen anderen Resolver verwenden, VPN abschalten, den Firmen-Proxy prüfen. Danach erneut `vctl system start` ausführen.
3. **Datei von einem funktionierenden PC übernehmen:** Hat ein anderer Rechner mit derselben Workstation-Hauptversion bereits `%USERPROFILE%\.vctl\bin\crx.vmdk`, den Ordner `.vctl\bin\` mit `crx.vmdk` (und ggf. mitgelieferten Tools) auf den Ziel-PC kopieren. Danach `vctl system start` und erneut `.\scripts\run_earnie_vctl.ps1 -Action up` ausführen.
4. **Broadcom Community bzw. Support fragen:** Suchbegriff `vctl crx.vmdk download3.vmware.com`.

Einen offiziellen Earnie-Workaround, der `crx.vmdk` selbst bereitstellt, gibt es nicht. Lizenz und Verteilung dieser VMware-Datei lassen das nicht zu.

### Empfohlener Ausweichweg (Earnie trotzdem betreiben)

Beide Wege nutzen dasselbe Image, ohne `vctl`.

**Option A: Docker Desktop auf dem Windows-PC**

```powershell
mkdir earnie_env\config, earnie_env\runtime
docker compose --project-directory . -f docker/compose/synology_productive.yml pull
docker compose --project-directory . -f docker/compose/synology_productive.yml up -d
```

UI: `http://localhost:8501`. Details: [container.md](container.md).

**Option B: kleine Linux-VM in VMware** mit Bridged-Netz, Docker Engine und Compose. Das Vorgehen folgt [proxmox-lxc.md](proxmox-lxc.md), nur als vollständige VM statt LXC.

Bei Option A lassen sich bestehende Daten aus `%USERPROFILE%\Earnie\earnie_env\` nach `.\earnie_env\` im Compose-Projektordner kopieren. Die Unterordner `config/` und `runtime/` bleiben gleich.
