# Preise & aWATTar

**Nachrechnen für Anwender:** [Tarife und Preise nachrechnen](../referenz/tarife-quellen.md) erklärt Schritt für Schritt Bezugs- und Einspeisepreis, SE-Fixkosten und Fake-Jahresrechnung.

Diese Seite beschreibt die Konfiguration: Tariftypen, JSON-Felder und Datenquellen.

## Überblick: Woher kommen die Preise?

Live-Bezugspreise entstehen aus Spot-Tarifen (`spot_hourly` u. a.) und dem Day-Ahead-Marktpreis. Earnie fragt die Quellen in dieser Reihenfolge ab:

1. **ENTSO-E**, wenn `ENTSOE_API_TOKEN` in `config/.env` gesetzt ist,
2. **Energy-Charts** (Fraunhofer),
3. Cache,
4. **aWATTar**.

Providerunabhängige EPEX-Daten für Planung und Backtesting kommen weiterhin von **Energy-Charts** (AT/DE/CH); aWATTar bleibt dort API-Fallback. Die aWATTar-API-URL leitet Earnie aus `import_tariff_id` → `land` ab, nicht aus dem Tarif-`type`.

Quellen und rechtliche Grundlagen: [Tarife und Preise nachrechnen](../referenz/tarife-quellen.md), [OeMAG & Referenzmarktwert](../referenz/oemag-referenzmarktwert.md).

### Fixkosten (nur SE)

- **Lieferanten-Grundpreis:** `monthly_fee_eur`; doppelte Einträge fasst Earnie über `supplier_id` zusammen.
- **Weitere Monatsgebühren (optional):** `grid_monthly_fee_eur`, `metering_monthly_fee_eur` und `other_monthly_fee_eur`. Sie zählen einmal je Hausanschluss, und zwar aus dem Bezugstarif, sonst aus dem Einspeisetarif.
- **Netto oder brutto:** **EPEX-/Spot-Tarife** immer **netto** speichern und `prices_include_vat` = false setzen (gleiche Basis wie Settlement und Markup). Bei Festpreisen richtet sich netto/brutto nach `prices_include_vat`.
- **Wirkung:** Die Fixkosten erscheinen nur in den Gesamt- und Monatskosten des **Szenario-Explorers** und in den Fake-Jahresrechnungen unter `{Log}/invoices/`. Live-MILP und stündliche `sim_cost` enthalten sie nicht.

Details: [tarife-quellen.md](../referenz/tarife-quellen.md) §4.

### Netznutzungsentgelte (Arbeitspreis)

Der Arbeitspreis für die Netznutzung steht am Hausprofil unter Standort im Objekt `netznutzung` (Cent/kWh **netto**, ohne USt).

- Er ist unabhängig vom Lieferantentarif.
- Earnie addiert ihn **vor** der USt zum Bezugspreis. Das gilt für Live-MILP und SE und für alle Import-Typen.
- In Fake-Jahresrechnungen erscheint er als eigene Position. Earnie rechnet ihn dafür aus dem Energiebezug heraus; bei Zeitfenstern ist er je Fenster aufgeschlüsselt.
- Der Arbeitspreis kann **zeitabhängig** sein (SNAP/WiNAP, siehe unten).
- Der Leistungspreis ist nicht modelliert.
- Der monatliche Netz-Grundpreis `grid_monthly_fee_eur` ist nur ein Platzhalter für die SE-Fixkosten.

### Netznutzung am Hausprofil (`netznutzung`)

| Feld | Bedeutung |
| --- | --- |
| `area_id` | Netzbereich aus dem Katalog `earnie_env/config/grid_fees.json` (Seed aus öffentlichem [`share/config/grid_fees.json`](../../share/config/grid_fees.json); z. B. `AT-VBG`). `null` = eigener Wert ohne Zeitregeln. |
| `power_metering` | `unmetered_power` (Standard Haushalt, nicht gemessene Leistung) oder `metered_power`; wählt den Basis-Arbeitspreis im Katalog. |
| `quarter_hour_meter` | Viertelstunden-Smart-Meter vorhanden. Voraussetzung für SNAP/WiNAP; ohne diesen Zähler überspringt Earnie die Regeln und weist das in UI und Jahresrechnung aus. |
| `base_cent_kwh` | Eigener Basis-Arbeitspreis (Cent/kWh netto); nur ohne `area_id` wirksam. |
| `include_status` | Welche Regel-Stati gelten. Standard ist nur `verordnet`; `entwurf` und `illustrativ` müssen bewusst aktiviert werden. |

**Zeitregeln** liegen im Katalog je Regelsatz (`rule_sets`). Eine Regel besteht aus:

- **Gültigkeit:** `valid_from` / `valid_to`.
- **Zeitraum:** Monate, Wochentage und Uhrzeitfenster. Ein Fenster darf über Mitternacht gehen und gilt in der Ortszeit des Hausprofils. Monat und Wochentag zählen nach dem Datum des Slots.
- **Wirkung:** `percent_off`, `absolute_cent` oder `add_cent`.
- **Voraussetzungen:** `requires`.
- **Status:** `status`.

Passt mehr als eine Regel, gewinnt die erste. Eine einbezogene Regel ohne Wert ist ein Fehler; Earnie ersetzt den Wert nicht stillschweigend.

| Regel | Fenster | Wirkung | Status |
| --- | --- | --- | --- |
| **SNAP** (Sommer-Nieder-Arbeitspreis) | 1.4.–30.9., 10–16 Uhr, NE 7 | −20 % auf den Arbeitspreis | verordnet (seit 1.4.2026) |
| **WiNAP** (Winter-Nieder-Arbeitspreis) | 1.10.–31.3., 22–4 Uhr, NE 7 | Höhe offen | Entwurf, im Katalog vorbereitet, standardmäßig aus |

Die Katalogwerte stammen aus einer Recherche (SNE-V 2018, Fassung 01.04.2026; SNAP-Abschlag laut Netzbetreibern). Sie sind nicht gegen die jeweiligen Preisblätter geprüft. Netzbetreiber können Voraussetzungen (z. B. Opt-in) unterschiedlich handhaben. Der Netzverlust-Anteil ist nicht enthalten.

**Migration:** Das frühere Feld `netznutzung_arbeitspreis_cent_kwh` wird nicht mehr gelesen; beim Laden erscheint eine Fehlermeldung. Einmalig umstellen mit:

```powershell
python -m scripts.migrate_grid_fee_profile --path earnie_env/config/house_profiles.json
```

Der Preis bleibt dabei gleich. Danach den Netzbereich im Hausprofil wählen oder `--area-id AT-VBG --quarter-hour-meter` übergeben.

### Land am Hausprofil

Der Hauskonfigurator speichert unter Standort das Feld `land` (`AT`/`DE`/`CH`). Im Szenarienkonfigurator ist der Filter **Land** Pflicht (kein „Alle“); er wird aus dem gewählten Hausprofil vorbelegt.

## Bezugspreis (Live)

Die Live-Optimierung löst die `import_tariff_id` des Live-Szenarios gegen `earnie_env/config/tariffs.json` auf (Seed aus öffentlichem [`share/config/tariffs.json`](../../share/config/tariffs.json)). Aufschläge stehen **am Tarif-Eintrag** (`settlement_fee_cent_kwh`, `markup_percent`, `vat_percent` / `prices_include_vat`).

### Marktpreise abrufen

Die Marktpreise (Live) kommen aus der Gebotszone des Hausprofil-`land` (AT / DE-LU / CH).

- **ENTSO-E:** Mit `ENTSOE_API_TOKEN` in `config/.env` fragt Earnie zuerst die **ENTSO-E Transparency Platform** ab (A44 Day-Ahead). AT/DE-LU liefern meist PT15M, CH derzeit PT60M; Earnie expandiert stündliche Werte auf QH.
- **Energy-Charts:** Ohne Token oder bei ENTSO-E-Ausfall folgt **Energy-Charts** (Fraunhofer).
- **Cache:** Erfolgreiche Abrufe speichert Earnie unter `runtime/live_day_ahead_<zone>.json` (Feld `source`: `entsoe` / `energy_charts`). Earnie verwendet sie wieder, solange die Serie das Planungsfenster abdeckt und seit dem letzten Day-Ahead-Publish (~12:00 Ortszeit) frisch ist. Ist ein Refresh nötig und liegt der Spiegel-Lookback (7 Tage) schon im Cache, fragt Earnie nur ab **heute 00:00** bis Planungsende ab und füllt die Historie aus dem Cache.
- **Ausfall beider Netzquellen:** Earnie nutzt zuerst diesen QH-Cache. Erst wenn der Cache fehlt oder das Fenster nicht abdeckt, folgt der Fallback **aWATTar** (stündlich, auf 15-Min-Slots expandiert). Die aWATTar-URL ergibt sich aus `land` (AT → `api.awattar.at`, DE → `api.awattar.de`).

### Berechnung

Der **Bezugspreis in Cent/kWh** ergibt sich so:

```
(Marktpreis × (1 + markup_percent/100) + settlement_fee_cent_kwh
  + Netznutzung Arbeitspreis aus Hausprofil, je Slot inkl. Zeitregeln)
  × (1 + vat_percent/100)   falls prices_include_vat = false
```

| Feld (Spot-Import in tariffs.json) | Bedeutung |
| --- | --- |
| `settlement_fee_cent_kwh` | Fixer Aufschlag Netz/Gebühren in Cent/kWh |
| `markup_percent` | Prozentualer Aufschlag (z. B. 3 ≈ Netzverlust) |
| `vat_percent` / `prices_include_vat` | USt (z. B. 20 % bei `prices_include_vat=false`) |

Das Hausprofil-Objekt `netznutzung` (siehe oben) gilt zusätzlich für **alle** Import-Typen.

## Einspeisevergütung (Live)

Die Live-Optimierung löst die `export_tariff_id` des Live-Szenarios auf. Bei Typ `fixed` kommt `k_push_cent` aus dem Tarif-Eintrag in `tariffs.json`. Die Tarif-Referenz im Live-Szenario lässt sich im **Szenarienkonfigurator** ändern.

**Eigener Festpreis:** Die Dropdowns Bezug und Einspeise im Szenarienkonfigurator enthalten den Eintrag **Eigener Festpreis**. Earnie speichert die Cent/kWh-Werte am Szenario in `backtesting_scenarios.json` (`user_import_cent_kwh` / `user_export_cent_kwh`, Tarif-ID `__user_fixed__`), also nicht in `tariffs.json`.

- **Bezug:** Lieferanten-Arbeitspreis inkl. USt (wie Katalog-`fixed_cent`). Der Netznutzungs-Arbeitspreis aus dem Hausprofil wird weiterhin addiert.
- **Einspeise:** eingegebene Vergütung ohne weitere Aufschläge.

> **Hinweis:** Die Vergütung kann sich ändern (z. B. monatlich). Tarif in `tariffs.json` bzw. die gewählte `export_tariff_id` aktuell halten.

## Planung & Backtesting

Der veröffentlichte Katalog liegt in [`share/config/tariffs.json`](../../share/config/tariffs.json) mit dem Root-Feld `catalog_as_of`. Zur Laufzeit nutzt Earnie `earnie_env/config/tariffs.json`; beim Bootstrap kopiert Earnie den Katalog bei Bedarf aus `share`. Szenarien in `backtesting_scenarios.json` verweisen auf `import_tariff_id` und `export_tariff_id` (oder auf `__user_fixed__` mit szenario-lokalen Cent-Feldern, siehe oben).

### Import-Typen

| Typ | Bedeutung |
| --- | --- |
| `fixed_cent` | Fixer Arbeitspreis (`fix_cent_kwh`) + optional Hausprofil-Netznutzung AP |
| `spot_hourly` | EPEX × (1 + `markup_percent`%) + `settlement_fee_cent_kwh` + optional Hausprofil-Netznutzung AP |
| `ex_post_spot` | Wie Spot; Kennzeichnung ex-post-Abrechnung |
| `monthly_market` | Wie Spot; Kennzeichnung Monatsmarkt |
| `monthly_table` | Monatstabelle Bezug (`monthly_rates`) + optional Hausprofil-Netznutzung AP |

### Export-Typen

| Typ | Bedeutung |
| --- | --- |
| `fixed` | Konstante Vergütung (`k_push_cent`) |
| `spot_hourly` / `ex_post_spot` | EPEX − `feed_in_fee_factor` × \|EPEX\| − `settlement_fee_cent_kwh` + `feed_in_fix_cent` (Faktor/Fix optional, Standard 0) |
| `monthly_table` | Monatskonstante Vergütung (`monthly_rates` am Tarif) |

Der interne Runtime-`feed_in_mode` für stündliche EPEX-Einspeisung bleibt `dynamic_epex`. Er ist nicht mit dem entfernten Katalog-`type` gleichen Namens zu verwechseln. Beispiel mit Prozentabschlag: Katalog-id `dynamic_epex` (aWATTar SUNNY SPOT) als `spot_hourly` mit `feed_in_fee_factor: 0.19`.

Die Berechnung steht in [`data/tariff_pricing.py`](../../data/tariff_pricing.py) (`import_cent_kwh`, `export_cent_kwh`). Die MILP-Matrix nutzt `k_act` (Bezug) und `k_push_act` (Einspeisung) je **15-Min-Slot** (`dt_h = 0.25`).

**Abrechnung vs. Plan:** Earnie plant alle Lieferanten auf derselben QH-Matrix, sowohl solche mit Viertelstunden-EPEX (z. B. VKW, Tibber) als auch solche mit Stundenprodukt (z. B. aWATTar HOURLY). Stündliche Marktdaten (CH auf Energy-Charts, aWATTar-Fallback, Historie vor ~2025-10) expandiert Earnie auf vier gleiche QH-Preise. Die Rechnung kann dann weiterhin stündlich mitteln, während der Plan QH-fähig ist.

**Fehlender Folgemonat:** Fehlt in `monthly_rates` der Monat eines Planungsslots (typisch der **nächste Kalendermonat**), nutzt Earnie vorübergehend denselben Monat im Vorjahr, sonst den Vormonat, und schreibt eine Warnung ins Log.

- Ein UI-Hinweis (Sidebar und Eingabeformular im **Szenarienkonfigurator**) erscheint erst in den **letzten zwei Kalendertagen** des Monats. Erst dann kann der ~48h-Planungshorizont in den Folgemonat reichen.
- Die Eingabe (Cent/kWh) ergänzt den Monat in `earnie_env/config/tariffs.json`.
- `main.py` liest die Datei bei jedem Optimierungslauf neu (`reload_config`), die Streamlit-App bei jedem Lauf (`reinit_config`).

### Marktzonen (Backtesting)

| Land (`land`) | Zone | Datenquelle (API) |
| --- | --- | --- |
| AT | AT | Energy-Charts (`bzn=AT`); Fallback aWATTar AT |
| DE | DE-LU | Energy-Charts (`bzn=DE-LU`); Fallback aWATTar DE |
| CH | CH | Energy-Charts |

`simulation/engine.py` und `data/backtesting_prices.py` werten `_import_tariff_spec` / `_export_tariff_spec` aus der Szenario-Auflösung aus. Day-Ahead-Daten: [Energy-Charts](https://energy-charts.info) (Fraunhofer ISE), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

**DACH-Katalog importieren:** `tools/convert_dach_tariffs.py` aus `stromtarife_dach_kombiniert.json` + `einspeisetarife_dach_erweitert.json`.

**Plausibilität prüfen** (vor dem Produktivstart oder dem Umzug auf das NAS):

```powershell
python -m scripts.validate_tariffs --check-catalog
tools/convert_dach_tariffs.py --check
```

### Monatspreis (`monthly_table`) – OeMAG / RefMarkt vs. aWATTar-SUNNY

Monatskonstante Einspeisetarife tragen **eigene** `monthly_rates`. Gemeinsame Kurven in `tariffs.json` dienen der Katalogpflege (Seeds):

| Feld | Zweck |
| --- | --- |
| `oemag_monthly_feed_in_rates` | ≥12 OeMAG-Gesetzliche-Marktpreise (Wartungskurve; länger für SE) |
| `monthly_float_reference_cent_kwh` | Historischer Nenner für OeMAG-proportionale Seeds (z. B. 7,15) |
| `econtrol_referenzmarktwert_pv_monthly` | ≥12 E-Control Referenzmarktwert PV (§ 13 EAG; z. B. VKW Flex-Seed) |

Die Seed-Formel gilt nur für die Katalogpflege, nicht zur Laufzeit. Sie ist pro Tarif im Feld `monthly_seed` festgelegt:

- `OeMAG_Monat × arbeitspreis / monthly_float_reference_cent_kwh − settlement_fee` bzw.
- `RefMarkt_PV − settlement_fee`.

Die Hilfsfunktionen stehen in [data/monthly_float_rates.py](../../data/monthly_float_rates.py). Gepflegt werden die Kurven mit `python -m scripts.update_tariff_curves` (siehe [Pflegehinweis](../referenz/oemag-referenzmarktwert.md#pflegehinweis)).

Rechtliche Abgrenzung OeMAG vs. RefMarkt: [oemag-referenzmarktwert.md](../referenz/oemag-referenzmarktwert.md).

aWATTar-SUNNY-Fixwerte liegen ebenfalls als `monthly_table` vor (z. B. `monthly_sunny`).

## Fehlende Zukunftspreise (Live)

Block `market_prices` in `config.json`:

| Feld | Bedeutung |
| --- | --- |
| `missing_price_strategy` | `forecast` (Standard) oder `mirror` |
| `forecast_model_path` | Pfad zu `price_model_coefficients.json` (Default: `share/data/price_model_coefficients.json`; Fallback `data/cache/…`; für Strategie `forecast`) |
| `live_bias_enabled` | Rollierende EPEX-Bias-Korrektur auf prognostizierte Slots (Standard: `true`) |
| `live_bias_lookback_hours` | Lookback-Fenster in Stunden (Standard: `48`) |
| `live_bias_cap_cent_kwh` | Absolute Kappe ±Cent/kWh (Standard: `12.0`) |

Wenn die aWATTar-API für späte Stunden des Horizonts noch keine Preise liefert, gilt die gewählte Strategie:

- **`forecast` (Standard):** Ein OLS-Korrelationsmodell extrapoliert die fehlenden Stunden. Als Live-Features dienen die Open-Meteo-Wetterprognose und ein stündlicher EU-Leistungs-Stand-in aus dem letzten Archivtag. Charts zeigen diese Stunden als grünen Bereich (siehe [Charts](../ui/charts.md)). Mit dem Standard `live_bias_enabled` korrigiert Earnie die prognostizierten EPEX-Werte rollierend (Day-Ahead − OLS), begrenzt durch `live_bias_cap_cent_kwh`.
- **`mirror`:** gleiche Uhrzeit vom Vortag. Earnie nutzt diese Strategie auch automatisch, wenn Modell oder Features nicht geladen werden können.

Spec: [Preis-Prognose (Dev)](../dev/done/price-forecast-renewables.md).

## Historische Preise

Für das **Backtesting** (Szenario-Explorer) legt `scenario_explorer_conf.price_source` die Quelle fest: `api` oder CSV über `path_price`.

- Die API lädt **Energy-Charts** (natives EPEX-Viertelstundenraster, gleiche Quelle wie Live). Nur bei einem Fehler fällt sie auf aWATTar (stündlich) zurück.
- `price_provider` ist ein Legacy-Feld und steuert die Reihenfolge nicht mehr.
- Die Bidding-Zone kommt aus dem Live-Importtarif (`market_zone` / `land`), nicht aus dem Default `DE-LU`.
- `price_range` und der Simulations-Gesamtzeitraum kommen aus `cons_data` (12 Kalendermonate bis zum letzten vollständigen Monat).

### Monatliche Fixtarife (Backtesting)

Der Export-Tarif-Typ `monthly_table` in `tariffs.json` liefert die Monatswerte (`monthly_rates`). **Sunset-2-Sunset** (Produktiv) nutzt die aufgelöste Export-Tarif-Referenz aus dem Live-Szenario.

### Preisreihe exportieren (`export_price_series`)

`scenario_explorer_conf.export_price_series` (Standard: `false`) schreibt bei `true` die Marktpreisreihe des Simulationszeitraums zusätzlich in eine eigene Datei.

- **Inhalt:** die **tarifunabhängige** EPEX-Preisreihe, wie `scripts/run_backtesting.py` sie geladen hat (netto Cent/kWh, QH-Auflösung, vor Markup, Netznutzung und USt).
- **Ablage:** `backtesting_prices.csv` im Log-Zielordner (`--output-dir`, Standard `.`), referenziert in `backtesting_log.json` als `price_series_file`.
- **Unterschied zu `backtesting.csv`:** Diese Datei gilt pro Szenario und enthält bereits verrechnete `k_act`/`k_push_act`. Die Preisreihe ist dagegen die rohe Marktpreisserie, gemeinsam für **alle** Szenarien eines Laufs.
- **Zweck:** Weiterverwendung ohne erneuten Energy-Charts- oder aWATTar-Abruf, z. B. für externe Einsparpotenzial-Rechnungen.
