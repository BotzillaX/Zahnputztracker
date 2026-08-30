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

## Lizenz

Privates Projekt, keine Lizenz vergeben.
