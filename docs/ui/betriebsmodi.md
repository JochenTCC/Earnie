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
| `live_environment` | **Smarthome-Backend**, **Optimierer-Dienst**, **EHAL-Com**, **Analyse Verbrauch & Kosten** (Live-Cockpit) | Daemon Control / Live-Cockpit | ja (ohne Key kein Live- und Daemon-Anteil) |
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
| **Daemon Control** | Smarthome-Backend, Optimierer-Dienst, EHAL-Com |

**Optimierer-Dienst:** Die Seite bietet Start, Stopp und Neustart, das Dienst-Log und den Umschalter **Silent / Loud** (`silent_mode` in `runtime/local_settings.json`). Für den Umschalter ist kein Neustart von `main.py` nötig. Details: [Betrieb](../einrichtung/betrieb.md) · Schreibverhalten: [EHAL-Com](ehal-com.md).

Während der Ersteinrichtung (Greenfield) sind zunächst nur **Konfiguration** und **Daemon Control** sichtbar. Die Daemon-Seiten erscheinen dabei auch dann, wenn `live_environment` in der Env fehlt. Solange kein Smarthome-Backend gewählt ist, zeigt Daemon Control nur **Smarthome-Backend**. Optimierer-Dienst und EHAL-Com erscheinen erst danach.

Spezifikation (Entwicklerdokument): [UI Sunset-2-Sunset](../dev/done/ui-sunset2sunset.md). Chart- und Panel-Details: [Charts & Panels](charts.md).

## Sunset-2-Sunset (Seite Monitor)

**Zweck:** Der Monitor ist ein einheitliches Produktiv-Cockpit ohne Grenze zwischen Live und Historie.

- **Vergangenheit:** aus dem Produktiv-Log (`optimization_history.jsonl`).
- **Gegenwart und Vorausschau:** aus dem **Produktiv-Snapshot** (`live_optimization_debug.json`), den `main.py` schreibt.
- **Darstellung:** Am Desktop zeigt die Seite ein Fenster SA₀→SA₂, mobil zwei benachbarte Segmente von Sonnenaufgang zu Sonnenaufgang.

**Abwesenheitsmodus:** Ist der wirksame Live-Abwesenheitsmodus aktiv, zeigt die Seite unter dem Titel den Hinweis „Abwesenheitsmodus aktiv“, optional mit der Quelle Earnie, Smarthome oder beide. Auslöser ist der Schalter im Hausprofil **oder** das Anlagen-Feld `sens_absent_mode` am aktiven Backend (Loxone-Merker, HA-Entity oder OpenEMS `component/Channel`). Konfiguration: [Flexible Verbraucher](../konfiguration/flexible-verbraucher.md#abwesenheitsmodus-live).

**Ersetzt:** Der Monitor ersetzt die früheren Modi **Echtzeit** und **Historischer Tag** sowie den Button **Produktiv-Archiv**. Eine **Nachrechnung** beliebiger Kalendertage bietet der Monitor nicht; sie ist als Entwicklerfunktion im Szenario-Explorer geplant.

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

Die Parameter für PV, Batterie und Einspeisung kommen über Entitäts-IDs aus dem **Live-Szenario**. Es liegt in `backtesting_scenarios.json` und wird über `live_scenario_id` in `config.json` gewählt; bearbeitet wird es auf der Seite **Szenarienkonfigurator**. Ein adaptives PV-Tuning gibt es nicht mehr; ein neuer Ansatz zur Parameter-Anpassung ist separat geplant.

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
> Standard-Horizont ist `sunrise_window`: Das MILP rechnet SA₀→SA₂, gebucht wird jeweils **[SA₁, SA₂)**, also von Sonnenaufgang zu Sonnenaufgang je `ready_by`-Tag. Der SoC wird an den Sonnenaufgang-Übergängen verkettet. `fixed_24h` bleibt als Vergleichsmodus erhalten (an `ready_by` ausgerichtete 24-h-Fenster).

Geplant ist eine Nachrechnung beliebiger Kalendertage als Entwicklerfunktion. Sie ersetzt den früheren Modus **Historischer Tag**.

### Gesamtkosten und -Verbrauch

Die Tabelle **Gesamtkosten und -Verbrauch** hat die Spalten `Szenario`, `Jahres Verbrauch [kWh]`, `Jahres Kosten [€]`, `Δ vs Referenz [€]` und `Hinweis`. Das Delta bezieht sich immer auf die Zeile der Live-Referenz.

Der volumetrische **Netznutzung Arbeitspreis** aus dem Hausprofil fließt in die Kosten des Szenario-Explorers ein. **Leistungspreis** und netzgebietsspezifische Tabellen fehlen. Nachrechnen: [Tarife und Preise nachrechnen](../referenz/tarife-quellen.md).

**Datenquellen für `Jahres Verbrauch [kWh]`** (UI: `build_annual_cost_rows` / `_jahres_kwh_for_row`):

| Zeile | kWh-Quelle |
| ----- | ---------- |
| `historical_reference` (Historisch) | `reference_kwh_for_period` → Summe `cons_data` `total_kw` über `meta.period` |
| Szenario-Referenz (`ref__…`) | `plausibility[<parent>].consumption_totals.historical_kwh` (Summe der gebuchten Fenster) |
| Optimiertes Szenario | `plausibility[<id>].consumption_totals.optimized_kwh` |

Mit Hausprofil ist `consumption_source` typischerweise `profile_spec`. Die Fenster-Referenz ist dann die Spec-Last aus Jahresverbrauch und Zeitplänen und stammt nicht vom Zähler. Die Zeile Historisch bleibt bewusst beim Ist-Zähler. Weicht der Ist-Verbrauch vom Modell ab, sind Unterschiede zu den übrigen Zeilen daher zu erwarten. Eine Kurzfassung steht in der UI-Caption unter der Tabelle; der Anwendertext steht im [Benutzer-Handbuch](../user-manual/Benutzer-Handbuch-Earnie.md#gesamtkosten-jahres-verbrauch-kwh).

Weicht der Jahresverbrauch einer Zeile relativ um **mehr als 5 %** (`CONSUMPTION_TOLERANCE_REL`) von der **Live-Referenz** ab, zeigt die Spalte **Hinweis** eine Warnung. Sie verweist auf **Info / About**, Bereich Kontakt: dort ein öffentliches Issue ohne Secrets anlegen; die vollständige Config-ZIP nur privat an `support@earnie-hems.com` senden. Die Zeile der Live-Referenz selbst bleibt ohne Warnung.

### Verbrauchsvergleich (Debug)

Diese Tabelle steht unter den Gesamtkosten. Sie summiert je optimiertem Szenario die gelieferten kWh über alle 24-h-Fenster, mit Δ gegen die Live-Referenz. Die Spalte **Hinweis** betrifft nur zeitliche Lastverschiebung bei gleicher Spec-Energie.
