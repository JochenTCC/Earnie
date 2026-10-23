# Fake-Jahresrechnung — Live

Szenario-ID: `live`

Bezugstarif: aWATTar — HOURLY (`awattar_at`)

Einspeisetarif: VERBUND — V-Strom SonnenEinspeisung Fix (`at_verbund_v_strom_sonneneinspeisung_fix`)

## Jahr

| Position | Betrag |
| --- | ---: |
| Energiebezug | 1918.06 € (13880.2 kWh) |
| Einspeiseerlös | −563.52 € (8669.5 kWh) |
| Verbrauch (Info) | 20011.3 kWh |
| Lieferant-Grundpreis | 57.48 € |
| Netzentgelt-Grundpreis | 0.00 € |
| Messstellengebühr | 0.00 € |
| Sonstige Fixkosten | 0.00 € |
| **Gesamt** | **1412.01 €** |

## Bezug

| Monat | Bezug kWh | Bezug € | Ø Tarif Cent/kWh | Ø Ist Cent/kWh |
| --- | ---: | ---: | ---: | ---: |
| 2025-01 | 1348.1 | 209.32 | 18.34 | 15.53 |
| 2025-02 | 1163.1 | 203.04 | 19.20 | 17.46 |
| 2025-03 | 1186.4 | 167.89 | 14.63 | 14.15 |
| 2025-04 | 1027.6 | 134.27 | 11.82 | 13.07 |
| 2025-05 | 1068.4 | 132.08 | 10.52 | 12.36 |
| 2025-06 | 966.5 | 115.97 | 10.01 | 12.00 |
| 2025-07 | 1007.0 | 134.72 | 12.67 | 13.38 |
| 2025-08 | 1092.2 | 134.49 | 10.98 | 12.31 |
| 2025-09 | 1128.1 | 140.15 | 13.21 | 12.42 |
| 2025-10 | 1260.8 | 174.46 | 15.26 | 13.84 |
| 2025-11 | 1278.9 | 178.97 | 16.13 | 13.99 |
| 2025-12 | 1353.1 | 192.69 | 15.90 | 14.24 |
| **Jahr** | **13880.2** | **1918.06** | **14.03** | **13.82** |

## Einspeisung

| Monat | Einspeisung kWh | Einspeisung € | Ø Tarif Cent/kWh | Ø Ist Cent/kWh |
| --- | ---: | ---: | ---: | ---: |
| 2025-01 | 137.2 | 8.92 | 6.50 | 6.50 |
| 2025-02 | 315.1 | 20.48 | 6.50 | 6.50 |
| 2025-03 | 721.8 | 46.92 | 6.50 | 6.50 |
| 2025-04 | 1151.0 | 74.81 | 6.50 | 6.50 |
| 2025-05 | 1117.2 | 72.62 | 6.50 | 6.50 |
| 2025-06 | 1380.7 | 89.75 | 6.50 | 6.50 |
| 2025-07 | 1079.9 | 70.19 | 6.50 | 6.50 |
| 2025-08 | 1261.8 | 82.01 | 6.50 | 6.50 |
| 2025-09 | 716.3 | 46.56 | 6.50 | 6.50 |
| 2025-10 | 385.1 | 25.03 | 6.50 | 6.50 |
| 2025-11 | 286.7 | 18.63 | 6.50 | 6.50 |
| 2025-12 | 116.8 | 7.59 | 6.50 | 6.50 |
| **Jahr** | **8669.5** | **563.52** | **6.50** | **6.50** |

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
