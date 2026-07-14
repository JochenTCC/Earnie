# Loxone-Kommunikation (Debug-Seite)

Die Seite **Loxone-Kommunikation** unter **Echtzeit-Umgebung** zeigt den Live-Zustand aller konfigurierten Loxone-Merker und die Schreibvorgänge des letzten Produktiv-Laufs von `main.py`. Sie dient vor allem der Abnahme beim [NAS Live-Cutover (1.99)](../einrichtung/nas-live-cutover-1.99.md).

## Aufruf

1. Streamlit starten: `python -m scripts.run_streamlit`
2. Navigation: **Echtzeit-Umgebung → Loxone-Kommunikation**

Die Seite ist auch während der Einrichtung sichtbar (eingeschränkte Navigation), sobald Loxone-Zugangsdaten in `config/.env` hinterlegt sind.

## Bereiche der Seite

### Statusleiste

- **Silent-Modus aktiv:** Steuerwerte werden nicht an den Miniserver geschrieben; nur Sollwerte werden angezeigt.
- **Live-Modus:** `main.py` sendet Steuerwerte an Loxone.
- **Letzter main.py-Lauf:** Zeitstempel und Alter des letzten erfolgreichen Optimierungsdurchlaufs.

### Live-Lesen

Alle aus `config.json` abgeleiteten Loxone-Eingänge werden periodisch (Standard: alle 10 Sekunden) vom Miniserver gelesen.

| Spalte | Bedeutung |
|--------|-----------|
| Label | Bezeichnung aus der Konfiguration (z. B. Batterie-SoC, Verbraucher-Leistung) |
| IO-Name | Merkername in Loxone |
| Status | OK, Warnung oder Fehler |
| Detail | Rohwert oder parsebarer Wert |
| Zuletzt gelesen | Zeitpunkt des letzten Abrufs auf dieser Seite |

Mit **Loxone-Merker testen** starten Sie eine einmalige Prüfung aller konfigurierten Merker (Ergebnis als farbige Meldungen). Die Tabelle darunter wird zusätzlich automatisch aktualisiert (Standard: alle 10 Sekunden).

Lesefehler bedeuten: Merkername falsch, Miniserver nicht erreichbar, oder Wert nicht parsebar — nicht dass `main.py` fehlgeschlagen ist.

### Letzte Schreibvorgänge

Daten stammen aus `runtime/optimizer_run_state.json` des **letzten** `main.py`-Laufs.

**Live-Modus** (`runtime/local_settings.json`: `"loxone_silent_mode": false` oder Eintrag entfernt):

| Spalte | Bedeutung |
|--------|-----------|
| IO-Name | Virtueller Eingang in Loxone |
| Wert | Gesendeter numerischer Wert |
| Erfolg | Ja/Nein — HTTP-Schreibvorgang an den Miniserver |
| Gesendet um | Zeitstempel des einzelnen Schreibvorgangs |

**Silent-Modus** (`"loxone_silent_mode": true`):

- Keine Schreibbestätigungen — es wurden keine HTTP-Schreibvorgänge ausgeführt.
- Tabelle **Sollwert (nicht gesendet)** zeigt die geplanten Werte aus `loxone_sent` des letzten Laufs.

### Expander: Lese-Snapshot aus run_state

Kompakte JSON-Ansicht der beim letzten Lauf gespeicherten Aggregatwerte (SoC, Flex-Leistungen, Event-Trigger, Verbrauchs-Snapshot).

## Silent-Modus vs. Live-Modus

| | Silent-Modus | Live-Modus |
|---|--------------|------------|
| Lesen | Immer aktiv (auch auf dieser Seite) | Immer aktiv |
| Schreiben durch `main.py` | Nein | Ja |
| Schreib-Tabelle | Nur Sollwerte | Wert + Erfolg + Zeitstempel |
| Typischer Einsatz | Migrations-Test, paralleler Legacy-Betrieb | Produktiv nach Cutover |

Silent-Modus wird in `runtime/local_settings.json` gesetzt (Priorität vor veraltetem `system.loxone_silent_mode` in `config.json`). Standard ohne Datei: **Silent-Modus an**.

## Cutover-Checkliste

Nach Deaktivierung des Silent-Modus und Neustart von `main.py`:

1. **Live-Lesen:** alle relevanten Merker Status **OK**
2. **Letzte Schreibvorgänge:** alle Einträge **Erfolg = Ja**
3. **Cockpit / Sankey:** Soll-Werte passen zu Live (siehe [Charts & Panels](charts.md))

Bei Schreibfehlern: Netzwerk, Merkernamen in `config.json`, Miniserver-Logs prüfen; Details auch in `runtime/earnie.log`.

## Siehe auch

- [Loxone-Anbindung](../einrichtung/loxone-anbindung.md)
- [Loxone-Signale](../referenz/loxone-signale.md)
- [Betrieb](../einrichtung/betrieb.md) — `main.py`-Takt und Laufzeitdateien
- CLI-Alternative: `python -m scripts.verify_loxone_setup`
