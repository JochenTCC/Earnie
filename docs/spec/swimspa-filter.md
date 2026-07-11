# Spezifikation: SwimSpa Filter — kostenoptimale ergänzende Filternutzung

**Version:** 1.0  
**Status:** Abgeschlossen (2026-07-07) — Code Phasen 1–4, Live-Abnahme, Deviation-Regeln, Ist-Leistung/Fall B; Release **v1.20.0**  
**Backlog:** `Backlog.md` → **Version 1.20.0** → **Swimspa Filternutzung optimieren**

## 1. Ziel

Der SwimSpa-Filter soll als **eigener flexibler Verbraucher** (`swimspa_filter`) in die MILP-Optimierung eingebunden werden. Earnie plant **ergänzende** Filterlaufzeit, wenn Schulden in Stunden (`Sollstunden`) offen sind und Strom/PV günstig ist.

Der native Duty-Cycle des SwimSpa läuft **unabhängig** und reduziert `Sollstunden` ohne Earnie. Earnie schaltet nur **zusätzlich** ein (nicht als Gate für den nativen Zyklus).

Langfristig soll `Ernie_Swimspa_Filter_Sollstunden` gegen null gehen; der Zähler darf nicht unbegrenzt steigen.

## 2. Annahmen (geklärt)

| Thema | Entscheidung |
|-------|----------------|
| Steuerungsmodell | Ergänzend — nativer Duty-Cycle unabhängig; Earnie nur Zusatzläufe |
| `Sollstunden`-Semantik | Verbleibende Filter-Stunden (Schuldenstand), Float (Live-Format noch verifizieren) |
| Natives Fenster | Start-Stunde + Dauer aus Loxone (nicht Start/Ende) |
| Mindestlaufzeit Earnie | 30 min gewünscht; MILP plant stündlich → effektiv **1 h**-Slots |
| Backtesting | Kein `path_log`; fiktives natives Fenster über `config_fallback` |

## 3. Loxone-Signale

| Richtung | Merker | Bedeutung |
|----------|--------|-----------|
| Lesen | `Ernie_Swimspa_Filter_Sollstunden` | Verbleibende Filter-Schulden in **Stunden** (Float) |
| Lesen | `homie_bwa_spa_filter1hour` | Start-Stunde natives Fenster (ganze Stunde, Format Live prüfen) |
| Lesen | `homie_bwa_spa_filter1durationhours` | Dauer natives Fenster in **Stunden** (Float) |
| Lesen | `homie_bwa_spa_filter2` | Filter läuft (binär 0/1) → Ist-Leistung 0 / 0,18 kW |
| Lesen | `homie_bwa_spa_filter1` | Autonome/native Filtersteuerung (binär 0/1) — Fallback wenn `filter2` = 0 |
| Schreiben | `Ernie_Swimspa_Filter_Freigabe` | Earnie-Freigabe für **zusätzlichen** Filterlauf (`0`/`1`) |

`homie_bwa_spa_filter2` erfasst jeden Filterlauf (nativ + Earnie) — für Logging, Soll-Ist und Delivery-Tracking.

**Gemeinsame Leistungsmessung (Fall B, Live-Abnahme bestätigt):** `Ernie_Swim-Spa-P_act` misst die **Gesamt**-Leistungsaufnahme des SwimSpa (Heizung **inkl.** Filter und sonstige Pumpen am selben Zähler). Die Chart-Spalte **SwimSpa** zeigt den **Rest** nach Abzug bekannter Binär-Lasten (Heizung + „Allgemein“ — weitere Pumpen nicht einzeln modelliert). Der Filter-Anteil (~0,18 kW) wird über `subtract_consumer_ids` abgezogen. Korrektur in `resolve_flexible_consumers_live_power` nur bei echtem Zählerwert (nicht MILP-Fallback). Invariante: `swimspa_ist + swimspa_filter_ist = Gesamtmessung`.

### Chart-Ist (seit v1.22.3)

| Aspekt | Verhalten |
|--------|-----------|
| Log-Feld `flex_live_kw` | Nur gemessene/inferierte kW — **kein** MILP-Soll |
| `flex_measured_ids` | IDs mit echter Messung (inkl. explizitem 0 bei Binär-aus) |
| Chart 1 | Verbraucher ohne Messung → **leer** (`None`), nicht Fallback |
| Inferenz | Natives Filterfenster + Gesamtzähler ≈ Filter-Nennleistung (±0,05 kW), Binär-Merker 0 → Filter dem Chart zuordnen |

Operative Pfade (`cons_data`, Delivery) nutzen weiterhin `kw` mit Fallback, wenn der Zähler ausfällt.

## 4. Verbraucher-Config (`swimspa_filter`)

```json
{
  "id": "swimspa_filter",
  "name": "SwimSpa Filter",
  "chart_color_index": 1,
  "nominal_power_kw": 0.18,
  "signal_type": "binary",
  "min_on_quarterhours": 2,
  "optimizer_enabled": true,
  "daily_target_source": "loxone_remaining_hours",
  "loxone_target_hours_name": "Ernie_Swimspa_Filter_Sollstunden",
  "loxone_outputs": {
    "enable_name": "Ernie_Swimspa_Filter_Freigabe"
  },
  "loxone_inputs": {
    "power_name": "homie_bwa_spa_filter2",
    "alternate_binary_power_name": "homie_bwa_spa_filter1",
    "signal_type": "binary"
  },
  "filter_schedule": {
    "enabled": true,
    "loxone": {
      "native_start_hour_name": "homie_bwa_spa_filter1hour",
      "native_duration_hours_name": "homie_bwa_spa_filter1durationhours"
    },
    "config_fallback": {
      "native_start_hour": 10,
      "native_duration_hours": 4.0
    }
  }
}
```

Getrennt vom Heiz-Verbraucher `swimspa` (2,8 kW, `daily_target_source: thermal`).

## 5. Zielberechnung (`loxone_remaining_hours`)

```
Ziel_kWh = Sollstunden_live × nominal_power_kw
```

- Live-Wert jeden Optimierungszyklus neu lesen.
- **Kein** Abzug aus `flexible_consumers_state.delivered` — der Loxone-Zähler ist die alleinige Schuldenquelle.
- `Sollstunden ≈ 0` oder Merker fehlt → Verbraucher inaktiv, Warnung im Log.

Neuer Wert in `daily_target_source`-Enum: `loxone_remaining_hours` (unterscheidet sich von `loxone`, das Tagesziele in kWh meint).

## 6. MILP-Verhalten

1. `remaining_kwh = Sollstunden × 0,18`
2. **Gesperrte Slots** = Stunden im nativen Fenster `[Start, Start + Dauer)` (aus Loxone oder `config_fallback`)
3. Ergänzende Filterenergie nur in **nicht gesperrten** Slots planen
4. Nebenbedingung: `gelieferte_kWh >= min(remaining, max_erreichbar_im_Horizont)` (Best-Effort wie E-Auto)
5. Konkurrenz mit `swimspa`-Heizung und E-Auto über normale Energiebilanz

### Granularität

Die MILP-Matrix ist **stündlich**; `min_on_quarterhours` wird auf ganze Stunden gerundet. Effektive Mindestlaufzeit: **1 h** pro Einschaltung.

## 7. Loxone-Logik (ergänzend)

```
Native Duty-Cycle:
  läuft im Fenster [filter1hour, filter1hour + duration)
  dekrementiert Sollstunden unabhängig von Earnie

Earnie (pro 15-Min-Slot):
  Wenn Sollstunden > 0 UND außerhalb nativem Fenster UND MILP-Freigabe
    → Ernie_Swimspa_Filter_Freigabe = 1
  sonst → 0
```

## 8. Backtesting / Offline

- Kein historisches Filter-Log (`path_log` entfällt).
- `filter_schedule.config_fallback` für festes natives Fenster.
- Optional fiktiver Schuldenwert in Config für Offline-Tests.

## 9. UI & Soll-Ist

- Chart 1 / Sankey: eigener Eintrag „SwimSpa Filter“ (`chart_color_index: 1`).
- **Soll-Ist-Regeln** (Backlog Z.17, umgesetzt) — scope `swimspa_filter`, siehe [soll-ist-abweichung.md](soll-ist-abweichung.md) §5.1/§5.2:

| Regel-ID | Kategorie | Bedeutung |
|----------|-----------|-----------|
| `swimspa_filter_should_run_missing` | Fehler | Earnie-Freigabe (Soll > 0), aber Filter läuft nicht |
| `swimspa_filter_runs_unexpectedly` | Fehler | Filter läuft (Ist > 0) ohne Soll **außerhalb** nativem Fenster |
| `swimspa_filter_over_nominal` | Warnung | Ist-Leistung über Nennleistung (0,18 kW) + Toleranz |

- Der native Duty-Cycle läuft unabhängig; `swimspa_filter_runs_unexpectedly` blendet legitime native Läufe über das je Durchlauf mitgeloggte `filter_contexts`-Fenster (`main.py`) aus.

## 10. Implementierungsphasen

| Phase | Inhalt |
|-------|--------|
| 1 | `loxone_remaining_hours` in `consumer_targets` + `get_consumer_remaining_kwh` (ohne `delivered`-Abzug) |
| 2 | `filter_context.py`: natives Fenster → gesperrte Matrix-Indizes; Anbindung MILP |
| 3 | Schema, `config.example.json`, `loxone-signale.md`, `verify_loxone_setup` |
| 4 | Live-Abnahme (Format `filter1hour`, Float `Sollstunden`) |

## 11. Live-Formate (Abnahme)

| Merker | Unterstütztes Format | Parser |
|--------|---------------------|--------|
| `homie_bwa_spa_filter1hour` | Integer `0`–`23`, `10.0`, `10 h` oder `HH:MM` | `parse_filter_native_start_hour` |
| `Ernie_Swimspa_Filter_Sollstunden` | Float (Stunden, ≥ 0) | `fetch_loxone_generic_value` |
| `homie_bwa_spa_filter1durationhours` | Float h (> 0) | `fetch_loxone_generic_value` |
| `homie_bwa_spa_filter2` | Binär `0`/`1` | `fetch_loxone_generic_value` |

Live-Abnahme:

```powershell
.venv\Scripts\python.exe -m scripts.verify_swimspa_filter_live
```

Bestehende `config.json` um `swimspa_filter` ergänzen (idempotent):

```powershell
.venv\Scripts\python.exe -m scripts.patch_swimspa_filter_config
```
