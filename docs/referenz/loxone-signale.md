# Loxone-Signale — Referenz

Alle Namen sind **Beispiele** aus [`config.example.json`](../../config.example.json). In der eigenen `config.json` müssen sie exakt den virtuellen Eingängen und Merkern im Loxone Miniserver entsprechen.

Prüfung aller konfigurierten Signale:

```powershell
python -m scripts.verify_loxone_setup
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

Die E-Auto-Freigabe zum Laden liegt bei `loxone_outputs.enable_name` (z. B. `Ernie_EAuto_LadeFreigabe`).

## Beispiel-Mapping aus `config.example.json`

| Verbraucher (`id`) | Freigabe (Schreiben) | Leistung (Lesen) |
|--------------------|----------------------|------------------|
| `swimspa` | `Ernie_SwimSpa_Freigabe` | `Merkername SwimSpa kW` |
| `eauto` | `Ernie_EAuto_LadeFreigabe` | `Merkername EAuto kW` |

Weitere Verbraucher (z. B. Wärmepumpe) nach demselben Muster in `flexible_consumers` ergänzen.

## Lesen vs. Schreiben in `main.py`

| Phase | Aktion |
|-------|--------|
| Einlesen | SOC, Leistungen, PV, Flex-Inputs, E-Auto-Status |
| Optimierung | MILP über 24 h (15-Min-Slots intern) |
| Schreiben | Ziel-SOC, Lade-/Entladeleistung, Steuerbefehl, Freigaben je Slot |

Die App **liest** dieselben Live-Werte für Anzeige; **schreibt** keine Steuersignale (außer indirekt über Sidebar-Änderungen an `config.json`).

Weitere Details: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md).
