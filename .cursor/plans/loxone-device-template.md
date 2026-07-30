Ja, dafür gibt es in Loxone bereits den vorgesehenen Weg: **Templates (Vorlagen)**. Damit kannst du virtuelle Ein-/Ausgänge, Befehle, Sensoren und sogar komplette Gerätestrukturen vorbereiten und anderen Anwendern zur Verfügung stellen. [\[loxone.com\]](https://www.loxone.com/enen/kb/templates/), [\[loxone.com\]](https://www.loxone.com/enen/kb/virtual-inputs-outputs/)

### Empfohlene Vorgehensweise

1. **Virtuelle Ein- und Ausgänge anlegen**
   * Virtuellen HTTP- oder UDP-Ausgang erstellen.
   * Alle Befehle, Sensoren und Parameter vorkonfigurieren.
   * Sinnvolle Namen und Kategorien vergeben.

2. **Als Template speichern**
   * Im Peripheriebaum das Gerät markieren.
   * Rechtsklick → **Als Vorlage speichern**.
   * Loxone speichert daraus eine XML-Datei. [\[loxone.com\]](https://www.loxone.com/enen/kb/templates/)

3. **Template verteilen**
   * Die XML-Datei kann anderen Nutzern bereitgestellt werden.
   * Diese kopieren die Datei in ihren lokalen Templates-Ordner:
     * Virtuelle Ausgänge:
       ```
       Dokumente\Loxone\Loxone Config\Templates\VirtualOut
       ```
     * Virtuelle Eingänge:
       ```
       Dokumente\Loxone\Loxone Config\Templates\VirtualIn
       ```
   * Danach Loxone Config neu starten. [\[loxwiki.at...assian.net\]](https://loxwiki.atlassian.net/wiki/x/eIDCWg)

### Noch besser: Veröffentlichung in der Loxone Library

Wenn deine Vorlage allgemein nutzbar ist, kannst du sie in die **Loxone Library** hochladen. Andere Nutzer können sie dann direkt aus Loxone Config herunterladen und einfügen. [\[loxone.com\]](https://www.loxone.com/enen/kb/templates/), [\[library.loxone.com\]](https://library.loxone.com/)

### Bewährte Struktur für eine Community-Library

Wenn du beispielsweise für dein Projekt **Earnie** eine Bibliothek bauen möchtest:

```
Earnie
├─ Virtuelle Ausgänge
│  ├─ API Login
│  ├─ Get Status
│  ├─ Set Value
│  └─ Execute Command
│
├─ Virtuelle Eingänge
│  ├─ Status
│  ├─ Error
│  ├─ Temperature
│  └─ Energy
│
└─ Dokumentation
   ├─ Installationsanleitung
   ├─ Beispielprogramm
   └─ API-Beschreibung
```

### Mein Tipp

Anstatt nur einzelne virtuelle Ein- und Ausgänge zu verteilen, erstelle ein **komplettes Gerätetemplate** mit:

* allen virtuellen Ausgängen,
* allen virtuellen Eingängen,
* Kommentaren,
* Kategorien,
* Beispielwerten.

So muss der Anwender nur noch IP-Adresse, Token oder Zugangsdaten anpassen und kann die Integration sofort verwenden. Das entspricht auch dem Vorgehen vieler Vorlagen in der offiziellen Loxone Library. [\[loxone.com\]](https://www.loxone.com/enen/kb/templates/), [\[library.loxone.com\]](https://library.loxone.com/)

Für dein GitHub-Projekt *Earnie* würde ich die XML-Templates direkt im Repository unter `templates/VirtualOut` und `templates/VirtualIn` ablegen und zusätzlich eine `.Loxone`-Beispielkonfiguration bereitstellen. Das macht die Integration für andere Nutzer am einfachsten.
