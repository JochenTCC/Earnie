---
name: session-abschluss
description: >-
  Beendet eine Entwicklungs-Session: Backlog.md, Backlog-Bugfixes.md und
  Backlog-Erledigt.md pflegen,
  alle offenen Änderungen committen und pushen, optional Docker-Image bauen
  und nach ghcr.io pushen.
  Verwenden bei „Session beenden“, „Backlog sync“, „Commit und Push“ oder
  ausdrücklicher Anfrage zum Session-Abschluss.
---

# Session-Abschluss

Zweiphasiger Workflow. **Phase 2 nur nach expliziter Bestätigung** des Users starten.

## Phase 1 — Backlog, Commit, Push

### 1. Kontext sammeln

Parallel ausführen:

- `git status`
- `git diff` (unstaged + staged)
- `git diff --cached`
- `git log -5 --oneline` (Commit-Stil)
- Chat-Verlauf dieser Session: was wurde erledigt, was ist offen geblieben?

### 2. Änderungen klassifizieren

**Standard:** Alle getrackten und sinnvollen untracked Änderungen committen.

**Vor dem Staging nachfragen** bei Dateien/Gruppen, die nur lokal oder möglicherweise temporär sind:

| Kategorie | Beispiele | Vorgehen |
|-----------|-----------|----------|
| IDE/Dev lokal | `.vscode/launch.json`, `.vscode/settings.json` mit persönlichen Pfaden | Einzeln vorstellen, committen ja/nein |
| Lokale Pfade | UNC-Pfade (`\\NAS\...`), absolute User-Pfade, Debug-Ports | Nachfragen |
| Experimentell | Scratch-Skripte, `tmp/`, `*.bak`, Kommentar-Reste | Nachfragen |
| Runtime/Secrets | `.env`, `runtime/*`, `config/config.json` | **Nicht** committen (gitignored); warnen falls doch sichtbar |
| Unklar | Große Diff ohne klaren Session-Bezug | Kurz beschreiben und nachfragen |

Wenn mehrere fragliche Dateien: **eine kompakte Liste** mit Empfehlung (committen / auslassen / später).

Erst nach Antwort des Users stagen. Ausgeschlossene Dateien nicht committen.

### 3. Backlog aktualisieren

Schema aus `Backlog.md` / `Backlog-Bugfixes.md` / `Backlog-Erledigt.md` beibehalten (siehe auch `.cursor/rules/backlog.mdc`):

- **Erledigte Punkte nicht durchstreichen** — aus der jeweiligen offenen Datei entfernen und in `Backlog-Erledigt.md` mit `- [x]` eintragen
- **Backlog-Bugfixes.md:** offene Prod-Bugs/Regressionen; bei Erledigung PATCH in `version.py` prüfen
- **Backlog.md:** Feature-Backlog (Version-Blöcke), Packaging, Referenz — nur noch offene Phasen/Unterpunkte
- **Backlog-Erledigt.md:** Neuer Abschnitt `### <Thema> (YYYY-MM-DD)` mit Datum **heute** (lokale Zeit Europe/Vienna)
- Nur dokumentieren, was in Session/Diff tatsächlich erledigt wurde — nichts erfinden
- Offene nächste Schritte bei teilweise erledigten Items belassen

Geänderte Backlog-Datei(en) in den Commit aufnehmen.

### 4. Commit

- Alle **freigegebenen** Änderungen stagen (`git add` gezielt oder `-A` minus ausgeschlossene Pfade)
- Commit-Message im Repo-Stil: kurz, Deutsch, Punkt am Ende, Fokus auf **Warum/Was** (vgl. `git log`)
- Mehrere thematisch getrennte Blöcke → ein Commit mit Bullet-Zeilen im Body ist ok; lieber **ein Session-Commit** als viele Mini-Commits
- **Nur committen, wenn der User Phase 1 ausgelöst hat** (explizite Session-beenden-Anfrage = Freigabe)

### 5. Push

```powershell
git push
```

Bei Fehler (upstream, Auth): Ursache nennen, nicht blind wiederholen.

### 6. Phase-1-Bericht

Kurz zusammenfassen:

- Backlog-Änderungen
- Commit-Hash und Message
- Push-Status
- Ausgeschlossene Dateien (falls vorhanden)

Abschließen mit:

> Soll ich jetzt das Docker-Image bauen und nach ghcr.io pushen?

**Nicht** automatisch mit Phase 2 starten.

---

## Phase 2 — Docker bauen & pushen (nur auf Nachfrage)

Start **nur** bei explizitem „Ja“ / „Docker bauen“ / „Image pushen“ nach Phase 1.

### 1. Version prüfen

`version.py` lesen. Wenn Code-Release sinnvoll erscheint, aber Version unverändert: User **einmal** fragen, ob `version.py` angehoben werden soll — nicht still ändern.

### 2. Build & Push

Kanonischer Befehl (linux/amd64, Synology):

```powershell
python -m scripts.build_container --push
```

Alternativ Windows-Wrapper: `.\build-container.ps1 --push`

Standard-Tags:

- `ghcr.io/jochentcc/ernie-energy:latest`
- `ghcr.io/jochentcc/ernie-energy:<version>` aus `version.py`

Details: `docs/einrichtung/container.md`

### 3. Voraussetzungen

- Docker läuft
- `docker login ghcr.io` erfolgreich — bei Auth-Fehler stoppen und Hinweis geben
- Hook kann `docker push` zur Bestätigung markieren — User-Freigabe abwarten

### 4. Phase-2-Bericht

- Gebaute/gepushte Tags
- Version aus `version.py`
- Kurzer Hinweis NAS-Deploy: `docker compose -f docker-compose-synology.yml pull && ... up -d`

---

## Fehlerbehandlung

- Keine leeren Commits
- Kein Push force ohne explizite User-Anweisung
- Kein Commit von Secrets oder gitignored Runtime-Dateien
- Bei Hook-Abfrage zu `docker push`: User-Entscheidung abwarten
