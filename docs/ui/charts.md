# Charts & Panels

Gilt primär für die Modi **Echtzeit** und **Historischer Tag** (gemeinsame Komponenten in `ui/simulation_results.py` und `ui/charts.py`). Der Modus **Backtesting** nutzt eigene Kosten- und Monatscharts.

## Metriken: Optimierungs-Einsparungen

Drei Kennzahlen über den 24-Stunden-Horizont:

| Metrik | Bedeutung |
|--------|-----------|
| **BL gleiches Ziel** | Stromkosten, wenn flexible Verbraucher dieselbe Tagesenergie verbrauchen wie in der Optimierung, aber **ohne** zeitliche Verschiebung (Profil skaliert) |
| **Optimiert** | Stromkosten mit MILP-Plan (Batterie + Flex-Verbraucher) |
| **Ersparnis** | Optimiert minus BL gleiches Ziel (negativ = günstiger) |

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

## Echtzeit-Leistungsfluss (Sankey)

**Titel:** „Echtzeit-Leistungsfluss (Live)“

Sankey-Diagramm aus **aktuellen Loxone-Leistungswerten** (PV, Netz, Batterie, Verbrauch). Aktualisierung ca. alle 10 Sekunden. Bei Fehler: Warnung, dass Live-Werte nicht geladen werden konnten.

## Produktiv-Durchlauf (`main.py`)

Expander mit dem letzten erfolgreichen Lauf aus `runtime/optimizer_run_state.json`:

| Anzeige | Bedeutung |
|---------|-----------|
| SoC | Batterie-SOC zum Optimierungszeitpunkt |
| Modus | Normal / Zwangs-Laden / Halten / Zwangs-Entladen |
| Ziel-Leistung | Soll-Leistung Batterie (kW) |
| Ziel-SoC | Soll-SOC (%) |
| PV (letzte h) | PV-Ertrag letzte Stunde (kWh) |
| Je Flex-Verbraucher | Live-Leistung vs. Soll aus Optimierung |

## Vergangene Optimierungen (Produktiv)

Historie aus `runtime/optimization_history.jsonl` (plus Legacy-CSV falls vorhanden):

- Filter: Zeitraum (24 h bis „Alles“)
- Mini-Chart: SOC über die Zeit
- Tabelle: Zeitpunkt, Modus, Zielwerte, Preis, Prognosen, Flex-Soll
- Expander „Details zu einem Durchlauf“ für Einzelansicht

## Plausibilität main.py ↔ App-Simulation (Debug)

Nur Echtzeit, wenn Debug-Snapshot existiert (`runtime/live_optimization_debug.json`):

- Abgleich Stunde 0 nach Overlay mit Produktiv-Durchlauf
- Optional: Abweichung der reinen App-Simulation vor Overlay (erwartbar, wenn `main.py` maßgeblich ist)

## Countdown (Fußzeile)

- **Optimierungs-Takt:** Viertelstunden (`:00` / `:15` / `:30` / `:45`)
- **Letzter Lauf:** Zeitstempel von `main.py` oder App
- **Nächster main.py-Takt** und **App-Sync** (ca. 1 Min. danach)
