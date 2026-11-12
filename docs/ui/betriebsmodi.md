# Betriebsmodi und Navigation

Die Streamlit-App ordnet ihre Seiten über **`st.navigation`** in Abschnitte. Welche Seiten sichtbar sind, steuert die Umgebungsvariable **`EARNIE_UI_MODES`**.

```text
EARNIE_UI_MODES=sunset2sunset,scenario_explorer,live_environment
```

Ohne diese Variable stehen in der Entwicklung **Sunset-2-Sunset** (Seite **Monitor**), **Szenario-Explorer** und **Daemon Control** zur Verfügung, optional auch **Preis-Prognose (Dev)**.

- **Gültige Keys:** `sunset2sunset`, `scenario_explorer`, `live_environment` und `price_forecast`. Die Aliase `live` und `historical` gibt es nicht.
- **Umbenannte Keys:** Die früheren Keys `backtesting` und `scenario_exploration` heißen inzwischen anders. Bei einer alten Env-Konfiguration erscheint ein Hinweis in der Sidebar.

Details zum Deployment: [Betrieb](../einrichtung/betrieb.md).

| Key | Seite | Abschnitt | Produktivbetrieb |
|-----|-------|-----------|------------------|
| `sunset2sunset` | **Monitor**, **Manuelle Geräte** | Live-Cockpit | ja (Hauptansicht; ohne Key kein Abschnitt Live-Cockpit) |
| `scenario_explorer` | **Szenario-Explorer** | Konfiguration | optional (Entwicklung / Community Cloud) |
| `live_environment` | **Smarthome-Backend**, **EHAL-Com**, **Optimierer-Dienst**, **Analyse Verbrauch & Kosten** (Live-Cockpit) | Daemon Control / Live-Cockpit | ja (ohne Key kein Live- und Daemon-Anteil) |
| `price_forecast` | **Preis-Prognose (Dev)** | Live-Cockpit | nur Entwicklung |

Beispiel Community Cloud (nur Szenario-Explorer): `EARNIE_UI_MODES=scenario_explorer`. Live-Cockpit und Daemon Control entfallen dann.

Einige Seiten hängen nicht von `EARNIE_UI_MODES` ab:

- **Hauskonfigurator** und **Szenarienkonfigurator:** Sie werden je nach Fortschritt der Einrichtung freigeschaltet (`ui/setup_readiness.py`).
- **Analyse Verbrauch & Kosten:** Die Seite erscheint nur mit `live_environment` und nur im Abschnitt Live-Cockpit. Ohne Live-Verbindung zur Smarthome-Steuerung zeigt sie einen Hinweis statt der Analyse. Die Analyse nutzt rollierende **7-/28-Tage**-Charts (keine Kalenderwochen) und eine Kennzahl über die letzten **365 Tage** vorhandener Log-Daten.

Die Sidebar enthält oben Setup-Hinweise und **„Sichern & Übertragen“**. Dort liegen der Export und Import der Config-Sidecars und `uploads/` als ZIP (siehe [Speichern / Laden](../konfiguration/speichern-laden.md)) und das Support-Paket (siehe [Betrieb → Support-Paket](../einrichtung/betrieb.md#support-paket-debug-dump)).

Unten in der Sidebar liegt der Abschnitt **Info / About** mit folgenden Inhalten:

- Banner der Wahrheit und Version.
- Kontakt über ein **GitHub-Issue** mit Art, Thema und Beschreibung; ein lokales ZIP für den Support erstellt **Sichern & Übertragen → Support-Paket**.
- Privater Ausnahmekanal `support@earnie-hems.com` für Registry-Anfragen und vertrauliche Inhalte.

### Navigationsabschnitte (nach vollständiger Einrichtung)

| Abschnitt | Seiten |
|-----------|--------|
| **Live-Cockpit** | Monitor, Manuelle Geräte, Analyse Verbrauch & Kosten (bei `live_environment`), Preis-Prognose (Dev) |
| **Konfiguration** | Hauskonfigurator, Szenarienkonfigurator, Szenario-Explorer (wenn freigeschaltet) |
| **Daemon Control** | Smarthome-Backend, EHAL-Com, Optimierer-Dienst |

**Optimierer-Dienst:** Die Seite bietet Start, Stopp und Neustart, das Dienst-Log und den Umschalter **Silent / Loud** (`silent_mode` in `runtime/local_settings.json`). Für den Umschalter ist kein Neustart von `main.py` nötig. Details: [Betrieb](../einrichtung/betrieb.md) · Schreibverhalten: [EHAL-Com](ehal-com.md).

Während der Ersteinrichtung (Greenfield) sind zunächst nur **Konfiguration** und **Daemon Control** sichtbar. Die Daemon-Seiten erscheinen dabei auch dann, wenn `live_environment` in der Env fehlt. Solange kein Smarthome-Backend gewählt ist, zeigt Daemon Control nur **Smarthome-Backend**. Optimierer-Dienst und EHAL-Com erscheinen erst danach.

Chart- und Panel-Details: [Charts & Panels](charts.md).

## Sunset-2-Sunset (Seite Monitor)

**Zweck:** Der Monitor ist ein einheitliches Produktiv-Cockpit ohne Grenze zwischen Live und Historie.

- **Vergangenheit:** aus dem Produktiv-Log (`optimization_history.jsonl`).
- **Gegenwart und Vorausschau:** aus dem **Produktiv-Snapshot** (`live_optimization_debug.json`), den `main.py` schreibt.
- **Darstellung:** Am Desktop zeigt die Seite ein Fenster SA₀→SA₂, mobil zwei benachbarte Segmente von Sonnenaufgang zu Sonnenaufgang.

**Abwesenheitsmodus:** Ist der wirksame Live-Abwesenheitsmodus aktiv, zeigt die Seite unter dem Titel den Hinweis „Abwesenheitsmodus aktiv“, optional mit der Quelle Earnie, Smarthome oder beide. Auslöser ist der Schalter im Hausprofil **oder** das Anlagen-Feld `sens_absent_mode` am aktiven Backend (Loxone-Merker, HA-Entity oder OpenEMS `component/Channel`). Konfiguration: [Flexible Verbraucher](../konfiguration/flexible-verbraucher.md#abwesenheitsmodus-live).

**Leistungspreis:** Hat das Live-Szenario eine **Bezugsgrenze** oder der Netzbereich im laufenden Monat einen **Leistungspreis**, zeigt die Seite unter dem Titel den Abschnitt „Leistungspreis“:

- **Monatsspitze** (höchste gemessene Viertelstunde des Netzbezugs), **Abgerechnet** (Spitze, mindestens die Mindestleistung des Netzbereichs), **Bisher (brutto)** (Betrag des Monats mit der USt des Bezugstarifs) und **Nächstes kW** (was ein kW mehr Spitze diesen Monat kostet). Darunter stehen Messbeginn, Zeitpunkt der Spitze und fehlende Viertelstunden. Ist im Monat noch keine Viertelstunde gemessen, steht „unbekannt“ statt 0 und beim Betrag der Mindestbetrag. Earnie misst selbst; maßgeblich ist die Abrechnung des Netzbetreibers.
- Mit Bezugsgrenze: Grenze, Reserve und bis wohin geplant wird. Liegt die Spitze schon darüber, plant Earnie bis zur Spitze.
- **Warnung**, wenn der letzte Plan die Grenze in Viertelstunden nicht halten kann: Anzahl, erste Viertelstunde und häufigste Ursache (Grundlast, Batterie oder Wechselrichter an der Leistungsgrenze, Batterie leer oder Reserve, Verbraucher muss sein Ziel erreichen, keine Ursache erkannt). Gemessene Viertelstunden über der Grenze nennt eine Zeile darunter, mit „Lastprognose“, wenn der Plan die Grenze hielt. Einzelheiten stehen im aufklappbaren Bereich „Details zur Bezugsgrenze“.
- **Hinweise:** Grenze unter der Mindestleistung des Netzbereichs (Earnie plant trotzdem mit der eingegebenen Grenze), Grenze inaktiv bis zum Beginn des Leistungspreises, oder der letzte Zyklus hat die Grenze nicht eingeplant (Automatikbetrieb oder Fenster ohne Optimierung).
- **Beobachtungsmodus** (Bezugsgrenze mit „Im Live-Betrieb: Beobachten“): Ein Hinweis sagt, dass Earnie ohne die Grenze plant und steuert. Die Zahlen oben bleiben die gemessenen. Eine zweite Zeile vergleicht die Viertelstunden seit Beginn der Beobachtung: **Spitze ohne Earnie** (höchste gemessene Viertelstunde in dieser Zeit), **Spitze mit Earnie** (geschätzte Spitze derselben Viertelstunden, wenn Earnie die Grenze eingehalten hätte), **Ersparnis (geschätzt)** (Leistungspreis bei der Spitze ohne Earnie minus Leistungspreis bei der Spitze mit Earnie) und **Mehrkosten Energie** (was das Einhalten der Grenze im aktuellen Plan über den Planungshorizont an Strom mehr kostet, keine Monatssumme). Geschätzt wird je Viertelstunde: gemessener Bezug plus die Änderung, die ein zweiter Plan mit Grenze vorgesehen hätte. Dieser Vergleichsplan startet jedes Mal vom tatsächlichen Zustand von Batterie und Verbrauchern, die Werte sind also eine Schätzung. Darunter stehen der Beginn der Beobachtung und die Viertelstunden ohne Vergleich (Automatik, Modus gerade umgestellt); sie zählen in keiner der beiden Spitzen. Ist die Lastprognose einer Viertelstunde weit daneben, ist es auch die Schätzung. Die Warnung bezieht sich auf den Vergleichsplan, und die Zeile über der Grenze nennt die geschätzten Viertelstunden. Unter „Details zur Bezugsgrenze“ zeigt die Tabelle **Wo Earnie eingegriffen hätte** je Viertelstunde den gemessenen und den geschätzten Bezug, die Batterie ohne und mit Grenze und geänderte Verbraucher.
- Lässt sich der Abschnitt nicht berechnen, etwa weil dem Netzbereich für den Monat ein Leistungspreis fehlt oder dem Live-Szenario mit Bezugsgrenze die Wahl „Im Live-Betrieb“ fehlt, zeigt er den Fehler; der Rest der Seite bleibt bedienbar.

Eine **Nachrechnung** beliebiger Kalendertage bietet der Monitor nicht.

### Sonnenaufgang-Anker SA₀, SA₁, SA₂

Die Anker liegen immer auf dem **Sonnenaufgang**, nie auf dem Sonnenuntergang:

| Situation | SA₀ | SA₁ | SA₂ |
|-----------|-----|-----|-----|
| Gerade in der SA-Stunde | **jetzt** | morgen | übermorgen |
| Jede andere Stunde | letzter SA (Vergangenheit) | nächster SA | übernächster SA |

### Chart-Fenster & Navigation

**Desktop / Tablet:** Das sichtbare Fenster reicht von **SA₀ bis SA₂** (etwa 48 h). Die Pfeile ← und → verschieben es um einen Sonnenaufgang-Zyklus; in der Live-Ansicht ist → deaktiviert.

**Mobil:** Zwei umschaltbare Segmente mit je etwa 24 h:

| Index | Fenster | Standard |
|-------|---------|----------|
| 0 | SA₀ → SA₁ | ja (App-Start) |
| 1 | SA₁ → SA₂ | per „Vor →“ |

| Steuerung | Verhalten |
|-----------|-----------|
| ← Zurück | Weitere SA-Zyklen zurück, soweit `optimization_history.jsonl` reicht |
| Vor → | Desktop: Zyklus Richtung Live (in der Live-Ansicht deaktiviert). Mobil: Wechsel zwischen SA₀→SA₁ und SA₁→SA₂ bzw. Zyklus Richtung Live |
| Navigation | Kompakte Buttons **zwischen Chart 1 und Sankey** (Chart 2 folgt darunter) |

Die Beschriftung lautet z. B. „SA₀→SA₂ (Live)“ am Desktop bzw. „SA₀→SA₁ (Live)“ / „SA₁→SA₂ (Vorausschau)“ mobil, jeweils mit Datumsbereich. Vertikale Marker **SA₀**, **SA₁** und **SA₂** gliedern das Chart. Der Marker **Jetzt** erscheint, sobald die aktuelle Zeit im sichtbaren Fenster liegt.

### Datenquellen

| Bereich | Quelle |
|---------|--------|
| Vergangenheit (grau) | Produktiv-Log, 15-Min-Slots |
| Laufende Stunde | Produktiv-Snapshot Stunde 0 (Overlay bereits in `main.py` angewendet; Auflösung ab x:15: 15 min) |
| Vorausschau (neutral/grün) | Produktiv-Snapshot bis zum Fensterrand SA₁ bzw. SA₂ |

Stunde 0 stammt aus dem **Produktiv-Durchlauf** (`main.py` → `live_optimization_debug.json`). Fehlende Log-Slots bleiben **leer** und sind orange markiert; der letzte Wert wird nicht fortgeschrieben.

**Wenn `main.py` nicht läuft:** Ist der Snapshot höchstens 1 h alt, zeigt die Seite ihn mit einem Hinweis an. Bei älteren Snapshots ist optional eine **einmalige** UI-Simulation möglich (opt-in, im Normalbetrieb ohne forecast.solar).

### Live-Szenario (Entitäts-Referenzen)

Die Parameter für PV, Batterie und Einspeisung kommen über Entitäts-IDs aus dem **Live-Szenario**. Es liegt in `backtesting_scenarios.json` und wird über `live_scenario_id` in `config.json` gewählt; bearbeitet wird es auf der Seite **Szenarienkonfigurator**. Ein adaptives PV-Tuning gibt es nicht mehr.

### Panels

| Panel | Verhalten |
|-------|-----------|
| Charts 1 & 2 | Leistung, SoC und Preis; kumulierte Kosten und Verbrauch (Ist und Prognose getrennt) |
| Sankey | Liegt **zwischen Navigation und Chart 2**. Zeigt die Anlagenleistungen (PV, Netz, Batterie) über das aktive EHAL-Backend; Flex-Knoten und EV-SoC-Label gibt es derzeit nur mit Loxone (siehe [Charts](charts.md#energiefluss-live-sankey)) |
| Simulations-Tabelle | Rohdaten des sichtbaren Fensters; orange = fehlende Log-Einträge |
| Energievergleich | Expander: Baseline gegen Optimierung |
| Countdown / Optimierungs-Takt | immer sichtbar |
| Auto-Refresh | Desktop: Live-Zyklus (`cycle_offset=0`); mobil: nur im Fenster SA₀→SA₁ |

Details: [Charts & Panels](charts.md).

### Kennzahlen-Horizont

**Chart 2** ist eine Kontoansicht: Kontostand mit und ohne Earnie seit Fensterstart, links von Jetzt gebucht aus dem Ersparnis-Buch, rechts der Plan. Ein Umschalter wählt **Ist bei Jetzt** oder **Gemeinsamer Start**; der Abstand zwischen den Linien ist die Ersparnis (**Bisher**, **Erwartet**, **Gesamt**). Abgeschlossene Tage zeigen ihr **Ergebnis** aus dem Buch. Details: [Charts](charts.md#chart-2-kontostand-mit-und-ohne-earnie).

Der **Energievergleich** und das MILP-Matching beziehen sich weiterhin auf **Jetzt → SA₂**, also den vollen Planungshorizont. Die Chart-Fenster dienen nur der Darstellung: Kumulierte Kurven darin sind Ausschnitte und bilden keine eigene Matching-Periode.

## Szenario-Explorer

**Zweck:** Langzeit-Auswertung aus dem Log von `scripts/run_backtesting.py` (`runtime/backtesting_log.json`).

Die Seite hat **keine Cockpit-Parameter**. In der Hauptansicht werden nur Szenarien und Monate ausgewählt.

**Inhalt:**

- **Kostenvergleich:** Gesamt- und Monatskosten, Referenz gegen optimierte Szenarien.
- **Plausibilisierung:** Plausibilitätsprüfung und Stundenverläufe pro Monat.
- **Season-Mirror (optional):** Mit `scenario_explorer_conf.season_mirror_to_last_month` werden Verbrauch und PV nach Kalendermonat auf die letzten 12 vollständigen Wanduhr-Monate gespiegelt. Die CSV bleibt unverändert; so gelten die aktuellen Tarife.
- **Szenarioauswahl:** Nur Szenarien mit `enabled` (Standard true) aus dem Szenarienkonfigurator erscheinen. Der Start der Verbrauchsdaten wird nur bei passendem Synthese-Fingerprint übernommen.

Der Szenario-Explorer hat keine Sonnenaufgang-Navigation wie der Monitor und führt das Produktiv-Log nicht mit ein. Für den täglichen Produktivbetrieb ist er nicht gedacht.

> **Hinweis zur Neuoptimierung:** Der Szenario-Explorer steuert die MILP-Commit-Weite über `commit_hours` in `backtesting_scenarios.json`. Der Standard **24** entspricht ungefähr einer Planung ohne Rückkopplung (open-loop), **1** bedeutet stündliche Neuoptimierung. Das ist nicht dasselbe wie die periodische Neuoptimierung im Live-Betrieb; eine 1:1-Übereinstimmung mit der Live-Optimierung (MPC) ist nicht nachgewiesen. `commit_hours: 1` unterstützt nur **eine** Hausbatterie; mit mehreren Hausbatterien bricht der Lauf mit einer Fehlermeldung ab, dann `commit_hours` größer als 1 verwenden.
>
> Standard-Horizont ist `sunrise_window`: Das MILP rechnet SA₀→SA₂, gebucht wird jeweils **[SA₁, SA₂)**. SA₂ ist der Sonnenaufgang am `ready_by`-Tag, SA₁ der des Vortags. Die Buchungsfenster schließen damit lückenlos und ohne Doppelbuchung aneinander, auch wenn die Sonne erst nach `ready_by` aufgeht. `ready_by` ist nur die Lade-Deadline des E-Autos; die Ladenacht davor liegt im selben Buchungsfenster. Alle flexiblen Verbraucher laufen nur innerhalb des Buchungsfensters. Der SoC wird an den Sonnenaufgang-Übergängen verkettet. `fixed_24h` bleibt als Vergleichsmodus erhalten (an `ready_by` ausgerichtete 24-h-Fenster).

### Ersparnis gegen Standard-Regeln

Ganz oben in den Ergebnissen steht je Szenario, was Earnie über Batterie und freie Regeln hinaus bringt: die Kosten mit **Standard-Regeln** minus die Kosten mit Earnie. Darunter steht der **Anteil der Regeln**: (Ohne Steuerung − Standard-Regeln) / (Ohne Steuerung − Earnie). Er sagt, wie viel der gesamten Ersparnis man auch ohne Earnie erreicht. Spart Earnie gegen „Ohne Steuerung“ nichts, steht dort „keine Gesamtersparnis“.

Der Bereich **Alle Stufen** zeigt die ganze Leiter. Jede Stufe ergänzt genau eine Sache:

| Stufe | Batterie | Flexible Verbraucher | Vorbild |
|---|---|---|---|
| **Ohne Steuerung** | keine | zu ihren üblichen Zeiten | die frühere Referenz ohne Optimierung |
| **Wechselrichter-Eigenverbrauch** | Eigenverbrauchsmodus des Wechselrichters | zu ihren üblichen Zeiten | was der Wechselrichter von sich aus tut |
| **Standard-Regeln** | Eigenverbrauchsmodus des Wechselrichters | lokale Regeln | E-Auto: PV-Überschussladen wie evcc, mit Zielladung. Heizung und Pool: SG-Ready-Sperre bei hohen Preisen und Anhebung bei Überschuss. Geräte mit Startfenster: „günstigste Stunden“ wie in Home Assistant. Bei negativem Einspeisepreis wird nicht eingespeist, überschüssige PV-Leistung wird abgeregelt |
| **Earnie** | MILP-Plan | MILP-Plan | der optimierte Lauf des Szenarios |

Die Regeln sind großzügig angesetzt: Sie sehen den Überschuss am Zähler und die veröffentlichten Day-Ahead-Preise, wissen aber nichts von anderen Verbrauchern und vom Ladestand der Batterie. Alle Stufen liefern dieselbe Energie, buchen dieselben Preise und halten dieselben Ladefenster ein.

**Warum die Ersparnis kleiner ist als früher:** Bisher verglich der Szenario-Explorer nur mit einer Anlage ohne Batterie und ohne jede Regel. Die Ersparnis schrieb Earnie damit auch das zu, was der Wechselrichter und kostenlose Regeln ohnehin leisten. Die neue Zahl ist kleiner, weil die Methode strenger ist. Die Optimierung rechnet nicht schlechter, und die frühere Vergleichszeile bleibt als „Ohne Steuerung“ erhalten.

**Grenzen:** Earnie plant im Szenario-Explorer mit bekannten PV-, Last- und Preisverläufen, die Ersparnis ist also eine Obergrenze. Läufe von vor dieser Auswertung zeigen einen Hinweis, bis sie neu berechnet sind.

### Gesamtkosten und -Verbrauch

Die Tabelle **Gesamtkosten und -Verbrauch** hat die Spalten `Szenario`, `Jahres Verbrauch [kWh]`, `Speicher-Standby [kWh]`, `Gesamtverbrauch [kWh]` (= Jahres Verbrauch + Speicher-Standby), `CO2 [kg]`, `Jahres Kosten [€]`, `Ersparnis vs. Standard-Regeln [€]`, `Δ vs Referenz [€]` und `Hinweis`. Das Delta bezieht sich immer auf die Zeile der Live-Referenz.

Je Szenario kommen zwei Referenzzeilen dazu. **Wechselrichter-Eigenverbrauch** rechnet die Batterie im Eigenverbrauchsmodus des Wechselrichters, die flexiblen Verbraucher laufen zu ihren üblichen Zeiten. **Standard-Regeln** ergänzt freie Regeln: PV-Überschussladen, SG-Ready-Sperre bei hohen Preisen und „günstigste Stunden“ für Geräte mit Startfenster sowie einen Heizstab neben einer Brennstoffheizung, der mit seiner Nennleistung läuft, sobald nach Verbrauchern und Batterie so viel eingespeist würde und der Wärmebedarf des Tages es zulässt. Die Wärme des Heizstabs spart Brennstoff. Beide Zeilen liefern je Fenster und Verbraucher dieselbe Energie wie die Optimierung. Ein Heizstab hat kein Energieziel: In **Wechselrichter-Eigenverbrauch** läuft er nicht. Szenarien mit gleichem Haus, Speicher, Tarif und gleichen Verbrauchern teilen sich diese Zeilen.

`Ersparnis vs. Standard-Regeln [€]` ist die Zeile **Standard-Regeln** des Szenarios minus seine optimierten Kosten, also das, was Earnie über freie Regeln hinaus bringt. Der Betrag steht ohne Vorzeichen, mit „gespart“ oder „mehr ausgegeben“ dabei; so auch die Kennzahl oben und die Spalte „Ersparnis zur Stufe davor“ in „Alle Stufen“. `Δ vs Referenz [€]` und der Ladestand am Periodenende behalten ihr Vorzeichen, weil sie Unterschiede sind. Dieser Wert ist kleiner als die Ersparnis gegen die Referenz ohne Optimierung. Das ist Absicht und kein Rückschritt: Die Batterie und einfache Regeln hätte man auch ohne Earnie. Earnie plant im Szenario-Explorer mit bekannten PV-, Last- und Preisverläufen, der Wert ist deshalb eine Obergrenze.

Die Spalte bewertet auch den Ladestand der Batterie am Periodenende. Endet Earnie voller als die Standard-Regeln, wird die zusätzlich gespeicherte Energie gutgeschrieben, endet es leerer, wird sie abgezogen. Bewertet wird sie wie im Ersparnis-Buch: Energie × Wirkungsgrad × mittlerer Bezugspreis des letzten Tages. Die Spalte `Hinweis` nennt den Betrag und beide Ladestände. Bei kurzen Zeiträumen kann das viel ausmachen, bei einem Jahr kaum. `Jahres Kosten [€]` bleibt der gebuchte Betrag ohne diese Bewertung.

In der **Abweichungsliste** vergleichen die Charts eines Fensters ebenfalls mit den Standard-Regeln. Chart 2 zeigt als Kontoansicht den Kontostand beider Läufe seit Fensterstart (gebuchte Kosten je Slot, beide beginnen bei 0 €); der Abstand am Fensterende ist die Ersparnis des Fensters (**Plan**) und passt zur Tabelle (ohne die Bewertung des Ladestands). Chart 1 zeigt weiter den Plan dieses Fensters, dazu Ladestand und flexible Verbraucher der Standard-Regeln. Den Abschnitt SA₀→SA₁ hat das Vorfenster gebucht, dort können Chart 1 und Chart 2 voneinander abweichen. Slots außerhalb des Zeitraums zählen nicht mit, der Text unter den Charts nennt sie. Ältere Läufe ohne Standard-Regeln zeigen wie bisher **BL Ziel**.

Enden die Börsenpreise vor dem Tag nach dem Zeitraum (zum Beispiel bei einem Lauf bis heute vor der Preisveröffentlichung), rechnet die Preissperre am letzten Nachmittag mit den vorhandenen Preisen. Die Spalte `Hinweis` nennt dann die betroffenen Stunden.

Heizt ein Hausprofil mit einem Brennstoff (Öl, Gas, Pellets, Fernwärme, Stückholz, siehe [Wärmequelle](../konfiguration/flexible-verbraucher.md#haus-wärme-wärmequelle-heat_source)), kommen die Spalten `Brennstoff [kWh]` und `Brennstoffkosten [€]` dazu. `Jahres Kosten [€]` enthält dann Strom **und** Brennstoff. Den Brennstoff rechnet Earnie aus der Jahressimulation über die gebuchten Tage; die Wärme eines Heizstabs zieht er davon ab. `CO2 [kg]` = Netzbezug × 226 g/kWh plus Brennstoff × Faktor des Energieträgers. Das gilt für alle Stufen der Leiter: `Ersparnis vs. Standard-Regeln [€]` vergleicht also Strom und Brennstoff, und ein Heizstab zählt mit seinem Mehrstrom und dem gesparten Brennstoff. Dieselben Zahlen liefert der Studienexport `scripts.run_reference_ladder` als CSV, dort je Stufe auch Bezug, Einspeisung, Brennstoff, Heizstab und Batterie-Durchsatz in kWh.

Der volumetrische **Netznutzung Arbeitspreis** (je Netzgebiet aus `grid_fees.json`) fließt in die Kosten des Szenario-Explorers ein. Trägt der Netzbereich einen **Leistungspreis**, weist die Seite ihn in einer eigenen Tabelle aus und rechnet ihn in die Kosten ein. Die Planung kennt den Preis selbst nicht, die SE-Optimierung plant aber unter einer eingetragenen **Bezugsgrenze**. Die Tabelle zeigt dann die Grenze, die gebuchten Viertelstunden darüber, die Tage mit mindestens einer solchen Viertelstunde und die **Hauptursachen** mit der Zahl ihrer Viertelstunden. Die Ursache kommt aus dem Plan des Fensters, wie in der Warnung auf der Monitor-Seite (Grundlast, Batterie oder Wechselrichter an der Leistungsgrenze, Batterie leer oder Reserve, Verbraucher muss sein Ziel erreichen, keine Ursache erkannt, Grenze nicht eingeplant). Dazu kommen zwei Ursachen nur im Szenario-Explorer: „Monatsspitze schon höher, Grenze angehoben“, wenn der Plan seine Grenze hielt, diese aber nach einer früheren Spitze des Monats über der eingetragenen lag, und „Gebucht über dem Plan“, wenn die gebuchte Viertelstunde über dem lag, was der Plan erlaubte. Die Vergleichsstufen L0 bis L2 planen ohne Grenze. Eine einmal überschrittene Grenze steigt für den Rest des Monats auf die neue Spitze, deshalb kann ein einziger Ausreißer viele Viertelstunden über der Grenze nach sich ziehen. Nachrechnen: [Tarife und Preise nachrechnen](../referenz/tarife-quellen.md).

**Datenquelle für `Jahres Verbrauch [kWh]` und `Speicher-Standby [kWh]`:** Alle Zeilen (Historisch, Szenario-Referenzen `ref:…`, optimierte Szenarien) lesen dieselbe Quelle `booked_consumption[<id>]` in `backtesting_log.json`. Das ist die Summe der gebuchten Stundenreihe aus `backtesting.csv`, also der Reihe, die auch Kosten, Bezug und Einspeisung trägt.

| Feld | Bedeutung |
| ---- | --------- |
| `consumption_kwh` | Σ `consumption_kw` × Slotdauer über den Zeitraum; jeder Zeitslot zählt einmal, ohne Speicher-Standby |
| `standby_kwh` | Standby-Leistung der Hausbatterie (`standby_power_kw`) über alle gebuchten Slots; bei optimierten Szenarien und ihren Referenzen, nicht bei Historisch |
| `duplicate_slots` | Zeitslots, die mehrere Fenster gebucht haben (einmal gezählt) |
| `gap_slots` | Zeitslots zwischen erstem und letztem gebuchten Slot, die kein Fenster gebucht hat |
| `reference_coverage` | Zeitslots, die nur das Szenario bzw. nur seine Referenz rechnet |
| `components_kwh` | Aufteilung je Verbraucherspalte (Grundlast ohne Standby, `other` = known-Verbraucher) |

Der Speicher-Standby steckt in der Verbrauch-Prognose der Optimierung und in der Last der Referenzen (die den Speicher des Szenarios behalten, nur ohne Optimierung) und damit in Bezug und Kosten. Historisch (ohne PV und Speicher) hat keinen. Als Hausverbrauch zählt er nicht, deshalb steht er in einer eigenen Spalte. Die Zeile Historisch rechnet die Last des Live-Hausprofils ohne PV und Batterie; der Ist-Zähler `cons_data` geht nicht mehr direkt in die Spalte ein.

Das erste und das letzte Sonnenaufgangs-Fenster ragen über den Zeitraum hinaus (SA₁ liegt vor dem Starttag, SA₂ nach dem Endtag). Gebucht wird dort nur der Teil **innerhalb** des Zeitraums; Verbraucher-Ziele und Ladefenster der beiden Randfenster folgen diesem Ausschnitt. So verschiebt der Optimierer keine Energie über die Periodengrenze (z. B. E-Auto-Ladung vom Vorabend in die Nacht des Starttags), und der Jahresverbrauch stimmt mit Historisch bis auf den Standby überein.

Referenzen und Historisch rechnen über **dieselben Zeitslots** wie die optimierten Szenarien: bei `sunrise_window` je `ready_by`-Tag das Buchungsfenster [SA₁, SA₂) des Szenarios, bei `fixed_24h` die 24 h vor dem Anker. Der Anwendertext steht im [Benutzer-Handbuch](../user-manual/Benutzer-Handbuch-Earnie.md#gesamtkosten-jahres-verbrauch-kwh).

Die Spalte **Hinweis** zeigt:

- **Doppelt gebuchte Zeitslots:** Die Reihe enthält Slots mehrfach; im Jahres Verbrauch zählen sie einmal, in den Kosten mehrfach.
- **Zeitslots ohne Buchung:** Zwischen erstem und letztem Slot fehlen Stunden. Verbrauch und Kosten dieser Stunden fehlen in der Zeile.
- **Andere Zeitslots als die Referenz:** Die gebuchten Slot-Mengen von Szenario und Referenz weichen ab (z. B. durch Fenster, die nur die Optimierung bucht). Kosten und Verbrauch beider Zeilen stehen dann nicht ganz auf derselben Basis.
- **Abweichung > 5 % zur Live-Referenz** (`CONSUMPTION_TOLERANCE_REL`): Warnung mit Verweis auf **Info / About**, Bereich Kontakt. Dort ein öffentliches Issue ohne Secrets anlegen; die vollständige Config-ZIP nur privat an `support@earnie-hems.com` senden. Die Zeilen Historisch und Live-Referenz bleiben ohne diese Warnung. Szenarien mit einem anderen Heizsystem als die Live-Referenz (`heating_system_ids`, z. B. Gas statt Wärmepumpe) prüft Earnie nicht, weil sich ihr Stromverbrauch gewollt ändert. Den Strom eines Heizstabs zieht Earnie vor dem Vergleich ab (Block `heat_fuel` im Lauf-Log: `heating_systems`, `rod_kwh`).

Ältere Läufe ohne `booked_consumption` zeigen „—“ und den Hinweis, den Szenario-Explorer neu zu berechnen.

### Verbrauchsvergleich (Debug)

Diese Tabelle steht unter den Gesamtkosten und zeigt je optimiertem Szenario:

| Spalte | Quelle |
| ------ | ------ |
| `Ohne PV und Speicher [kWh]` | gebuchter Verbrauch der Zeile Historisch |
| `Reference (Live) - ohne Optimierung [kWh]` | gebuchter Verbrauch der Live-Referenz |
| `Soll Fenster [kWh]` | Σ Fenster-Sollwerte (`consumption_totals.historical_kwh`) |
| `Geplant MILP [kWh]` | Σ vom Optimierer je Fenster geplanter Verbrauch; Flex läuft nur im Buchungsfenster [SA₁, SA₂) (`consumption_totals.optimized_kwh`) |
| `Optimiert (kWh)` | gebuchter Verbrauch des Szenarios (`booked_consumption`, ohne Standby) |
| `Δ kWh (Ref. ohne Optimierung)` | Optimiert minus Live-Referenz |

`Soll Fenster` und `Geplant MILP` summieren ganze Buchungsfenster, auch die Teile der Randfenster außerhalb des Zeitraums. `Optimiert` zählt nur die Zeitslots im Zeitraum; bei `sunrise_window` liegt es deshalb um etwa einen Tagesverbrauch unter `Geplant MILP`. Ein größerer Abstand heißt, dass geplante Energie nicht in der gebuchten Reihe ankommt, z. B. bei doppelt gebuchten Zeitslots (Spalte **Hinweis** in den Gesamtkosten). Die Plausibilitätsprüfung je Fenster (`Plausibilität`) prüft nur den Plan gegen das Soll. Die Plausibilitäts-Summen im Log enthalten zusätzlich `booked_kwh` und `booked_delta_kwh` (gebucht minus Soll). Die Spalte **Hinweis** betrifft nur zeitliche Lastverschiebung bei gleicher Spec-Energie.
