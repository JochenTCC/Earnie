# Spezifikation: SwimSpa Filter — kostenoptimale ergänzende Filternutzung

**Version:** 0.1  
**Status:** Implementiert (2026-07-07, v1.20.0)  
**Backlog:** `Backlog.md` → Version 1.+1 → **Swimspa Filternutzung optimieren**

## 1. Ziel

Der SwimSpa-Filter soll als **eigener flexibler Verbraucher** (`swimspa_filter`) in die MILP-Optimierung eingebunden werden. Ernie plant **ergänzende** Filterlaufzeit, wenn Schulden in Stunden (`Sollstunden`) offen sind und Strom/PV günstig ist.

Der native Duty-Cycle des SwimSpa läuft **unabhängig** und reduziert `Sollstunden` ohne Ernie. Ernie schaltet nur **zusätzlich** ein (nicht als Gate für den nativen Zyklus).

Langfristig soll `Ernie_Swimspa_Filter_Sollstunden` gegen null gehen; der Zähler darf nicht unbegrenzt steigen.

## 2. Annahmen (geklärt)

| Thema | Entscheidung |
|-------|----------------|
| Steuerungsmodell | Ergänzend — nativer Duty-Cycle unabhängig; Ernie nur Zusatzläufe |
| `Sollstunden`-Semantik | Verbleibende Filter-Stunden (Schuldenstand), Float (Live-Format noch verifizieren) |
| Natives Fenster | Start-Stunde + Dauer aus Loxone (nicht Start/Ende) |
| Mindestlaufzeit Ernie | 30 min gewünscht; MILP plant stündlich → effektiv **1 h**-Slots |
| Backtesting | Kein `path_log`; fiktives natives Fenster über `config_fallback` |

## 3. Loxone-Signale

| Richtung | Merker | Bedeutung |
|----------|--------|-----------|
| Lesen | `Ernie_Swimspa_Filter_Sollstunden` | Verbleibende Filter-Schulden in **Stunden** (Float) |
| Lesen | `homie_bwa_spa_filter1hour` | Start-Stunde natives Fenster (ganze Stunde, Format Live prüfen) |
| Lesen | `homie_bwa_spa_filter1durationhours` | Dauer natives Fenster in **Stunden** (Float) |
| Lesen | `homie_bwa_spa_filter2` | Filter läuft (binär 0/1) → Ist-Leistung 0 / 0,18 kW |
| Schreiben | `Ernie_Swimspa_Filter_Freigabe` | Ernie-Freigabe für **zusätzlichen** Filterlauf (`0`/`1`) |

`homie_bwa_spa_filter2` erfasst jeden Filterlauf (nativ + Ernie) — für Logging, Soll-Ist und Delivery-Tracking.

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
  dekrementiert Sollstunden unabhängig von Ernie

Ernie (pro 15-Min-Slot):
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
- Soll-Ist-Regel (Follow-up): z. B. Warnung bei dauerhaft hohen `Sollstunden`.

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
