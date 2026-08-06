# EARNIE — Benutzer-Handbuch

Dieses Handbuch beschreibt Earnie aus Anwendersicht.  
Technische Details (Container, Config-Schema, Entwickler) stehen in der [Anwender-Dokumentation](../README.md) und im [README](../../README.md).  
Häufige Kurzformen (EHAL, SE, SoC, …): [Abkürzungen](../referenz/abkuerzungen.md).

---

## Übersicht

### Sinn und Zweck von Earnie

**Earnie** ist ein Energie-Optimierer für Privathaushalte. Er plant und steuert, wann Strom bezogen, gespeichert, verbraucht oder eingespeist wird — mit dem Ziel, **Stromkosten zu senken** und den **Eigenverbrauch** zu erhöhen.

Besonders wirksam ist Earnie bei **dynamischen Spot-Tarifen** (z. B. aWATTar), bei denen die Preise (viertel-) stündlich schwanken. Statt fester Regeln berechnet Earnie regelmäßig einen **Plan für die nächsten etwa 24–48 Stunden** und berücksichtigt dabei:

- aktuelle (und wenn nötig prognostizierte) Strompreise  
- PV-Ertragsprognose (Wetter am Standort)  
- Zustand und Grenzen des Batteriespeichers  
- Steuerbare Verbraucher (E-Auto, Wärmepumpe, Pool, Haushaltsgeräte, …)

**Zwei Nutzungsarten:**


| Nutzung                             | Was Sie damit machen                                                                                                           |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **Was-wäre-wenn (ohne Smart-Home)** | Haus und Varianten konfigurieren, Jahresvergleich rechnen — z. B. ob sich Speicher, größere PV oder ein Spot-Tarif lohnen      |
| **Live-Betrieb (mit Smarthome)**    | Dauerhaft optimieren und Sollwerte an Loxone, Home Assistant (+ evcc) oder OpenEMS (Lab) schreiben; Monitor zeigt Plan und Ist |


Im Hintergrund läuft ein Optimierer-Dienst, der exklusiv die Anlage steuert. Die Web-Oberfläche (Streamlit) ist das **Cockpit**: Anzeige, Konfiguration und Analyse — und mit der Möglichkeit, den **Optimierer-Dienst** zu starten / stoppen /oder neu zu starten.

### Voraussetzungen

**Für Was-wäre-wenn-Analysen (ohne Live-Steuerung):**

- PC oder Server mit Docker **oder** lokaler Python-Umgebung  
- Webbrowser für die Oberfläche  
- Grobe Angaben zu Haus, Verbrauchern, optional PV/Speicher und Strom-Tarif(en)  
- Internet für Wetter- und Preisdaten (je nach Szenario)

**Für den produktiven Live-Betrieb zusätzlich:**

- Erreichbares Smarthome-Backend: [Loxone](https://www.loxone.com/) (Default), [Home Assistant](https://www.home-assistant.io/) + evcc (DACH-Pfad A2) oder OpenEMS (Lab-/Industrie-Prototyp) — siehe [Adapter wählen](../einrichtung/adapter-wahl.md)  
- Sinnvolle Merker / Entities für SOC, Leistungen, Freigaben und Sollwerte (Kapitel *Verbindung zu Smarthome*)  
- Typischerweise: PV und/oder Batteriespeicher sowie steuerbare Verbraucher  
- Empfohlen: dynamischer Bezugs- und/oder Einspeisetarif

Earnie ist **unabhängig von Energieversorger und Systemlieferant** gedacht.

### Lizenzbedingungen

Earnie ist **Source-Available** und für die **private, nicht-kommerzielle Nutzung** in Privathaushalten vorgesehen. Kommerzielle Nutzung, Weiterverkauf oder SaaS-Angebote sind ohne schriftliche Zustimmung nicht erlaubt.

Die Software wird „wie besehen“ bereitgestellt. Eingriffe in Speicher und Großverbraucher erfolgen auf **eigenes Risiko** des Betreibers.

Zu einem späteren Zeitpunkt werden verschiedene kommerzielle Angebote verfügbar sein für Nutzer, die die Konfiguration und Wartung nicht selbst vornehmen wollen.

Vollständige Bedingungen: [LICENSE.md](../../LICENSE.md).

### Banner der Wahrheit

In der Sidebar unter **Info / About** (unten) und zusätzlich **am unteren Ende des Hauptbereichs** erscheint ein kurzes Attributions-Banner (Name, nicht-kommerzieller Hinweis, Link zum offiziellen Repository, Version). Es kennzeichnet Earnie und die Nutzungsbedingungen.

Bei erkennbar inoffiziellen oder geänderten Builds (z. B. abweichende Git-Remote) kann zusätzlich ein Warnhinweis erscheinen. Das Banner ist bewusst sichtbar gehalten.

Unter **Info / About** erscheinen zusätzlich der **Hardware-Fingerprint** (vollständig, kopierbar) und der Registry-Status (`unbound` / `valid` bzw. gebunden / `mismatch` / `invalid_sig`). Das ist optional und sperrt den Start **nicht**.

### Hardware-Registry (`earnie_registry.json`)

Die Datei `earnie_registry.json` ist eine **einmalig ausgestellte Bindung** Ihrer Earnie-Installation an Ihren Hardware-Fingerprint (Host und optional Smart-Home-IDs). Private Nutzung ohne diese Datei bleibt möglich; der Status bleibt dann `unbound`.

**Wichtig:** Sie erzeugen die signierte Datei **nicht selbst**. Earnie berechnet nur den Fingerprint. Die Datei stellt der Rechteinhaber aus (derzeit per E-Mail; später ggf. Cloud-Portal). Offizielle Images prüfen die Signatur mit einem **öffentlichen** Schlüssel; der private Schlüssel bleibt beim Aussteller.

**So erhalten Sie die Datei:**

1. Earnie starten (Docker oder lokal).
2. In der Sidebar **Info / About** öffnen und den **vollständigen 64-stelligen Hardware-Fingerprint** kopieren (Anzeige als Code-Block).
3. Alternativ auf dem Host (Projektwurzel, mit Python-Umgebung):
  ```text
   python -m scripts.print_hardware_fingerprint
  ```
   Die Ausgabe enthält `fingerprint=` (vollständig) und `fingerprint_display=` (Kurzform).
4. Per **Info / About → Registry per E-Mail anfordern** an `support@earnie-hems.com` senden (Betreff „Earnie Registry“, Fingerprint und Datenschutzhinweis sind bereits im Mailtext). Bei Bedarf die Speicherung der Absenderadresse für Supportzwecke von **Nein** auf **Ja** ändern (DSGVO; Standard: keine Speicherung). Optional zusätzlich die Kontakt-ZIP über **Privater Support** anhängen (nicht in öffentliche GitHub-Issues).
5. Sie erhalten zurück die Datei `earnie_registry.json`.
6. Datei ablegen unter:

  | Installation         | Ablageort                                                     |
  | -------------------- | ------------------------------------------------------------- |
  | Docker / typisch     | `earnie_env/runtime/earnie_registry.json`                     |
  | eigener Runtime-Pfad | Ordner aus `EARNIE_RUNTIME_PATH` bzw. `…/runtime/`            |
  | abweichender Pfad    | Umgebungsvariable `EARNIE_REGISTRY_PATH` auf die Datei setzen |

7. Oberfläche neu laden und unter **Info / About** prüfen: Registry sollte als gebunden (`bound` / `valid`) erscheinen. Bei **mismatch** passt der Fingerprint nicht mehr zur Datei (z. B. anderer Host) — neuen Fingerprint senden und Datei erneut anfordern. Bei **invalid_sig** ist die Datei beschädigt oder nicht gültig signiert — neu anfordern. In beiden Fällen startet Earnie trotzdem (soft check).

**Was die Datei enthält (Kurz):** Fingerprint, Ausstellungszeit, optional Ablaufdatum, Aussteller und eine Ed25519-Signatur. Eine selbst gebaute Datei ohne passende Signatur ist ungültig (`invalid_sig`).

Die Datei wird **beim Rechteinhaber** erzeugt (Signatur mit dem privaten Schlüssel), nicht in der Earnie-Oberfläche. Technische Aussteller-Anleitung: Earnie-Projekt `Entwicklungsplan/Hardware-Registry-Ausstellung.md`.

### Support

- **Kontakt in der App:** Sidebar **Info / About** — Art, Thema, Beschreibung → **GitHub-Issue öffnen** (öffentlich; keine Secrets). Optional **Informationen in ZIP sammeln** (bleibt lokal). Registry / Vertrauliches: Expander **Privater Support** an `support@earnie-hems.com`
- **Projekt & Issues:** [GitHub — JochenTCC/Earnie](https://github.com/JochenTCC/Earnie/issues)  
- **Website:** [earnie-hems.com](https://earnie-hems.com)  
- **Community:** z. B. Diskussionen im Loxone-Umfeld (loxforum u. Ä.)  
- **Technische Doku:** [docs/README.md](../README.md)

Es gibt derzeit keinen vertraglichen Herstellersupport. Rückmeldungen zu neuen Hardware-Typen und Konfigurationen helfen der Weiterentwicklung.

---



## Installation

Kurzfassung der typischen Wege:


| Weg                              | Für wen                                 | Hinweis                                                                                |
| -------------------------------- | --------------------------------------- | -------------------------------------------------------------------------------------- |
| **Docker (empfohlen Produktiv)** | Synology NAS, LoxBerry, Proxmox LXC, PC | Persistente Ordner `earnie_env/config/` und `earnie_env/runtime/` außerhalb des Images |
| **Greenfield / Ersteinrichtung** | Erste Was-wäre-wenn-Tests lokal         | Eigener Stack, oft Port **8502** — getrennt vom Produktivsystem                        |
| **Lokal ohne Container**         | Entwickler, Tests                       | siehe [DEVELOPER.md](../../DEVELOPER.md)                                               |


**Typischer Ablauf (Docker):**

1. Projekt bzw. Compose-Datei bereitstellen, Verzeichnisse `earnie_env/config/` und `earnie_env/runtime/` anlegen.
2. Container starten — fehlende Dateien werden beim ersten Start angelegt (Bootstrap).
3. Oberfläche im Browser öffnen (Produktiv oft Port **8501**, siehe [Streamlit-Ports](../referenz/streamlit-ports.md)).
4. Bei geplantem Live-Betrieb: Smarthome-Backend wählen und Zugang hinterlegen ([Adapter](../einrichtung/adapter-wahl.md)), dann mit dem Hauskonfigurator fortfahren.

Details: [Container](../einrichtung/container.md) · [Betrieb](../einrichtung/betrieb.md) · [Greenfield](../einrichtung/greenfield-dev-stack.md).

Nach dem Start erscheinen in der Navigation zunächst vor allem **Konfiguration** und **Daemon Control**. Weitere Seiten (Monitor, Szenario-Explorer, …) werden freigeschaltet, sobald die Einrichtung weit genug ist.

---



## Erste Einrichtung (für Was-Wäre-Wenn-Analyse)

Ziel dieser Phase: Ihr Haus so abbilden, dass Earnie **Vergleichsszenarien** rechnen kann — noch ohne echte Steuerung der Anlage. Ideal, um Investitionen und Tarifwahl vorab zu prüfen oder sich von der Leistungsfähigkeit von Earnie zu überzeugen.

Empfohlene Reihenfolge:

1. Hauskonfigurator (Haus, Verbraucher, PV, Speicher)
2. Szenarienkonfigurator (Varianten: mit/ohne Speicher, anderer Tarif, …)
3. Live-Szenario zuweisen (welche Entitäten „gelten“ als Basis)
4. Szenario-Explorer: Verbrauch generieren, Rechnung starten, Ergebnisse lesen

Anmerkung: Zu Vergleichszwecken muss KEIN Szenario ohne PV und Batterie angelegt werden. Das macht Earnie als Referenz automatisch.



### Hauskonfigurator

Hauskonfigurator

*Hauskonfigurator: Hausprofil, Verbraucher, PV und Speicher als Kataloge.*

Unter **Konfiguration → Hauskonfigurator** pflegen Sie die baulichen und technischen Bausteine Ihres Haushalts. Gespeichert werden Kataloge (Hausprofile, Komponenten), die später von Szenarien **referenziert** werden.

In der Sidebar sehen Sie fehlende Schritte der Ersteinrichtung.

#### Konfiguration eines Hauses

Ein **Hausprofil** beschreibt Standort und „Wer lebt / was verbraucht hier“:

- **Standort:** Breite, Länge, Zeitzone (wichtig für Sonnenzeiten und PV-Prognose)  
- **Verbraucher im Profil:** z. B. Haus-Wärme, E-Auto, Pool, generische Geräte  
- **Grundlast:** typischer Haushaltsverbrauch über den Tag (Vorschau im Konfigurator prüfen)

Legen Sie zuerst ein Profil an und ergänzen Sie danach die Geräte. Ohne Standort und sinnvolles Profil sind Jahresvergleiche wenig aussagekräftig. Je mehr Freiheiten sie Earnie beim Verschieben der Aktivierung der verschiedenen Verbraucher geben, umso höher sind die Einsparungspotenziale.

Optional: **Historische Jahres-Leistungsprofile [kW] (CSV)** — Lastprofil (direkt oder als **Bilanz** aus PV + Batterie + Netz), optional PV-Erzeugungsprofil und Verbraucher — für Ist-vs-Modell-Vergleich und realistischere Explorer-Rechnungen. Pro Verbraucher: Checkbox **„Von Basis-Last abziehen“** steuert, ob die CSV-Last die Synthese ersetzt und von der Basislast abgezogen wird.

Earnie kennt verschiedene generische Verbrauchstypen (siehe unten), bei denen die Leistungsprofile unterschiedlich behandelt werden. Siehe dazu auch[Historische Leistungsprofil-CSV](../konfiguration/verbrauchs-csv.md)). 

Unter **Gesamt-Lastverhalten** können Sie die Basislast als **Jahres-Rest gleichmäßig** oder **Monats-Rest je Monat** wählen — letzteres gilt auch für den Szenario-Explorer (Pfad A), solange nicht alle steuerbaren Verbraucher ein CSV haben (Pfad B).

Änderungen im Hauskonfigurator und Szenarienkonfigurator werden **automatisch gespeichert**. Komplette Config-Pakete (ZIP) exportieren/importieren Sie in der Sidebar unter **„Konfiguration speichern / laden“** — siehe [Speichern / Laden](../konfiguration/speichern-laden.md).

#### Haus-Wärme

Thermischer Verbraucher für Heizung / Wärmepumpe (je nach Modell im Profil):

- Solltemperaturen und thermische Parameter (Wärmeverlust, Volumen bzw. Gebäudekennwerte). Dafür ist ein Energieausweis des Gebäudes hilfreich.  
- Earnie schätzt den **Wärmebedarf aus Wetterdaten** und den thermischen Parametern und plant den Strombedarf zeitlich mit ein.  
- Im Live-Betrieb erfolgt später die Anbindung über EHAL-Bindings (Leistung, Freigabe, ggf. Temperaturen)

Je genauer die thermischen Angaben, desto realistischer der Jahresvergleich — aber grobe Werte reichen für eine erste Orientierung.

#### Elektro-Auto

E-Auto / Wallbox als planbarer Verbraucher:

- Akkukapazität, Ladeleistung, Wirkungsgrad  
- **Zeitfenster:** wann das Auto da ist und bis wann es „geladen“ sein soll (getrennt für Werktage / Wochenende).  
- Ziel-SOC beim Abfahren

Earnie entscheidet **wann** am günstigsten geladen wird (günstige Stunden, PV-Überschuss) unter der Vorgabe, dass es zum angegebenen Zeitpunkt den gewünschten End-SOC hat. Im Live-Betrieb liefert das Smarthome-Backend typischerweise „angesteckt“, Ist-SOC und Fertig-Zeit; Earnie schreibt Lade-Sollleistung und ggf. PV-Follow um genau den PV-Überschuss ins E-Auto zu laden.

#### Pool

Ein Pool kann als komplexer Verbraucher angesehen werden, der mehrere Einzelkomponenten umfasst, die getrennt gesteuert werden können:

- **Heizung** — thermisches Modell (Wasservolumen, Solltemperatur, Wärmeverlust); Tagesenergie ergibt sich aus dem Modell  
- **Filter** — Laufzeitbedarf (Stunden), ggf. natives Zeitfenster der Poolsteuerung; Earnie kann **zusätzlich** außerhalb dieses Fensters freigeben
- **Jetdüsen**

Für Was-wäre-wenn reichen Volumen, Solltemperatur und Filterstunden. Der Live-Betrieb braucht passende Merker für Temperaturen und Freigaben.

##### Hinweis

Pools haben meistens keine standardisierte Schnittstelle zur Anbindung an Smarthome-Systeme. Daher ist hier Eigenleistung gefragt oder mit erhöhtem Aufwand zu rechnen, wenn eine Anbindung durch Fachkräfte vorgenommen werden soll. Das Einsparpotenzial ist aber enorm!!

#### Allgemeine Verbraucher

Waschmaschine, Trockner, Geschirrspüler und ähnliche Geräte als **generische** Verbraucher:


| Rolle in Earnie      | Bedeutung für Sie                                                                                                                                                                                                                   |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Bekannt (known)**  | Feste / geplante Zeiten fließen als Grundlast ein — Earnie verschiebt sie nicht, berücksichtigt sie aber bei der Optimierung                                                                                                        |
| **Flexibel (flex)**  | Earnie darf den Start im erlaubten Zeiffenster verschieben                                                                                                                                                                          |
| **Manuell (manual)** | Sie planen auf der Seite *Manuelle Geräte*; Earnie gibt Start-Empfehlungen. In Live-Optimierung und Szenario-Explorer wird die typische Zeitplan-Last trotzdem wie bei *bekannt* mitgerechnet (Annahme: Sie starten wie empfohlen). |


Leistung und typische Laufzeit angeben. Optional später ein Loxone-Leistungsmerker für Ist-Anzeige und zur Kontrolle.

#### PV-Anlagen

Unter PV-Anlagen (Komponenten-Katalog):

- installierte Leistung (**kWp**)  
- Dachneigung und Ausrichtung (Azimut: Süd ≈ 0°, Ost negativ, West positiv)

Es können mehrere PV-Anlagen konfiguriert werden. Die konfigurierten PV-Anlagen können in den Szenarios selektiert und kombiniert werden. So kann in einer Was-Wäre-Wenn Analyse auch eine mögliche Erweiterung vorab analysiert werden.

Der Standort wird aus dem Hausprofil entnommen. Earnie nutzt frei verfügbare, historische Wetterdaten für die Ertragsprognose. 

#### Batteriespeicher

Folgende Parameter sind relevant:

- nutzbare Kapazität (kWh)  
- max. Lade-/Entladeleistung (kW)  
- Wirkungsgrad, min./max. SOC  
- optional **Verschleißkosten** (damit Earnie bei vielen Zyklen dies wirtschaftlich berücksichtigt)

Im Live-Betrieb steuert Earnie Ziel-SOC und Lade-/Entlade-Sollwerte über das Smarthome-System; die konkrete Wechselrichter-Logik bleibt in der Hausautomation bzw. im Wechselrichter selbst.

### Szenarienkonfigurator

Unter **Konfiguration → Szenarienkonfigurator** bauen Sie **Varianten** Ihres Haushalts, ohne den Live-Betrieb zu ändern.

Ein Szenario verknüpft typischerweise:

- Hausprofil  
- Batterie und/oder PV-Anlage(n)  
- Bezugs- und Einspeisetarif

**Es ist kein eigenes Szenario „ohne PV und ohne Batterie“ nötig:** Diese Referenz berechnet Earnie im Szenario-Explorer automatisch als Zeile **Historisch** (Live-Tarife, Last ohne PV/Speicher und ohne Flex-Optimierung). Sie müssen dafür kein zusätzliches Szenario im Szenarienkonfigurator anlegen.

Beispiele für Vergleiche:

- Ist-Zustand vs. größerer Speicher  
- mit einer PV vs. mehreren PVs  
- Fixpreis vs. Spot-Tarif  
- ohne Batterie, aber mit PV / verschiedene Batteriegrößen 
- ...

Das **Live-Szenario** (meist ID `live`) ist die Basis für den späteren Produktivbetrieb. Weitere Szenarien dienen der Analyse im Szenario-Explorer. Die Szenarien wählen Sie in einer **Liste** (nicht Dropdown); rechts daneben verschieben ↑/↓ die Reihenfolge der weiteren Szenarien (Live bleibt oben) — so erscheinen sie später in Listen und Kostenvergleichen (Dient nur einer verständlicheren Darstellung). 

Pro Szenario können Sie **Aktiv für Szenario-Explorer** setzen; deaktivierte Varianten werden in der Explorer-Rechnung übersprungen (vorhandene Ergebnisse werden dadurch ungültig). Mit **Eigene Referenz ohne Optimierung** legen Sie fest, ob für die Variante eine eigene Nicht-Opt-Referenz berechnet wird (Vorbelegung nach Tarif/PV-Heuristik; Batterie-only-Varianten teilen standardmäßig die Live-Referenz); der Earnie-Optimierungs-Algorithmus ist dann **NICHT** aktiv.

Tarife wählen Sie aus dem Tarifkatalog (Bezug/Einspeise). Nach der Auswahl zeigt der Editor die **Katalogparameter** des gewählten Tarifs (read-only). Bitte prüfen Sie diese Werte — es gibt **keine Garantie** für Vollständigkeit oder Aktualität. **Monatliche Fixkosten** (Lieferant-Grundpreis, optional Netz-/Messstellen-/Sonstige) fließen als **Näherung** in die Gesamt- und Monatskosten des Szenario-Explorers ein, nicht in die Live-Optimierung. Nach jedem SE-Lauf liegen **Fake-Jahresrechnungen** (Markdown) im Log-Ordner unter `invoices/` (Bezug/Einspeisung mit Ø Tarif- und Ø Ist-Preis, Katalogparameter am Ende). Nachrechnen: [Tarife und Preise nachrechnen](../referenz/tarife-quellen.md). Technik: [Preise & aWATTar](../konfiguration/preise.md).

### Szenario-Explorer (Was-Wäre-Wenn-Analyse)

Monatliche Stromkosten

*Szenario-Explorer: Monatliche Stromkosten im Vergleich (Was-wäre-wenn).*

Unter **Konfiguration → Szenario-Explorer** (erscheint nach ausreichender Planungs-Konfiguration).

Hier analysieren Sie **Langzeitvergleiche** typischerweise über 12 Monate (für Tests auch kürzer, z. B. nur März) zwischen Referenzen und Ihren Szenarien:

- **Historisch** — „nacktes Haus“ ohne PV und ohne Speicher (Live-Tarife, Last ohne Flex-Optimierung); **automatisch** berechnet, kein eigenes Szenario konfigurieren  
- **Referenzen ohne Optimierung** — je nach Szenario-Einstellung und Heuristik: Live-Referenz und ggf. eigene Spalten bei abweichendem Tarif/PV (steuerbar im Szenarienkonfigurator)  
- **optimierte Szenarien** — mit Earnie-Planung (Batterie/Flex, sofern im Szenario vorhanden)

Das ist **kein** tägliches Live-Cockpit und ändert keine Steuerwerte am Hub.

> Hinweis: Ergebnisse sind Modellrechnungen. Es gibt **keine Garantie**, dass Live-Einsparungen exakt den Simulationen entsprechen (Wetter, Verhalten, Tarifdetails, Hardwaregrenzen).

**WICHTIG**: Für eine Vergleichbarkeit versucht Earnie bei allen Szenarios (Ausnahme: Historisch-Szenario - siehe unten) den Gesamt-Jahres-Verbrauch **gleich** zu halten. Es kann zu kleinen Abweichungen kommen aufgrund der Optimierung. Etwaige Abweichungen werden angezeigt und können mit berücksichtigt werden. Earnie nimmt **KEINE** Verbrauchs-Einsparung vor!!!

#### Verbrauchsdaten generieren und sichten

Vor oder beim Start einer Explorer-Rechnung brauchen Sie eine belastbare **Lastgrundlage**:

- aus dem **Hausprofil** (Zeitpläne / thermische Modelle / Flex-Fenster), und/oder  
- aus historischen Verbrauchsdaten, falls vorhanden

Im Explorer bzw. zugehörigen Schritten können Sie Verbrauchsverläufe erzeugen und prüfen (Plausibilität, Monatsprofile). Stimmen Größenordnung und Tagesgang nicht, zuerst Profil und Geräte korrigieren — sonst sind Kostenvergleiche irreführend. Wenn sich Synthese-Parameter (Hausprofil/PV) geändert haben, müssen die Verbrauchsdaten **neu generiert** werden — sonst bleibt der Start der Rechnung gesperrt.

#### Szenario-Explorer ausführen

Optional: Checkbox **Verbrauchsdaten auf letzten Kalendermonat spiegeln (aktuelle Tarife)** — die Verbrauchsmuster werden nach Kalendermonat auf die letzten 12 vollständigen Monate vom jeweiligen Kalendertag gelegt, damit Spot-/Tarifpreise aktuell sind; die CSV auf der Festplatte bleibt unverändert. Auswahl wird in `scenario_explorer_conf` gespeichert.

1. Die Auswahl der gewünschten Szenarien kontrollieren und ggf. im Szenarien-Konfigurator anpassen.
2. Rechnung starten (kann je nach Umfang länger dauern).
3. Warten, bis die Auswertung fertig ist; Ergebnisse landen in der Laufzeitablage für den Explorer.

Anmerkung: Für minimale Rechenzeiten startet Earnie für jedes Szenario einen eigenen Prozess, der auf einem eigenen Prozessor-Kernel läuft. Bei Rechnern mit wenigen Kernels kann das zu verlängerten Rechenzeiten führen. Daher ist es auch nicht ratsam, den Szenarien-Explorer auf einer Hardware auszuführen, die für den späteren Live-Betrieb gedacht ist.

Die Zeile **Historisch** rechnet Earnie **automatisch**: Zuvor generierte Last im Tarifsetting des Live-Szenarios **ohne** PV und **ohne** Batterie (Dafür brauchen Sie kein eigenes Szenario im Szenarienkonfigurator anlegen). Zusätzliche Referenzen ohne Optimierung entstehen nach Heuristik bzw. der Einstellung **Eigene Referenz ohne Optimierung** (bei PV-Szenarien mit dem PV-Ertrag dieses Szenarios). Batterie und Lastverschiebung gehören zur **optimierten** Variante — nicht zum Historisch-Szenario.

#### Ergebnisse des Szenario-Explorers

Auswertung u. a.:

- **Gesamtkosten und -Verbrauch** (Tabelle: Jahres Verbrauch, Jahres Kosten, Δ vs. Live-Referenz, Hinweis)  
- **Kostenvergleich** monatlich (Referenz vs. optimierte Szenarien)  
- **Monatsverläufe** und Plausibilitätsansichten  
- Charts zu Leistung, Verbrauch und PV je nach gewählter Ansicht

Nutzen Sie die Ergebnisse als **Entscheidungsgrundlage** (Investition, Tarif), nicht als exakte Prognose der nächsten Stromrechnung. Es wird keine Gewähr dafür übernommen, dass die Ergebnisse genau so eintreffen werden.

##### Gesamtkosten und -Verbrauch: Jahres Verbrauch [kWh]

Die Spalte zeigt **nicht überall dieselbe Datenquelle**. Deshalb kann die Zeile **Historisch** andere kWh-Werte haben als Referenz- und Optimierungszeilen — das ist kein Anzeigefehler, sondern Absicht.


| Zeilentyp                            | Was die Spalte zählt                                                                                                             | Herkunft                                                                                                          |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| **Historisch (ohne Optimierung, …)** | Summe des **Ist-Verbrauchs** über den Laufzeitraum                                                                               | Live-Zählerdatei `cons_data` (`total_kw`, Stundenwerte)                                                           |
| **Referenz (…)** ohne Optimierung    | Summe der **Referenzlast** aller gebuchten Fenster (bei `sunrise_window`: Sunrise→Sunrise je ready_by-Tag; bei `fixed_24h`: 24h) | Hausprofil-Modell (`profile_spec`: Jahresverbrauch + Zeitpläne / Profile), sofern das Szenario ein Hausprofil hat |
| **Optimiertes Szenario**             | Summe der **gelieferten** Last (Grundlast + flexible Verbraucher) aller gebuchten Fenster                                        | MILP-Ergebnis; soll nahe an der Referenzlast liegen (Plausibilität)                                               |


**Warum Historisch oft abweicht**

1. **Ist vs. Modell:** Historisch spiegelt den gemessenen Hausverbrauch. Die übrigen Zeilen rechnen mit dem konfigurierten Hausprofil (Soll-Jahresverbrauch, Grundlast, Verbraucherprofile — inkl. manueller Geräte mit ihrer Default-Schedule). Weichen Ist und Modell ab (unvollständige CSV, anderer Jahresverbrauch, synthetische Profile), weichen auch die kWh-Zahlen ab.
2. **Kosten und kWh der Historisch-Zeile:** Die **€-Kosten** der Historisch-Zeile werden mit der Last des Live-Hausprofils (ohne PV/Batterie) und den Live-Tarifen berechnet. Die **kWh-Spalte** derselben Zeile kommt dagegen aus `cons_data`. Stimmen Ist und Modell nicht überein, passen € und kWh in dieser einen Zeile inhaltlich nicht 1:1 zusammen.
3. **PV und Batterie** ändern die Spalte „Jahres Verbrauch“ nicht: gezählt wird der **Hausverbrauch** (Last), nicht Netzbezug nach Abzug von PV/Speicher.
4. **Kleine Differenzen** zwischen Referenz und Optimierung derselben Szenario-Familie sind normal (Lastverschiebung, Toleranz der Plausibilitätsprüfung).

Zum Abgleich Ist vs. Modell: Hauskonfigurator / Leistungsprofil-CSV und die Tabellen **Gesamtkosten und -Verbrauch** sowie **Verbrauchsvergleich** im Explorer. Weicht der Jahresverbrauch einer Zeile um **mehr als 5%** von der **Live-Referenz** ab, erscheint in der Spalte **Hinweis** eine Warnung — dann über **Info / About → Kontakt** ein öffentliches Issue ohne Secrets melden bzw. die Config-ZIP privat an `support@earnie-hems.com` senden. Technische Details: [Betriebsmodi — Szenario-Explorer](../ui/betriebsmodi.md#gesamtkosten-und--verbrauch), [Historische Leistungsprofil-CSV](../konfiguration/verbrauchs-csv.md).

---



## Verbindung zu Smarthome

Wenn die Was-wäre-wenn-Analyse überzeugt, folgt die Anbindung an die Smarthome-Steuerung. Earnie liefert **Sollwerte und Freigaben**; die konkrete Schaltlogik (Wechselrichter, Wallbox, Relais) bleibt im Smarthome-Backend.

Backend wählen und Umschalten: [Adapter wählen](../einrichtung/adapter-wahl.md). Bei Loxone zusätzlich VI/VO-Vorlagen und Merker: [Loxone-Signale und Earnie-Library](../referenz/loxone-signale.md).

### Vorbereitung der Smarthome-Konfiguration

1. **Benutzer / Token** am Smarthome-Backend mit Rechten zum Lesen und Schreiben der benötigten IOs / Entities einrichten.
2. **Signale** anlegen bzw. zuordnen — u. a. Batterie-SOC und Leistungen, PV, Netz, Freigaben, E-Auto-Status. Beispielnamen (Loxone): [Loxone-Signale](../referenz/loxone-signale.md).
3. **Mapping in Earnie:** unter **Daemon Control → EHAL-Com** Merker bzw. HA-Entities den EHAL-Feldern zuweisen (`plant.ehal_bindings` / `consumers[].ehal_bindings`). Bei Loxone oft zuerst **Loxone-Import** im Hauskonfigurator, dann Mapping prüfen.
4. Wenn Jahres-Leistungsprofile berücksichtigt werden sollen (ist optional): CSV-Upload nuten ([Leistungsprofil-CSV](../konfiguration/verbrauchs-csv.md)) Offline-Daten für den Szenario-Explorerliegen später unter`cons_data_hourly.csv`.

Earnie liest Werte im Live-Betrief oft als Text mit Einheit (z. B. `3.5 kW`); die Einheit wird ignoriert.

Weitere Informationen dazu: [Loxone-Anbindung](../einrichtung/loxone-anbindung.md) · [Home Assistant + evcc](../einrichtung/ha-evcc.md) · [EHAL-Com](../ui/ehal-com.md).

### Live-Szenario (Szenarienkonfigurator)

Unter **Konfiguration → Szenarienkonfigurator** wählen Sie das Live-Szenario und die Entitäten (Hausprofil, Batterie, PV, Tarife). Die Bezeichnung des Live-Szenarios ist fest. 

Details dazu: [PV & Batterie](../konfiguration/batterie-pv.md), [Überblick](../konfiguration/ueberblick.md).

### EHAL-Com

Unter **Daemon Control → EHAL-Com**: Backend und Zugangsdaten, Live-Lesen/Schreiben, Silent- vs. Live-Modus, Mapping-Assistenten. Cutover: Lesen OK → Schreiben OK → Monitor plausibel. 

Vollständige Checkliste: [EHAL-Com](../ui/ehal-com.md).

Bei Loxone optional: `python -m scripts.verify_loxone_setup`.

---



## Live-Betrieb

Im Produktivbetrieb läuft der Optimierer dauerhaft (Docker: mit der UI; lokal: `python main.py`) im **15-Minuten-Takt** (oder auf Anforderung durch das Smarthome-Backend). Der Optimierungsalgo selbst nutzt derzeit **Stunden-Slots**.

Unter **Daemon Control → Optimierer-Dienst**: Start/Stop/Neustart und Dienst-Log (`earnie.log`).

### Monitor

Earnie Monitor

*Monitor (Chart 1): Vergangenheit, laufender Plan und Preisprognose in einem Sunset-2-Sunset-Fenster.*

Unter **Live-Cockpit → Monitor** (Sunset-2-Sunset): einheitliches Cockpit über Vergangenheit, Jetzt und Vorausschau (Sonnenaufgangs-Segmente). Chart 1 / SoC-Linien / Sankey: [Charts & Panels](../ui/charts.md) · Modus: [Betriebsmodi](../ui/betriebsmodi.md).

Kennzahlen zur Ersparnis beziehen sich auf den **vollen Planungshorizont** (Jetzt bis übernächster Sonnenaufgang).

#### Chart 1: SoC-Linien (Plausibilität)

Ab **Jetzt** können zwei SoC-Verläufe liegen — **SoC** (MILP-Plan) und **SoC BL Ziel** (Gegenprobe ohne smarte Batterie / ohne Preis-Lastverschiebung). Kurzfassung und Farben: [Charts & Panels — Chart 1](../ui/charts.md#chart-1-leistung-soc--preis).

### Manuelle Geräte

Unter **Live-Cockpit → Manuelle Geräte**: Laufzeiten und Startempfehlungen für Verbraucher mit Rolle **manuell**. Geplante Läufe erscheinen in Chart 1.

### Analyse Verbrauch & Kosten

Unter **Live-Cockpit → Analyse Verbrauch & Kosten** (nur mit `live_environment` und Live-Verbindung): Wochen-/Monats-/Jahresauswertung aus dem Produktiv-Log, Batterieflüsse, Swimspa-Auswertung. Details in der App und unter [Betriebsmodi](../ui/betriebsmodi.md).

---



## Kurz-Checkliste vom Initial-Zustand zum "Go-Live"

1. Installieren (Docker/Greenfield) und UI öffnen
2. Hauskonfigurator: Profil, Wärme, Auto, Pool, Geräte, PV, Batterie
3. Szenarienkonfigurator: Live-Szenario + Vergleichsvarianten
4. Szenario-Explorer: Verbrauch prüfen, Rechnung, Ergebnisse bewerten
5. Backend wählen ([Adapter](../einrichtung/adapter-wahl.md)), Zugang speichern, Mapping auf **EHAL-Com**
6. Live-Szenario + EHAL-Com (Silent → Live)
7. Daemon dauerhaft laufen lassen, Monitor beobachten, Feintuning

Bei Unklarheiten: Hover-Hilfe in `config.json` (Schema) und [docs/README.md](../README.md).