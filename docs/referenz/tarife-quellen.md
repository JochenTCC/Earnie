# Tarife und Preise nachrechnen

Anleitung für Anwender:innen, die im **Szenarienkonfigurator** oder **Szenario-Explorer** verstehen wollen, wie Earnie Bezugs- und Einspeisepreise sowie die ungefähren Monatskosten bildet. Sprache der Anwenderdoku: Deutsch; Identifier, URLs und JSON-Keys unverändert.

Verwandt: [Preise & aWATTar](../konfiguration/preise.md) (Konfiguration/Typen) · [OeMAG und Referenzmarktwert](oemag-referenzmarktwert.md)

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
| **Netznutzungsentgelte** (Arbeits-/Leistungspreis, netzgebietsspezifisch) | **nein** | **nein** |
| PLZ-/netzgebietsspezifische Stacks, separate Stromsteuer/Konzessionsabgabe | nein | nein |

**Hinweis:** **Netznutzungsentgelte** fließen derzeit **nicht** in die Kostenrechnung ein (weder Live/MILP noch Szenario-Explorer). Optionale Katalogfelder wie `grid_monthly_fee_eur` oder `netzentgelt_cent_kwh` sind unvollständige Näherungs-Stubs — keine Abbildung echter, netzgebietsspezifischer Netznutzungsentgelte.

Earnie liefert **gute-genug-€** für Vergleiche und Demos — **keine** Abrechnung gegen echte Stromrechnungen. Katalogwerte können unvollständig oder veraltet sein; bitte die Parameter im Szenarienkonfigurator prüfen.

Nach jedem SE-Lauf schreibt Earnie zusätzlich **Fake-Jahresrechnungen** als Markdown unter `{Log-Ordner}/invoices/{szenario_label}_jahresrechnung.md` (Dateiname aus der Szenario-Bezeichnung; Bezug/Einspeisung getrennt mit Ø Tarif- und Ø Ist-Preis, Fixkosten ausgewiesen, Tarifnamen im Kopf, Katalogparameter am Ende).

- **Ø Tarif Cent/kWh:** arithmetisches Mittel der stündlichen Tarifpreise über alle Stunden des Monats (`Summe(k_act)/N` bzw. `k_push_act`).
- **Ø Ist Cent/kWh:** `Energiekosten € / Netzenergie kWh × 100`.

## 2. Bezugspreis Schritt für Schritt

Für Spot-/aWATTar-Tarife gilt (Cent/kWh), wie im Katalog und in der Vorschau:

1. **Börsenpreis** der Stunde (Day-Ahead / EPEX-Zone zum Land des Tarifs).
2. Optional **prozentualer Aufschlag** (`markup_percent`), z. B. 3 → Faktor 1,03.
3. **Fixer Aufschlag** (`settlement_fee_cent_kwh`) in Cent/kWh.
4. **Umsatzsteuer**, falls `prices_include_vat` = nein: Ergebnis × (1 + `vat_percent`/100).

Formel:

```
(Börsenpreis × (1 + markup_percent/100) + settlement_fee_cent_kwh)
  × (1 + vat_percent/100)   falls prices_include_vat = false
```

Bei Festpreis-Tarifen (`fixed_cent`) ist der Arbeitspreis `fix_cent_kwh` (ebenfalls mit USt-Regel).

### Beispiel: aWATTar HOURLY (AT)

Katalog (`awattar_at`): Aufschlag 1,5 Cent/kWh netto, Markup 3 %, Preise **ohne** USt, USt 20 %.

Angenommen Börsenpreis = **5,00** Cent/kWh:

1. 5,00 × 1,03 = 5,15  
2. 5,15 + 1,50 = 6,65  
3. 6,65 × 1,20 = **7,98 Cent/kWh** (brutto, wie Earnie ihn für die Kostenrechnung nutzt)

Zusätzlich kann der Tarif eine **Monatsgebühr** haben (bei aWATTar AT ca. 4,79 € netto / Monat) — die fließt nur in die SE-Gesamt-/Monatskosten ein, nicht in den Stundenpreis.

### Beispiel: VKW Strom Dynamisch

Katalog: +1,20 Cent/kWh **netto**, ohne Markup, `prices_include_vat` = nein. Bei Börse 10,00 Cent/kWh → (10,00 + 1,20) × 1,20 = **13,44 Cent/kWh** brutto.

## 3. Einspeisevergütung

Je nach Export-Tariftyp:

- **Fest** (`fixed`): konstanter Cent/kWh (`k_push_cent`).
- **Spot** (`spot_hourly`): Börsenpreis minus Abschlag (`settlement_fee_cent_kwh`).
- **Monatspreis** (`monthly_table`): ein Cent/kWh-Wert für den Kalendermonat (`monthly_rates`).

### Beispiel: VKW PV-Einspeisetarif Dynamisch

Vergütung ≈ EPEX − **0,60** Cent/kWh (**ohne USt** laut Produktseite). Bei Börse 10,00 Cent/kWh → **9,40 Cent/kWh** (kein ×1,20 — Katalog: `prices_include_vat` false, `vat_percent` 0).

Gleiches USt-Muster für `at_vkw_pv_flex` (`monthly_table`) und die meisten sonstigen Einspeise-Monats-/Spot-Tarife (OeMAG-Familie, SUNNY): Vergütung **ohne** USt-Aufschlag.

Details zu Typen und JSON: [Preise & aWATTar](../konfiguration/preise.md).

## 4. Fixkosten in den SE-Gesamtkosten

### Lieferant-Grundpreis

- Feld im Katalog: `monthly_fee_eur` (optional; fehlt = 0).
- Pflichtfeld **`supplier_id`** (Stromlieferant-Slug): gleiche Anbieter bei Bezug und Einspeise teilen sich **eine** Gebühr (`max` der beiden Werte), unterschiedliche Anbieter werden **addiert**.

### Hausanschluss-Fixkosten (einmal je Szenario)

| Feld | Bedeutung |
| ---- | --------- |
| `grid_monthly_fee_eur` | Netznutzungs-/Netzentgelt-Grundpreis |
| `metering_monthly_fee_eur` | Messstellenbetrieb / Zählergebühr |
| `other_monthly_fee_eur` | Sonstige Fixkosten (z. B. bekannte Abgabenpauschale) |

Regel: Wert aus dem **Bezugstarif**; fehlt er dort, aus dem Einspeisetarif — **nicht** Summe aus beiden. PLZ-/Netzgebiet-Tabellen sind nicht hinterlegt; fehlende Werte = 0.

### Gemeinsame Regeln

- **EPEX-/Spot-Tarife:** `prices_include_vat` = nein; volumetrische Aufschläge **und** `monthly_fee_eur` immer **netto** speichern (USt nur über `vat_percent` auf den Arbeitspreis).
- **Festpreis-Tarife:** Netto oder brutto wie `prices_include_vat` (oft brutto/`true`).
- Pro **Kalendermonat** im SE-Zeitraum: **eine volle** Gebühr — keine anteilige Kürzung.
- Jahres-/Gesamtwert: Summe aller Fixkosten über alle Monate + volumetrische Energiekosten (Bezug minus Einspeiseerlös).
- **Nicht** in Live-MILP, **nicht** in den stündlichen `sim_cost`-Kurven.
- Optional volumetrisch: `netzentgelt_cent_kwh` fließt in den Bezugs-Arbeitspreis (wenn gesetzt) — **kein** Ersatz für echte Netznutzungsentgelte.
- **Netznutzungsentgelte** (Arbeits-/Leistungspreis, netzgebietsspezifisch) werden derzeit **nicht** modelliert.

In der UI: Szenario-Explorer → Gesamtkosten und Monatliche Stromkosten (Hinweis „Näherung Monatsgebühren“, wenn Gebühren vorhanden; Hinweis zu Netznutzungsentgelten). Fake-Jahresrechnung: siehe §1.

## 5. Katalogparameter prüfen

Im Szenarienkonfigurator erscheint nach Tarifwahl eine **read-only-Vorschau** (Land, `supplier_id`, Aufschläge, USt-Flag, ggf. Lieferant-/Netz-/Messstellen-Fixkosten ca.).

Prüfen Sie insbesondere:

- Stimmen Aufschlag und USt-Flag mit dem Tarifblatt des Anbieters überein?
- Ist ein Lieferant-Grundpreis hinterlegt, den Sie erwarten — oder fehlt er (dann 0 in der SE-Rechnung)?
- Bei gleichem Anbieter (z. B. aWATTar Bezug + SUNNY): erscheint die Lieferant-Gebühr nur **einmal**?
- Netz-/Messstellenwerte sind oft netzgebietsspezifisch — ohne Katalogeintrag bleiben sie 0; **Netznutzungsentgelte** insgesamt fließen derzeit **nicht** in die Rechnung ein.
- Es gibt **keine Garantie** für Vollständigkeit oder Aktualität des Katalogs.

Nachrechnen der Formeln: diese Seite. Technisches Mapping: [preise.md](../konfiguration/preise.md).

## 6. Quellen und Herkunft der Katalogwerte

### Day-Ahead / EPEX

| Quelle | Zugang | Rolle in Earnie |
| ------ | ------ | --------------- |
| **Offizielle EPEX** SFTP / MATS API | Kostenpflichtig ([Market Data Services](https://www.epexspot.com/en/marketdataservices), [EEX Webshop](https://webshop.eex-group.com/epex-spot-public-market-data)) | **Nicht** angebunden |
| **Energy-Charts** `GET /price?bzn=…` | Kostenlos; Fraunhofer ISE, CC BY 4.0 ([api.energy-charts.info](https://api.energy-charts.info/)) | **Primäre** Day-Ahead-Quelle für AT, DE-LU, CH |
| **aWATTar** `api.awattar.at` / `.de` | Kostenlos, Fair Use | Fallback (AT) bzw. optional (DE); Katalog-Tarife als `spot_hourly` (API-URL aus `land`) |
| **ENTSO-E Transparency** | Token erforderlich | Optional später |
| **APG** markt.apg.at | Öffentliche Charts | Nur manuelle Referenz |

### OeMAG Marktpreis

- Offiziell: [oem-ag.at/marktpreis](https://www.oem-ag.at/marktpreis)
- Katalog: `oemag_monthly_feed_in_rates`; Export `at_oemag_gesetzlicher_marktpreis`

### E-Control Referenzmarktwert

- [e-control.at/referenzmarktwert](https://www.e-control.at/referenzmarktwert) · Abgrenzung: [oemag-referenzmarktwert.md](oemag-referenzmarktwert.md)
- Katalog: `econtrol_referenzmarktwert_pv_monthly`

### VKW (Vorarlberg)

| Produkt | Formel (Energie) | Katalog-ID |
| ------- | ---------------- | ---------- |
| Strom Dynamisch | EPEX + 1,20 ct netto | `at_vkw_strom_dynamisch` |
| Strom Duo | Fixpreis als `monthly_table`: Okt–Mar 9,40 ct netto; Apr–Sep 9,15 ct netto (Blend aus Normaltarif 9,40 + Sommerfenster 8,40, 10–16 Uhr) | `at_vkw_strom_duo` |
| PV Dynamisch | EPEX − 0,60 ct netto | `at_vkw_pv_dynamisch` |
| PV Flex | RefMarkt PV − 0,60 ct | `at_vkw_pv_flex` |

### Attribution

Day-Ahead über Energy-Charts: [Energy-Charts](https://energy-charts.info) (Fraunhofer ISE), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## 7. Audit / Abweichungen (Stand 2.3.b, 2026-07-21)

Transparenz zur Katalogpflege: Abgleich öffentlicher Quellen mit `tariffs.json`. Sekundärseiten können Grundgebühren weglassen oder USt falsch zuordnen — Primärquellen (Produktseite / Tarifblatt) haben Vorrang.

### Monatsgebühren (geseedet, Näherung)

| Katalog-ID | `monthly_fee_eur` | Basis | Quelle |
| ---------- | ----------------- | ----- | ------ |
| `awattar_at` | 4,79 | netto | [awattar.at/tariffs/hourly](https://www.awattar.at/tariffs/hourly) |
| `at_vkw_strom_dynamisch` | 3,00 | netto | [vkw.at Strom Dynamisch](https://www.vkw.at/produkte/strom/strom-dynamisch) (36 €/Jahr netto) |
| `at_vkw_strom_duo` | 3,00 | netto | [vkw.at Strom Duo](https://www.vkw.at/produkte/strom/strom-duo) (36 €/Jahr netto) |
| `at_smartenergy_smartcontrol` | 2,49 | netto | [smartenergy.at/smartcontrol](https://smartenergy.at/smartcontrol) (2,99 brutto) |
| `at_spotty_smart_active` | 2,00 | netto | Spotty-Rechnung / Portale (2,40 brutto) |
| `at_verbund_v_strom_spot` | 3,99 | netto | Selectra / Verbund-Grundpreis (ca. 4,79 brutto) |
| `de_tibber_tibber_dynamic` | 5,03 | netto | [Tibber Support](https://support.tibber.com/de/articles/12310314-grund-und-arbeitspreis-bei-tibber) (5,99 inkl. MwSt.) |
| `de_awattar_de_hourly_de` | 4,58 | netto (Näherung) | [awattar.de HOURLY](https://www.awattar.de/tariffs/hourly) (ggf. PLZ-abhängig) |

**Falle:** Manche Vergleichsportale behaupten für aWATTar AT „kein Grundpreis“ — das widerspricht der offiziellen aWATTar-Seite.

### Volumetrische Werte (Energieaufschläge)

| ID | Katalog | Prüfung | Status |
| -- | ------- | ------- | ------ |
| `awattar_at` | 1,5 ct + 3 % Markup, netto | Tarifblatt enthält 3 %; Marketingseite oft ohne 3 % | Match (Katalog vollständiger) |
| `at_vkw_strom_dynamisch` | 1,2 ct netto | Offiziell +1,20 ct netto | Match |
| `at_vkw_pv_dynamisch` / `at_vkw_pv_flex` | Abschlag 0,6; `vat_percent` 0 (ohne USt) | Offiziell ohne USt | Match |
| `at_smartenergy_smartcontrol` | 1,20 ct netto (`prices_include_vat` false) | Offiziell 1,20 netto / 1,44 inkl. | Match |
| `at_spotty_smart_active` | 1,49 ct netto | ≈ 1,79 inkl. / 1,2 | Match |
| `de_tibber_tibber_dynamic` | 1,81 ct netto | Support 2,15 ct brutto / 1,19 | Match |
| `at_verbund_v_strom_spot` | 1,3 + 4 % | Selectra eher Fix-ct; Formel unsicher | Offen — nur Monatsgebühr geseedet |
| `de_awattar_de_hourly_de` | 2,25 + 3 % | Seite betont EPEX+3 %; 2,25 unklar | Offen — Monatsgebühr ca. 4,58 |

Technische Typen und APIs: [Preise & aWATTar](../konfiguration/preise.md).
