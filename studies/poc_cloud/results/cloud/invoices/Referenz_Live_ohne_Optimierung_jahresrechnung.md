# Fake-Jahresrechnung — Referenz (Live) — ohne Optimierung

Szenario-ID: `ref:live`

Bezugstarif: aWATTar — HOURLY (`awattar_at`)

Einspeisetarif: VERBUND — V-Strom SonnenEinspeisung Fix (`at_verbund_v_strom_sonneneinspeisung_fix`)

## Jahr

| Position | Betrag |
| --- | ---: |
| Energiebezug | 2429.10 € (15915.0 kWh) |
| Einspeiseerlös | −699.37 € (10759.5 kWh) |
| Verbrauch (Info) | 20052.4 kWh |
| Lieferant-Grundpreis | 57.48 € |
| Netzentgelt-Grundpreis | 0.00 € |
| Messstellengebühr | 0.00 € |
| Sonstige Fixkosten | 0.00 € |
| **Gesamt** | **1787.21 €** |

## Bezug

| Monat | Bezug kWh | Bezug € | Ø Tarif Cent/kWh | Ø Ist Cent/kWh |
| --- | ---: | ---: | ---: | ---: |
| 2025-01 | 1539.2 | 266.52 | 18.34 | 17.32 |
| 2025-02 | 1320.2 | 245.71 | 19.20 | 18.61 |
| 2025-03 | 1371.5 | 214.49 | 14.63 | 15.64 |
| 2025-04 | 1229.4 | 177.19 | 11.82 | 14.41 |
| 2025-05 | 1242.4 | 171.64 | 10.52 | 13.82 |
| 2025-06 | 1108.6 | 154.44 | 10.01 | 13.93 |
| 2025-07 | 1160.7 | 167.38 | 12.67 | 14.42 |
| 2025-08 | 1212.2 | 167.13 | 10.98 | 13.79 |
| 2025-09 | 1288.4 | 186.77 | 13.21 | 14.50 |
| 2025-10 | 1427.9 | 219.35 | 15.27 | 15.36 |
| 2025-11 | 1458.2 | 221.78 | 16.14 | 15.21 |
| 2025-12 | 1556.5 | 236.70 | 15.90 | 15.21 |
| **Jahr** | **15915.0** | **2429.10** | **14.03** | **15.26** |

## Einspeisung

| Monat | Einspeisung kWh | Einspeisung € | Ø Tarif Cent/kWh | Ø Ist Cent/kWh |
| --- | ---: | ---: | ---: | ---: |
| 2025-01 | 318.8 | 20.72 | 6.50 | 6.50 |
| 2025-02 | 476.6 | 30.98 | 6.50 | 6.50 |
| 2025-03 | 910.3 | 59.17 | 6.50 | 6.50 |
| 2025-04 | 1364.8 | 88.71 | 6.50 | 6.50 |
| 2025-05 | 1301.6 | 84.61 | 6.50 | 6.50 |
| 2025-06 | 1529.7 | 99.43 | 6.50 | 6.50 |
| 2025-07 | 1240.6 | 80.64 | 6.50 | 6.50 |
| 2025-08 | 1390.5 | 90.38 | 6.50 | 6.50 |
| 2025-09 | 882.0 | 57.33 | 6.50 | 6.50 |
| 2025-10 | 560.3 | 36.42 | 6.50 | 6.50 |
| 2025-11 | 465.6 | 30.26 | 6.50 | 6.50 |
| 2025-12 | 318.5 | 20.70 | 6.50 | 6.50 |
| **Jahr** | **10759.5** | **699.37** | **6.50** | **6.50** |

## Hinweise

- Näherung für Plausibilität im Szenario-Explorer — **keine** echte Stromrechnung.
- Volumetrische **Netznutzung Arbeitspreis**: am Hausprofil setzen (`netznutzung`); sonst 0.
- **Leistungspreis** und netzgebietsspezifische Lookup-Tabellen werden **nicht** modelliert.
- Verbrauch (Info) = gebuchter Verbrauch der Stundenreihe dieses Szenarios (jeder Zeitslot einmal, ohne Speicher-Standby) – derselbe Wert wie „Jahres Verbrauch“ in der SE-Tabelle Gesamtkosten.
- Speicher-Standby (Info) = Eigenverbrauch der Hausbatterie; steckt in Bezug/Einspeisung (optimierte Szenarien und ihre Referenzen), wird aber nicht als Hausverbrauch gezählt.
- Verbrauch und Standby gehen **nicht** direkt in die Rechnungssumme ein.
- Ø Tarif Cent/kWh: arithmetisches Mittel der stündlichen Tarifpreise über alle Stunden des Monats (`Summe(k_act)/N` bzw. `k_push_act`); enthält ggf. den Netznutzung-Arbeitspreis.
- Ø Ist Cent/kWh: `Energiekosten € / Netzenergie kWh × 100` (nur Stunden mit Bezug bzw. Einspeisung wirken über die Summen).
- Fixkosten: Lieferant-Grundpreis je `supplier_id` einmal; Netzentgelt-/Messstellen-/Sonstige Fixkosten einmal je Hausanschluss (aus Bezugstarif, sonst Einspeisetarif) — Katalog-Stubs.
- Nicht modelliert: Leistungspreis, PLZ-/netzgebietsspezifische Stacks, separate Stromsteuer/Konzessionsabgabe/Elektrizitätsabgabe (oft im Arbeitspreis).

## Katalogparameter Bezug

| Parameter | Wert |
| --- | --- |
| Typ | Spot stündlich |
| Land | AT |
| Währung | EUR |
| Lieferant-Grundpreis (ca.) | 4.790 €/Monat |
| Anbieter (supplier_id) | awattar_at |
| Abwicklungsgebühr | 1.500 Cent/kWh |
| Aufschlag | 3 % |
| Preise inkl. USt | nein |
| USt | 20 % |

## Katalogparameter Einspeisung

| Parameter | Wert |
| --- | --- |
| Typ | Fixpreis Einspeise |
| Land | AT |
| Währung | EUR |
| Anbieter (supplier_id) | verbund |
| Hinweis | Klassischer Einspeise-Festpreis mit 12 Monaten Preisbindung unabhaengig vom Marktgeschehen. |
| Einspeisevergütung | 6.500 Cent/kWh |
| Abwicklungsgebühr | 0 Cent/kWh |
| Aufschlag | 0 % |
| Preise inkl. USt | ja |
| USt | 0 % |
