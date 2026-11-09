# Flexible Verbraucher

Ab Version **2.0** liegen steuerbare Verbraucher (SwimSpa, E-Auto, Wärmepumpe, Filter, Generics) primär im **Hausprofil** (`earnie_env/config/house_profiles.json`). Live-Parameter und Bindings stehen dort je Verbraucher unter `consumers[].ehal_bindings`. Der frühere Block `flexible_consumers[]` in `config.json` ist **entfernt**. Ein verbliebener Block (auch `[]`) bricht den Start mit einer Fehlermeldung ab; der Migrations-Assistent (`python -m scripts.migrate_config`) löscht einen leeren Block. Enthält er noch Einträge, bricht die Migration ab: Verbraucher dann zuerst im Hausprofil anlegen und den Block danach löschen. Eine doppelte `id` im Hausprofil ist ein Konfigurationsfehler.

Die Optimierung legt fest, **wann** die Verbraucher laufen. Ob die Anlage technisch laufen kann, entscheidet sie nicht. Die Freigabe an das Smarthome ist ein 0/1-Signal (E-Auto: Leistungs-Sollwert + PV-Follow). Die Feldnamen unten gelten für die aufgelöste Flex-Struktur im Hausprofil.

## Pflichtfelder (je Verbraucher)

| Feld | Bedeutung |
| ---- | --------- |
| `id` / `id_locked` / `id_provisional_label` | Interne Kennung bzw. EHAL-Slug (z. B. `eauto`). Neue Einträge starten freigegeben (`id_locked: false`, Startwert in `id_provisional_label`). Die erste geänderte **Bezeichnung** setzt `id` aus dem Label und sperrt die Kennung. Bestehende Einträge ohne Flag gelten als gesperrt. Einmalig steht der UI-Button „ID aus Bezeichnung übernehmen“ zur Verfügung. |
| `name` / `label` | Anzeigename in Charts und UI |
| `nominal_power_kw` | Nennleistung für die MILP |
| `chart_color_index` | Farbindex 0–7 für Chart 1 und Sankey (siehe [Charts](../ui/charts.md)) |
| `optimizer_enabled` | `false` = von der Optimierung ausgeschlossen |
| `bidirectional` | Nur Typ `ev`, optional (`true`/`false`, fehlt = `false`): Die Wallbox kann entladen (V2G). Fließt mit 3 Punkten in die [Earnie-Points](../einrichtung/betrieb.md#earnie-points) ein. Im Hauskonfigurator: **Wallbox bidirektional (V2G)**. |

## Abwesenheits- / Urlaubsmodus (Live)

<a id="abwesenheitsmodus-live"></a>

Die folgenden Hausprofil-Felder wirken nur in der **Live**-Optimierung; der Szenario-Explorer bleibt unverändert.

| Feld | Ort | Bedeutung |
| ---- | --- | --------- |
| `absent_mode` | Profil | Earnie-Schalter „Abwesend / Urlaub“ |
| `absent_mode_enabled` | Verbraucher | „Inaktiv wenn abwesend“. Bei wirksamem Modus nimmt Earnie diese Verbraucher aus der Live-MILP. Die Haus-Wärme hat das Feld nicht, sie wird über `thermal.absent_mode_enabled` abgesenkt. |
| `thermal.absent_mode_enabled` | Profil (Gebäude / Wärmebedarf) | „Absenken wenn abwesend“. Bei wirksamem Modus bleibt die Haus-Wärme in der Planung, mit abgesenkter Solltemperatur. |
| `thermal.absent_temp_reduction_c` | Profil (Gebäude / Wärmebedarf) | Absenkung in K; Live-Soll = `target_temp_c` − Absenkung. Warmwasser (`persons`) ist dann 0. |
| `plant.ehal_bindings.sens_absent_mode` | Plant | Optionales Smarthome-Signal 0/1, per **oder** mit `absent_mode` verknüpft. Live-Lesen über das aktive EHAL-Backend: Loxone-VO/Merker (Default-Name `Earnie_Abwesend`), HA-Entity (`binary_sensor` / `input_boolean` / …), OpenEMS-Kanal als `componentId/ChannelId` |

Der Modus ist wirksam, sobald der Schalter im Hauskonfigurator **oder** das EHAL-Live-Signal aktiv ist (alle Backends). Der Schalter `absent_mode` wirkt dabei **backend-unabhängig**. Verbraucher mit Opt-in nimmt Earnie aus der Live-MILP-Liste. Die Haus-Wärme bleibt in der Optimierung, mit reduzierter Solltemperatur, wenn „Absenken wenn abwesend“ an ist.

<a id="personen-richtwert-haushaltsstrom"></a>

## Personen und Richtwert Haushaltsstrom (Hausprofil)

Direkt unter dem **Jahresverbrauch** steht im Hauskonfigurator das Feld **Personen im Haushalt** (`persons`, Standard 2). Es gilt für jedes Haus, auch bei ausgeschaltetem „Heizung betrachten“. Earnie nutzt es für den Warmwasserbedarf der Heizung und für einen Richtwert zum Jahresverbrauch.

Darunter vergleicht Earnie den **Haushaltsstrom** des Profils mit dem Richtwert aus SUSI (Energieinstitut Vorarlberg):

| Personen | Richtwert Haushaltsstrom |
| -------- | ------------------------ |
| 1 | 1.700 kWh/a |
| 2 | 3.400 kWh/a |
| 3 | 4.200 kWh/a |
| ab 4 | 4.700 kWh/a |

- **Haushaltsstrom** = Jahresverbrauch minus Haus Wärme, E-Auto und Pool (Typ `thermal_rc`), denn der Richtwert enthält keinen Strom für Heizung, E-Auto oder Pool. Geräte-Verbraucher (z. B. Waschmaschine) gehören zum Haushaltsstrom und bleiben drin. Der Heizstab hat keinen eigenen Jahresverbrauch.
- Weicht der Haushaltsstrom um **mehr als ±40 %** vom Richtwert ab, zeigt Earnie eine Warnung. Sie ist nur ein Hinweis zum Prüfen von Jahresverbrauch, Personenzahl und Verbrauchern; gespeichert wird trotzdem.
- Bei ausgeschaltetem „Heizung betrachten“ plant Earnie die Haus-Wärme nicht und zieht sie nicht ab. Ein Heizungsstrom (z. B. einer Wärmepumpe) steckt dann im Haushaltsstrom; Earnie weist darauf hin.

**USt-Abzug (`vat_deductible`):** Das Hausprofil trägt außerdem das Feld `vat_deductible` (`true` = der Betreiber kann die Vorsteuer abziehen, Standard `false`). Earnie wertet es noch nicht aus und rechnet unverändert; im Hauskonfigurator gibt es dafür noch kein Feld, Speichern behält den Wert aus der Datei.

<a id="gebäude--wärmebedarf-hausprofil"></a>

## Gebäude / Wärmebedarf (Hausprofil)

Die wärmetechnischen Eigenschaften gehören zum Haus, nicht zur Heizung. Im Hauskonfigurator stehen sie im Abschnitt **Gebäude / Wärmebedarf** des Hausprofils, vor den Verbrauchern.

**Schalter „Heizung betrachten“** (`heating_enabled`):

- **Aus** (Standard für ein neues Haus): Abschnitt und Verbraucher „Haus Wärme“ sind ausgeblendet, die Heizung wird nicht geplant. Ihr Verbrauch bleibt in der Grundlast. Wer die Heizung nicht betrachten will, gibt hier nichts ein.
- **An:** Earnie plant die Heizung mit den Gebäudedaten dieses Abschnitts. Den Verbraucher „Haus Wärme“ legt man unter **Verbraucher** an; der Typ ist nur bei eingeschaltetem Schalter wählbar.
- Ausschalten löscht nichts: Gebäudedaten und Haus-Wärme bleiben gespeichert und sind beim Wiedereinschalten unverändert da. Ein Szenario, das für dieses Haus ein Heizsystem wählt, meldet bei ausgeschaltetem Schalter einen Fehler.

| Feld | Bedeutung |
| ---- | --------- |
| `thermal.living_area_m2` | Wohnfläche (m²) |
| `thermal.building_class` | Gebäudeklasse 1–4 (bestimmt den HWB, wenn kein genauer Wert angegeben ist) |
| `thermal.hwb_kwh_m2` | Optional: genauer Heizwärmebedarf (kWh/m²a) laut Energieausweis, bezogen auf die Bruttogrundfläche |
| `thermal.gross_floor_area_m2` | Optional: Bruttogrundfläche BGF (m²). Fehlt sie, rechnet Earnie mit Wohnfläche × 1,25 (siehe [Heizwärme und Gewinne](#heizwaerme-und-gewinne)) |
| `thermal.building_mass` | Bauweise `leicht` / `mittel` / `schwer` (Wärmekapazität nach DIN V 18599-2) |
| `thermal.target_temp_c` | Solltemperatur (°C) |
| `thermal.house_tolerance_c` | Heizband-Toleranz (K) um die Solltemperatur |
| `thermal.heating_limit_c` | Heizgrenze: im Live-Speicherplan kein Raumwärmebedarf oberhalb dieser Außentemperatur. Im Jahresmodell nur Startwert der H-Kalibrierung; dort ergibt sich die Heizpause aus den Gewinnen |
| `thermal.house_heat_loss_kw_per_k` | Optional: Verlustkoeffizient H (kW/K); fehlt er, kalibriert Earnie H aus dem HWB |
| `thermal.solar_gains` | Solare Gewinne durch die Fenster, siehe [Heizwärme und Gewinne](#heizwaerme-und-gewinne) |
| `baseload_internal_gain_factor` | Am Hausprofil: Anteil der Grundlast, der das Haus mitheizt (Standard 0,8) |
| `thermal.absent_mode_enabled`, `thermal.absent_temp_reduction_c` | Absenkung bei Abwesenheit, siehe [Abwesenheitsmodus](#abwesenheitsmodus-live) |
| `persons` | Personen im Haushalt (Warmwasserbedarf); steht direkt am Hausprofil, im Hauskonfigurator neben dem Jahresverbrauch (siehe [Richtwert Haushaltsstrom](#personen-richtwert-haushaltsstrom)) |

```json
{"id": "haus", "heating_enabled": true, "persons": 3,
 "thermal": {"living_area_m2": 140, "hwb_kwh_m2": 55, "building_mass": "mittel",
             "target_temp_c": 21.5, "absent_mode_enabled": true},
 "consumers": [{"id": "wp", "type": "thermal_annual", "heating_system_id": "heating_haus"}]}
```

Fehlende Felder bekommen die Standardwerte aus `house_profiles.schema.json`. Ein Haus hat höchstens eine Haus-Wärme. Gebäudefelder am Verbraucher lehnt Earnie beim Laden ab; ältere Konfigurationen stellt die [Migration](../einrichtung/betrieb.md) um (`dm5.house_thermal`).

<a id="heizwaerme-und-gewinne"></a>

### Heizwärme und Gewinne (SUSI P2)

**Jahres-Heizwärme = HWB × Bruttogrundfläche.** Der HWB im Energieausweis bezieht sich auf die Bruttogrundfläche (BGF), nicht auf die Wohnfläche. Ohne `gross_floor_area_m2` rechnet Earnie wie SUSI mit BGF = Wohnfläche × 1,25. Die Wärmekapazität des Hauses (Bauweise) rechnet weiter mit der Wohnfläche. Ohne genauen HWB gilt der Wert der Gebäudeklasse, ebenfalls je m² BGF.

**Interne Gewinne.** Strom, der im Haus verbraucht wird, wird zum größten Teil zu Raumwärme und senkt den Heizbedarf. Earnie rechnet dafür keine Pauschale in W/m², sondern nimmt die modellierten Verbräuche:

| Quelle | Feld | Standard |
| ------ | ---- | -------- |
| Grundlast (Jahresverbrauch minus modellierte Verbraucher) | `baseload_internal_gain_factor` am Hausprofil; im Hauskonfigurator **Grundlast als Wärme im Haus** | 0,8 |
| Geräte (Typ `generic`) | `internal_gain_factor` am Verbraucher; im Hauskonfigurator **Interner Gewinnanteil** | 0,8 |
| E-Auto (`ev`), Pool (`thermal_rc`), Poolfilter (`pool_filter`) | `internal_gain_factor` | 0 (außen) |
| Haus Wärme (`thermal_annual`), Heizstab | `internal_gain_factor` | immer 0: ihre Wärme ist das Hausmodell selbst |

Stündliche interne Gewinne = Σ Verbraucherleistung × Faktor plus Grundlast × Faktor. Ein Haushalt mit hohem Stromverbrauch heizt sich also stärker mit als ein sparsamer. Die interne Gewinne rechnet Earnie für jedes Haus mit „Heizung betrachten“, auch ohne solare Gewinne.

**Solare Gewinne** (`thermal.solar_gains`, im Hauskonfigurator **Solare Gewinne durch Fenster**):

| Feld | Bedeutung | Standard |
| ---- | --------- | -------- |
| `enabled` | Fenstergewinne einrechnen | neues Haus: an; nach der Migration: aus |
| `window_area_m2.s` / `.e` / `.w` / `.n` | Fensterfläche je Himmelsrichtung (m², senkrecht) | Vorschlag nach SUSI |
| `g_value` | Gesamtenergiedurchlassgrad der Verglasung | 0,6 |
| `frame_shading_factor` | Abminderung für Rahmen, Laibung, Vorsprünge, Verschmutzung | 0,5 |

Gewinn je Stunde = Σ Fensterfläche × g-Wert × Abminderung × Einstrahlung auf die senkrechte Fläche (Open-Meteo, vier Flächen Süd/Ost/West/Nord). Der Vorschlag im Hauskonfigurator folgt dem SUSI-Quader: BGF über 2 Geschosse, Seitenverhältnis 1,5, Geschosshöhe 2,6 m, Fensteranteil der Fassade Süd 20 %, Ost/West 10 %, Nord 6 %. Die Verschattung durch Gelände und Nachbargebäude ist hier noch nicht enthalten.

```json
"thermal": {"living_area_m2": 140, "hwb_kwh_m2": 55, "gross_floor_area_m2": 180,
            "solar_gains": {"enabled": true,
                            "window_area_m2": {"s": 12, "e": 4, "w": 4, "n": 3.5},
                            "g_value": 0.6, "frame_shading_factor": 0.5}},
"baseload_internal_gain_factor": 0.8
```

**H wird mit den Gewinnen kalibriert.** Der HWB ist bereits ein Netto-Wert nach Gewinnen. Earnie bestimmt den Verlustkoeffizienten H deshalb so, dass die Jahres-Heizwärme nach Abzug der Gewinne wieder HWB × BGF ergibt. Der Jahresbedarf bleibt also gleich, er verteilt sich nur anders: mehr Heizung in kalten Nächten und im Winter, weniger an sonnigen Tagen und in der Übergangszeit. Überschüssige Gewinne heizen das Haus über die Solltemperatur hinaus, höchstens um 3 K (darüber wird gelüftet oder verschattet). Ein fest eingetragenes H (`house_heat_loss_kw_per_k`) bleibt unverändert; dann senken die Gewinne den Jahresbedarf.

Die Live-Planung rechnet mit denselben Gewinnen. Die Fenster-Einstrahlung kommt aus der Open-Meteo-Prognose; fällt sie aus, nimmt Earnie die Werte des Vorjahres und schreibt eine Warnung ins Log. Die Grundlast kommt aus der Verbrauchsprognose, die Geräte aus ihren Zeitplänen. Bei einer Heizsystem-Variante im Szenario bleibt die Grundlast die des eingebauten Systems.

Solare Gewinne brauchen stündliche Wetterdaten. Ohne Open-Meteo-Archiv, also nur mit dem Offline-Klima aus Tageswerten, bricht die Berechnung mit einer Meldung ab.

<a id="kuehlung"></a>

### Kühlung (Klimaanlage)

Eine Klimaanlage ist kein eigener Verbraucher, sondern die umgekehrte Wärmequelle des Hausmodells. Sie steht als Block `cooling` am Verbraucher „Haus Wärme“ (`thermal_annual`). Eingeschaltet wird sie mit dem Schalter `cooling_enabled` am Hausprofil, im Hauskonfigurator **Kühlung betrachten** im Abschnitt **Kühlung**.

| Feld | Bedeutung | Standard |
| ---- | --------- | -------- |
| `cooling_enabled` (Hausprofil) | Kühlung im Hausmodell rechnen | aus |
| `cooling.type` | `split`: eigenes Klimagerät (Split oder Monoblock). `heat_pump`: die Wärmepumpe des Heizsystems kühlt (reversibel, nur mit Wärmequelle Wärmepumpe) | Pflicht; im Hauskonfigurator Klimagerät |
| `cooling.seer` | Saisonale Kälteleistungszahl: Kälte je kWh Strom (Datenblatt) | Klimagerät 5,0, Wärmepumpe 4,0 |
| `cooling.cooling_power_kw` | Kälteleistung in kW (thermisch, nicht die Stromaufnahme) | 3,5 |
| `cooling.setpoint_c` | Ab dieser Raumtemperatur kühlt das Gerät (°C) | 26 |

```json
"cooling_enabled": true,
"consumers": [{"id": "haus_waerme", "type": "thermal_annual", "heating_system_id": "heating_haus",
               "cooling": {"type": "split", "seer": 5.0, "cooling_power_kw": 3.5, "setpoint_c": 26}}]
```

So rechnet Earnie:

- Das Hausmodell läuft stündlich mit denselben solaren und internen Gewinnen wie die Heizung. Liegt die Raumtemperatur über dem Sollwert, nimmt die Klimaanlage die überschüssige Wärme heraus, höchstens mit ihrer Kälteleistung. Ein zu kleines Gerät lässt das Haus also wärmer. Strom je Stunde = Kälte / SEER.
- Vorher wird gelüftet: Das Haus kühlt über Fenster und Verschattung bis Solltemperatur + 3 K ab, solange es draußen kühler ist. Die Klimaanlage läuft deshalb vor allem an heißen Tagen, wenn die Außenluft selbst über dem Kühl-Sollwert liegt. Ohne solare Gewinne kühlt sie in Mitteleuropa kaum.
- Der Strom der Klimaanlage ist ein **fester Verbraucher**. Earnie zieht ihn von der Grundlast ab, rechnet ihn stündlich in die Verbrauchsprognose (Live und Szenarien-Explorer) und zeigt ihn im Hauskonfigurator als „Klimaanlage im Hausmodell: … kWh/a Strom“ sowie als eigene Reihe „Klimaanlage“ im Gesamt-Lastverhalten und in den synthetischen Verbrauchsdaten des Szenarien-Explorers. Nach dem Einschalten meldet der Szenarien-Explorer die synthetischen Verbrauchsdaten als veraltet; neu erzeugen. Beim Richtwert Haushaltsstrom zählt er wie die Heizung nicht mit.
- Earnie plant die Klimaanlage noch nicht als flexiblen Verbraucher und schaltet sie im Live-Betrieb nicht. Der Kühlstrom ist nie Teil des Wärmepumpen-Tagesziels.
- „Kühlung betrachten“ ist unabhängig von „Heizung betrachten“. Ist die Heizung aus, rechnet das Hausmodell die Heizung trotzdem mit, damit die Raumtemperatur stimmt; ihr Strom bleibt dann aber in der Grundlast. Die Kühlung braucht das Hausmodell, also einmal ausgefüllte Gebäudedaten und einen Verbraucher „Haus Wärme“.
- In den [Earnie-Points](../einrichtung/betrieb.md#earnie-points) zählt ein Klimagerät wie eine Wärmepumpe (1 Punkt). Eine reversible Wärmepumpe zählt nur einmal.

Bis Datenmodell 5 gab es das Verbraucherfeld `appliance_kind: "air_conditioner"` (Hauskonfigurator **Geräteart**). Die Migration `dm5.house_cooling` entfernt es (siehe [Betrieb](../einrichtung/betrieb.md)).

## Tagesenergie-Ziel

| Feld | Bedeutung |
| ---- | --------- |
| `daily_target_kwh` | Festes 24-h-Ziel in kWh (bei `daily_target_source: config`) |
| `daily_target_source` | `config` = fester Wert / `charging_schedule`; `historical` = Profil aus der Vergangenheit; `loxone` = Live-EHAL-Wert in kWh (Config-Enum-Name historisch); `loxone_remaining_hours` = Live-Schulden in Stunden × `nominal_power_kw` (SwimSpa-Filter); `thermal` = RC-Modell (SwimSpa-Heizung) |
| `min_on_quarterhours` | Mindestlaufzeit pro Einschaltung in 15-Minuten-Slots |
| `path_historical_log` | Historische Leistungs-CSV (Offline → `cons_data`; typisch ein Loxone-Export). Wird aus dem Hausprofil nur für den Pool-Filter übernommen; der Loxone-Log-Import (`integrations/loxone_log_import.py`) dient nur noch Migration und Tests |
| `signal_type` | `power` (kW) oder `binary` (Ein/Aus × `nominal_power_kw`) |
| `log_signal_type` | Optional: abweichendes Format nur für `path_historical_log` |

## Smarthome-Anbindung pro Verbraucher (EHAL)

| Verbraucher | Lesen (EHAL) | Schreiben (EHAL) |
| ----------- | ------------ | ---------------- |
| SwimSpa, Wärmepumpe, Filter | `ehal_bindings` / Leistung (`sens_*` bzw. Flex-Power) | `ehal_bindings` Freigabe (`set_enable` / Flex-Enable, 0/1) |
| E-Auto | EVCS-Telemetrie (`sens_evcs_*`, …) | `set_evcs_max_current`, `set_evcs_mode` / PV-Follow |

Optional lässt sich die Leistung anderer Verbraucher vom Ist-Wert abziehen (SwimSpa − Filter).

Feldnamen und Mapping-UI: [EHAL-Com](../ui/ehal-com.md). Loxone-Default-Namen und VO/VI-Vorlagen: [Loxone-Signale](../referenz/loxone-signals.md).

## Pool: `thermal_control`

Bei `daily_target_source: thermal` leitet das RC-Modell das Tagesenergie-Ziel aus Wassertemperatur und Umgebung ab.

| Feld | Bedeutung |
| ---- | --------- |
| `thermal_control.enabled` | Modell aktiv |
| `thermal_control.setpoint_c` / `tolerance_c` | Soll-Temperatur und Band |
| `thermal_control.water_volume_liters` | Wasservolumen |
| `thermal_control.heat_loss_kw_per_k` | Wärmeverlust pro Kelvin |
| `consumers[].ehal_bindings` | EHAL-Felder am Pool-Verbraucher: `sens_temperature_water`, `get_temperature_water_setpoint`, `get_temperature_tolerance_c`, `sens_heating_active`. Die Außentemperatur liegt hausweit unter `plant.ehal_bindings.sens_temperature_outside`. |
| `thermal_control.history_logs` | CSV-Pfade für die Kalibrierung; optional `heating_active_csv` / `filter_active_csv` statt einer reinen Leistungsschwelle |

Details: [EHAL-Com](../ui/ehal-com.md), [Loxone-Signale](../referenz/loxone-signals.md) (Loxone-Defaults), [SwimSpa Filter](../dev/done/swimspa-filter.md).

## Haus Wärme: Heizsystem (`heating_system_id`)

Der Verbraucher `type: thermal_annual` ist die Heizung des Hauses: Verweis auf das Heizsystem, Solarthermie-Kollektor, Verbrauchsdaten (Zähler-CSV) und Smarthome-Bindings. Die Gebäudedaten nimmt er immer aus dem Hausprofil, siehe [Gebäude / Wärmebedarf](#gebäude--wärmebedarf-hausprofil). Die Wärmeerzeugung steht in einem eigenen Katalog: `heating_systems[]` in `components.json`. Ein Eintrag enthält:

| Feld | Bedeutung |
| ---- | --------- |
| `id`, `label` | Kennung und Bezeichnung des Heizsystems |
| `heat_source` | Hauptwärmequelle, siehe [Wärmequelle](#haus-wärme-wärmequelle-heat_source) |
| `heating_power_kw` | Pflicht, > 0. Heizleistung des Wärmeerzeugers in kW thermisch (Typenschild / Auslegung), für jede Wärmequelle |
| `min_on_quarterhours` | Mindestlaufzeit in Viertelstunden, nur bei Wärmepumpe und Stromheizung |
| `heat_storage` | Optionaler Wärmespeicher, siehe [Wärmespeicher](#haus-wärme-optionaler-wärmespeicher-heat_storage) |
| `parts` | Optionaler Heizstab, siehe [Heizstab](#haus-wärme-heizstab-im-wärmespeicher-parts) |

```json
"heating_systems": [
  {"id": "heating_haus", "label": "Heizsystem Haus",
   "heat_source": {"type": "heat_pump", "heat_pump_type": "erde"},
   "heating_power_kw": 8.2, "min_on_quarterhours": 4,
   "heat_storage": {"volume_liters": 800}}
]
```

**Heizleistung und Eingangsleistung:** Earnie leitet die Eingangsleistung aus Heizleistung und Wirkungsgrad ab: Heizleistung / JAZ bei einer Wärmepumpe, Heizleistung / Nutzungsgrad bei allen anderen Quellen. Im Beispiel sind das 8,2 kW / 4,3 ≈ 1,9 kW elektrisch. Mit dieser elektrischen Leistung plant der Optimierer Wärmepumpe und Stromheizung. Bei Brennstoffen und Fernwärme ist es die Brennstoffleistung. Sie begrenzt nur die Wärme je Stunde in der Jahressimulation, denn diese Quellen plant der Optimierer nicht. Ein Heizsystem ohne Heizleistung lehnt Earnie beim Laden ab; es gibt keinen Standardwert.

**Referenzsystem:** Der Verbraucher verweist mit `heating_system_id` (Pflicht) auf das eingebaute Heizsystem. Live-Betrieb, Grundlast und die Vorschau im Hauskonfigurator rechnen immer mit diesem System. Der Hauskonfigurator legt den Eintrag beim Speichern an (Kennung `heating_<Hausprofil-ID>`) und ändert ihn direkt im Katalog. Am Verbraucher steht nur der Verweis.

- **Ein Haus je Heizsystem:** Ein Heizsystem ist Referenzsystem höchstens eines Hauses, weil eine Änderung sonst auch die Grundlast des anderen Hauses verschiebt. Verweisen zwei Hausprofile auf denselben Eintrag (z. B. von Hand in `house_profiles.json`), lehnt Earnie das Speichern ab.
- **Nur Verweis am Verbraucher:** Die Felder der Wärmeerzeugung (`heat_source`, `heat_storage`, `parts`, `heating_power_kw`, `min_on_quarterhours`) gehören in den Katalog. Stehen sie oder `nominal_power_kw` zusätzlich am Verbraucher, lehnt Earnie die Datei beim Laden ab, statt sie still zu überschreiben.
- **Hausprofil entfernen:** Das Referenzsystem bleibt im Katalog und ist danach eine gewöhnliche Variante (änderbar, im Szenario wählbar, entfernbar).

Im Formular des Verbrauchers „Haus Wärme“ (Bereich **Hausprofil**, nur bei eingeschaltetem „Heizung betrachten“) stehen:

- **Solarthermie-Kollektor:** Fläche, Neigung, Azimut. Sie bleiben am Verbraucher.
- **Heizsystem (Referenzsystem: …):** Wärmequelle, **Heizleistung (kW, thermisch)**, Wärmespeicher und Heizstab; bei Wärmepumpe und Stromheizung zusätzlich die Mindestlaufzeit und darunter die abgeleitete elektrische Leistung („≈ … kW elektrisch bei JAZ …“). Sie landen beim Speichern im Katalogeintrag des Referenzsystems. Dieselben Felder hat das Formular einer Variante im Bereich **Heizsysteme**.
- Darunter die Schätzung für ein Jahr, gerechnet mit den Gebäudedaten des Hausprofils und dem Wetter des letzten vollständigen Jahres am Standort:
  - **Geschätzter Wärmebedarf (kWh_th/a)** als Hauptzahl: die Wärme, die das Heizsystem liefert (Raumwärme und Warmwasser abzüglich Solarthermie). Sie hängt fast nur vom Gebäude ab. Das Heizsystem wirkt nur über die Heizleistung (reicht sie an kalten Tagen nicht, liefert es weniger Wärme) und über den Verlust des Wärmespeichers.
  - **Strombedarf mit diesem Heizsystem (kWh/a)** bei Wärmepumpe und Stromheizung bzw. **Brennstoffbedarf mit diesem Heizsystem (kWh/a Endenergie)** bei Brennstoffen und Fernwärme: Wärmebedarf / JAZ bzw. Nutzungsgrad.

**Heizsystem wechseln:** Das Referenzsystem ändert sich nur hier, im Abschnitt **Heizsystem** des Hauses. Ein anderes Heizsystem aus dem Katalog übernimmt ein Haus nicht; wer eine modellierte Variante eingebaut hat, trägt ihre Werte hier ein. Ändert sich die **Wärmequelle** gegenüber der gespeicherten Datei (z. B. Gas → Wärmepumpe), passen die Verbrauchsdaten des Hauses nicht mehr, denn sie stammen vom bisherigen System. Earnie speichert dann erst nach einer Wahl und zeigt direkt unter der Wärmequelle eine Warnung. Die Buttons nennen die beiden Systeme, im Beispiel Gas → Wärmepumpe:

- **Mit CSV-Messdaten** (Lastprofil des Hauses oder Zähler-CSV der Haus-Wärme): **Messdaten entfernen und zu Wärmepumpe wechseln** (entfernt Lastprofil, Batterie- und Netz-CSV des Hauses sowie die Zähler-CSV der Haus-Wärme; das PV-Profil bleibt) oder **Bei Gas bleiben**.
- **Nur mit Jahresverbrauch:** Jahresverbrauch oben an das neue Heizsystem anpassen und **Zu Wärmepumpe wechseln**, oder **Bei Gas bleiben**. Der Wechsel übernimmt den Jahresverbrauch, wie er oben steht; bei einem Neubau, dessen Jahresverbrauch schon eine Schätzung für das neue Heizsystem ist, den Wert unverändert lassen.

Alte Daten und neues Heizsystem zugleich gibt es nicht. WP-Typ, JAZ bzw. Nutzungsgrad, Leistung, Speicher und Heizstab sind Feinabstimmung und speichern ohne Warnung. Wer die Wärmequelle vor dem Speichern zurückstellt, hat nichts geändert. Eine von Hand bearbeitete `house_profiles.json` prüft Earnie nicht.

**Varianten:** Weitere Heizsysteme entstehen im Hauskonfigurator im Bereich **Heizsysteme**: Heizsystem auswählen (z. B. das Referenzsystem) und **Als neue Variante kopieren**. Dort ist das Referenzsystem eines Hauses nur lesbar, weil eine Änderung die Grundlast dieses Hauses verschiebt. Änderungen an einer Variante speichert Earnie automatisch, sobald die Eingaben gültig sind; eine Heizleistung von 0 kW wird nicht gespeichert. Ein Heizsystem, auf das ein Hausprofil oder ein Szenario verweist, lässt sich nicht entfernen. Die Auswahl im Szenario beschreibt [Heizsystem im Szenario](#heizsystem-im-szenario-heating_system_ids).

<a id="haus-wärme-wärmequelle-heat_source"></a>

### Wärmequelle (`heat_source`)

Jedes Heizsystem hat eine Hauptwärmequelle `heat_source` (Pflicht). Im Hauskonfigurator heißt das Feld **Wärmequelle**.

| Feld | Bedeutung |
| ---- | --------- |
| `heat_source.type` | `heat_pump` (Wärmepumpe), `oil` (Öl), `gas` (Gas), `pellets` (Pellets), `district_heat` (Fernwärme), `wood` (Stückholz) oder `electric_direct` (Stromheizung ohne Wärmepumpe) |
| `heat_source.heat_pump_type` | Nur bei `heat_pump`, Pflicht: `luft`, `erde` (Sole) oder `grundwasser` |
| `heat_source.efficiency` | Optional. Jahresarbeitszahl (JAZ) der Wärmepumpe bzw. Jahresnutzungsgrad der übrigen Quellen. Ohne Angabe gilt der Standardwert der Tabelle unten. |
| `heat_source.fuel_price` | Optional, nur bei Brennstoffen. Preis in der Einheit des Energieträgers. Ohne Angabe gilt der Standardpreis der Tabelle unten. |

**Standardwerte** (Datei `share/config/heat_source_defaults.json`, mit Quellenangabe je Wert):

| Wärmequelle | JAZ / Nutzungsgrad | Energieinhalt | Standardpreis | CO2 (g/kWh) |
| ----------- | ------------------ | ------------- | ------------- | ----------- |
| Wärmepumpe Luft / Erde / Grundwasser | 3,5 / 4,3 / 4,2 | – | Stromtarif | 226 (Strom) |
| Stromheizung | 0,99 | – | Stromtarif | 226 (Strom) |
| Öl | 0,90 | 10 kWh/l | 104,8 ct/l | 344 |
| Gas | 0,95 | 1 kWh/kWh | 10,43 ct/kWh | 249 |
| Pellets | 0,85 | 4.900 kWh/t | 322 €/t | 26 |
| Fernwärme | 0,95 | 1 kWh/kWh | 10,5 ct/kWh | 42 |
| Stückholz | 0,80 | 1.800 kWh/rm | 50 €/rm | 25 |

Quellen: Nutzungsgrade und Energieinhalte aus SUSI, Brennstoffpreise aus dem Heizrechner, CO2-Faktoren aus Hexit (alle Energieinstitut Vorarlberg). Die Brennstoffpreise sind Stand 2022. Für eine belastbare Rechnung den aktuellen Preis in `fuel_price` eintragen.

**Wie rechnet Earnie mit der Wärmequelle?** Die Jahressimulation des Hauses bleibt gleich: Wärmebedarf, Warmwasser und Wärmespeicher laufen unverändert. Die Wärmequelle bestimmt nur, welche Energie dafür nötig ist:

- **Wärmepumpe und Stromheizung:** Strombedarf = gelieferte Wärme / JAZ bzw. Nutzungsgrad. Die elektrische Leistung ist `heating_power_kw` / JAZ bzw. Nutzungsgrad.
- **Brennstoffe:** Brennstoffbedarf (Endenergie) = gelieferte Wärme / Nutzungsgrad. Die Heizung bezieht keinen Strom und ist kein flexibler Verbraucher in der Optimierung. `heating_power_kw` begrenzt die Wärme je Stunde.

Verteilverluste rechnet Earnie nicht zusätzlich ein. Der Wärmeverlust des Gebäudes ist auf den HWB kalibriert, der Speicherverlust ist eigens modelliert.

<a id="haus-wärme-heizstab-im-wärmespeicher-parts"></a>

### Heizstab im Wärmespeicher (`parts`)

Ein Heizstab lädt den Wärmespeicher elektrisch mit Wirkungsgrad 1. Er ist ein Teil des Heizsystems und kein eigener Verbraucher:

```json
"parts": [{"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": 3.0}]
```

- **Nur mit Wärmespeicher:** Ohne `heat_storage` lehnt Earnie den Heizstab beim Laden ab. Eine reine Elektroheizung ohne Speicher ist die Wärmequelle `electric_direct`.
- **Kennung:** In Signalen und Ergebnissen heißt der Heizstab `<Kennung des Verbrauchers>_heating_rod`, z. B. `waermepumpe_heating_rod`.
- **Neben einer Wärmepumpe:** Der Optimierer verteilt die Tageswärme auf Wärmepumpe und Heizstab. Der Heizstab lohnt sich, wenn Strom in einem Zeitfenster weniger kostet als der Strompreis der Wärmepumpe geteilt durch ihre JAZ, z. B. bei negativen Preisen. Die Wärmepumpe braucht dafür die Planung durch den Optimierer (`optimizer_flex` nicht `false`).
- **Neben einem Brennstoff:** Jede kWh Heizstab-Wärme spart Brennstoff im Wert von Brennstoffpreis / Nutzungsgrad. Der Optimierer setzt den Heizstab ein, wenn Strom günstiger ist, z. B. bei PV-Überschuss mit niedriger Einspeisevergütung.
- **Im Szenarien-Explorer:** Der Speicher begrenzt den Heizstab. Er nimmt Heizstab-Wärme auf, bis er zwischen Untergrenze und Sollwert voll ist (Volumen × `tolerance_c`), und gibt sie mit der Wärme wieder ab, die die Hauptquelle laut Jahresmodell liefern würde, gleichmäßig über den Tag verteilt. So bleibt Wärme eines sonnigen Tages für die Folgetage im Speicher, und an einem Tag kann der Heizstab mehr Wärme liefern, als das Haus an diesem Tag braucht. Ein Tag ohne Wärme aus der Hauptquelle hält den Heizstab aus. Der höhere Wärmeverlust eines heißeren Speichers ist nicht berücksichtigt, und der Speicher gilt am Anfang des Heizstab-Betriebs als leer, sein Band also als ganz frei. Beides überschätzt den Nutzen etwas. Neben einer Wärmepumpe bleibt zusätzlich die Tageswärme die Grenze.

#### Heizstab im Live-Betrieb

Live plant den Heizstab nur, wenn alle drei Signale vorhanden sind. Fehlt eines, bleibt er aus und das Log nennt das fehlende Signal:

| Signal | Bedeutung |
|---|---|
| `heatpump.<Kennung>_heating_rod.set_enable` | Freigabe 0/1, schaltet den Heizstab |
| `heatpump.<Kennung>_heating_rod.sens_power_act` oder `.sens_consumer_active` | Gemessene Leistung oder Laufstatus. Ohne Messung zählt der laufende Heizstab als Grundlast. Mit dem Laufstatus rechnet Earnie Status × Nennleistung. |
| `sens_temperature_heat_storage` am Verbraucher | Speichertemperatur, aus ihr rechnet Earnie die freie Kapazität |

Die Signale ordnest du in der EHAL-Zuordnung der eigenen Zeile des Heizstabs zu. Earnie speichert sie am Verbraucher in `heating_rod_ehal_bindings`, nicht im Heizsystem, weil die Verdrahtung zum Haus gehört und das Heizsystem im Szenario austauschbar bleibt.

- **Wie viel:** Höchstens die freie Wärme des Speichers bis zum Sollwert, abzüglich der Wärme, die die Hauptquelle ohnehin liefern muss. Ist der Speicher voll, bleibt der Heizstab aus. Reicht die freie Wärme nicht für eine Viertelstunde Heizstab, bleibt er ebenfalls aus.
- **Wann:** Nur am laufenden Kalendertag, höchstens vier Einschaltungen je Tag. Billige Nachtstunden nach Mitternacht plant Earnie erst nach dem Tageswechsel ein.
- **Neben einer Wärmepumpe:** Sie liefert dieselbe Wärme mit weniger Strom, der Heizstab läuft deshalb selten, z. B. bei negativen Preisen. Beide zusammen können den Speicher dann über die freie Wärme hinaus laden, bis die nächste Messung den Heizstab abschaltet.
- **Neben einem Brennstoff:** Die Kachel „Mit Earnie gespart“ rechnet den Heizstab-Strom als Kosten, die gesparte Brennstoffmenge rechnet sie nicht gegen.

**Sicherheit liegt beim Smarthome:** Earnie gibt den Heizstab nur frei. Den Übertemperaturschutz und das Verhalten beim Ausfall von Earnie muss die Anlage selbst sicherstellen, z. B. über den Sicherheitsthermostat und ein Abschalten, wenn die Freigabe nicht mehr aktualisiert wird. Eine einmal gesetzte Freigabe bleibt sonst stehen, bis Earnie wieder schreibt.

**Kein fester Verbrauch:** Der Heizstab hat keinen eigenen Verbrauch in den Hausdaten, weder als CSV noch als Jahres-kWh. Der Optimierer entscheidet allein, wann er läuft. So bleibt das Heizsystem im Szenario frei austauschbar.

**Mögliche Doppelzählung:** Lief ein Heizstab im Haus während des Messzeitraums (z. B. über eine PV-Überschussregelung), steckt sein Verbrauch im gemessenen Gesamtverbrauch und damit in der Grundlast. Plant der Optimierer den Heizstab im Szenario zusätzlich, zählt dieser Strom doppelt. Earnie nimmt das in Kauf und zeigt dazu keinen Hinweis.

Ältere Entwicklungsstände kannten `heating_rod_profile_csv` und `heating_rod_annual_kwh` am Verbraucher. Earnie lehnt diese Felder beim Laden ab; das Feld aus `house_profiles.json` entfernen.

<a id="haus-wärme-optionaler-wärmespeicher-heat_storage"></a>

### Optionaler Wärmespeicher (`heat_storage`)

Im Heizsystem lässt sich unter `heat_storage` ein **Pufferspeicher** modellieren. Solarthermie und Wärmepumpe speisen den Speicher; Raumheizung und Warmwasser entnehmen Wärme nur aus dem Speicher. Ohne Speicher bzw. bei `volume_liters = 0` gilt das bisherige Modell: Solarthermie wirkt als Tages-Gutschrift auf den WP-Bedarf.

**Temperaturband (Jahressimulation):** Die Speichertemperatur darf zwischen `setpoint_c − tolerance_c` und **95 °C** liegen. Die Wärmepumpe heizt hart nach, wenn die Temperatur unter die Untergrenze fallen würde. Sie speist höchstens bis zum Sollwert (`setpoint_c`) und bleibt darüber aus. Überschusswärme oberhalb des Sollwerts kommt nur von der Solarthermie; deren Eingang wird erst oberhalb von 95 °C begrenzt.

**Verschiebung im Szenarien-Explorer:** Der Szenarien-Explorer darf die Tagesenergie einer Wärmepumpe innerhalb ihres Fensters verschieben, aber nur so weit, wie Speicher und Haus die Wärme puffern können. Die Wärme der Wärmepumpe (und eines Heizstabs daneben) füllt einen Pegel, die Wärme, die das Jahresmodell in derselben Viertelstunde braucht, leert ihn. Der Pegel bleibt in jeder Viertelstunde zwischen 0 und der Kapazität: Speicherband (Volumen × `tolerance_c`) plus Hausmasse (Wohnfläche × Bauweise, wie in Live) × Komfortband `house_tolerance_c`. Ein Haus ohne Speicher puffert also nur über seine Masse, ein Speicher erlaubt immer mehr Verschiebung als keiner. Jedes Fenster beginnt mit dem Pegel, mit dem das vorige endete; das erste Fenster beginnt in der Mitte. Hält das Band nicht (z. B. bei einem kurzen Freigabefenster), plant der Optimierer trotzdem, aber mit hohen Strafkosten für die Wärme außerhalb des Bands. Live plant Haus und Speicher mit eigenem Modell und nutzt diese Grenze nicht; die Standard-Regeln der Referenzleiter (L2) auch nicht. Ohne Speicher und ohne Wohnfläche bricht der Szenarien-Explorer mit einer Meldung ab.

| Feld | Bedeutung |
| ---- | --------- |
| `heat_storage.volume_liters` | Speichervolumen; `≤ 0` oder fehlend = bisheriges Modell ohne Speicher |
| `heat_storage.heat_loss_kw_per_k` | Speicherverlust gegen die Umgebung |
| `heat_storage.setpoint_c` / `tolerance_c` | Sollwert und Untergrenze (`setpoint − tolerance`); Obergrenze für die Wärmepumpe = Sollwert, absolute Obergrenze (Solarthermie) = 95 °C |

**Schichtspeicher → Temperaturen für Earnie:** Hat der Speicher mehrere Fühler, muss das **Smarthome-Backend** eine **äquivalente Temperatur** `T_eq` bilden (volumengewichtetes Mittel). Zusätzlich liefert es den **untersten Fühler** `T_low`. Bindings am `thermal_annual`-Verbraucher: `sens_temperature_heat_storage` (`T_eq`) und `sens_temperature_heat_storage_low` (`T_low`). Anleitung: [Wärmespeicher Schichtung / T_eq](waermespeicher-schichtung-teq.md).

**Live-Band:** Mit aktivem `heat_storage` erzwingt die Live-Optimierung die WP-Freigabe in zwei Fällen:

- **Prognose:** Die Open-Loop-Prognose von `T_eq` würde unter `setpoint − tolerance` fallen (wie in der Jahressimulation).
- **Unterster Fühler:** `T_low` liegt unter derselben Grenze. Diese Freigabe wirkt kurzfristig.

Darüber hinaus darf die Live-Optimierung opportunistisch Energie bis zum Sollwert einplanen. Die Jahressimulation bleibt dagegen reines Bang-Bang an der Untergrenze. Das gilt für jeden regulären Optimierungslauf, auch wenn Earnie die Live-Telemetrie eines Laufs verwirft (z. B. Nullwerte oder negativer Hausverbrauch) und die Matrix bei Prognosewerten bleibt.

**Live-Prognose über den Planungshorizont:** Die Live-Optimierung simuliert den Speicher nur über den Planungshorizont. Startwert ist die gemessene Speichertemperatur. Eingänge sind die Außentemperatur **und die Kollektor-Einstrahlung aus der Open-Meteo-Wetterprognose** (Neigung/Ausrichtung aus `solar_thermal_tilt_deg` / `solar_thermal_azimuth_deg`).

- **Einstrahlungsprognose fällt aus:** Earnie nutzt dann die Werte des letzten vollständigen Kalenderjahres am selben Tag und zur selben Stunde und schreibt eine Warnung ins `earnie.log`. Die verwendete Quelle steht je Lauf in `optimization_history.jsonl` (`collector_solar_source`: `open_meteo`, `fallback_archive_year` oder `none`).
- **Wärmeverlust des Gebäudes:** Ohne eigenen Wert in `house_heat_loss_kw_per_k` kalibriert Earnie den Wärmeverlust (H) aus dem **letzten vollständigen Kalenderjahr** des Open-Meteo-Archivs. Das laufende, unvollständige Jahr fließt nicht ein.
- **Hauskonfigurator beim ersten Öffnen:** Für den Jahresbedarf einer Wärmepumpe (`thermal_annual`) lädt der Hauskonfigurator die Klimadaten des Archivs einmal von Open-Meteo und legt sie im Cache ab (`data/cache/open_meteo_utc`, anderes Verzeichnis über `EARNIE_OPEN_METEO_CACHE_PATH`). Währenddessen zeigt die Seite einen Hinweis. Dauert der Abruf länger als 30 s (langsames Netz, Ratenlimit), bricht Earnie ab und zeigt eine Fehlermeldung; ein erneutes Öffnen versucht es noch einmal.

**Live ohne Wärmespeicher:** Auch ohne `heat_storage` rechnet die Live-Optimierung nur über den Planungshorizont. Die Simulation des Hauses startet bei der Solltemperatur (`target_temp_c`), da es keinen Innentemperatur-Fühler gibt. Sie nutzt die Außentemperatur-Prognose und dieselben Regeln wie die Jahressimulation. Daraus ergeben sich der WP-Bedarf je Viertelstunde und die Tagesziele. Ohne Wohnfläche (`living_area_m2 = 0`) plant Earnie nur Warmwasser und zieht den prognostizierten Kollektorertrag pro Tag ab. Szenario-Explorer und Backtesting nutzen weiterhin die Jahressimulation mit historischem Wetter.

Entwickler-Spec: [thermals-p2.md](../dev/done/thermals-p2.md).

## Heizsystem im Szenario (`heating_system_ids`)

Ein weiteres Szenario kann für die Haus-Wärme ein anderes Heizsystem aus dem Katalog wählen, z. B. Gas statt Wärmepumpe. Im Szenarienkonfigurator steht dafür je Haus-Wärme-Verbraucher die Auswahl **Heizsystem**. Sie bietet das Referenzsystem des eigenen Hauses (Vorgabe) und die Varianten an, also die Heizsysteme, die kein Haus als Referenzsystem nutzt. Das Referenzsystem eines anderen Hauses steht nicht zur Wahl; eine solche Wahl in der Datei lehnt Earnie beim Rechnen ab. Gespeichert wird nur eine abweichende Wahl:

```json
"settings": {"house_profile_id": "haus", "heating_system_ids": {"waermepumpe": "gas_variante"}}
```

- **Grundlast bleibt:** Der Jahresverbrauch des Hauses gilt für das eingebaute Heizsystem. Earnie leitet die Grundlast deshalb immer mit dem Referenzsystem ab und tauscht danach nur die Wärmeerzeugung. Ein Gas-System senkt so den Strombedarf um den Anteil der Wärmepumpe und bringt Brennstoffkosten hinzu.
- **Messdaten:** Hat das Referenzsystem einen eigenen Zähler (Verbrauchs-CSV am Verbraucher), zieht Earnie die gemessenen Werte exakt ab. Ohne eigenen Zähler zieht Earnie das modellierte Profil des Referenzsystems ab; dessen Modellfehler bleibt dann in der Grundlast. Der Szenario-Explorer nennt in den Ergebnissen, welcher Fall vorliegt. Die Variante selbst ist immer modelliert.
- **Referenzspalte:** Szenarien mit unterschiedlichem Heizsystem bekommen getrennte Referenzwerte, weil sich die Hauslast unterscheidet.
- **Heizstab:** Der Szenario-Explorer plant mit dem Heizsystem des Szenarios. Eine Variante mit Heizstab setzt ihn auch dann ein, wenn das Referenzsystem keinen hat; eine Variante ohne Heizstab plant keinen, auch wenn das Referenzsystem einen hat.
- **Verbrauchswarnung:** Die Warnung „Verbrauch weicht >5% von Live-Referenz ab“ entfällt für Szenarien mit einem anderen Heizsystem als die Live-Referenz, weil sich deren Stromverbrauch gewollt ändert. Den Strom des Heizstabs rechnet Earnie vor dem Vergleich heraus.
- **Live-Szenario:** Das Live-Szenario rechnet immer mit dem Referenzsystem. Statt der Auswahl zeigt der Szenarienkonfigurator dort die Zeile „Heizsystem: … (Referenzsystem, Änderung im Hauskonfigurator)“. Eine Auswahl `heating_system_ids` im Live-Szenario lehnt Earnie ab.
- **Andere Häuser:** Eine Wärmepumpen-Variante ist auf die Heizlast eines Hauses ausgelegt. Earnie erlaubt sie trotzdem für ein anderes Haus und prüft die Auslegung derzeit nicht.

## E-Auto und Wallbox: Ladestrom

Seit Datenmodell 6 sind E-Auto und Wallbox getrennt. Die Wallbox steht in `components.json` unter `wallboxes[]`, das E-Auto ist ein Verbraucher im Hausprofil und verweist mit `wallbox_assignment` auf seine Wallbox. Die Ladegrenzen sind **Ströme**, keine Leistungen: Eine Leistung hängt vom Paar ab (Spannung, Phasen), ein Strom ist eine Eigenschaft des Geräts.

| Feld | Ort | Bedeutung |
| ---- | --- | --------- |
| `voltage_v` | Wallbox | Spannung je Phase (meist 230 V) |
| `phases` | Wallbox und E-Auto | Phasen, mit denen das Gerät lädt (1–3) |
| `min_current_a` | Wallbox und E-Auto | Kleinster Ladestrom (A) |
| `max_current_a` | Wallbox und E-Auto | Größter Ladestrom (A) |
| `ehal_bindings` | Wallbox | Lade-Felder: `sens_evcs_active_power`, `sens_evcs_connected`, `get_evcs_nominal_current`, `set_evcs_max_current` (Pflicht), `set_evcs_mode` |
| `wallbox_assignment` | E-Auto | `{"mode": "fixed", "wallbox_id": "<Kennung>"}`: feste Wallbox; `{"mode": "dynamic", "wallbox_ids": ["<Kennung>", …]}`: das Auto darf an diesen Wallboxen laden (siehe [Dynamische Zuordnung](#dynamische-zuordnung-mehrere-autos-mehrere-wallboxen)) |
| `unknown_vehicle` | Wallbox | Nur bei dynamischer Zuordnung: wie die Wallbox ein noch nicht erkanntes Auto lädt (`off`, `pv_only`, `immediate`) |

Für ein Paar aus Auto und Wallbox gilt der **größere** Mindeststrom, der **kleinere** Höchststrom und die **kleinere** Phasenzahl. Daraus rechnet Earnie die Ladeleistung: Strom × Spannung der Wallbox × Phasen. Ein einphasiges Auto an einer dreiphasigen Wallbox lädt also einphasig. Liegt der Mindeststrom des Paars über seinem Höchststrom, haben Auto und Wallbox keinen gemeinsamen Ladestrom: Earnie lehnt das Hausprofil beim Laden mit einer Meldung ab und begrenzt nichts stillschweigend.

Im Hauskonfigurator werden Auto und Wallbox getrennt gepflegt:

- **Bereich Wallboxen:** Bezeichnung, **Spannung (V)**, **Phasen**, **Mindest-** und **Höchst-Ladestrom (A)** der Wallbox. Die Kennung entsteht beim Anlegen aus der Bezeichnung und bleibt danach fest, weil die E-Autos und die IDs `evcs.<Kennung>.*` auf sie verweisen. Unter den Feldern stehen die zugeordneten E-Autos mit dem Ladebereich des Paars. Eine Wallbox, der noch ein E-Auto zugeordnet ist, lässt sich nicht entfernen. Eine Änderung, nach der ein zugeordnetes E-Auto keinen gemeinsamen Ladestrom mehr hätte, speichert Earnie nicht und zeigt eine Meldung.
- **E-Auto im Hausprofil:** **Phasen des Autos**, **Mindest-** und **Höchst-Ladestrom des Autos (A)** und die Auswahl **Wallbox**. Darunter zeigt Earnie die Daten der Wallbox und die Ladeleistung des Paars in kW. **Neue Wallbox für dieses E-Auto anlegen** erzeugt eine Wallbox mit den Grenzen des Autos und 230 V. Ohne Wallbox wird das E-Auto nicht gespeichert.

Innerhalb eines Hausprofils lädt eine Wallbox genau ein E-Auto; zwei E-Autos eines Profils an derselben Wallbox lehnt Earnie mit einer Meldung ab. Dasselbe E-Auto in mehreren Hausprofilen (kopierte Profile) nutzt dieselbe Wallbox. Die Lade-Bindings der Wallbox pflegt die Seite EHAL-Com wie bisher beim E-Auto.

Im Live-Betrieb schreibt Earnie Ladestrom und Lademodus je E-Auto an dessen Wallbox, mit der Spannung der Wallbox und den Phasen des Paars. Die EHAL-IDs tragen dabei die Kennung des E-Autos (`evcs.<E-Auto>.set_evcs_max_current`). Schlägt das Schreiben an einer Wallbox fehl, schreibt Earnie an die übrigen weiter. Unter OpenEMS steht die Komponente je Wallbox im Binding `set_evcs_max_current` (`<Komponente>/SetChargePowerLimit`, z.B. `evcs0/SetChargePowerLimit`); eine Wallbox ohne diese Adresse wird nicht geschrieben.

Ein importiertes E-Auto (Loxone-Import) bekommt beim Speichern eine eigene Wallbox mit seiner Kennung.

### Dynamische Zuordnung: mehrere Autos, mehrere Wallboxen

Ein E-Auto mit **Wallbox-Zuordnung: Dynamisch** hat keine feste Wallbox, sondern eine Liste **Erlaubte Wallboxen**. Earnie findet selbst heraus, an welcher Wallbox es steckt, und plant es erst dann, mit dem Ladebereich dieses Paars. Solange ein dynamisches Auto keiner Wallbox zugeordnet ist, plant Earnie es nicht.

Earnie rät nie. Es ordnet ein Auto nur mit einem dieser Belege zu, in dieser Reihenfolge:

1. **Steckabgleich:** Die Wallbox meldet „angesteckt“, und innerhalb von 5 Minuten meldet genau ein in Frage kommendes Auto über sein eigenes Signal **Auto meldet angesteckt** (`ev.<Kennung>.sens_ev_connected`) dasselbe. Wurde zur selben Zeit noch eine andere Wallbox angesteckt, an der dieses Auto laden dürfte, gilt der Abgleich nicht.
2. **Probeladung:** Earnie stellt die Wallbox für höchstens 2 Minuten auf den Mindeststrom und beobachtet die **Auto-Ladeleistung** (`ev.<Kennung>.sens_ev_charge_power`) der Kandidaten. Lädt genau ein Auto mit mindestens 500 W, ist es zugeordnet. Probeladungen laufen nacheinander, nie an zwei Wallboxen zugleich, und nicht, solange ein Kandidat „Sofort laden“ anfordert. Etwa 0,05 kWh je Probeladung.
3. **Auswahl im Monitor:** Unter **Live-Cockpit → Monitor**, Abschnitt **Wallboxen**, wählst du das Auto für die angesteckte Wallbox aus.

Ein Auto ohne die beiden Signale lässt sich nur im Monitor zuordnen. Im Silent-Modus sendet Earnie keine Sollwerte, also auch keine Probeladung; dann bleiben Steckabgleich und Auswahl. Abstecken an der Wallbox beendet die Zuordnung sofort. Nach einem Neustart des Optimierer-Dienstes beginnt jede Zuordnung von vorn: Ein schon angestecktes Auto wird per Probeladung oder Auswahl neu erkannt.

Die Feldwerte (5 Minuten, 2 Minuten, 500 W, Abfrage alle 10 Sekunden) sind feste, dokumentierte Werte dieser Version.

**Unbekanntes Auto** (`unknown_vehicle`, Bereich **Wallboxen**): Solange an einer Wallbox kein Auto erkannt ist, lädt sie so:

| Wert | Hauskonfigurator | Verhalten |
| --- | --- | --- |
| `off` | Nicht laden | 0 A |
| `pv_only` | Nur PV-Überschuss (PV-Modus der Wallbox) | Earnie setzt den PV-Modus der Wallbox (`set_evcs_mode = pv`) und den Höchststrom; die Wallbox regelt selbst. Braucht das Binding `set_evcs_mode`. |
| `immediate` | Sofort laden (Höchststrom) | Höchststrom der Wallbox, Modus `now` |

Die Angabe ist Pflicht an jeder Wallbox, die ein dynamisches Auto nutzen darf. Lädt an einer Wallbox mit `immediate` ein unbekanntes Auto, während an einer anderen eine Probeladung läuft, kann die Probeladung mehrdeutig werden; dann bleibt die Auswahl im Monitor.

**Regeln beim Laden des Hausprofils:**

- Eine Wallbox ist innerhalb eines Hausprofils entweder einem Auto fest zugeordnet oder für dynamische Autos freigegeben, nicht beides.
- Jede Wallbox eines dynamischen Autos braucht das Binding `sens_evcs_connected`, sonst erkennt Earnie kein angestecktes Auto.
- **Prognose, wenn nicht angeschlossen** ist bei dynamischen Autos noch nicht möglich (`forecast_when_absent: false`); der Hauskonfigurator schaltet sie ab.
- Ein dynamisches Auto trägt keine Lade-Bindings; die stehen an den Wallboxen. Auf der Seite **EHAL-Com** hat jede solche Wallbox eine eigene Zeile (`evcs.<Wallbox>.*`), die Zeile des Autos zeigt nur die Auto-Felder.
- Szenario-Explorer und Backtesting lehnen dynamische Autos in dieser Version mit einer Meldung ab.

## E-Auto: `charging_schedule`

Die folgenden Felder gelten, wenn der Block gesetzt ist und `enabled: true` enthält.

| Feld | Bedeutung |
| ---- | --------- |
| `target_soc_percent` | Ziel-SOC beim Abfahren (meist 100) |
| `charging_efficiency` | Lade-Wirkungsgrad (Netz → Akku) |
| `forecast_when_absent` | Ladebedarf auch dann prognostizieren, wenn das Auto nicht angeschlossen ist (Live- und Config-Pfad) |
| `weekday` / `weekend` | `car_available_from_hour`, `ready_by_hour`, `daily_rest_soc` |
| `loxone` | Legacy-Block (Config-Key): `plugged_in_name`, `ready_by_time_name`, `soc_at_plug_in_name`, `battery_capacity_kwh_name`, `nominal_power_kw_name`, `charge_immediate_*`. Die Adressen gehören heute unter `ehal_bindings` bzw. auf die Seite EHAL-Com. |

**Verspätete Rückkehr:** Startpunkt ist `car_available_from_hour`.

- **Ankunfts-Slot vorbei:** Ist das Auto dann noch nicht angeschlossen, setzt Earnie den internen Connect-Zeitpunkt auf ReadyAt − benötigte Ladezeit − 1 h (mindestens „jetzt“).
- **Frist (ReadyAt):** ReadyAt kommt zuerst aus FertigUm/`get_evcs_ready_by_time`, sonst aus der Config-`ready_by_hour`. Earnie überspringt den Ladezyklus nur ganz, wenn weder Live-FertigUm noch Config-`ready_by` eine gültige Frist liefern oder die Frist schon abgelaufen ist.
- **Vor der geplanten Ankunft:** Der Connect-Zeitpunkt bleibt die Ankunftsstunde (kein „ab jetzt“).
- **Auto nicht angesteckt:** Der **aktuelle** Viertelstunden-Slot bleibt ohne Ladeplan und ohne Live-Sollwert. Zukünftige Slots darf Earnie weiter planen.

Entwickler-Spec: [ev-return-prognosis.md](../dev/done/ev-return-prognosis.md).

Ladeziel in kWh (vereinfacht; die Akkukapazität stammt aus Live-EHAL, wenn gebunden):

`(target_soc_percent − Rest-SOC) / 100 × Akkukapazität_Live / charging_efficiency`

`nominal_power_kw_name` (Legacy unter `charging_schedule.loxone`) überschreibt zur Laufzeit die Höchstleistung des Paars, wenn der Live-Wert lesbar ist.

### SOC-Ziele im Live-Betrieb (EHAL)

| Signal | EHAL-Feld / Default-VO-Name (Loxone) | Bedeutung |
| ------ | ------------------------------------ | --------- |
| Ladeziel (Limit) | `get_evcs_limit_soc` / `Earnie_EAuto_LimitSOC` | Oberes SOC-Ziel bis FertigUm; die Restenergie plant Earnie preisoptimiert. |
| SOC-Min Sofort | `get_evcs_soc_min_immediate` / `Earnie_EAuto_SOCMinSofort` | Sofort-Boden: Earnie erzwingt bis zu diesem SOC eine Lieferung so schnell wie möglich (MILP) und plant danach normal bis zum Limit. Ein Wert ≤ 0 oder ein fehlendes Binding = inaktiv; ein Wert über dem Limit wird auf das Limit begrenzt. |
| Sofortladen | `set_evcs_mode=now` / Legacy-Sofortsignal | Volllast bis zum Limit, **außerhalb** der MILP-Planung (das Smarthome steuert). Unterscheidet sich von SOC-Min Sofort. |

Der Block `charging_schedule.milp` am EV-Verbraucher ist **Pflicht**, sobald Earnie den Ladestrom vorgibt (`set_evcs_max_current` gebunden). Ohne ihn bricht die Live-Optimierung mit einer Meldung ab, die das E-Auto nennt. Der Szenario-Explorer braucht ihn nicht. Die Werte stehen im Hauskonfigurator beim E-Auto unter **MILP-Feintuning**:

| Feld (UI) | Schlüssel | Bedeutung | Vorschlag |
| --- | --- | --- | --- |
| Kontinuierlich laden ab Restmenge (kWh) | `live_modus_a_min_remaining_kwh` | Liegt die noch zu ladende Energie darüber, gibt Earnie eine stetige Ladeleistung vor; darunter schaltet es in ganzen Viertelstunden. Muss > 0 sein. | 2 × Mindestleistung des Paars (Mindeststrom × Spannung × Phasen) |
| Tie-Break Einschalten (ε₁) | `tie_break_on_epsilon` | Kleine Strafe je Lade-Viertelstunde; weit unter dem kleinsten Bezugspreis. | 0,001 |
| Tie-Break Zeitpunkt (ε₂) | `tie_break_time_epsilon` | Kleine Strafe für spätes Laden; bei gleichen Kosten lädt Earnie früher. | 0,0001 |

Fehlt der Block, trägt das Formular die Vorschläge ein. Der Hauskonfigurator speichert automatisch: Schon das Öffnen der Seite schreibt die Vorschläge in `house_profiles.json`, danach läuft die Live-Optimierung.

## Pool-Filter: `filter_schedule` und `loxone_remaining_hours`

Der Filter ist ein eigener Verbraucher `pool_filter`. Die Heizung bleibt ein separater Verbraucher, z. B. `pool_swimspa` / `swimspa` mit `daily_target_source: thermal`.

| Feld | Bedeutung |
| ---- | --------- |
| `daily_target_source` | `loxone_remaining_hours`: Ziel_kWh = `Sollstunden` × `nominal_power_kw` (Config-Enum-Name historisch) |
| `get_filter_remaining_hours` | EHAL-Feld am Verbraucher `pool_filter`; Binding-Adresse in `ehal_bindings` |
| `filter_schedule.enabled` | `true` = das native Duty-Cycle-Fenster sperrt MILP-Slots |
| `filter_schedule.config_fallback` | Festes Fenster für Backtesting/Offline (kein natives Live-Fenster) |

Earnie schaltet nur **ergänzend** außerhalb des nativen Fensters ein (`flex.pool_filter.set_enable`). Entwickler-Spec: [SwimSpa Filter](../dev/done/swimspa-filter.md).

Im **Szenario-Explorer** läuft der Filter im Fenster aus `filter_schedule.config_fallback` mit `nominal_power_kw` als feste Last. Diese Energie bucht Earnie auf `pool_filter` und rechnet sie gegen das Tagesziel. Earnie plant nur den Rest außerhalb des Fensters. Bei Sonnenaufgang-Fenstern zählt dabei nur der native Lauf im jeweiligen Buchungsfenster.

## Manuelle Geräte (Hausprofil, `type: generic`)

Waschmaschine, Trockner usw. sind **`generic`-Verbraucher** in `house_profiles.json` (optional mit `appliance_recommendation`). Die Seite **Manuelle Geräte** zeigt je nach Modus die Start-Empfehlung oder den Reserve-Status. Die Startpläne speichert Earnie in `runtime/appliance_schedules.json`, den Reserve-Zustand in `runtime/powerstation_reserves.json`. Geplante Laufzeiten (Advice) erscheinen in Chart 1 (Flow-Balance).

**Unterstützung (genau ein Modus, Default `advice`):** Im Hauskonfigurator erhält jedes manuelle Gerät genau einen der beiden Modi.

| `appliance_recommendation.mode` | Verhalten |
| --- | --- |
| `advice` | Startempfehlung mit 1–5 Sternen auf **Manuelle Geräte**; optional mit Tagesplan-Häkchen |
| `reserve` | Powerstation mit `role: single_use` (`powerstation_id` → `components.batteries[]` mit `type: powerstation`); kein Sterne-Ranking. Bei `backing: virtual` dürfen mehrere manuelle Geräte dieselbe Powerstation teilen (gemeinsamer Carve-out). |

**Startempfehlung (Opportunitätskosten, nur `advice`):** Ranking und Sterne bewerten jede Planungsstunde nach Opportunitätskosten statt nach dem reinen Bezugspreis. PV-Überschuss (`expected_p_pv − expected_p_act`) zählt mit dem Einspeisetarif (`k_push_act`), der Rest mit dem Bezugspreis (`k_act`). Batteriepfade enthält diese Näherung nicht.

| Feld | Bedeutung |
| ---- | --------- |
| `id`, `label` | Kennung und Anzeigename |
| `appliance_recommendation.mode` | `advice` (Default) oder `reserve` |
| `appliance_recommendation.powerstation_id` | Bei `reserve`: ID der Powerstation in `components.json` |
| `appliance_recommendation.power_source` | `loxone` oder `manual` (Config-Enum; `loxone` = Live-Binding) |
| `loxone_inputs.power_name` | Bei `power_source: loxone`: Legacy-Adresse für die Ist-Leistung (`known` und `manual`); Mapping bevorzugt über `ehal_bindings` |
| `ehal_bindings.flex.{id}.sens_consumer_active` | Speicher-Schlüssel im Profil; im Live-/VO-Austausch: `consumer.{id}.sens_consumer_active` |
| `appliance_recommendation.default_power_kw` | Standard-Leistung für Empfehlung bzw. Reserve |
| `schedule.duration_h` | Laufzeit pro Lauf (auch bei Advice/Reserve: Ziel-kWh ≈ P × t) |

**Dauerlast:** `duration_h` ≥ 24 bei `runs_per_week` 7 (z. B. Server, Dev-PC) ist kein verschiebbarer Lauf. Der Szenario-Explorer bucht einen solchen Verbraucher in jedem Zeitslot mit `nominal_power_kw` als feste Last (Jahresverbrauch wie in der Referenz); im Live-Betrieb bleibt er ein manueller Verbraucher (Reserve/Powerstation wie konfiguriert).

**Reserve-Release:** Beim Start eines angeschlossenen Geräts gibt Earnie die virtuelle Energiereserve frei. Als Start gilt: digital aktiv **oder** Leistung ≥ Schwelle **oder** UI-Button. Im Nachlauf bucht Earnie den Restvorrat ab und lädt danach preisoptimal binnen 24 h nach. Austausch-ID: `consumer.{hk_id}.sens_consumer_active`; Loxone-Default-VO/Merker `Earnie_Verbraucher_<Slug>_Aktiv` in `VO_Earnie_Consumer.xml`.

## Baseline in der UI

Charts und Tabellen zeigen zwei Baselines:

- **BL Profil:** Historisches Verbrauchsmuster ohne Verschiebung.
- **BL Ziel:** Gleiche Tagesenergie wie die Optimierung, aber ohne zeitliche Verschiebung. Dient dem Vergleich „was wäre ohne Optimierung“.

## Hausprofil: Generic-Verbraucher und `earnie_role`

Im Hausprofil (`house_profiles.json`, `type: generic`) legt `earnie_role` (Standard: `known`) fest, wie die Live-Optimierung den Verbraucher berücksichtigt.

| `earnie_role` | Bedeutung | `start_shift_h` |
| ------------- | --------- | --------------- |
| `known` | Geplante Laufzeiten werden zur **Grundlast** (`expected_p_act`) addiert; die MILP behandelt sie nicht als Flex-Last. | wird auf `0` gesetzt (fester Start) |
| `flex` | Optimierbare Flex-Last (MILP) | Verschiebungsfenster (± h) |
| `manual` | **Manuelles Gerät** auf **Live-Cockpit → Manuelle Geräte**; Modus `advice` (Start-Empfehlung) oder `reserve` (Powerstation). Im **Szenario-Explorer** optimiert die MILP es wie `flex` (CSV-Energie als Ziel, wenn „Von Basis-Last abziehen“ aktiv ist, sonst Schedule). **Live mit `advice`:** nur der aktive Nutzer-Tagesplan, kein Default-Wochen-Overlay. | Bei `advice`: **Empfehlungshorizont (h)**; bei `reserve`: Powerstation-Anbindung |

Die Einstellung liegt im **Hauskonfigurator** unter „Earnie-Berücksichtigung“. Thermische Verbraucher (SwimSpa, Wärmepumpe) und das E-Auto sind davon nicht betroffen.

Ein `flex`- oder `manual`-Gerät läuft in ganzen Blöcken von `schedule.duration_h`. Bleibt im Planungsfenster weniger Platz als ein Block (zum Beispiel, weil das Fenster um 08:00 endet und der Lauf um 07:00 beginnen dürfte), plant Earnie den Lauf im nächsten Fenster; die übrigen Verbraucher werden normal geplant.

### Leistungsquelle (optional Live-Binding)

Bei `earnie_role: known` oder `manual` lässt sich optional eine **Live-Leistungsquelle** einrichten. Die Config-Keys heißen noch `loxone_*`.

| Feld | Bedeutung |
| ---- | --------- |
| `loxone_inputs.power_name` | Legacy-Adresse für die Ist-Leistung (einheitlich für `known` und `manual`); bevorzugt `ehal_bindings` |
| `appliance_recommendation.power_source` | `manual` oder `loxone` (nur bei `manual`; `loxone` = Live-Binding) |
| `appliance_recommendation.default_power_kw` | Nennleistung für Empfehlung/Grundlast |
| `schedule.duration_h` | Nenndauer pro Lauf, zugleich Laufzeit für Advice/Reserve |

Earnie speichert die Adresse. Die Live-Leistung (`sens_power_act` / aktiv) fließt bereits in die Reserve-Freigabe ein. Die **Adaption** der konfigurierten Nennleistung für Overlay und Startzeit-Empfehlung folgt in einer späteren Version. Bis dahin nutzen Overlay und Empfehlung die Werte aus dem Profil.
