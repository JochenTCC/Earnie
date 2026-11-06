# Unreleased — Sammelnotizen für das nächste Release

Maintainer-Hinweise als Eingabe für den Release-Notes-Entwurf (Skill `release-notes`): Der Entwurf muss sie enthalten. `release_notes_finalize` leert diese Datei bei offiziellen Releases (siehe `docs/workflow/release-checklist.md` §1).

Wenn seit dem letzten Tag neue Schritte in `runtime_store/migration/` hinzukamen: Abschnitt **`## Migration`** in die Release Notes (Entwurf: `python -m scripts.migration_release_notes --since <vorheriger-Tag>`).

## Neu

- **Chart 2 ist zurück, jetzt mit tatsächlicher Ersparnis.** Der Monitor vergleicht die gemessenen Kosten mit einer Anlage ohne Earnie (gleicher Verbrauch, gleiche PV, Batterie im Herstellermodus, gleiche Preise). Die neue Kachel „Mit Earnie gespart“ über Chart 2 zeigt das Ergebnis seit Beginn der Zählung. Beträge stehen ohne Vorzeichen, die Bedeutung als Wort dabei („gespart“, „mehr ausgegeben“). Grenzen: Das Verschieben von Verbrauch ist noch nicht bewertet, und das Ergebnis hängt vom eingestellten Batterie-Wirkungsgrad ab.

- **Chart 2 als Kontostand.** Chart 2 zeigt jetzt den Kontostand seit Fensterstart mit und ohne Earnie: links von Jetzt gebucht aus dem Ersparnis-Buch, rechts der Plan; fällt eine Linie, wird bezahlt. Der grüne oder rote Abstand zwischen den Linien ist die Ersparnis. Ein Umschalter wählt, ob sich die Linien bei Jetzt treffen (Abstand am Anfang = bisher gespart, am Ende = erwartet) oder gemeinsam bei 0 € beginnen. Ein kleines Panel darunter prüft, ob beide Seiten mit demselben Verbrauch gerechnet wurden. Das Fenster im Szenario-Explorer zeigt dieselbe Ansicht für seine beiden Läufe. Die bisherigen Kostenkurven und die Kosten-Annotationen je Tag entfallen. Die Seite „Analyse Verbrauch & Kosten“ zeigt dieselbe Ansicht für die gewählten 7 oder 28 Tage, mit einem Panel nur für die Ersparnis darunter.

- **Zahlen mit Komma.** Euro- und Cent-Beträge, kWh, kW und Prozent folgen jetzt der Sprache des Browsers, auch in Tabellen und auf den Achsen der Charts: Deutsch zeigt `2,18 €`, Englisch `2.18 €`. Eingabefelder zeigen weiter einen Punkt. Im Szenario-Explorer steht die Ersparnis wie im Monitor ohne Vorzeichen („gespart“, „mehr ausgegeben“); Differenzen wie `Δ vs Referenz` behalten ihr Vorzeichen.

- **Studienexport der Referenzleiter mit Brennstoff.** `scripts.run_reference_ladder` schreibt in `reference_ladder_summary.csv` und `reference_ladder_daily.csv` je Stufe jetzt auch Brennstoff (€ und kWh), Strom plus Brennstoff, Heizstab, Bezug, Einspeisung und Batterie-Durchsatz. Die neuen Spalten `saving_l2_l3_with_fuel_eur` und `rule_share_with_fuel` zeigen die Ersparnis inklusive Brennstoff. Die bisherigen Spalten bleiben reiner Strom. Der Tagesexport braucht einen neu gerechneten Lauf: Ältere Logs enthalten den Brennstoff nicht je Tag, das Skript bricht dann ab.

- **Heizstab im Live-Betrieb.** Earnie plant und schaltet den Heizstab jetzt auch live, sobald Freigabe, Leistung oder Laufstatus und Speichertemperatur zugeordnet sind. Er nutzt die freie Kapazität des Speichers am laufenden Tag, höchstens vier Einschaltungen. Grenzen: Übertemperaturschutz und das Verhalten beim Ausfall von Earnie bleiben Sache des Smarthomes, und die Ersparnis-Kachel rechnet gesparten Brennstoff nicht gegen.

## Breaking / Bitte prüfen

- **Szenario-Explorer: Die Ersparnis ist jetzt kleiner, weil die Methode strenger ist.** Earnie wird nicht mehr nur mit einer Anlage ohne Batterie und ohne Regeln verglichen, sondern mit Standard-Regeln: Batterie im Eigenverbrauchsmodus, PV-Überschussladen, SG-Ready-Sperre bei hohen Preisen, „günstigste Stunden“ und Abregeln bei negativem Einspeisepreis. Das sind die freien Mittel, die man auch ohne Earnie hätte. Die Ergebnisse zeigen oben die Ersparnis gegen diese Regeln und ihren Anteil an der Gesamtersparnis, die ganze Leiter von „Ohne Steuerung“ bis Earnie steht im Bereich „Alle Stufen“. Die Optimierung selbst rechnet nicht schlechter. Grenzen: Earnie plant im Szenario-Explorer mit bekannten Verläufen, die Ersparnis ist also eine Obergrenze. Bestehende Läufe bitte neu berechnen.

- **Szenario-Explorer: Ein E-Auto mit regelbarer Wallbox lädt jetzt stufenlos.** Die Optimierung plant zwischen Mindest- und Nennleistung wie im Live-Betrieb und trifft das Ladeziel genau, statt in ganzen Blöcken mit voller Leistung zu laden. Die Ergebnisse werden dadurch besser, in Stichproben um 14 bis 70 € im Jahr, und die Läufe rechnen schneller. Bestehende Läufe bitte neu berechnen.

- **Szenario-Explorer: In der Stufe „Regeln“ läuft ein Heizstab neben einer Brennstoffheizung jetzt auf PV-Überschuss.** Er bekommt, was nach Verbrauchern und Batterie eingespeist würde, läuft mit Nennleistung und höchstens bis zum Wärmebedarf des Tages. Seine Wärme spart Brennstoff. Die Ersparnis von Earnie gegen die Regeln ändert sich dadurch bei solchen Häusern. Bestehende Läufe bitte neu berechnen.

- **Szenario-Explorer: In der Stufe „Regeln“ wartet das E-Auto jetzt auf PV-Überschuss.** Es lädt nicht mehr sofort beim Anstecken, sondern aus dem Überschuss und erst kurz vor der Abfahrt aus dem Netz, wie eine Überschuss-Wallbox mit Zielzeit. Die Ersparnis von Earnie gegen die Regeln wird dadurch meist kleiner, bei Autos, die tagsüber zu Hause stehen, deutlich. Bei einem Pendlerauto kann die Regelstufe auch etwas teurer werden als vorher, weil es dann nachts lädt.

- **Batterie: Kein Entladen ins Netz mehr, nur weil der Ladestand über dem Plan liegt.** Das gilt auch im Live-Betrieb: Zwangsentladung läuft nur noch, wenn der Plan in diesem Slot tatsächlich verkauft. Sonst bleibt die Energie in der Batterie.

- **Ladefenster des E-Autos im Szenario-Explorer:** Jeder Slot nutzt jetzt das Fenster seines eigenen Tages. Vorher galt das Fenster des ersten Tags für den ganzen Planungshorizont, und über Wochenenden konnte das Auto zur falschen Zeit laden.

- **PV-Überschussladen im Plan:** Die Optimierung folgt einem Überschuss nur noch ab der Mindestleistung der Wallbox. Pläne mit 0,2 kW Ladeleistung, die keine Wallbox umsetzen kann, gibt es nicht mehr.

- **Tariftypen `ex_post_spot` und `monthly_market` entfernt.** Beide wurden genau wie `spot_hourly` gerechnet und kamen im Tarifkatalog nicht vor. Ein Benutzertarif mit einem dieser Typen wird beim Laden abgelehnt; in `user_tariffs.json` den Typ auf `spot_hourly` ändern (gleiche Preise) oder den Tarif im Tarif-Editor neu anlegen. Die Typ-Filter im Szenarienkonfigurator heißen jetzt wie im Tarif-Editor („Festpreis“, „Börsenpreis + Aufschlag“, „Monatspreise“, jeweils mit „– Bezug“ / „– Einspeisung“).

- **`flexible_consumers` aus `config.json` entfernt.** Verbraucher kommen nur noch aus dem Hausprofil. Ein verbliebener Block (auch `[]`) stoppt den Start: einmal `python -m scripts.migrate_config` ausführen. Enthält der Block noch Einträge, bricht die Migration ab; dann die Verbraucher zuerst im Hausprofil anlegen.
