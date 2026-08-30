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
