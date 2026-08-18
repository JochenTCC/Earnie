# Smarthome-Backend wählen

Earnie spricht die Anlage über den **EHAL** (Earnie Hardware Access Layer) an. Der Optimizer-Kern bleibt dabei immer derselbe; gewechselt wird nur das **Smarthome-Backend** (`ehal.backend`) zusammen mit den jeweiligen Zugangsdaten und Feld-Mappings.

Auswahl und Erkennung des Backends sind auf der Seite [Smarthome-Backend](../ui/smarthome-backend.md) beschrieben; den Überblick und die Live-Diagnose danach liefert [EHAL-Com](../ui/ehal-com.md).

## Welcher Pfad?


| Backend                   | `ehal.backend`       | Typischer Einsatz                                     | Detail                                  |
| ------------------------- | -------------------- | ----------------------------------------------------- | --------------------------------------- |
| **Loxone** (Default)      | `loxone` (oder leer) | Bestehende Loxone-Anlage; Produktion über Loxone-EHAL | [Loxone-Anbindung](loxone-anbindung.md) |
| **Home Assistant + evcc** | `ha`                 | DACH-Gerätevolumen (Pfad A2 / B)                      | [Home Assistant + evcc](ha-evcc.md)     |
| **OpenEMS**               | `openems`            | Lab- / Industrie-Prototyp (**nicht** B2C-Default)     | [OpenEMS-Lab](openems-lab.md)           |


Für neue Setups ohne bestehende Loxone-Anlage lautet die offizielle DACH-Empfehlung **HA + evcc**. OpenEMS bleibt ein dokumentierter Validierungspfad.

## Umschalten



### Über die Oberfläche (empfohlen)

1. In Streamlit zur Seite **Daemon Control → Smarthome-Backend** wechseln.
2. Das Backend wählen — entweder über die automatische Suche (mDNS/SSDP, optional mit OpenEMS-Portscan) oder manuell (Loxone, Home Assistant oder OpenEMS).
3. Die Zugangsdaten speichern. Bei Home Assistant folgt danach das Entity→EHAL-Mapping, bei Loxone die Merker- bzw. `plant.ehal_bindings`-Zuordnung — beides weiterhin auf **EHAL-Com**.

Die Auswahl schreibt `ehal.backend` in `config.json` und leert dabei den Adapter-Cache.

### Manuell in `config.json`

Für Home Assistant und OpenEMS liegen passende Snippets unter `share/config/`:

- HA: `[ehal.ha.snippet.json](../../share/config/ehal.ha.snippet.json)`
- OpenEMS: `[ehal.openems.snippet.json](../../share/config/ehal.openems.snippet.json)`

Die Loxone-Zugangsdaten liegen dagegen in `config/.env` (`LOXONE_IP`, `LOXONE_USER`, `LOXONE_PASS`), die Merker-Namen stehen in `plant.ehal_bindings` bzw. im Hausprofil. Details dazu: [Loxone-Signale](../referenz/loxone-signals.md).

Nach jedem Wechsel sollte die Verbindung auf **EHAL-Com** (Live-Lesen / Verbindungstest) geprüft werden, bevor der Silent-Modus ausgeschaltet wird.

## Was gleich bleibt — was neu gemappt werden muss

Der Kern bleibt beim Wechsel unverändert: Optimierung (MILP), Charts, Silent-/Live-Modus und die Hausprofil-Szenarien brauchen keinen Core-Umbau.

Neu zugeordnet werden muss dagegen je Hub Folgendes:


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

