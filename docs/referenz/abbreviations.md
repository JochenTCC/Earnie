# Abbreviations

Short explanations of abbreviations and short forms used in the Earnie documentation and UI. Alphabetical; not exhaustive.

Sources for additions (scan): entries from `backlog/Doc-Review-Checklist.md` (priority-1 user docs).

| Abbreviation | Meaning |
| --------- | ----------- |
| **aWATTar** | Dynamic electricity tariff (spot/day-ahead); frequent example in the docs |
| **B2C** | Business-to-Consumer — end-customer/household product (vs. lab/industrial) |
| **BL** | Baseline — in chart 1 **SoC BL target**: reference run without a smart battery / without price-based load shifting |
| **CSV** | Comma-Separated Values — table file for load/PV/consumer power profiles |
| **DACH** | Germany, Austria, Switzerland — region for the HA+evcc recommendation |
| **DSGVO** | GDPR — General Data Protection Regulation (EU) |
| **EFM** | Energieflussmonitor (Loxone) — Energy Flow Monitor: meter/power statistics for import and mapping |
| **EHAL** | Earnie Hardware Access Layer — unified interface between the optimizer and the smarthome backend |
| **EHAL-Com** | Streamlit page **Connection & Debug** (live read/write, mapping, backend choice) |
| **EPEX** | European Power Exchange — day-ahead market prices (basis for many spot tariffs) |
| **ESS** | Energy Storage System — battery storage (power, SoC, mode) |
| **EV** | Electric Vehicle |
| **EVCS** | Electric Vehicle Charging Station — wallbox / charging station |
| **evcc** | Open-source charging/PV control; sidecar under Home Assistant (DACH path) |
| **FTP** | File Transfer Protocol — historically Miniserver logs; Earnie uses CSV/energy monitor instead of FTP |
| **GHCR** | GitHub Container Registry — source of the official Earnie container images |
| **Greenfield / Default** | In user docs: **Default** (template/import path, Merker prefix `Earnie_*`). "Greenfield" still appears in filenames (`greenfield_device_map.json`) and older texts; local dev stack often port **8502** |
| **GX** | Victron GX (e.g. Cerbo) — device hub, often via Modbus TCP |
| **HA** | Home Assistant — smarthome backend (often together with **evcc**) |
| **HITL** | Human-in-the-Loop — manual mapping/confirmation in the UI (no fully automatic LLM mapping) |
| **HK** | Hauskonfigurator — Streamlit area for house/profile configuration |
| **kWp** | Kilowatt-peak — installed PV nominal power |
| **LoxAPP3** | Loxone configuration/app export (`LoxAPP3.json`) — used for, among other things, EFM meters and import |
| **LoxBerry** | Mini-PC/Raspberry Pi plugin host in the Loxone ecosystem; Earnie plugin as a Docker wrapper |
| **LXC** | Linux Container — typical Proxmox environment for Docker Compose |
| **MCP** | Model Context Protocol — in the docs: Loxone MCP (currently not offered in the UI) |
| **MILP** | Mixed-Integer Linear Programming — the mathematical optimization method behind the Earnie plan |
| **Modbus** | Fieldbus/TCP protocol for inverters, Victron GX, wallboxes, etc.; only one writing owner per bus |
| **NAS** | Network Attached Storage — e.g. Synology as a Docker host |
| **OeMAG** | Austrian settlement agency for green electricity — feed-in/market price context |
| **OpenEMS** | Open Energy Management System — lab/industrial backend (`ehal.backend=openems`) |
| **PV** | Photovoltaic |
| **RefMarkt** | Referenzmarktwert (E-Control) — reference market value, used for PV feed-in pricing |
| **REST** | Representational State Transfer — HTTP API (e.g. the HA EHAL adapter) |
| **SA₁ / SA₂** | Sunset anchors — bounds of the live planning horizon (sunset to sunset / related segments) |
| **SaaS** | Software as a Service — commercial cloud use (not permitted without consent per the license) |
| **SE** | Szenario-Explorer — Scenario Explorer: annual/long-term comparisons and what-if calculations |
| **SG-Ready** | Smart-Grid-Ready — heat pump enable/tariff signal (in EHAL often via `set_enable`) |
| **SoC / SOC** | State of Charge — the storage's charge level (usually in %) |
| **SSD** | Solid-State Drive — preferred storage for LoxBerry/Docker hosts (vs. a slow SD card) |
| **VE** | Victron Energy — product family; **VE.Bus** among other things for ESS setpoints on the GX |
| **VI / VO** | Virtual Input / Virtual Output — Loxone blocks for reading resp. writing signals |
| **WP** | Wärmepumpe — heat pump (often spelled out in texts) |
| **WR** | Wechselrichter — inverter |

## Related Pages

- [Loxone Signals](loxone-signals.md) — read/write fields and Merker
- [EHAL-Com](../ui/ehal-com.md) — connection and mapping
- [OeMAG & Reference Market Value](oemag-referenzmarktwert.md) — feed-in/market terms
- [User Manual](../user-manual/Benutzer-Handbuch-Earnie.md) — user-facing starting point
