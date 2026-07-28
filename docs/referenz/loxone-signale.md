# Loxone-Signale — Referenz

Alle Namen sind **Beispiele** aus [`share/config/config.example.json`](../../share/config/config.example.json). In der eigenen `earnie_env/config/config.json` (bzw. den Sidecars `house_profiles.json`) müssen sie exakt den virtuellen Eingängen und Merkern im Loxone Miniserver entsprechen.

**Begriffsklärung (Smarthome-Merker):** Die **Adresse** (Zeichenkette, z. B. `Ernie_WP_P_act`) ist ein *Smarthome-Merker*. Die **Rolle** ist der Config-Schlüssel (`power_name`, `soc_name`, …). Live-Backend bleibt vorerst ausschließlich Loxone; JSON-Schlüssel behalten die Präfixe `loxone_*` / `*.loxone`. Nicht verwechseln mit Chart-Markern oder `earnie_role` (Bekannt/Gesteuert/Manuell).

Prüfung aller konfigurierten Signale:

```powershell
.venv\Scripts\python.exe -m scripts.verify_loxone_setup
.venv\Scripts\python.exe -m scripts.verify_swimspa_filter_live
```

## Rolle ↔ Entity (Überblick)

| Entity / Bereich | Speicherort | Typische Rollen (Config-Schlüssel) |
|------------------|-------------|--------------------------------------|
| Anlage (Batterie, PV, Netz, Steuerbefehl) | `config.json` → `loxone_blocks` | `soc_name`, `pv_power_name`, `battery_power_name`, `grid_power_name`, `target_*`, `control_cmd_name` |
| Event-Trigger | `config.json` → `system.event_triggers[]` | `loxone_name` (+ `signal_type`, `on_change`) |
| Wärmepumpe (`thermal_annual`) | Hausprofil `consumers[]` | `loxone_inputs.power_name`, `loxone_outputs.enable_name` |
| E-Auto (`ev`) | Hausprofil | `loxone_inputs.power_name`, `loxone_outputs.power_setpoint_name` / `pv_follow_name`, `charging_schedule.loxone.*` |
| SwimSpa (`thermal_rc`) | Hausprofil | `loxone_inputs.power_name`, `loxone_outputs.enable_name`, `thermal_control.loxone.*` |
| SwimSpa-Filter (Bridge) | optional `swimspa_filter_bindings` am `thermal_rc`-Verbraucher (sonst Bridge-Defaults) | `loxone_target_hours_name`, Filter-`power_name` / `enable_name`, `filter_schedule.loxone.*` |
| Generic (known/manual) | Hausprofil | optional `loxone_inputs.power_name` |

Bearbeitung in der UI: Verbraucher-Merker im **Hauskonfigurator**; Anlagen-Merker und Event-Trigger unter **Daemon Control → EHAL-Com**.

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

## Flexible Verbraucher — Hausprofil bzw. `flexible_consumers[]`

Live-Steuerung kommt aus dem aktiven Hausprofil (`house_profiles.json`, Typen `thermal_annual` / `thermal_rc` / `ev`) und wird bei Bedarf mit Legacy-Einträgen in `flexible_consumers[]` über `legacy_id` überlagert. Wärmepumpe: Profil-id `wp_heating`, `legacy_id` typisch `waermepumpe`, Freigabe `loxone_outputs.enable_name` → z. B. `Ernie_WP_Freigabe`.

### Gemeinsame Signale (SwimSpa, Wärmepumpe, Filter)

| Config-Pfad | Richtung | Beispiel | Wert |
|-------------|----------|----------|------|
| `loxone_inputs.power_name` | Lesen | `Merkername SwimSpa kW` | kW oder 0/1 (siehe `signal_type`) |
| `loxone_outputs.enable_name` | Schreiben | `Ernie_SwimSpa_Freigabe` | `0` gesperrt, `1` Freigabe |

### E-Auto — Schreiben unter `loxone_outputs`

E-Auto nutzt **kein** `enable_name`, sondern Leistungs-Sollwert und PV-Follow-Flag:

| Config-Schlüssel | Richtung | Beispiel | Wert |
|------------------|----------|----------|------|
| `power_setpoint_name` | Schreiben | `Ernie_EAuto_Ziel_kW` | Ziel-Ladeleistung, kW |
| `pv_follow_name` | Schreiben | `Ernie_EAuto_pv_follow` | `0`/`1` — PV-Überschuss bevorzugen |

Zusätzlich Pflichtfeld **`min_power_kw`** am Verbraucher (untere Grenze für den Sollwert).

### E-Auto — Lesen unter `charging_schedule.loxone`

| Config-Schlüssel | Richtung | Beispiel | Wert |
|------------------|----------|----------|------|
| `plugged_in_name` | Lesen | `EAuto_Angeschlossen` | `1` = angeschlossen |
| `soc_at_plug_in_name` | Lesen | `EAuto_SOC_bei_Anschluss` | Rest-SOC, % |
| `actual_soc_name` | Lesen | `Ernie-SOC-Ist-EAuto` | Aktueller SOC, % — bei Erreichen von `target_soc_percent` gilt Ladung als abgeschlossen; solange das Auto angeschlossen ist, wird `ready_by_time_name` (FertigUm) dann ignoriert. Nach Abhängen wird FertigUm wieder ausgewertet (sofern nicht abgelaufen). |
| `ready_by_time_name` | Lesen | `EAuto_FertigUm` | Text, z. B. Fertig-Uhrzeit |
| `nominal_power_kw_name` | Lesen | `EAuto_MaxLeistung` | Max. Ladeleistung, kW (oder A → wird umgerechnet) |
| `nominal_power_voltage_v` | Config | — | Nennspannung für A→kW (unter `charging_schedule` oder `charging_schedule.loxone`; Default 230 V) |
| `nominal_power_phases` | Config | — | Phasenzahl für A→kW (1–3; Default 1) |
| `battery_capacity_kwh_name` | Lesen | `Batteriekapazität_E-Auto` | Akkukapazität, kWh (einzige Quelle für SOC→kWh) |
| `charge_immediate_name` | Lesen | `E-Auto_SOFORT_LADEN` | `1` = Sofort-Laden (Volllast in Loxone; Earnie plant fixen Verbrauch, keine Lade-Sollwerte) |
| `charge_immediate_remaining_name` | Lesen | `Ernie_Restzeit_Sofortladen` | Verbleibende Sofort-Ladezeit in **Sekunden** (Loxone-Countdown; `0` = abgeschlossen) |

### SwimSpa-Filter — zusätzlich (`swimspa_filter`)

Ergänzende Filterlaufzeit; nativer Duty-Cycle läuft unabhängig. Spec: [swimspa-filter.md](../spec/swimspa-filter.md).

Der Filter ist **kein** eigener Hausprofil-Verbraucher. Marker-Overrides liegen optional unter `swimspa_filter_bindings` am zugehörigen `thermal_rc`-Verbraucher (Deep-Merge über Bridge-Defaults in `planning_flex_bridge`). Ohne Bindings gelten die eingebauten Defaults.

| Config-Pfad (unter Bindings bzw. Bridge) | Richtung | Beispiel | Wert |
|-------------|----------|----------|------|
| `loxone_target_hours_name` | Lesen | `Ernie_Swimspa_Filter_Sollstunden` | Verbleibende Filter-Schulden, **Stunden** (Float) |
| `loxone_inputs.power_name` | Lesen | `homie_bwa_spa_filter2` | `0`/`1` — Filter läuft (nativ + Earnie) |
| `loxone_inputs.alternate_binary_power_name` | Lesen | `homie_bwa_spa_filter1` | `0`/`1` — autonome Filtersteuerung (Fallback wenn `filter2` = 0) |
| `loxone_outputs.enable_name` | Schreiben | `Ernie_Swimspa_Filter_Freigabe` | `0`/`1` — Earnie-Freigabe für **Zusatzlauf** |
| `filter_schedule.loxone.native_start_hour_name` | Lesen | `homie_bwa_spa_filter1hour` | Start-Stunde natives Fenster (0–23) |
| `filter_schedule.loxone.native_duration_hours_name` | Lesen | `homie_bwa_spa_filter1durationhours` | Dauer natives Fenster, **Stunden** (Float) |

### SwimSpa Heizung — `thermal_control.loxone` (`swimspa`)

Gemeinsamer Gesamtzähler (Fall B); Heizung wird über binären Indikator erkannt, nicht über separaten kW-Merker:

| Config-Pfad | Richtung | Beispiel | Wert |
|-------------|----------|----------|------|
| `thermal_control.loxone.heating_active_name` | Lesen | `homie_bwa_spa_heating` | `0`/`1` — Heizung aktiv |
| `thermal_control.history_logs.heating_active_csv` | Offline | Loxone-CSV-Export | Optional — bevorzugt für `tune_thermal_model` |
| `thermal_control.history_logs.filter_active_csv` | Offline | Loxone-CSV-Export | Optional — Filteranteil von Heizleistung abziehen |

Jets und weitere Pumpen am Gesamtzähler bleiben unmodelliert (Restlast). Filter weiterhin über `swimspa_filter` und `subtract_consumer_ids`.

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

## Beispiel-Mapping aus `share/config/config.example.json`

| Verbraucher (`id`) | Steuerung (Schreiben) | Leistung (Lesen) |
|--------------------|----------------------|------------------|
| `swimspa` | `Ernie_SwimSpa_Freigabe` (0/1) | `Ernie_Swim-Spa-P_act` (Gesamt inkl. Filter) |
| `swimspa_filter` | `Ernie_Swimspa_Filter_Freigabe` (0/1) | `homie_bwa_spa_filter2` (binär) |
| `eauto` | `Ernie_EAuto_Ziel_kW` + `Ernie_EAuto_pv_follow` | `Ernie_EAuto_P_act` |
| `wp_heating` (`legacy_id` `waermepumpe`) | `Ernie_WP_Freigabe` (0/1) | `Ernie_WP_P_act` |

**Hinweis SwimSpa (Fall B):** `Ernie_Swim-Spa-P_act` misst die **Gesamt**-Leistung (Heizung, Filter, Jets/weitere Pumpen). Filter-Anteil: `subtract_consumer_ids` + `homie_bwa_spa_filter*`. Heizung für thermisches Modell/Kalibrierung: `homie_bwa_spa_heating` (`thermal_control.loxone.heating_active_name`) — kein separater Heiz-kW-Merker in Loxone.

## Lesen vs. Schreiben in `main.py`

| Phase | Aktion |
|-------|--------|
| Einlesen | SOC, Leistungen, PV, Flex-Inputs, E-Auto-Status |
| Optimierung | MILP über 24 h (15-Min-Slots intern) |
| Schreiben | Ziel-SOC, Lade-/Entladeleistung, Steuerbefehl, Freigaben je Slot |

Die App **liest** dieselben Live-Werte für Anzeige; **schreibt** keine Steuersignale. Konfigurationsänderungen erfolgen über die Planungs- und Echtzeit-Seiten (Hauskonfigurator, Szenarienkonfigurator, Manuelle Geräte).

Weitere Details: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md).
