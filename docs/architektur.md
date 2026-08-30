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
