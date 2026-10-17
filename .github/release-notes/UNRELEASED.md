# Unreleased — Sammelnotizen für das nächste Release

Maintainer-Hinweise als Eingabe für den Release-Notes-Entwurf (Skill `release-notes`): Der Entwurf muss sie enthalten. `release_notes_finalize` leert diese Datei bei offiziellen Releases (siehe `docs/workflow/release-checklist.md` §1).

Wenn seit dem letzten Tag neue Schritte in `runtime_store/migration/` hinzukamen: Abschnitt **`## Migration`** in die Release Notes (Entwurf: `python -m scripts.migration_release_notes --since <vorheriger-Tag>`).

## Breaking / Bitte prüfen

- **Home Assistant: Vorzeichen der Batterieleistung prüfen.** Earnie rechnet den Hausverbrauch jetzt durchgehend als `PV + Netz + Batterie`, mit Netz `+` = Bezug und Batterie `+` = Entladen ([Vorzeichenkonvention](../../docs/referenz/ehal.md#units-and-sign-convention-frozen)). Bisher wurde die Batterie im Live-Hausverbrauch mit falschem Vorzeichen eingerechnet, und der abgeleitete Hausverbrauch (`sens_power_consumers`) nutzte `PV − Netz − Batterie`. Wer in der EHAL-Zuordnung (`ehal.ha.sign`) die Batterieleistung bewusst gedreht hat, damit der alte Wert plausibel aussah, muss das prüfen: Die Batterie-Entity muss nach der Zuordnung beim **Entladen positiv** sein. Gleiches gilt für Loxone: `Earnie_Batterie_Leistung` muss beim Entladen positiv sein (Earnie dreht nicht mehr).
