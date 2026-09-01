# Architektur

## Prozesse

| Prozess | Verantwortung |
|---|---|
| Kern (Rust) | Fenster, Tray, Aktualisierung, Prozessaufsicht, Geheimnisse |
| Dienst (Python) | Browsersteuerung, Registrierung, Ablauflogik, Auswertung |
| Oberfläche (Svelte) | Anzeige, Bedienung, Ereignisstrom |

## Startablauf

1. Der Kern holt das Dienst-Token aus dem Anmeldeinformationsspeicher oder
   erzeugt es beim ersten Mal.
2. Der Kern liest `%APPDATA%\Zahnputztracker\runtime.json`. Antwortet dort ein
   Dienst auf `/health` mit dem Token, wird er übernommen.
3. Sonst startet der Kern den Dienst, schreibt das Token auf dessen
   Standardeingabe und liest eine Zeile Handschlag mit dem Port zurück.
4. Eine Aufsicht prüft den Dienst im Sekundentakt. Nach drei Fehlversuchen gilt
   er als tot, wird beendet und neu gestartet; die Oberfläche erfährt das über
   das Ereignis `service-status`.

## Trennlinie: Code gegen Zuordnung

Diese Linie ist bewusst dokumentiert, damit sie sich später an einer Stelle
verschieben lässt.

**Im Code (nicht konfigurierbar):** Ablaufrahmen, Reihenfolge der Abarbeitung,
Schutz vor doppelter Ausführung, Statusverwaltung, Wiederherstellungsstufen,
Aufzeichnung und Auswertung.

**In der lokalen Zuordnung (ohne Codeänderung veränderbar):** welche Elemente
einer Seite eine Rolle tragen, wie sie erkannt werden, welche Zustände es gibt,
welche Aktionskette ein Zustand auslöst, alle Adressen und Textwerte.

Im Code steht keine Adresse, kein Selektor und kein Textinhalt einer Zielseite.

## Ablage (Phase 1)

| Inhalt | Ort | Bemerkung |
|---|---|---|
| Einstellungen | `%APPDATA%\Zahnputztracker\config.json` | eine Datei, atomar geschrieben, geprüft beim Lesen |
| Datenbank | `%APPDATA%\Zahnputztracker\data.sqlite` | führende Datenquelle, WAL-Modus |
| Geheimnisse | Windows-Anmeldeinformationsspeicher | nur setzen, löschen, abfragen ob vorhanden |

Die Oberfläche kann ein Geheimnis nie zurücklesen. Erlaubt sind ausschließlich
die zwei Namen `account-password` und `composer-api-key`; alles andere wird
abgewiesen.

## Statuswerte

| Status | Bedeutung | gilt als erledigt |
|---|---|---|
| `offen` | gesehen, noch nicht bearbeitet (intern) | nein |
| `kontaktiert` | Versand bestätigt | ja |
| `unklar` | Versand ausgelöst, Bestätigung fehlt | ja (nur der Benutzer entscheidet) |
| `uebersprungen` | Ausschluss erkannt, mit Grund | ja |
| `bereits_angefragt` | von der Seite als erledigt gemeldet | ja |
| `fehlgeschlagen` | Fehler, mit Verweis auf den Vorfall | nein |
| `wartet_auf_freigabe` | Testmodus, noch nicht entschieden | nein |

Beim Start prüft der Dienst die Tabelle `dispatch`. Ein Vermerk ohne Bestätigung
bedeutet Absturz zwischen Versand und Bestätigung: der Eintrag wandert auf
`unklar`, nie auf `kontaktiert`, und wird nie von selbst erneut versendet.

## Browser-Betrieb

Zwei permanente Instanzen, beide mit genau einem Tab, beide über dieselbe
Verbindung. Die Trennung ist eine harte Anforderung: die suchende Instanz ist
nicht angemeldet, die arbeitende ist es.

| Instanz | Profil | Fingerabdruck |
|---|---|---|
| Such-Browser | wird bei jedem Anwendungsstart verworfen | dadurch bei jedem Start neu |
| Sitzungs-Browser | dauerhaft | einmal erzeugt, in `launch-options.json` im Profil festgehalten und danach wiederverwendet |

Beide Profile liegen unter `%LOCALAPPDATA%\Zahnputztracker\profiles\`, das
Browser-Programm unter `%LOCALAPPDATA%\Zahnputztracker\browser\`. Es wird beim
ersten Bedarf von der offiziellen Quelle geladen; der Fortschritt läuft über den
Ereignisstrom in die Oberfläche.

### Ein-Tab-Regel

Verweise werden nie angeklickt, es wird immer über die Adresszeile navigiert.
Zusätzlich lauscht jede Instanz auf neue Seiten: entsteht doch eine, wird sie
sofort geschlossen und gezählt. Der Zähler steht in der Oberfläche, das Ereignis
im Strom.

### Sichtbarkeit: wer macht was

Die Aufteilung folgt der Regel, dass Fensterverwaltung Sache des Kerns ist.

| Teil | Aufgabe |
|---|---|
| Dienst (Python) | kennt den gewünschten Zustand je Instanz und meldet ihn samt Prozessliste unter `/browser/windows` |
| Kern (Rust) | fragt diesen Zustand viermal je Sekunde ab und setzt ihn um |

Ein Browserlauf besitzt mehrere Fenster, die meisten davon Hilfsfenster, die nie
sichtbar sein sollen. Deshalb blendet der Kern nur aus, was gerade sichtbar ist,
und blendet nur das wieder ein, was er selbst ausgeblendet hat. Eingeblendet wird
ohne Aktivierung, damit kein Fenster den Fokus stiehlt.

Weil der gewünschte Zustand im Dienst liegt, können Oberfläche und Tray dasselbe
schalten, ohne sich gegenseitig zu überschreiben.

### Anhalten

Anhalten ist ein Schalter im Dienst. Beide Browser bleiben offen und behalten
ihren Zustand, es wird nichts neu geladen. Das Tray zeigt den Zustand an und
schaltet ihn um.


## Seitenwissen: Rollen, Auswahlmodus, Ansichten

### Die Trennlinie

Im Code steht der Rahmen: wie ein Element beschrieben wird, in welcher
Reihenfolge Merkmale geprüft werden, wie gespeichert und zurückgesetzt wird.
In der Registrierung steht das Seitenwissen: welche Elemente es gibt und woran
man sie erkennt. Kein einziger Selektor, kein Attributname und kein Text der
Zielseite steht im Programm.

Eine Verschiebung dieser Linie bleibt dadurch eine Änderung an einer Stelle:
neue Merkmalsarten kommen in `service/picker/overlay/overlay.js` (Erzeugen und
Suchen) und in `service/registry/model.py` (Prüfen und Speichern) dazu, sonst
nirgends.

### Rollen

Eine Rolle ist ein abstrakter Name für etwas auf der Seite. Sie hat eine
neutrale Kennung, einen frei wählbaren Anzeigenamen, die Instanz, zu der sie
gehört, das Feld `menge` (`einzel` oder `liste`), eine Notiz, optional ein
Attribut als Kennungsträger und die priorisierte Liste ihrer Merkmale.

Die Anwendung liefert einen Grundkatalog neutral benannter Rollen mit. Er
enthält bewusst kein einziges Merkmal: nach dem Übernehmen kann die Anwendung
weiterhin nichts, bis angelernt wurde. Eigene Rollen sind jederzeit möglich und
werden technisch gleich behandelt.

### Erkennungsmerkmale und Degradierung

Zu jedem ausgewählten Element werden Merkmale in dieser Reihenfolge erzeugt und
geprüft:

| Reihenfolge | Merkmal |
|---|---|
| 1 | Datenattribute (Prüfkonventionen zuerst) |
| 2 | Rolle und zugänglicher Name |
| 3 | Sichtbarer Text |
| 4 | Kennung, sofern sie nicht erzeugt wirkt |
| 5 | Verkürzter Strukturpfad (letzte Rückfallebene) |

Das erste treffende Merkmal gilt. Musste ausgewichen werden, ist das eine
Degradierung: sie wird gemeldet und angezeigt, hält aber nichts an. Sie ist das
Frühwarnsystem für Layout-Änderungen.

Feste Auflösungsregel bei mehreren Treffern: gibt es das Element doppelt und ist
nur eines sichtbar, gilt das sichtbare, und der Doppeltreffer wird protokolliert.
Sind mehrere sichtbar, ist das ein unbekannter Zustand und es geschieht nichts.
Ein nur verborgen vorhandenes Element gilt nie als Treffer.

### Auswahlmodus

Das Overlay wird über `add_init_script` in beide Instanzen injiziert und ist
darum nach jeder Navigation wieder da. Element anfahren hebt es hervor, die
Pfeiltasten hoch und runter wechseln die Ebene, links und rechts den Nachbarn,
Enter übernimmt, Esc bricht ab. Zusätzlich wirkt Strg+Umschalt+Y im Fenster.

Das Zuordnungspanel liegt in der Anwendung, nicht in der Seite. Je weniger das
Overlay in der Seite tut, desto kleiner das Risiko, dass es in gespeichertem
Material auftaucht. Jeder Knoten des Overlays trägt ein Kennzeichen; vor einem
Bild wird es unsichtbar geschaltet, aus jeder gespeicherten Kopie wird es
entfernt.

### Auswahl auf einer gespeicherten Kopie

Eine Korrektur soll möglich sein, ohne die Situation neu herzustellen. Dafür
wird die gespeicherte Kopie örtlich geöffnet, vorher werden alle Skripte und
Ereignisbehandler daraus entfernt, und der Browser darf währenddessen nichts
aus dem Netz laden. Die Kopie sieht deshalb ungestaltet aus; es geht um die
Struktur, nicht um das Aussehen. Nach der Reparatur hebt "Netzsperre aufheben"
die Sperre wieder auf.

### Versionierung

Jede Änderung schreibt eine neue Fassung, die vorherige wandert ins Archiv.
Zurücksetzen holt eine alte Fassung als neue Fassung zurück, verwirft also
nichts. Export und Import laufen über eine Datei je Instanz.

Alles liegt in `%APPDATA%\Zahnputztracker\registry`, nie im Projektordner.

### Seiten-Katalog (Stufe 1)

Bei jedem Seitenwechsel wird eine strukturelle Signatur der Ansicht gebildet:
welche Arten von Elementen sichtbar sind, nicht was sie sagen. Eine unbekannte
Signatur wird einmal mit Kopie, Bild, Adresse, Zeitpunkt und auslösender Aktion
gesichert, eine bekannte erhöht nur den Zähler und vermerkt den Weg hinein.

Der Katalog ist reiner Beobachter: schlägt er fehl, läuft der Betrieb weiter.
Die Karte über dieses Material kommt später, das Material selbst wird ab jetzt
gesammelt.

### Übernahme eines laufenden Dienstes

Schließt du nur das Fenster, läuft der Dienst weiter und wird beim nächsten
Start übernommen. Übernommen wird aber nur ein Dienst, der aus demselben
Codestand läuft: der Dienst meldet unter `/health` eine Kennzeichnung seines
Standes (beim Entwickeln der jüngste Änderungszeitpunkt der Dienstdateien, im
Paket die Fassung), der Kern vergleicht sie mit seiner Erwartung.

Passt sie nicht, wird der alte Dienst über die Prozesskennung aus `runtime.json`
beendet und ein neuer gestartet. Ohne diese Regel läuft die Anwendung nach einer
Codeänderung stillschweigend mit dem alten Stand weiter, und man sucht den
Fehler an der falschen Stelle. Aus demselben Grund darf auch "Dienst neu
starten" einen Dienst beenden, den der Kern nicht selbst gestartet hat.

Der Fehlerkanal des Dienstes wird mitgelesen und landet in
`%APPDATA%\Zahnputztracker\logs\dienst-fehler.log`. Eine Pipe, die niemand
leert, blockiert den schreibenden Prozess, sobald sie voll ist.

## Zustände, Bedingungen und Aktionen

Der Ablauf ist keine Schrittfolge im Code. Er ergibt sich aus Zuständen, die du
selbst definierst, und der Kette von Aktionen, die zu einem Zustand gehört.

**Bedingungen.** Eine Bedingung ist immer dieselbe Art von Aussage: Rolle X ist
sichtbar, oder Rolle X ist nicht sichtbar. Alle Bedingungen der Liste müssen
zutreffen. Zusätzlich gibt es eine optionale ODER-Gruppe, von der mindestens
eine zutreffen muss. Mehr Logik gibt es bewusst nicht. Jede Bedingung trägt ihre
Art mit sich, damit eine weitere Art später dazukommen kann, ohne dass ein
gespeicherter Zustand umgeschrieben werden muss.

**Erkennung.** Vor jeder Aktionskette werden alle eingeschalteten Zustände
geprüft. Jede beteiligte Rolle wird dabei genau einmal auf der Seite gesucht.
Trifft genau einer zu, wird er genommen. Treffen mehrere zu, entscheidet die
Priorität (die kleinere Zahl ist die stärkere). Haben die beiden stärksten
dieselbe Zahl, wird nicht gewürfelt: das ist ein unbekannter Zustand. Ebenso,
wenn eine Rolle mehrere sichtbare Treffer hat oder keiner der Zustände passt.
Jedes Anhalten meldet, woran es lag.

**Ausführungsmodus.** Jede einzelne Aktion trägt ihren Modus: `automatisch`,
`freigabe` (die Anwendung zeigt, was sie tun würde, und wartet) oder `manuell`
(du erledigst es selbst im eingeblendeten Fenster und bestätigst). Solange eine
Freigabe offen ist, läuft nichts anderes weiter. Der Streifen dafür steht über
allen Reitern, weil er den ganzen Ablauf betrifft.

**Quellen.** Ein Text, den eine Aktion einträgt, steht nie im Zustand selbst. Er
kommt aus einem Konfigurationswert, einem Antwort-Paar, dem
Anmeldeinformationsspeicher (`geheimnis`) oder dem Variablenraum. Ein Geheimnis
wird erst im Moment des Eintragens geholt und taucht in keiner Meldung, keiner
Beschreibung und keinem Bericht auf. Die Einstellungen `Zugangskennung` und
`Startadresse` sind als Konfigurationswerte direkt ansprechbar.

**Variablenraum.** Was eine Aktion ausliest, landet unter einem Namen im
Variablenraum. Beide Browser lesen aus demselben Raum. Er ist nicht dauerhaft
und wird zu Beginn jedes Vorgangs geleert, damit kein Wert des vorigen Eintrags
in das nächste rutscht.

**Vorlagen.** Die mitgelieferten Zustands-Vorlagen liegen in
`%APPDATA%\Zahnputztracker\vorlagen.json`. Sie enthalten keine Erkennungs-
merkmale, sondern nur Bedingungen und Ketten über den neutralen Rollen des
Grundkatalogs. Eine Vorlage tut nichts, bis du sie lädst; danach ist sie ein
gewöhnlicher Zustand. Einzelne Vorlagen lassen sich löschen, ein Schalter
schaltet die Vorlagen komplett ab, und der mitgelieferte Satz lässt sich
wiederherstellen.

**Noch nicht angebunden.** Die Aktion "Anschreiben generieren" hält definiert
an, solange die Textgenerierung fehlt (nächste Ausbaustufe). "Als kontaktiert
dokumentieren" und "Überspringen" schreiben in die Datenbank, brauchen aber
einen laufenden Vorgang mit einer Kennung; ohne den halten sie ebenfalls an.

## Anmeldung und ein Vorgang von Anfang bis Ende

**Die Trennlinie steht in einer Datei.** `service/flow/contract.py` listet
vollständig auf, welche Rollennamen der Ablauf kennt: Merkmal für den
angemeldeten Zustand, Kennungsfeld, Geheimnisfeld, Knopf für die Anmeldung,
Merkmal und Feld für einen Code, Merkmal für die fertig geladene Seite, Merkmal
für einen bereits erledigten Eintrag, Knopf zum Öffnen des Formulars, Textfeld,
Absende-Element, Bestätigungs-Merkmal. Dazu zwei Familien: jede Rolle, deren
Kennung mit `exclusion_marker` beginnt, ist ein Grund, einen Eintrag in Ruhe zu
lassen; jede Rolle, deren Kennung mit `form_field` beginnt, ist ein Formularfeld
und wird aus dem Antwort-Paar gefüllt, das an der Rolle hinterlegt ist. Was
hinter einem Namen steckt, entscheidest allein du im Picker. Fehlt eine
Pflichtrolle, wird sie beim Namen genannt, statt dass etwas versucht wird.

**Anmeldung.** Vor jedem Vorgang wird der Anmeldestand über das angelernte
Merkmal geprüft. Ist er weg, läuft der Anmeldeablauf: Kennung aus den
Einstellungen, Geheimnis aus dem Anmeldeinformationsspeicher, abschicken. Kommt
eine Code-Abfrage, hält alles an und fragt in der Anwendung nach dem Code (der
Code steht in keinem Ereignis und in keiner Datei). Nach drei erfolglosen
Versuchen wird endgültig angehalten, jeder Fehlversuch wird als Vorfall
festgehalten.

**Ein Vorgang.** Die vierzehn Schritte stehen in `service/flow/contact.py` in
genau der Reihenfolge der Spezifikation. Wichtig sind die Ausgänge:

| Situation | Status | Wird erneut angeboten |
|---|---|---|
| Ausschluss-Merkmal sichtbar | übersprungen | nein |
| Seite meldet: bereits erledigt | bereits_angefragt | nein |
| Nachrichtenfeld erscheint nicht | übersprungen (nicht mehr verfügbar) | nein |
| Kein Text vom Anbieter | fehlgeschlagen, mit Vorfall | ja |
| Abgesendet, keine Bestätigung | unklar, mit Vorfall | nein, du entscheidest |
| Bestätigt | kontaktiert | nein |
| Freigabe abgelehnt | offen | ja |

**Nur nach Bestätigung.** Unmittelbar vor dem Absenden wird ein Vermerk
geschrieben, nach der Bestätigung wird er bestätigt. Ein Vermerk ohne
Bestätigung (Absturz, Stromausfall) landet beim nächsten Start in der Liste
"Status unklar". Dort gibt es zwei Knöpfe: als erledigt vermerken oder erneut
bearbeiten. Von allein wird nie ein zweites Mal gesendet.

**Testmodus.** Ist er an (Vorbelegung), wird zweimal gefragt: einmal vor dem
Erzeugen des Textes (Eintrag, geplante Formularfelder, Bild der Seite) und
einmal vor dem Absenden (der fertige Text). Solange die erste Frage offen ist,
steht der Eintrag auf "wartet_auf_freigabe" und gilt nicht als erledigt. Ein
abgelehnter Vorgang bleibt offen und wird beim nächsten Mal wieder vorgelegt.

**Anschreiben.** Der Anbieter steckt hinter einer Funktion
(`service/text/base.py`), ein zweiter Anbieter ist eine Funktion und ein
Eintrag mehr. Der Prompt kommt aus den Einstellungen und kennt die Platzhalter
`{{seitentext}}`, `{{adresse}}`, `{{titel}}` und `{{wert:Bezeichnung}}`. Ein
unbekannter Platzhalter ist ein Fehler und kein Text mit Klammern darin.
Antwortet der Anbieter nicht, leer oder zu spät, wird nichts gesendet und nichts
ersetzt.

**Vorfälle.** Ein Vorfall liegt in `%APPDATA%\Zahnputztracker\incidents\` als
eigener Ordner: `bericht.md` (lesbare Zusammenfassung), `daten.json`,
`seite.html` (Kopie ohne Overlay und ohne Skripte), `bild.png`, `text.txt`. Der
wichtigste Teil des Berichts ist die Liste der gefundenen und der erwarteten,
aber nicht gefundenen Rollen. Bildsequenz, Trace-Archiv und Referenzwerte kommen
mit der nächsten Ausbaustufe dazu.

## Beobachtung: Messen, Schwellen, Aufzeichnen (Phase 6)

Die Anwendung kann nicht beurteilen, ob ein Zustand fachlich falsch ist.
Sie erkennt nur, dass ein Vorgang ungewöhnlich lange dauert oder gar nicht
endet. Alles hier dient deshalb einem einzigen Zweck: einem Menschen später
den Vergleich zwischen einem auffälligen und einem funktionierenden
Durchlauf zu ermöglichen.

### Vorgänge als Messpunkte

Jede gemessene Handlung ist ein Vorgang mit festem Namen aus einer
geschlossenen Liste (`service/telemetry/spans.py`). Namen werden nie zur
Laufzeit zusammengesetzt, damit eine Statistik über Monate vergleichbar
bleibt. Gemessen wird heute: `item.open`, `auth.check`, `auth.login`,
`form.open`, `form.fill`, `compose.generate`, `submit.send`,
`submit.confirm`, `state.detect`. Die vier `search.*`-Namen sind
vorbereitet und werden mit dem Suchzyklus belegt.

Anfang und Ende jedes Vorgangs gehen in zwei Richtungen: als Ereignis an
die Oberfläche und als Zeile in die Tagesdatei unter
`%APPDATA%\Zahnputztracker\logs\JJJJ-MM-TT.jsonl`. Jede Zeile ist für sich
gültig, damit ein Absturz höchstens diese eine Zeile kostet.

Solange eine Freigabe offen ist, steht die Uhr aller laufenden Vorgänge
still. Sonst würde ein Mensch, der sich Zeit lässt, als Blockade gelten.

### Referenzwerte

Je Vorgangsname, Browser und Tagesstunde ein gleitendes Fenster der letzten
200 Messungen, bewertet über Median und mittlere absolute Abweichung. Der
Median ist gegen einzelne Ausreißer unempfindlich; ein einzelner Hänger
vergiftet die Referenz also nicht. Hat eine Stunde noch zu wenige Werte,
gilt der Gesamtwert des Browsers.

Regeln, die bewusst so und nicht anders sind:

- Die allererste Messung eines Vorgangs zählt nicht (kalter Start).
- Bewertet wird erst ab acht Messungen, vorher wird nur gesammelt.
- Auch auffällige Werte fließen ein, damit die Referenz dauerhaft
  veränderten Bedingungen folgt.
- Die Werte liegen in `stats\laufzeiten.json` und überleben einen Neustart.

### Zwei Schwellen

| Schwelle | Auslöser | Was passiert |
|---|---|---|
| weich | über dem Referenzbereich des Namens | Zustandserfassung, während der Vorgang noch hängt; Zyklus zur Speicherung vorgemerkt; der Ablauf läuft weiter |
| hart | absolutes Zeitlimit je Name (Einstellungen) | zweite Erfassung in denselben Ordner, Bildfolge und Aufzeichnungen dazu, Benachrichtigung, Wiederherstellung |

Die weiche Erfassung ist die wichtigere. Bis zum harten Limit hat die
Zielseite oft schon eine eigene Fehlermeldung nachgeladen, sodass nur noch
die Folge und nicht die Ursache sichtbar wäre. Der Vergleich beider
Erfassungen zeigt, ob sich die Seite verändert hat oder unverändert
stehen blieb.

Beide Schwellen prüft ein eigener Wachhund im Sekundentakt gegen die
laufenden Vorgänge, nicht gegen die beendeten. Der eigentliche Fehlerfall
ist der Vorgang, der nie endet.

### Aufzeichnungen

Kein Dauervideo. Statt dessen drei Dinge:

- **Bildfolge**: ein Bild alle zwei Sekunden, die letzten sechzig im
  Arbeitsspeicher. Sie deckt die zwei Minuten vor einem Ereignis ab und
  wird erst bei einer Schwelle auf die Platte geschrieben.
- **Zyklus-Aufzeichnung**: jeder Vorgang (Anmeldung, Kontaktvorgang) wird
  aufgezeichnet und wieder verworfen, sofern nichts daran auffällig war.
  Auffällige Zyklen bleiben, zusammen mit den zwanzig davor.
- **Referenzdurchlauf**: je Vorgangsname wird ein erfolgreicher Durchlauf
  dauerhaft vorgehalten und in jeden passenden Vorfallsordner kopiert.
  Damit ist ein Soll-Ist-Vergleich auch dann möglich, wenn der Fehler seit
  Stunden anhält.

Die Bildfolge fotografiert nie, während ein Vorgang auf der Seite
arbeitet. Ein Bildschirmfoto hält die Seite kurz an, und ein Klick, der in
diesen Moment fällt, wartet darauf. Eine Stoppuhr, die den Läufer
gelegentlich stellt, wäre schlechter als eine Lücke in den Bildern; der
Moment selbst wird ohnehin von den Erfassungen an den Schwellen
festgehalten. Zusätzlich bekommt jedes Bild sein Zeitlimit im Browser
selbst, nicht nur im Wartenden.

### Ein Vorfallsordner

Ein Ordner je Vorfall unter `%APPDATA%\Zahnputztracker\incidents\`, benannt
nach Zeitpunkt und Vorgang:

```
bericht.md          lesbare Zusammenfassung, ohne Werkzeugkenntnis
daten.json          alles Folgende als Daten
bild.png            Bildschirmfoto der ersten Erfassung
seite.html          Kopie der Seite (ohne Overlay, ohne Skripte)
text.txt            sichtbarer Text
stufe2-hart\        zweite Erfassung, gleiche Dateien
bilder\             Bildfolge aus dem Ringpuffer
aufzeichnung\       dieser Zyklus und die davor
referenz\           letzter erfolgreicher Durchlauf desselben Vorgangs
```

Kern des Berichts ist nicht die Laufzeit, sondern die Liste der Rollen:
welche gefunden wurden und welche erwartet, aber nicht gefunden. Das zeigt
in der Regel schon ohne Öffnen einer Aufzeichnung, ob ein Layout geändert
wurde, eine Abfrage dazwischenkam oder die Seite gar nicht geladen hat.

### Wiederherstellung

Vier Stufen in dieser Reihenfolge, dazwischen jeweils die Zustandsprüfung
als Urteil: Zustand erneut prüfen, Seite neu laden, zur Startadresse
zurückkehren, Anmeldung prüfen. Hält keine davon, wird angehalten und
benachrichtigt. Ist noch kein Zustand angelernt, gilt als Erfolg nur, dass
die Seite überhaupt antwortet; mehr wäre eine Behauptung ohne Grundlage.

Die einzige Handlung, die nie automatisch wiederholt wird, ist das
Absenden. War ein Versand offen, als die Wiederherstellung ansetzte, geht
der Eintrag auf die Liste „Status unklar“ und wartet auf eine Entscheidung.

### Speicher

Aufbewahrung: Protokoll 30 Tage, Vorfälle 7 Tage, dazu eine harte
Obergrenze für alle Aufzeichnungen (Vorbelegung 500 MB). Wird sie erreicht,
werden die ältesten Aufzeichnungen gelöscht, bis es wieder passt. Diese
Regel steht über allen anderen: die Anwendung darf wegen eines vollen
Datenträgers nicht stehen bleiben.

### Bericht

Markdown ist Ausgabeformat, kein Speicherformat. Der Bericht wird auf
Knopfdruck aus der Tagesdatei erzeugt und liegt unter `reports\`. Er lässt
sich für jeden noch vorhandenen Tag erneut erzeugen.

## Der Suchzyklus (Phase 7)

Der Suchlauf ist ein einziger, langer Auftrag. Er läuft, bis er angehalten
wird, und arbeitet immer denselben Zyklus ab:

1. Ergebnisseite neu laden (`search.reload`)
2. Zufällige Wartezeit zwischen dem eingestellten Minimum und Maximum
3. Gesamte sichtbare Trefferliste lesen (`search.parse_results`)
4. Kennungen gegen die Datenbank abgleichen
5. Jeden neuen Eintrag übergeben und vollständig bearbeiten
6. Erst danach der nächste Zyklus

Ausgewertet wird die **ganze** sichtbare Liste, nie eine feste Anzahl
oberster Zeilen: mehrere Einträge werden regelmäßig gleichzeitig
eingestellt. Die Liste steht neueste zuerst, bearbeitet wird deshalb in
umgekehrter Reihenfolge (ältester neuer Eintrag zuerst, weil er die
geringste Restzeit hat).

### Die Kennung eines Eintrags

Die Trefferliste liefert Verweise. Um zu entscheiden, ob ein Eintrag schon
bearbeitet wurde, muss aus dem Verweis etwas Stabiles werden: ganze
Adressen tragen Parameter, die sich von Aufruf zu Aufruf unterscheiden.

Die Regel dafür kommt nicht aus dem Code, sondern aus der Adressvorlage in
den Einstellungen. Sie enthält genau einen Platzhalter `{kennung}`; was an
seiner Stelle steht, ist die Kennung. Damit steht keine Spur der Zielseite
im Repository, und die Regel lässt sich an einem einzigen Feld ändern.

Ein Verweis, auf den die Vorlage nicht passt, wird **nicht** gedeutet. Er
wird gezählt und gemeldet („Verweise ohne erkennbare Kennung"), der
Eintrag dahinter bleibt liegen. Eine geratene Kennung könnte dazu führen,
dass derselbe Eintrag zweimal angeschrieben wird, und das ist der eine
Fehler, den diese Anwendung nicht machen darf.

Die Rolle `item_link` wird mit der Menge `liste` angelernt und darf auf
dem Verweis selbst oder auf der Zeile sitzen, die ihn enthält. Enthält
eine Zeile mehrere Verweise, wird keiner davon ausgewählt, sondern die
Zeile übersprungen und gezählt.

### Anhalten und Zurückstellen

Der Zyklus wartet (er scheitert nicht), solange eine Freigabe offen ist
oder der Betrieb pausiert. Beides zählt nicht als Fehler.

Scheitert ein Zyklus, wird das gezählt und nach einer kurzen Pause erneut
versucht. Nach drei Fehlschlägen in Folge hält der Suchlauf an und
benachrichtigt: das ist eine Lage, die ein Mensch ansehen muss.

Ein Eintrag, der ohne abschließenden Status endet (Fehler, abgelehnte
Freigabe, kein Text erzeugt), wird für den laufenden Suchlauf
zurückgestellt und in der Oberfläche mit Grund angezeigt. Sonst würde ein
einziger dauerhaft scheiternder Eintrag jeden folgenden Zyklus belegen.
Beim nächsten Start des Suchlaufs wird er wieder angeboten.

### Verhaltens-Simulation

Optional (Vorbelegung aus, eigener Vorgang `search.idle_behavior`).
Während der Wartezeit im Such-Browser kleine, zufällige Scrollbewegungen,
nie ein Klick: ein Klick könnte etwas öffnen, und dieser Browser soll nur
eine Liste lesen.

## Karte, Korrektur und Meldungen (Phase 8)

### Die Karte der Ansichten

Der Ansichten-Katalog sammelt seit Phase 3 jede Ansicht, die wirklich
gesehen wurde: Struktur-Signatur, Kopie, Bild, Adresse, Zeitpunkt. Dazu
kommt jetzt der **Schritt von einer Ansicht zur nächsten**.

Jede Erfassung merkt sich, auf welcher Ansicht die Instanz zuletzt stand.
Ist die neue Ansicht eine andere, entsteht (oder zählt hoch) eine Kante
`von > nach > Auslöser` in `%APPDATA%\Zahnputztracker\atlas\<browser>\edges.json`,
mit erstem und letztem Auftreten und Anzahl. Auslöser ist das, was den
Wechsel ausgelöst hat ("Navigation", "Neu laden", "Adresszeile", "Von
Hand"), also genau die Angabe, die schon die Ankunft beschriftet.

Drei Regeln, damit die Karte nichts behauptet:

- Nach einem Neustart hat die erste Ansicht eines Laufs keinen Vorgänger.
  Es wird keiner erfunden.
- Wird eine Ansicht wegen der Obergrenze nicht gespeichert, entsteht auch
  keine Kante zu ihr. Eine Linie, deren Ende es nicht gibt, erklärt nichts.
- Wird eine Ansicht vergessen, verschwinden alle Kanten, die sie berühren.

Die Karte selbst (Reiter **Karte**) ordnet die Ansichten spaltenweise: eine
Ansicht steht so weit rechts, wie sie Schritte von einem Anfang entfernt
ist. Anfang ist jede Ansicht, in die kein beobachteter Schritt führt.
Ansichten, die in gar keinem Schritt vorkommen, stehen in einer eigenen
Spalte ganz links ("ohne bekannten Weg"): gesehen, aber es ist nicht
aufgezeichnet, wie man hinkommt. Ein Klick auf einen Kasten zeigt Bild,
Adresse, Zeitpunkte, alle Wege hin und alle Wege weiter, und öffnet auf
Wunsch die gespeicherte Kopie im Auswahlmodus.

### Vom Vorfall direkt in die Korrektur

Jede Zustandserfassung eines Vorfalls enthält eine Kopie der Seite
(`seite.html`, spätere Erfassungen in `stufeN-...\seite.html`). In der
Diagnose öffnet ein Knopf genau diese Kopie im Such-Browser, ohne Skript
und ohne Netz. Der Auswahlmodus arbeitet dort wie auf der echten Seite,
also lässt sich eine Rolle korrigieren, ohne die Lage von damals wieder
herzustellen.

Welche Datei geöffnet wird, prüft der Dienst gegen den Ordner des
Vorfalls. Ein Pfad aus dem Ordner heraus wird abgelehnt.

### Benachrichtigungen und Ton

`telemetry/notify.py` ist weiterhin die einzige Stelle, die entscheidet,
was eine Meldung ist. Neu ist ein zweiter Empfänger: eine kurze
Warteschlange der letzten 50 Meldungen mit laufender Nummer. Der Kern
(Rust) fragt alle zwei Sekunden nach allem hinter der Nummer, die er
zuletzt gesehen hat, und macht daraus eine Windows-Systemmeldung. Damit
gilt:

- keine Meldung doppelt, keine verloren, solange die Warteschlange reicht
- was vor dem Start der Oberfläche geschah, wird nicht nachträglich
  angezeigt (beim ersten Abholen wird nur der Stand übernommen)
- startet der Dienst neu und zählt wieder von vorn, folgt der Kern der
  kleineren Nummer, statt für immer zu schweigen
- die Einstellung "Benachrichtigungen" steuert nur die Systemmeldung. Im
  Ereignisstrom und in der Oberfläche steht die Meldung immer.

Der Signalton bei einem neu gefundenen Eintrag liegt als Klangdatei bei
(`src/assets/hinweis.wav`, zwei kurze Töne, im Programm erzeugt, aus
keiner fremden Quelle). Ob er klingt, entscheidet der Dienst anhand der
Einstellung und hängt es an die Meldung; die Oberfläche spielt nur ab.
Geht das Abspielen nicht (stummer Rechner, gesperrte Wiedergabe), wird
der Fehler geschluckt: die Meldung steht ohnehin sichtbar da.

## Ausliefern und Aktualisieren (Phase 9)

### Zwei Bauschritte, ein Ergebnis

Der Dienst wird zuerst mit PyInstaller zu einem eigenständigen Ordner
gepackt (`scripts/dienst_bauen.py` nach `service_dist/service/`), danach
baut Tauri das Installationsprogramm und nimmt diesen Ordner als Beigabe
mit. Der Kern sucht ihn im fertigen Programm unter
`<Ressourcen>/service/service.exe`, genau dort, wo Tauri ihn ablegt.

Zwei Dinge, die leicht falsch laufen und spät auffallen:

- Der gepackte Dienst behält bewusst einen Konsolenkanal. Der Kern
  übergibt das Token über die Standardeingabe und liest die Antwort von
  der Standardausgabe. Ein fensterloser Bau hätte beides nicht, und der
  Handschlag würde ohne jede Meldung scheitern. Kein Fenster erscheint
  trotzdem: der Kern startet den Prozess ohne Konsole.
- Das Overlay ist eine Textdatei neben ihrem Modul, kein Code. Sie wird
  ausdrücklich mitgenommen und der Bau bricht ab, wenn sie im Ergebnis
  fehlt. Sonst startet das gepackte Programm und der Auswahlmodus wäre
  einfach weg.

Ein Platzhalter hält den Zielordner vorhanden, damit auch eine frische
Kopie des Projekts baut, bevor der Dienst je gepackt wurde.

### Der Updater

Fünf Sekunden nach dem Start und danach alle sechs Stunden wird die
Beschreibungsdatei des jüngsten Releases gelesen, mehr nicht. Vor einem
Klick wird nichts heruntergeladen.

Der Knopf hat sieben Erscheinungen: die sechs aus der Spezifikation und
zusätzlich `nicht_eingerichtet`. Das ist kein Fehlerzustand, sondern die
ehrliche Aussage, dass in der Konfiguration noch Platzhalter statt Konto
und öffentlichem Schlüssel stehen. Ein Fehler, den niemand beheben kann,
wäre die schlechtere Anzeige.

Ein fehlgeschlagener Hintergrundlauf leuchtet nicht. Er stellt den Knopf
auf den Stand von vorher zurück und legt den Grund als Hinweis dahinter,
der beim Überfahren erscheint. Nur eine erzwungene Prüfung zeigt einen
Fehler offen an: dort hat jemand gefragt und verdient eine Antwort.

### Der Weg vor der Installation

Erst nach dem Klick, und in dieser Reihenfolge:

1. Der Dienst wird gefragt, was läuft. Läuft ein Vorgang oder ist ein
   Browser offen, kommt eine Rückfrage.
2. Der Ablauf wird angehalten.
3. Beide Browser werden geschlossen, und es wird gewartet, bis sie
   wirklich weg sind (bis zu zwanzig Sekunden).
4. Erst dann wird der Dienst beendet, und zwar endgültig: eine Sperre
   hält die Prozessaufsicht davon ab, ihn wieder zu starten. Genau das
   darf während einer Installation nicht passieren.
5. Herunterladen mit Fortschritt, Unterschrift prüfen, installieren,
   neu starten.

Schritt 3 ist verpflichtend und nicht abkürzbar: ein hart beendeter
Browser hinterlässt verwaiste Prozesse und gesperrte Profilordner.

Ohne gültige Unterschrift wird nichts installiert. Das ist keine
Einstellung, sondern die eingebaute Regel des Updaters.

### Das Browser-Programm

Getrennt davon, in den Einstellungen, mit ruhigerer Anzeige und ohne
Neustart der Anwendung. Es benutzt denselben Weg wie die Erstinstallation
des Browsers, nur mit dem Zusatz, eine vorhandene Fassung zu ersetzen.

### Die Wortlistenprüfung

`scripts/tarnung.py` prüft Dateien und Commit-Nachricht gegen eine Liste
von Wörtern, die im Repository nicht vorkommen dürfen. Die Wörter stehen
ausschließlich in `privat/wortliste.txt` und damit nie im Repository:
eine Prüfliste, die selbst eingecheckt ist, wäre ihr eigener Treffer.

Fehlt die Liste, wird nicht geprüft und die Prüfung schlägt fehl. Eine
Prüfung, die bei fehlender Grundlage still durchwinkt, ist schlechter
als gar keine.

Zeilen mit `re:` sind reguläre Ausdrücke. Das braucht es dort, wo ein
harmloses technisches Wort ein verdächtiges enthält (`expose_binding`
aus Playwright gegen den Begriff selbst).

Eingeschaltet wird das einmal mit `git config core.hooksPath .githooks`.
Zwei Haken greifen: einer vor dem Commit für die vorgemerkten Dateien,
einer für die Nachricht.
