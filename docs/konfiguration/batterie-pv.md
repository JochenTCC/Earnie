# PV & Batterie (Live-Szenario)

Diese Parameter beschreiben die physische Anlage und fließen in die MILP-Optimierung ein (Live und Simulation). Konfiguration über Entitäts-Referenzen im **Live-Szenario** (`backtesting_scenarios.json`, gewählt via `live_scenario_id` in `config.json`); technische Werte liegen in `earnie_env/config/components.json` (`batteries[]`, `pv_systems[]`).

Ein Szenario kann **mehrere PV-Anlagen** referenzieren (`pv_system_ids`) und **mehrere Batterien** (`battery_ids`, 2.7.c). Die Prognose und die Optimierung nutzen die **Summe** aller Anlagen bzw. aller gewählten Speicher.

Im **Szenario-Explorer** (Verbrauchsdaten / cons_data) gilt für die PV-Linien:

- **Monatschart:** eine Serie pro **eindeutiger PV-Konfiguration** über alle Szenarien (Summe der Anlagen in dieser Konfiguration). Legende = mit „ + “ verbundene Bezeichnungen, z. B. „Dach Süd“ oder „Dach Nord + Dach Süd“.
- **Wochenchart:** eine Serie pro **eindeutiger PV-Anlage** plus zusätzlich die Mehrfach-Konfigurations-Summen wie im Monatschart (Einzelanlagen-Konfigurationen werden nicht doppelt gezeichnet).
- Farbe der PV-Linien: gelbliche Palette. Die historische Summe aus `cons_data` („PV Ist“) wird in diesen Charts **nicht** angezeigt.


| Parameter               | Einheit  | Quelle                               | Bedeutung                                                                                                                             |
| ----------------------- | -------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| `pv_system_ids`         | —        | Szenario → `components.json`         | Eine oder mehrere Referenzen auf `pv_systems[].id`                                                                                    |
| `battery_ids`           | —        | Szenario → `components.json`         | Eine oder mehrere Referenzen auf **Hausbatterien** `batteries[].id` mit `type: house` (2.7.c; ersetzt `battery_id`). Keine Powerstations. |
| `id` / `id_locked` / `id_provisional_label` | — | `components.json` → `batteries[]` / `pv_systems[]` | Interne ID (EHAL-Slug). Neu/Kopie: zuerst freigegeben (`id_locked: false`, Seed in `id_provisional_label`); erste geänderte **Bezeichnung** setzt `id` aus dem Label und sperrt. Bestehende Einträge ohne Flag gelten als gesperrt. Einmalig: UI-Button „ID aus Bezeichnung übernehmen“. Offline-Batch für schmutzige Envs: `python -m scripts.clean_entity_ids_once --config-dir <config>` (Dry-Run; `--apply` schreibt; optional `--only-copy`). |
| `type`                  | enum     | `components.json` → `batteries[]`    | `house` (Default) oder `powerstation` (2.7.g/h Reserve; Anbindung über manuelles Gerät `mode: reserve`) |
| `backing` / `role` / `attached_consumer_ids` | — | `components.json` → Powerstation | Nur bei `type: powerstation`: `virtual`\|`physical`, `single_use`\|`standby_backup`; `attached_consumer_ids` (Liste) optional — Zuordnung auch über manuelle Geräte `mode: reserve` + `powerstation_id`. Legacy: `attached_consumer_id` = erstes Listenelement. |
| `kind`                  | enum     | `components.json` → `batteries[]`    | Topologie: `battery_inverter` (Automatik/Optimieren) oder `isolated` (nur Laden/Entladen/Standby)                                    |
| `kwp`                   | kWp      | `components.json` → `pv_systems[]`   | Installierte PV-Leistung je Anlage; aufgelöst als Summe `pv_kwp`                                                                      |
| `pv_tilt`               | °        | `components.json` → `pv_systems[]`   | Dachneigung **je Anlage** (bei mehreren Anlagen keine einzelne Globalneigung)                                                         |
| `pv_azimuth`            | °        | `components.json` → `pv_systems[]`   | Ausrichtung je Anlage: `0` = Süd, `-90` = Ost, `90` = West                                                                            |
| `latitude`, `longitude` | °        | `house_profiles.json` (via Szenario) | Standort für PV-Prognose (Forecast.Solar / Open-Meteo)                                                                                |
| `k_push_cent`           | Cent/kWh | `tariffs.json` (Export-Tarif)        | **Einspeisevergütung**                                                                                                                |
| `battery_capacity_kwh`  | kWh      | `components.json` → `batteries[]`    | Nutzbare Speicherkapazität                                                                                                            |
| `battery_max_charge_power_kw` | kW | `components.json` → `batteries[]` | Max. Ladeleistung (2.7.j; ersetzt gemeinsames `battery_max_power_kw`) |
| `battery_max_discharge_power_kw` | kW | `components.json` → `batteries[]` | Max. Entladeleistung (2.7.j) |
| `battery_max_power_kw`  | kW       | `components.json` → `batteries[]`    | **Deprecated:** früher eine Grenze für beide Richtungen; beim Laden in charge/discharge migriert |
| `limits_from_live` | bool | `components.json` → `batteries[]` | Wenn true: Live `get_ess_*` für SOC-Min/Max und Max. Lade-/Entladeleistung (Fallback HK) |
| `battery_efficiency`    | 0–1      | `components.json` → `batteries[]`    | Roundtrip-Wirkungsgrad (Laden/Entladen)                                                                                               |
| `battery_min_soc`       | %        | `components.json` → `batteries[]`    | Untere SOC-Grenze (Schutz)                                                                                                            |
| `battery_max_soc`       | %        | `components.json` → `batteries[]`    | Obere SOC-Grenze                                                                                                                      |
| `threshold_power`       | Anteil   | `components.json` → `batteries[]`    | Relativ zu `max(charge, discharge)` kW (z. B. `0.2` = 20 %). Schwellwert für Modus-Erkennung und Entscheidung Zwangsentladen vs. Automatik |
| `standby_power_kw`      | kW       | `components.json` → `batteries[]`    | Dauerhafte AC-Eigenleistung der Batterie (24/7 Verbrauch in der Optimierung)                                                          |
| `control`               | enum     | `components.json` → `batteries[]`    | Steuerbarkeit der Anlage: `full` (Default) = Zwangsladen/-entladen; `limits_only` = nur Lade-/Entladegrenzen (Automatik/Entladesperre); `read_only` = Eigenverbrauch ohne Setpoints. Eigenschaft der Installation — gilt auch für Simulation / Backtesting / Business Case. |
| `timezone_name`         | —        | `house_profiles.json`                | IANA-Zeitzone für astronomische Sonnenzeiten; wird aus `land` abgeleitet (`AT`→`Europe/Vienna`, `DE`→`Europe/Berlin`, `CH`→`Europe/Zurich`); siehe `planning_horizon` |
| `netznutzung_arbeitspreis_cent_kwh` | Cent/kWh | `house_profiles.json` | Netznutzung Arbeitspreis netto (ohne USt); unabhängig vom Lieferantentarif                                                     |


### Virtuelle Powerstation (Carve-out)

Bei `type: powerstation` und `backing: virtual` ist die Powerstation **kein eigener Speicher**, sondern ein kWh-Carve-out auf der ersten Hausbatterie (`type: house`). Im Hauskonfigurator → Batterien sind dann nur noch sichtbar:

- Bezeichnung, Typ, Backing, Rolle, **Angeschlossene Verbraucher** (Mehrfachauswahl)
- **Kapazität (kWh)** = max. Reserve / Carve-out-Größe (nicht Packgröße)

Mehrere manuelle Geräte können dieselbe virtuelle Powerstation nutzen: gemeinsame Energiereserve (Ziel-kWh = Summe der Gerätebedarfe, begrenzt durch Kapazität); Trigger von jedem angeschlossenen Gerät.

**Release-Trigger (2.7.p, ODER):** digitales `consumer.{slug}.sens_consumer_active` (0/1 „Gerät läuft“, VO/Merker `Earnie_Verbraucher_<Slug>_Aktiv`), **oder** Leistungs-Schwelle auf `consumer.{slug}.sens_power_act` (Binding ggf. noch `flex.{slug}.*`), **oder** bei physischer PS die Ausgangsleistung `ess.{id}.sens_ess_power`, **oder** Button auf **Manuelle Geräte**. Solange ein Gerät aktiv ist, wird die gehaltene Reserve freigegeben (SoC-Floor der Hausbatterie fällt). Nach dem Lauf wird Restvorrat weiter abgebucht; danach Nachladen **preisoptimal** mit harter Frist **24 h**.

Ausgeblendet und beim Speichern/Normalisieren von der Hausbatterie übernommen (bzw. feste Defaults, falls keine Hausbatterie existiert): Max. Lade-/Entladeleistung, Wirkungsgrad, SoC-Grenzen, Leistungs-Schwelle, Standby, Topologie, Steuerbarkeit, `limits_from_live`, Verschleiß. Entladeleistung der virtuellen Powerstation wird immer `0` gesetzt; Verschleiß bleibt aus (Zyklen zählen auf der Hausbatterie).

Physische Powerstations (`backing: physical`) behalten das volle Batterie-Formular.

### Standby-Backup (`role: standby_backup`, 2.7.h)

Für Dauerläufer (PC, Router, NAS, Hub, …) ohne einzelnen Lauf-Trigger: Earnie schaltet die Versorgung der angeschlossenen Verbraucher **preisgetrieben** zwischen Netz-Pass-Through und Batterie-Insel um (`set_ess_source_select`: `0` = Netz, `1` = Batterie). In günstigen Slots darf die Powerstation parallel laden (`set_ess_charge_power_limit`).

- **Nur `backing: physical`:** Virtuelle Standby-Instanzen werden zur Laufzeit übersprungen (kein geschützter Floor auf der Hausbatterie — ggf. globales `battery_min_soc` erhöhen).
- **Harte Voraussetzung:** Capability `supports_ess_source_select` und Mapping von `set_ess_source_select` (EcoFlow: HA-Switch `switch.<device>_grid_bypass`; bei `ehal.backend=loxone` Merker `Earnie_Speicher_Quellenwahl` → Bridge zu HA, siehe [EcoFlow Delta 3](../einrichtung/ecoflow-delta3-loxone.md)).
- **Quellenwahl vs. Ladegrenzen:** `set_ess_source_select` darf das **Anlagen-**Binding nutzen (Plant-Merker / Plant-HA-Entity — EcoFlow-Bridge). `set_ess_charge_power_limit` / `set_ess_discharge_power_limit` der physischen Powerstation brauchen ein **eigenes** Binding an der Powerstation und greifen **nicht** auf die Hausbatterie-Mappings zurück (sonst würden Haus-Lade-/Entladegrenzen überschrieben).
- Reserve-Größe: angeschlossene Last × teure Stunden im Horizont (kein Energie-pro-Lauf-Lernen wie bei `single_use`).

Live-PV-Leistung kommt über `plant.ehal_bindings.sens_pv_production_active`. Die Intervallenergie für `cons_data` (`pv_kwh_interval`) wird aus der Leistung integriert — ein kumulativer Loxone-PV-Zähler wird nicht mehr verwendet.

## Topologie (`kind`, 2.7.c)

| Wert | Product modes | Wire |
|------|---------------|------|
| `battery_inverter` (Default) | optimizing / charging / discharging | Design C1 inkl. Automatik (`set_ess_mode = 0`) |
| `isolated` | charging / discharging / standby | Nie Automatik; Hold als Standby/Entladesperre |

EHAL-Bindings je Batterie: Pattern B `ess.{slug}.*` in `batteries[].ehal_bindings`. In [EHAL-Com](../ui/ehal-com.md) erscheinen Hausspeicher und **physische** Powerstations als Mapping-Entities; **virtuelle** Powerstations haben kein eigenes Binding (nutzen die Hausbatterie). Speichern schreibt `components.json`, nicht `house_profiles.json`. Die Anlagen-Zeile behält nur die gemeinsame Quellenwahl `set_ess_source_select` (`Earnie_Speicher_Quellenwahl` für die EcoFlow-Bridge). Übrige ESS-Felder gehören zur Batterie-Zeile; Loxone-Mehrspeicher-Merker mit Slug-Infix `Earnie_Batterie_<Slug>_…`. Einmal-Migration plant-flach → Batterie: `python -m scripts.migrate_ess_bindings_once --config-dir <config>`.

## Steuerbarkeit (`control`)

| Wert | MILP | Live-Setpoints |
|------|------|----------------|
| `full` | Netzladen und Batterie-Export erlaubt | Zwangsladen / Zwangsentladen / Entladesperre / Automatik |
| `limits_only` | Nur PV-Überschuss laden, nur Hauslast decken | Nur Automatik / Entladesperre (Lade-/Entladegrenzen) |
| `read_only` | Eigenverbrauch-Kopplung (kein freier Fahrplan) | Keine ESS-Setpoints |

Wenn `control` mehr verlangt als das EHAL-Mapping hergibt (z. B. `full` ohne `set_ess_active_power` und ohne `plant.ha_ess_force`), warnt EHAL-Com. Huawei ohne Wirkleistungs-Entity: optional `plant.ha_ess_force` (`driver: huawei_solar`, `device_id`, `duration_min`) — siehe [EHAL-Spec](../spec/ehal.md) und [EHAL-Com](../ui/ehal-com.md).

Einspeise-„unconstrained“-Wert = PV-kWp-Summe + Summe der Max-Entladeleistung aller gewählten Hausbatterien mit `control = full`. Powerstations (`type: powerstation`) zählen nicht mit — sie speisen nicht ins Hausnetz zurück.


## SOC-Verhalten

Der Parameter `battery_wear` kann niedrigere End-SOCs wirtschaftlich bestrafen (weicher Anreiz, unabhängig vom Modus). Der Block liegt am `components.json` → `batteries[]`-Eintrag, nicht mehr global in `config.json`.

Block `planning_horizon` in `config.json`:

```json
"planning_horizon": {
  "mode": "sunrise_window"
}
```

Details: [Spezifikation Sunset-Planungshorizont](../spec/planning-horizon-sunset.md).

## Batterieverschleiß (`battery_wear`)

Lineares Amortisationsmodell in der MILP-Zielfunktion. Pro kWh Durchsatz (Laden **oder** Entladen) wird ein Verschleiß-Anteil addiert:

`ct/kWh = cycle_cost_fraction × replacement_cost_euro / expected_cycles / battery_capacity_kwh × 100`

Beispiel (5 kWh, 1500 €, 6000 Zyklen, 50 % zyklenbedingt): **2,5 ct/kWh**.


| Parameter               | Bedeutung                                                                       |
| ----------------------- | ------------------------------------------------------------------------------- |
| `enabled`               | `false` = kein Verschleiß-Term (explizit aus); `true` = Parameter unten Pflicht |
| `replacement_cost_euro` | Ersatzkosten der Batterie                                                       |
| `expected_cycles`       | Angenommene Vollzyklen bis Ersatz                                               |
| `cycle_cost_fraction`   | Anteil der Kosten durch Zyklen (Rest: Kalenderalterung)                         |

Editierbar im Hauskonfigurator unter **Batterien** per Checkbox "Verschleiß berücksichtigen" (schaltet die drei Parameter frei); Direktbearbeitung von `components.json` bleibt weiterhin möglich.




## Live-Szenario vs. `config.json`

In der App (Seite **Szenarienkonfigurator**) werden Entitäts-Referenzen für das Live-Szenario gewählt (PV und Batterien als Mehrfachauswahl). Gespeichert wird das Live-Szenario in `backtesting_scenarios.json` (`live_scenario_id` in `config.json`, Standard: `live`). PV- und Batterie-Entitäten selbst pflegt man im **Hauskonfigurator**. Die Bezeichnung des Live-Szenarios ist fest.

## Szenarien

Zum Vergleich von Varianten zum Live-Szenario (größerer Speicher, mehrere PV-Anlagen, anderer Strom-Tarif, ...) ohne Produktiv-Änderung: weitere Einträge in `backtesting_scenarios.json` (siehe [Überblick](overview.md)).
