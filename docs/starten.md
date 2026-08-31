# Anwendung starten

## Im Entwicklungsbetrieb

```
cd C:\Users\KevinFritsch\Documents\Zahnputztracker
npm run tauri dev
```

Das genügt. Der Befehl startet den Vite-Server, baut den Kern (beim ersten
Mal einige Minuten, danach Sekunden) und öffnet das Fenster.

Den Dienst musst du **nicht** getrennt starten: der Kern startet ihn selbst
aus `.venv\Scripts\python.exe` und beaufsichtigt ihn. Wird er beendet
(Absturz oder Taskmanager), startet der Kern ihn neu und meldet das in der
Oberfläche.

Beenden mit `Strg+C` im Terminal. Der Dienst läuft absichtlich weiter und
wird beim nächsten Start wieder übernommen, damit ein geöffneter Browser
nicht bei jedem Fensterwechsel verloren geht.

## Der Browser

Der Browser startet nicht automatisch. Im Reiter Browser gibt es dafür einen
Knopf. Beim allerersten Mal wird das Programm vorher nachgeladen (rund
200 MB, mit Fortschrittsbalken).

## Reihenfolge beim ersten Mal

1. Fenster öffnet sich und zeigt „verbunden"
2. Einstellungen ausfüllen (Zugang, Adresse der Ergebnisseite,
   Adressvorlage mit `{kennung}`, Anbieter des Textes, persönliche Werte)
3. Browser starten
4. Rollen anlernen: im Sitzungs-Browser die Rollen für Anmeldung und
   Vorgang, im Such-Browser die Rolle für den Verweis der Trefferliste
   (Menge `liste`)
5. Anmelden, dann einen einzelnen Vorgang testen
6. Erst danach den Suchlauf

## Prüfläufe

Einzeln, nicht parallel, und nicht neben einem Vollbildspiel: die
Prüfläufe steuern echte Browser-Fenster, und ein Spiel im Vordergrund kann
dazu führen, dass Klicks nicht zugestellt werden.

```
.venv\Scripts\python.exe -m service.tests.test_storage
.venv\Scripts\python.exe -m service.tests.test_registry
.venv\Scripts\python.exe -m service.tests.test_picker
.venv\Scripts\python.exe -m service.tests.test_engine
.venv\Scripts\python.exe -m service.tests.test_flow
.venv\Scripts\python.exe -m service.tests.test_search
.venv\Scripts\python.exe -m service.tests.test_telemetry
```

Die Prüfläufe legen ihre Daten und ihre Browser-Profile in einem
Temp-Ordner an. Sie fassen weder deine Konfiguration noch das angemeldete
Profil an.

In PowerShell 5.1 ist `&&` kein Trennzeichen. Mehrere Befehle in einer
Zeile werden mit `;` getrennt.
