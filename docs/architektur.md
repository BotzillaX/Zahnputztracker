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
