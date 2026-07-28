# Earnie — Anwender-Dokumentation

Diese Dokumentation richtet sich an Betreiber von Earnie: Einrichtung, Konfiguration, Streamlit-Oberfläche und die Smarthome-Anbindung (Loxone, Home Assistant/evcc oder OpenEMS).

**Einstieg aus Anwendersicht (Handbuch):** [Benutzer-Handbuch Earnie](user-manual/Benutzer-Handbuch-Earnie.md)

Für Entwickler (Projektstruktur, Tests, Container) siehe [DEVELOPER.md](../DEVELOPER.md).

Zum Ausprobieren des Szenarien-eExplorers ohne Intallation:
[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://earnie.streamlit.app)

## Erste Schritte

1. **Konfiguration:** `share/config/config.example.json` → Bootstrap legt `earnie_env/config/config.json` an (lokal, nicht committen). Alternativ `python -m scripts.bootstrap_runtime`. Hausdaten: [Private Haus-Config](einrichtung/private-env.md).
2. **Smarthome-Backend wählen:** [Adapter wählen](einrichtung/adapter-wahl.md) (Default Loxone; alternativ HA+evcc oder OpenEMS-Lab). Bei Loxone: `.env.example` → `earnie_env/config/.env` mit `LOXONE_IP`, `LOXONE_USER`, `LOXONE_PASS` (Docker: Entrypoint legt `.env` im Config-Volume an).
3. **Feld-Mapping:** Bei Loxone Merker in `loxone_blocks` / Hausprofil ([Loxone-Signale](referenz/loxone-signale.md)); bei HA Entity→EHAL auf [EHAL-Com](ui/ehal-com.md). Legacy-`flexible_consumers` in `config.json` nur noch bei Bedarf.
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

- [Benutzer-Handbuch Earnie](user-manual/Benutzer-Handbuch-Earnie.md) — Überblick, Einrichtung Was-wäre-wenn, Loxone, Live-Betrieb (Entwurf)



### Einrichtung

- [Adapter wählen](einrichtung/adapter-wahl.md) — Loxone / HA+evcc / OpenEMS über `ehal.backend` (Config-Umschaltung)
- [Loxone-Anbindung](einrichtung/loxone-anbindung.md) — HTTP-Schnittstelle, FTP-Log, Prüfskript
- [Betrieb](einrichtung/betrieb.md) — `main.py` vs. App, Laufzeitdateien, Optimierungs-Takt
- [Container](einrichtung/container.md) — Docker/Synology/LoxBerry, Multi-Arch, Bootstrap, Migration, Config-Drift
- [LoxBerry-Plugin](einrichtung/loxberry-plugin.md) — Scope-A-Plugin (Docker-Wrapper, Port 8501) vs. manuelle Compose
- [Proxmox LXC](einrichtung/proxmox-lxc.md) — Unprivileged LXC mit Docker Compose (Port 8501)
- [Greenfield Dev-Stack](einrichtung/greenfield-dev-stack.md) — lokale Ersteinrichtung (Port 8502) für Hauskonfigurator/Backtesting
- [OpenEMS-Lab](einrichtung/openems-lab.md) — Earnie + OpenEMS Edge/UI (Port 8503); Kommunikationscheck in der Spec
- [Home Assistant + evcc](einrichtung/ha-evcc.md) — DACH-Pfad A2 (Compose, Port 8506) vs Pfad B (bestehendes HA); Optimizer-Exklusivität / Modbus
- [Private Haus-Config](einrichtung/private-env.md) — privates Repo + Junction; öffentliche Vorlagen/Tarife unter `share/config/`



### Konfiguration (`earnie_env/config/config.json`)

- [Überblick](konfiguration/ueberblick.md) — Aufbau der Datei, Szenarien, Dateipfade
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

- [Streamlit-Ports](referenz/streamlit-ports.md) — Port pro Stack/Plattform (8501 Prod, 8521/8531 lokal, 8502/8532 Greenfield, 8503 OpenEMS-Lab, …)
- [Loxone-Signale](referenz/loxone-signale.md) — Tabelle aller Lesen-/Schreib-Signale
- [OeMAG & Referenzmarktwert](referenz/oemag-referenzmarktwert.md) — OeMAG-Marktpreis vs. E-Control RefMarkt PV
- [Tarife und Preise nachrechnen](referenz/tarife-quellen.md) — Bezugs-/Einspeisepreise, SE-Fixkosten und Fake-Jahresrechnung; Quellen und Katalog-Audit



### Entwickler-Specs (Englisch/technisch)

- [Spec Soll-Ist](spec/soll-ist-abweichung.md) — Regelwerk, Szenarien, Pflegehinweis
- [Backtesting: fixed_24h vs sunrise_window](spec/backtesting-horizon-fixed24h-vs-sunrise.md) — Jahresvergleich Nutzen (€) und Rechenlast (CBC / strict_slow)

