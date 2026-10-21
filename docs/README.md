# Earnie – Anwender-Dokumentation

Diese Dokumentation richtet sich an alle, die Earnie betreiben. Die Themen sind Einrichtung, Konfiguration, die Streamlit-Oberfläche und die Smarthome-Anbindung (Loxone, Home Assistant/evcc oder OpenEMS).

**Einstieg aus Anwendersicht:** [Benutzer-Handbuch Earnie](user-manual/Benutzer-Handbuch-Earnie.md)

- **Produktüberblick:** [README.md](../README.md) im Repo-Root.
- **Für Entwickler:innen** (Projektstruktur, Tests, Container): [DEVELOPER.md](../DEVELOPER.md).

Der Szenario-Explorer lässt sich ohne Installation online ausprobieren:
[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://earnie.streamlit.app)

## Erste Schritte

1. **Konfiguration anlegen:** Der Bootstrap erzeugt aus `share/config/config.example.json` die Datei `earnie_env/config/config.json` (lokal, nicht committen). Alternativ `python -m scripts.bootstrap_runtime` ausführen. Hausdaten: [Private Haus-Config](einrichtung/private-env.md).
2. **Smarthome-Backend wählen:** Standard ist Loxone, alternativ HA+evcc oder OpenEMS-Lab ([Smarthome-Backend wählen](einrichtung/smarthome-backend-wahl.md)). Auswahl und Zugangsdaten stehen in der UI unter [Smarthome-Backend](ui/smarthome-backend.md).
   - **Loxone:** `.env.example` nach `earnie_env/config/.env` kopieren und `LOXONE_IP`, `LOXONE_USER`, `LOXONE_PASS` eintragen. Im Docker-Betrieb legt der Entrypoint die `.env` im Config-Volume an.
   - **Home Assistant:** Backend wählen, dann das YAML-Paket aus EHAL-Com in Home Assistant einbinden. Earnie braucht keine HA-URL und kein Token (Home Assistant ruft Earnie auf).
3. **Felder zuordnen:**
   - **Loxone:** Merker in `plant.ehal_bindings` bzw. im Hausprofil über **EHAL-Com** zuordnen ([Loxone-Signale und Earnie-Library](referenz/loxone-signals.md)).
   - **Home Assistant:** Entities auf [EHAL-Com](ui/ehal-com.md) den EHAL-Feldern zuordnen, je Entität in `plant` bzw. `consumers[].ehal_bindings`.
4. **Verbindung prüfen:** über EHAL-Com (Live-Lesen), bei Loxone alternativ mit dem Prüfskript:
  ```powershell
   python -m scripts.verify_loxone_setup
  ```
5. **Produktivbetrieb starten:** Docker-Container starten (UI und `main.py` starten automatisch). Lokal geht es mit `python main.py` oder über die UI-Seite **Optimierer-Dienst**. Unter HAOS: [Home-Assistant-Add-on](einrichtung/homeassistant-addon.md).
6. **Monitor öffnen:** `python -m scripts.run_streamlit` ausführen. Der Port kommt aus `ui.streamlit_port` bzw. `EARNIE_UI_STREAMLIT_PORT`; in einer lokalen venv ist er typischerweise **8501** (siehe [Streamlit-Ports](dev/streamlit-ports.md)).

> **Hinweis:** Cursor und VS Code zeigen die Parameter-Beschreibungen als Hover-Hilfe an, wenn in `config.json` `"$schema": "./config.schema.json"` gesetzt ist.

**Container-Betrieb:** [Container](einrichtung/container.md) · [LoxBerry-Plugin](einrichtung/loxberry-plugin.md) · [Proxmox LXC](einrichtung/proxmox-lxc.md) · [VMware `vctl`](einrichtung/vmware-vctl.md) · [Home-Assistant-Add-on](einrichtung/homeassistant-addon.md)

## Inhaltsverzeichnis

### Benutzer-Handbuch

- [Benutzer-Handbuch Earnie](user-manual/Benutzer-Handbuch-Earnie.md) – Überblick, Einrichtung der Was-wäre-wenn-Analyse, Smarthome, Live-Betrieb

### Einrichtung

- [Smarthome-Backend wählen](einrichtung/smarthome-backend-wahl.md) – Loxone, HA+evcc oder OpenEMS über `ehal.backend`
- [Loxone-Anbindung](einrichtung/loxone-anbindung.md) – HTTP-Schnittstelle und Prüfskript
- [Home Assistant + evcc](einrichtung/ha-evcc.md) – DACH-Pfad A2 (Compose) und Pfad B (bestehendes HA) im Vergleich
- [Home-Assistant-Add-on](einrichtung/homeassistant-addon.md) – Earnie als Supervisor-Add-on (Ingress, Options)
- [Betrieb](einrichtung/betrieb.md) – `main.py` und App, Laufzeitdateien, Optimierungs-Takt, [Update und Migration](einrichtung/betrieb.md#update-und-migration)
- [Container](einrichtung/container.md) – Docker/Synology/LoxBerry, Multi-Arch, Bootstrap, fehlende Config-Keys nach einem Upgrade
- [LoxBerry-Plugin](einrichtung/loxberry-plugin.md) – Plugin (Docker-Wrapper) und manuelle Compose-Installation im Vergleich
- [Proxmox LXC](einrichtung/proxmox-lxc.md) – Unprivileged LXC mit Docker Compose
- [VMware `vctl`](einrichtung/vmware-vctl.md) – Windows-PC ohne Docker Desktop
- [EcoFlow Delta 3 über Loxone](dev/done/ecoflow-delta3-loxone.md) – One-Way-Speicher und Hinweise zum Bridging
### Konfiguration (`earnie_env/config/`)

- [Überblick](konfiguration/overview.md) – Aufbau der Datei, Szenarien, Dateipfade
- [Speichern / Laden](konfiguration/speichern-laden.md) – `earnie_env`, Auto-Save, ZIP-Export/Import
- [PV & Batterie](konfiguration/batterie-pv.md) – Live-Szenario, Entitäts-Referenzen
- [Flexible Verbraucher](konfiguration/flexible-verbraucher.md) – SwimSpa, E-Auto, Wärmepumpe, Manuelle Geräte
- [Wärmespeicher Schichtung / T_eq](konfiguration/waermespeicher-schichtung-teq.md) – aus Schichtfühlern die äquivalente Temperatur für Earnie bilden (Loxone-Formel, Gewichte)
- [Historische Leistungsprofil-CSV](konfiguration/verbrauchs-csv.md) – Last-, PV- und Verbraucher-Profile, Normalisierung, Loxone-Import
- [Preise und Marktdaten](konfiguration/preise.md) – Bezugspreis, Einspeisevergütung, Preis-Prognose

### Benutzeroberfläche (Streamlit)

- [Betriebsmodi & Navigation](ui/betriebsmodi.md) – Seitenstruktur, Monitor (Sunset-2-Sunset), Szenario-Explorer
- [Charts & Panels](ui/charts.md) – Diagramme, Metriken, Sankey, Soll/Ist-Icons
- [Smarthome-Backend](ui/smarthome-backend.md) – Hub-Erkennung, Anbindung, Loxone-Import
- [EHAL-Com](ui/ehal-com.md) – Live-Lesen, Live-Schreiben und Mapping für Loxone, HA und OpenEMS (auf Englisch)

### Referenz

- [Abkürzungen](referenz/abbreviations.md) – EHAL, SE, HK, SoC, VI/VO und weitere Kurzformen
- [Streamlit-Ports](dev/streamlit-ports.md) – Port je Stack und Plattform
- [Loxone-Signale und Earnie-Library](referenz/loxone-signals.md) – VI/VO-Vorlagen je Entität, Default-Merker, EFM, Signal-Tabellen
- [OeMAG & Referenzmarktwert](referenz/oemag-referenzmarktwert.md) – OeMAG-Marktpreis und E-Control-RefMarkt PV im Vergleich
- [Tarife und Preise nachrechnen](referenz/tarife-quellen.md) – Bezugs- und Einspeisepreise, SE-Fixkosten und Fake-Jahresrechnung

### Für Entwickler:innen

Specs, Labs, Release-Prozess und Entwickler-Betrieb: [Entwickler-Index](entwicklung/README.md) und [DEVELOPER.md](../DEVELOPER.md).
