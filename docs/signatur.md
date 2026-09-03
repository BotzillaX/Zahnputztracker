# Schlüssel, Release, Veröffentlichung

Diese Anleitung ist für den Fall geschrieben, dass du das noch nie
gemacht hast. Jeder Schritt sagt, was du eingibst, was du danach siehst
und woran du merkst, dass es geklappt hat. Es gibt keinen Schritt, den
du "eigentlich schon kennen solltest".

Alles zusammen dauert etwa zwanzig Minuten und ist **einmalig**. Danach
reicht für jede neue Fassung ein einziger Befehl.

---

## Worum es geht

Die Anwendung darf sich selbst aktualisieren. Damit sie das darf, muss
sie erkennen können, dass ein Update wirklich von dir stammt und nicht
von jemand anderem, der die Datei ausgetauscht hat.

Dafür gibt es zwei zusammengehörende Schlüssel:

- den **privaten** Schlüssel. Damit unterschreibst du. Er darf niemals
  im Repository landen und niemals in einer Nachricht stehen.
- den **öffentlichen** Schlüssel. Damit prüft die Anwendung die
  Unterschrift. Der gehört in die Konfiguration und darf jeder sehen.

Passt die Unterschrift nicht, installiert die Anwendung nichts. Das ist
keine Einstellung, das ist fest eingebaut.

---

## Schritt 1: Schlüsselpaar erzeugen

Öffne im Projektordner ein Terminal und gib ein:

```bash
npm run tauri signer generate -- -w %USERPROFILE%\.tauri\zahnputztracker.key
```

Du wirst nach einem Kennwort gefragt (zweimal). Nimm eines, das du in
deinem Kennwortspeicher ablegst. Es schützt die Schlüsseldatei auf
deinem Rechner.

Danach stehen zwei Dinge auf dem Bildschirm und zwei Dateien auf der
Platte:

| Was | Wo |
|---|---|
| privater Schlüssel | `%USERPROFILE%\.tauri\zahnputztracker.key` |
| öffentlicher Schlüssel | `%USERPROFILE%\.tauri\zahnputztracker.key.pub` |

**Geschafft, wenn** beide Dateien vorhanden sind. Prüfen kannst du das
mit:

```bash
dir %USERPROFILE%\.tauri
```

---

## Schritt 2: Öffentlichen Schlüssel eintragen — erledigt

Der öffentliche Schlüssel aus Schritt 1 und das Konto `BotzillaX`
stehen bereits in `src-tauri\tauri.conf.json`:

```json
"plugins": {
  "updater": {
    "endpoints": [
      "https://github.com/BotzillaX/Zahnputztracker/releases/latest/download/latest.json"
    ],
    "pubkey": "dW50cnVzdGVkIGNvbW1lbnQ6ICg...)"
```

Hier ist nichts mehr zu tun. Dieser Schritt wird nur noch einmal
gebraucht, falls das Schlüsselpaar neu erzeugt wird (siehe die Warnung
ganz unten) oder das Repository unter einem anderen Namen liegt. Dann
gehören `pubkey` und die Adresse in `endpoints` zusammen angepasst.

**Geschafft, wenn** in den Einstellungen der Anwendung der Knopf nicht
"Updates noch nicht eingerichtet" sagt, sondern "Aktuell (v0.1.0)".
Dafür muss die Anwendung neu gebaut werden (`npm run tauri dev` reicht).

---

## Schritt 3: Privaten Schlüssel bei GitHub hinterlegen

Das Repository muss dafür schon auf GitHub liegen. Falls nicht:

```bash
git remote add origin https://github.com/BotzillaX/Zahnputztracker.git
git push -u origin master
```

Dann im Browser:

1. Gehe auf die Seite des Repositories.
2. Oben in der Leiste auf **Settings**.
3. Links in der langen Liste auf **Secrets and variables**, darunter auf
   **Actions**.
4. Grüner Knopf **New repository secret**.

Zwei Geheimnisse werden angelegt, eines nach dem anderen:

| Name | Inhalt |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | der **ganze Inhalt** der Datei `zahnputztracker.key` |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | das Kennwort aus Schritt 1 |

Die Datei öffnest du wie in Schritt 2 mit einem Texteditor und kopierst
alles, was drinsteht, mitsamt der ersten und letzten Zeile.

**Geschafft, wenn** unter Settings > Secrets and variables > Actions
beide Namen in der Liste stehen. Der Inhalt ist danach nicht mehr
lesbar, auch für dich nicht. Das ist richtig so.

---

## Schritt 4: Eine Fassung veröffentlichen

Immer wenn eine neue Fassung fertig ist:

1. Die Versionsnummer an **zwei** Stellen hochzählen, beide gleich:
   `package.json` (`"version"`) und `src-tauri\tauri.conf.json`
   (`"version"`).
2. Änderungen einchecken.
3. Eine Marke setzen und hochladen:

```bash
git tag v0.2.0
git push origin v0.2.0
```

Ab hier passiert alles von selbst. GitHub baut die Anwendung, packt den
Dienst dazu, unterschreibt das Installationsprogramm mit deinem privaten
Schlüssel und legt einen Entwurf des Releases an.

**Geschafft, wenn** unter dem Reiter **Actions** der Lauf grün ist und
unter **Releases** ein Entwurf mit drei Dateien liegt:

```
Zahnputztracker_0.2.0_x64-setup.exe
Zahnputztracker_0.2.0_x64-setup.exe.sig
latest.json
```

Der Entwurf ist noch nicht veröffentlicht. Öffne ihn, sieh ihn dir an,
und klicke **Publish release**. Erst ab diesem Moment sieht die
Anwendung das Update.

---

## Was passiert dann in der Anwendung

Fünf Sekunden nach dem Start und danach alle sechs Stunden fragt sie
nach `latest.json`. Das ist eine kleine Textdatei, mehr wird nicht
geladen. Ist etwas Neueres da, leuchtet der Knopf in den Einstellungen.

Erst wenn du darauf klickst:

1. Die Anwendung sagt dir, ob gerade ein Vorgang läuft, und fragt nach.
2. Der Vorgang wird angehalten, beide Browser werden geordnet
   geschlossen, der Dienst wird beendet.
3. Das Installationsprogramm wird geladen (mit Fortschrittsanzeige) und
   die Unterschrift geprüft.
4. Es wird installiert, die Anwendung startet neu.

Einstellungen, Registrierung und Datenbank liegen in `%APPDATA%` und
werden dabei nicht angefasst. Der Ablauf startet nach dem Neustart nicht
von selbst.

---

## Wenn etwas nicht klappt

| Was du siehst | Was los ist |
|---|---|
| Knopf sagt "Updates noch nicht eingerichtet" | In `tauri.conf.json` steht wieder ein Platzhalter (Schritt 2). |
| Knopf sagt "Prüfung fehlgeschlagen" | Zeig mit der Maus darauf, dann steht der Grund da. Meistens: es gibt noch kein veröffentlichtes Release, oder kein Netz. |
| Der Lauf unter Actions ist rot | Öffne ihn und sieh dir den ersten roten Schritt an. Fehlt ein Geheimnis, steht dort "secret not found". |
| Das Update wird abgelehnt | Der öffentliche Schlüssel in der Anwendung passt nicht zum privaten bei GitHub. Schritt 2 wiederholen. |

Den privaten Schlüssel niemals neu erzeugen, solange eine ältere Fassung
im Umlauf ist: die erkennt die neue Unterschrift dann nicht mehr und
kann sich nicht mehr selbst aktualisieren.
