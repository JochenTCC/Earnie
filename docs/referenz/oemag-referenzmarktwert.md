# OeMAG Marktpreis and E-Control Referenzmarktwert

For feed-in tariffs, Earnie uses **two different** monthly reference series. This page explains both and how they differ.

- Calculation formulas and tariff types: [Preise und Marktdaten](../konfiguration/preise.md) (German)
- Source list (URLs, decisions): [Recalculating tariffs and prices](tarife-quellen.md)

## Overview

| Term | Law | Publication | Role in Earnie |
| ---- | --- | ----------- | -------------- |
| **OeMAG Marktpreis** | § 13 ÖSG 2012 | [oem-ag.at/marktpreis](https://www.oem-ag.at/marktpreis) | Shared curve `oemag_monthly_feed_in_rates`; seed for OeMAG and OeMAG-proportional monthly feed-in tariffs |
| **Referenzmarktwert PV** | § 13 EAG | [e-control.at/referenzmarktwert](https://www.e-control.at/referenzmarktwert) | Shared curve `econtrol_referenzmarktwert_pv_monthly`; seed e.g. for VKW PV-Einspeisetarif Flex |
| **Referenzmarktpreis** | § 12 EAG | [e-control.at/referenzmarktpreis1](https://www.e-control.at/referenzmarktpreis1) | Annual or monthly mean of the day-ahead prices; **not** the OeMAG payout curve |

## OeMAG Marktpreis (ÖSG)

OeMAG pays for green electricity in the Marktpreis balance group (plants < 500 kW(p)). The Marktpreis is set **monthly, ex post**.

- **Basis:** the volume-weighted day-ahead monthly mean or the corridor to the quarterly market price (§ 41 ÖSG). The cost of balancing energy is deducted from it (2026 PV: 0.408 ct/kWh).
- **Limits:** the lower limit is 60 % of the quarterly market price (minus balancing energy), the upper limit is 100 % of the same quantity.
- **Publication:** OeMAG publishes the value at the start of the following month on its website.

In `tariffs.json` the curve is stored as `oemag_monthly_feed_in_rates`. The export tariff `at_oemag_gesetzlicher_marktpreis` has its **own** `monthly_rates` (type `monthly_table`). The shared curve is used for catalog maintenance.

## E-Control Referenzmarktwert PV (EAG)

The Referenzmarktwert is the **generation-weighted** mean of the hourly day-ahead prices in the Austrian bidding zone. It applies to one technology at a time, here photovoltaics. Among other things, the value is used to calculate the market premium. It is also the reference for market-based feed-in tariffs (e.g. VKW Flex = RefMarkt − deduction).

- **Publication:** E-Control publishes the value monthly (around the 2nd to 9th of the following month) at [referenzmarktwert](https://www.e-control.at/referenzmarktwert). Machine-readable with publication date: [Referenzmarktwert_Entwicklung.xlsx](https://www.e-control.at/documents/1785851/10823410/Referenzmarktwert_Entwicklung.xlsx) (column „Photovoltaikanlagen“).
- **Resolution:** from 2025-10-01, quantities and prices are available in quarter-hour resolution. Because the EAG prescribes hourly values, E-Control calculates with **hourly aggregates**.

In `tariffs.json` the curve is called `econtrol_referenzmarktwert_pv_monthly`. Example PV for August 2026: **9.42 ct/kWh** (E-Control publication of 2026-09-04).

## Referenzmarktpreis (do not confuse)

The Referenzmarktpreis (§ 12 EAG) is the **unweighted** arithmetic mean of the day-ahead prices, annually or monthly. It is a comparison value: neither the OeMAG payout nor the RefMarkt PV.

## Maintenance

Earnie does not query the official pages automatically. New monthly values are taken from there and entered with a script. The script automatically recalculates all dependent catalog tariffs with `monthly_seed` for the affected months:

```powershell
python -m scripts.update_tariff_curves --oemag 2026-08=8.997 --refmarkt 2026-08=9.42 --catalog-as-of 2026-09-28
python -m scripts.update_tariff_curves --check
```

- **`--set export:TARIF_ID:JJJJ-MM=CENT`:** enters a single value for monthly tariffs **without** `monthly_seed` (e.g. aWATTar SUNNY from the tariff sheet).
- **`--check`:** reports deviations between curves and seeded tariffs, and months that contain only placeholders.
- **`--dry-run`:** shows the changes without writing them.

The `monthly_seed` field on the tariff is used only for catalog maintenance. Earnie calculates with `monthly_rates`.

| `curve` | Formula |
| ------- | ------- |
| `oemag` | OeMAG × `arbeitspreis_kwh_cent` / `monthly_float_reference_cent_kwh` − `settlement_fee_cent_kwh` |
| `econtrol_refmarkt_pv` | RefMarkt PV − `settlement_fee_cent_kwh` |

If the formula gives a value ≤ 0 ct, the script writes nothing for that month and prints a warning. `monthly_rates` allows only values > 0.
