# Preise & aWATTar

Live-Bezugspreise kommen heute über Tarif-Einträge vom Typ `awattar` (API AT/DE). Weitere Import-Typen und providerunabhängige EPEX-Anbindung sind im Backlog vorgesehen — die Felder und Auflösung unten gelten bereits für den Tarifkatalog.

## Bezugspreis (Live)

Live-Optimierung löst die `import_tariff_id` des Live-Szenarios gegen `earnie_env/config/tariffs.json` auf (Seed aus öffentlichem [`share/config/tariffs.json`](../../share/config/tariffs.json)). Bei Typ `awattar` gelten dieselben Aufschläge wie bei Spot-Tarifen **am Tarif-Eintrag** (`settlement_fee_cent_kwh`, `markup_percent`, `vat_percent` / `prices_include_vat`).

Stundenpreise kommen von der aWATTar-API; die URL wird aus `import_tariff_id` → `land` abgeleitet (AT → `api.awattar.at`, DE → `api.awattar.de`). Berechnung des **Bezugspreises in Cent/kWh**:

```
(Marktpreis (API) × (1 + markup_percent/100) + settlement_fee_cent_kwh)
  × (1 + vat_percent/100)   falls prices_include_vat = false
```


| Feld (Tarif `awattar` in tariffs.json) | Bedeutung                                   |
| -------------------------------------- | ------------------------------------------- |
| `settlement_fee_cent_kwh`              | Fixer Aufschlag Netz/Gebühren in Cent/kWh   |
| `markup_percent`                       | Prozentualer Aufschlag (z. B. 3 ≈ Netzverlust) |
| `vat_percent` / `prices_include_vat`   | USt (z. B. 20 % bei `prices_include_vat=false`) |




## Einspeisevergütung (Live)

Live-Optimierung löst die `export_tariff_id` des Live-Szenarios auf. Bei Typ `fixed` kommt `k_push_cent` aus dem Tarif-Eintrag in `tariffs.json`. In der UI (Seite **Live-Konfiguration**) ist die aufgelöste Vergütung read-only; geändert wird die Tarif-Referenz im Live-Szenario.

**Hinweis:** Vergütung kann sich ändern (z. B. monatlich). Tarif in `tariffs.json` bzw. gewählte `export_tariff_id` aktuell halten.

## Planung & Backtesting (ab 1.24.f)

Der veröffentlichte Katalog liegt in [`share/config/tariffs.json`](../../share/config/tariffs.json) mit Root-Feld `catalog_as_of`. Zur Laufzeit nutzt Earnie `earnie_env/config/tariffs.json` (Bootstrap kopiert den Katalog bei Bedarf). Szenarien in `backtesting_scenarios.json` referenzieren `import_tariff_id` und `export_tariff_id`.

### Import-Typen


| Typ              | Bedeutung                                                                                             |
| ---------------- | ----------------------------------------------------------------------------------------------------- |
| `awattar`        | Aufschläge am Tarif-Eintrag in `tariffs.json`; API-URL aus `land`                                     |
| `fixed_cent`     | Fixer Arbeitspreis (`fix_cent_kwh`)                                                                   |
| `spot_hourly`    | EPEX × (1 + `markup_percent`%) + `settlement_fee_cent_kwh` (+ optional `netzentgelt_cent_kwh` für DE) |
| `ex_post_spot`   | Wie Spot; Kennzeichnung ex-post-Abrechnung                                                            |
| `monthly_market` | Wie Spot; Kennzeichnung Monatsmarkt                                                                   |




### Export-Typen


| Typ                            | Bedeutung                                                                  |
| ------------------------------ | -------------------------------------------------------------------------- |
| `fixed`                        | Konstante Vergütung (`k_push_cent`)                                        |
| `dynamic_epex`                 | EPEX − `feed_in_fee_factor` × |EPEX| + `feed_in_fix_cent` aus Export-Tarif |
| `spot_hourly` / `ex_post_spot` | EPEX − `settlement_fee_cent_kwh`                                           |
| `monthly_table`                | Monatliche Fixwerte (`monthly_rates`)                                      |
| `monthly_float`                | OeMAG-Referenzkurve skaliert mit `arbeitspreis_kwh_cent` (siehe unten)     |


Berechnung: `[data/tariff_pricing.py](../../data/tariff_pricing.py)` (`import_cent_kwh`, `export_cent_kwh`). Die MILP-Matrix nutzt `k_act` (Bezug) und `k_push_act` (Einspeise) je Stunde.

### Marktzonen (Backtesting)


| Land (`land`) | Zone  | Datenquelle (API)                            |
| ------------- | ----- | -------------------------------------------- |
| AT            | AT    | aWATTar AT                                   |
| DE            | DE-LU | Energy-Charts oder optional `api.awattar.de` |
| CH            | CH    | Energy-Charts                                |


`simulation/engine.py` und `data/backtesting_prices.py` werten `_import_tariff_spec` / `_export_tariff_spec` aus der Szenario-Auflösung aus.

DACH-Katalog importieren: `tools/convert_dach_tariffs.py` aus `stromtarife_dach_kombiniert.json` + `einspeisetarife_dach_erweitert.json`.

Plausibilität prüfen (vor Deploy / NAS-Cutover):

```powershell
python -m scripts.validate_tariffs --check-catalog
tools/convert_dach_tariffs.py --check
```



### monthly_float — OeMAG-Referenz vs. aWATTar-SUNNY

Referenzdaten für `monthly_float` in `backtesting_scenarios.json`:


| Feld                               | Zweck                                                                      |
| ---------------------------------- | -------------------------------------------------------------------------- |
| `oemag_monthly_feed_in_rates`      | 12 bekannte OeMAG-Gesetzliche-Marktpreise (Referenzkurve)                  |
| `monthly_float_reference_cent_kwh` | Nenner für Skalierung (OeMAG `arbeitspreis_kwh_cent`, z. B. 7,15)          |


Export-Tarif-Typ `monthly_float` in `tariffs.json`: Skalierung pro Monat  
`OeMAG_Monat × arbeitspreis_kwh_cent / 7,15 − settlement_fee_cent_kwh` (min. 0).  
Berechnung: `[data/monthly_float_rates.py](../../data/monthly_float_rates.py)`.

aWATTar-SUNNY-Fixwerte liegen als Export-Tarif-Typ `monthly_table` in `tariffs.json` (z. B. `monthly_sunny`).

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

Für **Backtesting** (und geplante Dev-Nachrechnung): `file_paths_battery_simulation.price_source`, `price_provider`, `price_range` und ggf. `path_price` (Energy-Charts-CSV, Zone `energy_charts_bzn`).

### Monatliche Fixtarife (Backtesting)

Export-Tarif-Typ `monthly_table` in `tariffs.json` liefert die Monatswerte (`monthly_rates`). **Sunset-2-Sunset** (Produktiv) nutzt die aufgelöste Export-Tarif-Referenz aus dem Live-Szenario.