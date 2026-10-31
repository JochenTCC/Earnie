# Charts & Panels

Diese Seite beschreibt Charts und Panels der Seite **Monitor** (Sunset-2-Sunset; Code: `ui/simulation_results.py`, `ui/charts.py`, `ui/live_mode.py`). Überblick über die Modi: [Betriebsmodi](betriebsmodi.md). Der **Szenario-Explorer** nutzt teilweise dieselben Chart-Komponenten, hat aber eigene Kosten- und Monatscharts.

## Seitenaufbau (Monitor / Sunset-2-Sunset)

| Bereich | Inhalt |
|---------|--------|
| Kopf | Seitentitel mit **?** (Geltungsbereich des Modus: Sunset-2-Sunset bzw. Szenario-Explorer) |
| Sidebar | Hinweise zu Env und Setup, Fortschritt der Ersteinrichtung, **Konfiguration speichern / laden** (ZIP); unten **Info / About** (Banner, Version, Kontakt). PV- und Batterie-Parameter liegen im **Szenarienkonfigurator** bzw. Hauskonfigurator, nicht in der Sidebar. |
| Menü | `st.navigation` mit den Abschnitten Live-Cockpit, Konfiguration, Daemon Control |
| Charts | Reihenfolge: Chart 1 → Navigation ←/→ → Sankey → Chart 2 → Simulations-Tabelle → Energievergleich (Expander) |
| Sankey | Live-Energiefluss unter Chart 1 (nach der Navigation). Anlagenwerte (Plant) kommen über das EHAL-Backend; Flex und EV-SoC siehe [Energiefluss](#energiefluss-live-sankey). |
| Footer | Trennlinie, dann **Datenbasis** (Expander, Log-Pfad), dann Optimierungs-Takt / Countdown |

Wartet die Seite auf **main.py**, erscheint **über** den Charts ein blauer Sync-Hinweis (Countdown und **?**). Im Footer steht zusätzlich ein **?** beim nächsten main.py-Takt.

## Chart 1: Leistung, SoC & Preis

**Überschrift:** Fensterbezeichnung und Datumsbereich, z. B. „SA₀→SA₂ (Live)“ am Desktop bzw. „SA₀→SA₁ (Live)“ mobil. Das **?** daneben erklärt die Hintergrundzonen (grau, neutral, grün) und die Navigation.

**Linke Y-Achse (kW):** Die Balkenhöhe zeigt die Leistung. Die Balkenbreite folgt der Slotdauer (**15 min** über den ganzen Horizont), die Fläche ist also proportional zur Energie. **Ausnahme Verbraucher:** Generic-Schedules werden intern stündlich modelliert und auf Viertelstunden gehalten. Läufe mit `duration_h < 1` können deshalb als mittlere Leistung erscheinen (`nominal × duration_h` in `generic_schedule`).

| Spur | Darstellung | Bedeutung |
|------|-------------|-----------|
| PV | Gelbe Linie | PV-Prognose (durchgängig über grau, neutral und grün) |
| Energiebilanz | Rauf/Runter-Balken (gestapelt) | **↑ kräftig:** PV (gelb), Netzbezug (blau). **↓ kräftig:** Grundlast (braun), Flex. **Gedämpft:** Batterie→Last grün, Netz→Batterie cyan, PV→Batterie gelb-grün, PV→Netz blassgelb. Rauf- und Runter-Säule sind gleich hoch. |

### Rauf/Runter-Algorithmus (Wasserfall)

Pro Slot verteilt Earnie die Leistungen aus den Chart-Feldern auf einzelne Flüsse (`ui/flow_balance_allocate.py`):

```
PV-Rest  := PV − min(PV, Last)
Last-Rest nach PV-Deckung
Netz     → min(Netzbezug, Last-Rest)
Entladen → min(Batterie-Entladen, verbleibende Last)
Laden    ← min(Laden, PV-Rest); PV-Rest reduzieren
Einspeisung (PV) ← min(Einspeisung, PV-Rest)
Einspeisung (Batterie) ← Rest der Einspeisung (≤ Entlade-Rest)
Entladen → Last ← verbleibende Entladung
```

Die gedämpften Segmente im Chart:

| Segment (Chart) | Farbe gedämpft | Bedeutung |
|-----------------|----------------|-----------|
| `battery_charge_pv` | Gelb-Grün | Laden aus PV-Rest |
| `battery_charge_grid` | Cyan | Laden aus Netz |
| `export_pv` | Blassgelb | PV direkt ins Netz |
| `export_battery` | Cyan | Einspeisung aus Entladung (Batterie→Netz) |
| `battery_discharge_load` | Grün | Entladen in die Last (0-Bilanz) |

Dieselbe Slot-Zuordnung nutzt auch die Auswertung [Analyse Verbrauch & Kosten](#analyse-verbrauch--kosten-live-cockpit).

### Sonderfälle

- **Vorzeichen:** `Netzbezug` und `Geplante Batterie-Aktion` sind vorzeichenkodiert. Bezug und Laden sind positiv, Einspeisung und Entladen negativ.
- **Fehlende Einspeisung:** Fehlt in der Zeile eine explizite Einspeisung, zeichnet der Chart den PV-Überschuss (`offset_kw > 0`) als gedämpfte PV-Einspeisung.
- **MILP (neutraler und grüner Bereich):** Gezeichnet wird der geplante Batteriewert. Am oberen bzw. unteren SoC-Limit entfällt der geplante Lade- bzw. Entladeanteil; der Überschuss erscheint dann als PV-Einspeisung bzw. Netzbezug. Im neutralen MILP-Bereich wird `Netzbezug` nach dem Live-Overlay aus Last, Flex, PV und Batterie neu abgeleitet.

### Ist-Werte im grauen Bereich (Produktiv-Log)

PV, Last, Netz, Batterieflüsse und **Flex-Verbraucher** zeigen im grauen Bereich Ist-Werte aus dem Produktiv-Log.

- **Viertelstunden-Mittel:** Ab Builds des Optimierer-Dienstes mit Viertelstunden-Mittelung schreibt `main.py` zusätzlich `closed_interval`. Das ist der Mittelwert der Leistungsproben (≤ 60 s) über die *vorherige* Viertelstunde, typisch alle 30 s.
- **Nutzung der Mittelwerte:** Chart 1, Verbrauch & Kosten und die Ist-Seite von Soll/Ist nutzen diese Mittelwerte, sobald `sample_count ≥ 3`. Andernfalls dient die Probe am Entscheidungspunkt (`consumption_snapshot`) als Fallback. Ältere Log-Zeilen ohne `closed_interval` bleiben Punktproben.
- **Loxone-Zähler (optional, VO-Push):** Sind die Energie-Felder aktiviert (`sens_pv_energy` / `sens_grid_energy_*` bzw. `consumer.*.sens_energy_total`), liest der Sampler die vom Miniserver gepushten Zählerstände aus der Inbox. Für diese Kanäle setzt er die mittlere Slot-Leistung aus ΔkWh / 0,25 h (`ist_power_source`: `counter`). Veraltete oder fehlende Zähler (kein Push bzw. älter als 3 × VO-Repeat) lassen den Kanal auf dem Leistungsmittel. Dasselbe gilt für gemeinsame Zähler mit `subtract_consumer_ids`.
- **HA-Energiezähler (optional):** Zusätzliche Entities `sens_pv_energy` / `sens_grid_energy_import` / `sens_grid_energy_export` in `plant.ehal_bindings` (`device_class=energy`, bevorzugt `state_class=total_increasing`). Für PV und Netz gilt derselbe Vertrag ΔE / 0,25 h; Batterie und Flex bleiben auf dem Leistungsmittel.
- **Batterie:** Die Aufteilung in Laden und Einspeisung ergibt sich aus der gemessenen Batterieleistung (`Ist Batterie-Leistung (kW)`), nicht aus `battery_plan_kw`. Widerspricht das Ist-Vorzeichen dem SoC-Schritt zum nächsten Log-Slot und fehlt ein brauchbares Slot-Mittel, leitet Earnie die Batterieleistung für die Balken aus dem SoC-Delta ab.

**PV im grauen Bereich:** Eine Prognose-Linie läuft über alle Zonen. Sie zeigt den Forecast.Solar-Wert **vor** dem Live-Overlay (Feld `forecast_pv_kw` im Log). Die PV-Balken (Rauf-Seite der Energiebilanz) nutzen im Log dagegen den **Ist**-Wert (`PV-Ist (kW)` aus `consumption_snapshot.pv_kw`). Die Abweichung ist ab dem nächsten Worker-Lauf nach dem Fix sichtbar. Ältere Log-Einträge können identische Werte haben, weil früher der Ist-Wert fälschlich als Prognose geloggt wurde.

### Flexible Verbraucher

**Farben:** Flexible Verbraucher erscheinen als gestapelte Runter-Segmente. Ihre Farbe stammt aus der festen **8er-Palette** in `ui/chart_colors.py` (`CONSUMER_PALETTE`, Farbton **260→40**, S≈90, L≈50). In `config.json` legt **`chart_color_index`** (0–7) die Farbe je Verbraucher fest; freie Hex-Werte gibt es nicht mehr. Die Auflösung läuft zentral über `consumer_chart_color()`, sodass Chart 1 und Sankey dieselben Vollfarben zeigen.

**Generic `earnie_role: known` und `manual`:** Die Optimierung zählt diese Verbraucher zum Grundlast-Overlay. Chart 1 zieht ihre geplanten Slot-Leistungen trotzdem **sichtbar** aus `Verbrauch-Prognose` heraus und zeigt sie als eigene Runter-Segmente (`house_config/known_chart_display.py`). `manual` bleibt für die Empfehlungs-UI relevant. SE und Live rechnen den Default-Schedule mit, unter der Annahme, dass der Start wie empfohlen erfolgt.

**Zonenabhängige Sättigung (nur Flex-Balken in Chart 1):** Im grauen Bereich (Vergangenheit) erscheinen die Palettenfarben voll gesättigt. Im neutralen Bereich (laufender Plan) und im grünen Bereich (Preis-Prognose) sind sie gemeinsam gedämpft (`CONSUMER_CHART_SATURATION_MUTED`, derzeit 0,8). Die Zuordnung Slot → Zone erfolgt über `chart_zone_kind_for_slot_start()` / `UiChartZones`. Die Legende bleibt in Vollfarbe (`visible='legendonly'`), der Sankey ebenfalls in voller Sättigung.

**Legende (Monitor, Chart 1 und 2):** Die Plotly-Legende (`showlegend`) ist ausgeschaltet. Stattdessen steht unter dem Chart auf allen Bildschirmgrößen ein ausklappbares HTML-`<details>` mit Farbfeldern (`ui/chart_legend_mobile.py`, `margin.b` = 0). Im Chart bleibt so kein leerer Legendenstreifen.

### Rechte Y-Achse (0–100, skaliert)

| Spur | Darstellung | Bedeutung |
|------|-------------|-----------|
| SoC (optimiert) | Grüne Linie (`_HSL_SOC` in `ui/chart_colors.py`). Bei ≥2 SoC-Trägern (Haus-ESS, physische Powerstation, virtuelle Powerstation) eine Linie pro Entität (`SoC · {Bezeichnung}`, Farbvarianten um `_HSL_SOC`). Virtuelle Powerstations erscheinen als sehr schmale **gestrichelte** Linien (Dash-Zyklus, nie durchgezogen), damit sich überlappende Reserven unterscheiden lassen. | Simulierter Batterie- bzw. Reserve-SOC: Haus-ESS live/MILP; physische `standby_backup`-PS live plus Forecast aus dem Standby-Plan (Inseln/Laden); virtuelle PS = `stored_kwh` / Kapazität, Forecast aus der Attribution des Haus-Batterieplans |
| ESS-Mode-Underlay | Dickere, halbtransparente Linie hinter dem SoC | Cyan = Entladesperre / Hold bzw. Zwangsleistung unter 5 % von `max_power_kw`; Blau = Zwangsladen ≥ 5 %; Magenta = Zwangsentladen ≥ 5 %; Automatik ohne Underlay. Das Underlay erscheint nur am Primär-SoC. |
| SoC BL Ziel | Dieselbe Farbe, gestrichelt ab **Jetzt** (nicht davor) | Referenz-SOC (Baseline) der Primärbatterie; Anker ist der Log-SOC am Jetzt-Marker |
| Preis (rot) | Strompreis skaliert | Hover: Cent/kWh |
| Einspeisepreis (orange, gestrichelt) | Einspeisevergütung skaliert | Hover: Cent/kWh |

**SoC-Plausibilität (Live-Monitor):** Der Abstand zwischen **SoC BL Ziel** und **SoC** entsteht durch Lastverschiebung (Flex oder E-Auto zeitlich anders platziert) und/oder durch die Batteriestrategie (Netzladen, Entladen, Halten). Umrandete Flex-Balken (**Original-Schedule**, nur Kanten, ohne Füllung) zeigen, wo Flex laut BL-Ziel gelaufen wäre. Die gefüllten Flex-Balken zeigen weiterhin die Optimierung. Solche Ghost-Segmente entfallen, wenn ihr Energie-Äquivalent (`kW × Slotdauer`) unter **1 kWh** liegt.

### Hintergrundzonen und Marker

Die Hintergrundzonen (Details im **?** der Chart-1-Überschrift):

- **Grau:** Vergangenheit (Log).
- **Neutral:** laufende Stunde.
- **Grün:** extrapolierte Preise bis zum Fensterrand.

Vertikale Marker zeigen **SA₀**, **SA₁** und **SA₂** sowie **Jetzt**, sobald die aktuelle Zeit im sichtbaren Fenster liegt.

### Soll/Ist-Icons

Soll/Ist-Icons erscheinen im grauen Log-Bereich, und zwar nur für Slots mit echtem Produktiv-Eintrag (`slot_quality == present`):

| Symbol | Kategorie | Farbe | Bedeutung |
|--------|-----------|-------|-----------|
| ▲ | Hinweis | grün | Unkritische Abweichung (z. B. Wärmepumpe: Freigabe ohne Anlauf) |
| ◆ | Warnung | gelb | Erwartete Abweichung (z. B. SwimSpa im Sollband, Zwangs-Laden lädt 60–80 % der Zielenergie) |
| ⬡ | Fehler | rot | Anweisung von Earnie nicht befolgt |

Die Marker liegen oberhalb der Chart-Fläche; beim **Hover** erscheinen Kategorie-Label und Regeltext. Pro Slot sind mehrere Icons möglich (verschiedene Scopes, z. B. Batterie und E-Auto).

Beim Zwangs-Laden vergleicht Earnie die im Slot tatsächlich geladene Energie (mittlere Ladeleistung × Slotdauer) mit der Zielenergie (Soll-Leistung × Slotdauer). Ab 80 % gilt der Slot als erfüllt. Zwischen 60 % und 80 % erscheint eine gelbe Warnung, darunter ein roter Fehler. Beide Marker erscheinen nur, wenn im Slot zusätzlich mehr als 0,1 kWh fehlen. Kleine Zwangsladungen lösen deshalb keinen Marker aus, auch wenn der Anteil niedrig ist. Der Tooltip nennt den erreichten Anteil sowie Soll und Ist in kWh. Die Schwellen stehen je Regel als `params.max_ratio` (Anteil) und `params.min_shortfall_kwh` (Mindest-Fehlmenge) in den beiden Zwangs-Laden-Regeln. Fehlt für den Slot der gemessene Mittelwert, bewertet Earnie die Zwangsladung nicht, weil ein Momentanwert keine Energie ergibt.

Die Wärmepumpe („Freigabe, aber nicht angesprungen“) bewertet Earnie genauso: Der grüne Hinweis erscheint, wenn die Wärmepumpe im Slot weniger als 50 % der geplanten Energie aufgenommen hat **und** mehr als 0,1 kWh fehlen. Läuft sie nur etwas schwächer als geplant, erscheint kein Hinweis. Beide Schwellen stehen getrennt von den Zwangs-Laden-Regeln als `params.max_ratio` und `params.min_shortfall_kwh` in der Wärmepumpen-Regel. Auch hier gibt es ohne gemessenen Slot-Mittelwert kein Urteil.

**Regelwerk:** `config/deviation_rules.json` (Schema: `deviation_rules.schema.json`). Pflegehinweis: [Spec Soll-Ist §5.3](../dev/done/soll-ist-abweichung.md).

**Aktive Regeln (Stand bei Einführung der Soll/Ist-Icons):**

| Regel-ID | Scope | Kategorie |
|----------|-------|-----------|
| `swimspa_thermal_band_ok` | swimspa | Warnung |
| `eauto_pv_follow_missing` | eauto | Fehler |
| `eauto_should_charge` | eauto | Fehler |
| `battery_forced_discharge_missing` | battery | Fehler |
| `battery_forced_charge_missing` | battery | Fehler |
| `battery_forced_charge_target_missed` | battery | Warnung |
| `waermepumpe_enable_no_start` | waermepumpe | Hinweis |
| `swimspa_filter_should_run_missing` | pool_filter | Fehler |
| `swimspa_filter_runs_unexpectedly` | pool_filter | Fehler |
| `swimspa_filter_over_nominal` | pool_filter | Warnung |

## Navigation nach Chart 1

| Steuerung | Verhalten |
|-----------|-----------|
| ← Zurück | Blättert SA-Zyklen im Produktiv-Log zurück |
| Vor → | Desktop: einen Zyklus Richtung Live (im Live-Fenster deaktiviert). Mobil: Wechsel SA₀→SA₁ ↔ SA₁→SA₂ bzw. einen Zyklus Richtung Live |

Die kompakten Buttons stehen in einer Zeile **ohne** Fließtext dazwischen (mobil-tauglich) und liegen **zwischen Chart 1 und Sankey**; Chart 2 folgt darunter. Der Desktop zeigt standardmäßig SA₀→SA₂, mobil bleibt es bei 24-h-Segmenten.

## Chart 2: Kumulierte Kosten & Verbrauch

**Überschrift** mit **?** (Ist vs. Prognose, orange Lücken). Im Sunset-2-Sunset-Fenster sind Ist und Prognose getrennte Kurven:

| Bereich | Kurven |
|---------|--------|
| Grau (Log) | **Ist bisher:** kumuliert aus dem Produktiv-Log. **Ersparnis bisher:** geplante Differenz BL−Opt der abgelaufenen Slots (pro SA-Tag, Neustart bei SA₁). |
| Neutral/Grün | **Prognose:** BL Ziel / optimiert ab der Log-Grenze (an die Ist-Kurve angeschlossen) |

Fehlende Log-Slots sind orange markiert; die Ist-Kurven haben dort Lücken.

Die Kennzahlen **BL Ziel** und **Optimiert** (Annotationen) beziehen sich **pro SA-Tag**: mobil nur auf den sichtbaren Tag, am Desktop (SA₀→SA₂) auf zwei Spalten (SA₀→SA₁ | SA₁→SA₂). Am **laufenden Tag** kommen **Ersparnis bisher** (SA bis Jetzt, geplante Differenz der abgelaufenen Slots) und **Ersparnis erwartet** (ganzer SA-Tag bis SA₁ bzw. SA₂) hinzu. Der MILP-Matching-Horizont (Jetzt → SA₂) bleibt davon unberührt, siehe [Energievergleich](#expander-energievergleich-baseline-vs-optimierung). Linienfarben: `_HSL_COST_*` in `ui/chart_colors.py`.

## Expander: Simulations-Details

Rohdaten-Tabelle aller Slots im sichtbaren Sunset-2-Sunset-Fenster (15-min-Log und MILP) mit der Spalte **Datenquelle**. Orange Zeilen markieren fehlende Log-Einträge. Der Erklärtext steht im Expander.

## Expander: Energievergleich Baseline vs. Optimierung

Tabelle je flexiblem Verbraucher über den Horizont SA₀→SA₂ mit den Spalten **BL Profil**, **BL Ziel** und **Optimierung** (kWh).

## Energiefluss (Live-Sankey)

<a id="energiefluss-live-sankey"></a>

Der Sankey aktualisiert sich etwa alle 10 Sekunden (`STATUS`-Fragment). Die Flex-Knoten nutzen dieselbe **`chart_color_index`**-Palette wie Chart 1 (`consumer_chart_color`). Liegt ein Optimierungslauf vor, kommt das Produktiv-Overlay (Soll vs. Ist an Batterie und Flex) aus `runtime/optimizer_run_state.json`.

| Teil | Quelle im Code | Backends heute |
|------|----------------|----------------|
| PV / Netz / Batterie / Hausleistung | `ehal_live.read_live_power_kw()` → aktiver Adapter | **Loxone, Home Assistant, OpenEMS** |
| Flex-Leistungen (Verbraucherknoten, Grundlast-Aufteilung) | `live_consumption.fetch_live_flex_kw_for_ui` → `loxone_client.resolve_flexible_consumers_live_power` | **nur Loxone** (bei HA/OpenEMS keine Live-Flex-Aufschlüsselung über Merker) |
| EV-SoC in der Knotenbeschriftung beim Laden | `fetch_loxone_actual_soc_percent` | **nur Loxone** |

Lädt ein E-Auto, zeigt der Flex-Knoten den aktuellen SoC in der Beschriftung, sofern der Loxone-Pfad den SoC liefert.

Sind PV, Netz, Batterie und Haus alle exakt 0 kW, zeichnet Earnie keinen Sankey, sondern eine gelbe Warnung. Bei Loxone und Home Assistant ist die häufigste Ursache ein zu seltener Push: Bleibt ein Leistungswert länger als 3 × Wiederholintervall (Standard 30 s) aus, nimmt Earnie 0 an (Status „0 angenommen (verstummt)“, siehe [Push-Takt](../referenz/loxone-signals.md#push-cadence-sb-neutral)). Den Status je Signal zeigt **EHAL-Com → Live-Lesen**.

## Footer

| Element | Inhalt |
|---------|--------|
| **Datenbasis** | Expander: eingeklappt der Pfad zum Produktiv-Log; ausgeklappt Runtime, Merge-Pfad und Flex-Soll |
| **Optimierungs-Takt** | Viertelstunden; letzter Lauf von main.py bzw. App |
| **Nächster main.py-Takt** | Countdown und **?** (Erklärung zur Synchronisation) |

## Analyse Verbrauch & Kosten (Live-Cockpit)

Die Auswertung nutzt dieselbe Slot-Zuordnung wie Chart 1 (`allocate_slot_flows`, siehe [Rauf/Runter-Algorithmus](#raufrunter-algorithmus-wasserfall)).

- **Verteilung:** Die Zuordnung wird anteilig (pro rata) auf Grundlast und gemessene Flex-Verbraucher verteilt.
- **Kosten am Verbrauchsort:** Kosten entstehen nur für den **Netzanteil** (Netzanteil × Importpreis); PV und Batterie-Entladung zählen mit 0 €.
- **Quelle und Zeitraum:** Grundlage ist das Produktiv-Log. Die Charts zeigen rollierende **7-** bzw. **28-Tage**-Fenster (mit Navigation), die Kennzahlen zusätzlich die letzten **365 Tage** vorhandener Log-Daten.
- **Batterie-Energieflüsse:** Gestapelte Lade- und Entladebalken, inklusive **Standby** aus dem Hauskonfigurator (`standby_power_kw` × Fensterstunden).
- **Caption zur Batterie:** Sie nennt den gemessenen Wirkungsgrad `η = √(E_Entladen / E_Laden)` als Empfehlung für den Hauskonfigurator; der Nominalwert bleibt genannt. Außerdem vergleicht sie den Standby laut Hauskonfigurator (A) mit dem Rest nach Roundtrip mit nominalem η (B) und empfiehlt konkret `Standby-Leistung ≈ B / Fensterstunden` in kW (Nominalwert genannt). Bei einer relativen Abweichung über 20 % erscheint ein Hinweis.
- **Wärmeinhalt:** Darunter folgt ein Chart mit Sim `Q_sim` und Ist `Q_meas` aus `thermal_observability`. Dazu kommt ein Fächer der letzten 12 stündlichen Q-Prognosen (`horizon_q_sim_kwh`, gemeinsamer Horizont ≤ 24 h) für Wärmespeicher und Pools.

## Szenario-Explorer

Eigene Charts und Monatsauswertung auf Basis von `runtime/backtesting_log.json`, ohne Sunset-2-Sunset-Navigation und ohne Zusammenführung mit dem Produktiv-Log. UI-Seite: **Szenario-Explorer** (`scenario_explorer`).

**Gesamtkosten und -Verbrauch, Spalte „Jahres Verbrauch“:** In allen Zeilen der gebuchte Verbrauch der jeweiligen Stundenreihe (jeder Zeitslot einmal); der Speicher-Standby steht in einer eigenen Spalte. Erklärung: [Betriebsmodi](betriebsmodi.md#gesamtkosten-und--verbrauch), [Benutzer-Handbuch](../user-manual/Benutzer-Handbuch-Earnie.md#gesamtkosten-jahres-verbrauch-kwh).
