# Testumgebung

Nachweis für M3 aus dem Entwicklungsplan („Add-on-Neustart, Add-on-Update und Supervisor-Backup/Restore erhalten `config.json`, Sidecars und `runtime/`"). Richtet sich an Entwickler, nicht an Anwender des Earnie-Add-ons — siehe dazu [`homeassistant-addon.md`](homeassistant-addon.md).

M3 braucht einen **echten Supervisor** (HA OS/Supervised) — reine `docker run`-Tests (auch mit `/data`-Bind-Mount, siehe [„Local build/test“ in der Packaging-README](../../packaging/homeassistant-addon/README.md#local-buildtest)) decken nur den Neustart-Teil ab, nicht Supervisor-Update/Backup/Restore. Zwei Wege, das ohne Home Assistant Green nachzubilden:

- **Option A — HA Supervised in WSL2:** rein softwarebasiert, läuft auf jedem Windows-PC ohne Hyper-V/KVM, aber `amd64` statt `aarch64` (Go/No-Go-Tabelle in [`homeassistant-addon.md`](homeassistant-addon.md#voraussetzungen-gono-go)).
- **Option B — echtes HA OS auf Raspberry Pi 4:** kein Emulations-Sonderfall, `aarch64` wie in Produktion (Home Assistant Green) — braucht aber die Hardware.

Für den reinen Persistenz-Nachweis (M3) ist Option A ausreichend; Option B ist der genauere Vorproduktions-Test, falls ein Pi 4 verfügbar ist.

## Option A: HA Supervised in WSL2 (ohne Hyper-V, ohne KVM)

Läuft komplett innerhalb von WSL2 — dafür genügt die auf Windows Home verfügbare **Virtual Machine Platform**, die Docker Desktop ohnehin schon nutzt. Kein `Microsoft-Hyper-V`-Feature, kein `/dev/kvm` nötig. Docker läuft hier als natives **Docker-CE** *innerhalb* der Debian-Distribution — nicht Docker Desktop, das bleibt für Earnie & Co. unangetastet.

1. Debian-Distribution installieren (PowerShell, nicht als Admin nötig):
   ```powershell
   wsl --install -d Debian
   ```
2. In der Debian-Shell `systemd` aktivieren (Pflicht — der Supervised-Installer bricht sonst mit „System has not been booted with systemd as init system" ab):
   ```bash
   sudo tee /etc/wsl.conf <<'EOF'
   [boot]
   systemd=true
   EOF
   ```
   Danach in PowerShell: `wsl --shutdown`, dann die Debian-Distribution neu öffnen.
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
5. OS-Agent installieren (Version/Architektur beim Download prüfen — `amd64` für WSL2 auf einem x86-PC): aktuelles `.deb` von [github.com/home-assistant/os-agent/releases](https://github.com/home-assistant/os-agent/releases) laden, dann `dpkg -i os-agent_*_linux_x86_64.deb`.
6. Home Assistant Supervised installieren:
   ```bash
   curl -L -o homeassistant-supervised.deb \
     https://github.com/home-assistant/supervised-installer/releases/latest/download/homeassistant-supervised.deb
   apt install -y ./homeassistant-supervised.deb
   ```
7. Nach ein paar Minuten Setup-Wizard unter `http://localhost:8123` — WSL2 leitet den Port automatisch auf den Windows-Host durch (`localhostForwarding`), kein manuelles Port-Mapping nötig.
8. **„Clean-Onboarding"-Sicherung** (Ersatz für den Hyper-V-Snapshot) — direkt nach dem Setup-Wizard, aus PowerShell:
   ```powershell
   wsl --shutdown
   wsl --export Debian ha-clean.tar
   ```
   Zum Zurücksetzen auf den sauberen Stand: bestehende Distribution entfernen (`wsl --unregister Debian`) und neu importieren (`wsl --import Debian <Zielordner> ha-clean.tar`).
9. **Loxone/LAN-Erreichbarkeit:** WSL2 hängt standardmäßig hinter NAT — für Zugriffe von echten LAN-Geräten (Loxone) auf Ports 8501/8541 braucht es zusätzlich `netsh interface portproxy`-Regeln auf dem Windows-Host oder den WSL2-Mirrored-Networking-Modus (`networkingMode=mirrored` in `%UserProfile%\.wslconfig`, ab Windows 11 22H2). Für den reinen M3-Persistenznachweis nicht nötig.

## Option B: Sauberes HA-OS-Image für Raspberry Pi 4 (SD-Karte)

Kommt der Produktionsumgebung am nächsten, weil es die **echte** aarch64-Zielarchitektur ist (siehe Go/No-Go-Tabelle in [`homeassistant-addon.md`](homeassistant-addon.md#voraussetzungen-gono-go)) — kein Emulations- oder WSL2-Sonderfall, echter Supervisor auf echter Hardware.

**Voraussetzungen:**

- Raspberry Pi 4 (empfohlen 4 GB RAM).
- microSD-Karte, **mind. 32 GB**, nach Möglichkeit Application-Class **A2** (eine langsame Karte ist ein No-Go).
- Ethernet-Kabel für den ersten Boot — deutlich zuverlässiger als WLAN-Onboarding beim Ersteinrichten.

**Image erstellen und flashen:**

1. [Raspberry Pi Imager](https://www.raspberrypi.com/software/) installieren — lädt das aktuelle HA-OS-Image direkt und flasht in einem Schritt, kein manuelles Versions-Tracking nötig.
2. Imager öffnen → **Choose Device** → *Raspberry Pi 4* → **Choose OS** → *Other specific-purpose OS* → *Home automation* → *Home Assistant* → **Home Assistant OS (RPi 4/400 – 64-bit)**.
   - Alternative, falls der Imager auf diesem Rechner nicht unterstützt wird: aktuelles `haos_rpi4-64-<version>.img.xz` manuell von [github.com/home-assistant/operating-system/releases](https://github.com/home-assistant/operating-system/releases) laden und mit [Balena Etcher](https://etcher.balena.io/) flashen (oder im Imager über *Use custom*).
3. **Choose Storage** → die microSD-Karte auswählen. Achtung: Der komplette Karteninhalt wird überschrieben.
4. Flash-Vorgang starten und abwarten.
5. SD-Karte in den Pi, Ethernet-Kabel und Strom anschließen. Nach ca. 1–2 Minuten ist der Setup-Wizard unter `http://homeassistant.local:8123` erreichbar (unter älteren Windows-Versionen oder restriktiven Netzwerken ggf. stattdessen über die IP-Adresse des Pi).

**„Clean-Onboarding"-Sicherung** (Ersatz für den Hyper-V-Snapshot): Direkt nach Abschluss des Setup-Wizards, **vor** den App-Tests, die SD-Karte am PC 1:1 klonen (z. B. mit dem Raspberry Pi Imager selbst über *Choose OS → Use custom* auf ein neues Image, oder mit `Win32DiskImager`/`dd`). Für die Tests (b) und (c) unten danach einfach den geklonten Kartenstand zurückspielen, statt HA OS jedes Mal neu aufzusetzen.

## Earnie-App installieren

Wie unter [Installation](homeassistant-addon.md#installation) beschrieben, mit dem veröffentlichten Repo `https://github.com/JochenTCC/ha-addon-earnie` — unabhängig davon, ob Option A (WSL2) oder Option B (Raspberry Pi 4) als Supervisor-Host dient.

## Prüfschritte

| Prüfung | Ablauf |
|---|---|
| **a) Neustart-Persistenz** | Werte in der Earnie-UI ändern/speichern → App **Neu starten** (oder Host neu starten: `wsl --shutdown` bei Option A, Strom aus/ein bei Option B) → `config.json`/Runtime unverändert? |
| **b) App-Update-Persistenz** | Im `ha-addon-earnie`-Repo `earnie/config.yaml` `version:` (und ggf. `earnie/build.yaml` `EARNIE_VERSION`) bumpen, pushen → in HA unter **Einstellungen → Apps** neu laden → **Update** → Konfiguration aus (a) noch da? |
| **c) Supervisor-Backup/Restore** | **Einstellungen → System → Backups** → Backup mit App „Earnie" erstellen → Config ändern → Backup **wiederherstellen** → Earnie-Config wieder auf Backup-Stand, App läuft normal weiter? |

Nach (b)/(c) jeweils zum sauberen Ausgangsstand zurück — beim `ha-clean.tar`-Export (Option A) bzw. der geklonten SD-Karte (Option B) —, um wieder von einem sauberen Stand zu testen.
