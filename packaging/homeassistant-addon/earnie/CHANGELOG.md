# Changelog — Earnie Home Assistant Add-on

Eigenes SemVer, unabhängig von `version.py` (Earnie-App-Version) — analog zum LoxBerry-Plugin.

## 0.1.0

- Erste Version (MVP): Add-on-Wrapper um `ghcr.io/jochentcc/earnie-energy`, dateibasierte Konfiguration unter `/data/earnie_env`, optionales Options-Mapping für Loxone-Zugangsdaten, Streamlit-Port, UI-Modi, Auto-Start und Zeitzone.
- Kein Ingress, keine Add-on-Options-UI-Erzeugung von `config.json`, keine MQTT-Discovery (siehe Roadmap in der Entwicklungsplan-Doku).
