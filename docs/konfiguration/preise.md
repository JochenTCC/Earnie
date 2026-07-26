# Preise & aWATTar

**Nachrechnen für Anwender:** [Tarife und Preise nachrechnen](../referenz/tarife-quellen.md) — Schritt-für-Schritt Bezugs-/Einspeisepreis, SE-Fixkosten und Fake-Jahresrechnung.

Live-Bezugspreise kommen über Spot-Tarife (`spot_hourly` u. a.) mit Day-Ahead-Marktpreis. Providerunabhängige EPEX-Daten für Planung/Backtesting kommen standardmäßig von **Energy-Charts** (AT/DE/CH); aWATTar bleibt API-Fallback. Die aWATTar-API-URL wird aus `import_tariff_id` → `land` abgeleitet (nicht aus dem Tarif-`type`).

Quellen und rechtliche Anker: [Tarife und Preise nachrechnen](../referenz/tarife-quellen.md), [OeMAG & Referenzmarktwert](../referenz/oemag-referenzmarktwert.md).

**Fixkosten (SE only):** `monthly_fee_eur` (Lieferant-Grundpreis; Deduplizierung über `supplier_id`), optional `grid_monthly_fee_eur` / `metering_monthly_fee_eur` / `other_monthly_fee_eur` (einmal je Hausanschluss aus Bezug, sonst Einspeise). Netto/brutto wie `prices_include_vat`. Nur in **Szenario-Explorer**-Gesamt-/Monatskosten und in Fake-Jahresrechnungen unter `{Log}/invoices/`, nicht in Live-MILP und nicht in stündlichen `sim_cost`. Details: [tarife-quellen.md](../referenz/tarife-quellen.md) §4.

**Land am Hausprofil:** Im Hauskonfigurator (Standort) wird `land` (`AT`/`DE`/`CH`) gespeichert. Der Szenarienkonfigurator-Filter **Land** ist Pflicht (kein „Alle“) und wird aus dem gewählten Hausprofil vorbelegt.

## Bezugspreis (Live)

Live-Optimierung löst die `import_tariff_id` des Live-Szenarios gegen `earnie_env/config/tariffs.json` auf (Seed aus öffentlichem [`share/config/tariffs.json`](../../share/config/tariffs.json)). Aufschläge stehen **am Tarif-Eintrag** (`settlement_fee_cent_kwh`, `markup_percent`, `vat_percent` / `prices_include_vat`).

Marktpreise (Live) kommen je nach Provider von Energy-Charts bzw. der aWATTar-API; die aWATTar-URL aus `land` (AT → `api.awattar.at`, DE → `api.awattar.de`). Berechnung des **Bezugspreises in Cent/kWh**:

```
(Marktpreis × (1 + markup_percent/100) + settlement_fee_cent_kwh)
  × (1 + vat_percent/100)   falls prices_include_vat = false
```


| Feld (Spot-Import in tariffs.json) | Bedeutung                                   |
| ---------------------------------- | ------------------------------------------- |
| `settlement_fee_cent_kwh`          | Fixer Aufschlag Netz/Gebühren in Cent/kWh   |
| `markup_percent`                   | Prozentualer Aufschlag (z. B. 3 ≈ Netzverlust) |
| `vat_percent` / `prices_include_vat` | USt (z. B. 20 % bei `prices_include_vat=false`) |




## Einspeisevergütung (Live)

Live-Optimierung löst die `export_tariff_id` des Live-Szenarios auf. Bei Typ `fixed` kommt `k_push_cent` aus dem Tarif-Eintrag in `tariffs.json`. Geändert wird die Tarif-Referenz im Live-Szenario im **Szenarienkonfigurator**.

**Hinweis:** Vergütung kann sich ändern (z. B. monatlich). Tarif in `tariffs.json` bzw. gewählte `export_tariff_id` aktuell halten.

## Planung & Backtesting (ab 1.24.f)

Der veröffentlichte Katalog liegt in [`share/config/tariffs.json`](../../share/config/tariffs.json) mit Root-Feld `catalog_as_of`. Zur Laufzeit nutzt Earnie `earnie_env/config/tariffs.json` (Bootstrap kopiert den Katalog bei Bedarf aus share). Szenarien in `backtesting_scenarios.json` referenzieren `import_tariff_id` und `export_tariff_id`.

### Import-Typen


| Typ              | Bedeutung                                                                                             |
| ---------------- | ----------------------------------------------------------------------------------------------------- |
| `fixed_cent`     | Fixer Arbeitspreis (`fix_cent_kwh`)                                                                   |
| `spot_hourly`    | EPEX × (1 + `markup_percent`%) + `settlement_fee_cent_kwh` (+ optional `netzentgelt_cent_kwh` für DE) |
| `ex_post_spot`   | Wie Spot; Kennzeichnung ex-post-Abrechnung                                                            |
| `monthly_market` | Wie Spot; Kennzeichnung Monatsmarkt                                                                   |
| `monthly_table`  | Monatstabelle Bezug (`monthly_rates`)                                                                 |




### Export-Typen


| Typ                            | Bedeutung                                                                 |
| ------------------------------ | ------------------------------------------------------------------------- |
| `fixed`                        | Konstante Vergütung (`k_push_cent`)                                       |
| `spot_hourly` / `ex_post_spot` | EPEX − `feed_in_fee_factor` × \|EPEX\| − `settlement_fee_cent_kwh` + `feed_in_fix_cent` (Faktor/Fix optional, Standard 0) |
| `monthly_table`                | Monatskonstante Vergütung (`monthly_rates` am Tarif)                      |


Interner Runtime-`feed_in_mode` für stündliche EPEX-Einspeise bleibt `dynamic_epex` (nicht mit dem entfernten Katalog-`type` verwechseln). Beispiel mit Prozentabschlag: Katalog-id `dynamic_epex` (aWATTar SUNNY SPOT) als `spot_hourly` mit `feed_in_fee_factor: 0.19`.

Berechnung: `[data/tariff_pricing.py](../../data/tariff_pricing.py)` (`import_cent_kwh`, `export_cent_kwh`). Die MILP-Matrix nutzt `k_act` (Bezug) und `k_push_act` (Einspeise) je Stunde.

### Marktzonen (Backtesting)


| Land (`land`) | Zone  | Datenquelle (API)                                      |
| ------------- | ----- | ------------------------------------------------------ |
| AT            | AT    | Energy-Charts (`bzn=AT`); Fallback aWATTar AT           |
| DE            | DE-LU | Energy-Charts oder optional `api.awattar.de`           |
| CH            | CH    | Energy-Charts                                          |


`simulation/engine.py` und `data/backtesting_prices.py` werten `_import_tariff_spec` / `_export_tariff_spec` aus der Szenario-Auflösung aus. Day-Ahead-Daten: [Energy-Charts](https://energy-charts.info) (Fraunhofer ISE), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

DACH-Katalog importieren: `tools/convert_dach_tariffs.py` aus `stromtarife_dach_kombiniert.json` + `einspeisetarife_dach_erweitert.json`.

Plausibilität prüfen (vor Deploy / NAS-Cutover):

```powershell
python -m scripts.validate_tariffs --check-catalog
tools/convert_dach_tariffs.py --check
```



### Monatspreis (`monthly_table`) — OeMAG / RefMarkt vs. aWATTar-SUNNY

Monatskonstante Einspeisetarife tragen **eigene** `monthly_rates`. Shared-Kurven in `tariffs.json` dienen der Katalog-Wartung (Seeds):


| Feld                                   | Zweck                                                                 |
| -------------------------------------- | --------------------------------------------------------------------- |
| `oemag_monthly_feed_in_rates`          | ≥12 OeMAG-Gesetzliche-Marktpreise (Wartungskurve; länger für SE)      |
| `monthly_float_reference_cent_kwh`     | Historischer Nenner für OeMAG-proportionale Seeds (z. B. 7,15)        |
| `econtrol_referenzmarktwert_pv_monthly`| ≥12 E-Control Referenzmarktwert PV (§ 13 EAG; z. B. VKW Flex-Seed)    |


Seed-Formel (nur Wartung, nicht Runtime):  
`OeMAG_Monat × arbeitspreis / monthly_float_reference_cent_kwh − settlement_fee` (min. 0) — Hilfsfunktion in `[data/monthly_float_rates.py](../../data/monthly_float_rates.py)`.

Rechtliche Abgrenzung OeMAG vs. RefMarkt: [oemag-referenzmarktwert.md](../referenz/oemag-referenzmarktwert.md).

aWATTar-SUNNY-Fixwerte liegen ebenfalls als `monthly_table` (z. B. `monthly_sunny`).

## Fehlende Zukunftspreise (Live)

Block `market_prices` in `config.json`:


| Feld                     | Bedeutung                                                          |
| ------------------------ | ------------------------------------------------------------------ |
| `missing_price_strategy` | `forecast` (Standard) oder `mirror`                                |
| `forecast_model_path`    | Pfad zu `price_model_coefficients.json` (für Strategie `forecast`) |


Wenn die aWATTar-API für späte Stunden des Horizonts noch keine Preise liefert:

- `forecast` (Standard): OLS-Korrelationsmodell (Wind/Solar EU) extrapoliert fehlende Stunden — in Charts als grüner Bereich gekennzeichnet (siehe [Charts](../ui/charts.md)).
- `mirror`: gleiche Uhrzeit vom Vortag; Fallback auch automatisch, wenn das Forecast-Modell nicht geladen werden kann.

Spec: [Preis-Prognose (Dev)](../spec/price-forecast-renewables.md).

## Historische Preise

Für **Backtesting** (und geplante Dev-Nachrechnung): `scenario_explorer_conf.price_source`, `price_provider`, `price_range` und ggf. `path_price` (Energy-Charts-CSV, Zone `energy_charts_bzn`). Der Simulations-Gesamtzeitraum kommt aus `cons_data` (12 Kalendermonate bis zum letzten vollständigen Monat), nicht aus ehemaligen Loxone-Pfadpaaren.

### Monatliche Fixtarife (Backtesting)

Export-Tarif-Typ `monthly_table` in `tariffs.json` liefert die Monatswerte (`monthly_rates`). **Sunset-2-Sunset** (Produktiv) nutzt die aufgelöste Export-Tarif-Referenz aus dem Live-Szenario.