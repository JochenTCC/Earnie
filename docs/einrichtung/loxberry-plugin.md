# LoxBerry-Plugin

Earnie kann auch als Loxberry-Plugin installiert werden. Dafür wird ein **schlanker Docker-Wrapper** als LoxBerry Plugin genutzt. Der Plugin-Installer startet denselben Container wie die manuelle Compose-Installation (`ghcr.io/jochentcc/earnie-energy`, Host-Port standardmäßig **8501**, im Container immer **8501**). Welches Image-Tag gezogen wird, steuert der **Versionskanal** in der Plugin-UI (Standard: Stabil → `:latest`).

Quellbaum im Repo: `[packaging/loxberry/](../../packaging/loxberry/)`. Packaging-Hinweise (ZIP, Version-Bump): `[packaging/loxberry/README.md](../../packaging/loxberry/README.md)`.

Manuelle Compose-Alternative (ohne Plugin): [Container — LoxBerry](container.md#loxberry-rpi-4b-arm64).

## Voraussetzungen (Go/No-Go)


| Kriterium   | Go                                                        | No-Go                                         |
| ----------- | --------------------------------------------------------- | --------------------------------------------- |
| LoxBerry    | **4.x**, 64-bit                                           | 3.x                                           |
| Docker      | Docker-Plugin installiert und aktiv (`docker compose` v2) | kein Docker / kein Socket für User `loxberry` |
| Architektur | **aarch64**                                               | 32-bit (`armv7l`)                             |
| RAM         | mind. **4 GB** empfohlen                                  | unter 2 GB                                    |
| Speicher    | **SSD** bevorzugt                                         | nur langsame SD ohne Puffer                   |


Gleiche Tabelle wie in [Container — Go/No-Go (LoxBerry)](container.md#gono-go-loxberry).

## Installation

1. Docker-Plugin im LoxBerry aktivieren und prüfen (`docker compose version`).
2. Loxberry-Plugin vom GitHub-Release laden.
3. LoxBerry → **Plugin-Verwaltung** → ZIP installieren.
4. Bei Erfolg: systemd-Unit `earnie`, Container `earnie-productive`, Volumes unter dem Plugin-Datenverzeichnis; Timer `earnie-update.timer` für optionale Image-Auto-Updates.
5. Streamlit im LAN: `http://<loxberry-ip>:8501` (oder der in der Plugin-UI gesetzte Host-Port)
6. Danach wie üblich `earnie_env/config/.env` und `config.json` anpassen (Entrypoint legt fehlende Dateien an). Miniserver-Prefill ist **nicht** Teil dieses Plugins.

Die Plugin-UI zeigt Status (laufende Earnie-Version, Kanal, Update verfügbar), Start/Stop/Neustart, Image-Pull, einen Link zur Streamlit-Oberfläche, die **Kanalwahl** und ein Feld zum Ändern des **Host-Ports** (Compose-Mapping `HOST:8501`; Container-Port bleibt 8501).

Der LoxBerry-**Healthcheck** meldet WARN (Status 4), wenn der Container läuft, Docker aber `.State.Health.Status=unhealthy` meldet (Streamlit oder Optimizer-Heartbeat). Ohne Healthcheck im Image bleibt „running“ weiterhin OK.

## Datenpfade

Persistenz (überlebt Plugin-Upgrades und Image-Pulls):


| Host (Plugin)                               | Container      |
| ------------------------------------------- | -------------- |
| `…/data/plugins/earnie/earnie_env/config/`  | `/app/config`  |
| `…/data/plugins/earnie/earnie_env/runtime/` | `/app/runtime` |


Kleine Plugin-Notizdatei: `…/config/plugins/earnie/plugin.env` (kein Geheimnis-Store; Loxone-Zugangsdaten gehören in `earnie_env/config/.env`). Enthält u. a.:


| Schlüssel                 | Bedeutung                                                                 |
| ------------------------- | ------------------------------------------------------------------------- |
| `EARNIE_CHANNEL`          | `stable` \| `prerelease` \| `pinned` (Standard nach Install/Upgrade: `stable`) |
| `EARNIE_PINNED_VERSION`   | nur bei `pinned`, z. B. `2.5.3`                                           |
| `EARNIE_AUTO_UPDATE`       | `1`/`0` — täglicher Image-Pull; nur wirksam bei `stable`/`prerelease`     |
| `STREAMLIT_PORT`          | Host-Port (Standard **8501**)                                             |


Beim Speichern in der Plugin-UI schreibt `sync_compose_env.sh` nach `…/data/plugins/earnie/docker/.env`: `STREAMLIT_PORT`, `EARNIE_IMAGE_TAG` (`latest` / `next` / SemVer), `TZ=…` aus der LoxBerry-Host-Zeitzone (`/etc/timezone`, Fallback `Europe/Vienna`) und `EARNIE_LAN_SUBNET=<Host-LAN>/24` (aus der Default-Route des Hosts, sofern noch nicht gesetzt). Override von `TZ` bzw. `EARNIE_LAN_SUBNET` manuell in dieser `.env` möglich.

## Versionskanäle (Earnie-Image)


| Kanal          | Image-Tag | Automatische Image-Updates                         |
| -------------- | --------- | -------------------------------------------------- |
| **Stabil**     | `:latest` | ja, wenn `EARNIE_AUTO_UPDATE=1` (Timer ~03:30)         |
| **Vorabversion** | `:next` | ja, wenn `EARNIE_AUTO_UPDATE=1` (Timer ~03:30)         |
| **Feste Version** | `:<SemVer>` (z. B. `:2.5.3`) | nein — Timer überspringt `pinned` |


`:next` zeigt auf das neueste Release inkl. Vorabversionen (und fällt nie hinter die letzte stabile zurück, wenn die Vorab älter ist). Die Plugin-UI listet bei „Feste Version“ die Tags aus der GitHub-Releases-API; wenn die API nicht erreichbar ist, reicht ein manuelles SemVer-Feld.

## Host-Port (Streamlit)


| Einstellung | Bedeutung                                                                      |
| ----------- | ------------------------------------------------------------------------------ |
| Standard    | Host **8501** → Container **8501**                                             |
| Ändern      | Plugin Admin → **Einstellungen** → Host-Port speichern (löst Image-Pull/Neustart aus) |
| Gültig      | 1024–65535                                                                     |
| Persistenz  | `plugin.env` (`STREAMLIT_PORT=…`); Upgrade stellt die Datei wieder her         |


Der „Earnie öffnen“-Link folgt dem konfigurierten Port. Parallelbetrieb mit manueller Compose auf demselben Host-Port vermeiden.

## Plugin-Update vs. Image-Update


| Aktion                                                             | Was sich ändert                                                                  |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| LoxBerry AutoUpdate / neues Plugin-ZIP (`plugin.cfg` `AUTOMATIC_UPDATES`) | Verwaltungsskripte, WebUI, Compose-Wrapper (`plugin.cfg` VERSION, z. B. `0.2.0`) — **nicht** das Earnie-Image |
| Kanal / `EARNIE_AUTO_UPDATE` / „Image aktualisieren“ / `earnie_ctl.sh pull` | zieht `ghcr.io/jochentcc/earnie-energy` gemäß Kanal (`:latest` / `:next` / `:Version`) und startet den Container neu |


Die Plugin-SemVer ist **unabhängig** von Earnie `version.py`. LoxBerry-`AUTOMATIC_UPDATES` und der Image-Kanal `EARNIE_AUTO_UPDATE` sind **zwei getrennte Schalter**.

## Upgrade

Bei Plugin-Upgrade stoppt der Installer die Unit kurz, erhält `plugin.env` und die Bind-Mounts unter `earnie_env/`, und startet Compose danach neu. Fehlt `EARNIE_CHANNEL`, setzt `postupgrade.sh` `stable` (und `EARNIE_AUTO_UPDATE=1` falls fehlend); eine tote `IMAGE=`-Zeile wird entfernt. Config und Runtime bleiben erhalten.

## Deinstallation

Das Uninstall-Skript:

- stoppt und entfernt die systemd-Units `earnie` und `earnie-update.timer`
- entfernt den Container `earnie-productive`
- **löscht nicht** absichtlich `earnie_env/` und entfernt **nicht** das GHCR-Image

LoxBerry kann beim Deinstallieren trotzdem das Plugin-Datenverzeichnis entfernen. Wenn Config/Runtime nach der Deinstallation noch gebraucht werden: **vorher** `earnie_env/` an einen sicheren Ort kopieren. Manuelles Löschen danach: Ordner `earnie_env` unter dem Plugin-Datenpfad entfernen.

## Parallelbetrieb mit manueller Compose

Nicht empfohlen: Plugin und manuelle Installation unter `/opt/earnie-energy/` nutzen denselben Container-Namen `earnie-productive` und standardmäßig denselben Host-Port **8501**. Entweder Plugin **oder** manuelle Compose wählen — oder im Plugin einen anderen Host-Port setzen.
