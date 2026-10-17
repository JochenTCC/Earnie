# Flexible Verbraucher

Ab Version **2.0** liegen steuerbare Verbraucher (SwimSpa, E-Auto, Wärmepumpe, Filter, Generics) primär im **Hausprofil** (`earnie_env/config/house_profiles.json`). Live-Parameter und Bindings stehen dort je Verbraucher unter `consumers[].ehal_bindings`. Der Block `flexible_consumers[]` in `config.json` ist **Legacy** (meist leer). Er wird weiterhin geladen und mit den Verbrauchern aus dem Hausprofil zusammengeführt; bei gleicher `id` hat der Eintrag in `flexible_consumers[]` Vorrang vor dem Hausprofil. Neue Verbraucher werden im Hausprofil angelegt.

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
| `path_historical_log` | Historische Leistungs-CSV für Profile und Backtesting (Offline → `cons_data`; typisch ein Loxone-Export) |
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

## Haus Wärme: optionaler Wärmespeicher (`heat_storage`)

Bei `type: thermal_annual` lässt sich unter `thermal.heat_storage` ein **Pufferspeicher** modellieren. Solarthermie und Wärmepumpe speisen den Speicher; Raumheizung und Warmwasser entnehmen Wärme nur aus dem Speicher. Ohne Speicher bzw. bei `volume_liters = 0` gilt das bisherige Modell: Solarthermie wirkt als Tages-Gutschrift auf den WP-Bedarf.

**Temperaturband (Jahressimulation):** Die Speichertemperatur darf zwischen `setpoint_c − tolerance_c` und **95 °C** liegen. Die Wärmepumpe heizt hart nach, wenn die Temperatur unter die Untergrenze fallen würde. Sie speist höchstens bis zum Sollwert (`setpoint_c`) und bleibt darüber aus. Überschusswärme oberhalb des Sollwerts kommt nur von der Solarthermie; deren Eingang wird erst oberhalb von 95 °C begrenzt.

| Feld | Bedeutung |
| ---- | --------- |
| `thermal.heat_storage.volume_liters` | Speichervolumen; `≤ 0` oder fehlend = bisheriges Modell ohne Speicher |
| `thermal.heat_storage.heat_loss_kw_per_k` | Speicherverlust gegen die Umgebung |
| `thermal.heat_storage.setpoint_c` / `tolerance_c` | Sollwert und Untergrenze (`setpoint − tolerance`); Obergrenze für die Wärmepumpe = Sollwert, absolute Obergrenze (Solarthermie) = 95 °C |

**Schichtspeicher → Temperaturen für Earnie:** Hat der Speicher mehrere Fühler, muss das **Smarthome-Backend** eine **äquivalente Temperatur** `T_eq` bilden (volumengewichtetes Mittel). Zusätzlich liefert es den **untersten Fühler** `T_low`. Bindings am `thermal_annual`-Verbraucher: `sens_temperature_heat_storage` (`T_eq`) und `sens_temperature_heat_storage_low` (`T_low`). Anleitung: [Wärmespeicher Schichtung / T_eq](waermespeicher-schichtung-teq.md).

**Live-Band:** Mit aktivem `heat_storage` erzwingt die Live-Optimierung die WP-Freigabe in zwei Fällen:

- **Prognose:** Die Open-Loop-Prognose von `T_eq` würde unter `setpoint − tolerance` fallen (wie in der Jahressimulation).
- **Unterster Fühler:** `T_low` liegt unter derselben Grenze. Diese Freigabe wirkt kurzfristig.

Darüber hinaus darf die Live-Optimierung opportunistisch Energie bis zum Sollwert einplanen. Die Jahressimulation bleibt dagegen reines Bang-Bang an der Untergrenze. Das gilt für jeden regulären Optimierungslauf, auch wenn Earnie die Live-Telemetrie eines Laufs verwirft (z. B. Nullwerte oder negativer Hausverbrauch) und die Matrix bei Prognosewerten bleibt.

**Live-Prognose über den Planungshorizont:** Die Live-Optimierung simuliert den Speicher nur über den Planungshorizont. Startwert ist die gemessene Speichertemperatur. Eingänge sind die Außentemperatur **und die Kollektor-Einstrahlung aus der Open-Meteo-Wetterprognose** (Neigung/Ausrichtung aus `solar_thermal_tilt_deg` / `solar_thermal_azimuth_deg`).

- **Einstrahlungsprognose fällt aus:** Earnie nutzt dann die Werte des letzten vollständigen Kalenderjahres am selben Tag und zur selben Stunde und schreibt eine Warnung ins `earnie.log`. Die verwendete Quelle steht je Lauf in `optimization_history.jsonl` (`collector_solar_source`: `open_meteo`, `fallback_archive_year` oder `none`).
- **Wärmeverlust des Gebäudes:** Ohne eigenen Wert in `house_heat_loss_kw_per_k` kalibriert Earnie den Wärmeverlust (H) aus dem **letzten vollständigen Kalenderjahr** des Open-Meteo-Archivs. Das laufende, unvollständige Jahr fließt nicht ein.

**Live ohne Wärmespeicher:** Auch ohne `heat_storage` rechnet die Live-Optimierung nur über den Planungshorizont. Die Simulation des Hauses startet bei der Solltemperatur (`target_temp_c`), da es keinen Innentemperatur-Fühler gibt. Sie nutzt die Außentemperatur-Prognose und dieselben Regeln wie die Jahressimulation. Daraus ergeben sich der WP-Bedarf je Viertelstunde und die Tagesziele. Ohne Wohnfläche (`living_area_m2 = 0`) plant Earnie nur Warmwasser und zieht den prognostizierten Kollektorertrag pro Tag ab. Szenario-Explorer und Backtesting nutzen weiterhin die Jahressimulation mit historischem Wetter.

Entwickler-Spec: [thermals-p2.md](../dev/done/thermals-p2.md).

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

Der Block `charging_schedule.milp` am EV-Verbraucher in `house_profiles.json` dient dem Feintuning der MILP-Heuristik (`live_modus_a_min_remaining_kwh`, Tie-Break-Parameter). Details stehen im Schema.

## Pool-Filter: `filter_schedule` und `loxone_remaining_hours`

Der Filter ist ein eigener Verbraucher `pool_filter`. Die Heizung bleibt ein separater Verbraucher, z. B. `pool_swimspa` / `swimspa` mit `daily_target_source: thermal`.

| Feld | Bedeutung |
| ---- | --------- |
| `daily_target_source` | `loxone_remaining_hours`: Ziel_kWh = `Sollstunden` × `nominal_power_kw` (Config-Enum-Name historisch) |
| `get_filter_remaining_hours` | EHAL-Feld am Verbraucher `pool_filter`; Binding-Adresse in `ehal_bindings` |
| `filter_schedule.enabled` | `true` = das native Duty-Cycle-Fenster sperrt MILP-Slots |
| `filter_schedule.config_fallback` | Festes Fenster für Backtesting/Offline (kein natives Live-Fenster) |

Earnie schaltet nur **ergänzend** außerhalb des nativen Fensters ein (`flex.pool_filter.set_enable`). Entwickler-Spec: [SwimSpa Filter](../dev/done/swimspa-filter.md).

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
