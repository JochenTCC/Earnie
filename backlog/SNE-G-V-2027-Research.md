# SNE-G-V 2027 — research note (capacity-based grid fee, Austria)

Research date: 2026-10-24. Backlog context: **Edibert integration → Capacity charge AT 2027** and **Implement max-power dependent tariff** (Version 2.8). Companion drafts: [Capacity-Peak-Budget-Draft.md](Capacity-Peak-Budget-Draft.md); external development document `Earnie-Projekt\Entwicklungsplan\Offen\Earnie-Leistungstarif-AT-2027-Entwicklungsdokument.md`.

Purpose: record what is **final** in the ordinance text, what is still **open**, and where each statement comes from, so the Earnie/Edibert design can cite it instead of secondary articles.

## 1. Legal status

| Item | Finding | Source |
|---|---|---|
| Enabling law | ElWG (Elektrizitätswirtschaftsgesetz), BGBl. I Nr. 91/2025, Nationalrat 2025-12-11, Bundesrat 2025-12-17, in force since 2025-12-24 | [S9], [S10] |
| Ordinance | **Systemnutzungsentgelte-Grundsatzverordnung (SNE-G-V)**, BGBl. II Nr. 299/2026, issued 2026-10-12, by the Vorstand of E-Control | [S1] |
| In force | 2027-01-01 (§ 32 Abs. 1); §§ 6 Abs. 3b and 7 Abs. 4b from 2026-10-13 | [S1] |
| Earlier stages | market consultation 2026-02-19 (8 kW split discussed), Begutachtungsentwurf with consultation until 2026-07-24 | [S4], [S5], [S6] |
| Prices | **not** in the SNE-G-V; set by the Tarifverordnung **SNE-T-V** per Netzbereich and Netzebene (ct/kW per month) | [S1], [S2] |

## 2. Rules confirmed from the ordinance text ([S1], read in full §§ 1–35)

- **Billing base:** calendar month, "basierend auf dem höchsten monatlichen Viertelstundenleistungswert" (§ 3 Abs. 1). § 2 Z 17 defines the Viertelstundenleistungswert as the average import or export power over 15 minutes. → Earnie's month-to-date peak = highest clock-aligned 15-min average import power of the calendar month.
- **Netzebene 7 structure:** two monthly capacity prices in ct/kW, one for the share up to 10 kW and one for the remaining share (§ 6 Abs. 2). The text does not say the upper share is more expensive; the E-Control presentation [S3] shows it at double the rate. → The ladder stays two linear segments; keep the slope of segment 2 a parameter.
- **Minimum billing base:** Netzebene 7: 2 kW, except Kleinstanschlüsse (§ 6 Abs. 3 Z 2). The 20 % of contracted power rule applies to Netzebenen 1–6 only (§ 6 Abs. 3 Z 1).
- **Ratio capacity : energy price:** to be raised stepwise in favour of the capacity price (§ 5 Abs. 1); **no quota and no year steps in the text**. E-Control communicates a 50:50 target [S2]; the presentation [S3] quotes end-state values.
- **Transition 2027:** § 6 Abs. 3a covers 2027-01-01 → 2027-11-30, including a flat EUR amount per Zählpunkt for customers without measured 15-min values (§ 6 Abs. 3a Z 1, referring to § 5 Abs. 1 Z 6 SNE-V 2018).
- **Introduction per Netzbereich:** operators report their expected readiness to the regulator by 2026-11-11 (§ 6 Abs. 3b); the dates can be modified per Netzbereich within 2027-01-01 → 2028-06-30 by a further ordinance under § 135 Abs. 1 ElWG. Secondary sources phrase this as "between 1 January 2027 and 1 July 2028, depending on the grid area" [S7].
- **Existing Netzebene-7 connections (§ 34 Abs. 1):** for connections built or contracted before 2027-01-01 the highest of (1) 10 kW, (2) the contracted netzwirksame Leistung as of 2026-12-31, (3) the mean of the two highest monthly 15-min peaks of 2026 (or 2027 if 2026 is missing) is "maßgeblich". Exceptions: Kleinstanschlüsse and connections that were interruptible per § 2 Abs. 1 Z 13 SNE-V 2018 on 2026-12-31 (§ 34 Abs. 2). **Reading:** this fixes the contracted power for grid-fee purposes (Netzbereitstellung / contracted capacity), not the monthly billing base of the capacity price (which is the measured peak with the 2 kW floor). **To verify against the Erläuterungen** before Edibert hardcodes anything.
- **No 15-min values:** SNAP and WiNAP do not apply to connections without measured 15-min values (§ 7 Abs. 5). A smart-meter opt-out is not regulated in the text.
- **Rounding:** commercially to two decimals (§ 28 Abs. 2).
- **SNAP / WiNAP windows (§ 7 Abs. 3, 4):** SNAP 1 April → 30 September, 10:00–16:00; WiNAP 1 October → 31 March, 23:00–05:00, first WiNAP from 2027-10-01 (§ 32 Abs. 4). Relevant for the existing SNAP regression case in Edibert/Earnie.

## 3. Still open (as of 2026-10-24)

- **Prices per Netzbereich:** SNE-T-V. Consultation announced for end of October 2026 [S7]; final values expected December 2026 [S8]. Indicative **end-state** values from the E-Control presentation of 2026-07-14 [S3]: energy price 4.53 ct/kWh, capacity price 33.82 EUR/kW/a up to 10 kW, 67.64 EUR/kW/a above. Presentation, not ordinance; first-year values will be lower because of the stepwise phase-in.
- **Start date per Netzbereich:** depends on operator readiness (report by 2026-11-11) and a follow-up ordinance.
- **Billing month of the peak:** same month vs. following month is not regulated in the text ([S1]); one operator FAQ describes the higher price "im darauffolgenden Monat" [S7] — operator practice, to be checked per Netzbereich.
- **§ 34 Abs. 1 interpretation:** see above.
- **Phase-in steps:** no numbers in the text; E-Control communication varies between "within three years" and "within the next years" [S2].

### Update 2026-11-07

- **SNE-T-V draft:** in consultation since 2026-10-29, comments until 2026-11-20 [S22]. Tariffs are published for both systems; the new one applies only once a Netzbereich has switched. The press release, its charts and the E-Control pages read give **no capacity price per kW** and no link to the draft text, so catalog values (plan D1) are still out of reach. The chart for the new system shows per-kWh equivalents at an assumed 4 kW and 3,500 kWh a year, for example Austrian average 9.55 ct/kWh, Vorarlberg 6.86 ct/kWh, net [S23]. These are preliminary and not usable as tariff data.
- **Start date:** the press release says the operators decide per Netzbereich, between 2027-01-01 and 2028-07-01 at the latest [S22]. One source gives 2027-12-01 as the default start [S24]. It fits the transition in § 6 Abs. 3a, which ends 2027-11-30, but was not checked against the ordinance. No dates per Netzbereich were published on the pages read; the operators' report is due 2026-11-11.
- **Next check:** after 2026-11-20 and when the final SNE-T-V is out (expected December 2026).

## 3a. Does the meter count on whole quarter hours? (research 2026-11-07)

Question: can Earnie measure in step with the official meter, without reading it?

| Region | Finding | Source | Level |
|---|---|---|---|
| AT | The value is the average power over a 15-minute market interval (SNE-G-V § 2 Abs. 1 Z 17). No statement on start times. Market interval not looked up in the ElWG. | [S1] | law, read |
| AT | The meter has an internal clock and calendar, remote synchronisation is provided for, values carry a timestamp (IMA-VO § 3 Z 2, Z 9). No alignment, no limit for the deviation, no synchronisation interval. | [S16] | law, read through a fetch summary |
| AT | Quarter-hour values may be meter readings, energy or average power depending on the meter type; meter readings "at the 15th minute". | [S17] p. 6 ff. | code of conduct, read |
| AT | Market rules chapter 6, V3.8: time zones and daylight saving of the data format; a text search finds no clock accuracy limit. Newer versions of the rules exist and were not read. | [S18] | market rules, searched |
| AT | Customer interface in Styria: push every 10 s, meter time with seconds and a summer-time flag, import and export counters in Wh. The example telegram has no running-average or peak register. | [S19] | operator document, 2024, one example |
| BE-VL | Fixed windows xxh00–xxh15 and so on, on the meter's internal clock. Import direction only, phases added first. The meter clock can be several seconds off the home system's, and it alone counts. P1 exposes the running average and the month peak. | [S20] | operator application note |
| DE | Time of a meter reading against legal time within ±27 s (3 % of 15 min), spacing of readings within ±9 s (PTB-A 50.8, as quoted in a talk). | [S21] | PTB talk 2016, not the rule itself |

**Conclusion:** clock-aligned quarter hours are the working assumption for Austria, supported by the market interval and by Flanders, but no Austrian text read states them, and none gives a tolerance. An answer would have to come from E-Control, an operator or a meter data sheet. A field comparison with the operator's quarter-hour export tests it in practice. Earnie's error from a clock offset is at most step of import power × offset / 900 s, for example 0.30 kW at 10 kW and 27 s. Consequences: `docs/dev/max-power-tariff-plan.md`, section **Meter timing**.

## 4. Consequences for the backlog items

- The MILP design (peak variable, convex two-segment ladder, 2 kW minimum, monthly reset) matches the final text. No model change needed.
- Prices, start date, minimum and segment slopes are **parameters per grid area supplied by Edibert**, never hardcoded in Earnie; this lets *Leistungstarif part 2* ship before the SNE-T-V values are published.
- The 2 kW floor means a household peak budget below 2 kW buys nothing; the budget loop should treat 2 kW as the lower bound.
- The 10 kW split applies to the **measured** peak on Netzebene 7 regardless of § 34; the § 34 value only matters if a Netzbereich bills a contracted-power component — keep a hook, do not model it until the SNE-T-V shows such a line.

## 5. Sources

Primary:

- [S1] RIS, BGBl. II Nr. 299/2026 — Systemnutzungsentgelte-Grundsatzverordnung (full text): <https://www.ris.bka.gv.at/Dokumente/BgblAuth/BGBLA_2026_II_299/BGBLA_2026_II_299.html>
- [S2] E-Control, "Neue Regeln für die Energiewende" (SNE-G-V landing page, decided version plus Erläuterungen, 2026-10-12): <https://www.e-control.at/marktteilnehmer/strom/sne-g-v/neue-regeln-fuer-die-energiewende>
- [S3] E-Control, Karin Emberger, Fachveranstaltung Grundsatzverordnung 2026-07-14 (slides with indicative end-state prices): <https://www.e-control.at/documents/1785851/1811582/03-Karin-Emberger-FachVA-GrundsatzVO-14072026.pdf/ea12f281-8d5e-3724-9869-b9014f0fab92?t=1784034800793>
- [S4] E-Control, SNE-G-V Begutachtungsentwurf samt Erläuterungen (V SNE 01/26): <https://www.e-control.at/documents/1785851/0/V+SNE+01_26+SNE-G-V+Begutachtungsentwurf+samt+Erl%C3%A4uterungen.pdf>
- [S5] E-Control, Marktkonsultation SNE-G-V Teil 1, 2026-02-19: <https://www.e-control.at/documents/1785851/0/Marktkonsultation+SNE-GV+Teil+1_20260219_1v0.pdf/c37b0eeb-080d-fd5c-9c4a-86b75b5f2051?t=1771832185841>
- [S6] Oesterreichs Energie, Stellungnahme zur SNE-G-V (Netz), 2026: <https://oesterreichsenergie.at/fileadmin/user_upload/Oesterreichs_Energie/Publikationsdatenbank/Stellungnahmen/Stellungnahmen_2026/OE-STN-SNE-G-V_Netz_u.pdf>

Secondary (operator / industry / press, for timelines and examples only):

- [S7] Energie NÖ, "Neue Netzentgelte ab 2027: Was die SNE-G-V für Haushalte bedeutet" (introduction window 2027-01-01 → 2028-07-01, SNE-T-V consultation end of October 2026): <https://www.energie-noe.at/neue-netzentgelte-ab-2027>
- [S8] pvrechner24, "Netzentgelt-Reform 2027" (status September 2026, SNE-T-V expected end of 2026): <https://www.pvrechner24.at/blog/netzentgelt-reform-2027-pv-speicher-eauto>
- [S9] ebz-photovoltaik, ElWG-Beschluss (Nationalrat / Bundesrat dates, BGBl. I Nr. 91/2025): <https://ebz-photovoltaik.at/elwg-beschluss-oesterreich/>
- [S10] ORF Kärnten, "Leistungsorientierte Netztarife ab 2027": <https://kaernten.orf.at/stories/3350801/>
- [S11] Wiener Stadtwerke, SNE-G-V Begutachtung (consultation until 2026-07-24, 8 → 10 kW change): <https://positionen.wienerstadtwerke.at/aktuelles/systemnutzungsentgelte-grundsatz-verordnung-begutachtung>
- [S12] stromliste.at, "Leistungstarif 2027" (overview, 60:40 start ratio claim, unverified): <https://stromliste.at/strompreis/zusammensetzung/netzentgelte/leistungstarif>
- [S13] Oesterreichs Energie, FAQ Systemnutzungsentgelte-Grundsatzverordnung (PDF, not machine-readable in this research; open manually): <https://oesterreichsenergie.at/fileadmin/user_upload/FAQ_Systemnutzungsentgelte-Grundsatzverordnung.pdf>
- [S14] HLK, "Strom-Kunden sollten ab 2027 auf ihr Nutzungsverhalten achten": <https://hlk.co.at/heizung/strom-kunden-sollten-ab-2027-auf-ihr-nutzungsverhalten-achten/>
- [S15] photovoltaik-service.at, "Was das SNE-G-V bedeutet" (E-Control household example: 7,000 kWh, 11 kW peak, +21 % / −8.5 %, from the draft): <https://photovoltaik-service.at/was-das-sne-g-v-bedeutet>

Added 2026-11-07 for section 3a:

- [S16] RIS, BGBl. II Nr. 339/2011, Intelligente Messgeräte-Anforderungsverordnung (IMA-VO): <https://www.ris.bka.gv.at/Dokumente/BgblAuth/BGBLA_2011_II_339/BGBLA_2011_II_339.html>
- [S17] Oesterreichs Energie / VÖEW, Verhaltensregeln Smart Meter (version of 2021-07-27): <https://oesterreichsenergie.at/fileadmin/user_upload/Smart_Meter-Plattform/Verhaltensregeln_idF_27.7.2021.pdf>
- [S18] E-Control, Sonstige Marktregeln Strom Kapitel 6, Version 3.8: <https://www.e-control.at/documents/1785851/1811582/SoMa_6_V3.8_clean.pdf/7ce1ebeb-8b6a-e93e-4e0e-5bd72e643611?t=1631299918433>
- [S19] Energienetze Steiermark, Aktivierung und Nutzung der Kundenschnittstelle (03/2024): <https://www.e-netze.at/downloads-data/pdf.aspx?pdf=EN_Update+Kundenschnittstelle+Smart+Meter+%2803_2024%29_WEB_RGB.pdf>
- [S20] Fluvius, Application note: Usage of maximum demands, month peaks: <https://partner.fluvius.be/sites/fluvius/files/2025-11/usage-of-maximum-demands-month-peaks.pdf>
- [S21] PTB, C. Leicht and R. Cuerdo, Latenzzeitmesseinrichtung für moderne elektronische Zähler (2016-05-11): <https://www.ptb.de/cms/fileadmin/internet/Veranstaltungen/2016/02_Leicht_Cuerdo.pdf>

- [S22] E-Control, press release on the tariff consultation, 2026-10-29: <https://www.e-control.at/documents/d/guest/2026_10_28_stromnetzentgelte_begutachtung_final_final-pdf>; consultation page: <https://www.e-control.at/begutachtungsentwurf-systemnutzungstarife-verordnung-2027>
- [S23] E-Control, chart of household grid fees from 2027, new system (consultation draft): <https://www.e-control.at/documents/d/guest/stromnetzengelte-darstellung-neue-systematik-1-jpg>
- [S24] Wiener Stadtwerke, "Systemnutzungsentgelte neu geregelt", 2026-10-14: <https://positionen.wienerstadtwerke.at/aktuelles/sne-g-vo>

Verification level: [S1] read in full; [S2] read as summary only; [S3]–[S6] located, key figures taken from search excerpts; secondary sources not independently verified. Re-check [S2] and the SNE-T-V when the consultation draft is published.
