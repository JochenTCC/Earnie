# Changelog — Earnie Home Assistant Add-on

Add-on `version:` mirrors the Earnie app release (`version.py` / GHCR tag). Each release tag auto-publishes via `.github/workflows/release.yml` → job `publish_ha_addon`.

## 2.6.0-alpha.1

- First community **pre-release** of the **2.6** HA-coupling line (follows official **2.5.3**). Do **not** continue `2.5.3-alpha.N` — pin this tag.
- Earnie release: [2.6.0-alpha.1](https://github.com/JochenTCC/Earnie/releases/tag/v2.6.0-alpha.1)

## Unreleased

- **`ehal_loxone_http_port`:** `run.sh` exports `EARNIE_EHAL_LOXONE_HTTP_PORT` (runtime env precedence over `config.json`, same pattern as Streamlit port).

## 2.5.3

- Official **PATCH** after **2.5.2**. HA add-on Ingress: nginx path re-inject, start-fix (broken `sed`), cold-start page „Earnie startet noch“ (HTTP 200 while Streamlit boots).
- Earnie release: [2.5.3](https://github.com/JochenTCC/Earnie/releases/tag/v2.5.3)

## 2.5.3-alpha.6

- **Ingress start fix:** `run.sh` no longer uses a broken GNU `sed` escape (`s/[&|]/g` → unterminated `s` command) that aborted add-on start when `ingress_entry` was present. Nginx conf is rendered with Python `str.replace`.
- Earnie release: [2.5.3-alpha.6](https://github.com/JochenTCC/Earnie/releases/tag/v2.5.3-alpha.6)

## 2.5.3-alpha.5

- **Ingress fix:** nginx on `:8501` re-attaches Supervisor `ingress_entry` and proxies to Streamlit on `:8502` with `baseUrlPath` (native Streamlit-only path caused "Not found" for Ingress and bare host:8501).
- Earnie release: [2.5.3-alpha.5](https://github.com/JochenTCC/Earnie/releases/tag/v2.5.3-alpha.5)

## 2.5.3-alpha.4

- **Ingress:** `ingress: true` / `ingress_port: 8501` — primary UI via HA sidebar / OPEN WEB UI (no `homeassistant.local:8501` lookup). Streamlit `baseUrlPath` from Supervisor `ingress_entry`.
- **Options → config.json:** fresh install seeds `ehal.backend=ha`; `streamlit_port` / `ehal_loxone_http_port` merge into `config.json` each start.
- Host port `8501` remains optional for advanced/direct LAN access.
- Earnie release: [2.5.3-alpha.4](https://github.com/JochenTCC/Earnie/releases/tag/v2.5.3-alpha.4)

## 2.5.3-alpha.3

- Community **pre-release** of the **2.5.3** line (follow-up to `2.5.3-alpha.2`). Focus: Home Assistant add-on Phase 1 installation blockers (Supervisor HA discovery/auth).
- Earnie release: [2.5.3-alpha.3](https://github.com/JochenTCC/Earnie/releases/tag/v2.5.3-alpha.3)

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
