# Abbreviations

Short explanations of abbreviations and short forms used in the Earnie documentation and UI. The list is alphabetical and not exhaustive.

New entries come from terms used in the main user docs (handbook, UI docs).

| Abbreviation | Meaning |
| --------- | ----------- |
| **aWATTar** | Dynamic electricity tariff (spot/day-ahead); a frequent example in the docs |
| **B2C** | Business-to-Consumer – end-customer/household product (as opposed to lab/industrial use) |
| **BL** | Baseline – in chart 1 **SoC BL target**: reference run without a smart battery and without price-based load shifting |
| **CSV** | Comma-Separated Values – table file for load, PV and consumer power profiles |
| **DACH** | Germany, Austria, Switzerland – region for the HA+evcc recommendation |
| **DSGVO** | GDPR – General Data Protection Regulation (EU) |
| **EFM** | Energieflussmonitor (Loxone) – Energy Flow Monitor: meter and power statistics for import and mapping |
| **EHAL** | Earnie Hardware Access Layer – unified interface between the optimizer and the smarthome backend |
| **EHAL-Com** | Streamlit page **EHAL-Com** (live read/write, mapping) |
| **EPEX** | European Power Exchange – day-ahead market prices (the basis for many spot tariffs) |
| **ESS** | Energy Storage System – battery storage (power, SoC, mode) |
| **EV** | Electric Vehicle |
| **EVCS** | Electric Vehicle Charging Station – wallbox / charging station |
| **evcc** | Open-source charging and PV control; sidecar under Home Assistant (DACH path) |
| **FTP** | File Transfer Protocol – historically used for Miniserver logs; Earnie uses CSV/energy monitor data instead |
| **GHCR** | GitHub Container Registry – source of the official Earnie container images |
| **Greenfield / Default** | User docs say **Default** (template/import path, Merker prefix `Earnie_*`). "Greenfield" still appears in file names (`greenfield_device_map.json`) and older texts; the local dev stack often uses port **8502** |
| **GX** | Victron GX (e.g. Cerbo) – device hub, often connected via Modbus TCP |
| **HA** | Home Assistant – smarthome backend (often together with **evcc**) |
| **HITL** | Human-in-the-Loop – manual mapping and confirmation in the UI (no fully automatic LLM mapping) |
| **HK** | Hauskonfigurator – Streamlit area for house and profile configuration |
| **kWp** | Kilowatt-peak – installed PV nominal power |
| **LoxAPP3** | Loxone configuration/app export (`LoxAPP3.json`) – used e.g. for EFM meters and import |
| **LoxBerry** | Mini-PC/Raspberry Pi plugin host in the Loxone ecosystem; the Earnie plugin is a Docker wrapper |
| **LXC** | Linux Container – typical Proxmox environment for Docker Compose |
| **MCP** | Model Context Protocol – in the docs: Loxone MCP (currently not offered in the UI) |
| **MILP** | Mixed-Integer Linear Programming – the mathematical optimization method behind the Earnie plan |
| **Modbus** | Fieldbus/TCP protocol for inverters, Victron GX, wallboxes, etc.; only one writing owner per bus |
| **NAS** | Network Attached Storage – e.g. Synology as a Docker host |
| **OeMAG** | Austrian settlement agency for green electricity – context for feed-in and market prices |
| **OpenEMS** | Open Energy Management System – lab/industrial backend (`ehal.backend=openems`) |
| **PV** | Photovoltaic |
| **RefMarkt** | Referenzmarktwert (E-Control) – reference market value, used for PV feed-in pricing |
| **REST** | Representational State Transfer – HTTP API (e.g. the HA EHAL adapter) |
| **SA₁ / SA₂** | Sunset anchors – bounds of the live planning horizon (sunset to sunset / related segments) |
| **SaaS** | Software as a Service – commercial cloud use (not permitted without consent under the license) |
| **SE** | Szenario-Explorer – Scenario Explorer: annual and long-term comparisons and what-if calculations |
| **SG-Ready** | Smart-Grid-Ready – heat pump enable/tariff signal (in EHAL often via `set_enable`) |
| **SoC / SOC** | State of Charge – the charge level of the storage (usually in %) |
| **SSD** | Solid-State Drive – preferred storage for LoxBerry/Docker hosts (instead of a slow SD card) |
| **VE** | Victron Energy – product family; **VE.Bus** is used, among other things, for ESS setpoints on the GX |
| **VI / VO** | Virtual Input / Virtual Output – Loxone blocks for reading and writing signals, respectively |
| **WP** | Wärmepumpe – heat pump (often spelled out in texts) |
| **WR** | Wechselrichter – inverter |

## Related Pages

- [Loxone Signals](loxone-signals.md) – read/write fields and Merker
- [EHAL-Com](../ui/ehal-com.md) – connection and mapping
- [OeMAG & Reference Market Value](oemag-referenzmarktwert.md) – feed-in and market terms
- [User Manual](../user-manual/Benutzer-Handbuch-Earnie.md) – user-facing starting point
