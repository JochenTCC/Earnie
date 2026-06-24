# Betriebsmodi

Die Streamlit-App bietet drei Modi (Sidebar: **Betriebsmodus**). In Produktion können Modi per Umgebungsvariable eingeschränkt werden: `ENERGY_OPTIMIZER_UI_MODES=live` (siehe [Betrieb](../einrichtung/betrieb.md)).

## Echtzeit

**Zweck:** Cockpit für den laufenden Betrieb und die **24-Stunden-Vorhersage** synchron zum letzten `main.py`-Durchlauf.

**Datenquellen:**

- Live: Loxone (SOC, Leistungen, Sankey)
- Simulation: aWATTar-Preise, Verbrauchs-/PV-Profile, optional Live-Snapshot der aktuellen Stunde
- Stunde 0 der Simulation = Werte aus dem **Produktiv-Durchlauf** (`optimizer_run_state.json`), sofern zum aktuellen Viertelstunden-Slot passend

**Sidebar:** PV-, Batterie- und Einspeiseparameter editierbar; adaptives PV-Tuning (Korrekturfaktor).

**Panels:** Einsparungs-Metriken, Charts, Sankey, Produktiv-Durchlauf, Optimierungs-Historie, Countdown — Details in [Charts & Panels](charts.md).

## Historischer Tag

**Zweck:** Einen **vergangenen Kalendertag** mit gespeicherten Stundenwerten nachrechnen (ohne Loxone-Live-Steuerung).

**Daten:**

- `cons_data_hourly.csv` (Grundlast, PV)
- Historische Marktpreise für das gewählte Datum

**Sidebar:** Simulations-Tag (letzte 12 Monate), Start-SOC für die Simulation.

**Ausgabe:** Dieselben Metriken und Charts wie im Live-Modus, aber vollständig aus Historie — kein `main.py`-Overlay.

## Backtesting

**Zweck:** Langzeit-Auswertung aus dem Log von `scripts/run_backtesting.py`.

**Keine Sidebar-Parameter** — nur Auswahl von Szenarien/Monaten in der Hauptansicht.

**Inhalt:**

- Gesamt- und Monatskostenvergleich (Referenz vs. optimierte Szenarien)
- Plausibilisierung und Stundenverläufe pro Monat

Nicht für den täglichen Produktivbetrieb gedacht.
