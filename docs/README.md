# Earnie — Anwender-Dokumentation

Diese Dokumentation richtet sich an Betreiber von Earnie: Einrichtung, Konfiguration, Streamlit-Oberfläche und die Smarthome-Anbindung (Loxone, Home Assistant/evcc oder OpenEMS).

**Einstieg aus Anwendersicht (Handbuch):** [Benutzer-Handbuch Earnie](user-manual/Benutzer-Handbuch-Earnie.md)

Produktüberblick und Landing: [README.md](../README.md) (Repo-Root).  
Für Entwickler (Projektstruktur, Tests, Container): [DEVELOPER.md](DEVELOPER.md).

Zum Ausprobieren des Szenario-Explorers ohne Installation:
[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://earnie.streamlit.app)

## Erste Schritte

1. **Konfiguration:** `share/config/config.example.json` → Bootstrap legt `earnie_env/config/config.json` an (lokal, nicht committen). Alternativ `python -m scripts.bootstrap_runtime`. Hausdaten: [Private Haus-Config](einrichtung/private-env.md).
2. **Smarthome-Backend wählen:** [Smarthome-Backend wählen](einrichtung/smarthome-backend-wahl.md) (Default Loxone; alternativ HA+evcc oder OpenEMS-Lab). Auswahl und Zugangsdaten in der UI: [Smarthome-Backend](ui/smarthome-backend.md). Bei Loxone: `.env.example` → `earnie_env/config/.env` mit `LOXONE_IP`, `LOXONE_USER`, `LOXONE_PASS` (Docker: Entrypoint legt `.env` im Config-Volume an). Bei HA: URL/Token in `config/.env` (`EHAL_HA_*`).
3. **Feld-Mapping:** Bei Loxone Merker in `plant.ehal_bindings` / Hausprofil über **EHAL-Com** ([Loxone-Signale und Earnie-Library](referenz/loxone-signals.md)); bei HA Entity→EHAL auf [EHAL-Com](ui/ehal-com.md) (Pattern B: `plant` / `consumers[].ehal_bindings`).
4. **Verbindung prüfen:** EHAL-Com (Live-Lesen) bzw. bei Loxone:
  ```powershell
   python -m scripts.verify_loxone_setup
  ```
5. **Produktivbetrieb:** Docker-Container starten (UI + `main.py` Auto-Start) oder lokal `python main.py` / UI **Optimierer-Dienst**. HAOS: [Home-Assistant-Add-on](einrichtung/homeassistant-addon.md).
6. **Monitor öffnen:** `python -m scripts.run_streamlit` (Port: `ui.streamlit_port` / `EARNIE_UI_STREAMLIT_PORT`; lokal venv typisch **8531**, siehe [Streamlit-Ports](referenz/streamlit-ports.md))

Parameter-Beschreibungen erscheinen in Cursor/VS Code als Hover-Hilfe, wenn in `config.json` `"$schema": "./config.schema.json"` gesetzt ist.

**Container-Betrieb:** [Container](einrichtung/container.md) · [LoxBerry-Plugin](einrichtung/loxberry-plugin.md) · [Proxmox LXC](einrichtung/proxmox-lxc.md) · [VMware `vctl`](einrichtung/vmware-vctl.md) · [Home-Assistant-Add-on](einrichtung/homeassistant-addon.md)

## Inhaltsverzeichnis

### Benutzer-Handbuch

- [Benutzer-Handbuch Earnie](user-manual/Benutzer-Handbuch-Earnie.md) — Überblick, Einrichtung Was-wäre-wenn, Smarthome, Live-Betrieb

### Einrichtung

- [Smarthome-Backend wählen](einrichtung/smarthome-backend-wahl.md) — Loxone / HA+evcc / OpenEMS über `ehal.backend`
- [Loxone-Anbindung](einrichtung/loxone-anbindung.md) — HTTP-Schnittstelle, Prüfskript
- [Home Assistant + evcc](einrichtung/ha-evcc.md) — DACH-Pfad A2 (Compose) vs. Pfad B (bestehendes HA)
- [Home-Assistant-Add-on](einrichtung/homeassistant-addon.md) — Earnie als Supervisor-Add-on (Ingress, Options)
- [Betrieb](einrichtung/betrieb.md) — `main.py` vs. App, Laufzeitdateien, Optimierungs-Takt
- [Container](einrichtung/container.md) — Docker/Synology/LoxBerry, Multi-Arch, Bootstrap, Migration
- [LoxBerry-Plugin](einrichtung/loxberry-plugin.md) — Scope-A-Plugin (Docker-Wrapper) vs. manuelle Compose
- [Proxmox LXC](einrichtung/proxmox-lxc.md) — Unprivileged LXC mit Docker Compose
- [VMware `vctl`](einrichtung/vmware-vctl.md) — Windows-PC ohne Docker Desktop
- [Greenfield Dev-Stack](einrichtung/greenfield-dev-stack.md) — lokale Ersteinrichtung für Hauskonfigurator/Backtesting
- [OpenEMS-Lab](einrichtung/openems-lab.md) — Earnie + OpenEMS Edge/UI; Kommunikationscheck in der Spec
- [Private Haus-Config](einrichtung/private-env.md) — privates Repo + Junction; öffentliche Vorlagen unter `share/config/`
- [EcoFlow Delta 3 über Loxone](einrichtung/ecoflow-delta3-loxone.md) — One-Way-Speicher / Bridging-Hinweis

### Konfiguration (`earnie_env/config/`)

- [Überblick](konfiguration/overview.md) — Aufbau der Datei, Szenarien, Dateipfade
- [Speichern / Laden](konfiguration/speichern-laden.md) — `earnie_env`, Auto-Save, ZIP-Export/Import
- [PV & Batterie](konfiguration/batterie-pv.md) — Live-Szenario, Entitäts-Referenzen
- [Flexible Verbraucher](konfiguration/flexible-verbraucher.md) — SwimSpa, E-Auto, Wärmepumpe, Manuelle Geräte
- [Historische Leistungsprofil-CSV](konfiguration/verbrauchs-csv.md) — Last-/PV-/Verbraucher-Profile, Normalisierung, Loxone-Import
- [Preise & aWATTar](konfiguration/preise.md) — Bezugspreis, Einspeisevergütung, Preis-Prognose

### Benutzeroberfläche (Streamlit)

- [Betriebsmodi & Navigation](ui/betriebsmodi.md) — Seitenstruktur, Monitor (Sunset-2-Sunset), Szenario-Explorer
- [Charts & Panels](ui/charts.md) — Diagramme, Metriken, Sankey, Soll/Ist-Icons
- [Smarthome-Backend](ui/smarthome-backend.md) — Hub-Erkennung, Anbindung, Loxone-Import
- [EHAL-Com](ui/ehal-com.md) — Live-Lesen / Live-Schreiben / Mapping (Loxone, HA, OpenEMS; English)

### Referenz

- [Abkürzungen](referenz/abbreviations.md) — EHAL, SE, HK, SoC, VI/VO und weitere Kurzformen
- [Streamlit-Ports](referenz/streamlit-ports.md) — Port pro Stack/Plattform
- [Loxone-Signale und Earnie-Library](referenz/loxone-signals.md) — VI/VO-Vorlagen (Pattern B), Default-Merker, EFM, Signal-Tabellen
- [OeMAG & Referenzmarktwert](referenz/oemag-referenzmarktwert.md) — OeMAG-Marktpreis vs. E-Control RefMarkt PV
- [Tarife und Preise nachrechnen](referenz/tarife-quellen.md) — Bezugs-/Einspeisepreise, SE-Fixkosten und Fake-Jahresrechnung

### Entwickler-Specs (Englisch/technisch)

Lab- und Simulationsumgebungen (HA Lab Compose, HouseSim-Mock) stehen nur hier — **nicht** Teil der Anwender-Einrichtung.

- [EHAL](spec/ehal.md) — Hardware Access Layer contract
- [HA + evcc lab setup](spec/ha-lab-setup.md) — Compose Earnie ↔ Home Assistant
- [House simulator](spec/house-sim.md) — interne Mock-/Dogfood-Bank (`house_sim/`)
- [OpenEMS lab setup](spec/openems-lab-setup.md) — Compose + Earnie ↔ OpenEMS
- [Branching & Hotfix Playbook](spec/branching-hotfix-playbook.md) — Tags, hotfixes, `main`
- Weitere Specs unter [`docs/spec/`](spec/)
