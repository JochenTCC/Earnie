# OeMAG Marktpreis und E-Control Referenzmarktwert

Earnie nutzt für Einspeisetarife **zwei unterschiedliche** monatliche Referenzreihen. Diese Seite erklärt beide und grenzt sie voneinander ab.

- Berechnungsformeln und Tariftypen: [Preise und Marktdaten](../konfiguration/preise.md)
- Quellenverzeichnis (URLs, Entscheidungen): [Tarife und Preise nachrechnen](tarife-quellen.md)

## Kurzüberblick

| Begriff | Gesetz | Veröffentlichung | Rolle in Earnie |
| ------- | ------ | ---------------- | --------------- |
| **OeMAG Marktpreis** | § 13 ÖSG 2012 | [oem-ag.at/marktpreis](https://www.oem-ag.at/marktpreis) | Shared-Kurve `oemag_monthly_feed_in_rates`; Seed für OeMAG- und OeMAG-proportionale Monats-Einspeisetarife |
| **Referenzmarktwert PV** | § 13 EAG | [e-control.at/referenzmarktwert](https://www.e-control.at/referenzmarktwert) | Shared-Kurve `econtrol_referenzmarktwert_pv_monthly`; Seed z. B. für VKW PV-Einspeisetarif Flex |
| **Referenzmarktpreis** | § 12 EAG | [e-control.at/referenzmarktpreis1](https://www.e-control.at/referenzmarktpreis1) | Jahres- bzw. Monatsmittel der Day-Ahead-Preise; **nicht** die OeMAG-Auszahlungskurve |

## OeMAG Marktpreis (ÖSG)

Die OeMAG vergütet Ökostrom in der Marktpreis-Bilanzgruppe (Anlagen < 500 kW(p)). Der Marktpreis wird **monatlich ex-post** festgelegt.

- **Basis:** Grundlage ist das mengengewichtete Day-Ahead-Monatsmittel bzw. der Korridor zum Quartalsmarktpreis (§ 41 ÖSG). Davon wird der Aufwand für Ausgleichsenergie abgezogen (2026 PV: 0,408 ct/kWh).
- **Grenzen:** Die Untergrenze liegt bei 60 % des Quartalsmarktpreises (abzgl. Ausgleichsenergie), die Obergrenze bei 100 % derselben Größe.
- **Veröffentlichung:** Die OeMAG veröffentlicht den Wert Anfang des Folgemonats auf ihrer Website.

In `tariffs.json` liegt die Kurve unter `oemag_monthly_feed_in_rates`. Der Export-Tarif `at_oemag_gesetzlicher_marktpreis` hat **eigene** `monthly_rates` (Typ `monthly_table`). Die Shared-Kurve dient der Katalog-Wartung.

## E-Control Referenzmarktwert PV (EAG)

Der Referenzmarktwert ist der **erzeugungsgewichtete** Mittelwert der Day-Ahead-Stundenpreise in der österreichischen Gebotszone. Er gilt jeweils für eine Technologie, hier Photovoltaik. Der Wert dient u. a. zur Berechnung der Marktprämie. Außerdem ist er Bezugsgröße für marktorientierte Einspeisetarife (z. B. VKW Flex = RefMarkt − Abschlag).

- **Veröffentlichung:** Die E-Control veröffentlicht den Wert monatlich (ca. 2.–9. des Folgemonats) unter [referenzmarktwert](https://www.e-control.at/referenzmarktwert). Maschinenlesbar mit Veröffentlichungsdatum: [Referenzmarktwert_Entwicklung.xlsx](https://www.e-control.at/documents/1785851/10823410/Referenzmarktwert_Entwicklung.xlsx) (Spalte „Photovoltaikanlagen“).
- **Auflösung:** Seit 01.10.2025 liegen Mengen und Preise in Viertelstundenauflösung vor. Solange das EAG Stundenwerte vorschreibt, rechnet die E-Control weiterhin mit **Stundenaggregaten**.

In `tariffs.json` heißt die Kurve `econtrol_referenzmarktwert_pv_monthly`. Beispiel PV für August 2026: **9,42 ct/kWh** (E-Control-Veröffentlichung vom 04.09.2026).

## Referenzmarktpreis (nicht verwechseln)

Der Referenzmarktpreis (§ 12 EAG) ist das **ungewichtete** arithmetische Mittel der Day-Ahead-Preise, jährlich bzw. monatlich. Er ist ein Vergleichswert, also weder die OeMAG-Auszahlung noch der RefMarkt PV.

## Pflegehinweis

Earnie fragt die offiziellen Seiten nicht automatisch ab. Neue Monatswerte werden von dort übernommen und mit einem Script eingetragen. Das Script rechnet alle abhängigen Katalog-Tarife mit `monthly_seed` für die betroffenen Monate automatisch nach:

```powershell
python -m scripts.update_tariff_curves --oemag 2026-08=8.997 --refmarkt 2026-08=9.42 --catalog-as-of 2026-09-28
python -m scripts.update_tariff_curves --check
```

- **`--set export:TARIF_ID:JJJJ-MM=CENT`:** trägt einen Einzelwert für Monats-Tarife **ohne** `monthly_seed` ein (z. B. aWATTar SUNNY aus dem Tarifblatt).
- **`--check`:** meldet Abweichungen zwischen Kurven und geseedeten Tarifen sowie Monate, die nur Platzhalter enthalten.
- **`--dry-run`:** zeigt die Änderungen an, ohne zu schreiben.

Das Feld `monthly_seed` am Tarif dient nur der Katalog-Wartung. Die Runtime nutzt weiterhin `monthly_rates`.

| `curve` | Formel |
| ------- | ------ |
| `oemag` | OeMAG × `arbeitspreis_kwh_cent` / `monthly_float_reference_cent_kwh` − `settlement_fee_cent_kwh` |
| `econtrol_refmarkt_pv` | RefMarkt PV − `settlement_fee_cent_kwh` |

Ergibt die Formel einen Wert ≤ 0 ct, schreibt das Script nichts und gibt eine Warnung aus. `monthly_rates` erlaubt nur Werte > 0.
