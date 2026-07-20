# Earnie — Anwender-Dokumentation

Diese Dokumentation richtet sich an Betreiber von Earnie: Einrichtung, Konfiguration, Streamlit-Oberfläche und die Schnittstelle zum Loxone Miniserver.

**Einstieg aus Anwendersicht (Handbuch):** [Benutzer-Handbuch Earnie](user-manual/Benutzer-Handbuch-Earnie.md)

Für Entwickler (Projektstruktur, Tests, Container) siehe [DEVELOPER.md](../DEVELOPER.md).

## Erste Schritte

1. **Konfiguration:** `share/config/config.example.json` → Bootstrap legt `earnie_env/config/config.json` an (lokal, nicht committen). Alternativ `python -m scripts.bootstrap_runtime`. Hausdaten: [Private Haus-Config](einrichtung/private-env.md).
2. **Loxone-Zugang:** `.env.example` → `earnie_env/config/.env` mit `LOXONE_IP`, `LOXONE_USER`, `LOXONE_PASS` (Docker: Entrypoint legt `.env` im Config-Volume an).
3. **Merker-Namen** in `earnie_env/config/config.json` unter `loxone_blocks` und in den Verbrauchern des Hausprofils (`house_profiles.json`) anpassen (siehe [Loxone-Signale](referenz/loxone-signale.md)). Legacy-`flexible_consumers` in `config.json` nur noch bei Bedarf.
4. **Verbindung prüfen:**
   ```powershell
   python -m scripts.verify_loxone_setup
   ```
5. **Produktivbetrieb:** Docker-Container starten (UI + `main.py` Auto-Start) oder lokal `python main.py` / UI **Optimierer-Dienst**.
6. **Monitor öffnen:** `python -m scripts.run_streamlit` (Port: `ui.streamlit_port` / `EARNIE_UI_STREAMLIT_PORT`; lokal venv typisch **8531**, siehe [Streamlit-Ports](referenz/streamlit-ports.md))

Parameter-Beschreibungen erscheinen in Cursor/VS Code als Hover-Hilfe, wenn in `config.json` `"$schema": "./config.schema.json"` gesetzt ist.

**Container-Betrieb (Synology / LoxBerry / Proxmox LXC):** [Container](einrichtung/container.md) · [Proxmox LXC](einrichtung/proxmox-lxc.md)

## Inhaltsverzeichnis

### Benutzer-Handbuch

- [Benutzer-Handbuch Earnie](user-manual/Benutzer-Handbuch-Earnie.md) — Überblick, Einrichtung Was-wäre-wenn, Loxone, Live-Betrieb (Entwurf)

### Einrichtung

- [Loxone-Anbindung](einrichtung/loxone-anbindung.md) — HTTP-Schnittstelle, FTP-Log, Prüfskript
- [Betrieb](einrichtung/betrieb.md) — `main.py` vs. App, Laufzeitdateien, Optimierungs-Takt
- [Container](einrichtung/container.md) — Docker/Synology/LoxBerry, Multi-Arch, Bootstrap, Migration, Config-Drift
- [Proxmox LXC](einrichtung/proxmox-lxc.md) — Unprivileged LXC mit Docker Compose (Port 8501)
- [Greenfield Dev-Stack](einrichtung/greenfield-dev-stack.md) — lokale Ersteinrichtung (Port 8502) für Hauskonfigurator/Backtesting
- [Private Haus-Config](einrichtung/private-env.md) — privates Repo + Junction; öffentliche Vorlagen/Tarife unter `share/config/`

### Konfiguration (`earnie_env/config/config.json`)

- [Überblick](konfiguration/ueberblick.md) — Aufbau der Datei, Szenarien, Dateipfade
- [Speichern / Laden](konfiguration/speichern-laden.md) — `earnie_env`, Auto-Save, ZIP-Export/Import
- [PV & Batterie](konfiguration/batterie-pv.md) — Live-Szenario, Entitäts-Referenzen
- [Flexible Verbraucher](konfiguration/flexible-verbraucher.md) — SwimSpa, E-Auto, Wärmepumpe, Manuelle Geräte
- [Historische Verbrauchs-CSV](konfiguration/verbrauchs-csv.md) — Hausprofil Gesamt-/Verbraucher-CSV, Normalisierung, Loxone-Import
- [Preise & aWATTar](konfiguration/preise.md) — Bezugspreis, Einspeisevergütung, Preis-Prognose

### Benutzeroberfläche (Streamlit)

- [Betriebsmodi & Navigation](ui/betriebsmodi.md) — Seitenstruktur, Monitor (Sunset-2-Sunset), Szenario-Explorer
- [Charts & Panels](ui/charts.md) — Diagramme, Metriken, Sankey, Soll/Ist-Icons
- [Loxone-Kommunikation](ui/loxone-kommunikation.md) — Debug-Seite: Live-Lesen, Schreib-Nachverfolgung (Cutover 1.99)

### Referenz

- [Streamlit-Ports](referenz/streamlit-ports.md) — Port pro Stack/Plattform (8501 Prod, 8521/8531 lokal, 8502/8532 Greenfield, 8503 lokal gegen NAS)
- [Loxone-Signale](referenz/loxone-signale.md) — Tabelle aller Lesen-/Schreib-Signale

### Entwickler-Specs (Englisch/technisch)

- [Spec Soll-Ist](spec/soll-ist-abweichung.md) — Regelwerk, Szenarien, Pflegehinweis
