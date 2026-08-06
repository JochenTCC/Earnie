# Abkürzungen

Kurze Erklärungen zu Abkürzungen und Kurzformen in der Earnie-Dokumentation und Oberfläche. Alphabetisch; ohne Anspruch auf Vollständigkeit.

Quellen der Ergänzung (Scan): Einträge aus `backlog/Doc-Review-Checklist.md` (Priority-1-Anwenderdocs).

| Abkürzung | Bedeutung |
| --------- | --------- |
| **aWATTar** | Dynamischer Stromtarif (Spot/Day-Ahead); häufiges Beispiel in der Doku |
| **B2C** | Business-to-Consumer — Endkunden-/Haushaltsprodukt (vs. Lab-/Industrie) |
| **BL** | Baseline — in Chart 1 **SoC BL Ziel**: Gegenprobe ohne smarte Batterie / ohne Preis-Lastverschiebung |
| **CSV** | Comma-Separated Values — Tabellendatei für Last-/PV-/Verbraucher-Leistungsprofile |
| **DACH** | Deutschland, Österreich, Schweiz — Region für HA+evcc-Empfehlung |
| **DSGVO** | Datenschutz-Grundverordnung (EU) |
| **EFM** | Energieflussmonitor (Loxone) — Zähler-/Leistungsstatistik für Import und Mapping |
| **EHAL** | Earnie Hardware Access Layer — einheitliche Schnittstelle zwischen Optimizer und Smarthome-Backend |
| **EHAL-Com** | Streamlit-Seite **Anbindung & Debug** (Live-Lesen/Schreiben, Mapping, Backend-Wahl) |
| **EPEX** | European Power Exchange — Day-Ahead-Marktpreise (Basis vieler Spot-Tarife) |
| **ESS** | Energy Storage System — Batteriespeicher (Leistung, SoC, Modus) |
| **EV** | Electric Vehicle — E-Auto |
| **EVCS** | Electric Vehicle Charging Station — Wallbox / Ladestation |
| **evcc** | Open-Source-Lade-/PV-Steuerung; Sidecar unter Home Assistant (DACH-Pfad) |
| **FTP** | File Transfer Protocol — historisch Miniserver-Logs; Earnie nutzt CSV/Energiemonitor statt FTP |
| **GHCR** | GitHub Container Registry — Quelle der offiziellen Earnie-Container-Images |
| **Greenfield / Default** | In Anwenderdocs: **Default** (Vorlagen-/Import-Pfad, Merker-Prefix `Earnie_*`). „Greenfield“ noch in Dateinamen (`greenfield_device_map.json`) und älteren Texten; lokaler Dev-Stack oft Port **8502** |
| **GX** | Victron GX (z. B. Cerbo) — Gerätehub, oft über Modbus-TCP |
| **HA** | Home Assistant — Smarthome-Backend (oft zusammen mit **evcc**) |
| **HITL** | Human-in-the-Loop — manuelles Mapping/Bestätigen in der Oberfläche (kein vollautomatisches LLM-Mapping) |
| **HK** | Hauskonfigurator — Streamlit-Bereich zur Haus-/Profilkonfiguration |
| **kWp** | Kilowatt-peak — installierte PV-Nennleistung |
| **LoxAPP3** | Loxone-Konfigurations-/App-Export (`LoxAPP3.json`) — u. a. für EFM-Zähler und Import |
| **LoxBerry** | Mini-PC-/Raspberry-Plugin-Host im Loxone-Umfeld; Earnie-Plugin als Docker-Wrapper |
| **LXC** | Linux Container — typisch Proxmox-Umgebung für Docker-Compose |
| **MCP** | Model Context Protocol — in der Doku: Loxone-MCP (derzeit nicht in der UI angeboten) |
| **MILP** | Mixed-Integer Linear Programming — mathematisches Optimierungsverfahren hinter dem Earnie-Plan |
| **Modbus** | Feldbus-/TCP-Protokoll für WR, Victron GX, Wallboxen u. a.; nur ein schreibender Owner pro Bus |
| **NAS** | Network Attached Storage — z. B. Synology als Docker-Host |
| **OeMAG** | Österreichische Abwicklungsstelle für Ökostrom — Einspeise-/Marktpreis-Kontext |
| **OpenEMS** | Open Energy Management System — Lab-/Industrie-Backend (`ehal.backend=openems`) |
| **PV** | Photovoltaik |
| **RefMarkt** | Referenzmarktwert (E-Control) — Marktpreis-Bezug für PV-Einspeisung |
| **REST** | Representational State Transfer — HTTP-API (z. B. HA-EHAL-Adapter) |
| **SA₁ / SA₂** | Sunset-Anker — Grenzen des Live-Planungshorizonts (Sonnenuntergang zu Sonnenuntergang / verwandte Segmente) |
| **SaaS** | Software as a Service — kommerzielle Cloud-Nutzung (laut Lizenz ohne Zustimmung nicht erlaubt) |
| **SE** | Szenario-Explorer — Jahres-/Langzeitvergleiche und Was-wäre-wenn-Rechnung |
| **SG-Ready** | Smart-Grid-Ready — Wärmepumpen-Freigabe-/Tarifsignal (in EHAL oft über `set_enable`) |
| **SoC / SOC** | State of Charge — Ladezustand des Speichers (meist in %) |
| **SSD** | Solid-State Drive — bevorzugter Speicher für LoxBerry/Docker-Hosts (vs. langsame SD-Karte) |
| **VE** | Victron Energy — Produktfamilie; **VE.Bus** u. a. für ESS-Setpoints am GX |
| **VI / VO** | Virtual Input / Virtual Output — Loxone-Bausteine für Lesen bzw. Schreiben von Signalen |
| **WP** | Wärmepumpe (in Texten oft ausgeschrieben) |
| **WR** | Wechselrichter |

## Verwandte Seiten

- [Loxone-Signale](loxone-signale.md) — Lesen-/Schreib-Felder und Merker
- [EHAL-Com](../ui/ehal-com.md) — Anbindung und Mapping
- [OeMAG & Referenzmarktwert](oemag-referenzmarktwert.md) — Einspeise-/Marktbegriffe
- [Benutzer-Handbuch](../user-manual/Benutzer-Handbuch-Earnie.md) — Einstieg aus Anwendersicht
