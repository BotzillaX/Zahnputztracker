# Zahnputztracker

Desktop-Anwendung für Windows, die einen wiederkehrenden Ablauf im Browser
begleitet, protokolliert und auswertet. Die Anwendung kennt den Ablauf nicht von
sich aus: welche Elemente einer Seite relevant sind und was mit ihnen geschieht,
legt der Benutzer selbst fest und speichert es lokal. Ohne diese Zuordnung führt
die Anwendung bewusst keine einzige Aktion aus.

## Aufbau

```
Zahnputztracker.exe
 ├─ Oberfläche     Svelte, HTML/CSS
 ├─ Kern (Rust)    Fenster, Tray, Aktualisierung, Prozessaufsicht, Geheimnisse
 └─ Dienst (Python) Browsersteuerung, Registrierung, Ablauflogik, Auswertung
```

Kern und Dienst sind getrennte Prozesse. Der Dienst lauscht auf `127.0.0.1` auf
einem zufälligen Port und akzeptiert nur Anfragen mit einem Einmal-Token, das
der Kern beim Start über die Standardeingabe übergibt. Das Token liegt im
Windows-Anmeldeinformationsspeicher, nie in einer Datei. Ereignisse fließen über
WebSocket in die Oberfläche.

Stirbt der Dienst, meldet der Kern das und startet ihn neu. Stirbt die
Oberfläche, läuft der Dienst weiter und wird beim nächsten Start übernommen.

## Ablageorte

| Inhalt | Ort |
|---|---|
| Einstellungen, Registrierung, Datenbank, Protokolle | `%APPDATA%\Zahnputztracker\` |
| Browserdaten, Profile, temporäre Aufzeichnungen | `%LOCALAPPDATA%\Zahnputztracker\` |
| Zugangsdaten, Schlüssel | Windows-Anmeldeinformationsspeicher |

Neben der ausführbaren Datei liegt nichts davon.

## Entwicklung

Voraussetzungen: Rust (MSVC), Node 20 oder neuer, Python 3.11 oder neuer.

```bash
npm install
py -m venv .venv
.venv/Scripts/python.exe -m pip install -r service/requirements.txt
npm run tauri dev
```

Der Dienst lässt sich auch einzeln starten, das Token kommt dann über die
Standardeingabe:

```bash
.venv/Scripts/python.exe -m service.main --token beliebig
```

## Prüfen

Jede Prüfung ist ein eigenes Modul und schreibt ihr Ergebnis Zeile für
Zeile. Die Prüfungen mit Browser öffnen ein echtes Fenster auf einer
Übungsseite, die im Test selbst geschrieben wird.

```bash
.venv/Scripts/python.exe -m service.tests.test_storage
.venv/Scripts/python.exe -m service.tests.test_registry
.venv/Scripts/python.exe -m service.tests.test_browser
.venv/Scripts/python.exe -m service.tests.test_picker
.venv/Scripts/python.exe -m service.tests.test_engine
.venv/Scripts/python.exe -m service.tests.test_telemetry
.venv/Scripts/python.exe -m service.tests.test_flow
.venv/Scripts/python.exe -m service.tests.test_search
```

Vor jedem Commit läuft zusätzlich eine Prüfung der vorgemerkten Dateien
und der Commit-Nachricht gegen eine lokale Wortliste. Sie wird einmal
eingeschaltet mit:

```bash
git config core.hooksPath .githooks
```

## Bauen

Der Dienst wird zuerst zu einem eigenständigen Ordner gepackt, danach
entsteht das Installationsprogramm, das diesen Ordner mitnimmt.

```bash
.venv/Scripts/python.exe -m pip install pyinstaller
.venv/Scripts/python.exe scripts/dienst_bauen.py
npm run tauri build
```

Das Ergebnis liegt unter `src-tauri/target/release/bundle/nsis/`.

## Aktualisierung

Die Anwendung fragt kurz nach dem Start und danach alle sechs Stunden
eine Beschreibungsdatei des jüngsten Releases ab. Heruntergeladen wird
davon nichts. Erst ein Klick auf den Knopf in den Einstellungen lädt und
installiert, und auch das erst, nachdem der laufende Ablauf angehalten
und beide Browser geschlossen wurden.

Ohne gültige Signatur wird nichts installiert. Der öffentliche Schlüssel
steht in `src-tauri/tauri.conf.json`, der private gehört in die
Geheimnisse des Repositories. Wie das Schlüsselpaar entsteht, steht
Schritt für Schritt in `docs/signatur.md`.

Das Browser-Programm wird getrennt davon aktualisiert, ebenfalls in den
Einstellungen, ohne Neustart der Anwendung.

## Weitere Beschreibungen

| Datei | Inhalt |
|---|---|
| `docs/architektur.md` | Aufbau, Entscheidungen und ihre Begründung |
| `docs/starten.md` | Wie die Anwendung zum Ausprobieren gestartet wird |
| `docs/anlernen.md` | Wie der Benutzer der Anwendung die Seite beibringt |
| `docs/signatur.md` | Schlüsselpaar, Release, Veröffentlichung |

## Lizenz

Privates Projekt, keine Lizenz vergeben.
