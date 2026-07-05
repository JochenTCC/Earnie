# Charts & Panels

Gilt für den Produktiv-Modus **Sunset-2-Sunset** (`ui/simulation_results.py`, `ui/charts.py`, `ui/live_mode.py`). Modus-Übersicht: [Betriebsmodi](betriebsmodi.md). Der Modus **Backtesting** nutzt teils dieselben Chart-Komponenten, eigene Kosten- und Monatscharts.

## Seitenaufbau (Sunset-2-Sunset)

| Bereich | Inhalt |
|---------|--------|
| Kopf | Seitentitel, **Version** (Caption), **?** mit Modus-Scope (Sunset-2-Sunset / Backtesting) |
| Sidebar | Betriebsparameter (PV, Batterie, Runtime) |
| Charts | Chart 1 → Navigation ←/→ → Chart 2 |
| Darunter | Simulations-Tabelle, Energievergleich (Expander) |
| Sankey | Live-Energiefluss (Loxone) |
| Footer | Trennlinie → **Datenbasis** (Expander, Log-Pfad) → Optimierungs-Takt / Countdown |

Bei Wartezeit auf **main.py**: blauer Sync-Hinweis **über** den Charts (Countdown + **?**); im Footer zusätzlich **?** beim nächsten main.py-Takt.

## Chart 1: Leistung, SoC & Preis

**Überschrift:** Segment-Label (z. B. „SA₀→SA₁ (Live) · Datumsbereich“) mit **?** (Hintergrundzonen grau/neutral/grün, Navigation).

**Linke Y-Achse (kW):**

| Spur | Darstellung | Bedeutung |
|------|-------------|-----------|
| PV | Gelbe Linie | PV-Prognose / Log-Ist |
| Verbrauch | Blaue gestrichelte Linie | Grundlast |
| Batterie | Grün/rot Balken | Lade- (+) / Entladeleistung (−) |
| Flexible Verbraucher | Farbige Balken | Leistung je Verbraucher |

**Rechte Y-Achse (0–100, skaliert):**

| Spur | Bedeutung |
|------|-----------|
| SoC (optimiert) | Simulierter Batterie-SOC |
| SoC Baseline / BL Ziel | Referenz-SOC-Verläufe |
| Preis (rot) | Strompreis skaliert; Hover: Cent/kWh |

**Hintergrundzonen** (Details im **?** der Chart-1-Überschrift): grau = Vergangenheit (Log), neutral = laufende Stunde, grün = extrapolierte Preise bis Fensterrand.

Vertikale Marker **SA₀**, **SA₁**, **SA₂**; **Jetzt** nur im Live-Segment SA₀→SA₁.

**Soll/Ist-Icons** im grauen Log-Bereich: gelbes Dreieck (Hinweis), orange Raute (Warnung), rotes Achteck (Fehler) — Hover für Details; Erklärung im **?** der Chart-1-Überschrift. Regeln in `config/deviation_rules.json`.

## Navigation zwischen Chart 1 und Chart 2

| Steuerung | Verhalten |
|-----------|-----------|
| ← Zurück | Weitere SA-Zyklen zurück im Produktiv-Log |
| Vor → | SA₀→SA₁ ↔ SA₁→SA₂ bzw. einen Zyklus Richtung Live |

Kompakte Buttons in einer Zeile **ohne** Fließtext dazwischen (mobil-tauglich).

## Chart 2: Kumulierte Kosten & Verbrauch

**Überschrift** mit **?** (Ist vs. Prognose, orange Lücken) — im S-2-Split-Modus getrennte Kurven:

| Bereich | Kurven |
|---------|--------|
| Grau (Log) | **Ist bisher** — kumuliert aus Produktiv-Log |
| Neutral/Grün | **Prognose** — BL Ziel / optimiert ab Log-Grenze (ohne Anschluss an Ist) |

Fehlende Log-Slots: orange Markierung, Lücken in Ist-Kurven.

Kennzahlen **BL Ziel**, **Optimiert**, **Ersparnis** beziehen sich auf den Horizont **Jetzt → SA₂** (nicht nur das sichtbare Chart-Segment).

## Expander: Simulations-Details

Rohdaten-Tabelle aller Slots im sichtbaren S-2-Fenster (15-min Log + MILP); Spalte **Datenquelle**; orange Zeilen = fehlende Log-Einträge. Erklär-Markdown bleibt im Expander.

## Expander: Energievergleich Baseline vs. Optimierung

Tabelle je flexiblem Verbraucher über Horizont Jetzt→SA₂:

- **BL Profil**, **BL Ziel**, **Optimierung** (kWh)

## Energiefluss (Live-Sankey)

Sankey aus **aktuellen Loxone-Leistungswerten**; Produktiv-Overlay aus `runtime/optimizer_run_state.json` (Soll vs. Ist an Batterie/Flex). Aktualisierung ca. alle 10 Sekunden.

## Footer

| Element | Inhalt |
|---------|--------|
| **Datenbasis** | Expander: eingeklappt Produktiv-Log-Pfad; ausgeklappt Runtime, Merge-Pfad, Flex-Soll |
| **Optimierungs-Takt** | Viertelstunden; letzter Lauf main.py/App |
| **Nächster main.py-Takt** | Countdown + **?** (Sync-Erklärung) |

## Backtesting

Eigene Charts und Monatsauswertung aus `backtesting_log.json` — ohne S-2-Navigation und ohne Produktiv-Log-Merge.
