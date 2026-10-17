# Testumgebung für das Home-Assistant-Add-on

Diese Seite beschreibt den Nachweis für M3 aus dem Entwicklungsplan: „Add-on-Neustart, Add-on-Update und Supervisor-Backup/Restore erhalten `config.json`, Sidecars und `runtime/`“. Sie richtet sich an Entwickler:innen. Die Installation des Earnie-Add-ons für Anwender:innen beschreibt [`homeassistant-addon.md`](homeassistant-addon.md).

Der Nachweis braucht einen **echten Supervisor** (HA OS oder Supervised). Reine `docker run`-Tests decken nur den Neustart ab, auch mit `/data`-Bind-Mount (siehe [„Local build/test“ in der Packaging-README](../../packaging/homeassistant-addon/README.md#local-buildtest)). Supervisor-Update und Backup/Restore lassen sich damit nicht prüfen.

Ohne Home Assistant Green gibt es zwei Wege, die Umgebung nachzubilden:

- **Option A – HA Supervised in WSL2:** Rein softwarebasiert, läuft auf jedem Windows-PC ohne Hyper-V oder KVM. Die Architektur ist allerdings `amd64` statt `aarch64` (Go/No-Go-Tabelle in [`homeassistant-addon.md`](homeassistant-addon.md#voraussetzungen-gono-go)).
- **Option B – echtes HA OS auf Raspberry Pi 4:** Kein Emulations-Sonderfall, `aarch64` wie im Produktivbetrieb (Home Assistant Green). Dafür ist die Hardware nötig.

Für den reinen Persistenz-Nachweis genügt Option A. Option B ist der genauere Test vor dem Produktivbetrieb, falls ein Pi 4 verfügbar ist.

## Option A: HA Supervised in WSL2 (ohne Hyper-V, ohne KVM)

Die Umgebung läuft komplett innerhalb von WSL2. Dafür genügt die **Virtual Machine Platform**, die auch unter Windows Home verfügbar ist und die Docker Desktop ohnehin nutzt. Das Feature `Microsoft-Hyper-V` und `/dev/kvm` sind nicht nötig.

Docker läuft hier als natives **Docker-CE** *innerhalb* der Debian-Distribution. Docker Desktop bleibt davon unberührt und steht weiter für Earnie und andere Container zur Verfügung.

1. Debian-Distribution installieren (PowerShell, Admin-Rechte nicht nötig):
   ```powershell
   wsl --install -d Debian
   ```
2. In der Debian-Shell `systemd` aktivieren. Dieser Schritt ist Pflicht, sonst bricht der Supervised-Installer mit „System has not been booted with systemd as init system“ ab:
   ```bash
   sudo tee /etc/wsl.conf <<'EOF'
   [boot]
   systemd=true
   EOF
   ```
   Danach in PowerShell `wsl --shutdown` ausführen und die Debian-Distribution neu öffnen.
3. Netzwerk-Stack für den Supervisor vorbereiten (in der Debian-Shell, als root):
   ```bash
   apt update && apt install -y network-manager systemd-resolved curl udisks2
   systemctl restart systemd-resolved.service
   systemctl disable --now networking.service
   mv /etc/network/interfaces /etc/network/interfaces.disabled
   systemctl restart NetworkManager
   ```
4. Docker-CE installieren:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
5. OS-Agent installieren: das aktuelle `.deb` von [github.com/home-assistant/os-agent/releases](https://github.com/home-assistant/os-agent/releases) laden und mit `dpkg -i os-agent_*_linux_x86_64.deb` installieren. Beim Download Version und Architektur prüfen (`amd64` für WSL2 auf einem x86-PC).
6. Home Assistant Supervised installieren:
   ```bash
   curl -L -o homeassistant-supervised.deb \
     https://github.com/home-assistant/supervised-installer/releases/latest/download/homeassistant-supervised.deb
   apt install -y ./homeassistant-supervised.deb
   ```
7. Nach ein paar Minuten ist der Setup-Wizard unter `http://localhost:8123` erreichbar. WSL2 leitet den Port automatisch auf den Windows-Host weiter (`localhostForwarding`), ein manuelles Port-Mapping ist nicht nötig.
8. **„Clean-Onboarding“-Sicherung** (Ersatz für den Hyper-V-Snapshot): Direkt nach dem Setup-Wizard in PowerShell ausführen:
   ```powershell
   wsl --shutdown
   wsl --export Debian ha-clean.tar
   ```
   Zum Zurücksetzen auf den sauberen Stand die bestehende Distribution entfernen (`wsl --unregister Debian`) und neu importieren (`wsl --import Debian <Zielordner> ha-clean.tar`).
9. **Loxone/LAN-Erreichbarkeit:** WSL2 hängt standardmäßig hinter NAT. Damit echte LAN-Geräte (Loxone) die Ports 8501/8541 erreichen, braucht es eine von zwei Ergänzungen:
   - `netsh interface portproxy`-Regeln auf dem Windows-Host, oder
   - den WSL2-Mirrored-Networking-Modus (`networkingMode=mirrored` in `%UserProfile%\.wslconfig`, ab Windows 11 22H2).

   Für den reinen Persistenz-Nachweis ist das nicht nötig.

## Option B: Sauberes HA-OS-Image für Raspberry Pi 4 (SD-Karte)

Diese Variante kommt dem Produktivbetrieb am nächsten, weil sie die **echte** aarch64-Zielarchitektur nutzt (siehe Go/No-Go-Tabelle in [`homeassistant-addon.md`](homeassistant-addon.md#voraussetzungen-gono-go)). Ein echter Supervisor läuft auf echter Hardware, ohne Emulations- oder WSL2-Sonderfall.

**Voraussetzungen:**

- **Raspberry Pi 4:** empfohlen mit 4 GB RAM.
- **microSD-Karte:** mindestens 32 GB, nach Möglichkeit Application-Class **A2**. Eine langsame Karte ist ein No-Go.
- **Ethernet-Kabel für den ersten Boot:** Beim Ersteinrichten deutlich zuverlässiger als WLAN-Onboarding.

**Image erstellen und flashen:**

1. [Raspberry Pi Imager](https://www.raspberrypi.com/software/) installieren. Der Imager lädt das aktuelle HA-OS-Image direkt und flasht es in einem Schritt, ein manuelles Versions-Tracking entfällt.
2. Imager öffnen → **Choose Device** → *Raspberry Pi 4* → **Choose OS** → *Other specific-purpose OS* → *Home automation* → *Home Assistant* → **Home Assistant OS (RPi 4/400 – 64-bit)**.
   - Falls der Imager auf dem Rechner nicht unterstützt wird: das aktuelle `haos_rpi4-64-<version>.img.xz` manuell von [github.com/home-assistant/operating-system/releases](https://github.com/home-assistant/operating-system/releases) laden und mit [Balena Etcher](https://etcher.balena.io/) flashen (oder im Imager über *Use custom*).
3. **Choose Storage** → die microSD-Karte auswählen. Der komplette Karteninhalt wird dabei überschrieben.
4. Flash-Vorgang starten und abwarten.
5. SD-Karte in den Pi stecken, Ethernet-Kabel und Strom anschließen. Nach ca. 1–2 Minuten ist der Setup-Wizard unter `http://homeassistant.local:8123` erreichbar. Unter älteren Windows-Versionen oder in restriktiven Netzwerken ggf. stattdessen die IP-Adresse des Pi verwenden.

**„Clean-Onboarding“-Sicherung** (Ersatz für den Hyper-V-Snapshot): Direkt nach Abschluss des Setup-Wizards und **vor** den App-Tests die SD-Karte am PC 1:1 klonen. Das geht z. B. mit dem Raspberry Pi Imager selbst über *Choose OS → Use custom* auf ein neues Image oder mit `Win32DiskImager`/`dd`. Für die Tests (b) und (c) unten danach den geklonten Kartenstand zurückspielen, statt HA OS jedes Mal neu aufzusetzen.

## Earnie-App installieren

Die Installation läuft wie unter [Installation](homeassistant-addon.md#installation) beschrieben, mit dem veröffentlichten Repo `https://github.com/JochenTCC/ha-addon-earnie`. Das gilt für beide Supervisor-Hosts, Option A (WSL2) und Option B (Raspberry Pi 4).

## Prüfschritte

| Prüfung | Ablauf |
|---|---|
| **a) Neustart-Persistenz** | Werte in der Earnie-UI ändern und speichern → App **Neu starten** (oder Host neu starten: `wsl --shutdown` bei Option A, Strom aus/ein bei Option B) → Sind `config.json` und Runtime unverändert? |
| **b) App-Update-Persistenz** | Im `ha-addon-earnie`-Repo in `earnie/config.yaml` den Eintrag `version:` erhöhen (ggf. auch `EARNIE_VERSION` in `earnie/build.yaml`) und pushen → in HA unter **Einstellungen → Apps** neu laden → **Update** → Ist die Konfiguration aus (a) noch da? |
| **c) Supervisor-Backup/Restore** | **Einstellungen → System → Backups** → Backup mit App „Earnie“ erstellen → Konfiguration ändern → Backup **wiederherstellen** → Ist die Earnie-Konfiguration wieder auf dem Backup-Stand und läuft die App normal weiter? |

Nach (b) und (c) jeweils zum sauberen Ausgangsstand zurückkehren: über den `ha-clean.tar`-Export (Option A) bzw. die geklonte SD-Karte (Option B). So startet jeder Test wieder vom selben sauberen Stand.
