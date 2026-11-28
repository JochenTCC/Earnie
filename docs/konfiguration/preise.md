# Preise und Marktdaten

**Nachrechnen für Anwender:** [Tarife und Preise nachrechnen](../referenz/tarife-quellen.md) (auf Englisch) erklärt Schritt für Schritt Bezugs- und Einspeisepreis, SE-Fixkosten und Fake-Jahresrechnung.

Diese Seite beschreibt die Konfiguration: Tariftypen, JSON-Felder und Datenquellen.

## Überblick: Woher kommen die Preise?

Live-Bezugspreise entstehen aus Spot-Tarifen (`spot_hourly` u. a.) und dem Day-Ahead-Marktpreis. Den Marktpreis holt Earnie über die Edibert-Bibliothek, in dieser Reihenfolge:

1. Cache, solange er das erwartete Fenster abdeckt,
2. **ENTSO-E**, wenn `ENTSOE_API_TOKEN` in `config/.env` gesetzt ist,
3. **Energy-Charts** (Fraunhofer),
4. **aWATTar** (nur AT und DE).

Die aWATTar-API-URL leitet Earnie aus `import_tariff_id` → `land` ab, nicht aus dem Tarif-`type`.

Quellen und rechtliche Grundlagen: [Tarife und Preise nachrechnen](../referenz/tarife-quellen.md) (auf Englisch), [OeMAG & Referenzmarktwert](../referenz/oemag-referenzmarktwert.md) (auf Englisch).

### Fixkosten (nur SE)

- **Lieferanten-Grundpreis:** `monthly_fee_eur`; doppelte Einträge fasst Earnie über `supplier_id` zusammen.
- **Weitere Monatsgebühren (optional):** `metering_monthly_fee_eur` und `other_monthly_fee_eur`. Sie zählen einmal je Hausanschluss, und zwar aus dem Bezugstarif, sonst aus dem Einspeisetarif.
- **Feste Netzbeträge:** Sie kommen nicht aus dem Tarif, sondern aus dem Netzbereich (siehe unten).
- **Netto oder brutto:** **EPEX-/Spot-Tarife** immer **netto** speichern und `prices_include_vat` = false setzen (gleiche Basis wie Settlement und Markup). Bei Festpreisen richtet sich netto/brutto nach `prices_include_vat`. Bei `prices_include_vat` = false schlägt Earnie den `vat_percent` des Tarifs auf die Monatsgebühren auf; bei true zählen sie unverändert.
- **Wirkung:** Die Fixkosten erscheinen nur in den Gesamt- und Monatskosten des **Szenario-Explorers** und in den Fake-Jahresrechnungen unter `{Log}/invoices/`. Live-MILP und stündliche `sim_cost` enthalten sie nicht.

Details: [tarife-quellen.md](../referenz/tarife-quellen.md) §4 (auf Englisch).

### Netznutzungsentgelte (Arbeitspreis)

Der Arbeitspreis für die Netznutzung steht am Hausprofil unter **Netzanschluss & Netzentgelt** im Objekt `netznutzung` (Cent/kWh **netto**, ohne USt).

- Er ist unabhängig vom Lieferantentarif.
- Earnie addiert ihn **vor** der USt zum Bezugspreis. Das gilt für Live-MILP und SE und für alle Import-Typen.
- In Fake-Jahresrechnungen erscheint er als eigene Position. Earnie rechnet ihn dafür aus dem Energiebezug heraus; bei Zeitfenstern ist er je Fenster aufgeschlüsselt.
- Der Arbeitspreis kann **zeitabhängig** sein (SNAP/WiNAP, siehe unten).
- **Leistungspreis:** Ab 2027 kommt je Monat ein Betrag für die höchste Viertelstunde des Netzbezugs dazu. Wie Earnie ihn rechnet und eine Bezugsgrenze einplant, steht unter [Leistungspreis und Bezugsgrenze](#leistungspreis-und-bezugsgrenze).
- **Netzverlust und Abgaben je kWh:** Der Katalog führt je Netzbereich auch das Netzverlustentgelt und die bundesweiten Abgaben (Erneuerbaren-Förderbeitrag, Elektrizitätsabgabe für Haushalte). Earnie addiert sie wie den Arbeitspreis vor der USt zum Bezugspreis. In Live-MILP und SE zählen sie also mit. Zeitregeln wie SNAP ändern sie nicht.
- **Feste Beträge je Jahr:** Grundpauschale, Förderbeitrag auf die Grundpauschale und Erneuerbaren-Förderpauschale stehen ebenfalls im Katalog, in Österreich zusammen 76,82 € netto je Jahr. Der Szenario-Explorer zählt je Kalendermonat ein Zwölftel davon, mit der USt des Bezugstarifs; bei 20 % USt sind das 7,68 € je Monat. Die Fake-Jahresrechnung zeigt jeden Betrag einzeln. Live-MILP und Slotpreise enthalten sie nicht.
- **Anzeige im Hauskonfigurator:** Unter dem gewählten Netzbereich steht, was er neben dem Arbeitspreis je kWh und je Jahr kostet.
- **Früheres Feld `grid_monthly_fee_eur`:** Tarife dürfen es nicht mehr enthalten. Der Migrations-Assistent verschiebt es aus Benutzertarifen in den eigenen Netzbereich, wenn alle Hausprofile denselben Benutzer-Netzbereich nutzen; sonst nennt er, was zu tun ist.

### Netznutzung am Hausprofil (`netznutzung`)

| Feld | Bedeutung |
| --- | --- |
| `area_id` | **Pflicht.** Netzbereich aus dem Katalog `earnie_env/config/grid_fees.json` (Seed aus öffentlichem [`share/config/grid_fees.json`](../../share/config/grid_fees.json); z. B. `AT-VBG`) oder ein Benutzer-Netzbereich aus `user_grid_fees.json` (eigener Arbeitspreis, siehe unten). Es gibt kein stillschweigendes „kein Netzentgelt“. |
| `power_metering` | Immer `unmetered_power` (nicht gemessene Leistung / Standard Haushalt). Wählt den Basis-Arbeitspreis im Katalog; keine UI-Einstellung. |
| `quarter_hour_meter` | Immer `true`. Earnie setzt voraus, dass ein Viertelstunden-Smart-Meter vorhanden ist (Voraussetzung der Katalogregeln SNAP/WiNAP); keine UI-Einstellung. |
| `include_status` | Welche Regel-Stati gelten. Standard ist nur `verordnet`; `entwurf` und `illustrativ` müssen bewusst aktiviert werden. |

**Zeitregeln** liegen im Katalog je Regelsatz (`rule_sets`). Eine Regel besteht aus:

- **Gültigkeit:** `valid_from` / `valid_to`.
- **Zeitraum:** Monate, Wochentage und Uhrzeitfenster. Ein Fenster darf über Mitternacht gehen und gilt in der Ortszeit des Hausprofils. Monat und Wochentag zählen nach dem Datum des Slots.
- **Wirkung:** `percent_off`, `absolute_cent` oder `add_cent`.
- **Voraussetzungen:** `requires`.
- **Status:** `status`.

Passt mehr als eine Regel, gewinnt die erste. Eine einbezogene Regel ohne Wert ist ein Fehler; Earnie ersetzt den Wert nicht stillschweigend.

| Regel | Fenster | Wirkung | Status |
| --- | --- | --- | --- |
| **SNAP** (Sommer-Nieder-Arbeitspreis) | 1.4.–30.9., 10–16 Uhr, NE 7 | −20 % auf den Arbeitspreis | verordnet (seit 1.4.2026) |
| **WiNAP** (Winter-Nieder-Arbeitspreis) | 1.10.–31.3., 22–4 Uhr, NE 7 | Höhe offen | Entwurf, im Katalog vorbereitet, standardmäßig aus |

Die Katalogwerte stammen aus den Verordnungen für 2026: SNE-V 2018 in der Novelle BGBl. II Nr. 305/2025 (Arbeitspreis, Grundpauschale, Netzverlustentgelt), Erneuerbaren-Förderbeitragsverordnung 2026 (BGBl. II Nr. 301/2025), Erneuerbaren-Förderpauschale-Verordnung 2025 (BGBl. II Nr. 416/2024) und Elektrizitätsabgabegesetz (BGBl. I Nr. 95/2025, Haushaltssatz befristet auf 2026). Der SNAP-Abschlag stammt von den Netzbetreibern. Netzbetreiber können Voraussetzungen (z. B. Opt-in) unterschiedlich handhaben.

### Eigener Arbeitspreis (Benutzer-Netzbereich)

Im Hauskonfigurator (**Netzanschluss & Netzentgelt** → **Netzbereich (Netznutzung)**) gibt es neben den Katalog-Netzbereichen die Auswahl **Eigener Arbeitspreis**. Earnie speichert den Wert als eigenen Netzbereich `user_<Hausprofil-ID>` in `user_grid_fees.json` (neben `grid_fees.json`) und trägt diese ID als `area_id` im Hausprofil ein.

- Ein neu angelegter eigener Arbeitspreis gilt für beide Messarten und hat keine Zeitregeln und keine festen Beträge.
- Das Formular ändert nur den Arbeitspreis. Steht im eigenen Netzbereich in `user_grid_fees.json` mehr, zum Beispiel Zeitregeln oder eine vom Migrations-Assistenten verschobene Grundgebühr, bleibt das beim Speichern erhalten. Eine Zeile unter dem Eingabefeld zeigt es an.
- Zeitregeln bearbeitet das Formular nicht. Dafür trägt man sie in `user_grid_fees.json` ein. Jeder Netzbereich aus dieser Datei steht auch in der Auswahl.
- `0` Cent/kWh heißt bewusst „kein Netzentgelt“.
- IDs in `user_grid_fees.json` beginnen mit `user_`. Dieselbe ID in `grid_fees.json` und `user_grid_fees.json` ist ein Ladefehler.
- Ein neues Hausprofil hat keinen vorausgewählten Netzbereich; ohne Auswahl speichert der Hauskonfigurator das Profil nicht.

Beide Netzentgelt-Dateien gehören wie die Tarifdateien zum **Tarif-Track** (Feld `tariff_format`, siehe [speichern-laden.md](speichern-laden.md)).

**Migration (Datenmodell 5):** Hausprofile aus Datenmodell 4 mit `area_id: null` und eigenem Wert `base_cent_kwh` stellt der Migrations-Wizard um: der Wert wandert unverändert in den Benutzer-Netzbereich `user_<Hausprofil-ID>`. Hat ein Profil keinen Netzbereich und keinen Wert (oder `0`), fragt der Wizard nach: Katalog-Netzbereich wählen oder `user_<Hausprofil-ID>` mit 0 Cent/kWh anlegen. Ein Hausprofil mit `base_cent_kwh` oder ohne `area_id` lädt Earnie nicht mehr; die Fehlermeldung verweist auf den Wizard bzw. `python -m scripts.migrate_config`.

Das noch ältere Feld `netznutzung_arbeitspreis_cent_kwh` stellt derselbe Wizard-Lauf zuerst auf das Objekt `netznutzung` um.

### Leistungspreis und Bezugsgrenze

Ab 2027 rechnen die österreichischen Netzbetreiber einen Teil des Netzentgelts als **Leistungspreis** ab (Systemnutzungsentgelte-Verordnung SNE-G-V, BGBl. II Nr. 299/2026). Maßgeblich ist je Kalendermonat die höchste Viertelstunde des Netzbezugs, gemittelt über die Viertelstunde. Für Haushalte (Netzebene 7) gibt es zwei Sätze in Cent je kW und Monat: einen bis 10 kW und einen höheren für den Anteil darüber. Abgerechnet werden mindestens 2 kW. Ein angebrochener Monat zählt voll.

**Start je Netzbereich.** Die Verordnung gilt ab 1.1.2027, der Netzbetreiber kann den Start für seinen Netzbereich aber bis 30.6.2028 hinausschieben. Earnie rechnet den Leistungspreis deshalb nur für Monate, die ein Eintrag des Netzbereichs abdeckt. Vor dem ersten Eintrag fällt keiner an, und eine Bezugsgrenze bleibt inaktiv; Monitor und Szenario-Formular sagen dann „Die Grenze bleibt inaktiv bis …“. Fehlt nach dem Start ein Monat, meldet Earnie einen Fehler, statt mit 0 zu rechnen.

**Preise und ihr Status.** Die Sätze je Netzbereich legt erst die Tarifverordnung (SNE-T-V) fest. Bis dahin enthält der Katalog **keine** Leistungspreise. Wer schon jetzt rechnen will, trägt sie in einen eigenen Netzbereich in `user_grid_fees.json` ein (siehe [Eigener Arbeitspreis](#eigener-arbeitspreis-benutzer-netzbereich)), zum Beispiel:

```json
"capacity_charges": [
  {
    "id": "lp_2027",
    "basis": "monthly_peak_15min",
    "min_kw": 2.0,
    "bands": [
      { "up_to_kw": 10, "cent_per_kw_month": 150 },
      { "up_to_kw": null, "cent_per_kw_month": 300 }
    ],
    "valid_from": "2027-01-01",
    "valid_to": "2027-12-31"
  }
]
```

Die Zahlen sind Platzhalter. Die Sätze sind netto; Earnie rechnet die USt des Bezugstarifs dazu. Ein eigener Eintrag ohne `status` gilt immer. Katalogeinträge tragen einen Status wie die Zeitregeln: `verordnet` gilt, `entwurf` und `illustrativ` nur, wenn `include_status` am Hausprofil sie einschließt. Ein ausgelassener Eintrag erscheint als Hinweis. Das Formular **Eigener Arbeitspreis** bearbeitet die Einträge nicht, behält sie aber beim Speichern.

**Was Earnie damit tut.**

- **Szenario-Explorer:** Er weist den Betrag je Kalendermonat aus, für jede Vergleichsstufe und für die Optimierung ([Tarife und Preise nachrechnen](../referenz/tarife-quellen.md) (auf Englisch)).
- **Monitor:** Er zeigt im laufenden Monat die gemessene Spitze, die abgerechnete Leistung und den Betrag bisher ([Betriebsmodi](../ui/betriebsmodi.md#sunset-2-sunset-seite-monitor)).
- **Bezugsgrenze:** Am Szenario lässt sich eine Grenze für den Netzbezug je Viertelstunde eintragen, dazu eine Sicherheitsmarge ([Konfiguration](overview.md), [Handbuch](../user-manual/Benutzer-Handbuch-Earnie.md)). Der Plan hält den Bezug dann unter Grenze minus Sicherheitsmarge. Den Preis selbst kennt die Planung nicht: Earnie wägt nicht ab, ob sich ein Überschreiten in diesem Monat lohnen würde. Die Grenze wählt der Nutzer.
- **Vorgehen:** Zuerst im Szenario-Explorer Varianten mit verschiedenen Grenzen vergleichen, denn eine enge Grenze kann mehr Strom kosten, als sie beim Leistungspreis spart. Dann die Grenze im Live-Betrieb auf **Beobachten** stellen: Earnie steuert wie ohne Grenze und zeigt auf dem Monitor, wo er eingegriffen hätte und was das gespart hätte. Erst danach auf **Danach planen** umstellen.

**Batterie nach Plan.** Mit **Danach planen** verteilt der Plan die Batterie oft über mehrere teure Viertelstunden und entlädt in jeder nur einen Teil des Verbrauchs. Im Automatikbetrieb würde der Wechselrichter den ganzen Verbrauch decken und die Batterie zu früh leeren. Earnie setzt deshalb in Viertelstunden mit Grenze die Entladegrenze des Wechselrichters auf die geplante Leistung. Liegt der Verbrauch über der Prognose, hebt Earnie die Grenze so weit an, dass der Bezug auf dem geplanten Wert bleibt. Zwangsladen holt einen Rückstand zum geplanten SoC höchstens bis zur Grenze auf. Der Szenario-Explorer bucht genauso.

**Ein zuverlässiger Plan, keine Garantie.** Earnie plant jede Viertelstunde so, dass der Bezug unter der Grenze bleibt. Die gemessene Spitze kann trotzdem höher liegen:

- **Keine Regelung innerhalb der Viertelstunde.** Earnie plant einmal je Viertelstunde. Schaltet jemand Herd, Wasserkocher oder Waschmaschine ein, steigt der Bezug, und Earnie reagiert erst mit dem nächsten Plan.
- **Lastprognose und Messung.** Der Plan rechnet mit einer geschätzten Grundlast, und Earnie misst den Bezug selbst, nicht mit dem Zähler des Netzbetreibers. Die Sicherheitsmarge, vorbelegt mit 0,7 kW, fängt den üblichen Fehler beider ab, nicht jeden. Der Wert stammt aus einem Vergleich mit den Viertelstundenwerten des Netzbetreibers über knapp zwei Wochen an einer Anlage. Wer schon eine Grenze mit 0,3 kW gespeichert hat, behält diesen Wert und sollte ihn anheben.
- **Plan hält die Grenze nicht.** Reichen Batterie und Verschieben nicht, etwa bei hoher Grundlast, leerer Batterie oder einem Verbraucher, der sein Ziel erreichen muss, nennt der Monitor die Viertelstunden und die Ursache.
- **Ohne Plan keine Grenze.** Im Automatikbetrieb und in Fenstern ohne Optimierung gilt die Grenze nicht; Protokoll und Monitor vermerken das.
- **Einmal überschritten.** Liegt die Spitze des Monats schon über der Grenze, plant Earnie bis zu dieser Spitze, weil sie ohnehin bezahlt wird.
- **Eigene Messung.** Earnie misst die Spitze selbst, nach der eigenen Systemuhr ([Betrieb](../einrichtung/betrieb.md)). Maßgeblich ist die Abrechnung des Netzbetreibers.

### Land am Hausprofil

Der Hauskonfigurator speichert unter Standort das Feld `land` (`AT`/`DE`/`CH`). Im Szenarienkonfigurator ist der Filter **Land** Pflicht (kein „Alle“); er wird aus dem gewählten Hausprofil vorbelegt.

Optional speichert er daneben die **Region (Feiertage)** als Feld `region`: Bundesland bzw. Kanton für den Feiertagskalender (AT `1` Burgenland … `9` Wien, DE z. B. `BY`, CH z. B. `ZH`). Tarife mit Zeitregeln nach Wochentag oder Feiertag (z. B. Benutzertarife aus Edibert, siehe unten) brauchen sie zum Rechnen. Ohne Region gibt es keinen Feiertagskalender. Eine unbekannte Region lehnt Earnie beim Speichern ab.

Die Region schlägt auch den **Netzbereich** vor. Jeder österreichische Katalog-Netzbereich nennt in `grid_fees.json` sein Bundesland (Feld `regions`). Liegt in der gewählten Region genau ein Netzbereich, setzt der Hauskonfigurator ihn beim Wählen der Region; eine Zeile unter dem Netzbereich sagt das. In Österreich gilt das für Burgenland, Niederösterreich, Salzburg und Wien. In Kärnten, Oberösterreich, Steiermark, Tirol und Vorarlberg gibt es zusätzlich ein Stadt- bzw. Talnetz (Klagenfurt, Linz, Graz, Innsbruck, Kleinwalsertal); dort wählt der Benutzer selbst.

- Ein gewählter Netzbereich, der in der Region liegt, bleibt stehen, ebenso **Eigener Arbeitspreis**.
- Ein Netzbereich einer anderen Region wird ersetzt, wenn die neue Region eindeutig ist; sonst bleibt er stehen.
- Benutzer-Netzbereiche (`user_grid_fees.json`) haben keine Region und werden nie automatisch gesetzt.
- Hat eine ältere `grid_fees.json` noch kein Feld `regions`, setzt Earnie keinen Netzbereich; der Benutzer wählt ihn selbst.

## Bezugspreis (Live)

Die Live-Optimierung löst die `import_tariff_id` des Live-Szenarios gegen `earnie_env/config/tariffs.json` auf (Seed aus öffentlichem [`share/config/tariffs.json`](../../share/config/tariffs.json)). Aufschläge stehen **am Tarif-Eintrag** (`settlement_fee_cent_kwh`, `markup_percent`, `vat_percent` / `prices_include_vat`).

Die Preise je Slot berechnet die Tarif-Bibliothek [Edibert](https://github.com/JochenTCC/Edibert) – für Live und für den Szenario-Explorer dieselbe Rechnung. Jedes Szenario braucht dafür einen **Bezugs- und einen Einspeisetarif** (Katalog, Benutzertarif oder **Eigener Festpreis**). Ohne Tarif bricht die Berechnung mit einer Meldung ab; Earnie nimmt weder den Tarif des Live-Szenarios noch einen festen Ersatzwert. Ältere Szenarien mit `k_push_cent` / `feed_in_mode` ohne Einspeisetarif stellt der **Migrations-Wizard** um (Frage je Szenario).

### Marktpreise abrufen

Die Marktpreise (Live) kommen aus der Gebotszone des Hausprofil-`land` (AT / DE-LU / CH).

- **Erwartetes Fenster:** die letzten 7 Tage (Quellen für die Spiegelung) bis heute 24:00, ab 12:00 Ortszeit (Day-Ahead-Veröffentlichung) bis morgen 24:00. Spätere Stunden des Planungshorizonts füllt die Strategie unter [Fehlende Zukunftspreise](#fehlende-zukunftspreise-live) auf.
- **ENTSO-E:** Mit `ENTSOE_API_TOKEN` in `config/.env` fragt Earnie zuerst die **ENTSO-E Transparency Platform** ab (A44 Day-Ahead). AT/DE-LU liefern meist PT15M, CH derzeit PT60M; stündliche Werte gelten für alle vier Viertelstunden.
- **Energy-Charts:** Ohne Token oder wenn ENTSO-E nicht das ganze Fenster liefert, folgt **Energy-Charts** (Fraunhofer).
- **aWATTar:** Danach **aWATTar** (stündlich, auf 15-Min-Slots aufgeteilt), nur für AT (`api.awattar.at`) und DE (`api.awattar.de`). **CH hat keine dritte Quelle.**
- **Cache:** Der letzte Abruf liegt unter `runtime/edibert_market/market_<zone>.json`. Deckt er das Fenster ab, fragt Earnie keine Quelle. Fehlt etwas, fragt Earnie höchstens alle 10 Minuten erneut nach.
- **Ausfall aller Quellen:** Earnie nimmt die beste Teilantwort (auch aus dem Cache) und meldet die fehlenden Viertelstunden im Log; die Lücke füllt die Strategie für fehlende Preise. Ohne jeden Preis bricht der Lauf mit „Keine Day-Ahead-Preise“ ab.
- **Land:** Fehlt `land` im Hausprofil oder ist es unbekannt, bricht der Abruf mit einer Fehlermeldung ab.

### Berechnung

Der **Bezugspreis in Cent/kWh** ergibt sich so:

```
(Marktpreis × (1 + markup_percent/100) + settlement_fee_cent_kwh
  + Netznutzung Arbeitspreis aus Hausprofil, je Slot inkl. Zeitregeln)
  × (1 + vat_percent/100)   falls prices_include_vat = false
```

Die Netznutzung ist immer ein Nettopreis. Bei `prices_include_vat = true` addiert Earnie sie deshalb mit USt auf den Brutto-Preis des Lieferanten: `Preis + Netznutzung × (1 + vat_percent/100)`. Seit Tarifformat 1 ist `vat_percent` an **jedem** Tarif Pflicht (brutto und netto, `0` ist erlaubt); ein Tarif ohne `vat_percent` ist ein Ladefehler. Steht `vat_percent: 0` an einem Brutto-Tarif, warnt Earnie beim Laden und addiert die Netznutzung ohne USt.

| Feld (Spot-Import in tariffs.json) | Bedeutung |
| --- | --- |
| `settlement_fee_cent_kwh` | Fixer Aufschlag des Lieferanten auf den Börsenpreis in Cent/kWh (**nur Spot-Typen**; bei `fixed_cent` und `monthly_table` wirkungslos). Netzkosten gehören nicht hierher, sondern in `netznutzung` am Hausprofil. |
| `markup_percent` | Prozentualer Aufschlag (z. B. 3 ≈ Netzverlust) |
| `vat_percent` / `prices_include_vat` | USt (z. B. 20 % bei `prices_include_vat=false`) |

Das Hausprofil-Objekt `netznutzung` (siehe oben) gilt zusätzlich für **alle** Import-Typen, auch für Fixtarife. Ein Netzbereich mit 0 Cent/kWh (eigener Arbeitspreis `0`) bedeutet, dass keine Netzkosten angesetzt werden. Bei `fixed_cent` und `monthly_table` ist `settlement_fee_cent_kwh` ohne Wirkung; Earnie warnt beim Laden, wenn dort ein Wert ungleich 0 steht.

## Einspeisevergütung (Live)

Die Live-Optimierung löst die `export_tariff_id` des Live-Szenarios auf. Bei Typ `fixed` kommt `k_push_cent` aus dem Tarif-Eintrag in `tariffs.json`. Die Tarif-Referenz im Live-Szenario lässt sich im **Szenarienkonfigurator** ändern.

**Eigener Festpreis:** Die Dropdowns Bezug und Einspeise im Szenarienkonfigurator enthalten den Eintrag **Eigener Festpreis**. Earnie speichert die Cent/kWh-Werte am Szenario in `backtesting_scenarios.json` (`user_import_cent_kwh` / `user_export_cent_kwh`, Tarif-ID `__user_fixed__`), also nicht in `tariffs.json`.

- **Bezug:** Lieferanten-Arbeitspreis inkl. USt (wie Katalog-`fixed_cent`). Der Netznutzungs-Arbeitspreis aus dem Hausprofil wird weiterhin addiert, mit der Standard-USt des Hausprofil-Landes (AT 20 %, DE 19 %, CH 8,1 %).
- **Einspeise:** eingegebene Vergütung ohne weitere Aufschläge.

> **Hinweis:** Die Vergütung kann sich ändern (z. B. monatlich). Tarif in `tariffs.json` bzw. die gewählte `export_tariff_id` aktuell halten.

<a id="benutzertarife-usertariffsjson"></a>

### Benutzertarife (`user_tariffs.json`)

Eigene Tarife entstehen auf der Seite **Konfiguration → Tarife** (Tarif-Editor von [Edibert](https://github.com/JochenTCC/Edibert), eingebettet in Earnie; Beschreibung im [Benutzer-Handbuch](../user-manual/Benutzer-Handbuch-Earnie.md#tarife-benutzertarife)). Sie liegen in `user_tariffs.json` **neben** `tariffs.json` (gleiches Verzeichnis, gleiche Struktur, IDs beginnen mit `user_`). Earnie liest die Datei, wenn sie existiert; fehlt sie, gibt es einfach keine Benutzertarife. Die Datei gehört zum Config-Paket (Export/Import).

- Nach jedem Speichern oder Löschen auf der Seite Tarife prüft Earnie die Tarife einmal (Katalog, Benutzertarife, Netzbereiche, Hausprofile und die Tarif-Verweise der Szenarien) und zeigt Befunde als Fehlermeldung.
- Nutzt ein Szenario einen Benutzertarif, fragt der Editor vor dem Löschen nach und nennt die Szenarien. Nach dem Löschen meldet die Prüfung diese Szenarien, bis dort ein anderer Tarif gewählt ist; Earnie setzt die Auswahl nicht von sich aus zurück.

- Im Szenarienkonfigurator erscheinen Benutzertarife mit dem Zusatz **· Benutzertarif** in den Dropdowns Bezug und Einspeise.
- Benutzertarife mit Zeitregeln (`rules`), Preisunter- oder -obergrenze (`price_floor_cent_kwh` / `price_cap_cent_kwh`) berechnet Earnie über Edibert wie jeden anderen Tarif.
- Edibert prüft die Datei streng: ein falsches ID-Präfix, ein unbekanntes Feld oder eine doppelte ID ist ein Ladefehler mit Hinweis auf `user_tariffs.json`. Jeder Benutzertarif braucht wie Katalog-Tarife ein `land` und einen `vat_percent` (`0` erlaubt).
- **Migration (Tarifformat 1):** Für Benutzertarife ohne `vat_percent` fragt der Migrations-Wizard den USt-Satz ab. Er schlägt den Standardsatz des Landes vor (AT 20 %, DE 19 %, CH 8,1 %), übernimmt ihn aber nur nach Bestätigung (Schaltfläche **Vorschlag übernehmen** oder eigener Wert).
- **Netz-Grundgebühr (`grid_monthly_fee_eur`):** Seit Edibert 0.1.12 gehört die monatliche Netz-Grundgebühr zum Netzbereich, nicht mehr zum Tarif. Ein Benutzertarif mit `grid_monthly_fee_eur` ist ein Ladefehler mit Hinweis auf die Migration. Der Migrations-Wizard verschiebt den Betrag als feste Jahresgebühr (`grid_base_fee`) in den eigenen Netzbereich, wenn alle Hausprofile denselben Benutzer-Netzbereich verwenden. Nutzen die Hausprofile verschiedene Netzbereiche oder einen Katalog-Netzbereich, oder haben mehrere Tarife verschiedene Werte, blockiert der Wizard und nennt die Tarife; das Feld ist dann von Hand zu entfernen. Im Szenario-Explorer zählt sie dann wie die übrigen festen Beträge des Netzbereichs (siehe [Netznutzungsentgelte](#netznutzungsentgelte-arbeitspreis)).
- **Teilen mit der Tarifdatenbank:** nur mit eigener Zustimmung auf der Seite *Tarife* (siehe [Benutzer-Handbuch](../user-manual/Benutzer-Handbuch-Earnie.md#tarife-benutzertarife)). Die Antwort steht in `runtime/tariff_share.json`; ohne Zustimmung bekommt der Editor weder Sendeweg noch Serververbindung.

## Planung & Backtesting

Der veröffentlichte Katalog liegt in [`share/config/tariffs.json`](../../share/config/tariffs.json) mit dem Root-Feld `catalog_as_of`. Zur Laufzeit nutzt Earnie `earnie_env/config/tariffs.json`; beim Bootstrap kopiert Earnie den Katalog bei Bedarf aus `share`. Szenarien in `backtesting_scenarios.json` verweisen auf `import_tariff_id` und `export_tariff_id` (oder auf `__user_fixed__` mit szenario-lokalen Cent-Feldern, siehe oben).

**Basiskatalog ohne neue Einträge (ab 2.8):** `share/config/tariffs.json` und `share/config/grid_fees.json` bekommen nur noch Korrekturen bestehender Einträge und die neuen Monatswerte der Referenzkurven, aber keine neuen Tarife oder Netzbereiche. Ein Tarif, der im Katalog fehlt, wird als Benutzertarif auf der Seite *Tarife* angelegt (siehe [Benutzertarife](#benutzertarife-usertariffsjson)). Neue Katalogtarife kommen künftig über den Community-Katalog von Edibert.

### Import-Typen

| Typ | Bedeutung |
| --- | --- |
| `fixed_cent` | Fixer Arbeitspreis (`fix_cent_kwh`) + optional Hausprofil-Netznutzung AP |
| `spot_hourly` | EPEX × (1 + `markup_percent`%) + `settlement_fee_cent_kwh` + optional Hausprofil-Netznutzung AP |
| `monthly_table` | Monatstabelle Bezug (`monthly_rates`) + optional Hausprofil-Netznutzung AP |

### Export-Typen

| Typ | Bedeutung |
| --- | --- |
| `fixed` | Konstante Vergütung (`k_push_cent`) |
| `spot_hourly` | EPEX − `feed_in_fee_factor` × \|EPEX\| − `settlement_fee_cent_kwh` + `feed_in_fix_cent` (Faktor/Fix optional, Standard 0) |
| `monthly_table` | Monatskonstante Vergütung (`monthly_rates` am Tarif) |

Beispiel mit Prozentabschlag: Katalog-id `dynamic_epex` (aWATTar SUNNY SPOT) als `spot_hourly` mit `feed_in_fee_factor: 0.19`.

Die Berechnung macht Edibert (Anbindung in [`data/edibert_slot_prices.py`](../../data/edibert_slot_prices.py)). Die MILP-Matrix nutzt `k_act` (Bezug) und `k_push_act` (Einspeisung) je **15-Min-Slot** (`dt_h = 0.25`).

**Abrechnung vs. Plan:** Earnie plant alle Lieferanten auf derselben QH-Matrix, sowohl solche mit Viertelstunden-EPEX (z. B. VKW, Tibber) als auch solche mit Stundenprodukt (z. B. aWATTar HOURLY). Stündliche Marktdaten (CH auf Energy-Charts, aWATTar-Fallback, Historie vor ~2025-10) expandiert Earnie auf vier gleiche QH-Preise. Tarife mit `settlement_mtu: 60min` rechnen mit dem Mittel der vier Viertelstunden **der echten Stunde**. Beginnt oder endet der Planungshorizont mitten in einer Stunde, holt Earnie die fehlenden Viertelstunden-Börsenpreise dieser Stunde dazu (Day-Ahead, sonst Spiegelung bzw. Prognose wie im Horizont), statt nur die vorhandenen zu mitteln. In der Herbst-Zeitumstellung zählen die beiden 02:00-Stunden getrennt.

**Fehlender Folgemonat:** Fehlt in `monthly_rates` der Monat eines Planungsslots (typisch der **nächste Kalendermonat**), nutzt Earnie vorübergehend denselben Monat im Vorjahr, sonst den Vormonat, und schreibt eine Warnung ins Log.

- Ein UI-Hinweis (Sidebar und Eingabeformular im **Szenarienkonfigurator**) erscheint erst in den **letzten zwei Kalendertagen** des Monats. Erst dann kann der ~48h-Planungshorizont in den Folgemonat reichen.
- Die Eingabe (Cent/kWh) ergänzt den Monat in `earnie_env/config/tariffs.json`.
- `main.py` liest die Datei bei jedem Optimierungslauf neu (`reload_config`), die Streamlit-App bei jedem Lauf (`reinit_config`).

### Marktzonen (Backtesting)

| Land (`land`) | Zone | Datenquelle (API) |
| --- | --- | --- |
| AT | AT | Energy-Charts (`bzn=AT`) |
| DE | DE-LU | Energy-Charts (`bzn=DE-LU`) |
| CH | CH | Energy-Charts |

Day-Ahead-Daten: [Energy-Charts](https://energy-charts.info) (Fraunhofer ISE), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

**DACH-Katalog importieren:** `tools/convert_dach_tariffs.py` aus `stromtarife_dach_kombiniert.json` + `einspeisetarife_dach_erweitert.json` – seit 2.8 nur noch für Korrekturen bestehender Einträge (siehe *Basiskatalog ohne neue Einträge*).

**Plausibilität prüfen** (vor dem Produktivstart oder dem Umzug auf das NAS):

```powershell
python -m scripts.validate_tariffs --check-catalog
python tools/convert_dach_tariffs.py --check
```

### Monatspreis (`monthly_table`) – OeMAG / RefMarkt vs. aWATTar-SUNNY

Monatskonstante Einspeisetarife tragen **eigene** `monthly_rates`. Gemeinsame Kurven in `tariffs.json` dienen der Katalogpflege (Seeds):

| Feld | Zweck |
| --- | --- |
| `oemag_monthly_feed_in_rates` | ≥12 OeMAG-Gesetzliche-Marktpreise (Wartungskurve; länger für SE) |
| `monthly_float_reference_cent_kwh` | Historischer Nenner für OeMAG-proportionale Seeds (z. B. 7,15) |
| `econtrol_referenzmarktwert_pv_monthly` | ≥12 E-Control Referenzmarktwert PV (§ 13 EAG; z. B. VKW Flex-Seed) |

Die Seed-Formel gilt nur für die Katalogpflege, nicht zur Laufzeit. Sie ist pro Tarif im Feld `monthly_seed` festgelegt:

- `OeMAG_Monat × arbeitspreis / monthly_float_reference_cent_kwh − settlement_fee` bzw.
- `RefMarkt_PV − settlement_fee`.

Die Hilfsfunktionen stehen in [data/monthly_float_rates.py](../../data/monthly_float_rates.py). Gepflegt werden die Kurven mit `python -m scripts.update_tariff_curves` (siehe [Pflegehinweis](../referenz/oemag-referenzmarktwert.md#maintenance) (auf Englisch)).

Rechtliche Abgrenzung OeMAG vs. RefMarkt: [oemag-referenzmarktwert.md](../referenz/oemag-referenzmarktwert.md) (auf Englisch).

aWATTar-SUNNY-Fixwerte liegen ebenfalls als `monthly_table` vor (z. B. `monthly_sunny_web_recherche`).

## Fehlende Zukunftspreise (Live)

Block `market_prices` in `config.json`:

| Feld | Bedeutung |
| --- | --- |
| `missing_price_strategy` | `forecast` (Standard) oder `mirror` |
| `forecast_model_path` | Pfad zu `price_model_coefficients.json` (Default: `share/data/price_model_coefficients.json`; Fallback `data/cache/…`; für Strategie `forecast`) |
| `live_bias_enabled` | Rollierende EPEX-Bias-Korrektur auf prognostizierte Slots (Standard: `true`) |
| `live_bias_lookback_hours` | Lookback-Fenster in Stunden vor dem ersten prognostizierten Slot (Standard: `48`) |
| `live_bias_cap_cent_kwh` | Absolute Kappe ±Cent/kWh, für Bias und Anschluss (Standard: `12.0`) |
| `live_bias_seam_hours` | Bekannte Stunden vor dem ersten prognostizierten Slot, deren Abweichung den Anschluss bestimmt (Standard: `2`) |
| `live_bias_seam_decay_hours` | Stunden, in denen der Anschluss linear in den Bias übergeht; `0` schaltet den Anschluss ab (Standard: `8`) |

Wenn keine Preisquelle der Kaskade (Cache, ENTSO-E, Energy-Charts, aWATTar) für späte Stunden des Horizonts schon Preise liefert, gilt die gewählte Strategie:

- **`forecast` (Standard):** Ein OLS-Korrelationsmodell extrapoliert die fehlenden Stunden. Als Live-Features dienen die Open-Meteo-Wetterprognose und ein stündlicher EU-Leistungs-Stand-in aus dem letzten Archivtag. Charts zeigen diese Stunden als grünen Bereich (siehe [Charts](../ui/charts.md)). Mit dem Standard `live_bias_enabled` korrigiert Earnie die prognostizierten EPEX-Werte rollierend (Day-Ahead − OLS), begrenzt durch `live_bias_cap_cent_kwh`. Der Bias ist die mittlere Abweichung der `live_bias_lookback_hours` Stunden vor dem ersten prognostizierten Slot; bekannte Preise des Horizonts zählen also mit. Damit die Prognose an die letzten bekannten Preise anschließt, beginnt sie mit der mittleren Abweichung der letzten `live_bias_seam_hours` bekannten Stunden und geht über `live_bias_seam_decay_hours` linear in den Bias über. Der erste prognostizierte Slot liegt damit auf dem Niveau dieser Stunden, nicht exakt auf dem letzten Viertelstundenpreis. Fehlen mehrere getrennte Abschnitte, erhält jeder Abschnitt seinen eigenen Bias und Anschluss. Fehlt für eine dieser Stunden ein Preis oder ein Feature, gilt ab dem ersten Slot der Bias; das Log meldet das als Warnung. Lassen sich die Features der Stunden vor dem Planungsstart nicht laden, prognostiziert Earnie ohne Korrektur und meldet das ebenfalls als Warnung. Jeder prognostizierte Slot trägt seine Korrektur im Feld `live_bias_cent_kwh`.
- **`mirror`:** gleiche Uhrzeit am nächsten früheren Tag mit Preis (bis 7 Tage zurück; über die Zeitumstellung hinweg gilt die Uhrzeit, nicht der Abstand in Stunden). Ein Stundenwert gilt für alle vier Viertelstunden seiner Stunde. Earnie nutzt diese Strategie auch automatisch, wenn Modell oder Features nicht geladen werden können, und für einzelne Stunden ohne Features.
  Ist ein Datendienst (z. B. Energy-Charts) nicht erreichbar, bricht Earnie den Abruf beim ersten Verbindungsfehler ab und versucht es erst nach einer Stunde wieder, damit ein Lauf nicht minutenlang wartet. Wer die EU-Abrufe ganz abschalten möchte, setzt `missing_price_strategy` auf `mirror`.
  Liefert Energy-Charts für ein Land keine EU-Leistungsdaten („no content available“, z.B. für Dänemark seit dem 04.11.2026), rechnet Earnie die Summe der übrigen Länder mit dem typischen Anteil dieses Landes hoch (je Monat und Stunde, aus einem Jahr Archivdaten in `share/data/eu_power_country_shares.json`). Dasselbe gilt für einzelne Stunden, in denen ein Land keine Werte hat, z.B. wenn die Daten mitten am Tag enden. Die Prognose läuft dann weiter, das Log nennt das Land höchstens einmal pro Stunde, und die prognostizierten Slots tragen das Feld `eu_power_stand_in`. Kommen die Daten des Landes später doch noch, nutzt Earnie sie beim nächsten Abruf (spätestens nach einer Stunde). Machen die fehlenden Länder zusammen mehr als 15 % einer EU-Summe aus, nutzt Earnie die Spiegelung, weil das Modell mit allen zwölf Ländern trainiert ist.
  Antwortet Energy-Charts für ein Land auch nach mehreren Versuchen nur mit „zu viele Anfragen“ oder einem Serverfehler, nutzt Earnie ebenfalls die Spiegelung und meldet das Land im Log. Im Backtesting und beim Training braucht Earnie immer alle zwölf Länder mit Werten für jede Stunde ihres eigenen Kalendertags.

Im Backtesting mit `price_strategy=forecast` berechnet Earnie den Bias aus denselben Trainings-Features wie die Prognose (48 Stunden, ±12 Cent/kWh) und ruft dafür keine Daten bei Energy-Charts ab.

Prognose und Spiegelung füllen höchstens 72 Stunden ab dem ersten fehlenden Börsenpreis. Fehlen mehr, bricht die Preisberechnung mit einer Fehlermeldung ab, statt weiter in die Zukunft zu raten.

Spec: [Preis-Prognose](../dev/done/price-forecast-renewables.md) (Entwickler-Doku).

## Historische Preise

Für das **Backtesting** (Szenario-Explorer) legt `scenario_explorer_conf.price_source` die Quelle fest: `api` oder CSV über `path_price`.

- Die API lädt **Energy-Charts** (natives EPEX-Viertelstundenraster) über Edibert. Antwortet Energy-Charts nicht und liegt nichts im Cache, bricht der Lauf mit einer Fehlermeldung ab.
- **Cache:** ein Monat pro Datei unter `runtime/edibert_market/market_archive/<Zone>/JJJJ-MM.json`. Ein abgeschlossener Monat wird nicht erneut abgefragt; wiederholte Backtests laufen damit ohne Netz. Fehlende Viertelstunden meldet das Log als Warnung.
- **CSV** (`price_source` ≠ `api`): eine Energy-Charts-CSV unter `path_price`, Spalte `Day Ahead Auktion (<Zone>)`.
- `price_provider` ist ein Legacy-Feld und steuert die Reihenfolge nicht mehr.
- Die Bidding-Zone kommt aus dem Live-Importtarif (`market_zone` / `land`), sonst aus `energy_charts_bzn`. Fehlen beide, bricht der Lauf ab.
- `price_range` und der Simulations-Gesamtzeitraum kommen aus `cons_data` (12 Kalendermonate bis zum letzten vollständigen Monat).

### Monatliche Fixtarife (Backtesting)

Der Export-Tarif-Typ `monthly_table` in `tariffs.json` liefert die Monatswerte (`monthly_rates`). **Sunset-2-Sunset** (Produktiv) nutzt die aufgelöste Export-Tarif-Referenz aus dem Live-Szenario.

### Preisreihe exportieren (`export_price_series`)

`scenario_explorer_conf.export_price_series` (Standard: `false`) schreibt bei `true` die Marktpreisreihe des Simulationszeitraums zusätzlich in eine eigene Datei.

- **Inhalt:** die **tarifunabhängige** EPEX-Preisreihe, wie `scripts/run_backtesting.py` sie geladen hat (netto Cent/kWh, QH-Auflösung, vor Markup, Netznutzung und USt).
- **Ablage:** `backtesting_prices.csv` im Log-Zielordner (`--output-dir`, Standard `.`), referenziert in `backtesting_log.json` als `price_series_file`.
- **Unterschied zu `backtesting.csv`:** Diese Datei gilt pro Szenario und enthält bereits verrechnete `k_act`/`k_push_act`. Die Preisreihe ist dagegen die rohe Marktpreisserie, gemeinsam für **alle** Szenarien eines Laufs.
- **Zweck:** Weiterverwendung ohne erneuten Energy-Charts-Abruf, z. B. für externe Einsparpotenzial-Rechnungen.
