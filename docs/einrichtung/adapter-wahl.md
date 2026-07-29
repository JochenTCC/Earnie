# Smarthome-Adapter wählen

Earnie spricht Anlagen über den **EHAL** (Earnie Hardware Access Layer) an. Derselbe Optimizer-Kern bleibt; gewechselt wird nur das **Smarthome-Backend** (`ehal.backend`) plus die jeweiligen Zugangsdaten und Feld-Mappings.

Überblick und Debug: [EHAL-Com](../ui/ehal-com.md).

## Welcher Pfad?

| Backend | `ehal.backend` | Typischer Einsatz | Detail |
|---------|----------------|-------------------|--------|
| **Loxone** (Default) | `loxone` (oder leer) | Bestehende Loxone-Anlage; Produktion über Loxone-EHAL | [Loxone-Anbindung](loxone-anbindung.md) |
| **Home Assistant + evcc** | `ha` | DACH-Gerätevolumen (Pfad A2 / B) | [Home Assistant + evcc](ha-evcc.md) |
| **OpenEMS** | `openems` | Lab- / Industrie-Prototyp (**nicht** B2C-Default) | [OpenEMS-Lab](openems-lab.md) |

Offizielle DACH-Empfehlung für neue Setups ohne Loxone: **HA + evcc**. OpenEMS bleibt dokumentierter Validierungspfad.

## Umschalten

### Über die Oberfläche (empfohlen)

1. Streamlit: **Daemon Control → EHAL-Com → Anbindung**
2. Backend wählen (Loxone / Home Assistant / OpenEMS)
3. Zugangsdaten speichern; bei HA zusätzlich Entity→EHAL-Mapping, bei Loxone Merker/`plant.ehal_bindings`

Die Auswahl schreibt `ehal.backend` in `config.json` und leert den Adapter-Cache.

### Manuell in `config.json`

Snippets unter `share/config/`:

- HA: [`ehal.ha.snippet.json`](../../share/config/ehal.ha.snippet.json)
- OpenEMS: [`ehal.openems.snippet.json`](../../share/config/ehal.openems.snippet.json)

Loxone-Zugangsdaten liegen in `config/.env` (`LOXONE_IP`, `LOXONE_USER`, `LOXONE_PASS`); Merker-Namen in `plant.ehal_bindings` / Hausprofil (Legacy optional `loxone_blocks`). Siehe [Loxone-Signale](../referenz/loxone-signale.md).

Nach dem Wechsel: Verbindung auf **EHAL-Com** (Live-Lesen / Verbindungstest) prüfen, bevor Silent-Modus ausgeschaltet wird.

## Was gleich bleibt — was neu gemappt werden muss

**Gleich (Kern):** Optimierung (MILP), Charts, Silent-/Live-Modus, Hausprofil-Szenarien — kein Core-Umbau nötig.

**Neu zuordnen je Hub:**

| Backend | Mapping |
|---------|---------|
| Loxone | Merker ↔ EHAL-Felder (`plant.ehal_bindings`; Assistent auf EHAL-Com) |
| HA | HA-Entities ↔ EHAL (`ehal.ha.entities`, optional `sign`) |
| OpenEMS | REST-Komponenten (`ess0` / `evcs0` u. a. in `ehal.openems`) |

## Grenzen (Loxone-Extras)

Flexible Verbraucher (Freigaben, Wallbox-Leistung über Flex-Pfad) sowie Huawei-Extras (`target_soc`, `control_cmd`) bleiben **Loxone-spezifisch** über `loxone_client`. Bei HA/OpenEMS schreibt Earnie die EHAL-M1-Setpoints (ESS-Limits, EVCS-Maxstrom); eine 1:1-Flex-Parität gibt es dort noch nicht.

## Weiterlesen

- [EHAL-Com](../ui/ehal-com.md) — Anbindung, Live-Lesen/Schreiben
- [Loxone-Anbindung](loxone-anbindung.md)
- [Home Assistant + evcc](ha-evcc.md)
- [OpenEMS-Lab](openems-lab.md)
- Entwickler-Spec (Englisch): [docs/spec/ehal.md](../spec/ehal.md)
