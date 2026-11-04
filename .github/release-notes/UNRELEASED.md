# Unreleased — Sammelnotizen für das nächste Release

Maintainer-Hinweise als Eingabe für den Release-Notes-Entwurf (Skill `release-notes`): Der Entwurf muss sie enthalten. `release_notes_finalize` leert diese Datei bei offiziellen Releases (siehe `docs/workflow/release-checklist.md` §1).

Wenn seit dem letzten Tag neue Schritte in `runtime_store/migration/` hinzukamen: Abschnitt **`## Migration`** in die Release Notes (Entwurf: `python -m scripts.migration_release_notes --since <vorheriger-Tag>`).

## Neu

- **Chart 2 ist zurück, jetzt mit tatsächlicher Ersparnis.** Der Monitor vergleicht die gemessenen Kosten mit einer Anlage ohne Earnie (gleicher Verbrauch, gleiche PV, Batterie im Herstellermodus, gleiche Preise). Die neue Kachel „Mit Earnie gespart“ über Chart 2 zeigt das Ergebnis seit Beginn der Zählung. Beträge stehen ohne Vorzeichen, die Bedeutung als Wort dabei („gespart“, „mehr ausgegeben“). Grenzen: Das Verschieben von Verbrauch ist noch nicht bewertet, und das Ergebnis hängt vom eingestellten Batterie-Wirkungsgrad ab.

## Breaking / Bitte prüfen

- **Tariftypen `ex_post_spot` und `monthly_market` entfernt.** Beide wurden genau wie `spot_hourly` gerechnet und kamen im Tarifkatalog nicht vor. Ein Benutzertarif mit einem dieser Typen wird beim Laden abgelehnt; in `user_tariffs.json` den Typ auf `spot_hourly` ändern (gleiche Preise) oder den Tarif im Tarif-Editor neu anlegen. Die Typ-Filter im Szenarienkonfigurator heißen jetzt wie im Tarif-Editor („Festpreis“, „Börsenpreis + Aufschlag“, „Monatspreise“, jeweils mit „– Bezug“ / „– Einspeisung“).

- **`flexible_consumers` aus `config.json` entfernt.** Verbraucher kommen nur noch aus dem Hausprofil. Ein verbliebener Block (auch `[]`) stoppt den Start: einmal `python -m scripts.migrate_config` ausführen. Enthält der Block noch Einträge, bricht die Migration ab; dann die Verbraucher zuerst im Hausprofil anlegen.
