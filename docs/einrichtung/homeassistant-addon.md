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
5. **Start**. Web-UI über die **HA-Seitenleiste** (Ingress) oder **OPEN WEB UI** auf der App-Seite — **ohne** Host-Port `:8501` und ohne manuelles Nachschlagen der VM-/Host-IP.
   Optional (Fortgeschritten): direkter LAN-Zugriff `http://<home-assistant-ip>:8501`.
   **Nach dem Start ca. 20–40 Sekunden warten**, bis die Oberfläche erreichbar ist — Bootstrap der `earnie_env`-Dateien, dann Streamlit hinter nginx. Öffnest du Ingress **sofort**, sind typisch:
   - Hinweis-Seite **„Earnie startet noch“** (nginx, aktualisiert sich selbst), oder
   - HA-Meldung **„Bad Gateway / 502“**, falls der Proxy noch gar nicht antwortet.
   Beides ist beim Kaltstart normal — kurz warten und neu laden / OPEN WEB UI erneut.
6. Danach Haus-/Entity-Konfiguration in der Earnie-Oberfläche (Smarthome-Backend, Hauskonfigurator) bzw. optional dateibasiert unter dem Add-on-Datenpfad. Beim ersten Start legt der Entrypoint fehlende Dateien an und setzt im Add-on-Kontext `ehal.backend=ha`.

## Konfiguration

Add-on-Optionen (`config.yaml` → `options`) sind ein optionales Zusatzangebot, keine Pflicht. Wer nichts einträgt, konfiguriert Earnie weiterhin dateibasiert (`config.json`, Sidecars) — genau wie bei den anderen Deployments.

| Add-on-Option | Wirkung | Pflicht |
|---|---|---|
| `streamlit_port` (Default `8501`) | `EARNIE_UI_STREAMLIT_PORT` und Merge nach `config.json` `ui.streamlit_port` | nein |
| `ehal_loxone_http_port` (Default `8541`) | `EARNIE_EHAL_LOXONE_HTTP_PORT` und Merge nach `config.json` `system.ehal_loxone_http_port` | nein |
| `ui_modes` (Default `sunset2sunset,scenario_explorer,live_environment`) | `EARNIE_UI_MODES` | nein |
| `auto_start_main` (Default `true`) | `EARNIE_AUTO_START_MAIN` | nein |
| `timezone` (Default `Europe/Vienna`) | `TZ` | nein |

Loxone- und HA-Zugangsdaten gehören **nicht** in die Supervisor-Optionen — sie werden in der Earnie-Oberfläche unter **Smarthome-Backend** bzw. in `config/.env` gepflegt (im Add-on oft leer → Supervisor-Proxy).

### Options → `config.json` (Add-on 0.2)

- **Frische Installation:** fehlende `config.json` wird aus der Minimal-Vorlage angelegt und im Add-on-Kontext auf `ehal.backend=ha` / `adapter_id=earnie-hems` gesetzt (URL/Token leer → Supervisor-Proxy zur Laufzeit).
- **Jeder Start:** `streamlit_port` und `ehal_loxone_http_port` aus `/data/options.json` werden in die genannten `config.json`-Keys geschrieben. Bestehende Backend-Wahl (z. B. bewusst Loxone) wird nicht überschrieben.

### Home-Assistant-Anbindung im Add-on

Das Manifest setzt `homeassistant_api: true`. Damit injiziert der Supervisor `SUPERVISOR_TOKEN` und erlaubt den Zugriff auf die Core-API unter `http://supervisor/core`. Die Smarthome-Backend-Suche findet diesen lokalen Core ohne mDNS; für `ehal.backend=ha` reicht die URL `http://supervisor/core` ohne manuelles Long-Lived Access Token (leerer Token → Laufzeit nutzt `SUPERVISOR_TOKEN`).

### Ingress (Add-on 0.2)

`ingress: true` / `ingress_port: 8501` — die UI ist in die HA-Oberfläche eingebettet. Im Add-on sitzt **nginx** auf Port `8501` und reicht an Streamlit auf internem Port `8502` weiter; dabei wird der von HA abgeschnittene Ingress-Pfad (`ingress_entry`) wieder vorangestellt und Streamlit mit `server.baseUrlPath` gestartet. Ohne diesen Proxy liefert Streamlit unter Ingress und unter `http://<host>:8501/` nur „Not found“.

Direkter LAN-Zugriff nutzt denselben nginx-Port `8501`.

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
| Ingress | Primäre Earnie Web-UI in der HA-Seitenleiste / OPEN WEB UI |
| `8501/tcp` | Optionaler Direktzugriff (Streamlit) |
| `8541/tcp` | EHAL Loxone-HTTP (Request-Optimize, `/alive`, Pattern-B-Status) — nur bei `ehal.backend=loxone` relevant |

Port-Gesamtübersicht: [`docs/referenz/streamlit-ports.md`](../referenz/streamlit-ports.md).

## Add-on-Update vs. Image-Update

Die Add-on-`version:` in `config.yaml` **entspricht der Earnie-App-Version** (z. B. `2.6.0` oder `2.6.0-alpha.1`). Bei jedem Earnie-Release-Tag wird das Add-on-Repository [`ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie) automatisch aktualisiert — der Supervisor zeigt dann **Update verfügbar**, sobald die neue `version:` im Repository ankommt.

Unterschied zum LoxBerry-Plugin: dort zieht die Compose-Datei `:latest`; beim HA-Add-on wird das Release-Image explizit über `build.yaml` / `EARNIE_VERSION` gepinnt.

## Einschränkungen (Feature-Stufe 0.2)

Die Add-on-`version:` folgt der Earnie-App (z. B. `2.6.0-alpha.1`). „0.2“ meint hier den ausgelieferten Options-/Ingress-Umfang, nicht die SemVer-Nummer.

- Add-on-Optionen decken nur die gängigsten Werte ab; volle Haus-/Entity-Konfiguration bleibt in-App bzw. dateibasiert.
- Kein MQTT Discovery, keine nativen HA-Entitäten, keine Energy-Dashboard-Integration (Add-on **1.0** → Earnie-Backlog **Version 2.+1**, nicht Teil von 2.6).

## Testumgebung

Für Entwickler: siehe [`homeassistant-addon-testumgebung.md`](homeassistant-addon-testumgebung.md) für den Aufbau einer Testumgebung mit echtem Supervisor (M3-Persistenz-Nachweis).

### Dogfood-Checkliste (Ingress / Options 0.2)

Auf der HAOS-in-VM-Instanz (Synology):

1. Add-on ab **`2.5.3`** (oder neuer) mit Ingress starten — Earnie in der Seitenleiste bzw. OPEN WEB UI **ohne** `:8501` / IP-Lookup. Sofort nach Start: Hinweis-Seite „Earnie startet noch“ oder kurz 502 → nach ~30 s UI OK.
2. Charts/Navigation laden (kein „Not found“, kein leeres Blatt, keine Massen-404 unter `/static` oder `_stcore`).
3. Optional: Direkt `http://<ha-ip>:8501` (nginx) öffnet dieselbe UI.
4. Frische Daten: Smarthome-Backend zielt auf HA; Supervisor-Proxy-Auth funktioniert.
5. Neustart: `/data/earnie_env` und gemergte/seeded `config.json` bleiben erhalten.

Hinweis: `2.5.3-alpha.4` setzte nur Streamlit-`baseUrlPath` ohne nginx-Pfad-Reinject → Ingress und Host`:8501` meldeten „Not found“.

## Deinstallation

Add-on in **Einstellungen → Apps → Earnie** stoppen und deinstallieren. Das Add-on-Datenverzeichnis (`/data/earnie_env/…`) wird dabei vom Supervisor entfernt — vorher sichern, falls Config/Runtime weiter gebraucht werden.
