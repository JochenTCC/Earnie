# LoxBerry-Plugin

Earnie lässt sich auch als LoxBerry-Plugin installieren. Das Plugin ist ein **schlanker Docker-Wrapper**: Sein Installer startet denselben Container wie die manuelle Compose-Installation (`ghcr.io/jochentcc/earnie-energy`). Der Host-Port ist standardmäßig **8501**, im Container immer **8501**. Welches Image-Tag geladen wird, legt der **Versionskanal** in der Plugin-UI fest (Standard: Stabil → `:latest`).

- **Quellbaum im Repo:** [packaging/loxberry/](../../packaging/loxberry/).
- **Packaging-Hinweise (ZIP, Version-Bump):** [packaging/loxberry/README.md](../../packaging/loxberry/README.md).
- **Manuelle Compose-Alternative (ohne Plugin):** [Container – LoxBerry](container.md#loxberry-rpi-4b-arm64).

## Voraussetzungen (Go/No-Go)


| Kriterium   | Go                                                        | No-Go                                         |
| ----------- | --------------------------------------------------------- | --------------------------------------------- |
| LoxBerry    | **4.x**, 64-bit                                           | 3.x                                           |
| Docker      | Docker-Plugin installiert und aktiv (`docker compose` v2) | kein Docker / kein Socket für User `loxberry` |
| Architektur | **aarch64**                                               | 32-bit (`armv7l`)                             |
| RAM         | mind. **4 GB** empfohlen                                  | unter 2 GB                                    |
| Speicher    | **SSD** bevorzugt                                         | nur langsame SD ohne Puffer                   |
| MILP-Performance | langsamer als NAS akzeptabel, Log prüfen             | Erwartung identischer Laufzeit wie x86-NAS    |


Dieselben Kriterien wie in [Container – Go/No-Go (LoxBerry)](container.md#gono-go-loxberry). Zusätzlich gilt für das Plugin: Docker-Plugin aktiv und Docker-Socket für den User `loxberry`. Vor dem Produktivbetrieb das Daemon-Log (`runtime/earnie.log`) auf MILP-Laufzeiten und Startfehler prüfen.

## Installation

1. Docker-Plugin im LoxBerry aktivieren und prüfen (`docker compose version`).
2. LoxBerry-Plugin aus dem GitHub-Release herunterladen.
3. In LoxBerry unter **Plugin-Verwaltung** die ZIP-Datei installieren.
4. Nach erfolgreicher Installation sind eingerichtet: die systemd-Unit `earnie`, der Container `earnie-productive`, die Volumes unter dem Plugin-Datenverzeichnis und der Timer `earnie-update.timer` für optionale automatische Image-Updates.
5. Streamlit im LAN öffnen: `http://<loxberry-ip>:8501` (oder der in der Plugin-UI gesetzte Host-Port).
6. Danach wie üblich `earnie_env/config/.env` und `config.json` anpassen. Fehlende Dateien legt der Entrypoint an. Ein Miniserver-Prefill ist **nicht** Teil dieses Plugins.

Die Plugin-UI bietet:

- **Status:** laufende Earnie-Version, Kanal und ob ein Update verfügbar ist.
- **Steuerung:** Start, Stop, Neustart und Image-Pull.
- **Link** zur Streamlit-Oberfläche.
- **Kanalwahl** (siehe [Versionskanäle](#versionskanäle-earnie-image)).
- **Host-Port:** Feld zum Ändern des Compose-Mappings `HOST:8501`; der Container-Port bleibt 8501.

Der LoxBerry-**Healthcheck** meldet WARN (Status 4), wenn der Container läuft, Docker aber `.State.Health.Status=unhealthy` meldet. Ursache ist dann Streamlit oder der Heartbeat des Optimierer-Dienstes. Hat das Image keinen Healthcheck, bleibt „running“ weiterhin OK.

## Datenpfade

Diese Pfade bleiben bei Plugin-Upgrades und Image-Pulls erhalten:


| Host (Plugin)                               | Container      |
| ------------------------------------------- | -------------- |
| `…/data/plugins/earnie/earnie_env/config/`  | `/app/config`  |
| `…/data/plugins/earnie/earnie_env/runtime/` | `/app/runtime` |


Zusätzlich gibt es eine kleine Plugin-Notizdatei `…/config/plugins/earnie/plugin.env`. Diese Datei ist kein Speicher für Geheimnisse; Loxone-Zugangsdaten gehören in `earnie_env/config/.env`. Sie enthält u. a.:


| Schlüssel                 | Bedeutung                                                                 |
| ------------------------- | ------------------------------------------------------------------------- |
| `EARNIE_CHANNEL`          | `stable` \| `prerelease` \| `pinned` (Standard nach Install/Upgrade: `stable`) |
| `EARNIE_PINNED_VERSION`   | nur bei `pinned`, z. B. `2.5.3`                                           |
| `EARNIE_AUTO_UPDATE`       | `1`/`0` – täglicher Image-Pull; nur wirksam bei `stable`/`prerelease`     |
| `STREAMLIT_PORT`          | Host-Port (Standard **8501**)                                             |


Beim Speichern in der Plugin-UI schreibt `sync_compose_env.sh` folgende Werte nach `…/data/plugins/earnie/docker/.env`:

- `STREAMLIT_PORT`.
- `EARNIE_IMAGE_TAG` (`latest` / `next` / SemVer).
- `TZ=…` aus der Zeitzone des LoxBerry-Hosts (`/etc/timezone`, Fallback `Europe/Vienna`).
- `EARNIE_LAN_SUBNET=<Host-LAN>/24` aus der Default-Route des Hosts, sofern noch nicht gesetzt.

`TZ` und `EARNIE_LAN_SUBNET` lassen sich in dieser `.env` manuell überschreiben.

## Versionskanäle (Earnie-Image)


| Kanal          | Image-Tag | Automatische Image-Updates                         |
| -------------- | --------- | -------------------------------------------------- |
| **Stabil**     | `:latest` | ja, wenn `EARNIE_AUTO_UPDATE=1` (Timer ~03:30)         |
| **Vorabversion** | `:next` | ja, wenn `EARNIE_AUTO_UPDATE=1` (Timer ~03:30)         |
| **Feste Version** | `:<SemVer>` (z. B. `:2.5.3`) | nein, der Timer überspringt `pinned` |


`:next` zeigt auf das neueste Release einschließlich Vorabversionen. Ist die neueste Vorabversion älter als die letzte stabile Version, fällt `:next` nicht hinter diese zurück.

Bei „Feste Version“ listet die Plugin-UI die Tags aus der GitHub-Releases-API. Ist die API nicht erreichbar, genügt die Eingabe der SemVer in einem manuellen Feld.

## Host-Port (Streamlit)


| Einstellung | Bedeutung                                                                      |
| ----------- | ------------------------------------------------------------------------------ |
| Standard    | Host **8501** → Container **8501**                                             |
| Ändern      | Plugin Admin → **Einstellungen** → Host-Port speichern (löst Image-Pull/Neustart aus) |
| Gültig      | 1024–65535                                                                     |
| Persistenz  | `plugin.env` (`STREAMLIT_PORT=…`); ein Upgrade stellt die Datei wieder her     |


Der Link „Earnie öffnen“ folgt dem konfigurierten Port.

## Plugin-Update vs. Image-Update


| Aktion                                                             | Was sich ändert                                                                  |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| LoxBerry AutoUpdate / neues Plugin-ZIP (`plugin.cfg` `AUTOMATIC_UPDATES`) | Verwaltungsskripte, WebUI, Compose-Wrapper (`plugin.cfg` VERSION, z. B. `0.2.0`); das Earnie-Image bleibt **unverändert** |
| Kanal / `EARNIE_AUTO_UPDATE` / „Image aktualisieren“ / `earnie_ctl.sh pull` | lädt `ghcr.io/jochentcc/earnie-energy` gemäß Kanal (`:latest` / `:next` / `:Version`) und startet den Container neu |


Die Versionsnummer des Plugins ist **unabhängig** von der Earnie-Version (`version.py`). LoxBerry-`AUTOMATIC_UPDATES` und der Image-Kanal `EARNIE_AUTO_UPDATE` sind **zwei getrennte Schalter**.

## Upgrade

Bei einem Plugin-Upgrade stoppt der Installer kurz die Unit. Er behält `plugin.env` und die Bind-Mounts unter `earnie_env/` bei und startet Compose danach neu. Config und Runtime bleiben erhalten.

Zusätzlich räumt `postupgrade.sh` die Notizdatei auf:

- Fehlt `EARNIE_CHANNEL`, setzt das Skript `stable`.
- Fehlt `EARNIE_AUTO_UPDATE`, setzt es `EARNIE_AUTO_UPDATE=1`.
- Eine nicht mehr genutzte `IMAGE=`-Zeile wird entfernt.

Nach einem Earnie-Image-Update kann der Container im **Migrationsmodus** starten; statt der normalen Oberfläche erscheint dann ein Assistent. Backups liegen unter `…/data/plugins/earnie/earnie_env/config/backups/pre-migration-…/`. Details: [Betrieb → Update und Migration](betrieb.md#update-und-migration).

## Deinstallation

Das Uninstall-Skript:

- stoppt und entfernt die systemd-Units `earnie` und `earnie-update.timer`,
- entfernt den Container `earnie-productive`,
- löscht absichtlich **nicht** `earnie_env/` und entfernt **nicht** das GHCR-Image.

LoxBerry kann beim Deinstallieren trotzdem das Plugin-Datenverzeichnis entfernen. Werden Config und Runtime nach der Deinstallation noch gebraucht, `earnie_env/` **vorher** an einen sicheren Ort kopieren. Zum manuellen Löschen danach den Ordner `earnie_env` unter dem Plugin-Datenpfad entfernen.