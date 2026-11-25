# Recalculating tariffs and prices

This page explains how Earnie builds import and feed-in prices and the approximate monthly costs. It helps you trace the values in the **Szenarienkonfigurator** and in the **Szenario-Explorer** (SE for short).

Related: [Preise und Marktdaten](../konfiguration/preise.md) (German; configuration and tariff types) · [OeMAG and Referenzmarktwert](oemag-referenzmarktwert.md)

## 1. What Earnie calculates (and what it does not)

| Component | Live planning | Szenario-Explorer (total and monthly costs) |
| --------- | ------------- | ------------------------------------------- |
| Import energy price (€/kWh × grid import) | yes | yes |
| Feed-in tariff (€/kWh × grid export) | yes | yes |
| Tariff surcharges (`settlement_fee_cent_kwh`, `markup_percent`, VAT) | yes | yes |
| **Supplier base fee** (`monthly_fee_eur`, approximation) | **no** | **yes** (after aggregation) |
| **Metering fee** (`metering_monthly_fee_eur`) | **no** | **yes** (if in the catalog) |
| **Other fixed costs** (`other_monthly_fee_eur`) | **no** | **yes** (if in the catalog) |
| **Netznutzung Arbeitspreis** (`netznutzung` in the house profile, incl. SNAP time windows) | **yes** (added to the import price before VAT) | **yes** |
| **Grid loss and levies per kWh** (grid area: Netzverlustentgelt, Erneuerbaren-Förderbeitrag, Elektrizitätsabgabe Haushalt) | **yes** (added to the import price before VAT) | **yes** |
| **Fixed grid amounts per year** (grid area: Grundpauschale, Förderbeitrag, Förderpauschale) | **no** | **yes** (after aggregation) |
| **Netznutzung Leistungspreis** (grid area: `capacity_charges`) | **no** | **yes** (after aggregation, per calendar month) |
| Postcode- or grid-area-specific stacks, Konzessionsabgabe | no | no |

> **Note:** The volumetric **Netznutzung Arbeitspreis** is set in the house profile (site) and does not depend on the supplier tariff. It can be time-dependent (e.g. SNAP). The values come from the runtime catalog `earnie_env/config/grid_fees.json`; its template is `share/config/grid_fees.json`. A custom Arbeitspreis is a user grid area in `user_grid_fees.json` (see [Preise](../konfiguration/preise.md#eigener-arbeitspreis-benutzer-netzbereich) (German)). All four tariff files carry the tariff format `tariff_format: 1`; every tariff needs a `vat_percent`.

Earnie delivers **sufficiently accurate euro amounts** for comparisons and demos. It does **not** allow you to reconcile against real electricity bills. Catalog values can be incomplete or outdated, so check the parameters in the **Szenarienkonfigurator**.

### Fake annual invoice

After every SE run, Earnie also writes **fake annual invoices** as a Markdown file at `{log folder}/invoices/{szenario_label}_jahresrechnung.md`. The file name comes from the scenario label. The invoice contains:

- **Header:** the tariff names.
- **Import and feed-in:** listed separately, each with the Ø tariff price and the Ø actual price.
- **Fixed costs:** as a separate line item.
- **Catalog parameters:** at the end of the file.

If a **Netznutzung Arbeitspreis** is set in the house profile, a **Netznutzung** section appears. The annual table then separates **Energiebezug (Lieferant)**, **Netznutzung Arbeitspreis** and **Netzverlust und Abgaben je kWh**. The total stays the same; nothing is counted twice. The **fixed grid amounts** appear as a separate fixed-cost line in the annual table and, per amount, in the Netznutzung section.

- **Ø tariff cent/kWh:** arithmetic mean of the hourly tariff prices over all hours of the month.
- **Ø actual cent/kWh:** `energy cost € / grid energy kWh × 100`.

## 2. Import price step by step

For spot and aWATTar tariffs the order is as follows (cent/kWh), as in the catalog and the preview:

1. **Exchange price** of the slot (day-ahead, EPEX zone for the tariff's country); with `settlement_mtu: 60min` the mean of the four quarter hours of the hour.
2. Optional **percentage markup** (`markup_percent`), e.g. 3 → factor 1.03.
3. **Fixed supplier surcharge** (`settlement_fee_cent_kwh`) in cent/kWh. This field applies only to spot types. Grid costs do not belong here; they go into `netznutzung` (step 4).
4. Optional **Netznutzung Arbeitspreis** from the house profile (`netznutzung`, net, per slot, with time rules such as SNAP) and **grid loss and levies per kWh** of the grid area (net, without time rules).
5. **VAT**, if `prices_include_vat` = no: result × (1 + `vat_percent`/100). If `prices_include_vat` = yes, the supplier price is already gross; the grid charges from step 4 then get VAT (`vat_percent`) in step 4 itself, because they are net prices.

Formula:

```
(exchange price × (1 + markup_percent/100) + settlement_fee_cent_kwh)
  × (1 + vat_percent/100)   if prices_include_vat = false
```

For fixed-price tariffs (`fixed_cent`) the energy price is `fix_cent_kwh`; `settlement_fee_cent_kwh` has no effect there (Earnie warns when loading). The grid charges from the house profile are added here as well. The VAT rule applies here too.

### User tariffs from Edibert

Earnie calculates tariffs from `user_tariffs.json` (next to `tariffs.json`, IDs `user_…`) with the same steps as catalog tariffs, through the tariff library Edibert. Time rules (`rules`) and price limits (`price_floor_cent_kwh`, `price_cap_cent_kwh`) apply per slot (see [Preise und Marktdaten](../konfiguration/preise.md#benutzertarife-usertariffsjson) (German)).

### Custom fixed price (scenario-local)

In the **Szenarienkonfigurator**, the dropdowns for import and feed-in contain the entry **Eigener Festpreis**. Earnie stores the cent/kWh value with the scenario in `backtesting_scenarios.json` (`user_import_cent_kwh` / `user_export_cent_kwh`, tariff ID `__user_fixed__`). It does **not** go into `tariffs.json`.

| Direction | Meaning |
| --------- | ------- |
| Import | Supplier energy price incl. VAT; the **Netznutzung Arbeitspreis** from the house profile is added |
| Feed-in | The entered tariff without further surcharges |

The custom fixed price has no catalog preview and no fixed costs from the tariff catalog. The SE total costs then contain only the fixed grid amounts of the grid area (see §4). Details: [Preise und Marktdaten](../konfiguration/preise.md) (German).

### Example: aWATTar HOURLY (AT)

Catalog (`awattar_at`): surcharge 1.5 cent/kWh net, markup 3 %, prices **without** VAT, VAT 20 %.

Assumed exchange price: **5.00** cent/kWh.

1. 5.00 × 1.03 = 5.15
2. 5.15 + 1.50 = 6.65
3. 6.65 × 1.20 = **7.98 cent/kWh** (gross; Earnie uses this price in the cost calculation)

The tariff can also have a **monthly fee** (aWATTar AT: about 4.79 € net per month). It enters only the SE total and monthly costs, not the hourly price.

### Example: VKW Strom Dynamisch

Catalog: +1.20 cent/kWh **net**, no markup, `prices_include_vat` = no. At an exchange price of 10.00 cent/kWh this gives (10.00 + 1.20) × 1.20 = **13.44 cent/kWh** gross.

## 3. Feed-in tariff

The tariff depends on the export tariff type:

- **Fixed** (`fixed`): constant cent/kWh value (`k_push_cent`).
- **Spot** (`spot_hourly`): exchange price minus deduction (`settlement_fee_cent_kwh`).
- **Monthly price** (`monthly_table`): one cent/kWh value per calendar month (`monthly_rates`).
- **Eigener Festpreis** (`__user_fixed__`): scenario-local cent/kWh value (`user_export_cent_kwh`), see §2.

### Example: VKW PV-Einspeisetarif Dynamisch

Tariff ≈ EPEX − **0.60** cent/kWh (**without VAT** according to the product page). At an exchange price of 10.00 cent/kWh this gives **9.40 cent/kWh**. There is no factor ×1.20, because the catalog sets `prices_include_vat` false and `vat_percent` 0.

The same VAT pattern applies to `at_vkw_pv_flex` (`monthly_table`) and all other feed-in tariffs in the catalog (OeMAG family, SUNNY): the tariff gets **no** VAT surcharge.

Details on types and JSON: [Preise und Marktdaten](../konfiguration/preise.md) (German).

## 4. Fixed costs in the SE total costs

### Supplier base fee

- **Catalog field:** `monthly_fee_eur` is optional; if it is missing, 0 applies.
- **Required field `supplier_id`** (identifier of the electricity supplier): if import and feed-in have the same supplier, only **one** fee applies (the higher of the two values, `max`). Fees of different suppliers are **added**.
- **Required field `land`** (`AT`, `DE` or `CH`): every tariff in `tariffs.json` needs a country, including fixed-price and monthly-table tariffs. Earnie rejects tariffs without `land` with an error message when loading; otherwise the country filter in the **Szenarienkonfigurator** would hide them silently. (The „Eigener Festpreis“ is not a catalog tariff and needs no country.)

### Connection fixed costs (once per scenario)

| Field | Meaning |
| ----- | ------- |
| `metering_monthly_fee_eur` | Metering operation / meter fee |
| `other_monthly_fee_eur` | Other fixed costs (e.g. a known flat levy) |

Earnie takes each value from the **import tariff**. If it is missing there, it comes from the feed-in tariff; the two values are **not** summed. There are no tables by postcode; missing values count as 0.

### Fixed grid amounts (from the grid area)

Grundpauschale, Förderbeitrag on the Grundpauschale and Erneuerbaren-Förderpauschale are stored per year and net in the grid area of the house profile, not in the tariff. Earnie counts one twelfth of them per calendar month and adds the VAT of the import tariff:

`annual amount / 12 × (1 + vat_percent/100)`

**Example:** The Austrian catalog areas carry 54.00 + 3.796 + 19.02 = 76.816 € net per year. With 20 % VAT this gives 7.68 € per month, i.e. 92.18 € per year. Without a grid area on the scenario, this line item is omitted.

### Common rules

- **EPEX / spot tariffs:** `prices_include_vat` = no. Always store volumetric surcharges **and** monthly fees **net**; VAT is added to both via `vat_percent`. Example: `awattar_at` carries 4.79 € net and counts 5.75 € per month with 20 % VAT. The preview in the **Szenarienkonfigurator** shows the stored value.
- **Fixed-price tariffs:** net or gross, depending on `prices_include_vat`.
- **Feed-in tariffs:** they carry `vat_percent` 0, so their monthly fee stays net. If the same supplier is also the import supplier, the higher gross value counts, usually that of the import tariff.
- **Billing per calendar month:** for every calendar month in the SE period, **one full** fee applies, without pro-rata reduction.
- **Annual and total value:** sum of all fixed costs over all months plus volumetric energy costs (import minus feed-in revenue).
- **Live planning:** fixed costs are not included in live planning and in the hourly cost curves.
- **Netznutzung Arbeitspreis:** the volumetric value comes from the house profile (`netznutzung`) and the grid fee catalog, not from the tariff catalog.
- **Leistungspreis:** only if the grid area carries `capacity_charges`. Per calendar month, the highest billed quarter hour of grid import counts, at least the minimum power (`min_kw`). Above the band limit, the higher rate applies only to the share above it. The amount comes net from Edibert and gets the VAT of the import tariff. A partial month counts in full. Before the start of the first entry, no Leistungspreis applies. A gap after that aborts the run with an error message. Entries with a status outside `include_status` do not count and appear as a note. Load profiles from hourly values smooth out short peaks; the real peak can be higher. The planning does not know the price itself; it only keeps to an entered import limit. Start per grid area, prices and their status: [Leistungspreis und Bezugsgrenze](../konfiguration/preise.md#leistungspreis-und-bezugsgrenze) (German).

In the interface, the fixed costs appear in the **Szenario-Explorer** under total costs and monthly electricity costs. If fees are present, the page shows the hint „Näherung Fixkosten“ and a note on grid usage fees. For the fake annual invoice, see §1.

## 5. Checking catalog parameters

After you choose a tariff, the **Szenarienkonfigurator** shows a **read-only preview**. It contains the country, `supplier_id`, surcharges, the VAT flag and, if present, the approximate supplier and metering fixed costs.

These points are especially worth a look:

- Do surcharge and VAT flag match the supplier's tariff sheet?
- Is the expected supplier base fee stored? If it is missing, the **Szenario-Explorer** calculates with 0.
- Does the supplier fee appear only **once** for the same supplier (e.g. aWATTar import + SUNNY)?
- Grid and metering values are often specific to the grid area. Without a catalog entry they stay 0; the volumetric **Netznutzung Arbeitspreis** comes from the house profile.

There is **no guarantee** that the catalog is complete and up to date.

The formulas for recalculating are on this page; the technical mapping is in [preise.md](../konfiguration/preise.md) (German).

## 6. Sources and origin of catalog values

### Day-Ahead / EPEX

| Source | Access | Role in Earnie |
| ------ | ------ | -------------- |
| **Official EPEX** SFTP / MATS API | Paid ([Market Data Services](https://www.epexspot.com/en/marketdataservices), [EEX Webshop](https://webshop.eex-group.com/epex-spot-public-market-data)) | **Not** connected |
| **ENTSO-E Transparency** `documentType=A44` | Personal API token (`ENTSOE_API_TOKEN` in `config/.env`); [transparency.entsoe.eu](https://transparency.entsoe.eu/) | **Primary** live day-ahead source if a token is set (AT / DE-LU / CH) |
| **Energy-Charts** `GET /price?bzn=…` | Free; Fraunhofer ISE, CC BY 4.0 ([api.energy-charts.info](https://api.energy-charts.info/)) | Live fallback without ENTSO-E or when it fails; the **only** SE / backtesting source for AT, DE-LU, CH (no fallback) |
| **aWATTar** `api.awattar.at` / `.de` | Free, fair use | Last live fallback (AT, DE-LU) |
| **APG** markt.apg.at | Public charts | Manual reference only |

### OeMAG Marktpreis

- **Official source:** [oem-ag.at/marktpreis](https://www.oem-ag.at/marktpreis)
- **Catalog:** `oemag_monthly_feed_in_rates`; export `at_oemag_gesetzlicher_marktpreis`

### E-Control Referenzmarktwert

- **Official source:** [e-control.at/referenzmarktwert](https://www.e-control.at/referenzmarktwert) · Distinction: [oemag-referenzmarktwert.md](oemag-referenzmarktwert.md)
- **Catalog:** `econtrol_referenzmarktwert_pv_monthly`

### VKW (Vorarlberg)

| Product | Formula (energy) | Catalog ID |
| ------- | ---------------- | ---------- |
| Strom Dynamisch | EPEX + 1.20 ct net | `at_vkw_strom_dynamisch` |
| Strom Duo | Fixed price as `monthly_table`: Oct–Mar 9.40 ct net; Apr–Sep 9.15 ct net (blend of the normal rate 9.40 and the summer window 8.40, 10:00–16:00) | `at_vkw_strom_duo` |
| Strom Duo ohne Sonderrabatt | Normal price as `monthly_table`: Oct–Mar 12.20 ct net; Apr–Sep 11.95 ct net (blend of 12.20 and the summer window 11.20, 10:00–16:00) | `at_vkw_strom_duo_normalpreis` |
| Strom Einfach | Fixed price around the clock: 17.20 ct net (normal price without the temporary special discount of 7.30 ct valid until 2027-03-31) | `at_vkw_strom_einfach` |
| PV Dynamisch | EPEX − 0.60 ct net | `at_vkw_pv_dynamisch` |
| PV Flex | RefMarkt PV − 0.60 ct | `at_vkw_pv_flex` |

### Attribution

Day-ahead live: optionally [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/) (personal token); otherwise [Energy-Charts](https://energy-charts.info) (Fraunhofer ISE), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## 7. Audit / deviations (as of 2026-10-17, catalog as of 2026-09-28)

This section makes catalog maintenance transparent: it compares public sources with `tariffs.json`. The table values were last checked against the catalog (`catalog_as_of` 2026-09-28); the supplier pages were not fetched again for that check. Secondary sites sometimes omit base fees or assign VAT incorrectly. Primary sources (product page, tariff sheet) therefore take precedence.

### Monthly fees (prefilled, approximation)

| Catalog ID | `monthly_fee_eur` | Basis | Source |
| ---------- | ----------------- | ----- | ------ |
| `awattar_at` | 4.79 | net | [awattar.at/tariffs/hourly](https://www.awattar.at/tariffs/hourly) |
| `at_vkw_strom_dynamisch` | 3.00 | net | [vkw.at Strom Dynamisch](https://www.vkw.at/produkte/strom/strom-dynamisch) (36 €/year net) |
| `at_vkw_strom_duo` | 3.00 | net | [vkw.at Strom Duo](https://www.vkw.at/produkte/strom/strom-duo) (36 €/year net) |
| `at_vkw_strom_duo_normalpreis` | 3.00 | net | [vkw.at Produktblatt Strom Duo](https://www.vkw.at/vkw/dokumente/strom/produktblaetter/produktblatt-strom-duo.pdf) (36 €/year net, as of 04/2026) |
| `at_vkw_strom_einfach` | 1.75 | net | [vkw.at Produktblatt Strom Einfach](https://www.vkw.at/vkw/dokumente/strom/produktblaetter/produktblatt-strom-einfach.pdf) (21 €/year net, as of 01/2026) |
| `at_smartenergy_smartcontrol` | 2.49 | net | [smartenergy.at/smartcontrol](https://smartenergy.at/smartcontrol) (2.99 gross) |
| `at_spotty_smart_active` | 2.00 | net | Spotty invoice / portals (2.40 gross) |
| `at_verbund_v_strom_spot` | 3.99 | net | Selectra / Verbund base fee (about 4.79 gross) |
| `de_tibber_tibber_dynamic` | 5.03 | net | [Tibber Support](https://support.tibber.com/de/articles/12310314-grund-und-arbeitspreis-bei-tibber) (5.99 incl. VAT) |
| `de_awattar_de_hourly_de` | 4.58 | net (approximation) | [awattar.de HOURLY](https://www.awattar.de/tariffs/hourly) (may depend on the postcode) |

> **Note:** Some comparison portals state „kein Grundpreis“ (no base fee) for aWATTar AT. The official aWATTar page, however, lists a base fee.

### Volumetric values (energy surcharges)

| ID | Catalog | Check | Status |
| -- | ------- | ----- | ------ |
| `awattar_at` | 1.5 ct + 3 % markup, net | Tariff sheet includes 3 %; marketing page often without 3 % | Match (catalog more complete) |
| `at_vkw_strom_dynamisch` | 1.2 ct net | Official +1.20 ct net | Match |
| `at_vkw_pv_dynamisch` / `at_vkw_pv_flex` | Deduction 0.6; `vat_percent` 0 (without VAT) | Official without VAT | Match |
| `at_smartenergy_smartcontrol` | 1.20 ct net (`prices_include_vat` false) | Official 1.20 net / 1.44 incl. VAT | Match |
| `at_spotty_smart_active` | 1.49 ct net | ≈ 1.79 incl. VAT / 1.2 | Match |
| `de_tibber_tibber_dynamic` | 1.81 ct net | Support 2.15 ct gross / 1.19 | Match |
| `at_verbund_v_strom_spot` | 1.3 + 4 % | Selectra suggests a fixed ct value; formula uncertain | Open, only the monthly fee is prefilled |
| `de_awattar_de_hourly_de` | 2.25 + 3 % | Page emphasizes EPEX + 3 %; 2.25 unclear | Open, monthly fee about 4.58 |

Technical types and APIs: [Preise und Marktdaten](../konfiguration/preise.md) (German).
