# LoxBerry-Plugin (Scope A) — Earnie per Docker

Earnie als **dünner Docker-Wrapper** im LoxBerry Plugin Admin: kein natives Python/Streamlit/MILP auf dem Pi. Der Plugin-Installer startet denselben Container wie die manuelle Compose-Installation (`ghcr.io/jochentcc/earnie-energy:latest`, Host-Port standardmäßig **8501**, im Container immer **8501**).

Quellbaum im Repo: [`packaging/loxberry/`](../../packaging/loxberry/). Packaging-Hinweise (ZIP, Version-Bump): [`packaging/loxberry/README.md`](../../packaging/loxberry/README.md).

Manuelle Compose-Alternative (ohne Plugin): [Container — LoxBerry](container.md#loxberry-rpi-4b-arm64).

## Voraussetzungen (Go/No-Go)

| Kriterium | Go | No-Go |
|-----------|----|-------|
| LoxBerry | **4.x**, 64-bit | 3.x |
| Docker | Docker-Plugin installiert und aktiv (`docker compose` v2) | kein Docker / kein Socket für User `loxberry` |
| Architektur | **aarch64** | 32-bit (`armv7l`) |
| RAM | mind. **4 GB** empfohlen | unter 2 GB |
| Speicher | **SSD** bevorzugt | nur langsame SD ohne Puffer |

Gleiche Tabelle wie in [Container — Go/No-Go (LoxBerry)](container.md#gono-go-loxberry).

## Installation

1. Docker-Plugin im LoxBerry aktivieren und prüfen (`docker compose version`).
2. Plugin-ZIP bauen oder vom GitHub-Release laden (siehe Packaging-README).
3. LoxBerry → **Plugin-Verwaltung** → ZIP installieren.
4. Bei Erfolg: systemd-Unit `earnie`, Container `earnie-productive`, Volumes unter dem Plugin-Datenverzeichnis.
5. Streamlit im LAN: `http://<loxberry-ip>:8501` (oder der in der Plugin-UI gesetzte Host-Port)
6. Danach wie üblich `earnie_env/config/.env` und `config.json` anpassen (Entrypoint legt fehlende Dateien an). Miniserver-Prefill ist **nicht** Teil dieses Plugins.

Die Plugin-UI zeigt Status, Start/Stop/Neustart, Image-Pull, einen Link zur Streamlit-Oberfläche und ein Feld zum Ändern des **Host-Ports** (Compose-Mapping `HOST:8501`; Container-Port bleibt 8501).

## Datenpfade

Persistenz (überlebt Plugin-Upgrades und Image-Pulls):

| Host (Plugin) | Container |
|---------------|-----------|
| `…/data/plugins/earnie/earnie_env/config/` | `/app/config` |
| `…/data/plugins/earnie/earnie_env/runtime/` | `/app/runtime` |

Kleine Plugin-Notizdatei: `…/config/plugins/earnie/plugin.env` (kein Geheimnis-Store; Loxone-Zugangsdaten gehören in `earnie_env/config/.env`). Enthält u. a. `STREAMLIT_PORT` (Host-Port, Standard **8501**). Beim Speichern in der Plugin-UI wird derselbe Wert nach `…/data/plugins/earnie/docker/.env` gespiegelt (Compose-Interpolation).

## Host-Port (Streamlit)

| Einstellung | Bedeutung |
|-------------|-----------|
| Standard | Host **8501** → Container **8501** |
| Ändern | Plugin Admin → Feld **Host-Port (Streamlit)** → speichern (Container-Neustart) |
| Gültig | 1024–65535 |
| Persistenz | `plugin.env` (`STREAMLIT_PORT=…`); Upgrade stellt die Datei wieder her |

Der „Earnie öffnen“-Link folgt dem konfigurierten Port. Parallelbetrieb mit manueller Compose auf demselben Host-Port vermeiden.

## Plugin-Update vs. Image-Update

| Aktion | Was sich ändert |
|--------|-----------------|
| LoxBerry AutoUpdate / neues Plugin-ZIP | Verwaltungsskripte, WebUI, Compose-Wrapper (`plugin.cfg` VERSION, z. B. `0.2.0`) |
| In der Plugin-UI **Image aktualisieren** bzw. `earnie_ctl.sh pull` | zieht `ghcr.io/jochentcc/earnie-energy:latest` neu und startet den Container neu |

Die Plugin-SemVer ist **unabhängig** von Earnie `version.py`. Es gibt keinen Alpha/Prod-Umschalter in Scope A — immer `:latest`.

## Upgrade

Bei Plugin-Upgrade stoppt der Installer die Unit kurz, erhält `plugin.env` und die Bind-Mounts unter `earnie_env/`, und startet Compose danach neu. Config und Runtime bleiben erhalten.

## Deinstallation (Datenpolitik)

Das Uninstall-Skript:

- stoppt und entfernt die systemd-Unit `earnie`
- entfernt den Container `earnie-productive`
- **löscht nicht** absichtlich `earnie_env/` und entfernt **nicht** das GHCR-Image

LoxBerry kann beim Deinstallieren trotzdem das Plugin-Datenverzeichnis entfernen. Wenn Config/Runtime nach der Deinstallation noch gebraucht werden: **vorher** `earnie_env/` an einen sicheren Ort kopieren. Manuelles Löschen danach: Ordner `earnie_env` unter dem Plugin-Datenpfad entfernen.

## Parallelbetrieb mit manueller Compose

Nicht empfohlen: Plugin und manuelle Installation unter `/opt/earnie-energy/` nutzen denselben Container-Namen `earnie-productive` und standardmäßig denselben Host-Port **8501**. Entweder Plugin **oder** manuelle Compose wählen — oder im Plugin einen anderen Host-Port setzen.

## Alpha / Sidecars

Community-Alpha (Port 8511), HA/evcc/OpenEMS-Sidecars und Kanalumschalter sind **nicht** Teil von Scope A. Siehe [Streamlit-Ports](../referenz/streamlit-ports.md) und [Container](container.md).
