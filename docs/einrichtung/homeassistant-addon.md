# Home-Assistant-Add-on

Earnie lässt sich auch als **Home Assistant Supervisor Add-on** installieren, vorrangig auf **Home Assistant Green** (HA OS, `aarch64`). Wie das LoxBerry-Plugin ist das Add-on ein **schlanker Docker-Wrapper**. Der Add-on-Installer startet ein schlankes Add-on-Image (`ghcr.io/jochentcc/earnie-addon-{arch}`), das auf demselben produktiv genutzten Image wie die manuelle Compose-Installation (`ghcr.io/jochentcc/earnie-energy`) aufbaut.

Quellbaum im Repo: [`packaging/homeassistant-addon/earnie/`](../../packaging/homeassistant-addon/earnie/). Veröffentlicht wird das Add-on über ein eigenes Custom-Repository (`https://github.com/JochenTCC/ha-addon-earnie`), also nicht über die offizielle Liste der HA-Community-Add-ons.

**Abgrenzung zum EHAL-HA-Adapter:** Mit dem bestehenden EHAL-HA-Adapter (`ehal.backend=ha`, siehe [Home Assistant + evcc](ha-evcc.md)) läuft Earnie **außerhalb** von Home Assistant und spricht die HA-REST-API als Southbound-Ziel an. Beim Add-on läuft Earnie dagegen **innerhalb** von Home Assistant. Beide Wege schließen sich nicht aus.

**Begriff „Add-on“ und „App“:** Seit Home Assistant 2026.2 heißt der Menüpunkt in der Oberfläche **„Apps“** statt „Add-ons“. Das betrifft nur die Beschriftung; Repository-Format, `config.yaml` und Supervisor-API heißen technisch weiterhin „Add-on“. Diese Doku bleibt beim Begriff „Add-on“ für das Earnie-Paket. In der HA-Oberfläche steht es unter **Einstellungen → Apps**.

## Voraussetzungen (Go/No-Go)

| Kriterium | Go | No-Go |
|---|---|---|
| Home Assistant | HA OS / Supervised, **Supervisor** aktiv | Home Assistant Container/Core ohne Supervisor (dort funktionieren Add-ons grundsätzlich nicht) |
| Architektur | **aarch64** (z. B. Home Assistant Green) oder `amd64` (Dev/Test-VM) | 32-bit ARM (`armv7`) |
| CPU (nur `amd64`) | Befehlssatz **x86-64-v2** (SSE4.2, POPCNT; jede x86-CPU ab ca. 2009) | VM mit CPU-Typ `kvm64`/`qemu64` oder sehr alte CPU/Atom |
| RAM | mind. **4 GB** empfohlen | unter 2 GB |
| Speicher | SSD/eMMC bevorzugt | nur sehr langsame SD-Karte |

**x86-64-v2 in VMs:** NumPy und pyarrow (von Earnie genutzte Bibliotheken) laufen auf x86 nur mit x86-64-v2. Ältere Proxmox-VMs stehen oft noch auf dem CPU-Typ `kvm64`, der diese Befehle nicht weitergibt – selbst wenn die echte CPU sie beherrscht. Das Add-on prüft das beim Start und bricht dann mit der Meldung `earnie: FEHLER - die CPU unterstützt den Befehlssatz x86-64-v2 nicht` ab. Abhilfe in Proxmox:

1. HA-VM herunterfahren (**Shutdown**).
2. VM → **Hardware** → **Prozessoren** → **Bearbeiten**.
3. **Typ** `host` wählen (alternativ `x86-64-v2-AES`) → **OK**.
4. VM wieder starten. Ein Neustart aus Home Assistant heraus reicht nicht; die VM muss aus- und wieder eingeschaltet werden.

Die CPU lässt sich z. B. im Add-on **Terminal & SSH** prüfen: `grep -o -w -E 'sse4_2|popcnt' /proc/cpuinfo | sort -u` muss beide Begriffe ausgeben.

Zusätzlich prüft der Image-Entrypoint die Schreibrechte unter `/config` und `/data/earnie_env/runtime` sowie die Systemuhr (gegen das Build-Datum des Images). Die Health-Prüfung übernimmt der Docker-**HEALTHCHECK** des Images (`docker/healthcheck.sh`). Er prüft Streamlit auf dem internen Port 8502 und, wenn der Daemon läuft, ein frisches `runtime/daemon_heartbeat.json`.

## Installation

1. **Einstellungen → Apps** → ⋮ (oben rechts) → **Repositories** öffnen.
2. URL hinzufügen: `https://github.com/JochenTCC/ha-addon-earnie`.
3. In der App-Liste **Earnie** öffnen → **Installieren**.
4. Optional: App-Optionen ausfüllen (siehe unten). Alle Felder sind optional.
5. **Start** wählen. Die Web-UI öffnet sich über die **HA-Seitenleiste** (Ingress) oder über **OPEN WEB UI** auf der App-Seite. Ein Host-Port `:8501` oder das Nachschlagen der VM-/Host-IP ist dafür **nicht** nötig.
   Optional (Fortgeschritten): direkter LAN-Zugriff über `http://<home-assistant-ip>:8501`.
   **Nach dem Start ca. 20–40 Sekunden warten**, bis die Oberfläche erreichbar ist. In dieser Zeit legt Earnie die `earnie_env`-Dateien an und startet Streamlit hinter nginx. Wird Ingress **sofort** geöffnet, erscheint typischerweise eine der folgenden Anzeigen:
   - die Hinweis-Seite **„Earnie startet noch“** (von nginx, aktualisiert sich selbst) oder
   - die HA-Meldung **„Bad Gateway / 502“**, falls der Proxy noch gar nicht antwortet.

   Beides ist beim Kaltstart normal. Kurz warten, dann die Seite neu laden oder OPEN WEB UI erneut öffnen.
6. Danach Haus und Entities in der Earnie-Oberfläche konfigurieren (Smarthome-Backend, Hauskonfigurator) oder optional dateibasiert unter dem Datenpfad des Add-ons. Beim ersten Start legt der Entrypoint fehlende Dateien an und setzt im Add-on-Kontext `ehal.backend=ha`.

## Konfiguration

Die Add-on-Optionen (`config.yaml` → `options`) sind ein optionales Zusatzangebot. Ohne Einträge wird Earnie weiterhin dateibasiert konfiguriert (`config.json`, Sidecars), genau wie bei den anderen Installationsarten.

| Add-on-Option | Wirkung | Pflicht |
|---|---|---|
| `streamlit_port` (Default `8501`) | `EARNIE_UI_STREAMLIT_PORT` und Merge nach `config.json` `ui.streamlit_port` | nein |
| `ehal_loxone_http_port` (Default `8541`) | `EARNIE_EHAL_LOXONE_HTTP_PORT` und Merge nach `config.json` `system.ehal_loxone_http_port` | nein |
| `ui_modes` (Default `sunset2sunset,scenario_explorer,live_environment`) | `EARNIE_UI_MODES` | nein |
| `auto_start_main` (Default `true`) | `EARNIE_AUTO_START_MAIN` | nein |
| `timezone` (Default `Europe/Vienna`) | `TZ` | nein |
| `usage_ping` (optional, `true`/`false`) | Spiegelt die Zustimmung zur optionalen Nutzungsstatistik. Ohne diese Option bleibt der bestehende Zustand unverändert (siehe [Betrieb → Nutzungsstatistik](betrieb.md#nutzungsstatistik)). | nein |

Zugangsdaten für Loxone und HA gehören **nicht** in die Supervisor-Optionen. Sie werden in der Earnie-Oberfläche unter **Smarthome-Backend** oder in `config/.env` gepflegt. Im Add-on bleiben sie oft leer; dann greift der Supervisor-Proxy.

### Optionen und `config.json`

- **Frische Installation:** Eine fehlende `config.json` wird aus der Minimal-Vorlage angelegt und im Add-on-Kontext auf `ehal.backend=ha` / `adapter_id=earnie-hems` gesetzt. URL und Token bleiben leer; zur Laufzeit übernimmt der Supervisor-Proxy.
- **Jeder Start:** `streamlit_port` und `ehal_loxone_http_port` aus `/data/options.json` werden in die genannten `config.json`-Keys geschrieben. Eine bestehende Backend-Wahl (z. B. bewusst Loxone) bleibt unverändert.

### Home-Assistant-Anbindung im Add-on

Das Manifest setzt `homeassistant_api: true`. Dadurch stellt der Supervisor `SUPERVISOR_TOKEN` bereit und erlaubt den Zugriff auf die Core-API unter `http://supervisor/core`. Die Suche auf der Seite Smarthome-Backend findet diesen lokalen Core ohne mDNS. Für `ehal.backend=ha` reicht die URL `http://supervisor/core`; ein manuelles Long-Lived Access Token ist nicht nötig. Bei leerem Token nutzt Earnie zur Laufzeit `SUPERVISOR_TOKEN`.

### Ingress

Mit `ingress: true` / `ingress_port: 8501` ist die UI in die HA-Oberfläche eingebettet. Im Add-on lauscht **nginx** auf Port `8501` und leitet an Streamlit auf dem internen Port `8502` weiter. Dabei stellt nginx den Ingress-Pfad (`ingress_entry`), den HA abschneidet, wieder voran; Streamlit startet mit `server.baseUrlPath`. Ohne diesen Proxy liefert Streamlit unter Ingress und unter `http://<host>:8501/` nur „Not found“.

Der direkte LAN-Zugriff nutzt denselben nginx-Port `8501`.

## Datenpfade

Die Konfiguration liegt im Supervisor-Ordner `addon_config` (sichtbar per Samba oder File Editor). Laufzeitdaten bleiben intern unter `/data`:

| Container-Pfad | Host (typisch) | Bedeutung |
|---|---|---|
| `/config/` | `/addon_configs/<repo-hash>_earnie/` | `config.json`, Sidecars, `.env`, `uploads/` |
| `/data/earnie_env/runtime/` | Add-on-Datenvolume | Laufzeitdaten, Historie, Logs |

> **Hinweis:** Die `.env` mit Zugangsdaten liegt damit im per Samba sichtbaren Ordner. Das ist bei HA üblich (`secrets.yaml` liegt ebenso dort). Beim Wechsel auf die Vorabversion den Inhalt von `…_earnie/` nach `…_earnie_prerelease/` kopieren (siehe unten).

**Migration älterer Installationen:** Beim ersten Start einer Version mit `addon_config` kopiert `run.sh` einmalig `/data/earnie_env/config/` nach `/config/`. Den Altordner benennt es in `config.migrated-<datum>` um und bewahrt ihn eine Version lang auf.

Erreichbar sind die Ordner z. B. über das Add-on **Samba** oder **SSH & Web Terminal**.

## Ports

| Port | Zweck |
|---|---|
| Ingress | Primäre Earnie-Web-UI in der HA-Seitenleiste / OPEN WEB UI |
| `8501/tcp` | Optionaler Direktzugriff (Streamlit) |
| `8541/tcp` | EHAL Loxone-HTTP (Request-Optimize, Telemetry/Heartbeat, Pattern-B-Status). Relevant bei `ehal.backend=loxone` sowie bei Home Assistant mit `ehal.ha.transport=push`; bei `pull` nicht nötig |

Gesamtübersicht der Ports: [`docs/dev/streamlit-ports.md`](../dev/streamlit-ports.md).

## Add-on-Update vs. Image-Update

Die Add-on-`version:` in `config.yaml` **entspricht der Earnie-App-Version**. Das Repository [`ha-addon-earnie`](https://github.com/JochenTCC/ha-addon-earnie) enthält zwei Add-ons:

| Kanal | Add-on | Was landet dort |
|---|---|---|
| Stabil | **Earnie** (`earnie`) | nur offizielle Releases (`X.Y.Z`) |
| Vorab | **Earnie (Vorabversion)** (`earnie_prerelease`) | jedes Release inkl. Alpha/RC; bei offiziellen Releases dieselbe Version wie `earnie` |

Der Supervisor meldet **Update verfügbar**, sobald die neue `version:` im Repository ankommt. Die Images kommen vorgebaut von GHCR (`image:` in `config.yaml`); auf dem Gerät wird nichts gebaut.

Nach dem Update kann Earnie den **Migrations-Assistenten** zeigen (Form des Config-Packs). Der Optimierer startet erst danach. Backups liegen unter `/config/backups/pre-migration-…/` (Host: `addon_configs/…`) und sind auch in den HA-Backups des Add-ons enthalten. Details: [Betrieb → Update und Migration](betrieb.md#update-und-migration).

### Stabile Version oder Vorabversion

| | Stabil (`earnie`) | Vorab (`earnie_prerelease`) |
|---|---|---|
| Für wen | Normalbetrieb | Tester:innen / Community |
| Auto-Update | HA-Schalter „Automatische Updates“ | dasselbe |
| Feste Version | Auto-Update aus; Rückweg nur per HA-Backup | dasselbe |
| Konfiguration übernehmen | – | Inhalt von `/addon_configs/…_earnie/` nach `…_earnie_prerelease/` kopieren, dann `earnie` stoppen und Vorab starten |

**Nie beide gleichzeitig laufen lassen**, denn beide würden dieselben Geräte steuern. Beim Start prüft jedes Add-on über die Supervisor-API, ob das andere bereits läuft, und bricht in diesem Fall ab.

Unterschied zum LoxBerry-Plugin: Dort wird der Kanal in der Plugin-UI gewählt (`:latest` / `:next` / fest). Beim HA-Add-on bestimmt das installierte Add-on den Kanal.

## Einschränkungen

- Die Add-on-Optionen decken nur die gängigsten Werte ab. Die vollständige Konfiguration von Haus und Entities erfolgt weiterhin in der App oder dateibasiert.
- Es gibt kein MQTT Discovery, keine nativen HA-Entitäten und keine Integration ins Energy-Dashboard. Diese sind für Add-on **1.0** in einer späteren Version geplant und nicht Teil der aktuellen 2.7-Linie.

## Deinstallation

Das Add-on unter **Einstellungen → Apps → Earnie** stoppen und deinstallieren. Werden die Daten weiter gebraucht, vorher sichern:

- die Konfiguration unter Host-`addon_configs/<hash>_earnie/` (Container `/config/`),
- die Laufzeitdaten im Add-on-Datenvolume (`/data/earnie_env/…`).

Der Supervisor entfernt diese Pfade zusammen mit dem Add-on.
