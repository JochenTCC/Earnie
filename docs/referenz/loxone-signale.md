# Loxone-Signale — Referenz

Für **Greenfield / Earnie-Library (2.4.n)** gelten die **gefrorenen** Merkernamen in [`share/loxone/greenfield_device_map.json`](../../share/loxone/greenfield_device_map.json) und [`share/loxone/recipes/`](../../share/loxone/recipes/) (z. B. `Ernie_WP_P_act`, `Ernie_Batterie_SoC`). Bestehende Anlagen dürfen abweichende Bezeichnungen behalten — in `ehal_bindings` muss die Adresse exakt dem Miniserver-Namen entsprechen.

**Begriffsklärung (Smarthome-Merker):** Die **Adresse** (Zeichenkette, z. B. `Ernie_WP_P_act`) ist ein *Smarthome-Merker*. Die **Rolle** ist der EHAL-Feldname (`sens_ess_soc`, `flex.power_name`, …) in `ehal_bindings`. Live-Backend bleibt vorerst Loxone-HTTP; Legacy-Schlüssel `loxone_*` / `*.loxone` können nach Migration noch dual-gelesen werden. Nicht verwechseln mit Chart-Markern oder `earnie_role` (Bekannt/Gesteuert/Manuell).

**Pattern B (Library):** Virtual HTTP In pollt Earnie (Heartbeat + Sollwerte) → benannte Merker; Earnie Core schreibt parallel weiter per `/jdev/sps/io/{name}`. Entwürfe: [`share/loxone/templates/`](../../share/loxone/templates/).

Prüfung aller konfigurierten Signale:

```powershell
.venv\Scripts\python.exe -m scripts.verify_loxone_setup
.venv\Scripts\python.exe -m scripts.verify_swimspa_filter_live
```

## Rolle ↔ Entity (Überblick)

| Entity / Bereich | Speicherort | Typische EHAL-Felder / Rollen |
|------------------|-------------|-------------------------------|
| Anlage (Batterie, PV, Netz, Steuerbefehl, Hauslast) | `house_profiles.json` → `plant.ehal_bindings` | `sens_ess_soc`, `sens_pv_production_active`, `sens_ess_power`, `sens_grid_power_active`, `sens_power_consumers`, `set_ess_*` |
| Event-Trigger (Anlage) | `house_profiles.json` → `plant.event_triggers[]` | `ehal_field` (+ `signal_type`, `on_change`, `label`); Adresse aus Binding |
| Event-Trigger (Verbraucher) | `consumers[].event_triggers[]` | gleiches Schema, Scope = Consumer-Entity |
| Wärmepumpe / Flex / Thermal | `consumers[].ehal_bindings` | `flex.power_name`, `flex.enable_name`, `flex.power_setpoint_name` |
| E-Auto (`ev`) | `consumers[].ehal_bindings` | `sens_evcs_*`, `get_evcs_*`, `set_evcs_*` |

Bearbeitung in der UI: **nur** unter **Daemon Control → EHAL-Com → Loxone Struktur → EHAL Mapping** (Entity wählen). Der Hauskonfigurator editiert keine Merker-Adressen mehr.

## Zentrale Signale (`plant.ehal_bindings`)

Greenfield-Namen (2.4.n). Bestehende Prod-Namen (z. B. `B004-Battery_SOC`) bleiben gültig, wenn sie in `ehal_bindings` stehen. Netz/PV/Batterie-**Leistung** bevorzugt über EFM-Zähler-Bezeichnung.

| EHAL-Feld | Richtung | Greenfield-Name | Wert / Einheit |
|-----------|----------|-----------------|----------------|
| `sens_ess_soc` | Lesen | `Ernie_Batterie_SoC` | Batterie-SOC, % |
| `sens_pv_production_active` | Lesen | `Ernie_PV_Leistung` (oder EFM Production) | PV-Leistung, kW |
| `sens_ess_power` | Lesen | `Ernie_Batterie_Leistung` (oder EFM Storage) | Batterie; EHAL: +Entladung |
| `sens_grid_power_active` | Lesen | `Ernie_Netzleistung` (oder EFM Grid) | Netz: +Bezug, kW |
| `sens_power_consumers` | Lesen | (optional) | Hauslast; sonst Ableitung |
| `set_ess_active_power` | Schreiben | `Ernie_Batterie_Sollleistung` | Forced Leistung, kW; `+` Entladung, `−` Ladung |
| `set_ess_charge_power_limit` | Schreiben | `Ernie_Ladegrenze` | Max. Ladeleistung (echte Grenze) |
| `set_ess_discharge_power_limit` | Schreiben | `Ernie_Entladegrenze` | Max. Entladeleistung (echte Grenze) |
| `set_ess_mode` | Schreiben | `Ernie_Steuerbefehl` | Modus-Hinweis (Huawei); OpenEMS ignoriert |
| *(Watchdog)* | Lesen | `Ernie_Heartbeat` | Pattern B; kein EHAL-Feld |

Legacy-Rollenamen (`soc_name`, `pv_power_name`, …) in `loxone_blocks` werden beim Migrate nach `plant.ehal_bindings` übernommen und danach aus der Config entfernt (leeres `loxone_blocks` entfällt; **2.4.m**).

## Flexible Verbraucher — `ehal_bindings` am Consumer

Live-Steuerung kommt aus dem aktiven Hausprofil (`house_profiles.json`). Nach Cutover liegen Merker unter `ehal_bindings` mit EHAL-Feldnamen; Legacy-Nester (`loxone_inputs` / `charging_schedule.loxone`) bleiben nur noch dual-read bis Migration.

### Flex / Thermal (Stub `flex.*`)

| EHAL-Feld | Richtung | Greenfield / Beispiel | Wert |
|-----------|----------|------------------------|------|
| `flex.power_name` | Lesen | WP: `Ernie_WP_P_act`; Generic: `Ernie_Verbraucher_Leistung`; oder EFM Load | kW oder 0/1 |
| `flex.enable_name` | Schreiben | WP: `Ernie_WP_Freigabe`; Generic: `Ernie_Verbraucher_Freigabe` | `0`/`1` |
| `flex.power_setpoint_name` | Schreiben | `Ernie_Verbraucher_Ziel_kW` (optional) | kW-Sollwert |

SwimSpa u. Ä. behalten projektspezifische Namen (z. B. `Ernie_SwimSpa_Freigabe`), sofern in `ehal_bindings` gesetzt.

### E-Auto (Prefix `Ernie_EAuto_`)

| EHAL-Feld | Richtung | Greenfield-Name | Wert |
|-----------|----------|-----------------|------|
| `flex.power_name` | Lesen | `Ernie_EAuto_P_act` (oder EFM Load) | kW |
| `sens_evcs_connected` | Lesen | `Ernie_EAuto_Angeschlossen` | `1` = angeschlossen |
| `sens_evcs_soc_act` | Lesen | `Ernie_EAuto_SOC` | Aktueller SOC, % |
| `sens_evcs_bat_capacity` | Lesen | `Ernie_EAuto_Kapazitaet` | kWh |
| `get_evcs_nominal_current` | Lesen | `Ernie_EAuto_MaxStrom` | A |
| `get_evcs_ready_by_time` | Lesen | `Ernie_EAuto_FertigUm` | Text / Uhrzeit |
| `get_evcs_limit_soc` | Lesen | (optional) | Ladeziel-SOC % |
| `set_evcs_max_current` | Schreiben | `Ernie_EAuto_Soll_A` | Soll-/Maxstrom A |
| `set_evcs_mode` | Schreiben | `Ernie_EAuto_Modus` | `pv` \| `now` |

Zusätzlich Pflichtfeld **`min_power_kw`** am Verbraucher. SwimSpa-Filter-Overrides können noch unter `swimspa_filter_bindings` liegen (Bridge-Defaults); Pflege der Haupt-Merker über EHAL-Com.

## Event-Trigger (an Entities)

Außerplanmäßige Optimierungsläufe in `main.py` (zwischen den Viertelstunden). Konfiguration in `house_profiles.json` an **Plant** oder **Verbraucher** — **nicht** mehr unter `config.json` → `system.event_triggers`.

| Feld | Bedeutung |
|------|-----------|
| `id` | Kennung für Logs und `run_trigger` (z. B. `eauto_plugged_in`) |
| `ehal_field` | EHAL-Feld derselben Entity; Adresse aus `ehal_bindings` |
| `signal_type` | `binary` (0/1) oder `text` oder `analog` |
| `on_change` | `binary`: `any` / `rising` / `falling`; `text`/`analog`: `any` |
| `label` | Anzeigename (optional) |

`verify_loxone_setup` prüft alle aggregierten Trigger.

## Beispiel-Mapping

| Verbraucher (`id`) | Steuerung (Schreiben) | Leistung (Lesen) |
|--------------------|----------------------|------------------|
| `swimspa` | `flex.enable_name` → `Ernie_SwimSpa_Freigabe` | `flex.power_name` → `Ernie_Swim-Spa-P_act` |
| `eauto` | `set_evcs_max_current` / `set_evcs_mode` | `sens_evcs_*` / `flex.power_name` |
| `wp_heating` | `flex.enable_name` → `Ernie_WP_Freigabe` | `flex.power_name` → `Ernie_WP_P_act` |

## Lesen vs. Schreiben in `main.py`

| Phase | Aktion |
|-------|--------|
| Einlesen | SOC, Leistungen, PV, Flex-Inputs, E-Auto-Status |
| Optimierung | MILP über 24 h (15-Min-Slots intern) |
| Schreiben | ESS-Limits / Modus, Freigaben / EV-Strom je Slot |

Die App **liest** dieselben Live-Werte für Anzeige; **schreibt** Steuerwerte nur im Live-Modus. Merker-Zuordnung: [EHAL-Com](../ui/ehal-com.md).

Weitere Details: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md).
