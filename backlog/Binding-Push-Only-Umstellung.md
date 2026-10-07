# Push-Only-Umstellung des Loxone-Bindings — Übergabe und Vorgehen

**Zweck:** Einstieg für einen neuen Chat. Beschreibt Ausgangslage, Entscheidungen, Pilot-Erkenntnisse und das Vorgehen, wie das Binding **entitätsweise** von „Loxone-Merker lesen (Poll)“ auf „Loxone sendet per Virtual Output (Push)“ umgestellt wird. **Stand: 2026-10-07. Es ist noch nichts vom Push-Only-Lesepfad gebaut** — der Pilot ist reine Beobachtung.

**Einstiegs-Prompt (in den neuen Chat kopieren):**

> Lies `CLAUDE.md` und `backlog/Binding-Push-Only-Umstellung.md`. Wir stellen das Loxone-Binding entitätsweise auf Push-Only um (Pilot-Branch `spike/vo-push-pilot`). Beginne mit Abschnitt 8 (Arbeitspakete) und frage mich nach den offenen Entscheidungen in Abschnitt 9, bevor du den Lesepfad änderst.

---

## 1. Ziel und Kontext

- **Heute:** Earnie liest jedes Loxone-Signal einzeln per `GET /jdev/sps/io/<Merkername>` (Polling). Die Zuordnung „EHAL-Feld → Merkername“ steht in `ehal_bindings`. Neue Felder erfordern Änderungen an etwa 15 Stellen, die Namenskonvention ist nicht durchgängig.
- **Ziel (Epic `Binding`, Backlog 2.7.n):** Bezeichner festschreiben (qualifizierte EHAL-IDs), Loxone sendet seine Werte per **Virtual Output** mit **EHAL-ID im Pfad** an Earnie. Dann braucht Earnie keine Merkernamen mehr zum Lesen.
- **Entscheidung für diese Umstellung:** **Push-Only** (kein dauerhafter Poll-Rückfall), **entitätsweise**, Earnie läuft im **Loud-Modus** (Sollwerte werden geschrieben!). Das Schreiben bleibt unverändert (direkt per `/dev/sps/io/<Name>/<Wert>` und `status.json`-Spiegel).
- Verwandte Dokumente: `backlog/EHAL-Binding-UX-Draft.md` (Analyse, §9 Slice 2.7.n, §10 Pilot-Ergebnisse), `backlog/Binding-Walkthrough-Ist.md` / `-Soll.md` (Lese-/Schreibpfad), Backlog-Eintrag **2.7.n** und Epic **Binding** in `backlog/Backlog.md`.

## 2. Stand der Repositories und Umgebungen

| Was | Stand |
|---|---|
| Pilot-Branch | `spike/vo-push-pilot` im Hauptordner `…\Energy-Optimizer`, Commit `054ab475` „spike(vo-push): pilot telemetry inbox, qualified IDs, VO <v> templates (v2.7.0-dev.20)“ auf `main@0006af86`. Enthält **alles** aus dem Pilot (siehe Abschnitt 5). Im Arbeitsbaum offen: nur `version.py` (dev.21, von dir, nicht von Claude). |
| Fix-Branch | `fix/status-json-powerstation-keys`, Commit `b5a658d2`, eigener Worktree `…\Energy-Optimizer-statusfix`. **Nicht gemerged** und **nicht** im Pilot-Branch enthalten. Behebt: Powerstation-Werte überschrieben die flachen Haus-Akku-Schlüssel in `status.json` (jetzt `ess.<Kennung>.<Feld>`). Mögliche Merge-Konflikte in `backlog/Backlog-Bugfixes.md` (beide Branches ändern die Datei). |
| NAS „Alpha“ | `192.168.178.35`, Daemon-Port **8541** (`8501` ist Streamlit!). Config: `P:\earnie-alpha\earnie_env\config`, Laufzeit: `P:\earnie-alpha\earnie_env\runtime` (`loxone_push_inbox.json`, `earnie.log`). Läuft **Loud**. Pilot-Empfänger aktiv; Token steht in der `.env` der Instanz (`EARNIE_PILOT_PUSH_TOKEN`, **nicht in dieser Datei**). Ob dort schon der Container aus `054ab475` läuft, ist zu prüfen (erkennbar daran, dass `consumer.`/`heatpump.`/`pool.`-IDs ankommen). |
| Greenfield (Dev-PC) | Host-Port 8542 → Container 8541; hat Platzhalter-Loxone, kein Poll-Vergleich. |
| Loxone | VO-Vorlagen aus `…\scratchpad\pilot_vo_alpha` liegen in `Documents\Loxone\Loxone Config\Templates\VirtualOut\` (8 Dateien `VO_Pilot_*.xml`) und als Kopie samt `Pilot-VO-Signalliste.csv` in `Documents\Loxone\pilot_vo_alpha\`. Alle 40 Befehle (39 Signale + Heartbeat) sind eingefügt und verdrahtet; in der Inbox kommen 40 Signale an bzw. werden als 0 angenommen. Offen: Befehl bei **AUS** der digitalen Signale prüfen, Heartbeat-Konstante verdrahten. |
| Alter Stash | `stash@{0}: wip before research/live-price-prognosis` (aus dem Repo, nicht anfassen; ein versehentliches `git stash pop` hat ihn einmal in einen Worktree gelegt, bereinigt). |

## 3. Was der Pilot über Loxone gezeigt hat

| Beobachtung | Folge |
|---|---|
| Ein VO-Befehl ist ein einfacher `GET` des Miniservers, **ohne Header**. | Token nur als `?t=` im Befehl. |
| Wert-Platzhalter im VO-Befehl ist **`<v>`** (`<v.1>` = eine Stelle); `\v` wird als Steuerzeichen 0x0B gesendet (`\v` gilt nur im Virtual **Input**). `<v>` liefert Punkt und drei Nachkommastellen. | Alle Telemetrie-Templates nutzen `<v>`. |
| Wiederholung läuft exakt alle 30 s, auch bei unverändertem Wert; der Timer startet nach jeder Sendung neu; Änderungen kommen sofort. | Frische-Kriterium 3 × 30 s = 90 s. |
| Ein Ausgang meldet „EIN“ (Wert ≠ 0) und „AUS“ (Wert = 0) getrennt. **Analog: kein AUS-Befehl** → bei 0 wird **nichts** gesendet. **Digital:** AUS wird einmal bei der Flanke gesendet, **nicht wiederholt**. | Schweigen eines analogen Signals = 0, **sofern die Verbindung lebt**. Digitale Werte gelten bis zur nächsten Flanke. Ein Abfall auf 0 wird erst nach 90 s bemerkt. |
| Der Docker-Empfänger sieht das Docker-Gateway (`172.28.0.1`) als Peer, nicht den Miniserver. | Peer-Anzeige ist nur Hinweis. |
| Exportierte Config-Vorlagen haben eine feste Struktur (`Info`-Element, `HintText`, `CmdAnswer`, `SourceVal…`, BOM, Tabs). | Repo-Templates und Generator folgen dieser Struktur. |
| `LoxAPP3.json` enthält nur sichtbare Controls, keine VO-/VI-Befehle, keine Beschreibungsfelder (nur `hasControlNotes`-Flag). | EHAL-IDs können nicht aus der Strukturdatei gelesen werden. Ob der Hinweis-Text der Zähler irgendwo exportiert wird, ist offen (später testen: frisch auslesen). |

## 4. Entscheidungen (bindend)

- **Qualifizierte EHAL-IDs** `<Namensraum>.<Kennung>.<Feld>`, Anlage ohne Namensraum: `ess` (Batterie), `evcs` (Wallbox), `ev` (Fahrzeug), `inv` (Wechselrichter, reserviert), `heatpump` (`thermal_annual`), `pool` (`thermal_rc` und die Entität `pool_filter`), `consumer` (alle übrigen). `flex.` bleibt nur als lesbarer Alias für gespeicherte Bindings. Speicherung unverändert (keine Migration).
- `sens_evcs_connected` ist in beiden EV-Namensräumen erlaubt und wird **nicht** umbenannt.
- Neue Namensvorschläge enthalten **immer** die Kennung. Die **Kennung ist editierbar** (Umbenennen nur mit Dry-Run; Alias-Tabelle falls Spike P0c das verlangt).
- Der Pilot ist beobachtend: nichts aus der Inbox speist bisher den Optimierer. Diese Datei beschreibt den Schritt, das zu ändern.
- Bindings werden **nicht** angefasst: Umschalten ist eine Quellen-Entscheidung je Entität, kein Datenmodell-Wechsel (Bindings behalten die Merkernamen für den Rückbau und die Zuordnung Name ↔ EHAL-ID).

## 5. Code-Landkarte (alles im Commit `054ab475`)

| Datei | Rolle |
|---|---|
| `ehal/qualified_ids.py` | Namensräume, Zuordnung Verbraucher → Namensraum, `is_digital_id`, `DIGITAL_KINDS`. |
| `ehal/push_signals.py` | `Signal`, `read_signals_from_docs(house, components)` (gebundene Lesefelder → qualifizierte ID, VO-Titel `Push_…`), `heartbeat_signal()`. |
| `runtime_store/loxone_push_inbox.py` | Inbox (`runtime/loxone_push_inbox.json`), `record_push`, `link_alive`, `derive_state` (OK / 0 gehalten / 0 angenommen / Digital gehalten / Unbekannt …), `expected_repeat_s` (`EARNIE_PILOT_PUSH_REPEAT_S`, Standard 30). |
| `integrations/loxone_request_http.py` | Daemon-HTTP auf 8541: Endpunkt `GET /ehal/loxone/telemetry/<ID>/<Wert>`; **aus**, solange `EARNIE_PILOT_PUSH_TOKEN` fehlt; Token als Header `X-Earnie-Token`, als **Adress-Präfix** `/t/<Token>` vor dem Pfad (Gerät-Adresse `http://host:8541/t/<Token>`, Befehl ohne `?t=`) oder als `?t=` (Reihenfolge in dieser Folge, das erste vorhandene muss stimmen); nimmt nur `sens_`/`get_`-IDs und `heartbeat`. |
| `ui/loxone_push_inbox_ui.py` | EHAL-Com-Abschnitt „Push-Inbox“: abgeleiteter Zustand, Verbindung, erwartete Signale aus den Bindings, Vergleich mit Poll-Wert. |
| `scripts/pilot_vo_template_gen.py` | Erzeugt `VO_Pilot_*.xml` aus den Bindings einer Config (`--config-dir`, `--host`, `--port`, `--env-file`/Platzhalter-Token, `--out-dir`). Digital: EIN `…/1`, AUS `…/0`; analog: kein AUS. Option `--token-in-address` setzt das Token in die Adresse des VO-Geräts statt in jeden Befehl. |
| `scripts/pilot_vo_capture.py` | Mini-Listener, zeigt, was ein VO wirklich sendet. |
| `share/loxone/templates/VirtualIn|VirtualOut/*.xml` | Repo-Vorlagen in der Config-Export-Struktur. |
| Tests | `tests/test_qualified_ids.py`, `test_loxone_push_inbox.py`, `test_loxone_push_inbox_ui.py`, `test_pilot_vo_template_gen.py`, `test_loxone_vo_template_shape.py`. |

Der heutige Lesepfad (Ziel der Umstellung): `integrations/loxone_client.py::fetch_loxone_generic_value` (ein Wert pro Aufruf), `integrations/loxone_adapter.py::LoxoneAdapter.read_telemetry` (Anlage), `ehal_live.read_ess_soc_by_id` (SoC je Batterie), `integrations/loxone_live_power.py` (Verbraucher-Zähler, EV), Wärme-/Pool-Lesungen. Details: `backlog/Binding-Walkthrough-Ist.md`.

## 6. Zielbild: Push-Only je Entität

**Quelle je Entität** (Schalter `poll | push`, Standard `poll`). Für eine Entität auf `push`:

1. Jede gebundene `sens_*`/`get_*`-Größe kommt aus der Inbox, nicht mehr aus dem Poll. Die Zuordnung Merkername ↔ qualifizierte ID liefert die Bindungsliste (`read_signals_from_docs`: `old_name` ↔ `ehal_id`).
2. **Nicht pushbar** und deshalb weiter Poll bzw. unverändert: `get_evcs_ready_by_time` (AlarmClock, `SpecialState10`), Zählerenergie über `/all` (`sens_*_energy`).
3. **Frische:** Wert gilt, wenn jünger als 3 × Wiederholintervall (90 s). Beim Start kennt die Inbox bis zu 30 s lang nichts → **Anlauffenster** (Vorschlag: bis zu 40 s auf Heartbeat warten, bevor der erste Lauf liest).
4. **Null-Regel (Vorschlag, zu bestätigen)**, nur für Größen, bei denen 0 plausibel ist:

   | Feldart | Schweigen bei lebender Verbindung | Schweigen bei toter Verbindung |
   |---|---|---|
   | Leistungen (`sens_*_power*`, `sens_power_act`, `sens_evcs_active_power`, `sens_grid_power_active`, `sens_pv_production_active`) | 0 | Lesefehler |
   | Aktivität/digital (`sens_heating_active`, `sens_filter_active`, `sens_absent_mode`, `sens_evcs_connected`) | letzter Wert gilt bis zur Flanke; nie gesendet = 0 | Lesefehler |
   | SoC, Kapazität, Grenzen (`get_*`), Temperaturen | **nicht** 0 annehmen → Lesefehler | Lesefehler |

5. **Lesefehler** verhalten sich wie heute: Pflichtfelder (`sens_ess_soc`, Netz, PV, Batterieleistung) → Lauf abbrechen und loggen (`LoxoneAdapterError`), optionale Felder werden ausgelassen. Der Dead-Man-Fallback der Loxone-Programmierung bleibt unverändert.
6. **Verbindung** = frisches wiederholendes Signal ≠ 0 (Heartbeat oder analoger Messwert). Heartbeat-VO: `Push_Earnie_Heartbeat`, Konstante ≠ 0 am Eingang.
7. **Stichprobe zur Kontrolle** auch im Push-Only-Betrieb (Vorschlag): alle 15 Minuten ein einzelner Poll nur zum Vergleich (Log bei Abweichung), nie für Entscheidungen. Sonst gibt es nach dem Umschalten keine Gegenprobe mehr.
8. **Rückbau jederzeit:** Entität wieder auf `poll`. Die Bindings (Merkernamen) bleiben erhalten.

## 7. Vorgehen entitätsweise

**Reihenfolge nach steigendem Risiko** (Zahl der Signale aus `Pilot-VO-Signalliste.csv`):

| Stufe | Entität | Signale | Risiko | Warum hier |
|---|---|---|---|---|
| 1 | Verbraucher-Zähler (`consumer.*`) | 5 | niedrig | Rückfall des Optimierers auf Sollwerte bei fehlendem Wert; nur Diagramm- und Basislast-Wirkung |
| 2 | Wärmepumpe-Leistung (`heatpump.*.sens_power_act`) | 1 | niedrig | wie Stufe 1 |
| 3 | Anlage-Rand: `sens_temperature_outside`, `sens_absent_mode`, `get_grid_export_power_limit` | 3 | niedrig–mittel | Außentemperatur speist Wärmemodelle |
| 4 | Pool und Filter (`pool.*`) | 9 | mittel | Thermik-Entscheidungen, digitale Felder |
| 5 | Wärmepumpe-Temperaturen (`heatpump.*.sens_temperature_*`) | 2 | mittel | RC-Zustand |
| 6 | E-Auto (`evcs.*`, `ev.*`) | 7 | mittel–hoch | Ladeentscheidungen für das Fahrzeug |
| 7 | Batterie Delta 3 (`ess.ecoflow_delta_3.*`) | 4 | hoch | Powerstation-Planung, SoC je Batterie |
| 8 | Batterie 15 kWh (`ess.15_kwh_speicher.*`) | 6 | hoch | Hauptspeicher |
| 9 | Anlage Netz und PV (`sens_grid_power_active`, `sens_pv_production_active`) | 2 | höchste | Pflichtfelder, Start- und Live-Zustand |

(Die Namen der Entitäten stammen aus der NAS-Alpha-Config; bei anderer Config entsprechend anpassen.)

**Ablauf je Stufe (Checkliste):**

1. **Vorbedingungen:** alle VOs der Stufe verdrahtet; Inbox zeigt für **alle** Signale der Stufe seit **mindestens 48 h** `OK` oder plausibles `0 angenommen`; Spalte „Abweichung“ gegenüber dem Poll durchgehend `gleich` (außer bekannte Totzeit); keine `Unbekannt`-Zustände; Verbindung `aktiv`; Heartbeat läuft; digitale Signale haben EIN und AUS gesetzt.
2. **Gegenprobe-Zeitraum:** Bei Stufen 7 bis 9 zusätzlich einen Neustart des Daemons testen (Werte nach ≤ 40 s wieder da) und einen Verbindungsabbruch (Miniserver kurz trennen, Verhalten laut Abschnitt 6 prüfen).
3. **Umschalten:** Entität auf `push` setzen (Ort des Schalters: siehe Abschnitt 9, Entscheidung 2); Daemon neu starten, falls der Schalter nur beim Start gelesen wird.
4. **Prüfen (30–60 min nach dem Umschalten):** Log auf Lesefehler und Abbrüche; EHAL-Com Live-Lesen (Wert-Quelle `Push` sichtbar); Sollwerte und Entscheidungen mit dem Vortag vergleichen; Stichproben-Log.
5. **Beobachten:** mindestens 24 h, bevor die nächste Stufe beginnt. Bei Stufen 7 bis 9 über einen Tag und eine Nacht (PV = 0 nachts, Batterie ruht).
6. **Rückbau, wenn eines zutrifft:** Lesefehler häufen sich, Verbindung bricht ab, Werte weichen von der Stichprobe ab, Sollwerte wirken unplausibel → Entität zurück auf `poll`, Ursache in der Inbox analysieren, **erst dann** weiter.

**Abschluss:** Wenn alle Stufen laufen, Merkernamen aus den Bindings entfernen und den generischen Lese-/Schreibpfad (2.7.n-5/-6, Feld-Registry in der Rollen-JSON) angehen. Das ist ein eigener Schritt.

## 8. Arbeitspakete (noch zu bauen)

Voraussetzung vor jeder Änderung am Lesepfad: **Charakterisierungstests** (Backlog 2.7.n-4) als Absicherung — heutiges Leseverhalten festhalten (Umrechnungen kW → W, Klammerungen, Pflicht-/optionale Felder, Fehlerfälle). Tests immer über `.venv\Scripts\python.exe -m scripts.run_pytest …`.

| WP | Inhalt | Dateien / Hinweise |
|---|---|---|
| WP1 | **Lese-API der Inbox im Daemon:** `read_push_value(ehal_id)` → (Wert, Zustand) mit In-Process-Cache (Listener und Lesepfad laufen im selben Prozess `main.py`; die JSON-Datei ist nur für die UI) | `runtime_store/loxone_push_inbox.py` |
| WP2 | **Quellen-Schalter je Entität** (`poll`/`push`), Standard `poll`; Zuordnung Entität → IDs; Merkername → ID-Umkehrliste | neue kleine Konfig-Schicht; Ort siehe Abschnitt 9 |
| WP3 | **Vorschaltung im Lesepfad**: für Entitäten auf `push` Wert aus WP1 statt HTTP; **keine** Änderung an Adaptern, wenn die Umkehrliste an `fetch_loxone_generic_value` greift | `integrations/loxone_client.py`; AlarmClock- und `/all`-Reads ausnehmen |
| WP4 | **Null-Regel je Feldart** (Tabelle Abschnitt 6) + Tests je Zeile; Lesefehler-Semantik (Pflichtfeld → Abbruch) | neue reine Funktion neben `derive_state`; Tests wie `test_loxone_push_inbox.py` |
| WP5 | **Anlauffenster und Verbindung:** vor dem ersten Lauf auf Heartbeat warten (Obergrenze), Loglinien bei Verbindungsverlust, Status in EHAL-Com | `main.py`-Schleife, `ui/loxone_push_inbox_ui.py` |
| WP6 | **Stichproben-Vergleich** (Poll nur zum Vergleich, Log) | Lese-Schicht + Log |
| WP7 | **EHAL-Com:** je Entität Quelle anzeigen und (später) umschalten; Live-Lesen zeigt „Quelle: Push/Poll“ | `ui/loxone_debug*.py`, Mapping-Seiten |
| WP8 | **Doku:** `docs/ui/ehal-com.md`, `docs/referenz/loxone-signals.md` (deutsch, `german-user-docs.mdc`); Backlog: eigener Punkt für den Push-Only-Lesepfad (kein Teil des Epic-Phasen-Schemas, Folgeaufgabe = eigener Punkt); Epic-Phasen in `roadmap-nomenclature.mdc` falls nötig | siehe Regeln in `CLAUDE.md` |
| WP9 | **Auslieferung:** Container aus dem Branch bauen, auf NAS Alpha ausrollen; Fix-Branch vorher oder gleichzeitig mergen (sonst bleibt der `status.json`-Überschreib-Effekt) | Pre-commit-Hook läuft die volle Suite (7–8 min), Version nur nach Freigabe ändern |

## 9. Offene Entscheidungen (vor dem Bau klären)

1. **Null-Regel bestätigen** (Tabelle Abschnitt 6, vor allem: dürfen Temperaturen und Grenzen bei Schweigen als Lesefehler gelten?).
2. **Wo steht der Quellen-Schalter?** Vorschlag: `config.json` → `ehal.loxone_push.entities` (Liste von Entitäten-IDs, z. B. `plant`, `battery:ecoflow_delta_3`, `consumer:trockner`), später per Schalter in EHAL-Com. Alternative: `runtime/local_settings.json` (ohne Neustart änderbar, aber nicht versionierbar).
3. **Push-Only wirklich ohne jeden Rückfall?** Bei Pflichtfeldern (SoC, Netz, PV, Batterieleistung) bricht der Lauf bei Schweigen ab. Alternative: letzter bekannter Wert bis N Minuten. Der Wunsch war Push-Only; die Sicherheitsnetze (Dead-Man in Loxone, Abbruch bei Lesefehler) sind der Ersatz.
4. **Stichprobe** im Push-Only-Betrieb: ja/nein, Intervall.
5. **Anlauffenster:** Obergrenze (Vorschlag 40 s) und Verhalten danach.
6. **Fix-Branch** zuerst mergen? Und wie die zwei Branches (`054ab475`, `b5a658d2`) in `main` zusammengeführt werden.
7. **Digitale Befehle:** Prüfen, ob Config den Befehl bei AUS aus der Vorlage übernommen hat (sonst nachtragen).

8. **Token in der Adresse statt in jedem Befehl** (`--token-in-address`, Empfänger kann es, siehe `integrations/loxone_request_http.py::split_token_prefix`): **erst prüfen, ob Loxone Adresse und Befehl so zusammensetzt.** Test mit dem Capture-Skript: `python -m scripts.pilot_vo_capture --port 8599`, ein VO mit Adresse `http://<PC-IP>:8599/t/abc` und Befehl `/ehal/loxone/telemetry/sens_ess_soc/<v>`; im Capture muss `/t/abc/ehal/loxone/telemetry/sens_ess_soc/<Wert>` ankommen. Kommt der Pfadanteil der Adresse nicht mit, bleibt `?t=` im Befehl (weiterhin unterstützt).

## 10. Risiken

- **Totzeit bei Abfall auf 0:** analoge Signale (Wallbox, Batterie ruht, PV nachts) werden erst nach 90 s als 0 erkannt; der Optimierer sieht bis dahin den letzten Wert. Verkürzbar (Faktor < 3), auf Kosten falscher Nullen bei verspäteten Wiederholungen.
- **Loud-Modus:** Fehler im Lesepfad wirken auf echte Sollwerte. Deshalb Charakterisierungstests zuerst, kleine Stufen, Rückbau je Entität.
- **Miniserver-Last:** 40 Befehle × 30 s ≈ 1,3 Anfragen/s dauerhaft; Langzeitverhalten nicht gemessen.
- **Daemon-Neustart:** Werte fehlen bis zu 30 s; deshalb Anlauffenster.
- **Token:** Er liegt im Klartext in den VO-Vorlagen und im Config-Programm (nur LAN). **Das aktuelle Pilot-Token ist kompromittiert**: Es steht im Chat und (als Testwert) im Commit `054ab475` auf `spike/vo-push-pilot`. Im Pilot ist das unkritisch (reine Beobachtung); **vor dem Push-Only-Betrieb muss es ersetzt werden**, denn dann kann jeder im LAN mit dem Token Werte in die Optimierung einspeisen. Neues Token in der `.env` der Instanz setzen, Vorlagen neu erzeugen (`--env-file`) und in Config austauschen — mit `--token-in-address` nur in den 8 VO-Geräte-Adressen statt in allen 40 Befehlen (siehe Abschnitt 9, Entscheidung 8). Den Branch **nicht pushen**, solange `054ab475` unverändert drinsteckt (oder die Historie vorher bereinigen). Nie ein echtes Token in Tests oder Doku schreiben.
- **Digitale Signale:** EIN-Wiederholung nicht verifiziert; AUS nur als Flanke.

## 11. Arbeitshinweise für den neuen Chat

- Projektregeln: `CLAUDE.md` und `.cursor/rules/*.mdc`; Chat auf Deutsch, Backlog/Specs auf Englisch, Nutzerdoku deutsch. `version.py` nie ohne ausdrückliche Freigabe ändern.
- Tests immer über den Wrapper (`scripts.run_pytest`), UTF-8-Umgebung setzen. Der Pre-commit-Hook läuft die volle Suite in 7–8 Minuten: im Hintergrund committen; im Worktree den Pfad des vorhandenen venv voranstellen.
- Fixes auf `main` in einem **Worktree** vorbereiten (`git worktree add ../<Name> -b <Branch> main`), nicht im Pilot-Branch.
- **Nie `git stash pop` ohne vorheriges `stash push`** (im Repo liegt ein alter Stash).
- In Shell-Here-Docs werden doppelte Backslashes verkürzt (`\\` → `\`): Sonderzeichen per `chr(92)` bauen oder die Datei mit dem Schreib-Werkzeug anlegen und ausführen.
- Template-Generator (Beispiel, Platzhalter-Token):
  `python -m scripts.pilot_vo_template_gen --config-dir <earnie_env\config> --host <Earnie-IP> --port 8541 --out-dir <Ordner>` (mit `--env-file <.env>` wird das echte Token eingesetzt; Ausgabe nicht committen).
- Zugriffe auf die NAS-Freigabe der Alpha-Instanz (Inbox, Log, Config) erfolgten bisher **nur lesend**; der Miniserver selbst wurde von Claude nie angesprochen. Einen Abruf von `status.json` vermeiden: er überschreibt die Anzeige „Letzter Aufruf vom Miniserver“.
- Die Datei `capture.jsonl` im Repo-Stamm ist eine Pilot-Aufzeichnung (nicht committen); sie darf gelöscht werden.
