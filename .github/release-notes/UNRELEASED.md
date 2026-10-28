# Unreleased — Sammelnotizen für das nächste Release

Maintainer-Hinweise als Eingabe für den Release-Notes-Entwurf (Skill `release-notes`): Der Entwurf muss sie enthalten. `release_notes_finalize` leert diese Datei bei offiziellen Releases (siehe `docs/workflow/release-checklist.md` §1).

Wenn seit dem letzten Tag neue Schritte in `runtime_store/migration/` hinzukamen: Abschnitt **`## Migration`** in die Release Notes (Entwurf: `python -m scripts.migration_release_notes --since <vorheriger-Tag>`).

## Breaking / Bitte prüfen

- **Wer schon mit einer 2.7-Vorabversion von 2.6 migriert hat: Batterie-Wirkungsgrad prüfen.** Die Migration hat den Wirkungsgrad des Wechselrichters (η_inv, Vorgabe 0,97) gesetzt, den bisherigen Batterie-Wirkungsgrad aber nicht aufgeteilt. Der Speicherpfad rechnet dann mit beiden Werten, z. B. 0,97 × 0,97 ≈ 0,94 statt 0,97 pro Richtung. Die Migration teilt jetzt richtig auf und zeigt die neuen Werte an. Bereits migrierte Konfigurationen werden nicht nachträglich korrigiert: Im Hauskonfigurator den Wirkungsgrad der Batterie (η_batt) so setzen, dass η_inv × η_batt dem früheren Wert aus 2.6 entspricht (früherer Wert ÷ η_inv, z. B. 0,97 ÷ 0,97 = 1,0).
- **Home Assistant: Vorzeichen der Batterieleistung prüfen.** Earnie rechnet den Hausverbrauch jetzt durchgehend als `PV + Netz + Batterie`, mit Netz `+` = Bezug und Batterie `+` = Entladen ([Vorzeichenkonvention](../../docs/referenz/ehal.md#units-and-sign-convention-frozen)). Bisher wurde die Batterie im Live-Hausverbrauch mit falschem Vorzeichen eingerechnet, und der abgeleitete Hausverbrauch (`sens_power_consumers`) nutzte `PV − Netz − Batterie`. Wer in der EHAL-Zuordnung (`ehal.ha.sign`) die Batterieleistung bewusst gedreht hat, damit der alte Wert plausibel aussah, muss das prüfen: Die Batterie-Entity muss nach der Zuordnung beim **Entladen positiv** sein. Gleiches gilt für Loxone: `Earnie_Batterie_Leistung` muss beim Entladen positiv sein (Earnie dreht nicht mehr).

- **`flexible_consumers` aus `config.json` entfernt.** Verbraucher kommen nur noch aus dem Hausprofil. Ein verbliebener Block (auch `[]`) stoppt den Start: einmal `python -m scripts.migrate_config` ausführen. Enthält der Block noch Einträge, bricht die Migration ab; dann die Verbraucher zuerst im Hausprofil anlegen.
