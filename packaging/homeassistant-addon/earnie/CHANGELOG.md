# Changelog — Earnie Home Assistant Add-on

Add-on `version:` mirrors the Earnie app release (`version.py` / GHCR tag). Each release tag auto-publishes via `.github/workflows/release.yml` → job `publish_ha_addon`.

## 2.5.3-alpha.2

- Community **pre-release** of the **2.5.3** line (follow-up to `2.5.3-alpha.1`). Focus: EV EHAL binding safety, EHAL-Com mapping UX, and SonarCloud leak-period remediations.
- Earnie release: [2.5.3-alpha.2](https://github.com/JochenTCC/Earnie/releases/tag/v2.5.3-alpha.2)

## 2.5.3-alpha.1

- Pins Earnie `2.5.3-alpha.1` (`ghcr.io/jochentcc/earnie-energy:2.5.3-alpha.1`).
- Earnie release: [2.5.3-alpha.1](https://github.com/JochenTCC/Earnie/releases/tag/v2.5.3-alpha.1)

## 2.5.2

- Official **PATCH** after **2.5.1**. Focus: Analyse period navigation and Chart 1 Ist↔SoC consistency.
- Earnie release: [2.5.2](https://github.com/JochenTCC/Earnie/releases/tag/v2.5.2)

## 2.5.1

- Official **PATCH** after **2.5.0**. Focus: live telemetry robustness, Chart 1 / SoC consistency, and Loxone auth recovery.
- Earnie release: [2.5.1](https://github.com/JochenTCC/Earnie/releases/tag/v2.5.1)

## 2.5.0

- Official **2.5.0** after the community alpha line (`2.5.0-alpha.*`). Focus: **15‑minute MILP horizon**, tariff settlement fidelity, Hauskonfigurator / Smarthome-Backend UX, and release hardening.
- Earnie release: [2.5.0](https://github.com/JochenTCC/Earnie/releases/tag/v2.5.0)

## 0.1.0

- Erste Version (MVP): Add-on-Wrapper um `ghcr.io/jochentcc/earnie-energy`, dateibasierte Konfiguration unter `/data/earnie_env`, optionales Options-Mapping für Loxone-Zugangsdaten, Streamlit-Port, UI-Modi, Auto-Start und Zeitzone.
- Kein Ingress, keine Add-on-Options-UI-Erzeugung von `config.json`, keine MQTT-Discovery (siehe Roadmap in der Entwicklungsplan-Doku).
- Ab dem nächsten automatischen Release: Add-on-Version = Earnie-App-Version (kein separates SemVer mehr).
