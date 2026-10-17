# PV & Batterie (Live-Szenario)

Diese Parameter beschreiben die physische Anlage. Sie fließen in die MILP-Optimierung ein, im Live-Betrieb ebenso wie in der Simulation.

- **Live-Szenario:** Es enthält die Entitäts-Referenzen (`backtesting_scenarios.json`, gewählt über `live_scenario_id` in `config.json`).
- **Technische Werte:** Sie liegen in `earnie_env/config/components.json` (`inverters[]`, `batteries[]`, `pv_systems[]`).

Ein Szenario kann **mehrere PV-Anlagen** (`pv_system_ids`) und **mehrere Batterien** (`battery_ids`) referenzieren. Prognose und Optimierung rechnen mit der **Summe** aller Anlagen bzw. aller gewählten Speicher. Welche Wechselrichter beteiligt sind, ergibt sich aus `inverter_id` an PV-Anlage und Batterie. Im Szenario gibt es dafür kein eigenes `inverter_ids[]`.

Im **Szenario-Explorer** (Verbrauchsdaten / cons_data) gilt für die PV-Linien:

- **Monatschart:** Je **eindeutiger PV-Konfiguration** über alle Szenarien erscheint eine Serie (Summe der Anlagen in dieser Konfiguration). Die Legende verbindet die Bezeichnungen mit „ + “, z. B. „Dach Süd“ oder „Dach Nord + Dach Süd“.
- **Wochenchart:** Je **eindeutiger PV-Anlage** erscheint eine Serie, zusätzlich die Summen der Mehrfach-Konfigurationen wie im Monatschart. Konfigurationen mit nur einer Anlage werden nicht doppelt gezeichnet.
- **Farben:** Die PV-Linien nutzen eine gelbliche Palette. Die historische Summe aus `cons_data` („PV Ist“) zeigen diese Charts **nicht** an.


| Parameter | Einheit | Quelle | Bedeutung |
| --------- | ------- | ------ | --------- |
| `pv_system_ids` | – | Szenario → `components.json` | Eine oder mehrere Referenzen auf `pv_systems[].id` |
| `battery_ids` | – | Szenario → `components.json` | Eine oder mehrere Referenzen auf **Hausbatterien** `batteries[].id` mit `type: house` (ersetzt `battery_id`). Powerstations sind hier nicht zulässig. |
| `id` / `id_locked` / `id_provisional_label` | – | `components.json` → `inverters[]` / `batteries[]` / `pv_systems[]` | Interne ID (EHAL-Slug / Kennung). Neue Einträge und Kopien starten mit freigegebener ID (`id_locked: false`, Vorschlag in `id_provisional_label`). Die erste geänderte **Bezeichnung** setzt `id` aus dem Label und sperrt die ID. Bestehende Einträge ohne Flag gelten als gesperrt. Einmalig steht der UI-Button „ID aus Bezeichnung übernehmen“ zur Verfügung. Zum einmaligen Bereinigen unsauberer IDs offline: `python -m scripts.clean_entity_ids_once --config-dir <config>` (Dry-Run; `--apply` schreibt; optional `--only-copy`). |
| `type` | enum | `components.json` → `batteries[]` | `house` (Default) oder `powerstation` (Reserve; Anbindung über ein manuelles Gerät mit `mode: reserve`) |
| `backing` / `role` / `attached_consumer_ids` | – | `components.json` → Powerstation | Nur bei `type: powerstation`: `virtual`\|`physical` bzw. `single_use`\|`standby_backup`. `attached_consumer_ids` (Liste) ist optional; die Zuordnung ist auch über manuelle Geräte mit `mode: reserve` + `powerstation_id` möglich. Ältere Konfigurationen: `attached_consumer_id` entspricht dem ersten Listenelement. |
| `inverter_id` | – | `components.json` → `batteries[]` / `pv_systems[]` | Referenz auf `inverters[].id`. Pflicht für Hausbatterien, physische Powerstations und alle PV-Anlagen. Virtuelle Powerstations haben **keinen** Wechselrichter. |
| `kwp` | kWp | `components.json` → `pv_systems[]` | Installierte PV-Leistung je Anlage; die Summe ergibt `pv_kwp` |
| `pv_tilt` | ° | `components.json` → `pv_systems[]` | Dachneigung **je Anlage** (bei mehreren Anlagen gibt es keine gemeinsame Neigung) |
| `pv_azimuth` | ° | `components.json` → `pv_systems[]` | Ausrichtung je Anlage: `0` = Süd, `-90` = Ost, `90` = West |
| `latitude`, `longitude` | ° | `house_profiles.json` (über das Szenario) | Standort für die PV-Prognose (Forecast.Solar / Open-Meteo) |
| `k_push_cent` | Cent/kWh | `tariffs.json` (Export-Tarif) | **Einspeisevergütung** |
| `battery_capacity_kwh` | kWh | `components.json` → `batteries[]` | Nutzbare Speicherkapazität |
| `battery_max_charge_power_kw` | kW | `components.json` → `batteries[]` | Max. Ladeleistung (ersetzt das gemeinsame `battery_max_power_kw`) |
| `battery_max_discharge_power_kw` | kW | `components.json` → `batteries[]` | Max. Entladeleistung |
| `battery_max_power_kw` | kW | `components.json` → `batteries[]` | **Veraltet (deprecated):** früher eine Grenze für beide Richtungen; wird beim Laden der Konfiguration in Lade- und Entladegrenze übertragen |
| `limits_from_live` | bool | `components.json` → `batteries[]` | Bei `true` kommen SOC-Min/Max und max. Lade-/Entladeleistung live aus `get_ess_*` (Fallback: Hauskonfigurator-Werte) |
| `efficiency` | 0–1 | `components.json` → `inverters[]` | Einweg-Wirkungsgrad DC↔AC (**η_inv**), Pflicht. Wirkt auf PV DC→AC und als Teil des Speicherpfads. Migration bestehender Konfigurationen: `python -m scripts.migrate_conversion_efficiency_once --config-dir <config>` |
| `battery_efficiency` | 0–1 | `components.json` → `batteries[]` | Einweg-Wirkungsgrad der Zellchemie (**η_batt**). Optimierung und Simulation nutzen **η_path = η_inv · η_batt** (Roundtrip ≈ η_path²). Früher stand hier ein zusammengefasster Pfad-Faktor; die Migration rechnet η_inv heraus. |
| `battery_min_soc` | % | `components.json` → `batteries[]` | Untere SOC-Grenze (Schutz) |
| `battery_max_soc` | % | `components.json` → `batteries[]` | Obere SOC-Grenze |
| `threshold_power` | Anteil | `components.json` → `batteries[]` | Relativ zu `max(charge, discharge)` in kW (z. B. `0.2` = 20 %). Schwellwert für die Modus-Erkennung und für die Entscheidung zwischen Zwangsentladen und Automatik |
| `standby_power_kw` | kW | `components.json` → `batteries[]` | Dauerhafte AC-Eigenleistung der Batterie (in der Optimierung als Verbrauch rund um die Uhr) |
| `control` | enum | `components.json` → `batteries[]` | Steuerbarkeit der Anlage: `full` (Default) = Zwangsladen/-entladen; `limits_only` = nur Lade-/Entladegrenzen (Automatik/Entladesperre); `read_only` = Eigenverbrauch ohne Sollwerte. Das Feld beschreibt die Installation und gilt deshalb auch für Simulation, Backtesting und Business Case. |
| `regulates_on` | enum | `components.json` → `batteries[]` (nur `type: house`) | Eigener Geräteregler: `grid` = regelt auf den Netzzähler (Eigenverbrauch / Zero-Export, Normalfall); `none` = folgt nur den Sollwerten. **Pflicht** für Hausbatterien, unabhängig von `control`. Powerstations haben dieses Feld nicht. Optional auch an `inverters[]` (dynamisches Einspeiselimit). |
| `timezone_name` | – | `house_profiles.json` | IANA-Zeitzone für die astronomischen Sonnenzeiten. Sie wird aus `land` abgeleitet (`AT`→`Europe/Vienna`, `DE`→`Europe/Berlin`, `CH`→`Europe/Zurich`); siehe `planning_horizon` |
| `netznutzung` | Objekt | `house_profiles.json` | Arbeitspreis der Netznutzung netto (ohne USt): Netzbereich aus dem Katalog (inkl. Zeitregeln SNAP/WiNAP) oder eigener Wert. Unabhängig vom Lieferantentarif, siehe [Preise](preise.md) |


### Virtuelle Powerstation (Carve-out)

Bei `type: powerstation` mit `backing: virtual` ist die Powerstation **kein eigener Speicher**. Sie reserviert einen kWh-Anteil der ersten Hausbatterie (`type: house`), den sogenannten Carve-out. Im Hauskonfigurator → Batterien sind dann nur noch diese Felder sichtbar:

- Bezeichnung, Typ, Backing, Rolle und **Angeschlossene Verbraucher** (Mehrfachauswahl).
- **Kapazität (kWh):** die maximale Reserve bzw. Größe des Carve-outs, nicht die Packgröße.

Mehrere manuelle Geräte können dieselbe virtuelle Powerstation nutzen. Sie teilen sich dann eine Energiereserve: Die Ziel-kWh sind die Summe der Gerätebedarfe, begrenzt durch die Kapazität. Jedes angeschlossene Gerät kann die Freigabe auslösen.

**Freigabe-Auslöser (Release-Trigger, ODER-verknüpft):**

- digitales `consumer.{slug}.sens_consumer_active` (0/1 „Gerät läuft“, VO/Merker `Earnie_Verbraucher_<Slug>_Aktiv`),
- Leistungsschwelle auf `consumer.{slug}.sens_power_act` (Binding ggf. noch `flex.{slug}.*`),
- bei physischer Powerstation die Ausgangsleistung `ess.{id}.sens_ess_power`,
- Button auf der Seite **Manuelle Geräte**.

Solange ein Gerät aktiv ist, gibt Earnie die gehaltene Reserve frei, der SoC-Floor der Hausbatterie sinkt also. Nach dem Lauf bucht Earnie den Restvorrat weiter ab. Danach lädt Earnie **preisoptimal** nach, mit einer harten Frist von **24 h**.

Einige Felder sind ausgeblendet. Beim Speichern bzw. Normalisieren übernimmt Earnie sie von der Hausbatterie, ohne Hausbatterie gelten feste Defaults: Max. Lade-/Entladeleistung, Wirkungsgrad, SoC-Grenzen, Leistungsschwelle, Standby, Steuerbarkeit, `limits_from_live` und Verschleiß. Die Entladeleistung der virtuellen Powerstation ist immer `0`. Der Verschleiß bleibt aus, weil die Zyklen auf der Hausbatterie zählen. Ein `inverter_id` gibt es nicht.

Physische Powerstations (`backing: physical`) behalten das volle Batterie-Formular. Sie bekommen einen **integrierten Powerstation-Wechselrichter** (`owned_by` = Batterie-ID, Abschnitt „Integrierter Wechselrichter“ im Hauskonfigurator). Dieser speist nur die angeschlossenen Verbraucher, nicht den AC-Bus des Hauses. Sein AC-Eingang kann am Netz hängen (einseitige Last), das Gerät ist also **nicht** „netzlos“.

### Standby-Backup (`role: standby_backup`)

Diese Rolle ist für Dauerläufer ohne einzelnen Lauf-Auslöser gedacht (PC, Router, NAS, Hub, …). Earnie schaltet die Versorgung der angeschlossenen Verbraucher **preisgetrieben** zwischen Netz-Durchleitung (Pass-Through) und Batterie-Inselbetrieb um (`ess.<id>.set_ess_source_select`: `0` = Netz, `1` = Batterie). In günstigen Slots darf die Powerstation parallel laden (`set_ess_charge_power_limit`).

- **Nur `backing: physical`:** Earnie überspringt virtuelle Standby-Instanzen zur Laufzeit. Auf der Hausbatterie gibt es dafür keinen geschützten Floor; ggf. das globale `battery_min_soc` erhöhen.
- **Harte Voraussetzung:** Die physische Standby-Backup-Batterie braucht die Capability `supports_ess_source_select` und ein Mapping von `ess.<id>.set_ess_source_select`. Bei EcoFlow ist das der HA-Switch `switch.<device>_grid_bypass`; bei `ehal.backend=loxone` ein Pattern-B-Merker mit Bridge zu HA, siehe [EcoFlow Delta 3](../dev/done/ecoflow-delta3-loxone.md). Anlage und Hausspeicher haben kein Feld für die Quellenwahl.
- **Quellenwahl und Ladegrenzen:** Beide brauchen an der physischen Powerstation jeweils ein **eigenes** Pattern-B-Binding. Sie greifen **nicht** auf die Mappings der Hausbatterie zurück, da sonst deren Lade-/Entladegrenzen überschrieben würden.
- **Reserve-Größe:** angeschlossene Last × teure Stunden im Horizont. Ein Lernen der Energie pro Lauf wie bei `single_use` gibt es hier nicht.

Die Live-PV-Leistung (AC-Summe der Anlage) kommt über `plant.ehal_bindings.sens_pv_production_active`. Fehlt dieses Mapping, kann Earnie die Anlagen-PV als Σ(WR-PV · η_inv) ableiten. Voraussetzung: Alle netzgekoppelten Wechselrichter mit PV sind vollständig über `inv.{id}.sens_inv_power_pv` gemappt (oder alle zugehörigen `pv.{id}.sens_pv_production_active`). Powerstation- und Insel-Wechselrichter (`ac_connection: island`) zählen nicht mit. Unvollständige Mappings führen zu einem Fehler. Optional je PV-Anlage: `pv_systems[].ehal_bindings` mit `pv.{id}.sens_pv_production_active`. Die Intervallenergie für `cons_data` (`pv_kwh_interval`) integriert Earnie aus der Anlagen-Leistung. Ein kumulativer Loxone-PV-Zähler wird nicht mehr verwendet.

## Wechselrichter (`inverters[]`)

PV-Anlagen und Batterien können über `inverter_id` auf denselben Wechselrichter verweisen (n:1). Im Hauskonfigurator gibt es dafür den Tab **Wechselrichter** und eine Auswahl in den PV- und Batterie-Formularen. Die Geräte-Vorlage **EcoFlow Delta 3** legt eine physische Powerstation samt integriertem Powerstation-Hybrid-Wechselrichter in einem Schritt an.

| Feld | Bedeutung |
|------|-----------|
| `type` | `hybrid` (PV + Batterie DC), `pv_string` (nur PV), `battery` (AC-gekoppelter Batterie-Wechselrichter ohne PV-Seite) |
| `ac_connection` | `grid_tied` = AC am Hausbus (Automatik/Optimieren möglich); `island` = speist nur angeschlossene Verbraucher, **nicht** den AC-Bus des Hauses (die PV dieses Wechselrichters zählt nicht in der Hausbilanz). Der AC-Eingang kann am Netz hängen (einseitige Last); `island` beschreibt also die **Bus-Teilnahme** und bedeutet nicht „netzlos“. Ersetzt das frühere `batteries[].kind` (`isolated` ⇒ `island`). |
| `max_ac_power_kw` | Optional: AC-Clipping bzw. Obergrenze der Entladung; ohne Wert gibt es keine Grenze |
| `max_pv_input_kw` | Optional: Obergrenze DC/MPPT |
| `max_ac_charge_kw` | Optional: Netzladen über den Wechselrichter |
| `control` | `full` \| `limits_only` \| `read_only` (wie bei Batterien) |
| `owned_by` | Batterie-ID bei integrierten Wechselrichtern (EcoFlow / physische Powerstation). Betrifft nur Oberfläche und Lebenszyklus: Anlegen, Anzeigen und Löschen geschehen zusammen mit der Batterie. |

**Einmal-Migration** älterer Konfigurationen (`batteries[].kind` oder fehlendes `inverters[]`): `python -m scripts.migrate_inverters_once --config-dir <config>` (mit `--dry-run` ohne Schreiben; ohne `--dry-run` wird geschrieben). Danach `kind` entfernen, da der Loader Restbestände sofort mit Fehler ablehnt.

**EHAL-Bindings:**

- **Batterien:** entity-scoped `ess.{slug}.*` in `batteries[].ehal_bindings`.
- **Wechselrichter:** `inv.{slug}.*` in `inverters[].ehal_bindings`.
- **PV-Anlagen:** optional `pv.{slug}.*` in `pv_systems[].ehal_bindings`.

In [EHAL-Com](../ui/ehal-com.md) erscheinen Hausspeicher, **physische** Powerstations, Wechselrichter und PV-Anlagen als Mapping-Entities. **Virtuelle** Powerstations haben kein eigenes Binding und nutzen die Hausbatterie. Speichern schreibt `components.json`, nicht `house_profiles.json`.

Die Quellenwahl `ess.{slug}.set_ess_source_select` gibt es nur an physischen `standby_backup`-Batterien, nicht in der Anlagen-Zeile. Die übrigen ESS-Felder gehören zur Batterie-Zeile. Loxone-Merker für mehrere Speicher tragen den Slug als Infix: `Earnie_Batterie_<Slug>_…`. Einmal-Migration von anlagenweiten (plant-flachen) Bindings auf die Batterie, inkl. Quellenwahl → Standby-Backup: `python -m scripts.migrate_ess_bindings_once --config-dir <config>`.

## Anlagen-Topologie (Live): drei Fragen

Vor dem Live-Betrieb muss die Wurzel der Bilanz klar sein: ein Zähler, ein Tarif und höchstens ein Regler auf diesen Zähler.

1. **Sitzt der Zähler direkt am Hausanschluss?** → `plant.grid_meter.at_house_connection` in `house_profiles.json` (Hauskonfigurator → Profil / Anlage).
2. **Gibt es nur einen Tarif?** → `plant.grid_meter.single_tariff` (kein zweiter Abrechnungszähler hinter demselben Mapping).
3. **Regelt ein anderes Gerät selbst auf diesen Zähler?** → Hausbatterie mit `regulates_on: grid` (Eigenverbrauch / Zero-Export) oder `none` (folgt nur den Sollwerten). Fremdregler zählen ebenfalls mit; `control: read_only` heißt nur, dass Earnie nicht schreibt.

Im Live-Pfad müssen beide `plant.grid_meter`-Flags `true` sein. Migration bestehender Anlagen:

```text
python -m scripts.migrate_topology_once --config-dir <config-dir>
```

Das Skript setzt `regulates_on: grid` für jede Hausbatterie und legt `plant.grid_meter` mit `true`/`true` an. Danach die drei Fragen bestätigen. Szenario-Explorer und Backtesting sind von den Live-Ablehnungen ausgenommen. Schema-Regeln, etwa eine Batterie an einem `pv_string`-Wechselrichter, gelten überall.

**Live-Bilanz:**

- **Speicherleistung:** Das Anlagen-`sens_ess_power` ist die Summe der gemappten `ess.{id}.sens_ess_power` aller netzgekoppelten Hausbatterien. Ein fehlendes Binding führt zu einem Fehler.
- **PV bei mehreren Wechselrichtern:** Bei gemappter Anlagen-PV und mehreren netzgekoppelten Wechselrichtern mit PV sind entweder vollständige `inv.*`/`pv.*`-Mappings **oder** `plant.pv_covers_all_inverters: true` (Hauskonfigurator) nötig.
- **Abgeleitete Hauslast:** Eine negative Restbilanz unterhalb der Toleranz (`plant.balance_tolerance_pct` / `balance_tolerance_w`, Defaults 5 % / 100 W) gilt als Telemetrie-Fehler. Earnie setzt sie nicht stillschweigend auf `0`.

Details: [EHAL-Spec § Plant topology](../referenz/ehal.md).

## Steuerbarkeit (`control`)

| Wert | MILP | Live-Sollwerte |
|------|------|----------------|
| `full` | Netzladen und Batterie-Export erlaubt | Zwangsladen / Zwangsentladen / Entladesperre / Automatik |
| `limits_only` | Nur PV-Überschuss laden, nur Hauslast decken | Nur Automatik / Entladesperre (Lade-/Entladegrenzen) |
| `read_only` | Eigenverbrauch-Kopplung (kein freier Fahrplan) | Keine ESS-Sollwerte |

Verlangt `control` mehr, als das EHAL-Mapping hergibt (z. B. `full` ohne `set_ess_active_power` und ohne `plant.ha_ess_force`), warnt EHAL-Com. Für Huawei ohne Wirkleistungs-Entity gibt es optional `plant.ha_ess_force` (`driver: huawei_solar`, `device_id`, `duration_min`), siehe [EHAL-Spec](../referenz/ehal.md) und [EHAL-Com](../ui/ehal-com.md).

Die unbegrenzte Einspeiseleistung (Wert „unconstrained“) ergibt sich aus der PV-kWp-Summe plus der Summe der max. Entladeleistung aller gewählten Hausbatterien mit `control = full`. Powerstations (`type: powerstation`) zählen nicht mit, da sie nicht ins Hausnetz zurückspeisen.


## SOC-Verhalten

Der Parameter `battery_wear` kann niedrigere End-SOCs wirtschaftlich bestrafen. Das ist ein weicher Anreiz, unabhängig vom Modus. Der Block gehört zum jeweiligen Eintrag in `components.json` → `batteries[]` und liegt nicht mehr global in `config.json`.

Block `planning_horizon` in `config.json`:

```json
"planning_horizon": {
  "mode": "sunrise_window"
}
```

Details: [Spezifikation Sunset-Planungshorizont](../dev/done/planning-horizon-sunset.md).

## Batterieverschleiß (`battery_wear`)

Die Optimierung nutzt ein lineares Amortisationsmodell in der Zielfunktion. Pro kWh Durchsatz (Laden **oder** Entladen) kommt ein Verschleiß-Anteil hinzu:

`ct/kWh = cycle_cost_fraction × replacement_cost_euro / expected_cycles / battery_capacity_kwh × 100`

Beispiel (5 kWh, 1500 €, 6000 Zyklen, 50 % zyklenbedingt): **2,5 ct/kWh**.


| Parameter | Bedeutung |
| --------- | --------- |
| `enabled` | `false` = kein Verschleiß-Term (explizit aus); `true` = die Parameter unten sind Pflicht |
| `replacement_cost_euro` | Ersatzkosten der Batterie |
| `expected_cycles` | Angenommene Vollzyklen bis zum Ersatz |
| `cycle_cost_fraction` | Anteil der Kosten, der auf Zyklen entfällt (Rest: Kalenderalterung) |

Im Hauskonfigurator unter **Batterien** schaltet die Checkbox „Verschleiß berücksichtigen“ die drei Parameter frei. Direktes Bearbeiten von `components.json` ist weiterhin möglich.



## Live-Szenario vs. `config.json`

Auf der Seite **Szenarienkonfigurator** werden die Entitäts-Referenzen für das Live-Szenario gewählt (PV und Batterien als Mehrfachauswahl). Gespeichert wird das Live-Szenario in `backtesting_scenarios.json` (`live_scenario_id` in `config.json`, Standard: `live`). Die PV- und Batterie-Entitäten selbst werden im **Hauskonfigurator** gepflegt. Die Bezeichnung des Live-Szenarios ist fest.

## Szenarien

Varianten lassen sich mit dem Live-Szenario vergleichen, ohne den Produktivbetrieb zu ändern, etwa ein größerer Speicher, mehrere PV-Anlagen oder ein anderer Strom-Tarif. Dafür weitere Einträge in `backtesting_scenarios.json` anlegen (siehe [Überblick](overview.md)).
