# Tarife — Quellenverzeichnis (2.3.a)

Dokumentation der **Quellen und Entscheidungen** hinter der Tarif-Hygiene in Earnie (Backlog **2.3.a**). Sprache der Anwenderdoku: Deutsch; Identifier, URLs und JSON-Keys unverändert.

Verwandt: [OeMAG und Referenzmarktwert](oemag-referenzmarktwert.md) · [Preise und aWATTar](../konfiguration/preise.md)

## 1. Day-Ahead / EPEX-Quellen


| Quelle | Zugang | Rolle in Earnie |
| ------ | ------ | --------------- |
| **Offizielle EPEX** SFTP / MATS API | Kostenpflichtig ([Market Data Services](https://www.epexspot.com/en/marketdataservices), [EEX Webshop](https://webshop.eex-group.com/epex-spot-public-market-data); [SFTP-Spezifikation](https://www.epexspot.com/sites/default/files/download_center_files/EPEXSPOT_SFTP_file_specifications_2025-10a.pdf)) | **Nicht** angebunden (Lizenz/Kosten für Community-OSS) |
| **Energy-Charts** `GET /price?bzn=…` | Kostenlos, ohne Token; Fraunhofer ISE, CC BY 4.0 ([api.energy-charts.info](https://api.energy-charts.info/)) | **Primäre** Day-Ahead-Quelle für AT, DE-LU, CH |
| **aWATTar** `api.awattar.at` / `.de` | Kostenlos, Fair Use | Fallback (AT) bzw. optional (DE); weiterhin Tarif-Typ `awattar` |
| **ENTSO-E Transparency** | Kostenlos + Registrierung + API-Token ([transparency.entsoe.eu](https://transparency.entsoe.eu/)) | Optional später; Token-Hürde für Endnutzer |
| **APG** markt.apg.at | Öffentliche Charts | Nur manuelle Referenz, keine API-Anbindung |

Implementierung: [`data/data_loader.py`](../../data/data_loader.py) (`load_market_prices`). Preisformeln bleiben in [`data/tariff_pricing.py`](../../data/tariff_pricing.py).

## 2. OeMAG Marktpreis

- Offiziell: [https://www.oem-ag.at/marktpreis](https://www.oem-ag.at/marktpreis)
- Katalog: `oemag_monthly_feed_in_rates`, Nenner `monthly_float_reference_cent_kwh` (historisch 7,15 für Seeds)
- Export-Tarif: `at_oemag_gesetzlicher_marktpreis` (`monthly_table` mit eigenen `monthly_rates`)
- Hygiene 2025: Aug/Sep/Nov/Dez gegen OeMAG-Vorjahrestabelle bzw. übereinstimmende Sekundärquellen (z. B. [smartmeter-portal OeMAG](https://www.smartmeter-portal.at/einspeisetarife-pv-oemag-2025/)) geprüft; 2026 Jan–Jun stimmen mit der OeMAG-Tabelle überein

## 3. E-Control Referenzmarktwert / Referenzmarktpreis

- RefMarkt: [https://www.e-control.at/referenzmarktwert](https://www.e-control.at/referenzmarktwert)
- RefMarktpreis: [https://www.e-control.at/referenzmarktpreis1](https://www.e-control.at/referenzmarktpreis1)
- Katalog: `econtrol_referenzmarktwert_pv_monthly`
- Abgrenzung: siehe [oemag-referenzmarktwert.md](oemag-referenzmarktwert.md)

Seed Jul 2025–Jun 2026: E-Control-Veröffentlichungen (u. a. Mai 2026 = 3,76; Jun 2026 = 5,55) sowie konsistente Ableitung aus VKW-Flex-Beispielwerten (Flex ≈ RefMarkt − 0,60). Monatswerte bei Bedarf an der E-Control-Seite aktualisieren.

## 4. VKW-Produkte (Vorarlberg)


| Produkt | URL | Formel (Energie) | Katalog-ID / Typ |
| ------- | --- | ---------------- | ---------------- |
| Strom Dynamisch (Bezug) | [vkw.at/produkte/strom/strom-dynamisch](https://www.vkw.at/produkte/strom/strom-dynamisch) | EPEX Spot AT Day-Ahead + **1,20 ct netto** (+ 20 % USt) | `at_vkw_strom_dynamisch` / `spot_hourly` |
| PV-Einspeisetarif Dynamisch | [vkw.at/pv-einspeisetarif-dynamisch](https://www.vkw.at/pv-einspeisetarif-dynamisch) | EPEX − **0,60 ct** netto | `at_vkw_pv_dynamisch` / export `spot_hourly` |
| PV-Einspeisetarif Flex | [vkw.at/pv-einspeisetarif-flex](https://www.vkw.at/pv-einspeisetarif-flex) | RefMarkt PV − **0,60 ct** | `at_vkw_pv_flex` / `monthly_table` |

- Geltungsbereich: Vorarlberg (ohne Kleinwalsertal); Flex typisch bis 100 kWp.
- **Nicht** modelliert: Strom Flex (monatlicher Phelix-AT-Future an der EEX) — braucht Futures-Feed.

## 5. Katalog / Datenmodell

- Öffentlicher Katalog: [`share/config/tariffs.json`](../../share/config/tariffs.json) (Schema: `tariffs.schema.json`)
- Monatskonstante Einspeisung: ein Typ **`monthly_table`** mit eigenen `monthly_rates` (früher zusätzlich `monthly_float` mit Live-Skalierung)
- Shared-Kurven (`oemag_*`, `econtrol_referenzmarktwert_pv_*`) bleiben **Wartungs-/Seed-Hilfen**; Runtime liest die owned Rates am Tarif
- UI-Label: „Monatspreis“ ([`ui/tariff_filter_helpers.py`](../../ui/tariff_filter_helpers.py))

## 6. Attribution

Day-Ahead-Preise über Energy-Charts: Daten von [Energy-Charts](https://energy-charts.info) (Fraunhofer ISE), Lizenz [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
