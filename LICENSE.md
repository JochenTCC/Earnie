# Lizenz- und Nutzungsbedingungen: HEMS-Optimierer (Awattar & Loxone Integration)
**Status:** Entwurf v1.0 (Rechtliche & Strategische Vorlage)
**Lizenztyp:** Source-Available & Non-Commercial License (mit Datenbeitrags-Verpflichtung)

---

### Präambel
Diese Software wird als "Source-Available" (Quelloffen, aber mit Nutzungsbeschränkungen) zur Verfügung gestellt. Das Ziel ist es, der Smart-Home- und Open-Source-Community ein mächtiges Werkzeug zur Energiekostenoptimierung bereitzustellen, während gleichzeitig die kommerzielle Ausbeutung durch Dritte ausgeschlossen wird. Durch die Nutzung, Vervielfältigung oder Modifikation dieser Software erklärt sich der Nutzer mit den folgenden Bedingungen einverstanden.

---

### § 1 Erlaubte Nutzung (Eingeschränkte private Nutzung)
1. Die Nutzung der Software ist ausschließlich **natürlichen Personen für den privaten, nicht-kommerziellen Gebrauch in Privathaushalten** gestattet.
2. Der Betrieb ist auf die Steuerung von hauseigenen Komponenten (z. B. PV-Anlage, Heimspeicher, Wärmepumpe, private E-Auto-Ladestation) des eigenen Haushalts beschränkt.
3. Die Modifikation des Quellcodes für den eigenen, privaten Gebrauch ist gestattet, solange alle Modifikationen unter derselben Lizenz verbleiben (Copyleft-Prinzip für den privaten Bereich).

---

### § 2 Verbot der kommerziellen Nutzung und Verwertung
1. Jegliche kommerzielle oder gewerbliche Nutzung, Vermietung, Verpachtung, der Verkauf oder das Angebot der Software als Dienstleistung (SaaS, Managed Service) durch Dritte ist **strikt untersagt**.
2. Es ist Dritten untersagt, die Software oder Teile davon in kommerzielle Produkte, Hardware-Systeme (z. B. kommerziell vertriebene Energiemanager oder vorkonfigurierte Steuerungen) zu integrieren oder als Basis für ein eigenes Geschäftsmodell zu verwenden.
3. Ausnahmeregelungen und kommerzielle Lizenzen bedürfen der ausdrücklichen, schriftlichen Zustimmung des Urhebers/Rechteinhabers.

---

### § 3 Datenbeitrags-Verpflichtung für unbekannte Systeme
1. Da die Weiterentwicklung der Software auf der Erkennung und Integration einer Vielzahl von Hardware-Komponenten (Wechselrichter, Speicher, Ladestationen) basiert, verpflichtet sich der Nutzer zur Kooperation bei der Systemerweiterung.
2. Schließt der Nutzer Hardware-Komponenten an das System an, die im offiziellen Core-Repository noch nicht vollständig unterstützt werden oder für die keine Standard-Konfigurationsprofile vorliegen ("unbekannte Systeme"), erklärt er sich bereit, die für die Integration notwendigen technischen Parameter, Kommunikationsprotokolle (z. B. Modbus-Registerbelegungen) und anonymisierte Konfigurationsdaten dem Projekt zur Verfügung zu stellen.
3. Die Bereitstellung erfolgt in anonymisierter Form (ohne personenbezogene Daten wie Namen, IP-Adressen oder genaue Standorte).
4. **Kompensationsregelung (Entschädigung):** Als Gegenleistung für die erfolgreiche Bereitstellung funktionsfähiger Konfigurationsdaten für ein neues System erhält der Nutzer eine Entschädigung. Die Höhe, Art und Form dieser Entschädigung (z. B. in Form von Gutschriften auf Premium-Cloud-Dienste, Erlass von Abo-Gebühren oder eine direkte Aufwandsentschädigung) wird durch den Rechteinhaber separat definiert (siehe Konfigurationsparameter `[PARAM_DATA_COMPENSATION]`).

---

### § 4 Weitergabe und Abspaltungen (Forks)
1. Bei der Weitergabe des Quellcodes oder von Modifikationen muss dieser Lizenztext zwingend und unverändert mitgeführt werden.
2. Abspaltungen (Forks) im öffentlichen Raum (z. B. auf GitHub) müssen unter exakt denselben Bedingungen (Source-Available, Non-Commercial) geführt werden. Es ist untersagt, die Lizenz bei einem Fork zu ändern.

---

### § 5 Gewährleistungsausschluss und Haftungsbeschränkung
1. Die Software wird "wie besehen" (AS IS) und ohne jegliche ausdrückliche oder implizite Gewährleistung zur Verfügung gestellt.
2. Da die Software direkt in die Steuerung von elektrischen Großverbrauchern und Speichersystemen eingreift, liegt das Risiko der Nutzung vollständig beim Anwender. Der Urheber haftet nicht für Schäden an der Hardware (z. B. Batterieverschleiß, Fehlsteuerungen von Wärmepumpen), entgangene Einsparungen oder Strafen durch Netzbetreiber/Energieversorger.

---

## 8. Konfigurations-Notiz für das Business-Modell
Um diese Lizenzbedingungen rechtssicher mit unserem Abrechnungsmodell zu verknüpfen, müssen wir im Backend die Kompensations-Logik festlegen.

Bitte teile mir mit, ob wir hierfür einen Standard-Default-Wert hinterlegen sollen:
* **[PARAM_DATA_COMPENSATION]** (Gutschrift/Entschädigung für verifizierte Hardware-Profile): **[Noch offen, z. B. 3 Monate Gratis-Premium-Abo oder Einmalzahlung]**
