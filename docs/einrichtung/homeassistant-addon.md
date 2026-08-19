# Home-Assistant-Add-on

Earnie kann auch als **Home Assistant Supervisor Add-on** installiert werden, primär für **Home Assistant Green** (HA OS, `aarch64`). Wie beim LoxBerry-Plugin ist das ein **schlanker Docker-Wrapper**: der Add-on-Installer startet dasselbe, produktiv genutzte Image wie die manuelle Compose-Installation (`ghcr.io/jochentcc/earnie-energy`).

Quellbaum im Repo: [`packaging/homeassistant-addon/earnie/`](../../packaging/homeassistant-addon/earnie/). Veröffentlicht wird das Add-on über ein eigenes Custom-Repository, `https://github.com/JochenTCC/ha-addon-earnie` (nicht die offizielle HA-Community-Add-on-Liste).

**Abgrenzung zum EHAL-HA-Adapter:** Der bestehende EHAL-HA-Adapter (`ehal.backend=ha`, siehe [Loxone-Anbindung](loxone-anbindung.md)) lässt Earnie **außerhalb** von Home Assistant laufen und spricht die HA-REST-API als Southbound-Ziel an. Dieses Add-on ist das Gegenteil: Earnie läuft **innerhalb** von Home Assistant. Beide schließen sich nicht aus.

**Begriff „Add-on" vs. „App":** Seit Home Assistant 2026.2 heißt der Menüpunkt in der Oberfläche **„Apps"** statt „Add-ons" (nur die UI-Beschriftung — Repository-Format, `config.yaml` und Supervisor-API heißen technisch weiterhin „Add-on"). Diese Doku nutzt weiter „Add-on" für das hier beschriebene Earnie-Paket; in der HA-Oberfläche findest du es unter **Einstellungen → Apps**.

## Voraussetzungen (Go/No-Go)

| Kriterium | Go | No-Go |
|---|---|---|
| Home Assistant | HA OS / Supervised, **Supervisor** aktiv | Home Assistant Container/Core ohne Supervisor (dort funktionieren Add-ons grundsätzlich nicht) |
| Architektur | **aarch64** (z. B. Home Assistant Green) oder `amd64` (Dev/Test-VM) | 32-bit ARM (`armv7`) |
| RAM | mind. **4 GB** empfohlen | unter 2 GB |
| Speicher | SSD/eMMC bevorzugt | nur sehr langsame SD-Karte |

## Installation

1. **Einstellungen → Apps** → ⋮ (oben rechts) → **Repositories**.
2. URL hinzufügen: `https://github.com/JochenTCC/ha-addon-earnie`.
3. In der App-Liste **Earnie** öffnen → **Installieren**.
4. Optional: App-Optionen ausfüllen (siehe unten) — alle Felder sind optional.
5. **Start**. Web-UI über den Button **OPEN WEB UI** auf der App-Seite, oder direkt `http://<home-assistant-ip>:8501`.
   **Erwarte nach dem Start ca. 30 Sekunden Wartezeit**, bis die Oberfläche erreichbar ist — Streamlit muss im Container erst hochfahren (Bootstrap der `earnie_env`-Dateien, dann Streamlit-Server-Start). In dieser Zeit meldet der Browser typischerweise **„Die Website ist nicht erreichbar" / „Verbindung abgelehnt"** — das ist normal, kein Fehler. Einfach kurz warten und die Seite neu laden.
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

Die Add-on-`version:` in `config.yaml` **entspricht der Earnie-App-Version** (z. B. `2.5.0` oder `2.5.0-alpha.9`). Bei jedem Earnie-Release-Tag wird das Add-on-Repository [`ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie) automatisch aktualisiert — der Supervisor zeigt dann **Update verfügbar**, sobald die neue `version:` im Repository ankommt.

Unterschied zum LoxBerry-Plugin: dort zieht die Compose-Datei `:latest`; beim HA-Add-on wird das Release-Image explizit über `build.yaml` / `EARNIE_VERSION` gepinnt.

## Einschränkungen (Version 0.1)

- Keine Ingress-Einbindung — die UI läuft auf einem eigenen Port, nicht eingebettet in die HA-Seitenleiste.
- Add-on-Optionen decken nur die gängigsten Werte ab; volle Konfiguration bleibt dateibasiert.
- Kein MQTT Discovery, keine nativen HA-Entitäten, keine Energy-Dashboard-Integration (geplant für Version 1.0).

## Testumgebung

Für Entwickler: siehe [`homeassistant-addon-testumgebung.md`](homeassistant-addon-testumgebung.md) für den Aufbau einer Testumgebung mit echtem Supervisor (M3-Persistenz-Nachweis).

## Deinstallation

Add-on in **Einstellungen → Apps → Earnie** stoppen und deinstallieren. Das Add-on-Datenverzeichnis (`/data/earnie_env/…`) wird dabei vom Supervisor entfernt — vorher sichern, falls Config/Runtime weiter gebraucht werden.
