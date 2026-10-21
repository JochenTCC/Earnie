# Tarife und Preise nachrechnen

Diese Seite erklärt, wie Earnie Bezugs- und Einspeisepreise sowie die ungefähren Monatskosten bildet. Sie hilft beim Nachvollziehen der Werte im **Szenarienkonfigurator** und im **Szenario-Explorer** (kurz SE).

Verwandt: [Preise und Marktdaten](../konfiguration/preise.md) (Konfiguration und Tariftypen) · [OeMAG und Referenzmarktwert](oemag-referenzmarktwert.md)

## 1. Was Earnie berechnet (und was nicht)

| Bestandteil | Live / MILP | Szenario-Explorer (Gesamt- und Monatskosten) |
| ----------- | ----------- | --------------------------------------------- |
| Energiepreis Bezug (€/kWh × Netzbezug) | ja | ja |
| Einspeisevergütung (€/kWh × Netzeinspeisung) | ja | ja |
| Aufschläge am Tarif (`settlement_fee_cent_kwh`, `markup_percent`, USt) | ja | ja |
| **Lieferant-Grundpreis** (`monthly_fee_eur`, Näherung) | **nein** | **ja** (nach Aggregation) |
| **Netzentgelt-Grundpreis** (`grid_monthly_fee_eur`) | **nein** | **ja** (wenn im Katalog) |
| **Messstellengebühr** (`metering_monthly_fee_eur`) | **nein** | **ja** (wenn im Katalog) |
| **Sonstige Fixkosten** (`other_monthly_fee_eur`) | **nein** | **ja** (wenn im Katalog) |
| **Netznutzung Arbeitspreis** (`netznutzung` am Hausprofil, inkl. Zeitfenster SNAP) | **ja** (vor USt zum Bezugspreis) | **ja** |
| **Netznutzung Leistungspreis** / netzgebietsspezifische Tabellen | **nein** | **nein** |
| PLZ-/netzgebietsspezifische Stacks, separate Stromsteuer/Konzessionsabgabe | nein | nein |

> **Hinweis:** Der volumetrische **Netznutzung Arbeitspreis** wird am Hausprofil (Standort) gepflegt und ist unabhängig vom Lieferantentarif. Er kann zeitabhängig sein (SNAP, vorbereitet WiNAP). Die Werte stammen aus dem Laufzeitkatalog `earnie_env/config/grid_fees.json`; die Vorlage dafür liegt in `share/config/grid_fees.json`. Der Leistungspreis fehlt weiterhin. Das optionale Katalogfeld `grid_monthly_fee_eur` dient nur als monatliche Fixgebühr im Szenario-Explorer.

Earnie liefert **ausreichend genaue Eurobeträge** für Vergleiche und Demos. Eine Abrechnung gegen echte Stromrechnungen ist damit **nicht** möglich. Katalogwerte können unvollständig oder veraltet sein; die Parameter im Szenarienkonfigurator daher prüfen.

### Fake-Jahresrechnung

Nach jedem SE-Lauf schreibt Earnie zusätzlich **Fake-Jahresrechnungen** als Markdown-Datei unter `{Log-Ordner}/invoices/{szenario_label}_jahresrechnung.md`. Der Dateiname ergibt sich aus der Szenario-Bezeichnung. Die Rechnung enthält:

- **Kopf:** die Tarifnamen.
- **Bezug und Einspeisung:** getrennt ausgewiesen, jeweils mit Ø Tarif- und Ø Ist-Preis.
- **Fixkosten:** als eigene Position.
- **Katalogparameter:** am Ende der Datei.

Ist am Hausprofil ein **Netznutzung Arbeitspreis** gesetzt, erscheint ein Abschnitt **Netznutzung**. Die Jahrestabelle trennt dann **Energiebezug (Lieferant)** und **Netznutzung Arbeitspreis**. Die Summe bleibt dabei gleich, es wird nichts doppelt gezählt.

- **Ø Tarif Cent/kWh:** arithmetisches Mittel der stündlichen Tarifpreise über alle Stunden des Monats (`Summe(k_act)/N` bzw. `k_push_act`).
- **Ø Ist Cent/kWh:** `Energiekosten € / Netzenergie kWh × 100`.

## 2. Bezugspreis Schritt für Schritt

Für Spot- und aWATTar-Tarife gilt folgende Reihenfolge (Cent/kWh), wie im Katalog und in der Vorschau:

1. **Börsenpreis** der Stunde (Day-Ahead, EPEX-Zone zum Land des Tarifs).
2. Optional **prozentualer Aufschlag** (`markup_percent`), z. B. 3 → Faktor 1,03.
3. **Fixer Aufschlag** (`settlement_fee_cent_kwh`) in Cent/kWh.
4. Optional **Netznutzung Arbeitspreis** aus dem Hausprofil (`netznutzung`, netto, je Slot, mit Zeitregeln wie SNAP).
5. **Umsatzsteuer**, falls `prices_include_vat` = nein: Ergebnis × (1 + `vat_percent`/100).

Formel:

```
(Börsenpreis × (1 + markup_percent/100) + settlement_fee_cent_kwh)
  × (1 + vat_percent/100)   falls prices_include_vat = false
```

Bei Festpreis-Tarifen (`fixed_cent`) ist der Arbeitspreis `fix_cent_kwh`. Auch hier gilt die USt-Regel.

### Eigener Festpreis (szenario-lokal)

Im Szenarienkonfigurator enthalten die Dropdowns für Bezug und Einspeisung den Eintrag **Eigener Festpreis**. Earnie speichert den Cent/kWh-Wert am Szenario in `backtesting_scenarios.json` (`user_import_cent_kwh` / `user_export_cent_kwh`, Tarif-ID `__user_fixed__`). In `tariffs.json` landet er **nicht**.

| Richtung | Bedeutung |
| -------- | --------- |
| Bezug | Lieferanten-Arbeitspreis inkl. USt (wie Katalog-`fixed_cent`); **Netznutzung Arbeitspreis** aus dem Hausprofil wird weiterhin addiert |
| Einspeisung | eingegebene Vergütung ohne weitere Aufschläge |

Für den eigenen Festpreis gibt es keine Katalog-Vorschau und keine Lieferant- oder Netz-Fixkosten aus dem Tarifkatalog. Die Fixkosten in den SE-Gesamtkosten bleiben daher 0, sofern sie nicht über andere Szenario- oder Hauswerte abgebildet sind. Details: [Preise und Marktdaten](../konfiguration/preise.md).

### Beispiel: aWATTar HOURLY (AT)

Katalog (`awattar_at`): Aufschlag 1,5 Cent/kWh netto, Markup 3 %, Preise **ohne** USt, USt 20 %.

Angenommener Börsenpreis: **5,00** Cent/kWh.

1. 5,00 × 1,03 = 5,15  
2. 5,15 + 1,50 = 6,65  
3. 6,65 × 1,20 = **7,98 Cent/kWh** (brutto, so nutzt Earnie den Preis in der Kostenrechnung)

Zusätzlich kann der Tarif eine **Monatsgebühr** haben (bei aWATTar AT ca. 4,79 € netto pro Monat). Sie fließt nur in die SE-Gesamt- und Monatskosten ein, nicht in den Stundenpreis.

### Beispiel: VKW Strom Dynamisch

Katalog: +1,20 Cent/kWh **netto**, ohne Markup, `prices_include_vat` = nein. Bei einem Börsenpreis von 10,00 Cent/kWh ergibt sich (10,00 + 1,20) × 1,20 = **13,44 Cent/kWh** brutto.

## 3. Einspeisevergütung

Die Vergütung hängt vom Export-Tariftyp ab:

- **Fest** (`fixed`): konstanter Cent/kWh-Wert (`k_push_cent`).
- **Spot** (`spot_hourly`): Börsenpreis minus Abschlag (`settlement_fee_cent_kwh`).
- **Monatspreis** (`monthly_table`): ein Cent/kWh-Wert je Kalendermonat (`monthly_rates`).
- **Eigener Festpreis** (`__user_fixed__`): szenario-lokaler Cent/kWh-Wert (`user_export_cent_kwh`), siehe §2.

### Beispiel: VKW PV-Einspeisetarif Dynamisch

Vergütung ≈ EPEX − **0,60** Cent/kWh (**ohne USt** laut Produktseite). Bei einem Börsenpreis von 10,00 Cent/kWh ergibt sich **9,40 Cent/kWh**. Ein Faktor ×1,20 entfällt, weil der Katalog `prices_include_vat` false und `vat_percent` 0 setzt.

Dasselbe USt-Muster gilt für `at_vkw_pv_flex` (`monthly_table`) und die meisten anderen Einspeise-Monats- und Spot-Tarife (OeMAG-Familie, SUNNY): Die Vergütung erhält **keinen** USt-Aufschlag.

Details zu Typen und JSON: [Preise und Marktdaten](../konfiguration/preise.md).

## 4. Fixkosten in den SE-Gesamtkosten

### Lieferant-Grundpreis

- **Katalogfeld:** `monthly_fee_eur` ist optional; fehlt es, gilt 0.
- **Pflichtfeld `supplier_id`** (Kennung des Stromlieferanten): Ist der Anbieter bei Bezug und Einspeisung derselbe, fällt nur **eine** Gebühr an (der höhere der beiden Werte, `max`). Gebühren unterschiedlicher Anbieter werden **addiert**.

### Hausanschluss-Fixkosten (einmal je Szenario)

| Feld | Bedeutung |
| ---- | --------- |
| `grid_monthly_fee_eur` | Netznutzungs-/Netzentgelt-Grundpreis |
| `metering_monthly_fee_eur` | Messstellenbetrieb / Zählergebühr |
| `other_monthly_fee_eur` | Sonstige Fixkosten (z. B. bekannte Abgabenpauschale) |

Earnie übernimmt jeden Wert aus dem **Bezugstarif**. Fehlt er dort, kommt er aus dem Einspeisetarif; die beiden Werte werden **nicht** summiert. Tabellen nach PLZ oder Netzgebiet sind nicht hinterlegt, fehlende Werte zählen als 0.

### Gemeinsame Regeln

- **EPEX-/Spot-Tarife:** `prices_include_vat` = nein. Volumetrische Aufschläge **und** `monthly_fee_eur` immer **netto** speichern; die USt kommt nur über `vat_percent` auf den Arbeitspreis.
- **Festpreis-Tarife:** Netto oder brutto je nach `prices_include_vat` (oft brutto, also `true`).
- **Abrechnung je Kalendermonat:** Für jeden Kalendermonat im SE-Zeitraum fällt **eine volle** Gebühr an, ohne anteilige Kürzung.
- **Jahres- und Gesamtwert:** Summe aller Fixkosten über alle Monate plus volumetrische Energiekosten (Bezug minus Einspeiseerlös).
- **Live-Planung:** Die Fixkosten fehlen im Live-MILP und in den stündlichen `sim_cost`-Kurven.
- **Netznutzung Arbeitspreis:** Der volumetrische Wert kommt aus dem Hausprofil (`netznutzung`) und dem Netzentgelt-Katalog, nicht aus dem Tarifkatalog.
- **Leistungspreis:** Earnie modelliert ihn derzeit **nicht**.

In der Oberfläche erscheinen die Fixkosten im Szenario-Explorer unter Gesamtkosten und Monatliche Stromkosten. Sind Gebühren vorhanden, zeigt die Seite den Hinweis „Näherung Monatsgebühren“ sowie einen Hinweis zu Netznutzungsentgelten. Zur Fake-Jahresrechnung siehe §1.

## 5. Katalogparameter prüfen

Nach der Tarifwahl zeigt der Szenarienkonfigurator eine **Vorschau ohne Bearbeitungsmöglichkeit**. Sie enthält Land, `supplier_id`, Aufschläge, USt-Flag und ggf. die ungefähren Lieferant-, Netz- und Messstellen-Fixkosten.

Besonders lohnt sich ein Blick auf diese Punkte:

- Stimmen Aufschlag und USt-Flag mit dem Tarifblatt des Anbieters überein?
- Ist der erwartete Lieferant-Grundpreis hinterlegt? Fehlt er, rechnet der Szenario-Explorer mit 0.
- Erscheint die Lieferant-Gebühr bei gleichem Anbieter (z. B. aWATTar Bezug + SUNNY) nur **einmal**?
- Netz- und Messstellenwerte sind oft netzgebietsspezifisch. Ohne Katalogeintrag bleiben sie 0; der volumetrische **Netznutzung Arbeitspreis** kommt aus dem Hausprofil.

Für Vollständigkeit und Aktualität des Katalogs gibt es **keine Garantie**.

Die Formeln zum Nachrechnen stehen auf dieser Seite, das technische Mapping in [preise.md](../konfiguration/preise.md).

## 6. Quellen und Herkunft der Katalogwerte

### Day-Ahead / EPEX

| Quelle | Zugang | Rolle in Earnie |
| ------ | ------ | --------------- |
| **Offizielle EPEX** SFTP / MATS API | Kostenpflichtig ([Market Data Services](https://www.epexspot.com/en/marketdataservices), [EEX Webshop](https://webshop.eex-group.com/epex-spot-public-market-data)) | **Nicht** angebunden |
| **ENTSO-E Transparency** `documentType=A44` | Persönlicher API-Token (`ENTSOE_API_TOKEN` in `config/.env`); [transparency.entsoe.eu](https://transparency.entsoe.eu/) | **Primäre** Live-Day-Ahead-Quelle, wenn ein Token gesetzt ist (AT / DE-LU / CH) |
| **Energy-Charts** `GET /price?bzn=…` | Kostenlos; Fraunhofer ISE, CC BY 4.0 ([api.energy-charts.info](https://api.energy-charts.info/)) | Live-Fallback ohne ENTSO-E oder bei dessen Ausfall; **primäre** SE-/Backtesting-Quelle für AT, DE-LU, CH |
| **aWATTar** `api.awattar.at` / `.de` | Kostenlos, Fair Use | Letzter Live-Fallback (AT) bzw. optional (DE); Katalog-Tarife als `spot_hourly` (API-URL aus `land`) |
| **APG** markt.apg.at | Öffentliche Charts | Nur manuelle Referenz |

### OeMAG Marktpreis

- **Offizielle Quelle:** [oem-ag.at/marktpreis](https://www.oem-ag.at/marktpreis)
- **Katalog:** `oemag_monthly_feed_in_rates`; Export `at_oemag_gesetzlicher_marktpreis`

### E-Control Referenzmarktwert

- **Offizielle Quelle:** [e-control.at/referenzmarktwert](https://www.e-control.at/referenzmarktwert) · Abgrenzung: [oemag-referenzmarktwert.md](oemag-referenzmarktwert.md)
- **Katalog:** `econtrol_referenzmarktwert_pv_monthly`

### VKW (Vorarlberg)

| Produkt | Formel (Energie) | Katalog-ID |
| ------- | ---------------- | ---------- |
| Strom Dynamisch | EPEX + 1,20 ct netto | `at_vkw_strom_dynamisch` |
| Strom Duo | Fixpreis als `monthly_table`: Okt–Mär 9,40 ct netto; Apr–Sep 9,15 ct netto (Mischwert aus Normaltarif 9,40 und Sommerfenster 8,40, 10–16 Uhr) | `at_vkw_strom_duo` |
| Strom Duo ohne Sonderrabatt | Normalpreis als `monthly_table`: Okt–Mär 12,20 ct netto; Apr–Sep 11,95 ct netto (Mischwert aus 12,20 und Sommerfenster 11,20, 10–16 Uhr) | `at_vkw_strom_duo_normalpreis` |
| Strom Einfach | Fixpreis rund um die Uhr: 17,20 ct netto (Normalpreis ohne befristeten Sonderrabatt von 7,30 ct bis 31.03.2027) | `at_vkw_strom_einfach` |
| PV Dynamisch | EPEX − 0,60 ct netto | `at_vkw_pv_dynamisch` |
| PV Flex | RefMarkt PV − 0,60 ct | `at_vkw_pv_flex` |

### Attribution

Day-Ahead Live: optional [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/) (persönlicher Token); sonst [Energy-Charts](https://energy-charts.info) (Fraunhofer ISE), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## 7. Audit / Abweichungen (Stand 2026-10-17, Katalogstand 2026-09-28)

Dieser Abschnitt macht die Katalogpflege transparent: Er gleicht öffentliche Quellen mit `tariffs.json` ab. Zuletzt wurden die Tabellenwerte gegen den Katalog (`catalog_as_of` 2026-09-28) geprüft; die Anbieterseiten wurden dabei nicht erneut abgerufen. Sekundärseiten lassen Grundgebühren mitunter weg oder ordnen die USt falsch zu. Primärquellen (Produktseite, Tarifblatt) haben daher Vorrang.

### Monatsgebühren (vorbelegt, Näherung)

| Katalog-ID | `monthly_fee_eur` | Basis | Quelle |
| ---------- | ----------------- | ----- | ------ |
| `awattar_at` | 4,79 | netto | [awattar.at/tariffs/hourly](https://www.awattar.at/tariffs/hourly) |
| `at_vkw_strom_dynamisch` | 3,00 | netto | [vkw.at Strom Dynamisch](https://www.vkw.at/produkte/strom/strom-dynamisch) (36 €/Jahr netto) |
| `at_vkw_strom_duo` | 3,00 | netto | [vkw.at Strom Duo](https://www.vkw.at/produkte/strom/strom-duo) (36 €/Jahr netto) |
| `at_vkw_strom_duo_normalpreis` | 3,00 | netto | [vkw.at Produktblatt Strom Duo](https://www.vkw.at/vkw/dokumente/strom/produktblaetter/produktblatt-strom-duo.pdf) (36 €/Jahr netto, Stand 04/2026) |
| `at_vkw_strom_einfach` | 1,75 | netto | [vkw.at Produktblatt Strom Einfach](https://www.vkw.at/vkw/dokumente/strom/produktblaetter/produktblatt-strom-einfach.pdf) (21 €/Jahr netto, Stand 01/2026) |
| `at_smartenergy_smartcontrol` | 2,49 | netto | [smartenergy.at/smartcontrol](https://smartenergy.at/smartcontrol) (2,99 brutto) |
| `at_spotty_smart_active` | 2,00 | netto | Spotty-Rechnung / Portale (2,40 brutto) |
| `at_verbund_v_strom_spot` | 3,99 | netto | Selectra / Verbund-Grundpreis (ca. 4,79 brutto) |
| `de_tibber_tibber_dynamic` | 5,03 | netto | [Tibber Support](https://support.tibber.com/de/articles/12310314-grund-und-arbeitspreis-bei-tibber) (5,99 inkl. MwSt.) |
| `de_awattar_de_hourly_de` | 4,58 | netto (Näherung) | [awattar.de HOURLY](https://www.awattar.de/tariffs/hourly) (ggf. PLZ-abhängig) |

> **Hinweis:** Manche Vergleichsportale geben für aWATTar AT „kein Grundpreis“ an. Die offizielle aWATTar-Seite nennt dagegen einen Grundpreis.

### Volumetrische Werte (Energieaufschläge)

| ID | Katalog | Prüfung | Status |
| -- | ------- | ------- | ------ |
| `awattar_at` | 1,5 ct + 3 % Markup, netto | Tarifblatt enthält 3 %; Marketingseite oft ohne 3 % | Match (Katalog vollständiger) |
| `at_vkw_strom_dynamisch` | 1,2 ct netto | Offiziell +1,20 ct netto | Match |
| `at_vkw_pv_dynamisch` / `at_vkw_pv_flex` | Abschlag 0,6; `vat_percent` 0 (ohne USt) | Offiziell ohne USt | Match |
| `at_smartenergy_smartcontrol` | 1,20 ct netto (`prices_include_vat` false) | Offiziell 1,20 netto / 1,44 inkl. | Match |
| `at_spotty_smart_active` | 1,49 ct netto | ≈ 1,79 inkl. / 1,2 | Match |
| `de_tibber_tibber_dynamic` | 1,81 ct netto | Support 2,15 ct brutto / 1,19 | Match |
| `at_verbund_v_strom_spot` | 1,3 + 4 % | Selectra eher Fix-ct; Formel unsicher | Offen, nur Monatsgebühr vorbelegt |
| `de_awattar_de_hourly_de` | 2,25 + 3 % | Seite betont EPEX + 3 %; 2,25 unklar | Offen, Monatsgebühr ca. 4,58 |

Technische Typen und APIs: [Preise und Marktdaten](../konfiguration/preise.md).
