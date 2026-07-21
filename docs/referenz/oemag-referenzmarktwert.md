# OeMAG Marktpreis und E-Control Referenzmarktwert

Diese Seite erklärt die **zwei unterschiedlichen** monatlichen Referenzreihen, die Earnie für Einspeisetarife nutzt. Beide sind **nicht** dasselbe.

Berechnungsformeln und Tariftypen: [Preise & aWATTar](../konfiguration/preise.md).  
Quellenverzeichnis (URLs, Entscheidungen): [Tarife — Quellen](tarife-quellen.md).

## Kurzüberblick


| Begriff | Gesetz | Veröffentlichung | Rolle in Earnie |
| ------- | ------ | ---------------- | --------------- |
| **OeMAG Marktpreis** | § 13 ÖSG 2012 | [oem-ag.at/marktpreis](https://www.oem-ag.at/marktpreis) | Shared-Kurve `oemag_monthly_feed_in_rates`; Seed für OeMAG- und OeMAG-proportionale Monats-Einspeisetarife |
| **Referenzmarktwert PV** | § 13 EAG | [e-control.at/referenzmarktwert](https://www.e-control.at/referenzmarktwert) | Shared-Kurve `econtrol_referenzmarktwert_pv_monthly`; Seed z. B. für VKW PV-Einspeisetarif Flex |
| **Referenzmarktpreis** | § 12 EAG | [e-control.at/referenzmarktpreis1](https://www.e-control.at/referenzmarktpreis1) | Jahres- bzw. Monatsmittel der Day-Ahead-Preise — **nicht** die OeMAG-Auszahlungskurve |


## OeMAG Marktpreis (ÖSG)

Die OeMAG vergütet Ökostrom in der Marktpreis-Bilanzgruppe (Anlagen < 500 kW(p)) mit einem **monatlich ex-post** festgelegten Marktpreis.

- Basis: mengengewichtetes Day-Ahead-Monatsmittel bzw. Korridor zum Quartalsmarktpreis (§ 41 ÖSG), abzüglich Aufwand Ausgleichsenergie (2026 PV: 0,408 ct/kWh).
- Untergrenze: 60 % des Quartalsmarktpreises (abzgl. Ausgleichsenergie); Obergrenze: 100 % derselben Größe.
- Veröffentlichung: Anfang des Folgemonats auf der OeMAG-Website.

In `tariffs.json` liegt die Kurve unter `oemag_monthly_feed_in_rates`. Der Export-Tarif `at_oemag_gesetzlicher_marktpreis` hat **eigene** `monthly_rates` (Typ `monthly_table`); die Shared-Kurve dient der Katalog-Wartung.

## E-Control Referenzmarktwert PV (EAG)

Der Referenzmarktwert ist der **erzeugungsgewichtete** Mittelwert der Day-Ahead-Stundenpreise der österreichischen Gebotszone für eine Technologie (hier: Photovoltaik). Er dient u. a. der Marktprämie und als Bezugsgröße marktorientierter Einspeisetarife (z. B. VKW Flex = RefMarkt − Abschlag).

- Veröffentlichung: monatlich durch die E-Control unter [referenzmarktwert](https://www.e-control.at/referenzmarktwert).
- Seit 01.10.2025 liegen Mengen und Preise in Viertelstundenauflösung vor; die E-Control bildet für die Berechnung weiterhin **Stundenaggregate**, solange das EAG Stundenwerte vorschreibt.

In `tariffs.json`: `econtrol_referenzmarktwert_pv_monthly`. Beispiel Jun 2026 PV: **5,55 ct/kWh** (Stand E-Control-Veröffentlichung).

## Referenzmarktpreis (nicht verwechseln)

Der Referenzmarktpreis (§ 12 EAG) ist das **ungewichtete** arithmetische Mittel der Day-Ahead-Preise (jährlich bzw. monatlich). Er ist ein Vergleichswert, nicht die OeMAG-Auszahlung und nicht der RefMarkt PV.

## Pflegehinweis

Monatswerte manuell aus den offiziellen Tabellen/Seiten nachziehen und bei Bedarf die `monthly_rates` der abhängigen Katalog-Tarife neu seeden. Es gibt keine automatische HTML-Abfrage.
