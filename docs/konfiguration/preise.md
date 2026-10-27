# Preise und Marktdaten

**Nachrechnen für Anwender:** [Tarife und Preise nachrechnen](../referenz/tarife-quellen.md) erklärt Schritt für Schritt Bezugs- und Einspeisepreis, SE-Fixkosten und Fake-Jahresrechnung.

Diese Seite beschreibt die Konfiguration: Tariftypen, JSON-Felder und Datenquellen.

## Überblick: Woher kommen die Preise?

Live-Bezugspreise entstehen aus Spot-Tarifen (`spot_hourly` u. a.) und dem Day-Ahead-Marktpreis. Den Marktpreis holt Earnie über die Edibert-Bibliothek, in dieser Reihenfolge:

1. Cache, solange er das erwartete Fenster abdeckt,
2. **ENTSO-E**, wenn `ENTSOE_API_TOKEN` in `config/.env` gesetzt ist,
3. **Energy-Charts** (Fraunhofer),
4. **aWATTar** (nur AT und DE).

Providerunabhängige EPEX-Daten für Planung und Backtesting kommen weiterhin von **Energy-Charts** (AT/DE/CH); aWATTar bleibt dort API-Fallback. Die aWATTar-API-URL leitet Earnie aus `import_tariff_id` → `land` ab, nicht aus dem Tarif-`type`.

Quellen und rechtliche Grundlagen: [Tarife und Preise nachrechnen](../referenz/tarife-quellen.md), [OeMAG & Referenzmarktwert](../referenz/oemag-referenzmarktwert.md).

### Fixkosten (nur SE)

- **Lieferanten-Grundpreis:** `monthly_fee_eur`; doppelte Einträge fasst Earnie über `supplier_id` zusammen.
- **Weitere Monatsgebühren (optional):** `grid_monthly_fee_eur`, `metering_monthly_fee_eur` und `other_monthly_fee_eur`. Sie zählen einmal je Hausanschluss, und zwar aus dem Bezugstarif, sonst aus dem Einspeisetarif.
- **Netto oder brutto:** **EPEX-/Spot-Tarife** immer **netto** speichern und `prices_include_vat` = false setzen (gleiche Basis wie Settlement und Markup). Bei Festpreisen richtet sich netto/brutto nach `prices_include_vat`.
- **Wirkung:** Die Fixkosten erscheinen nur in den Gesamt- und Monatskosten des **Szenario-Explorers** und in den Fake-Jahresrechnungen unter `{Log}/invoices/`. Live-MILP und stündliche `sim_cost` enthalten sie nicht.

Details: [tarife-quellen.md](../referenz/tarife-quellen.md) §4.

### Netznutzungsentgelte (Arbeitspreis)

Der Arbeitspreis für die Netznutzung steht am Hausprofil unter Standort im Objekt `netznutzung` (Cent/kWh **netto**, ohne USt).

- Er ist unabhängig vom Lieferantentarif.
- Earnie addiert ihn **vor** der USt zum Bezugspreis. Das gilt für Live-MILP und SE und für alle Import-Typen.
- In Fake-Jahresrechnungen erscheint er als eigene Position. Earnie rechnet ihn dafür aus dem Energiebezug heraus; bei Zeitfenstern ist er je Fenster aufgeschlüsselt.
- Der Arbeitspreis kann **zeitabhängig** sein (SNAP/WiNAP, siehe unten).
- Der Leistungspreis ist nicht modelliert.
- Der monatliche Netz-Grundpreis `grid_monthly_fee_eur` ist nur ein Platzhalter für die SE-Fixkosten.

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

Die Katalogwerte stammen aus einer Recherche (SNE-V 2018, Fassung 01.04.2026; SNAP-Abschlag laut Netzbetreibern). Sie sind nicht gegen die jeweiligen Preisblätter geprüft. Netzbetreiber können Voraussetzungen (z. B. Opt-in) unterschiedlich handhaben. Der Netzverlust-Anteil ist nicht enthalten.

### Eigener Arbeitspreis (Benutzer-Netzbereich)

Im Hauskonfigurator (Standort → **Netzbereich (Netznutzung)**) gibt es neben den Katalog-Netzbereichen die Auswahl **Eigener Arbeitspreis**. Earnie speichert den Wert als eigenen Netzbereich `user_<Hausprofil-ID>` in `user_grid_fees.json` (neben `grid_fees.json`) und trägt diese ID als `area_id` im Hausprofil ein.

- Ein eigener Arbeitspreis gilt für beide Messarten und hat keine Zeitregeln.
- `0` Cent/kWh heißt bewusst „kein Netzentgelt“.
- IDs in `user_grid_fees.json` beginnen mit `user_`. Dieselbe ID in `grid_fees.json` und `user_grid_fees.json` ist ein Ladefehler.
- Ein neues Hausprofil hat keinen vorausgewählten Netzbereich; ohne Auswahl speichert der Hauskonfigurator das Profil nicht.

Beide Netzentgelt-Dateien gehören wie die Tarifdateien zum **Tarif-Track** (Feld `tariff_format`, siehe [speichern-laden.md](speichern-laden.md)).

**Migration (Datenmodell 5):** Hausprofile aus Datenmodell 4 mit `area_id: null` und eigenem Wert `base_cent_kwh` stellt der Migrations-Wizard um: der Wert wandert unverändert in den Benutzer-Netzbereich `user_<Hausprofil-ID>`. Hat ein Profil keinen Netzbereich und keinen Wert (oder `0`), fragt der Wizard nach: Katalog-Netzbereich wählen oder `user_<Hausprofil-ID>` mit 0 Cent/kWh anlegen. Ein Hausprofil mit `base_cent_kwh` oder ohne `area_id` lädt Earnie nicht mehr; die Fehlermeldung verweist auf den Wizard bzw. `python -m scripts.migrate_config`.

Das noch ältere Feld `netznutzung_arbeitspreis_cent_kwh` stellt derselbe Wizard-Lauf zuerst auf das Objekt `netznutzung` um.

### Land am Hausprofil

Der Hauskonfigurator speichert unter Standort das Feld `land` (`AT`/`DE`/`CH`). Im Szenarienkonfigurator ist der Filter **Land** Pflicht (kein „Alle“); er wird aus dem gewählten Hausprofil vorbelegt.

Optional speichert er daneben die **Region (Feiertage)** als Feld `region`: Bundesland bzw. Kanton für den Feiertagskalender (AT `1` Burgenland … `9` Wien, DE z. B. `BY`, CH z. B. `ZH`). Tarife mit Zeitregeln nach Wochentag oder Feiertag (z. B. Benutzertarife aus Edibert, siehe unten) brauchen sie zum Rechnen. Ohne Region gibt es keinen Feiertagskalender. Eine unbekannte Region lehnt Earnie beim Speichern ab.

## Bezugspreis (Live)

Die Live-Optimierung löst die `import_tariff_id` des Live-Szenarios gegen `earnie_env/config/tariffs.json` auf (Seed aus öffentlichem [`share/config/tariffs.json`](../../share/config/tariffs.json)). Aufschläge stehen **am Tarif-Eintrag** (`settlement_fee_cent_kwh`, `markup_percent`, `vat_percent` / `prices_include_vat`).

Die Preise je Slot berechnet die Tarif-Bibliothek [Edibert](https://github.com/JochenTCC/Edibert) – für Live und für den Szenario-Explorer dieselbe Rechnung. Jedes Szenario braucht dafür einen **Bezugs- und einen Einspeisetarif** (Katalog, Benutzertarif oder **Eigener Festpreis**). Ohne Tarif bricht die Berechnung mit einer Meldung ab; Earnie nimmt weder den Tarif des Live-Szenarios noch einen festen Ersatzwert. Ältere Szenarien mit `k_push_cent` / `feed_in_mode` ohne Einspeisetarif stellt der **Migrations-Wizard** um (Frage je Szenario).

### Marktpreise abrufen

Die Marktpreise (Live) kommen aus der Gebotszone des Hausprofil-`land` (AT / DE-LU / CH).

- **Erwartetes Fenster:** die letzten 7 Tage (Quellen für die Spiegelung) bis heute 24:00, ab 12:00 Ortszeit (Day-Ahead-Veröffentlichung) bis morgen 24:00. Spätere Stunden des Planungshorizonts füllt die Strategie unter [Fehlende Zukunftspreise](#fehlende-zukunftspreise-live) auf.
- **ENTSO-E:** Mit `ENTSOE_API_TOKEN` in `config/.env` fragt Earnie zuerst die **ENTSO-E Transparency Platform** ab (A44 Day-Ahead). AT/DE-LU liefern meist PT15M, CH derzeit PT60M; stündliche Werte gelten für alle vier Viertelstunden.
- **Energy-Charts:** Ohne Token oder wenn ENTSO-E nicht das ganze Fenster liefert, folgt **Energy-Charts** (Fraunhofer).
- **aWATTar:** Danach **aWATTar** (stündlich, auf 15-Min-Slots aufgeteilt), nur für AT (`api.awattar.at`) und DE (`api.awattar.de`). **CH hat keine dritte Quelle**; früher nahm Earnie für CH ersatzweise die aWATTar-Reihe von AT, das entfällt.
- **Cache:** Der letzte Abruf liegt unter `runtime/edibert_market/market_<zone>.json`. Deckt er das Fenster ab, fragt Earnie keine Quelle. Fehlt etwas, fragt Earnie höchstens alle 10 Minuten erneut nach.
- **Ausfall aller Quellen:** Earnie nimmt die beste Teilantwort (auch aus dem Cache) und meldet die fehlenden Viertelstunden im Log; die Lücke füllt die Strategie für fehlende Preise. Ohne jeden Preis bricht der Lauf mit „Keine Day-Ahead-Preise“ ab.
- **Land:** Fehlt `land` im Hausprofil oder ist es unbekannt, bricht der Abruf mit einer Fehlermeldung ab (früher galt still AT).

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

### Benutzertarife (`user_tariffs.json`)

Eigene Tarife aus dem Tarif-Editor [Edibert](https://github.com/JochenTCC/Edibert) liegen in `user_tariffs.json` **neben** `tariffs.json` (gleiches Verzeichnis, gleiche Struktur, IDs beginnen mit `user_`). Earnie liest die Datei, wenn sie existiert; fehlt sie, gibt es einfach keine Benutzertarife. Die Datei gehört zum Config-Paket (Export/Import).

- Im Szenarienkonfigurator erscheinen Benutzertarife mit dem Zusatz **· Benutzertarif** in den Dropdowns Bezug und Einspeise.
- Benutzertarife mit Zeitregeln (`rules`), Preisunter- oder -obergrenze (`price_floor_cent_kwh` / `price_cap_cent_kwh`) berechnet Earnie über Edibert wie jeden anderen Tarif.
- Edibert prüft die Datei streng: ein falsches ID-Präfix, ein unbekanntes Feld oder eine doppelte ID ist ein Ladefehler mit Hinweis auf `user_tariffs.json`. Jeder Benutzertarif braucht wie Katalog-Tarife ein `land` und einen `vat_percent` (`0` erlaubt).
- **Migration (Tarifformat 1):** Für Benutzertarife ohne `vat_percent` fragt der Migrations-Wizard den USt-Satz ab. Er schlägt den Standardsatz des Landes vor (AT 20 %, DE 19 %, CH 8,1 %), übernimmt ihn aber nur nach Bestätigung (Schaltfläche **Vorschlag übernehmen** oder eigener Wert).

## Planung & Backtesting

Der veröffentlichte Katalog liegt in [`share/config/tariffs.json`](../../share/config/tariffs.json) mit dem Root-Feld `catalog_as_of`. Zur Laufzeit nutzt Earnie `earnie_env/config/tariffs.json`; beim Bootstrap kopiert Earnie den Katalog bei Bedarf aus `share`. Szenarien in `backtesting_scenarios.json` verweisen auf `import_tariff_id` und `export_tariff_id` (oder auf `__user_fixed__` mit szenario-lokalen Cent-Feldern, siehe oben).

### Import-Typen

| Typ | Bedeutung |
| --- | --- |
| `fixed_cent` | Fixer Arbeitspreis (`fix_cent_kwh`) + optional Hausprofil-Netznutzung AP |
| `spot_hourly` | EPEX × (1 + `markup_percent`%) + `settlement_fee_cent_kwh` + optional Hausprofil-Netznutzung AP |
| `ex_post_spot` | Wie Spot; Kennzeichnung ex-post-Abrechnung |
| `monthly_market` | Wie Spot; Kennzeichnung Monatsmarkt |
| `monthly_table` | Monatstabelle Bezug (`monthly_rates`) + optional Hausprofil-Netznutzung AP |

### Export-Typen

| Typ | Bedeutung |
| --- | --- |
| `fixed` | Konstante Vergütung (`k_push_cent`) |
| `spot_hourly` / `ex_post_spot` | EPEX − `feed_in_fee_factor` × \|EPEX\| − `settlement_fee_cent_kwh` + `feed_in_fix_cent` (Faktor/Fix optional, Standard 0) |
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

`simulation/engine.py` und `data/backtesting_prices.py` bepreisen über die Edibert-Preisreferenz der Szenario-Auflösung (`_edibert_pricing`); `_import_tariff_spec` / `_export_tariff_spec` tragen nur noch die Katalogparameter für Anzeige, Fixkosten und Rechnung. Day-Ahead-Daten: [Energy-Charts](https://energy-charts.info) (Fraunhofer ISE), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

**DACH-Katalog importieren:** `tools/convert_dach_tariffs.py` aus `stromtarife_dach_kombiniert.json` + `einspeisetarife_dach_erweitert.json`.

**Plausibilität prüfen** (vor dem Produktivstart oder dem Umzug auf das NAS):

```powershell
python -m scripts.validate_tariffs --check-catalog
tools/convert_dach_tariffs.py --check
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

Die Hilfsfunktionen stehen in [data/monthly_float_rates.py](../../data/monthly_float_rates.py). Gepflegt werden die Kurven mit `python -m scripts.update_tariff_curves` (siehe [Pflegehinweis](../referenz/oemag-referenzmarktwert.md#pflegehinweis)).

Rechtliche Abgrenzung OeMAG vs. RefMarkt: [oemag-referenzmarktwert.md](../referenz/oemag-referenzmarktwert.md).

aWATTar-SUNNY-Fixwerte liegen ebenfalls als `monthly_table` vor (z. B. `monthly_sunny`).

## Fehlende Zukunftspreise (Live)

Block `market_prices` in `config.json`:

| Feld | Bedeutung |
| --- | --- |
| `missing_price_strategy` | `forecast` (Standard) oder `mirror` |
| `forecast_model_path` | Pfad zu `price_model_coefficients.json` (Default: `share/data/price_model_coefficients.json`; Fallback `data/cache/…`; für Strategie `forecast`) |
| `live_bias_enabled` | Rollierende EPEX-Bias-Korrektur auf prognostizierte Slots (Standard: `true`) |
| `live_bias_lookback_hours` | Lookback-Fenster in Stunden (Standard: `48`) |
| `live_bias_cap_cent_kwh` | Absolute Kappe ±Cent/kWh (Standard: `12.0`) |

Wenn keine Preisquelle der Kaskade (Cache, ENTSO-E, Energy-Charts, aWATTar) für späte Stunden des Horizonts schon Preise liefert, gilt die gewählte Strategie:

- **`forecast` (Standard):** Ein OLS-Korrelationsmodell extrapoliert die fehlenden Stunden. Als Live-Features dienen die Open-Meteo-Wetterprognose und ein stündlicher EU-Leistungs-Stand-in aus dem letzten Archivtag. Charts zeigen diese Stunden als grünen Bereich (siehe [Charts](../ui/charts.md)). Mit dem Standard `live_bias_enabled` korrigiert Earnie die prognostizierten EPEX-Werte rollierend (Day-Ahead − OLS), begrenzt durch `live_bias_cap_cent_kwh`.
- **`mirror`:** gleiche Uhrzeit am nächsten früheren Tag mit Preis (bis 7 Tage zurück; über die Zeitumstellung hinweg gilt die Uhrzeit, nicht der Abstand in Stunden). Ein Stundenwert gilt für alle vier Viertelstunden seiner Stunde. Earnie nutzt diese Strategie auch automatisch, wenn Modell oder Features nicht geladen werden können.
  Ist ein Datendienst (z. B. Energy-Charts) nicht erreichbar, bricht Earnie den Abruf beim ersten Verbindungsfehler ab und versucht es erst nach einer Stunde wieder, damit ein Lauf nicht minutenlang wartet. Wer die EU-Abrufe ganz abschalten möchte, setzt `missing_price_strategy` auf `mirror`.

Spec: [Preis-Prognose (Dev)](../dev/done/price-forecast-renewables.md).

## Historische Preise

Für das **Backtesting** (Szenario-Explorer) legt `scenario_explorer_conf.price_source` die Quelle fest: `api` oder CSV über `path_price`.

- Die API lädt **Energy-Charts** (natives EPEX-Viertelstundenraster) über Edibert. Es gibt **keinen aWATTar-Fallback** mehr: Antwortet Energy-Charts nicht und liegt nichts im Cache, bricht der Lauf mit einer Fehlermeldung ab.
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
