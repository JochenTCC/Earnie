# Home-Assistant-Add-on

Earnie kann auch als **Home Assistant Supervisor Add-on** installiert werden, primär für **Home Assistant Green** (HA OS, `aarch64`). Wie beim LoxBerry-Plugin ist das ein **schlanker Docker-Wrapper**: der Add-on-Installer startet dasselbe, produktiv genutzte Image wie die manuelle Compose-Installation (`ghcr.io/jochentcc/earnie-energy`).

Quellbaum im Repo: [`packaging/homeassistant-addon/earnie/`](../../packaging/homeassistant-addon/earnie/). Veröffentlicht wird das Add-on über ein eigenes Custom-Repository, `https://github.com/JochenTCC/ha-addon-earnie` (nicht die offizielle HA-Community-Add-on-Liste).

**Abgrenzung zum EHAL-HA-Adapter:** Der bestehende EHAL-HA-Adapter (`ehal.backend=ha`, siehe [Loxone-Anbindung](loxone-anbindung.md)) lässt Earnie **außerhalb** von Home Assistant laufen und spricht die HA-REST-API als Southbound-Ziel an. Dieses Add-on ist das Gegenteil: Earnie läuft **innerhalb** von Home Assistant. Beide schließen sich nicht aus.

## Voraussetzungen (Go/No-Go)

| Kriterium | Go | No-Go |
|---|---|---|
| Home Assistant | HA OS / Supervised, **Supervisor** aktiv | Home Assistant Container/Core ohne Supervisor (dort funktionieren Add-ons grundsätzlich nicht) |
| Architektur | **aarch64** (z. B. Home Assistant Green) oder `amd64` (Dev/Test-VM) | 32-bit ARM (`armv7`) |
| RAM | mind. **4 GB** empfohlen | unter 2 GB |
| Speicher | SSD/eMMC bevorzugt | nur sehr langsame SD-Karte |

## Installation

1. **Einstellungen → Add-ons → Add-on Store** → ⋮ (oben rechts) → **Repositories**.
2. URL hinzufügen: `https://github.com/JochenTCC/ha-addon-earnie`.
3. In der Add-on-Liste **Earnie** öffnen → **Installieren**.
4. Optional: Add-on-Optionen ausfüllen (siehe unten) — alle Felder sind optional.
5. **Start**. Web-UI über den Button **OPEN WEB UI** auf der Add-on-Seite, oder direkt `http://<home-assistant-ip>:8501`.
6. Danach wie üblich `config.json` (und ggf. Sidecars/`.env`) unter dem Add-on-Datenpfad anpassen — der Entrypoint legt fehlende Dateien beim ersten Start automatisch an.

## Konfiguration

Add-on-Optionen (`config.yaml` → `options`) sind ein optionales Zusatzangebot, keine Pflicht. Wer nichts einträgt, konfiguriert Earnie weiterhin dateibasiert (`config.json`, Sidecars) — genau wie bei den anderen Deployments.

| Add-on-Option | Env-Variable im Container | Pflicht |
|---|---|---|
| `loxone_user` | `LOXONE_USER` | nein (nur bei `ehal.backend=loxone`) |
| `loxone_pass` | `LOXONE_PASS` | nein |
| `loxone_ip` | `LOXONE_IP` | nein |
| `streamlit_port` (Default `8501`) | `EARNIE_UI_STREAMLIT_PORT` | nein |
| `ehal_loxone_http_port` (Default `8541`) | aktuell kein Env-Override — wirkt nur über `config.json` `system.ehal_loxone_http_port` | nein |
| `ui_modes` (Default `sunset2sunset,scenario_explorer,live_environment`) | `EARNIE_UI_MODES` | nein |
| `auto_start_main` (Default `true`) | `EARNIE_AUTO_START_MAIN` | nein |
| `timezone` (Default `Europe/Vienna`) | `TZ` | nein |

Loxone-Zugangsdaten, die in den Add-on-Optionen gesetzt sind, überschreiben eine vorhandene `earnie_env/config/.env` (Env gewinnt, wie in den anderen Deployments auch).

## Datenpfade

Der Supervisor gibt jedem Add-on ein eigenes Volume unter `/data`, das Add-on-Updates und -Neustarts übersteht (Standard-Add-on-Konvention — **nicht** `/config`, das ist das HA-Core-Konfigurationsverzeichnis):

| Container-Pfad | Bedeutung |
|---|---|
| `/data/earnie_env/config/` | `config.json`, Sidecars, `.env`, `uploads/` |
| `/data/earnie_env/runtime/` | Laufzeitdaten, Historie, Logs |

Erreichbar z. B. über das **Samba** oder **SSH & Web Terminal** Add-on (Pfad unter `addon_configs/<slug>` bzw. `addons/data/<slug>`, je nach HA-OS-Version).

## Ports

| Port | Zweck |
|---|---|
| `8501/tcp` | Earnie Web-UI (Streamlit) |
| `8541/tcp` | EHAL Loxone-HTTP (Request-Optimize, `/alive`, Pattern-B-Status) — nur bei `ehal.backend=loxone` relevant |

Port-Gesamtübersicht: [`docs/referenz/streamlit-ports.md`](../referenz/streamlit-ports.md).

## Add-on-Update vs. Image-Update

Analog zum LoxBerry-Plugin ist die Add-on-`version:` in `config.yaml` **unabhängig** von der Earnie-App-Version (`version.py`). Ein neuer Earnie-Release erfordert einen `config.yaml`-Version-Bump plus `EARNIE_VERSION`-Bump im Add-on-Repo, damit der Supervisor ein Update anzeigt — kein automatisches `:latest`-Pull wie beim LoxBerry-Plugin.

## Einschränkungen (Version 0.1)

- Keine Ingress-Einbindung — die UI läuft auf einem eigenen Port, nicht eingebettet in die HA-Seitenleiste.
- Add-on-Optionen decken nur die gängigsten Werte ab; volle Konfiguration bleibt dateibasiert.
- Kein MQTT Discovery, keine nativen HA-Entitäten, keine Energy-Dashboard-Integration (geplant für Version 1.0).

## Testumgebung für M3 (Persistenz-Nachweis)

M3 aus dem Entwicklungsplan („Add-on-Neustart, Add-on-Update und Supervisor-Backup/Restore erhalten `config.json`, Sidecars und `runtime/`") braucht einen **echten Supervisor** (HA OS/Supervised) — reine `docker run`-Tests (auch mit `/data`-Bind-Mount wie hier im Repo vorexerziert) decken nur den Neustart-Teil ab, nicht Supervisor-Update/Backup/Restore. Wer keine Home Assistant Green oder anderes Supervisor-fähiges Gerät hat, kann das lokal in einer VM nachbilden:

### VM aufsetzen (Hyper-V, Windows)

Passt vor allem, wenn ohnehin schon WSL2/Docker Desktop läuft — der Windows-Hypervisor ist dann bereits aktiv, kein zusätzliches Drittanbieter-Tool nötig (Alternative: VirtualBox 7.x).

1. **Hyper-V aktivieren** (PowerShell als Admin, danach Neustart):
   ```powershell
   Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
   ```
2. HA-OS-Image laden: [github.com/home-assistant/operating-system/releases](https://github.com/home-assistant/operating-system/releases) → `haos_ova-<version>.vhdx.zip` (Hyper-V, **amd64** — deckt sich mit `arch: [aarch64, amd64]` im Add-on-Manifest). Entpacken.
3. Hyper-V-Manager → **Neu → Virtueller Computer** → **Generation 2**, mind. **4096 MB RAM** (kein dynamischer Speicher), **4 vCPUs**, vorhandene `.vhdx` als Festplatte.
4. **Netzwerkadapter**: externer **Bridged**-vSwitch (nicht NAT/intern) — sonst sind Ports 8501/8541 vom Host bzw. LAN-Geräte (Loxone) nicht erreichbar.
5. VM-Einstellungen → **Sicherheit**: **Secure Boot deaktivieren**, Vorlage **Microsoft UEFI Certificate Authority** — HA OS bootet sonst nicht unter Generation 2.
6. VM starten, nach 1–2 Minuten unter `http://homeassistant.local:8123` den Setup-Wizard durchlaufen.
7. **Direkt danach einen Hyper-V-Snapshot anlegen** („Clean-Onboarding") — Ausgangspunkt für wiederholbare Update-/Backup-Restore-Tests, ohne jedes Mal neu zu installieren.

### Earnie-Add-on installieren

Wie unter [Installation](#installation) oben, mit dem veröffentlichten Repo `https://github.com/JochenTCC/ha-addon-earnie`.

### Prüfschritte

| Prüfung | Ablauf |
|---|---|
| **a) Neustart-Persistenz** | Werte in der Earnie-UI ändern/speichern → Add-on **Neu starten** (oder VM neu booten) → `config.json`/Runtime unverändert? |
| **b) Add-on-Update-Persistenz** | Im `ha-addon-earnie`-Repo `earnie/config.yaml` `version:` (und ggf. `earnie/build.yaml` `EARNIE_VERSION`) bumpen, pushen → in HA Add-on Store neu laden → **Update** → Konfiguration aus (a) noch da? |
| **c) Supervisor-Backup/Restore** | **Einstellungen → System → Backups** → Backup mit Add-on „Earnie" erstellen → Config ändern → Backup **wiederherstellen** → Earnie-Config wieder auf Backup-Stand, Add-on läuft normal weiter? |

Nach (b)/(c) jeweils zum Snapshot aus Schritt 7 zurück, um wieder von einem sauberen Stand zu testen.

## Deinstallation

Add-on in **Einstellungen → Add-ons → Earnie** stoppen und deinstallieren. Das Add-on-Datenverzeichnis (`/data/earnie_env/…`) wird dabei vom Supervisor entfernt — vorher sichern, falls Config/Runtime weiter gebraucht werden.
