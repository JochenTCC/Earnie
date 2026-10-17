# Smarthome-Backend wählen

Earnie spricht die Anlage über den **EHAL** (Earnie Hardware Access Layer) an. Der Optimizer-Kern bleibt dabei immer derselbe. Gewechselt werden nur das **Smarthome-Backend** (`ehal.backend`), die zugehörigen Zugangsdaten und die Feld-Mappings.

Auswahl und Erkennung des Backends beschreibt die Seite [Smarthome-Backend](../ui/smarthome-backend.md). Den Überblick und die Live-Diagnose danach liefert [EHAL-Com](../ui/ehal-com.md).

## Welches Backend passt?

| Backend                   | `ehal.backend`       | Typischer Einsatz                                     | Detail                                  |
| ------------------------- | -------------------- | ----------------------------------------------------- | --------------------------------------- |
| **Loxone** (Default)      | `loxone` (oder leer) | Bestehende Loxone-Anlage; Produktion über Loxone-EHAL | [Loxone-Anbindung](loxone-anbindung.md) |
| **Home Assistant + evcc** | `ha`                 | DACH-Gerätevolumen (Pfad A2 / B)                      | [Home Assistant + evcc](ha-evcc.md)     |
| **OpenEMS**               | `openems`            | Lab- bzw. Industrie-Prototyp, kein B2C-Default        | [OpenEMS-Lab](openems-lab.md)           |

Für neue Setups ohne bestehende Loxone-Anlage lautet die offizielle DACH-Empfehlung **HA + evcc**. OpenEMS bleibt ein dokumentierter Validierungspfad.

## Umschalten

### Über die Oberfläche (empfohlen)

1. In Streamlit die Seite **Daemon Control → Smarthome-Backend** öffnen.
2. Das Backend wählen: entweder über die automatische Suche (mDNS/SSDP, optional mit OpenEMS-Portscan) oder manuell (Loxone, Home Assistant oder OpenEMS).
3. Die Zugangsdaten speichern. Danach folgt die Zuordnung auf **EHAL-Com**: bei Home Assistant das Entity→EHAL-Mapping (`plant.ehal_bindings` / `consumers[].ehal_bindings`), bei Loxone die Merker-Zuordnung.

Die Auswahl schreibt `ehal.backend` in `config.json` und leert dabei den Adapter-Cache.

### Manuell in `config.json` / `.env`

Für Home Assistant und OpenEMS liegen passende Snippets unter `share/config/`:

- **HA:** [ehal.ha.snippet.json](../../share/config/ehal.ha.snippet.json) enthält `ehal.backend` und `sign`; URL und Token gehören in `config/.env`.
- **OpenEMS:** [ehal.openems.snippet.json](../../share/config/ehal.openems.snippet.json).

Die Zugangsdaten für Loxone und HA liegen in `config/.env` (`LOXONE_IP` / `LOXONE_USER` / `LOXONE_PASS` bzw. `EHAL_HA_BASE_URL` / `EHAL_HA_TOKEN`). Merker- und Entity-Namen stehen in `plant.ehal_bindings` bzw. im Hausprofil. Details: [Loxone-Signale](../referenz/loxone-signals.md), [Home Assistant + evcc](ha-evcc.md).

> **Hinweis:** Nach jedem Wechsel die Verbindung auf **EHAL-Com** prüfen (Live-Lesen bzw. Verbindungstest), bevor der Silent-Modus ausgeschaltet wird.

## Was bleibt gleich, was wird neu zugeordnet?

Beim Wechsel bleibt der Kern unverändert. Optimierung (MILP), Charts, Silent-/Live-Modus und die Hausprofil-Szenarien brauchen keinen Core-Umbau.

Neu zugeordnet werden je Hub folgende Mappings:

| Backend | Mapping                                                              |
| ------- | -------------------------------------------------------------------- |
| Loxone  | Merker ↔ EHAL-Felder (`plant.ehal_bindings`; Assistent auf EHAL-Com) |
| HA      | HA-Entities ↔ EHAL (`plant.ehal_bindings` / `consumers[].ehal_bindings`; optional `sign` in `ehal.ha`) |
| OpenEMS | REST-Komponenten (`ess0` / `evcs0` u. a. in `ehal.openems`)          |

## Weiterlesen

- [Smarthome-Backend](../ui/smarthome-backend.md) – Erkennung und Auswahl
- [EHAL-Com](../ui/ehal-com.md) – Live-Lesen und -Schreiben, Mapping
- [Loxone-Anbindung](loxone-anbindung.md)
- [Home Assistant + evcc](ha-evcc.md)
- [OpenEMS-Lab](openems-lab.md)
- Entwickler-Spec (Englisch): [docs/referenz/ehal.md](../referenz/ehal.md)
