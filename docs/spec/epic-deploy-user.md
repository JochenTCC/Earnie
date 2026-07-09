Hier ist der Entwurf für ein **Epic**, das du direkt so in Cursor (z. B. als `.md`-Datei im Repository oder im Project Management) verwenden kannst, um die CI/CD-Pipeline umzusetzen.

---

# Epic: Automatisierte Multi-Plattform-Builds für GitHub Releases via GitHub Actions

## Status: 📋 Open

## Beschreibung

Da unser Produkt auf Python basiert , benötigt es standardmäßig eine Python-Laufzeitumgebung. Um Endnutzern auf Windows und macOS die Installation so einfach wie möglich zu machen und sie nicht zur Nutzung von Containern zu zwingen , sollen bei jeder neuen Veröffentlichung automatisch native, ausführbare Dateien (`.exe` und `.dmg`/`.app`) generiert und als Release-Assets bereitgestellt werden.

Da ein PyInstaller-Build nicht plattformübergreifend ist (Windows-Builds benötigen Windows, Mac-Builds benötigen macOS) , wird der Build-Prozess über eine GitHub Actions CI/CD-Pipeline automatisiert. Die Pipeline soll durch ein neues Git-Tag getriggert werden.

---

## 🎯 Ziele

1. 
**Automatisierung:** Kein manuelles Erstellen von Builds auf unterschiedlichen lokalen Betriebssystemen mehr.
2. 
**Benutzerfreundlichkeit:** Endnutzer können lauffähige Binärdateien direkt aus den GitHub Releases per Doppelklick starten.
3. 
**Multi-Plattform:** Automatische Bereitstellung von dedizierten Windows- und macOS-Paketen parallel zu den bestehenden Docker-Containern.

---

## 🛠️ Technische Anforderungen & Stack
* 
**Build-Tool:** `pyinstaller` (Paketierung von Python-Code & Abhängigkeiten in eigenständige Programme).
* 
**CI/CD Plattform:** GitHub Actions.
* 
**OS Runner:** `windows-latest` und `macos-latest`.

---

## 📋 Tasks (To-Do Liste für Cursor)

### Task 1: PyInstaller Konfiguration & Test

* [ ] `pyinstaller` im Projekt installieren und Abhängigkeiten in `requirements.txt` einfrieren.
* [ ] Build-Konfiguration festlegen: Entscheiden zwischen `--onefile` (einzelne Datei) und `--onedir` (Ordnerstruktur).
* [ ] Parameter `--windowed` (oder `-w`) für GUI-Anwendungen konfigurieren, um das Hintergrund-Terminal zu unterdrücken.
* [ ] Lokalen Test-Build auf Funktionalität prüfen.

### Task 2: GitHub Actions Workflow erstellen

* [ ] Eine neue Workflow-Datei unter `.github/workflows/release.yml` anlegen.
* [ ] Trigger-Event definieren: Der Workflow darf nur starten, wenn ein Tag gepusht wird, das dem Muster `v*` entspricht (z. B. `v1.0.0`).

### Task 3: Build-Jobs für Windows und macOS aufsetzen

* [ ] **Windows-Job:**
* Nutzen von `runs-on: windows-latest`.
* Python-Umgebung aufsetzen und `requirements.txt` installieren.
* PyInstaller ausführen, um die `.exe` zu generieren.

* [ ] **macOS-Job:**
* Nutzen von `runs-on: macos-latest`.
* Python-Umgebung aufsetzen und Abhängigkeiten installieren.
* PyInstaller ausführen, um die `.app` / `.dmg` zu generieren.

### Task 4: GitHub Release Erstellung und Asset-Upload integrieren

* [ ] Einen Schritt (Step) am Ende der Jobs hinzufügen, der ein neues GitHub Release erzeugt.
* [ ] Die generierten Binärdateien automatisch als ZIP/DMG-Artefakte an das erstellte Release anhängen.

---

## ✅ Akzeptanzkriterien (Definition of Done)

* [ ] Das Pushen eines neuen Git-Tags (z. B. `git tag v1.0.0 && git push --tags`) startet die GitHub Actions Pipeline automatisch.
* [ ] Die Pipeline läuft sowohl auf dem Windows- als auch auf dem macOS-Runner erfolgreich durch.
* [ ] Auf GitHub wird automatisch ein neues Release mit der korrekten Versionsnummer publiziert.
* [ ] Im Release sind die fertigen Download-Assets (z. B. `mein_produkt_windows.zip` und `mein_produkt_mac.dmg`) für den Endnutzer verfügbar.