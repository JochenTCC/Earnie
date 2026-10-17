# Smarthome-Backend wählen

Earnie spricht die Anlage über den **EHAL** (Earnie Hardware Access Layer) an. Die Optimierung bleibt dabei immer dieselbe. Beim Wechsel ändern sich nur drei Dinge: das **Smarthome-Backend** (`ehal.backend`), die zugehörigen Zugangsdaten und die Feld-Mappings.

Wie Earnie Backends erkennt und wie die Auswahl funktioniert, beschreibt die Seite [Smarthome-Backend](../ui/smarthome-backend.md). Den Überblick und die Live-Diagnose danach liefert [EHAL-Com](../ui/ehal-com.md).

## Welches Backend passt?

| Backend                   | `ehal.backend`       | Typischer Einsatz                                              | Detail                                  |
| ------------------------- | -------------------- | -------------------------------------------------------------- | --------------------------------------- |
| **Loxone** (Standard)     | `loxone` (oder leer) | Bestehende Loxone-Anlage; Produktivbetrieb über Loxone-EHAL    | [Loxone-Anbindung](loxone-anbindung.md) |
| **Home Assistant + evcc** | `ha`                 | Breites Geräteangebot im DACH-Raum (Pfad A2 / B)               | [Home Assistant + evcc](ha-evcc.md)     |
| **OpenEMS**               | `openems`            | Lab- bzw. Industrie-Prototyp, kein Standard für Privathaushalte | [OpenEMS-Lab](openems-lab.md)           |

Für neue Setups ohne bestehende Loxone-Anlage lautet die offizielle Empfehlung für den DACH-Raum **HA + evcc**. OpenEMS bleibt ein dokumentierter Validierungspfad.

## Umschalten

### Über die Oberfläche (empfohlen)

1. In der Oberfläche die Seite **Daemon Control → Smarthome-Backend** öffnen.
2. Das Backend wählen. Dafür gibt es zwei Wege:
   - **Automatische Suche:** per mDNS/SSDP, optional mit OpenEMS-Portscan.
   - **Manuelle Auswahl:** Loxone, Home Assistant oder OpenEMS.
3. Die Zugangsdaten speichern. Danach folgt die Zuordnung auf **EHAL-Com**:
   - **Home Assistant:** das Entity→EHAL-Mapping (`plant.ehal_bindings` / `batteries[].ehal_bindings` / `consumers[].ehal_bindings`).
   - **Loxone:** die Merker-Zuordnung.

Die Auswahl schreibt `ehal.backend` in `config.json` und leert dabei den Adapter-Cache.

### Manuell in `config.json` / `.env`

Für Home Assistant und OpenEMS liegen passende Snippets unter `share/config/`:

- **HA:** [ehal.ha.snippet.json](../../share/config/ehal.ha.snippet.json) enthält `ehal.backend` und `sign`. URL und Token gehören in `config/.env`.
- **OpenEMS:** [ehal.openems.snippet.json](../../share/config/ehal.openems.snippet.json).

Die Zugangsdaten für Loxone und HA liegen in `config/.env`:

- **Loxone:** `LOXONE_IP` / `LOXONE_USER` / `LOXONE_PASS`.
- **HA:** `EHAL_HA_BASE_URL` / `EHAL_HA_TOKEN`.

Merker- und Entity-Namen stehen in `plant.ehal_bindings` / `batteries[].ehal_bindings` / `consumers[].ehal_bindings` (Hausprofil bzw. `components.json`). Details: [Loxone-Signale](../referenz/loxone-signals.md), [Home Assistant + evcc](ha-evcc.md).

> **Hinweis:** Nach jedem Wechsel die Verbindung auf **EHAL-Com** prüfen (Live-Lesen bzw. Verbindungstest), bevor der Silent-Modus ausgeschaltet wird.

## Was bleibt gleich, was wird neu zugeordnet?

Beim Wechsel bleibt alles Übrige unverändert. Optimierung (MILP), Charts, die Betriebsmodi Silent / Loud und die Hausprofil-Szenarien funktionieren ohne Umbau weiter.

Neu zugeordnet werden je Backend folgende Mappings:

| Backend | Mapping                                                              |
| ------- | -------------------------------------------------------------------- |
| Loxone  | Merker ↔ EHAL-Felder (`plant` / `batteries[]` / `consumers[].ehal_bindings`; Assistent auf EHAL-Com) |
| HA      | HA-Entities ↔ EHAL (`plant` / `batteries[]` / `consumers[].ehal_bindings`; optional `sign` in `ehal.ha`) |
| OpenEMS | REST-Komponenten (`ess0` / `evcs0` u. a. in `ehal.openems`)          |

## Weiterlesen

- [Smarthome-Backend](../ui/smarthome-backend.md) – Erkennung und Auswahl
- [EHAL-Com](../ui/ehal-com.md) – Live-Lesen und -Schreiben, Mapping
- [Loxone-Anbindung](loxone-anbindung.md)
- [Home Assistant + evcc](ha-evcc.md)
- [OpenEMS-Lab](openems-lab.md)
- Entwickler-Spec (Englisch): [docs/referenz/ehal.md](../referenz/ehal.md)
