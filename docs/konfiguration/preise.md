# Preise & aWATTar

## Bezugspreis (Live)

Live-Optimierung löst `runtime_settings.import_tariff_id` gegen [`config/tariffs.json`](../../config/tariffs.json) auf. Bei Typ `awattar` gelten die Aufschläge **am Tarif-Eintrag** (`fix_aufschlag_cent`, `netzverlust_faktor`, `mwst_austria_faktor`).

Stundenpreise kommen von der aWATTar-API; die URL wird aus `import_tariff_id` → `land` abgeleitet (AT → `api.awattar.at`, DE → `api.awattar.de`). Berechnung des **Bezugspreises in Cent/kWh**:

```
Marktpreis (API)
  × netzverlust_faktor
  + fix_aufschlag_cent
  × mwst_austria_faktor   (falls konfiguriert)
```

| Feld (Tarif `awattar` in tariffs.json) | Bedeutung |
|-------------------|-----------|
| `fix_aufschlag_cent` | Fixer Aufschlag Netz/Gebühren in Cent/kWh |
| `netzverlust_faktor` | Multiplikator für Netzverluste (z. B. 1.03) |
| `mwst_austria_faktor` | USt-Faktor (z. B. 1.2 für 20 %) |

## Einspeisevergütung (Live)

Live-Optimierung löst `runtime_settings.export_tariff_id` auf. Bei Typ `fixed` kommt `k_push_cent` aus dem Tarif-Eintrag in `tariffs.json`. In der UI (Seite **Konfiguration**) ist die aufgelöste Vergütung read-only; geändert wird die Tarif-Referenz, nicht mehr ein flaches `k_push_cent` in `runtime_settings`.

**Hinweis:** Vergütung kann sich ändern (z. B. monatlich). Tarif in `tariffs.json` bzw. gewählte `export_tariff_id` aktuell halten.

## Planung & Backtesting (ab 1.24.f)

Tarife liegen in [`config/tariffs.json`](../../config/tariffs.json) mit Root-Feld `catalog_as_of` (Stand der Tarifliste). Szenarien in `backtesting_scenarios.json` referenzieren `import_tariff_id` und `export_tariff_id`.

### Import-Typen

| Typ | Bedeutung |
|-----|-----------|
| `awattar` | Aufschläge am Tarif-Eintrag in `tariffs.json`; API-URL aus `land` |
| `fixed_cent` | Fixer Arbeitspreis (`fix_cent_kwh`) |
| `spot_hourly` | EPEX × (1 + `markup_percent`%) + `settlement_fee_cent_kwh` (+ optional `netzentgelt_cent_kwh` für DE) |
| `ex_post_spot` | Wie Spot; Kennzeichnung ex-post-Abrechnung |
| `monthly_market` | Wie Spot; Kennzeichnung Monatsmarkt |

### Export-Typen

| Typ | Bedeutung |
|-----|-----------|
| `fixed` | Konstante Vergütung (`k_push_cent`) |
| `dynamic_epex` | EPEX − `feed_in_fee_factor` × \|EPEX\| + `feed_in_fix_cent` aus Export-Tarif |
| `spot_hourly` / `ex_post_spot` | EPEX − `settlement_fee_cent_kwh` |
| `monthly_table` | Monatliche Fixwerte (`monthly_rates`) |
| `monthly_float` | OeMAG-Referenzkurve skaliert mit `arbeitspreis_kwh_cent` (siehe unten) |

Berechnung: [`data/tariff_pricing.py`](../../data/tariff_pricing.py) (`import_cent_kwh`, `export_cent_kwh`). Die MILP-Matrix nutzt `k_act` (Bezug) und `k_push_act` (Einspeise) je Stunde.

### Marktzonen (Backtesting)

| Land (`land`) | Zone | Datenquelle (API) |
|---------------|------|-------------------|
| AT | AT | aWATTar AT |
| DE | DE-LU | Energy-Charts oder optional `api.awattar.de` |
| CH | CH | Energy-Charts |

`simulation/engine.py` und `data/backtesting_prices.py` werten `_import_tariff_spec` / `_export_tariff_spec` aus der Szenario-Auflösung aus.

DACH-Katalog importieren: `tools/convert_dach_tariffs.py` aus `stromtarife_dach_kombiniert.json` + `einspeisetarife_dach_erweitert.json`.

### monthly_float — OeMAG-Referenz vs. aWATTar-SUNNY

Zwei getrennte Monatstabellen in `backtesting_scenarios.json`:

| Feld | Zweck |
|------|--------|
| `oemag_monthly_feed_in_rates` | 12 bekannte OeMAG-Gesetzliche-Marktpreise (Referenzkurve) |
| `monthly_float_reference_cent_kwh` | Nenner für Skalierung (OeMAG `arbeitspreis_kwh_cent`, z. B. 7,15) |
| `fixed_monthly_feed_in_rates` | aWATTar-SUNNY / Legacy `feed_in_mode=fixed` (Jun/Jul 2026: 3,60 / 6,46 ct) |

Export-Tarif-Typ `monthly_float` in `tariffs.json`: Skalierung pro Monat  
`OeMAG_Monat × arbeitspreis_kwh_cent / 7,15 − settlement_fee_cent_kwh` (min. 0).  
Berechnung: [`data/monthly_float_rates.py`](../../data/monthly_float_rates.py).

## Fehlende Zukunftspreise

Wenn die API für späte Stunden des 24h-Horizonts noch keine Preise liefert, **spiegelt** die Optimierung die gleiche Uhrzeit vom Vortag (in Charts als extrapoliert gekennzeichnet — siehe [Charts](../ui/charts.md)).

## Historische Preise

Für **Backtesting** (und geplante Dev-Nachrechnung): `file_paths_battery_simulation.price_source`, `price_provider`, `price_range` und ggf. `path_price` (Energy-Charts-CSV, Zone `energy_charts_bzn`).

### Monatliche Fixtarife (Backtesting)

In `config/backtesting_scenarios.json` kann `fixed_monthly_feed_in_rates` die aWATTar-SUNNY-Fixwerte pro Monat enthalten. Alternativ Export-Tarif-Typ `monthly_table` in `tariffs.json`. **Sunset-2-Sunset** (Produktiv) nutzt die aufgelöste Export-Tarif-Referenz aus `runtime_settings.export_tariff_id`.
