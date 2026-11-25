# PV & Batterie (Live-Szenario)

Diese Parameter beschreiben die physische Anlage. Sie fließen in die MILP-Optimierung ein, im Live-Betrieb ebenso wie in der Simulation.

- **Live-Szenario:** Es enthält die Entitäts-Referenzen (`backtesting_scenarios.json`, gewählt über `live_scenario_id` in `config.json`).
- **Technische Werte:** Sie liegen in `earnie_env/config/components.json` (`inverters[]`, `batteries[]`, `pv_systems[]`).

Ein Szenario kann **mehrere PV-Felder** (`pv_system_ids`) und **mehrere Batterien** (`battery_ids`) referenzieren. Prognose und Optimierung rechnen mit der **Summe** aller PV-Felder bzw. aller gewählten Speicher. Welche Wechselrichter beteiligt sind, ergibt sich aus `inverter_id` an PV-Feld und Batterie. Im Szenario gibt es dafür kein eigenes `inverter_ids[]`.

Im **Szenario-Explorer** (Verbrauchsdaten / cons_data) gilt für die PV-Linien:

- **Monatschart:** Je **eindeutiger PV-Konfiguration** über alle Szenarien erscheint eine Serie (Summe der PV-Felder in dieser Konfiguration). Die Legende verbindet die Bezeichnungen mit „ + “, z. B. „Dach Süd“ oder „Dach Nord + Dach Süd“.
- **Wochenchart:** Je **eindeutigem PV-Feld** erscheint eine Serie, zusätzlich die Summen der Mehrfach-Konfigurationen wie im Monatschart. Konfigurationen mit nur einem PV-Feld werden nicht doppelt gezeichnet.
- **Farben:** Die PV-Linien nutzen eine gelbliche Palette. Die historische Summe aus `cons_data` („PV Ist“) zeigen diese Charts **nicht** an.

| Parameter | Einheit | Quelle | Bedeutung |
| --------- | ------- | ------ | --------- |
| `pv_system_ids` | – | Szenario → `components.json` | Eine oder mehrere Referenzen auf `pv_systems[].id` |
| `battery_ids` | – | Szenario → `components.json` | Eine oder mehrere Referenzen auf **Hausbatterien** `batteries[].id` mit `type: house`. Powerstations sind hier nicht zulässig. |
| `id` / `id_locked` / `id_provisional_label` | – | `components.json` → `inverters[]` / `batteries[]` / `pv_systems[]` | Interne ID (EHAL-Slug / Kennung). Neue Einträge und Kopien starten mit freigegebener ID (`id_locked: false`, Vorschlag in `id_provisional_label`). Die erste geänderte **Bezeichnung** setzt `id` aus dem Label und sperrt die ID. Bestehende Einträge ohne Flag gelten als gesperrt. Einmalig steht der UI-Button „ID aus Bezeichnung übernehmen“ zur Verfügung. Zum einmaligen Bereinigen unsauberer IDs offline: `python -m scripts.clean_entity_ids_once --config-dir <config>` (Dry-Run; `--apply` schreibt; optional `--only-copy`). |
| `type` | enum | `components.json` → `batteries[]` | `house` (Default) oder `powerstation` (Reserve; Anbindung über ein manuelles Gerät mit `mode: reserve`) |
| `backing` / `role` / `attached_consumer_ids` | – | `components.json` → Powerstation | Nur bei `type: powerstation`: `virtual`\|`physical` bzw. `single_use`\|`standby_backup`. `attached_consumer_ids` (Liste) ist optional; die Zuordnung ist auch über manuelle Geräte mit `mode: reserve` + `powerstation_id` möglich. Ältere Konfigurationen: `attached_consumer_id` entspricht dem ersten Listenelement. |
| `inverter_id` | – | `components.json` → `batteries[]` / `pv_systems[]` | Referenz auf `inverters[].id`. Pflicht für Hausbatterien, physische Powerstations und alle PV-Felder. Virtuelle Powerstations haben **keinen** Wechselrichter. |
| `kwp` | kWp | `components.json` → `pv_systems[]` | Installierte PV-Leistung je Anlage; die Summe ergibt `pv_kwp` |
| `pv_tilt` | ° | `components.json` → `pv_systems[]` | Dachneigung **je Anlage** (bei mehreren Anlagen gibt es keine gemeinsame Neigung). Nachkommastellen sind erlaubt (z. B. `17.5`) |
| `pv_azimuth` | ° | `components.json` → `pv_systems[]` | Ausrichtung je Anlage: `0` = Süd, `-90` = Ost, `90` = West |
| `latitude`, `longitude` | ° | `house_profiles.json` (über das Szenario) | Standort für die PV-Prognose (Forecast.Solar / Open-Meteo) |
| `horizon_source`, `horizon` | – / ° | `house_profiles.json` | Horizont am Standort (Gelände, Gebäude, Bäume), siehe [Horizont](#horizont). Ohne die Felder rechnet Earnie mit freiem Horizont. |
| `k_push_cent` | Cent/kWh | `tariffs.json` (Export-Tarif) | **Einspeisevergütung** |
| `battery_capacity_kwh` | kWh | `components.json` → `batteries[]` | Nutzbare Speicherkapazität |
| `battery_max_charge_power_kw` | kW | `components.json` → `batteries[]` | Max. Ladeleistung |
| `battery_max_discharge_power_kw` | kW | `components.json` → `batteries[]` | Max. Entladeleistung |
| `battery_max_power_kw` | kW | `components.json` → `batteries[]` | **Veraltet:** eine gemeinsame Grenze für beide Richtungen. Steht sie noch in einer Konfiguration, überträgt Earnie sie beim Laden in Lade- und Entladegrenze. |
| `limits_from_live` | bool | `components.json` → `batteries[]` | Bei `true` kommen SOC-Min/Max und max. Lade-/Entladeleistung live aus `get_ess_*` (Fallback: Hauskonfigurator-Werte). Diese Lesewerte müssen statische Gerätegrenzen sein, nie ein Wert, den Earnie selbst schreibt (Details: [EHAL-Referenz](../referenz/ehal.md#get_ess_-limits-device-capability-only-never-an-earnie-setpoint)) |
| `efficiency` | 0–1 | `components.json` → `inverters[]` | Einweg-Wirkungsgrad DC↔AC (**η_inv**), Pflicht. Wirkt auf PV DC→AC und als Teil des Speicherpfads. Migration bestehender Konfigurationen: `python -m scripts.migrate_conversion_efficiency_once --config-dir <config>` |
| `battery_efficiency` | 0–1 | `components.json` → `batteries[]` | Einweg-Wirkungsgrad der Zellchemie (**η_batt**). Optimierung und Simulation nutzen **η_path = η_inv · η_batt** (Roundtrip ≈ η_path²). |
| `battery_min_soc` | % | `components.json` → `batteries[]` | Untere SOC-Grenze (Schutz). Liegt der gemessene SoC darunter, plant Earnie keine Entladung, bis die Grenze wieder erreicht ist; geladen wird preisoptimal, nicht sofort. Danach wird die Grenze nicht mehr unterschritten. Eine virtuelle Reserve hebt die Grenze nur in den Viertelstunden an, in denen sie sich lohnt (siehe unten) |
| `battery_max_soc` | % | `components.json` → `batteries[]` | Obere SOC-Grenze. Liegt der gemessene SoC darüber, plant Earnie keine Ladung, bis die Grenze wieder erreicht ist; entladen wird preisoptimal, nicht sofort. Danach wird die Grenze nicht mehr überschritten |
| `threshold_power` | Anteil | `components.json` → `batteries[]` | Relativ zu `max(charge, discharge)` in kW (z. B. `0.2` = 20 %). Schwellwert für die Modus-Erkennung und für die Entscheidung zwischen Zwangsentladen und Automatik |
| `standby_power_kw` | kW | `components.json` → `batteries[]` | Dauerhafte AC-Eigenleistung der Batterie (in der Optimierung als Verbrauch rund um die Uhr) |
| `idle_drain_kw` | kW | `components.json` → `batteries[]` (optional, fehlt = 0) | Selbstentladung aus dem Speicher (DC), z. B. BMS und Wechselrichter im Haltebetrieb. Anders als `standby_power_kw` ist das kein Verbrauch im Haus, sondern Energie, die dem Speicher fehlt: Die Simulation zieht sie in jedem Slot vom SoC ab, solange der SoC über `battery_min_soc` liegt (auch durch den Floor einer virtuellen Reserve hindurch); sie fließt außerdem in die Haltekosten und das Toleranzband der virtuellen Reserve ein. Die Optimierung (MILP) rechnet ohne sie: Es sind nur wenige Wh pro Viertelstunde, und der Plan startet jede Viertelstunde neu vom gemessenen SoC. Die Batterieleistung zeigt sie meist nicht an. Earnie schätzt den Wert im Betrieb aus der Zeit zwischen zwei Rückgängen der SoC-Anzeige ohne Laden oder Entladen (Laufzeitdatei `idle_drain_learner.json`, Logzeile `idle_drain_learner`); der Schätzwert ist nur ein Vorschlag und wirkt erst, wenn er eingetragen wird. Im Hauskonfigurator steht das Feld als **Selbstentladung (kW)** unter der Standby-Leistung; liegt ein Schätzwert vor, steht er als Hinweis darunter. Der Wert 0 wird nicht gespeichert. |
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

Solange ein Gerät aktiv ist, gibt Earnie die gehaltene Reserve frei, der SoC-Floor der Hausbatterie sinkt also. Nach dem Lauf bucht Earnie den Restvorrat weiter ab. Danach lädt Earnie **preisoptimal** vor dem nächsten Zeitraum nach, in dem sich die Reserve lohnt (siehe unten). Gibt es im Planungshorizont keinen solchen Zeitraum, lädt Earnie nicht nach.

**Freigabe ohne Warten auf die nächste Viertelstunde:** Zwischen zwei Läufen prüft Earnie alle 30 Sekunden die Geräte virtueller Reserven, die Energie halten und noch nicht freigegeben sind (digitales Signal und Live-Leistung). Startet ein Gerät, gibt Earnie die Reserve sofort frei und startet einen außerplanmäßigen Lauf (Trigger **Reserve-Freigabe** im Verlauf). Der neue Plan entscheidet, wann die freigegebene Energie genutzt wird; die Batterie muss das Gerät nicht selbst versorgen. Die Verzögerung liegt bei bis zu 30 Sekunden plus der Laufzeit der Optimierung.

- Pro Gerätestart gibt es genau einen Zusatzlauf. Die Freigabe bleibt bestehen, bis die Reserve leer ist; ein weiter laufendes Gerät weckt Earnie also nicht erneut.
- Beginnt der nächste reguläre Lauf ohnehin innerhalb seiner erwarteten Laufzeit (Vorlauf des Frühstarts), weckt Earnie nicht. Der reguläre Lauf übernimmt die Freigabe.
- Endet der Zusatzlauf erst nach dem nächsten Viertelstunden-Takt, startet Earnie sofort einen regulären Lauf für die neue Viertelstunde. Sonst blieben die Sollwerte der alten Viertelstunde bis zum übernächsten Takt stehen.
- Die Prüfung zwischen den Läufen liest nur Signale, die Earnie live abfragen kann: das digitale Aktiv-Signal (`sens_consumer_active`) und die Live-Leistung des Geräts. Signale, die nur in der Telemetrie eines Laufs stehen (etwa die Ausgangsleistung einer physischen Powerstation), sieht erst der nächste reguläre Lauf.
- Kann Earnie ein Signal nicht lesen (z. B. Smarthome nicht erreichbar), schreibt es eine Warnung ins Log, einmal pro Quelle und Wartezeit, und prüft weiter. Über ein nicht lesbares Signal gibt Earnie bis zum nächsten Lauf nichts frei.
- Leere Reserven und physische Powerstations lösen keinen Zusatzlauf aus. Physische Powerstations gibt der reguläre Lauf frei.
- Ein Smarthome kann denselben Effekt auch von außen auslösen, indem es beim Gerätestart `Earnie_Request_Optimize` sendet.

**Schutz der gehaltenen Reserve:** Der SoC-Floor ist der Mindest-SoC der Hausbatterie plus der Carve-out (z. B. 5 % + 1,1 kWh von 15 kWh = 12,3 %).

**Reserve nur, wo sie sich lohnt:** Earnie hält den Floor nicht rund um die Uhr, sondern nur in den Viertelstunden, in denen Strom aus der Batterie billiger ist als aus dem Netz. Das ist der Fall, wenn der Netzpreis höher ist als der günstigste Preis davor, geteilt durch den Wirkungsgrad hin und zurück (Wirkungsgrad²), plus die Kosten der Selbstentladung (`idle_drain_kw`) während der Haltezeit.

- Vor einem teuren Zeitraum baut Earnie die Reserve in den günstigsten Viertelstunden davor auf, ähnlich wie beim Laden eines E-Autos bis zu einer Abfahrtszeit. Am Anfang der ersten teuren Viertelstunde ist sie voll.
- In einer günstigen Phase gibt es keinen Floor. Eine volle Reserve wird dort nicht herausgedrängt; der Plan nutzt die Energie nur, wenn sich das lohnt. Ein SoC unter dem Floor löst in einer günstigen Phase keine Nachladung aus.
- Bei flachen Preisen lohnt sich die Reserve nie; Earnie hält und lädt dann nichts.
- Hält der Plan die Reserve gerade, merkt sich Earnie den Preis, zu dem sie geladen wurde (Laufzeitdatei `powerstation_reserves.json`, Felder `fill_basis_price` und `fill_basis_at`). Der nächste Lauf mitten in der teuren Phase sieht so weiter, dass die gespeicherte Energie günstig war, und hält den Floor. Fällt der Floor in einer günstigen Phase weg, wird die Reserve freigegeben oder ist sie leer, löscht Earnie diesen Preis.
- Für gespeicherte Energie zählt die Selbstentladung erst ab jetzt: Ladepreis und bisherige Haltezeit sind bereits bezahlt. Eine lange teure Phase hält den Floor deshalb bis zu ihrem Ende, auch wenn die Reserve schon Stunden davor geladen wurde.
- Liegt der SoC beim Start unter dem Mindest-SoC, führt Earnie ihn zurück und baut die Reserve bis zur ersten Viertelstunde auf, in der sie sich lohnt (soweit die Ladeleistung reicht).
- Reicht die Ladeleistung nicht, um die Reserve bis zur ersten teuren Viertelstunde aufzubauen, baut Earnie sie so schnell wie möglich auf und schreibt eine Warnung ins Log.

- Im Modus **Automatik** begrenzt Earnie das geschriebene Entladelimit auf die Energie über diesem Floor, die in einer Viertelstunde abfließen darf. Das gilt nur, wenn die Reserve in der aktuellen Viertelstunde gehalten wird; ohne Floor bleibt das volle Entladelimit. Bei 14 % SoC und einem Floor von 12,3 % sind das rund 0,9 kW. So kann ein großer Verbraucher (z. B. Pool) die Reserve nicht innerhalb eines Slots leeren, die danach aus dem Netz nachgeladen werden müsste. Weiter über dem Floor bleibt das volle Entladelimit.
- **Toleranz am Floor:** Die Anlage meldet den SoC in ganzen Prozent, und die Batterie verliert im Haltebetrieb durch Selbstentladung laufend etwas Energie. Damit das keine kurzen Lade- und Entladeimpulse auslöst, gilt um den Floor ein Toleranzband:
  - Liegt die Anzeige höchstens 1 % über dem Floor (z. B. 13 % bei 12,3 %), gibt Earnie nichts frei: kein Entladen im Plan und ein Entladelimit von 0 in **Automatik**.
  - Liegt die Anzeige unter dem Floor, aber innerhalb des Nachladebands (z. B. 12 % oder 11 % bei 12,3 %), hält Earnie den Stand und lädt nicht nach. Die Selbstentladung darf weiterlaufen.
  - Erst wenn die Anzeige unter das Band fällt (z. B. 10 %), lädt Earnie in einem Block bis zum Floor nach.
  - Endet die teure Phase und kommt später eine weitere, ist die Reserve bis zu deren Beginn wieder voll; Earnie lädt dafür in den günstigsten Viertelstunden davor.
  - **Breite des Bands:** die Selbstentladung (`idle_drain_kw`) über 8 Planungsslots (2 Stunden bei Viertelstunden), mindestens aber 2 %. Ohne eingetragene Selbstentladung sind es 2 %. Bei 1 %/h Selbstentladung reicht ein Nachladeblock so für gut zwei Stunden.

Einige Felder sind ausgeblendet: Max. Lade-/Entladeleistung, Wirkungsgrad, SoC-Grenzen, Leistungsschwelle, Standby, Steuerbarkeit, `limits_from_live` und Verschleiß. Beim Speichern bzw. Normalisieren übernimmt Earnie diese Werte von der Hausbatterie. Ohne Hausbatterie speichert der Hauskonfigurator die virtuelle Powerstation nicht. Er zeigt dann einen Fehler; lege zuerst eine Hausbatterie an oder wähle Backing „Physisch“.

- Die Entladeleistung der virtuellen Powerstation ist immer `0`.
- Der Verschleiß bleibt aus, weil die Zyklen auf der Hausbatterie zählen.
- Ein `inverter_id` gibt es nicht.

Physische Powerstations (`backing: physical`) behalten das volle Batterie-Formular. Sie bekommen einen **integrierten Powerstation-Wechselrichter** (`owned_by` = Batterie-ID, Abschnitt „Integrierter Wechselrichter“ im Hauskonfigurator). Dieser speist nur die angeschlossenen Verbraucher, nicht den AC-Bus des Hauses. Sein AC-Eingang kann am Netz hängen (einseitige Last), das Gerät ist also **nicht** „netzlos“. Der Wechselrichter heißt `wr_<Batterie-ID>`. Ändert sich die Batterie-ID, zieht er mit allen Feldern und Bindings auf die neue ID um. Felder, die der Abschnitt nicht zeigt (z. B. `max_ac_charge_kw`), bleiben beim Speichern erhalten.

### Standby-Backup (`role: standby_backup`)

Diese Rolle ist für Dauerläufer ohne einzelnen Lauf-Auslöser gedacht (PC, Router, NAS, Hub, …). Earnie schaltet die Versorgung der angeschlossenen Verbraucher **preisgetrieben** zwischen Netz-Durchleitung (Pass-Through) und Batterie-Inselbetrieb um (`ess.<id>.set_ess_source_select`: `0` = Netz, `1` = Batterie). In günstigen Slots darf die Powerstation parallel laden (`set_ess_charge_power_limit`).

- **Nur `backing: physical`:** Earnie überspringt virtuelle Standby-Instanzen zur Laufzeit. Auf der Hausbatterie gibt es dafür keinen geschützten Floor; ggf. das globale `battery_min_soc` erhöhen.
- **Harte Voraussetzung:** Die physische Standby-Backup-Batterie braucht die Capability `supports_ess_source_select` und ein Mapping von `ess.<id>.set_ess_source_select`. Bei EcoFlow ist das der HA-Switch `switch.<device>_grid_bypass`; bei `ehal.backend=loxone` ein Pattern-B-Merker mit Bridge zu HA, siehe [EcoFlow Delta 3](../dev/done/ecoflow-delta3-loxone.md) (Lab-Anleitung). Anlage und Hausspeicher haben kein Feld für die Quellenwahl.
- **Quellenwahl und Ladegrenzen:** Beide brauchen an der physischen Powerstation jeweils ein **eigenes** Pattern-B-Binding. Sie greifen **nicht** auf die Mappings der Hausbatterie zurück, da sonst deren Lade-/Entladegrenzen überschrieben würden.
- **Reserve-Größe:** angeschlossene Last × teure Stunden im Horizont. Ein Lernen der Energie pro Lauf wie bei `single_use` gibt es hier nicht.

### Live-PV-Leistung

Die Live-PV-Leistung (AC-Summe der Anlage) leitet Earnie aus den netzgekoppelten Wechselrichtern ab: Σ(`inv.{id}.sens_inv_power_pv` · η_inv).

- **Mapping je Wechselrichter:** Jeder Wechselrichter mit angeschlossenen PV-Feldern braucht dieses Mapping. Fehlt die PV-Leistung des Wechselrichters, können vollständige String-Mappings `pv.{id}.sens_pv_production_active` die Summe je Wechselrichter ersetzen.
- **Nicht berücksichtigt:** Powerstation- und Insel-Wechselrichter (`ac_connection: island`) zählen nicht mit.
- **Unvollständige Mappings** führen zu einem Fehler.
- **Kein Anlagen-Feld für PV:** `plant.ehal_bindings.sens_pv_production_active` gibt es nicht; ein vorhandenes eindeutiges Mapping überträgt die Migration auf den einzigen Wechselrichter.
- **Intervallenergie:** Die Intervallenergie für `cons_data` (`pv_kwh_interval`) integriert Earnie aus der abgeleiteten Anlagen-Leistung.

### PV-Prognose im Live-Betrieb

Earnie kennt zwei Quellen für die PV-Prognose:

- **forecast.solar** mit Neigung, Ausrichtung und kWp des Felds, bei eingeschaltetem Horizont auch mit der Horizontlinie (siehe *Horizont* unten). Earnie fragt höchstens alle 15 min neu ab und hält ein Rate-Limit (HTTP 429) ein. Dazwischen nutzt es die letzte Antwort. Diese liegt auch in `runtime/pv_forecast_cache.json` und überbrückt so einen Neustart, solange sie höchstens 6 h alt ist. forecast.solar liefert die Leistung **zum** jeweiligen Zeitpunkt (volle Stunden sowie Sonnenauf- und -untergang). Earnie nimmt für jeden Slot den Mittelwert dieses Verlaufs über die Dauer des Slots. Damit stimmt die Slot-Energie mit der Stundenenergie von forecast.solar überein, auch in der Stunde von Sonnenauf- und -untergang.
- **Open-Meteo-Einstrahlung** (`global_tilted_irradiance`, Wettermodell `best_match`: Open-Meteo wählt das passende Modell für den Standort) für Neigung und Ausrichtung des Felds. Die Leistung ist Einstrahlung / 1000 W/m² × kWp, wie im Backtesting.

Welche Quelle zuerst gilt, legt die **Hauptquelle der PV-Prognose** fest: Hauskonfigurator → Gruppe „Sonne & Horizont“ → „Anlagenweit“ (`plant.pv_forecast_source` in `house_profiles.json`, Werte `forecast_solar` oder `open_meteo`, ohne Eintrag forecast.solar). Die Einstellung gilt für alle Profile. Je PV-Feld geht Earnie so vor:

1. **Hauptquelle** abfragen.
2. Liefert sie für das Feld keine Daten, die **andere Quelle** nehmen. Das Log meldet das als WARNING, und das Cockpit zeigt einen Hinweis mit den betroffenen PV-Feldern.
3. **Abbruch des Zyklus**, wenn auch die andere Quelle nicht antwortet. Earnie plant dann nicht mit erfundenen PV-Werten, sondern meldet einen Fehler und versucht es im nächsten Zyklus erneut, wie bei fehlenden Day-Ahead-Preisen.

Die Quelle je PV-Feld steht im Laufzustand (`optimizer_run_state.json`, Feld `pv_forecast_sources`: `forecast_solar`, `open_meteo` oder `none` bei 0 kWp), die Hauptquelle im Feld `pv_forecast_primary`.

<a id="horizont"></a>

### Horizont (Verschattung durch Gelände und Gebäude)

Steht die Sonne hinter einem Berg, einem Nachbarhaus oder einem Baum, erreicht sie das Haus nicht direkt. Earnie kann das einrechnen: Im Hauskonfigurator unter **Sonne & Horizont** den Schalter **Horizont berücksichtigen** einschalten und für 16 Himmelsrichtungen (alle 22,5°) den Höhenwinkel des Horizonts einstellen. Das Diagramm zeigt je Richtung einen Balken, beschriftet mit Himmelsrichtung und Azimut wie bei den PV-Feldern (Süd 0°, Ost -90°, West 90°): den Balken mit der Maus auf die Höhe ziehen oder mit ▲ / ▼ in 1°-Schritten ändern. Richtungen, die die Sonne am Standort nie erreicht, sind grau und bleiben auf 0°.

**Messen:** vom Dach oder von der PV-Anlage aus mit der Kompass-App die Richtung und mit der Neigungsmesser-App des Handys den Winkel bis zur Oberkante von Berg, Haus oder Baum anpeilen. 0° heißt freier Horizont. Das Diagramm zeigt hinter den Balken den Horizont als graue Fläche und die Sonnenbahnen am 21. Juni, zur Tagundnachtgleiche und am 21. Dezember. Wo eine Sonnenbahn unter dem Horizont liegt, fehlt an diesem Tag die direkte Sonne.

| Feld | Bedeutung |
| ---- | --------- |
| `horizon_source` | `manual`: die Liste in `horizon` wird angewendet. `none`: kein Horizont; eine vorhandene Liste bleibt gespeichert, wirkt aber nicht (Schalter aus). |
| `horizon` | Liste aus `azimuth_deg` (0 = Süd, -90 = Ost, 90 = West, ±180 = Nord, wie bei den PV-Feldern) und `elevation_deg` (0–90°). Zwischen den Punkten interpoliert Earnie linear, auch über Nord hinweg. |

```json
"horizon_source": "manual",
"horizon": [{"azimuth_deg": -90, "elevation_deg": 4},
            {"azimuth_deg": -45, "elevation_deg": 12},
            {"azimuth_deg": 0, "elevation_deg": 18},
            {"azimuth_deg": 45, "elevation_deg": 9},
            {"azimuth_deg": 90, "elevation_deg": 0}]
```

**So rechnet Earnie:** Für jede Stunde bestimmt Earnie den Sonnenstand an vier Zeitpunkten. Liegt die Sonne unter dem Horizont ihrer Richtung, entfällt für diesen Teil der Stunde die direkte Einstrahlung auf die Fläche. Das diffuse Licht des Himmels und das vom Boden reflektierte Licht bleiben. Dafür fragt Earnie bei Open-Meteo zusätzlich die Direktstrahlung (`direct_normal_irradiance`) ab, und zwar nur, wenn ein Horizont eingeschaltet ist.

**Wo der Horizont wirkt:**

- **PV-Ertrag** im Szenarien-Explorer und im Jahresmodell (Open-Meteo-Archiv), auch im Prognose-Modus des Szenarien-Explorers.
- **Solarthermie-Kollektor** und **solare Gewinne durch die Fenster**, im Jahresmodell und in der Live-Planung. Der Verlustkoeffizient H des Hauses wird mit den beschatteten Gewinnen kalibriert; die Jahres-Heizwärme bleibt also beim HWB.
- **PV-Prognose im Live-Betrieb:** Earnie übergibt den eingetragenen Horizont an forecast.solar (in 10°-Schritten, ganze Grad). Bei Open-Meteo wirkt er genauso, ob als Hauptquelle oder als Ersatz.

> **Wichtig für forecast.solar:** Ohne eingetragenen Horizont rechnet forecast.solar mit dem Gelände am Standort (PVGIS-Horizont). Der eingetragene Horizont **ersetzt** dieses Gelände. Tragen Sie deshalb auch entfernte Berge ein, nicht nur Nachbarhäuser und Bäume; sonst fehlt der Bergschatten in der PV-Prognose.

> **Hinweis:** Ein eingeschalteter Horizont ändert die Ergebnisse: PV-Ertrag und Kollektorwärme sinken vor allem im Winter und in den Randstunden. Ohne die beiden Felder oder mit ausgeschaltetem Schalter rechnet Earnie mit freiem Horizont.

## Wechselrichter (`inverters[]`)

PV-Felder und Batterien können über `inverter_id` auf denselben Wechselrichter verweisen (n:1). Im Hauskonfigurator gibt es dafür den Tab **Wechselrichter** und eine Auswahl in den PV- und Batterie-Formularen. Die Geräte-Vorlage **EcoFlow Delta 3** legt eine physische Powerstation samt integriertem Powerstation-Hybrid-Wechselrichter in einem Schritt an.

| Feld | Bedeutung |
|------|-----------|
| `type` | `hybrid` (PV + Batterie DC), `pv_string` (nur PV), `battery` (AC-gekoppelter Batterie-Wechselrichter ohne PV-Seite) |
| `ac_connection` | `grid_tied` = AC am Hausbus (Automatik/Optimieren möglich); `island` = speist nur angeschlossene Verbraucher, **nicht** den AC-Bus des Hauses (die PV dieses Wechselrichters zählt nicht in der Hausbilanz). Der AC-Eingang kann am Netz hängen (einseitige Last); `island` beschreibt also die **Bus-Teilnahme** und bedeutet nicht „netzlos“. |
| `max_ac_power_kw` | Optional: AC-Clipping bzw. Obergrenze der Entladung; ohne Wert gibt es keine Grenze |
| `max_pv_input_kw` | Optional: Obergrenze DC/MPPT |
| `max_ac_charge_kw` | Optional: Netzladen über den Wechselrichter |
| `control` | `full` \| `limits_only` \| `read_only` (wie bei Batterien) |
| `owned_by` | Batterie-ID bei integrierten Wechselrichtern (EcoFlow / physische Powerstation). Betrifft nur Oberfläche und Lebenszyklus: Anlegen, Anzeigen und Löschen geschehen zusammen mit der Batterie. |

**Einmal-Migration** älterer Konfigurationen (`batteries[].kind` oder fehlendes `inverters[]`): `python -m scripts.migrate_inverters_once --config-dir <config>` (mit `--dry-run` ohne Schreiben; ohne `--dry-run` wird geschrieben). Danach `kind` entfernen, da der Loader Restbestände sofort mit Fehler ablehnt.

**EHAL-Bindings:**

- **Batterien:** entity-scoped `ess.{slug}.*` in `batteries[].ehal_bindings`.
- **Wechselrichter:** `inv.{slug}.*` in `inverters[].ehal_bindings`.
- **PV-Felder:** optional `pv.{slug}.*` in `pv_systems[].ehal_bindings`.

In [EHAL-Com](../ui/ehal-com.md) erscheinen Hausspeicher, **physische** Powerstations, Wechselrichter und PV-Felder als Mapping-Entities. **Virtuelle** Powerstations haben kein eigenes Binding und nutzen die Hausbatterie. Speichern schreibt `components.json`, nicht `house_profiles.json`.

Die Quellenwahl `ess.{slug}.set_ess_source_select` gibt es nur an physischen `standby_backup`-Batterien, nicht in der Anlagen-Zeile. Die übrigen ESS-Felder gehören zur Batterie-Zeile. Loxone-Merker für mehrere Speicher tragen den Slug als Infix: `Earnie_Batterie_<Slug>_…`. Einmal-Migration von anlagenweiten (plant-flachen) Bindings auf die Batterie, inkl. Quellenwahl → Standby-Backup: `python -m scripts.migrate_ess_bindings_once --config-dir <config>`.

## Anlagen-Topologie (Live): drei Fragen

Vor dem Live-Betrieb muss die Wurzel der Bilanz klar sein: ein Zähler, ein Tarif und höchstens ein Regler auf diesen Zähler.

1. **Sitzt der Zähler direkt am Hausanschluss?** → `plant.grid_meter.at_house_connection` in `house_profiles.json` (Hauskonfigurator → **Netzanschluss & Netzentgelt**, Kasten „Anlagenweit“).
2. **Gibt es nur einen Tarif?** → `plant.grid_meter.single_tariff` (kein zweiter Abrechnungszähler hinter demselben Mapping).
3. **Regelt ein anderes Gerät selbst auf diesen Zähler?** → Hausbatterie mit `regulates_on: grid` (Eigenverbrauch / Zero-Export) oder `none` (folgt nur den Sollwerten). Fremdregler zählen ebenfalls mit; `control: read_only` heißt nur, dass Earnie nicht schreibt.

Im Live-Betrieb müssen beide `plant.grid_meter`-Flags `true` sein. Migration bestehender Anlagen:

```text
python -m scripts.migrate_topology_once --config-dir <config-dir>
```

Das Skript setzt `regulates_on: grid` für jede Hausbatterie und legt `plant.grid_meter` mit `true`/`true` an. Danach die drei Fragen bestätigen. Szenario-Explorer und Backtesting sind von den Live-Ablehnungen ausgenommen. Schema-Regeln, etwa eine Batterie an einem `pv_string`-Wechselrichter, gelten überall.

**Live-Bilanz:**

- **Speicherleistung:** Das Anlagen-`sens_ess_power` ist die Summe der gemappten `ess.{id}.sens_ess_power` aller netzgekoppelten Hausbatterien. Ein fehlendes Binding führt zu einem Fehler.
- **PV bei mehreren Wechselrichtern:** Bei mehreren netzgekoppelten Wechselrichtern mit PV bildet Earnie die Anlagen-PV immer als Summe der gemappten `inv.*`/`pv.*`-Leistungen (× η_inv). Ein flaches Anlagen-PV-Mapping wird in diesem Fall nicht verwendet; unvollständige Mappings führen zu einem Fehler.
- **Abgeleitete Hauslast:** Eine negative Restbilanz unterhalb der Toleranz (`plant.balance_tolerance_pct` / `balance_tolerance_w`, Defaults 5 % / 100 W) gilt als Telemetrie-Fehler. Earnie setzt sie nicht stillschweigend auf `0`.

Details: [EHAL-Spec § Plant topology](../referenz/ehal.md).

## Steuerbarkeit (`control`)

| Wert | MILP | Live-Sollwerte |
|------|------|----------------|
| `full` | Netzladen und Batterie-Export erlaubt | Zwangsladen / Zwangsentladen / Entladesperre / Automatik |
| `limits_only` | Nur PV-Überschuss laden, nur Hauslast decken | Nur Automatik / Entladesperre (Lade-/Entladegrenzen) |
| `read_only` | Eigenverbrauch-Kopplung (kein freier Fahrplan) | Keine ESS-Sollwerte |

Verlangt `control` mehr, als das EHAL-Mapping hergibt (z. B. `full` ohne `set_ess_active_power` und ohne `plant.ha_ess_force`), warnt EHAL-Com. Für Huawei ohne Wirkleistungs-Entity gibt es optional `plant.ha_ess_force` (`driver: huawei_solar`, `device_id`, `duration_min`), siehe [EHAL-Spec](../referenz/ehal.md) und [EHAL-Com](../ui/ehal-com.md).

<a id="einspeisegrenze"></a>

## Einspeisegrenze

Optional lässt sich im Hauskonfigurator eine statische Obergrenze für die Einspeisung setzen (`plant.max_export_power_kw`). Die wirksame Obergrenze ist das Minimum aus:

- dem Wert aus dem Hauskonfigurator,
- der vom Smarthome gemeldeten Grenze über EHAL (inbound, `get_grid_export_power_limit`),
- **0**, wenn der Einspeisetarif negativ ist (Einspeisung kostet dann Geld).

Gilt keine Begrenzung, schreibt Earnie die maximal mögliche Einspeisung der Anlage auf `set_grid_export_power_limit`. Dafür summiert Earnie über alle netzgekoppelten Wechselrichter `min(max_ac_power_kw, PV-kWp begrenzt durch max_pv_input_kw + Zwangsentlade-kW)`:

- **Insel-Wechselrichter** zählen nicht.
- **Ohne Wechselrichter in der Anlagen-Topologie** (keine Wechselrichter angelegt) rechnet Earnie mit der Summe aus PV-kWp und max. Entladeleistung der Batterien mit `control = full`. Batterien mit `limits_only` oder `read_only` zählen nicht. Powerstations (`type: powerstation`) zählen nicht mit, da sie nicht ins Hausnetz zurückspeisen.
- **Ist das Ergebnis 0 oder unbekannt** (weder PV-kWp noch Zwangsentladeleistung hinterlegt bzw. keine netzgekoppelten Wechselrichter), schreibt Earnie als Obergrenze `1000` kW (EHAL: 1 000 000 W).

Die Umsetzung im Smarthome-System (z. B. Abregelung in Loxone Config) beschreibt die jeweilige Anbindungs-Doku, für Loxone die [Loxone-Anbindung](../einrichtung/loxone-anbindung.md).

## SOC-Verhalten

Der Parameter `battery_wear` kann niedrigere End-SOCs wirtschaftlich bestrafen. Das ist ein weicher Anreiz, unabhängig vom Modus. Der Block gehört zum jeweiligen Eintrag in `components.json` → `batteries[]`.

Block `planning_horizon` in `config.json`:

```json
"planning_horizon": {
  "mode": "sunrise_window"
}
```

Details: [Spezifikation Sunset-Planungshorizont](../dev/done/planning-horizon-sunset.md) (Entwickler-Doku).

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

Im Hauskonfigurator unter **Batterien** schaltet die Checkbox „Verschleiß berücksichtigen“ die drei Parameter frei. Direktes Bearbeiten von `components.json` ist ebenfalls möglich.



## Live-Szenario vs. `config.json`

Auf der Seite **Szenarienkonfigurator** erfolgt die Auswahl der Entitäts-Referenzen für das Live-Szenario (PV und Batterien als Mehrfachauswahl). Earnie speichert das Live-Szenario in `backtesting_scenarios.json` (`live_scenario_id` in `config.json`, Standard: `live`). Die PV- und Batterie-Entitäten selbst entstehen im **Hauskonfigurator**. Die Bezeichnung des Live-Szenarios ist fest.

## Szenarien

Varianten lassen sich mit dem Live-Szenario vergleichen, ohne den Produktivbetrieb zu ändern, etwa ein größerer Speicher, mehrere PV-Felder oder ein anderer Strom-Tarif. Dafür weitere Einträge in `backtesting_scenarios.json` anlegen (siehe [Überblick](overview.md)).
