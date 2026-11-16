# Unreleased — Sammelnotizen für das nächste Release

Maintainer-Hinweise als Eingabe für den Release-Notes-Entwurf (Skill `release-notes`): Der Entwurf muss sie enthalten. `release_notes_finalize` leert diese Datei bei offiziellen Releases (siehe `docs/workflow/release-checklist.md` §1).

Wenn seit dem letzten Tag neue Schritte in `runtime_store/migration/` hinzukamen: Abschnitt **`## Migration`** in die Release Notes (Entwurf: `python -m scripts.migration_release_notes --since <vorheriger-Tag>`).

## Behoben

- **Szenario-Explorer: Ein Gerät, dessen Lauf nicht mehr ins Planungsfenster passte, legte die ganze Planung lahm.** Ein verschiebbares Gerät (Rolle „Gesteuert“ oder „Manuelles Gerät“) läuft in ganzen Blöcken. Blieb im Fenster weniger Platz als ein Block, etwa am ersten Morgen eines Laufs, war der Planungsschritt unlösbar und Earnie fiel für diese Stunden in die Automatik zurück. Jetzt plant Earnie den Lauf im nächsten Fenster und die übrigen Verbraucher wie gewohnt.
