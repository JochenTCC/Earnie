# EHAL-Com (Anbindung & Debug)

Die Seite **EHAL-Com** unter **Daemon Control** ist die zentrale Stelle für Smarthome-Anbindung und Live-Debug: **Loxone**, **Home Assistant (EHAL)** oder **OpenEMS**. Sie zeigt Live-Lesen / Live-Schreiben des letzten Produktiv-Laufs von `main.py` und erlaubt die Bearbeitung von Anlagen-Merkern / Event-Triggern (Loxone-Pfad).

## Aufruf

1. Streamlit starten: `python -m scripts.run_streamlit`
2. Navigation: **Daemon Control → EHAL-Com**

Zugangsdaten werden **nicht** mehr in der Sidebar erfasst, sondern unter **Anbindung** auf dieser Seite (oder in der Ersteinrichtung beim ersten Start).

## Anbindung

Oben wählen Sie das **Smarthome-Backend**:

| Backend | Speicherung | Formular |
|---------|-------------|----------|
| Loxone | `config/.env` (`LOXONE_IP` / `USER` / `PASS`) | Miniserver-IP, Benutzer, Passwort |
| Home Assistant | `config.json` → `ehal.ha` | URL, Long-Lived Token; darunter Entity→EHAL-Mapping |
| OpenEMS | `config.json` → `ehal.openems` | Base-URL, Benutzer, Passwort, ESS-/EVCS-Komponenten |

`ehal.backend` steuert den Live-Pfad in `main.py` (Loxone-HTTP vs. EHAL-REST).

## Live-Cockpit noch gesperrt (Greenfield)

Nach abgeschlossener Planungs-Konfiguration erscheint **Szenario-Explorer**, aber **Live-Cockpit** bleibt ausgeblendet, solange die Anbindung für den Live-Betrieb nicht vollständig ist. Nutzen Sie **Anbindung**, **Live-Lesen** und die Verbindungstests auf dieser Seite.

## Bereiche der Seite

### Statusleiste

- **Silent-Modus:** Steuerwerte werden nicht an den Hub geschrieben; nur Sollwerte.
- **Live-Modus / HA-EHAL / OpenEMS-EHAL:** `main.py` sendet an den gewählten Hub.
- **Letzter main.py-Lauf:** Zeitstempel und Alter.

### Live-Lesen

**Loxone:** konfigurierte Merker periodisch vom Miniserver (Tabelle + **Smarthome-Merker testen**).

**HA / OpenEMS:** EHAL-Telemetrie über REST (Tabelle der EHAL-Felder, optional Live-Leistung in kW) sowie Button **Verbindung testen**.

### Live-Schreiben

Daten aus `runtime/optimizer_run_state.json` des letzten `main.py`-Laufs.

- **Loxone:** `loxone_writes` (IO-Name, Wert, Erfolg, Zeit) bzw. Silent: `loxone_sent`.
- **HA / OpenEMS:** `ehal_writes` (EHAL-Feld, Wert, Erfolg, Zeit, Meldung); Fehlerbanner aus `runtime/ehal_write_error.json`.

### HA Entity → EHAL Mapping

Nur bei Backend **Home Assistant**: Entities scannen, Telemetrie-/Setpoint-Felder zuweisen, speichern. Details: [Home Assistant + evcc](../einrichtung/ha-evcc.md).

### Anlagen-Merker / Event-Trigger

Loxone-Rollen (`loxone_blocks`, `system.event_triggers`) — für Legacy-Live und künftiges Loxone-EHAL. Bei HA/OpenEMS im Expander (standardmäßig zugeklappt). Siehe [Loxone-Signale](../referenz/loxone-signale.md).

## Silent-Modus vs. Live-Modus

| | Silent-Modus | Live-Modus |
|---|--------------|------------|
| Lesen | Immer aktiv (auch auf dieser Seite) | Immer aktiv |
| Schreiben durch `main.py` | Nein | Ja |
| Schreib-Tabelle | Nur Sollwerte | Wert + Erfolg + Zeitstempel |
| Typischer Einsatz | Tests, paralleler Legacy-Betrieb | Produktiv nach Cutover |

Silent-Modus: `runtime/local_settings.json` → `"loxone_silent_mode"` (Priorität vor `system.loxone_silent_mode`). Standard ohne Datei: **Silent an**.

## Cutover-Checkliste

1. **Anbindung** gespeichert und Backend gewählt  
2. **Live-Lesen:** Merker bzw. EHAL-Telemetrie **OK**  
3. **Live-Schreiben:** alle Einträge **Erfolg = Ja** (Silent zuvor deaktivieren)  
4. **Cockpit / Sankey:** Soll-Werte passen zu Live ([Charts & Panels](charts.md))

## Siehe auch

- [Loxone-Anbindung](../einrichtung/loxone-anbindung.md)
- [Home Assistant + evcc](../einrichtung/ha-evcc.md)
- [OpenEMS-Lab](../einrichtung/openems-lab.md)
- [Loxone-Signale](../referenz/loxone-signale.md)
- [Betrieb](../einrichtung/betrieb.md)
- CLI (Loxone): `python -m scripts.verify_loxone_setup`
