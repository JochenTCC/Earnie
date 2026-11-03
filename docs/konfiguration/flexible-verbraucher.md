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
| `appliance_kind` | Nur Typ `generic` und `thermal_rc`, optional: `air_conditioner` kennzeichnet eine Klimaanlage. Sie zählt in den [Earnie-Points](../einrichtung/betrieb.md#earnie-points) wie eine Wärmepumpe. Im Hauskonfigurator: **Geräteart**. |

## Abwesenheits- / Urlaubsmodus (Live)

<a id="abwesenheitsmodus-live"></a>

Die folgenden Hausprofil-Felder wirken nur in der **Live**-Optimierung; der Szenario-Explorer bleibt unverändert.

| Feld | Ort | Bedeutung |
| ---- | --- | --------- |
| `absent_mode` | Profil | Earnie-Schalter „Abwesend / Urlaub“ |
| `absent_mode_enabled` | Verbraucher | „Inaktiv wenn abwesend“. Bei wirksamem Modus nimmt Earnie alle Verbraucher außer Haus Wärme aus der Live-MILP; Haus Wärme bleibt mit Absenkung in der Planung. |
| `absent_temp_reduction_c` | Haus Wärme (`thermal_annual`) | Absenkung in K; Live-Soll = `target_temp_c` − Absenkung. Warmwasser (`persons`) ist dann 0. |
| `plant.ehal_bindings.sens_absent_mode` | Plant | Optionales Smarthome-Signal 0/1, per **oder** mit `absent_mode` verknüpft. Live-Lesen über das aktive EHAL-Backend: Loxone-VO/Merker (Default-Name `Earnie_Abwesend`), HA-Entity (`binary_sensor` / `input_boolean` / …), OpenEMS-Kanal als `componentId/ChannelId` |

Der Modus ist wirksam, sobald der Schalter im Hauskonfigurator **oder** das EHAL-Live-Signal aktiv ist (alle Backends). Der Schalter `absent_mode` wirkt dabei **backend-unabhängig**. Verbraucher mit Opt-in außer Haus Wärme nimmt Earnie aus der Live-MILP-Liste. Haus Wärme bleibt mit reduzierter Solltemperatur in der Optimierung.

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

Der Verbraucher `type: thermal_annual` beschreibt den Wärmebedarf des Gebäudes (Wohnfläche, Gebäudeklasse bzw. HWB, Personen, Temperaturen, Solarthermie) und seine Smarthome-Bindings. Die Wärmeerzeugung steht in einem eigenen Katalog: `heating_systems[]` in `components.json`. Ein Eintrag enthält:

| Feld | Bedeutung |
| ---- | --------- |
| `id`, `label` | Kennung und Bezeichnung des Heizsystems |
| `heat_source` | Hauptwärmequelle, siehe [Wärmequelle](#haus-wärme-wärmequelle-heat_source) |
| `nominal_power_kw` | Elektrische Leistung der Wärmepumpe (kW); bei Brennstoffen ungenutzt |
| `min_on_quarterhours` | Mindestlaufzeit in Viertelstunden |
| `heat_storage` | Optionaler Wärmespeicher, siehe [Wärmespeicher](#haus-wärme-optionaler-wärmespeicher-heat_storage) |
| `parts` | Optionaler Heizstab, siehe [Heizstab](#haus-wärme-heizstab-im-wärmespeicher-parts) |

```json
"heating_systems": [
  {"id": "heating_haus", "label": "Heizsystem Haus",
   "heat_source": {"type": "heat_pump", "heat_pump_type": "erde"},
   "nominal_power_kw": 1.9, "min_on_quarterhours": 4,
   "heat_storage": {"volume_liters": 800}}
]
```

**Referenzsystem:** Der Verbraucher verweist mit `heating_system_id` (Pflicht) auf das eingebaute Heizsystem. Live-Betrieb, Grundlast und die Vorschau im Hauskonfigurator rechnen immer mit diesem System. Der Hauskonfigurator legt den Eintrag beim Speichern an (Kennung `heating_<Hausprofil-ID>`) und ändert ihn direkt im Katalog. Am Verbraucher steht nur der Verweis.

- **Ein Haus je Heizsystem:** Ein Heizsystem ist Referenzsystem höchstens eines Hauses, weil eine Änderung sonst auch die Grundlast des anderen Hauses verschiebt. Verweisen zwei Hausprofile auf denselben Eintrag (z. B. von Hand in `house_profiles.json`), lehnt Earnie das Speichern ab.
- **Nur Verweis am Verbraucher:** Die Felder der Wärmeerzeugung (`heat_source`, `heat_storage`, `parts`, `nominal_power_kw`, `min_on_quarterhours`) gehören in den Katalog. Stehen sie zusätzlich am Verbraucher, lehnt Earnie die Datei beim Laden ab, statt sie still zu überschreiben.
- **Hausprofil entfernen:** Das Referenzsystem bleibt im Katalog und ist danach eine gewöhnliche Variante (änderbar, im Szenario wählbar, entfernbar).

Im Formular des Verbrauchers „Haus Wärme“ (Bereich **Hausprofil**) stehen die Felder in zwei Abschnitten:

- **Gebäude / Wärmebedarf:** Wohnfläche, Gebäudeklasse, Bauweise, HWB, Personen, Temperaturen, Verlustkoeffizient, Absenkung bei Abwesenheit und Solarthermie. Sie bleiben am Verbraucher.
- **Heizsystem (Referenzsystem: …):** Wärmequelle, Nennleistung, Mindestlaufzeit, Wärmespeicher und Heizstab. Sie landen beim Speichern im Katalogeintrag des Referenzsystems.

**Heizsystem wechseln:** Das Referenzsystem ändert sich nur hier, im Abschnitt **Heizsystem** des Hauses. Ein anderes Heizsystem aus dem Katalog übernimmt ein Haus nicht; wer eine modellierte Variante eingebaut hat, trägt ihre Werte hier ein. Ändert sich die **Wärmequelle** gegenüber der gespeicherten Datei (z. B. Gas → Wärmepumpe), passen die Verbrauchsdaten des Hauses nicht mehr, denn sie stammen vom bisherigen System. Earnie speichert dann erst nach einer Wahl und zeigt direkt unter der Wärmequelle eine Warnung:

- **Mit CSV-Messdaten** (Lastprofil des Hauses oder Zähler-CSV der Haus-Wärme): **Messdaten entfernen** (Lastprofil, Batterie- und Netz-CSV des Hauses sowie die Zähler-CSV der Haus-Wärme; das PV-Profil bleibt) oder **Heizsystem beibehalten**.
- **Nur mit Jahresverbrauch:** Jahresverbrauch oben an das neue Heizsystem anpassen und **Jahresverbrauch übernehmen**, oder **Heizsystem beibehalten**. Bei einem Neubau, dessen Jahresverbrauch schon eine Schätzung für das neue Heizsystem ist, den Wert unverändert übernehmen.

Alte Daten und neues Heizsystem zugleich gibt es nicht. WP-Typ, JAZ bzw. Nutzungsgrad, Leistung, Speicher und Heizstab sind Feinabstimmung und speichern ohne Warnung. Wer die Wärmequelle vor dem Speichern zurückstellt, hat nichts geändert. Eine von Hand bearbeitete `house_profiles.json` prüft Earnie nicht.

**Varianten:** Weitere Heizsysteme entstehen im Hauskonfigurator im Bereich **Heizsysteme**, z. B. als Kopie des Referenzsystems. Dort ist das Referenzsystem eines Hauses nur lesbar, weil eine Änderung die Grundlast dieses Hauses verschiebt. Ein Heizsystem, auf das ein Hausprofil oder ein Szenario verweist, lässt sich nicht entfernen. Die Auswahl im Szenario beschreibt [Heizsystem im Szenario](#heizsystem-im-szenario-heating_system_ids).

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

- **Wärmepumpe und Stromheizung:** Strombedarf = gelieferte Wärme / JAZ bzw. Nutzungsgrad. `nominal_power_kw` ist die elektrische Leistung.
- **Brennstoffe:** Brennstoffbedarf (Endenergie) = gelieferte Wärme / Nutzungsgrad. Die Heizung bezieht keinen Strom und ist kein flexibler Verbraucher in der Optimierung. `nominal_power_kw` ist die Brennstoffleistung des Kessels.

Verteilverluste rechnet Earnie nicht zusätzlich ein. Der Wärmeverlust des Gebäudes ist auf den HWB kalibriert, der Speicherverlust ist eigens modelliert.

<a id="haus-wärme-heizstab-im-wärmespeicher-parts"></a>

### Heizstab im Wärmespeicher (`parts`)

Ein Heizstab lädt den Wärmespeicher elektrisch mit Wirkungsgrad 1. Er ist ein Teil des Heizsystems und kein eigener Verbraucher:

```json
"parts": [{"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": 3.0}]
```

- **Nur mit Wärmespeicher:** Ohne `heat_storage` lehnt Earnie den Heizstab beim Laden ab. Eine reine Elektroheizung ohne Speicher ist die Wärmequelle `electric_direct`.
- **Kennung:** In Signalen und Ergebnissen heißt der Heizstab `<Kennung des Verbrauchers>_heating_rod`, z. B. `waermepumpe_heating_rod`.
- **Neben einer Wärmepumpe:** Der Optimierer verteilt die Tageswärme auf Wärmepumpe und Heizstab. Der Heizstab lohnt sich, wenn Strom in einem Zeitfenster weniger kostet als der Strompreis der Wärmepumpe geteilt durch ihre JAZ, z. B. bei negativen Preisen. Die Wärmepumpe braucht dafür die Planung durch den Optimierer (`nominal_power_kw` > 0, `optimizer_flex` nicht `false`).
- **Neben einem Brennstoff:** Jede kWh Heizstab-Wärme spart Brennstoff im Wert von Brennstoffpreis / Nutzungsgrad. Der Optimierer setzt den Heizstab ein, wenn Strom günstiger ist, z. B. bei PV-Überschuss mit niedriger Einspeisevergütung. Höchstens so viel Wärme, wie das Haus am Tag braucht.
- **Grenzen:** Der Optimierer rechnet mit der Tageswärme des Hauses, nicht mit der freien Kapazität des Speichers. Der Heizstab plant derzeit nur im Szenarien-Explorer. Im Live-Betrieb bleibt er aus, eine Steuerung über ein eigenes Binding folgt später.

**Kein fester Verbrauch:** Der Heizstab hat keinen eigenen Verbrauch in den Hausdaten, weder als CSV noch als Jahres-kWh. Der Optimierer entscheidet allein, wann er läuft. So bleibt das Heizsystem im Szenario frei austauschbar.

**Mögliche Doppelzählung:** Lief ein Heizstab im Haus während des Messzeitraums (z. B. über eine PV-Überschussregelung), steckt sein Verbrauch im gemessenen Gesamtverbrauch und damit in der Grundlast. Plant der Optimierer den Heizstab im Szenario zusätzlich, zählt dieser Strom doppelt. Earnie nimmt das in Kauf und zeigt dazu keinen Hinweis. Ein Heizstab-Zähler für den Live-Betrieb ist ein eigenes Thema; dort braucht er eigene Smarthome-Bindings.

Ältere Entwicklungsstände kannten `heating_rod_profile_csv` und `heating_rod_annual_kwh` am Verbraucher. Earnie lehnt diese Felder beim Laden ab; das Feld aus `house_profiles.json` entfernen.

<a id="haus-wärme-optionaler-wärmespeicher-heat_storage"></a>

### Optionaler Wärmespeicher (`heat_storage`)

Im Heizsystem lässt sich unter `heat_storage` ein **Pufferspeicher** modellieren. Solarthermie und Wärmepumpe speisen den Speicher; Raumheizung und Warmwasser entnehmen Wärme nur aus dem Speicher. Ohne Speicher bzw. bei `volume_liters = 0` gilt das bisherige Modell: Solarthermie wirkt als Tages-Gutschrift auf den WP-Bedarf.

**Temperaturband (Jahressimulation):** Die Speichertemperatur darf zwischen `setpoint_c − tolerance_c` und **95 °C** liegen. Die Wärmepumpe heizt hart nach, wenn die Temperatur unter die Untergrenze fallen würde. Sie speist höchstens bis zum Sollwert (`setpoint_c`) und bleibt darüber aus. Überschusswärme oberhalb des Sollwerts kommt nur von der Solarthermie; deren Eingang wird erst oberhalb von 95 °C begrenzt.

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

`nominal_power_kw_name` (Legacy unter `charging_schedule.loxone`) überschreibt zur Laufzeit die konfigurierte `nominal_power_kw`, wenn der Live-Wert lesbar ist.

### SOC-Ziele im Live-Betrieb (EHAL)

| Signal | EHAL-Feld / Default-VO-Name (Loxone) | Bedeutung |
| ------ | ------------------------------------ | --------- |
| Ladeziel (Limit) | `get_evcs_limit_soc` / `Earnie_EAuto_LimitSOC` | Oberes SOC-Ziel bis FertigUm; die Restenergie plant Earnie preisoptimiert. |
| SOC-Min Sofort | `get_evcs_soc_min_immediate` / `Earnie_EAuto_SOCMinSofort` | Sofort-Boden: Earnie erzwingt bis zu diesem SOC eine Lieferung so schnell wie möglich (MILP) und plant danach normal bis zum Limit. Ein Wert ≤ 0 oder ein fehlendes Binding = inaktiv; ein Wert über dem Limit wird auf das Limit begrenzt. |
| Sofortladen | `set_evcs_mode=now` / Legacy-Sofortsignal | Volllast bis zum Limit, **außerhalb** der MILP-Planung (das Smarthome steuert). Unterscheidet sich von SOC-Min Sofort. |

Der Block `charging_schedule.milp` am EV-Verbraucher ist **Pflicht**, sobald Earnie den Ladestrom vorgibt (`set_evcs_max_current` gebunden). Ohne ihn bricht die Live-Optimierung mit einer Meldung ab, die das E-Auto nennt. Der Szenario-Explorer braucht ihn nicht. Die Werte stehen im Hauskonfigurator beim E-Auto unter **MILP-Feintuning**:

| Feld (UI) | Schlüssel | Bedeutung | Vorschlag |
| --- | --- | --- | --- |
| Kontinuierlich laden ab Restmenge (kWh) | `live_modus_a_min_remaining_kwh` | Liegt die noch zu ladende Energie darüber, gibt Earnie eine stetige Ladeleistung vor; darunter schaltet es in ganzen Viertelstunden. Muss > 0 sein. | 2 × Mindestleistung (ohne Mindestleistung 2 × 1,4 kW) |
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

### Leistungsquelle (optional Live-Binding)

Bei `earnie_role: known` oder `manual` lässt sich optional eine **Live-Leistungsquelle** einrichten. Die Config-Keys heißen noch `loxone_*`.

| Feld | Bedeutung |
| ---- | --------- |
| `loxone_inputs.power_name` | Legacy-Adresse für die Ist-Leistung (einheitlich für `known` und `manual`); bevorzugt `ehal_bindings` |
| `appliance_recommendation.power_source` | `manual` oder `loxone` (nur bei `manual`; `loxone` = Live-Binding) |
| `appliance_recommendation.default_power_kw` | Nennleistung für Empfehlung/Grundlast |
| `schedule.duration_h` | Nenndauer pro Lauf, zugleich Laufzeit für Advice/Reserve |

Earnie speichert die Adresse. Die Live-Leistung (`sens_power_act` / aktiv) fließt bereits in die Reserve-Freigabe ein. Die **Adaption** der konfigurierten Nennleistung für Overlay und Startzeit-Empfehlung folgt in einer späteren Version. Bis dahin nutzen Overlay und Empfehlung die Werte aus dem Profil.
