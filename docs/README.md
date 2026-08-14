# Earnie — Anwender-Dokumentation

Diese Dokumentation richtet sich an Betreiber von Earnie: Einrichtung, Konfiguration, Streamlit-Oberfläche und die Smarthome-Anbindung (Loxone, Home Assistant/evcc oder OpenEMS).

**Einstieg aus Anwendersicht (Handbuch):** [Benutzer-Handbuch Earnie](user-manual/Benutzer-Handbuch-Earnie.md)

Für Entwickler (Projektstruktur, Tests, Container) siehe [DEVELOPER.md](../DEVELOPER.md).

Zum Ausprobieren des Szenario-Explorers ohne Installation:
[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://earnie.streamlit.app)

## Erste Schritte

1. **Konfiguration:** `share/config/config.example.json` → Bootstrap legt `earnie_env/config/config.json` an (lokal, nicht committen). Alternativ `python -m scripts.bootstrap_runtime`. Hausdaten: [Private Haus-Config](einrichtung/private-env.md).
2. **Smarthome-Backend wählen:** [Adapter wählen](einrichtung/adapter-wahl.md) (Default Loxone; alternativ HA+evcc oder OpenEMS-Lab). Bei Loxone: `.env.example` → `earnie_env/config/.env` mit `LOXONE_IP`, `LOXONE_USER`, `LOXONE_PASS` (Docker: Entrypoint legt `.env` im Config-Volume an).
3. **Feld-Mapping:** Bei Loxone Merker in `plant.ehal_bindings` / Hausprofil über **EHAL-Com** ([Loxone-Signale und Earnie-Library](referenz/loxone-signals.md)); bei HA Entity→EHAL auf [EHAL-Com](ui/ehal-com.md). Legacy-`flexible_consumers` in `config.json` nur noch bei Bedarf (meist leer).
4. **Verbindung prüfen:** EHAL-Com (Live-Lesen) bzw. bei Loxone:
  ```powershell
   python -m scripts.verify_loxone_setup
  ```
5. **Produktivbetrieb:** Docker-Container starten (UI + `main.py` Auto-Start) oder lokal `python main.py` / UI **Optimierer-Dienst**.
6. **Monitor öffnen:** `python -m scripts.run_streamlit` (Port: `ui.streamlit_port` / `EARNIE_UI_STREAMLIT_PORT`; lokal venv typisch **8531**, siehe [Streamlit-Ports](referenz/streamlit-ports.md))

Parameter-Beschreibungen erscheinen in Cursor/VS Code als Hover-Hilfe, wenn in `config.json` `"$schema": "./config.schema.json"` gesetzt ist.

**Container-Betrieb (Synology / LoxBerry / Proxmox LXC):** [Container](einrichtung/container.md) · [LoxBerry-Plugin](einrichtung/loxberry-plugin.md) · [Proxmox LXC](einrichtung/proxmox-lxc.md)

## Inhaltsverzeichnis



### Benutzer-Handbuch

- [Benutzer-Handbuch Earnie](user-manual/Benutzer-Handbuch-Earnie.md) — Überblick, Einrichtung Was-wäre-wenn, Smarthome, Live-Betrieb



### Einrichtung

- [Adapter wählen](einrichtung/adapter-wahl.md) — Loxone / HA+evcc / OpenEMS über `ehal.backend` (Config-Umschaltung)
- [Loxone-Anbindung](einrichtung/loxone-anbindung.md) — HTTP-Schnittstelle, Prüfskript
- [Betrieb](einrichtung/betrieb.md) — `main.py` vs. App, Laufzeitdateien, Optimierungs-Takt
- [Container](einrichtung/container.md) — Docker/Synology/LoxBerry, Multi-Arch, Bootstrap, Migration, Config-Drift
- [LoxBerry-Plugin](einrichtung/loxberry-plugin.md) — Scope-A-Plugin (Docker-Wrapper, Port 8501) vs. manuelle Compose
- [Proxmox LXC](einrichtung/proxmox-lxc.md) — Unprivileged LXC mit Docker Compose (Port 8501)
- [Greenfield Dev-Stack](einrichtung/greenfield-dev-stack.md) — lokale Ersteinrichtung (Port 8502) für Hauskonfigurator/Backtesting
- [OpenEMS-Lab](einrichtung/openems-lab.md) — Earnie + OpenEMS Edge/UI (Port 8503); Kommunikationscheck in der Spec
- [Home Assistant + evcc](einrichtung/ha-evcc.md) — DACH-Pfad A2 (Compose, Port 8506) vs Pfad B (bestehendes HA); Optimizer-Exklusivität / Modbus
- [Private Haus-Config](einrichtung/private-env.md) — privates Repo + Junction; öffentliche Vorlagen/Tarife unter `share/config/`



### Konfiguration (`earnie_env/config/config.json`)

- [Überblick](konfiguration/overview.md) — Aufbau der Datei, Szenarien, Dateipfade
- [Speichern / Laden](konfiguration/speichern-laden.md) — `earnie_env`, Auto-Save, ZIP-Export/Import
- [PV & Batterie](konfiguration/batterie-pv.md) — Live-Szenario, Entitäts-Referenzen
- [Flexible Verbraucher](konfiguration/flexible-verbraucher.md) — SwimSpa, E-Auto, Wärmepumpe, Manuelle Geräte
- [Historische Leistungsprofil-CSV](konfiguration/verbrauchs-csv.md) — Hausprofil Last-/PV-/Verbraucher-Leistungsprofile, Normalisierung, Loxone-Import
- [Preise & aWATTar](konfiguration/preise.md) — Bezugspreis, Einspeisevergütung, Preis-Prognose



### Benutzeroberfläche (Streamlit)

- [Betriebsmodi & Navigation](ui/betriebsmodi.md) — Seitenstruktur, Monitor (Sunset-2-Sunset), Szenario-Explorer
- [Charts & Panels](ui/charts.md) — Diagramme, Metriken, Sankey, Soll/Ist-Icons
- [EHAL-Com](ui/ehal-com.md) — Anbindung & Debug: Loxone / HA / OpenEMS, Live-Lesen, Live-Schreiben



### Referenz

- [Abkürzungen](referenz/abbreviations.md) — EHAL, SE, HK, SoC, VI/VO und weitere Kurzformen
- [Streamlit-Ports](referenz/streamlit-ports.md) — Port pro Stack/Plattform (8501 Prod, 8521/8531 lokal, 8502/8532 Greenfield, 8503 OpenEMS-Lab, …)
- [Loxone-Signale und Earnie-Library](referenz/loxone-signals.md) — Motivation, VI/VO-Vorlagen (Pattern B), Default-Merker, EFM, Import, Signal-Tabellen
- [OeMAG & Referenzmarktwert](referenz/oemag-referenzmarktwert.md) — OeMAG-Marktpreis vs. E-Control RefMarkt PV
- [Tarife und Preise nachrechnen](referenz/tarife-quellen.md) — Bezugs-/Einspeisepreise, SE-Fixkosten und Fake-Jahresrechnung; Quellen und Katalog-Audit



### Entwickler-Specs (Englisch/technisch)

- [EHAL](spec/ehal.md) — Hardware Access Layer contract (schema_version 3, adapters)
- [Spec Soll-Ist](spec/soll-ist-abweichung.md) — Regelwerk Chart 1, Szenarien, Pflegehinweis
- [UI Sunset-2-Sunset](spec/ui-sunset2sunset.md) — Monitor-Cockpit (historisch abgeschlossen)
- [UI-Menüstruktur](spec/ui-menu-structure.md) — historische Epic-Notiz (native Pages shipped)
- [Sunset-Planungshorizont](spec/planning-horizon-sunset.md) — Live-Horizont SA₁→SA₂, SOC-Anker
- [Backtesting: fixed_24h vs sunrise_window](spec/backtesting-horizon-fixed24h-vs-sunrise.md) — Jahresvergleich Nutzen (€) und Rechenlast
- [Backtesting deviation calendar](spec/backtesting-deviation-calendar.md) — Abweichungskalender SE
- [Backtesting plausibility S2](spec/backtesting-plausibility-s2-kein-pv-jan-2-7.md) — Plausibilitätsnotiz
- [Scenario-Explorer consumption](spec/scenario-explorer-consumption.md) — SE-Last-/CSV-Semantik
- [SE calculation test plan](spec/se-calculation-test-plan.md) — SE-Rechentests
- [OpenEMS lab setup](spec/openems-lab-setup.md) — Compose + Earnie ↔ OpenEMS
- [OpenEMS testing platform](spec/openems-testing-platform-todo.md) — Plant-/REST-Kanal-Checkliste
- [HA + evcc lab setup](spec/ha-lab-setup.md) — Compose + Earnie ↔ Home Assistant
- [SwimSpa filter](spec/swimspa-filter.md) — Filter-Schulden / MILP
- [Price forecast renewables](spec/price-forecast-renewables.md) — Preisprognose-Modell
- [EFM auto-sync](spec/efm-auto-sync-2.4.l.md) — historische Research-Notiz Interpretation C
- [Hardware registry Layer C](spec/hardware-registry-layer-c.md) — Registry / Banner (soft 2.4.q; full C later)
- [Branching & Hotfix Playbook](spec/branching-hotfix-playbook.md) — Tags, hotfixes, `main`
- [Epic deploy user](spec/epic-deploy-user.md) — historische PyInstaller-Draft (superseded by GHCR release)

