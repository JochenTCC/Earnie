# Smarthome-Backend wählen

Earnie spricht Anlagen über den **EHAL** (Earnie Hardware Access Layer) an. Derselbe Optimizer-Kern bleibt; gewechselt wird nur das **Smarthome-Backend** (`ehal.backend`) plus die jeweiligen Zugangsdaten und Feld-Mappings.

Auswahl/Erkennung: [Smarthome-Backend](../ui/smarthome-backend.md); Überblick und Debug danach: [EHAL-Com](../ui/ehal-com.md).

## Welcher Pfad?


| Backend                   | `ehal.backend`       | Typischer Einsatz                                     | Detail                                  |
| ------------------------- | -------------------- | ----------------------------------------------------- | --------------------------------------- |
| **Loxone** (Default)      | `loxone` (oder leer) | Bestehende Loxone-Anlage; Produktion über Loxone-EHAL | [Loxone-Anbindung](loxone-anbindung.md) |
| **Home Assistant + evcc** | `ha`                 | DACH-Gerätevolumen (Pfad A2 / B)                      | [Home Assistant + evcc](ha-evcc.md)     |
| **OpenEMS**               | `openems`            | Lab- / Industrie-Prototyp (**nicht** B2C-Default)     | [OpenEMS-Lab](openems-lab.md)           |


Offizielle DACH-Empfehlung für neue Setups ohne Loxone: **HA + evcc**. OpenEMS bleibt dokumentierter Validierungspfad.

## Umschalten



### Über die Oberfläche (empfohlen)

1. Streamlit: **Daemon Control → Smarthome-Backend**
2. Backend wählen — automatische Suche (mDNS/SSDP, optional OpenEMS-Portscan) oder manuell (Loxone / Home Assistant / OpenEMS)
3. Zugangsdaten speichern; bei HA zusätzlich Entity→EHAL-Mapping, bei Loxone Merker/`plant.ehal_bindings` (weiterhin auf **EHAL-Com**)

Die Auswahl schreibt `ehal.backend` in `config.json` und leert den Adapter-Cache.

### Manuell in `config.json`

Snippets unter `share/config/`:

- HA: `[ehal.ha.snippet.json](../../share/config/ehal.ha.snippet.json)`
- OpenEMS: `[ehal.openems.snippet.json](../../share/config/ehal.openems.snippet.json)`

Loxone-Zugangsdaten liegen in `config/.env` (`LOXONE_IP`, `LOXONE_USER`, `LOXONE_PASS`); Merker-Namen in `plant.ehal_bindings` / Hausprofil. Siehe [Loxone-Signale](../referenz/loxone-signals.md).

Nach dem Wechsel: Verbindung auf **EHAL-Com** (Live-Lesen / Verbindungstest) prüfen, bevor Silent-Modus ausgeschaltet wird.

## Was gleich bleibt — was neu gemappt werden muss

**Gleich (Kern):** Optimierung (MILP), Charts, Silent-/Live-Modus, Hausprofil-Szenarien — kein Core-Umbau nötig.

**Neu zuordnen je Hub:**


| Backend | Mapping                                                              |
| ------- | -------------------------------------------------------------------- |
| Loxone  | Merker ↔ EHAL-Felder (`plant.ehal_bindings`; Assistent auf EHAL-Com) |
| HA      | HA-Entities ↔ EHAL (`ehal.ha.entities`, optional `sign`)             |
| OpenEMS | REST-Komponenten (`ess0` / `evcs0` u. a. in `ehal.openems`)          |


## Weiterlesen

- [Smarthome-Backend](../ui/smarthome-backend.md) — Erkennung/Auswahl
- [EHAL-Com](../ui/ehal-com.md) — Live-Lesen/Schreiben, Mapping
- [Loxone-Anbindung](loxone-anbindung.md)
- [Home Assistant + evcc](ha-evcc.md)
- [OpenEMS-Lab](openems-lab.md)
- Entwickler-Spec (Englisch): [docs/spec/ehal.md](../spec/ehal.md)

