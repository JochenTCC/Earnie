# Fake-Jahresrechnung — Historisch (ohne Optimierung, ohne PV/Batterie)

Szenario-ID: `historical_reference`

Bezugstarif: aWATTar — HOURLY (`awattar_at`)

Einspeisetarif: VERBUND — V-Strom SonnenEinspeisung Fix (`at_verbund_v_strom_sonneneinspeisung_fix`)

## Jahr

| Position | Betrag |
| --- | ---: |
| Energiebezug | 2965.68 € (20052.4 kWh) |
| Einspeiseerlös | −0.00 € (0.0 kWh) |
| Verbrauch (Info) | 20052.4 kWh |
| Lieferant-Grundpreis | 57.48 € |
| Netzentgelt-Grundpreis | 0.00 € |
| Messstellengebühr | 0.00 € |
| Sonstige Fixkosten | 0.00 € |
| **Gesamt** | **3023.16 €** |

## Bezug

| Monat | Bezug kWh | Bezug € | Ø Tarif Cent/kWh | Ø Ist Cent/kWh |
| --- | ---: | ---: | ---: | ---: |
| 2025-01 | 1776.9 | 313.81 | 18.34 | 17.66 |
| 2025-02 | 1604.1 | 301.41 | 19.20 | 18.79 |
| 2025-03 | 1744.3 | 269.70 | 14.63 | 15.46 |
| 2025-04 | 1647.2 | 220.36 | 11.82 | 13.38 |
| 2025-05 | 1674.5 | 208.12 | 10.52 | 12.43 |
| 2025-06 | 1562.6 | 193.09 | 10.01 | 12.36 |
| 2025-07 | 1619.2 | 222.50 | 12.67 | 13.74 |
| 2025-08 | 1628.8 | 206.91 | 10.98 | 12.70 |
| 2025-09 | 1605.2 | 228.88 | 13.21 | 14.26 |
| 2025-10 | 1706.9 | 261.64 | 15.27 | 15.33 |
| 2025-11 | 1701.6 | 263.83 | 16.14 | 15.50 |
| 2025-12 | 1780.9 | 275.44 | 15.90 | 15.47 |
| **Jahr** | **20052.4** | **2965.68** | **14.03** | **14.79** |

## Einspeisung

| Monat | Einspeisung kWh | Einspeisung € | Ø Tarif Cent/kWh | Ø Ist Cent/kWh |
| --- | ---: | ---: | ---: | ---: |
| 2025-01 | 0.0 | 0.00 | 6.50 | — |
| 2025-02 | 0.0 | 0.00 | 6.50 | — |
| 2025-03 | 0.0 | 0.00 | 6.50 | — |
| 2025-04 | 0.0 | 0.00 | 6.50 | — |
| 2025-05 | 0.0 | 0.00 | 6.50 | — |
| 2025-06 | 0.0 | 0.00 | 6.50 | — |
| 2025-07 | 0.0 | 0.00 | 6.50 | — |
| 2025-08 | 0.0 | 0.00 | 6.50 | — |
| 2025-09 | 0.0 | 0.00 | 6.50 | — |
| 2025-10 | 0.0 | 0.00 | 6.50 | — |
| 2025-11 | 0.0 | 0.00 | 6.50 | — |
| 2025-12 | 0.0 | 0.00 | 6.50 | — |
| **Jahr** | **0.0** | **0.00** | **6.50** | **—** |

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
