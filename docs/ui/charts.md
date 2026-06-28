# Charts & Panels

Gilt primär für die Modi **Echtzeit** und **Historischer Tag** (gemeinsame Komponenten in `ui/simulation_results.py` und `ui/charts.py`). Der Modus **Backtesting** nutzt eigene Kosten- und Monatscharts.

## Chart 1: 24-Stunden-Zeithorizont (Leistung, SoC & Preis)

**Linke Y-Achse (kW):**

| Spur | Darstellung | Bedeutung |
|------|-------------|-----------|
| PV | Gelbe Linie | PV-Prognose |
| Verbrauch | Blaue gestrichelte Linie | Grundlast-Prognose |
| Batterie | Grün/rot Balken | Geplante Lade- (+) / Entladeleistung (−) |
| Flexible Verbraucher | Farbige Balken | Geplante Leistung je Verbraucher (`flexible_consumers[].name`) |

**Rechte Y-Achse (0–100, skaliert):**

| Spur | Bedeutung |
|------|-----------|
| SoC (optimiert) | Simulierter Batterie-SOC über 24 h |
| SoC Baseline | SOC ohne Optimierung (historisches Profil) |
| SoC BL Ziel | SOC bei gleicher Flex-Energie ohne Verschiebung |
| Preis (rot) | Strompreis relativ skaliert; **Hover** zeigt Cent/kWh |

**Hinweise:**

- Ohne Preis-Extrapolation: *„Preis rot auf der rechten Achse: relativ auf 0–100 skaliert (Hover zeigt Cent/kWh).“*
- Wenn Zukunftspreise geschätzt werden: *„Ab {Stunde} bis {Stunde}: Strompreis geschätzt (Spiegelung gleicher Uhrzeit vom Vortag, gepunktete rote Linie). Übrige Verläufe (ohne PV) in diesem Bereich mit 50 % Transparenz.“*

Im **Echtzeit**-Modus kann unter den Charts erscheinen:

- Verbrauch der **aktuellen Stunde** aus `main.py` oder Loxone live
- **SoC für Simulation** aus dem letzten Produktiv-Lauf
- **Stunde 0 = Produktiv-Durchlauf** — übrige Stunden simuliert

Bei Wartezeit auf `main.py`: Countdown zur Synchronisation (ca. 1 Min. nach Viertelstunden-Wechsel).

## Chart 2: Kumulierte Kosten & Verbrauch

Am Ende des 24-Stunden-Fensters (rechts am Kostenverlauf) werden die Gesamtwerte angezeigt:

| Kennzahl | Bedeutung |
|----------|-----------|
| **BL Ziel** | Stromkosten mit skaliertem Profil, ohne Lastverschiebung |
| **Optimiert** | Stromkosten mit MILP-Plan |
| **Ersparnis** | Optimiert minus BL Ziel (negativ = günstiger, grün) |

| Spur | Achse | Bedeutung |
|------|-------|-----------|
| BL Ziel (Kosten) | links, € kumuliert | Kosten mit skaliertem Profil |
| Optimiert (Kosten) | links | Kosten mit Optimierung |
| BL Ziel (Verbrauch) | rechts, kWh kumuliert | Gesamtverbrauch Grundlast + Flex |
| Optimiert (Verbrauch) | rechts | Entsprechend optimiert |

Caption: *„Durchgezogene Linien: Kosten. Gestrichelte Linien (rechte Achse): Gesamtverbrauch Grundlast + Flex. BL Ziel: historisches Profil skaliert.“*

## Expander: Energievergleich Baseline vs. Optimierung

Tabelle je flexiblem Verbraucher:

- **BL Profil:** historisches Flex-Profil (kWh)
- **BL Ziel:** gleiche Energie wie Optimierung, ohne Verschiebung
- **Optimierung:** geplante kWh (ggf. mit Quellenhinweis, z. B. `loxone`)

## Expander: Simulations-Details

Rohdaten-Tabelle aller Stundenslots — Grundlage für die Charts (Nachrechnen/Debug).

## Energiefluss (Live-Sankey)

**Titel:** „Energiefluss (Live)“

Sankey-Diagramm aus **aktuellen Loxone-Leistungswerten** (PV, Netz, Batterie, Grundlast, flexible Verbraucher). Aktualisierung ca. alle 10 Sekunden.

**Produktiv-Overlay** aus `runtime/optimizer_run_state.json` (solange ein erfolgreicher Lauf vorliegt):

- Kopfzeile: Zeitstempel, Modus, Ziel-Leistung und Ziel-SoC der Batterie
- Knoten **Batterie**: Live-Leistung + Soll-Steuerbefehl
- Knoten **flexible Verbraucher**: Live-kW vs. Soll-kW aus der Optimierung (Abweichung orange markiert). Ist-Leistung 0 bei Soll > 0: schmales oranges Platzhalter-Band (Breite ≠ Soll, Hover zeigt Soll).

Ohne erfolgreichen Produktiv-Lauf: nur Live-Daten, Hinweis in der Kopfzeile.

## Vergangene Optimierungen (Produktiv)

Historie aus `runtime/optimization_history.jsonl` (plus Legacy-CSV falls vorhanden):

- Filter: Zeitraum (24 h bis „Alles“)
- Mini-Chart: SOC über die Zeit
- Tabelle: Zeitpunkt, Modus, Zielwerte, Preis, Prognosen, Flex-Soll
- Expander „Details zu einem Durchlauf“ für Einzelansicht

## Countdown (Fußzeile)

- **Optimierungs-Takt:** Viertelstunden (`:00` / `:15` / `:30` / `:45`)
- **Letzter Lauf:** Zeitstempel von `main.py` oder App
- **Nächster main.py-Takt** und **App-Sync** (ca. 1 Min. danach)
