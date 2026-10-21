# Betriebsmodi und Navigation

Die Streamlit-App ordnet ihre Seiten über **`st.navigation`** in Abschnitte. Das frühere Sidebar-Radio „Betriebsmodus“ gibt es nicht mehr. Welche Seiten sichtbar sind, steuert die Umgebungsvariable **`EARNIE_UI_MODES`**.

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

Die Sidebar enthält oben Setup-Hinweise und **„Konfiguration speichern / laden“**. Diese Funktion exportiert und importiert die Config-Sidecars und `uploads/` als ZIP (siehe [Speichern / Laden](../konfiguration/speichern-laden.md)).

Unten in der Sidebar liegt der Abschnitt **Info / About** mit folgenden Inhalten:

- Banner der Wahrheit und Version.
- Kontakt über ein **GitHub-Issue** mit Art, Thema und Beschreibung; optional eine lokale Kontakt-ZIP.
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

**Ersetzt:** Der Monitor ersetzt die früheren Modi **Echtzeit** und **Historischer Tag** sowie den Button **Produktiv-Archiv**. Eine **Nachrechnung** beliebiger Kalendertage bietet der Monitor nicht.

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

**Chart 2** zeigt die Kosten-Annotationen **BL Ziel**, **Optimiert** und **Ersparnis** **pro SA-Tag**. Mobil gilt das nur für den sichtbaren Tag, am Desktop für SA₀→SA₂ in zwei Spalten. Am laufenden Tag erscheinen **Ersparnis bisher** (SA bis jetzt) und **Ersparnis erwartet** (ganzer Tag). Im grauen Bereich zeigt das Chart zusätzlich die Kurve **Ersparnis bisher**.

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

> **Hinweis zur Neuoptimierung:** Der Szenario-Explorer steuert die MILP-Commit-Weite über `commit_hours` in `backtesting_scenarios.json`. Der Standard **24** entspricht ungefähr einer Planung ohne Rückkopplung (open-loop), **1** bedeutet stündliche Neuoptimierung. Das ist nicht dasselbe wie die periodische Neuoptimierung im Live-Betrieb; eine 1:1-Übereinstimmung mit der Live-Optimierung (MPC) ist nicht nachgewiesen.
>
> Standard-Horizont ist `sunrise_window`: Das MILP rechnet SA₀→SA₂, gebucht wird jeweils **[SA₁, SA₂)**. SA₂ ist der Sonnenaufgang am `ready_by`-Tag, SA₁ der des Vortags. Die Buchungsfenster schließen damit lückenlos und ohne Doppelbuchung aneinander, auch wenn die Sonne erst nach `ready_by` aufgeht. `ready_by` ist nur die Lade-Deadline des E-Autos; die Ladenacht davor liegt im selben Buchungsfenster. Alle flexiblen Verbraucher laufen nur innerhalb des Buchungsfensters. Der SoC wird an den Sonnenaufgang-Übergängen verkettet. `fixed_24h` bleibt als Vergleichsmodus erhalten (an `ready_by` ausgerichtete 24-h-Fenster).

### Gesamtkosten und -Verbrauch

Die Tabelle **Gesamtkosten und -Verbrauch** hat die Spalten `Szenario`, `Jahres Verbrauch [kWh]`, `Speicher-Standby [kWh]`, `Gesamtverbrauch [kWh]` (= Jahres Verbrauch + Speicher-Standby), `Jahres Kosten [€]`, `Δ vs Referenz [€]` und `Hinweis`. Das Delta bezieht sich immer auf die Zeile der Live-Referenz.

Der volumetrische **Netznutzung Arbeitspreis** (je Netzgebiet aus `grid_fees.json`) fließt in die Kosten des Szenario-Explorers ein. Ein **Leistungspreis** wird noch nicht berücksichtigt. Nachrechnen: [Tarife und Preise nachrechnen](../referenz/tarife-quellen.md).

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
- **Abweichung > 5 % zur Live-Referenz** (`CONSUMPTION_TOLERANCE_REL`): Warnung mit Verweis auf **Info / About**, Bereich Kontakt. Dort ein öffentliches Issue ohne Secrets anlegen; die vollständige Config-ZIP nur privat an `support@earnie-hems.com` senden. Die Zeilen Historisch und Live-Referenz bleiben ohne diese Warnung.

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
