# Loxone-Signale — Referenz

Alle Namen sind **Beispiele** aus [`config/config.example.json`](../../config/config.example.json). In der eigenen `config/config.json` müssen sie exakt den virtuellen Eingängen und Merkern im Loxone Miniserver entsprechen.

Prüfung aller konfigurierten Signale:

```powershell
.venv\Scripts\python.exe -m scripts.verify_loxone_setup
.venv\Scripts\python.exe -m scripts.verify_swimspa_filter_live
```

## Zentrale Signale (`loxone_blocks`)

| Config-Schlüssel | Richtung | Beispiel-Name | Wert / Einheit |
|------------------|----------|---------------|----------------|
| `soc_name` | Lesen | `B004-Battery_SOC` | Batterie-SOC, % |
| `pv_power_name` | Lesen | `Ernie-Merker-PV_Act` | PV-Leistung, kW |
| `battery_power_name` | Lesen | `Ernie-Merker-LeistungBat_Act` | Batterie: + laden, − entladen, kW |
| `grid_power_name` | Lesen | `Ernie-Merker-LeistungNetz_Act` | Netzleistung, kW |
| `pv_counter_name` | Lesen | `48 - Accumulated energy yield` | PV-Zähler kumuliert, kWh |
| `log_filename` | FTP | `Verbrauch.csv` | Dateiname im Miniserver-Ordner `log/` |
| `pv_tuning_log_file` | Lokal | `pv_accuracy_log.csv` | Lokale CSV für PV-Tuning (optional) |
| `target_soc_name` | Schreiben | `Ernie_Ziel_SoC` | Ziel-SOC, % |
| `target_charge_power_name` | Schreiben | `Ernie_Ziel_LadeLeistung` | Zwangsladeleistung, kW |
| `target_discharge_power_name` | Schreiben | `Ernie_Ziel_Entladeleistung` | Ziel-Entladeleistung, kW |
| `control_cmd_name` | Schreiben | `Ernie_Steuerbefehl` | `0` Automatik, `1` Zwangsladen, `2` Zwangs-Entladen |

## Flexible Verbraucher — pro Eintrag in `flexible_consumers[]`

### Gemeinsame Signale

| Config-Pfad | Richtung | Beispiel | Wert |
|-------------|----------|----------|------|
| `loxone_inputs.power_name` | Lesen | `Merkername SwimSpa kW` | kW oder 0/1 (siehe `signal_type`) |
| `loxone_outputs.enable_name` | Schreiben | `Ernie_SwimSpa_Freigabe` | `0` gesperrt, `1` Freigabe |

### E-Auto — zusätzlich unter `charging_schedule.loxone`

| Config-Schlüssel | Richtung | Beispiel | Wert |
|------------------|----------|----------|------|
| `plugged_in_name` | Lesen | `EAuto_Angeschlossen` | `1` = angeschlossen |
| `soc_at_plug_in_name` | Lesen | `EAuto_SOC_bei_Anschluss` | Rest-SOC, % |
| `ready_by_time_name` | Lesen | `EAuto_FertigUm` | Text, z. B. Fertig-Uhrzeit |
| `nominal_power_kw_name` | Lesen | `EAuto_MaxLeistung` | Max. Ladeleistung, kW (oder A → wird umgerechnet) |
| `battery_capacity_kwh_name` | Lesen | `Batteriekapazität_E-Auto` | Akkukapazität, kWh (einzige Quelle für SOC→kWh) |
| `charge_immediate_name` | Lesen | `E-Auto_SOFORT_LADEN` | `1` = Sofort-Laden (Volllast in Loxone; Ernie plant fixen Verbrauch, keine Lade-Sollwerte) |
| `charge_immediate_remaining_name` | Lesen | `Ernie_Restzeit_Sofortladen` | Verbleibende Sofort-Ladezeit in **Sekunden** (Loxone-Countdown; `0` = abgeschlossen) |

Die E-Auto-Freigabe zum Laden liegt bei `loxone_outputs.enable_name` (z. B. `Ernie_EAuto_LadeFreigabe`).

### SwimSpa-Filter — zusätzlich (`swimspa_filter`)

Ergänzende Filterlaufzeit; nativer Duty-Cycle läuft unabhängig. Spec: [swimspa-filter.md](../spec/swimspa-filter.md).

| Config-Pfad | Richtung | Beispiel | Wert |
|-------------|----------|----------|------|
| `loxone_target_hours_name` | Lesen | `Ernie_Swimspa_Filter_Sollstunden` | Verbleibende Filter-Schulden, **Stunden** (Float) |
| `loxone_inputs.power_name` | Lesen | `homie_bwa_spa_filter2` | `0`/`1` — Filter läuft (nativ + Ernie) |
| `loxone_outputs.enable_name` | Schreiben | `Ernie_Swimspa_Filter_Freigabe` | `0`/`1` — Ernie-Freigabe für **Zusatzlauf** |
| `filter_schedule.loxone.native_start_hour_name` | Lesen | `homie_bwa_spa_filter1hour` | Start-Stunde natives Fenster (0–23) |
| `filter_schedule.loxone.native_duration_hours_name` | Lesen | `homie_bwa_spa_filter1durationhours` | Dauer natives Fenster, **Stunden** (Float) |

`verify_loxone_setup` prüft diese Merker, wenn `filter_schedule.enabled: true` bzw. `daily_target_source: loxone_remaining_hours`.

## Event-Trigger (`system.event_triggers`)

Außerplanmäßige Optimierungsläufe in `main.py` (zwischen den Viertelstunden). Konfiguration in `config.json`:

| Feld | Bedeutung |
|------|-----------|
| `id` | Kennung für Logs und `run_trigger` (z. B. `eauto_plugged_in`) |
| `loxone_name` | Merkername im Miniserver |
| `signal_type` | `binary` (0/1) oder `text` oder `analog` (numerisch, z. B. Rest-SOC) |
| `on_change` | `binary`: `any` / `rising` / `falling`; `text`/`analog`: `any` |
| `label` | Anzeigename (optional) |

`verify_loxone_setup` prüft alle konfigurierten Trigger zusätzlich.

## Beispiel-Mapping aus `config/config.example.json`

| Verbraucher (`id`) | Freigabe (Schreiben) | Leistung (Lesen) |
|--------------------|----------------------|------------------|
| `swimspa` | `Ernie_SwimSpa_Freigabe` | `Ernie_Swim-Spa-P_act` |
| `swimspa_filter` | `Ernie_Swimspa_Filter_Freigabe` | `homie_bwa_spa_filter2` (binär) |
| `eauto` | `Ernie_EAuto_LadeFreigabe` | `Ernie_EAuto_P_act` |

Weitere Verbraucher (z. B. Wärmepumpe) nach demselben Muster in `flexible_consumers` ergänzen.

## Lesen vs. Schreiben in `main.py`

| Phase | Aktion |
|-------|--------|
| Einlesen | SOC, Leistungen, PV, Flex-Inputs, E-Auto-Status |
| Optimierung | MILP über 24 h (15-Min-Slots intern) |
| Schreiben | Ziel-SOC, Lade-/Entladeleistung, Steuerbefehl, Freigaben je Slot |

Die App **liest** dieselben Live-Werte für Anzeige; **schreibt** keine Steuersignale (außer indirekt über Sidebar-Änderungen an `config.json`).

Weitere Details: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md).
