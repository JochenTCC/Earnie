# EARNIE — Benutzer-Handbuch

> **Entwurf.** Dieses Handbuch beschreibt Earnie aus Anwendersicht nach der Installation.
> Technische Details (Container, Config-Schema, Entwickler) stehen in der [Anwender-Dokumentation](../README.md) und im [README](../../README.md).

---

## Übersicht

### Sinn und Zweck von Earnie

**Earnie** ist ein Energie-Optimierer für Privathaushalte. Er plant und steuert, wann Strom bezogen, gespeichert, verbraucht oder eingespeist wird — mit dem Ziel, **Stromkosten zu senken** und den **Eigenverbrauch** zu erhöhen.

Besonders wirksam ist Earnie bei **dynamischen Spot-Tarifen** (z. B. aWATTar), weil Preise stündlich schwanken. Statt fester Regeln berechnet Earnie regelmäßig einen **Plan für die nächsten etwa 24–48 Stunden** (15-Minuten-Schritte) und berücksichtigt dabei:

- aktuelle und prognostizierte Strompreise  
- PV-Ertragsprognose (Wetter am Standort)  
- Zustand und Grenzen des Batteriespeichers  
- verschiebbare Verbraucher (E-Auto, Wärmepumpe, Pool, Haushaltsgeräte, …)

**Zwei Nutzungsarten:**

| Nutzung | Was Sie damit machen |
|--------|----------------------|
| **Was-wäre-wenn (ohne Smart-Home)** | Haus und Varianten konfigurieren, Jahresvergleich rechnen — z. B. ob sich Speicher, größere PV oder ein Spot-Tarif lohnen |
| **Live-Betrieb (mit Loxone)** | Dauerhaft optimieren und Sollwerte an die Hausautomation schreiben; Monitor zeigt Plan und Ist |

Nur der Hintergrunddienst (`main.py`) steuert die Anlage. Die Web-Oberfläche (Streamlit) ist das **Cockpit**: Anzeige, Konfiguration und Analyse — sie schreibt keine Steuerbefehle an Loxone.

### Voraussetzungen

**Für Was-wäre-wenn-Analysen (ohne Live-Steuerung):**

- PC oder Server mit Docker **oder** lokaler Python-Umgebung  
- Webbrowser für die Oberfläche  
- Grobe Angaben zu Haus, Verbrauchern, optional PV/Speicher und Tarif  
- Internet für Wetter- und Preisdaten (je nach Szenario)

**Für den produktiven Live-Betrieb zusätzlich:**

- [Loxone](https://www.loxone.com/)-Miniserver mit erreichbarer HTTP-Schnittstelle  
- Sinnvolle Merker / virtuelle Eingänge für SOC, Leistungen, Freigaben und Sollwerte (siehe Kapitel *Verbindung zu Smarthome*)  
- Typischerweise: PV und/oder Batteriespeicher sowie steuerbare Verbraucher  
- Empfohlen: dynamischer Bezugs- und/oder Einspeisetarif  

Earnie ist **unabhängig von Energieversorger und Systemlieferant** gedacht; die heutige Live-Anbindung ist Loxone. Andere Systeme können später ergänzt werden.

### Lizenzbedingungen

Earnie ist **Source-Available** und für die **private, nicht-kommerzielle Nutzung** in Privathaushalten vorgesehen. Kommerzielle Nutzung, Weiterverkauf oder SaaS-Angebote sind ohne schriftliche Zustimmung nicht erlaubt.

Die Software wird „wie besehen“ bereitgestellt. Eingriffe in Speicher und Großverbraucher erfolgen auf **eigenes Risiko** des Betreibers.

Vollständige Bedingungen: [LICENSE.md](../../LICENSE.md).

### Support

- **Projekt & Issues:** [GitHub — JochenTCC/Earnie](https://github.com/JochenTCC/Earnie)  
- **Community:** z. B. Diskussionen im Loxone-Umfeld (loxforum u. Ä.)  
- **Technische Doku:** [docs/README.md](../README.md)  

Es gibt derzeit keinen vertraglichen Herstellersupport. Rückmeldungen zu neuen Hardware-Typen und Konfigurationen helfen der Weiterentwicklung.

---

## Installation

Kurzfassung der typischen Wege:

| Weg | Für wen | Hinweis |
|-----|---------|---------|
| **Docker (empfohlen Produktiv)** | Synology NAS, LoxBerry, Proxmox LXC, PC | Persistente Ordner `config/` und `runtime/` außerhalb des Images |
| **Greenfield / Ersteinrichtung** | Erste Was-wäre-wenn-Tests lokal | Eigener Stack, oft Port **8502** — getrennt vom Produktivsystem |
| **Lokal ohne Container** | Entwickler, Tests | siehe [DEVELOPER.md](../../DEVELOPER.md) |

**Typischer Ablauf (Docker):**

1. Projekt bzw. Compose-Datei bereitstellen, Verzeichnisse `config/` und `runtime/` anlegen.  
2. Container starten — fehlende Dateien werden beim ersten Start angelegt (Bootstrap).  
3. Oberfläche im Browser öffnen (Produktiv oft Port **8501**, siehe [Streamlit-Ports](../referenz/streamlit-ports.md)).  
4. Loxone-Zugang hinterlegen (falls Live geplant) und mit dem Hauskonfigurator fortfahren.

Details: [Container](../einrichtung/container.md) · [Betrieb](../einrichtung/betrieb.md) · [Greenfield](../einrichtung/greenfield-dev-stack.md).

Nach dem Start erscheinen in der Navigation zunächst vor allem **Planung** und **Echtzeit-Umgebung**. Weitere Seiten (Monitor, Szenario-Explorer, …) werden freigeschaltet, sobald die Einrichtung weit genug ist.

---

## Erste Einrichtung (für Was-Wäre-Wenn-Analyse)

Ziel dieser Phase: Ihr Haus so abbilden, dass Earnie **Vergleichsszenarien** rechnen kann — noch ohne echte Steuerung der Anlage. Ideal, um Investitionen und Tarifwahl vorab zu prüfen.

Empfohlene Reihenfolge:

1. Hauskonfigurator (Haus, Verbraucher, PV, Speicher)  
2. Szenarieneditor (Varianten: mit/ohne Speicher, anderer Tarif, …)  
3. Live-Szenario zuweisen (welche Entitäten „gelten“ als Basis)  
4. Szenario-Explorer: Verbrauch generieren, Rechnung starten, Ergebnisse lesen  

### Hauskonfigurator

Unter **Planung → Hauskonfigurator** pflegen Sie die baulichen und technischen Bausteine Ihres Haushalts. Gespeichert werden Kataloge (Hausprofile, Komponenten), die später von Szenarien **referenziert** werden — nicht alles doppelt in einer einzigen Datei.

In der Sidebar sehen Sie fehlende Schritte der Ersteinrichtung.

#### Konfiguration eines Hauses

Ein **Hausprofil** beschreibt Standort und „Wer lebt / was verbraucht hier“:

- **Standort:** Breite, Länge, Zeitzone (wichtig für Sonnenzeiten und PV-Prognose)  
- **Verbraucher im Profil:** z. B. Haus-Wärme, E-Auto, Pool, generische Geräte  
- **Grundlast:** typischer Haushaltsverbrauch über den Tag (Vorschau im Konfigurator prüfen)

Legen Sie zuerst ein Profil an und ergänzen Sie danach die Geräte. Ohne Standort und sinnvolles Profil sind Jahresvergleiche wenig aussagekräftig.

#### Haus-Wärme

Thermischer Verbraucher für Heizung / Wärmepumpe (je nach Modell im Profil):

- Solltemperaturen und thermische Parameter (Wärmeverlust, Volumen bzw. Gebäudekennwerte)  
- Earnie schätzt den **Wärmebedarf aus Wetterdaten** und plant den Strombedarf zeitlich mit ein  
- Im Live-Betrieb später Anbindung über Loxone-Merker (Leistung, Freigabe, ggf. Temperaturen)

Je genauer die thermischen Angaben, desto realistischer der Jahresvergleich — grobe Werte reichen für eine erste Orientierung.

#### Elektro-Auto

E-Auto / Wallbox als planbarer Verbraucher:

- Akkukapazität, Ladeleistung, Wirkungsgrad  
- **Zeitfenster:** wann das Auto da ist und bis wann es „fertig“ sein soll (Werktag / Wochenende)  
- Ziel-SOC bzw. Rest-SOC beim Abfahren  

Earnie entscheidet **wann** geladen wird (günstige Stunden, PV-Überschuss), nicht ob Sie ein Auto haben. Im Live-Betrieb liefert Loxone typischerweise „angesteckt“, Rest-SOC und Fertig-Zeit; Earnie schreibt Lade-Sollleistung und ggf. PV-Follow.

#### Pool

Pool / SwimSpa oft als **zwei Aspekte**:

- **Heizung** — thermisches Modell (Wasservolumen, Solltemperatur, Wärmeverlust); Tagesenergie ergibt sich aus dem Modell  
- **Filter** — Laufzeitbedarf (Stunden), ggf. natives Zeitfenster der Poolsteuerung; Earnie kann **zusätzlich** außerhalb dieses Fensters freigeben  

Für Was-wäre-wenn reichen Volumen, Solltemperatur und Filterstunden. Live braucht passende Merker für Temperaturen und Freigaben.

#### Allgemeine Verbraucher

Waschmaschine, Trockner, Geschirrspüler und ähnliche Geräte als **generische** Verbraucher:

| Rolle in Earnie | Bedeutung für Sie |
|-----------------|-------------------|
| **Bekannt (known)** | Feste / geplante Zeiten fließen als Grundlast ein — Earnie verschiebt sie nicht |
| **Flexibel (flex)** | Earnie darf den Start im erlaubten Fenster verschieben |
| **Manuell (manual)** | Sie planen auf der Seite *Manuelle Geräte*; Earnie gibt Start-Empfehlungen |

Leistung und typische Laufzeit angeben. Optional später ein Loxone-Leistungsmerker für Ist-Anzeige und Empfehlungen.

#### PV-Anlage

Unter PV-Anlagen (Komponenten-Katalog):

- installierte Leistung (**kWp**)  
- Dachneigung und Ausrichtung (Azimut: Süd ≈ 0°, Ost negativ, West positiv)  

Standort kommt aus dem Hausprofil. Earnie nutzt Wetterdaten für die Ertragsprognose. Mehrere unabhängige PV-Anlagen in einem Szenario sind noch eingeschränkt (Roadmap); für den Entwurf reicht in der Regel **eine** Anlage.

#### Batteriespeicher

Unter Batterien:

- nutzbare Kapazität (kWh)  
- max. Lade-/Entladeleistung (kW)  
- Wirkungsgrad, min./max. SOC  
- optional **Verschleißkosten** (damit Earnie unnötige Zyklen wirtschaftlich berücksichtigt)  

Im Live-Betrieb steuert Earnie Ziel-SOC und Lade-/Entlade-Sollwerte über Loxone; die konkrete Wechselrichter-Logik bleibt in der Hausautomation.

### Szenarien-Editor

Unter **Planung → Szenarieneditor** bauen Sie **Varianten** Ihres Haushalts, ohne den Live-Betrieb zu ändern.

Ein Szenario verknüpft typischerweise:

- Hausprofil  
- Batterie und/oder PV (oder bewusst „ohne“)  
- Bezugs- und Einspeisetarif  

Beispiele für Vergleiche:

- Ist-Zustand vs. größerer Speicher  
- mit PV vs. ohne PV  
- Fixpreis vs. Spot-Tarif  
- ohne Batterie, aber mit PV  

Das **Live-Szenario** (meist ID `live`) ist die Basis für den späteren Produktivbetrieb. Weitere Szenarien dienen nur der Analyse im Szenario-Explorer.

Tarife wählen Sie aus dem Tarifkatalog (Bezug/Einspeise). Details zu Preisen: [Preise & aWATTar](../konfiguration/preise.md).

### Szenario-Explorer (Was-Wäre-Wenn-Analyse)

Unter **Analyse → Szenario-Explorer** (erscheint nach ausreichender Planungs-Konfiguration).

Hier rechnen Sie **Langzeitvergleiche** (Monate / Jahr) zwischen Referenz und Ihren Szenarien. Das ist **kein** tägliches Live-Cockpit und ändert keine Steuerwerte an Loxone.

> Hinweis: Ergebnisse sind Modellrechnungen. Es gibt **keine Garantie**, dass Live-Einsparungen exakt den Simulationen entsprechen (Wetter, Verhalten, Tarifdetails, Hardwaregrenzen).

#### Verbrauchsdaten generieren und sichten

Vor oder beim Start einer Explorer-Rechnung brauchen Sie eine belastbare **Lastgrundlage**:

- aus dem **Hausprofil** (Zeitpläne / thermische Modelle / Flex-Fenster), und/oder  
- aus historischen Verbrauchsdaten, falls vorhanden  

Im Explorer bzw. zugehörigen Schritten können Sie Verbrauchsverläufe erzeugen und prüfen (Plausibilität, Monatsprofile). Stimmen Größenordnung und Tagesgang nicht, zuerst Profil und Geräte korrigieren — sonst sind Kostenvergleiche irreführend.

#### Szenario-Explorer ausführen

1. Gewünschte Szenarien und Zeitraum (Monate) wählen.  
2. Rechnung starten (kann je nach Umfang länger dauern).  
3. Warten, bis die Auswertung fertig ist; Ergebnisse landen in der Laufzeitablage für den Explorer.

Die Referenzökonomie vergleicht typischerweise „Last am gewählten Tarif **ohne** Batterieoptimierung“; Szenarien mit PV rechnen mit dem jeweiligen PV-Ertrag. Batterie ist Teil der **optimierten** Variante, nicht der reinen Referenz.

#### Ergebnisse des Szenario-Explorers

Auswertung u. a.:

- **Kostenvergleich** Gesamt und monatlich (Referenz vs. optimierte Szenarien)  
- **Monatsverläufe** und Plausibilitätsansichten  
- Charts zu Leistung, Verbrauch und PV je nach gewählter Ansicht  

Nutzen Sie die Ergebnisse als **Entscheidungsgrundlage** (Investition, Tarif), nicht als exakte Prognose der nächsten Stromrechnung.

---

## Verbindung zu Smarthome (Loxone)

Wenn die Was-wäre-wenn-Analyse überzeugt, folgt die Anbindung an den Miniserver. Earnie liefert **Sollwerte und Freigaben**; die konkrete Schaltlogik (Wechselrichter, Wallbox, Relais) bleibt in Loxone.

### Vorbereitung der Loxone-Konfiguration

1. **Benutzer** am Miniserver mit Rechten zum Lesen und Schreiben der benötigten IOs.  
2. **Merker / virtuelle Eingänge** anlegen bzw. benennen — u. a.:  
   - Batterie: SOC, Leistungen, PV-Leistung  
   - Steuerung: Ziel-SOC, Lade-/Entlade-Soll, Steuerbefehl (Automatik / Zwang)  
   - Verbraucher: Ist-Leistung lesen; Freigabe 0/1 oder E-Auto-Leistungs-Soll schreiben  
   - E-Auto: angesteckt, Fertig-Zeit, Rest-SOC, Kapazität, …  
3. Optional **FTP-Verbrauchslog** für historische Daten.  
4. Namen in Earnie hinterlegen (Live-Konfiguration / Config) — **exakt** wie in Loxone.  

Earnie liest Loxone-Werte oft als Text mit Einheit (z. B. `3.5 kW`); die Einheit wird ignoriert.

Signalübersicht: [Loxone-Signale](../referenz/loxone-signale.md) · Anbindung: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md).

### Live-Konfiguration

Unter **Echtzeit-Umgebung → Live-Konfiguration**:

- welches Szenario **live** gilt (`live_scenario_id`)  
- welche Entitäten (Hausprofil, Batterie, PV, Tarife) daran hängen  

Aufgelöste Zahlen (kWp, Kapazität, Vergütung in ct/kWh) sind meist **nur Anzeige**. Geändert werden die Referenzen bzw. die Kataloge im Hauskonfigurator / Szenarieneditor.

Damit nutzen Live-Optimierung und Szenario-Explorer dieselbe Auflösungslogik.

### Loxone-Kommunikation

Unter **Echtzeit-Umgebung → Loxone-Kommunikation** (Debug / Abnahme):

- **Live-Lesen:** alle konfigurierten Merker periodisch vom Miniserver  
- **Letzte Schreibvorgänge:** was `main.py` zuletzt gesendet hat (Erfolg ja/nein)  
- **Silent-Modus:** Earnie berechnet und zeigt Sollwerte, **schreibt aber nicht** an Loxone — sinnvoll für Tests und parallelen Altbetrieb  
- **Live-Modus:** Schreiben aktiv — erst nach erfolgreicher Lesekontrolle umschalten  

Prüfungen auch per Skript: `python -m scripts.verify_loxone_setup`.

Cutover-Checkliste: Lesen OK → Schreiben Erfolg → Monitor/Sankey plausibel. Details: [Loxone-Kommunikation](../ui/loxone-kommunikation.md).

---

## Live-Betrieb

Im Produktivbetrieb läuft der Optimierer dauerhaft (Container-Worker bzw. `python main.py`) und arbeitet im **15-Minuten-Takt** (zusätzlich bei konfigurierten Ereignissen). **Nur eine Instanz** darf schreiben.

Die Oberfläche zeigt den aktuellen Plan; sie ersetzt den Daemon nicht.

### Earnie Monitor

Unter **Betrieb → Monitor** (Sunset-2-Sunset):

Einheitliches Cockpit über **Vergangenheit, Jetzt und Vorausschau** — navigierbar in Sonnenaufgangs-Fenstern (ca. 24 h Segmente).

Typische Inhalte:

- **Chart 1:** Leistungen, Energieflüsse (PV, Netz, Batterie, Flex-Verbraucher), SOC, Preis  
- **Chart 2:** ergänzende Verläufe / Kennzahlen des Fensters  
- **Sankey:** aktueller Energiefluss aus Live-Daten  
- **Tabelle & Energievergleich:** Rohdaten und Baseline vs. Optimierung  
- **Countdown:** nächster Optimierungslauf  

Graue Bereiche = Historie aus dem Produktiv-Log; Vorausschau = letzter Plan von `main.py`. Fehlende Log-Slots bleiben sichtbar leer.

Kennzahlen zur Ersparnis beziehen sich auf den **vollen Planungshorizont** (Jetzt bis übernächster Sonnenaufgang), nicht nur auf das gerade sichtbare Chart-Segment.

Charts im Detail: [Charts & Panels](../ui/charts.md) · Modus: [Betriebsmodi](../ui/betriebsmodi.md).

### Manuelle Geräte

Unter **Betrieb → Manuelle Geräte** für Verbraucher mit Rolle **manuell**:

- Laufzeiten planen bzw. Earnie-**Startempfehlungen** nutzen  
- angenommene Leistung und Dauer aus dem Hausprofil  

Geplante Läufe erscheinen im Monitor (Chart 1) und fließen in die Optimierung der übrigen Lasten ein. Ideal für Geräte ohne smarte Freigabe, bei denen Sie den Start selbst setzen.

### Verbraucher-Analyse

Unter **Analyse → Verbraucheranalyse**:

Auswertung, welcher Verbrauch **autonom** (Haus/Loxone ohne Earnie-Plan) und welcher **earnie-initiiert** bzw. verschoben war. Hilft zu prüfen, ob Freigaben und Pläne greifen und wo noch Potenzial liegt.

---

## Kurz-Checkliste vom Leerzustand zum Live

1. Installieren (Docker/Greenfield) und UI öffnen  
2. Hauskonfigurator: Profil, Wärme, Auto, Pool, Geräte, PV, Batterie  
3. Szenarieneditor: Live-Szenario + Vergleichsvarianten  
4. Szenario-Explorer: Verbrauch prüfen, Rechnung, Ergebnisse bewerten  
5. Loxone vorbereiten und Zugang speichern  
6. Live-Konfiguration + Loxone-Kommunikation (Silent → Live)  
7. Daemon dauerhaft laufen lassen, Monitor beobachten, Feintuning  

Bei Unklarheiten in der Konfiguration: Hover-Hilfe in `config.json` (Schema) und die Kapitel unter [docs/README.md](../README.md).
