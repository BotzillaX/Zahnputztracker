# Projektregeln

## 0. Antwortstil (gilt immer)

**Obergrenze sechs Sätze.** Wer mehr braucht, hat nicht zu Ende gedacht.
Einzige Ausnahme: eine nummerierte Liste mit Befehlen zum Abarbeiten.

Verboten:

- wiederholen, was gefragt wurde
- zusammenfassen, was im Diff steht
- begründen, was niemand angezweifelt hat
- erklären, was der Benutzer nicht gefragt hat
- vorwegnehmen, was er als Nächstes fragen könnte
- einordnen, abwägen, anbieten, absichern

Was kaputt ist, was der Benutzer tun muss und was ungeprüft blieb, fehlt
trotzdem nie. Das sind zwei Sätze, nicht zehn.

Deutsch für alles, was der Benutzer liest. Englisch für Code, Kommentare und
Commit-Nachrichten. Keine Gedankenstriche als Klammern, runde Klammern
benutzen.

## 1. Worum es geht

Windows-Desktop-Anwendung. Sie begleitet einen wiederkehrenden Ablauf im
Browser, führt ihn aus und protokolliert ihn.

Die Anwendung weiß von sich aus **nichts** über die Seite, mit der sie
arbeitet. Sie kennt nur einen festen Katalog von Rollen. Welches Element
welche Rolle ausfüllt, lernt der Benutzer ihr bei. Ohne diese Zuordnung führt
sie bewusst keine einzige Aktion aus.

Bindend ist `privat/spec.md`. Abschnitt 0 (Leseregeln) und Abschnitt 2
(Trennung von Code und Zuordnung) haben Vorrang vor allem anderen.
`privat/anlage-a-seitenwissen.md` ist **nur Referenz** für den Rollen-Katalog
und die Konfigurationsstruktur. Kein einziger Wert daraus (Selektoren,
Attributnamen, Auswahlwerte, Adressen) darf in den Code.

## 2. Harte Regeln

- `privat/` wird **niemals** committet, auch die Spezifikation nicht.
- Keine Begriffe im Repository, die auf die Seite schließen lassen
  (Dateinamen, Ordner, Klassen, Kommentare, Commits, Release-Notes). Geprüft
  bei jedem Commit gegen `privat/wortliste.txt`. Die Liste fängt nur
  konkrete Wörter. Formulierungen, die den Zweck durchscheinen lassen, ohne
  eines davon zu benutzen, muss der Verstand fangen.
- Bei Unklarheit: fragen, nicht raten. Keine Funktion bauen, die nicht in der
  Spezifikation steht. Keine Heuristik, die "meistens funktioniert" (Spez. 0.3).
  Ein definierter Abbruch mit Meldung ist immer besser.
- Das Dienst-Token steht in keiner Datei. Kennwörter und Schlüssel nur im
  Windows-Anmeldeinformationsspeicher. Die Zuordnung wird nie eingecheckt.
  Keine Bildschirmfotos, Beispielprotokolle oder Testdaten mit echten Inhalten
  im Repository.
- Das Absenden eines Formulars wird **nie** automatisch wiederholt. Ein Eintrag
  gilt erst nach bestätigtem Versand als erledigt.

## 3. Aufbau

```
src/            Oberfläche (Svelte 5, Runes). Reiter: Betrieb, Browser,
                Registrierung, Zustände, Ansichten, Karte, Diagnose,
                Einstellungen
src-tauri/      Kern (Rust): Fenster, Tray, Prozessaufsicht, Geheimnisse,
                Systemmeldungen (notices.rs), Updates (update.rs)
service/        Dienst (Python): api, runtime, registry, picker, engine,
                flow, atlas, telemetry, storage, text, tests
docs/           architektur.md, starten.md, anlernen.md, signatur.md
scripts/        dienst_bauen.py (PyInstaller), tarnung.py (Wortliste)
```

Kern und Dienst sind getrennte Prozesse. Der Dienst lauscht auf `127.0.0.1`
auf einem zufälligen Port, das Token kommt über die Standardeingabe. Stirbt
der Dienst, startet der Kern ihn neu. Stirbt die Oberfläche, läuft der Dienst
weiter.

## 4. Befehle

```bash
npm run tauri dev                                  # alles starten
.venv/Scripts/python.exe -m service.tests.<name>   # eine Prüfung
npm run build                                      # Oberfläche
cargo check --manifest-path src-tauri/Cargo.toml   # Kern
.venv/Scripts/python.exe scripts/tarnung.py        # Wortliste, ganzes Repo
```

Prüfungen: `test_storage`, `test_registry`, `test_browser`, `test_picker`,
`test_engine`, `test_telemetry`, `test_flow`, `test_search`. Die mit Browser
öffnen ein echtes Fenster. PowerShell kennt kein `&&`, Befehle mit `;` trennen.

Vor dem Bauen des Installationsprogramms: erst
`.venv/Scripts/python.exe scripts/dienst_bauen.py`, dann `npm run tauri build`.

## 5. Deine Aufgabe: die Zuordnung pflegen

**Das ist Arbeitsteilung, keine Nebensache.** Der Benutzer bedient kein
Formular, er zeigt nur.

1. Er startet den Auswahlmodus (Reiter Registrierung) und klickt Elemente an.
   Der Modus bleibt an, Esc beendet.
2. Jede Auswahl landet nummeriert in
   `%APPDATA%\Zahnputztracker\auswahl.json` (letzte 50, mit `serial`, `at`,
   `scope`, `url`, `element.candidates`, `element.outer`, `raw`).
3. Er schreibt dir, welche Auswahl welche Rolle ist, in seinen Worten.
4. **Du liest die Datei direkt**, wählst Erkennungsmerkmale und Menge, benennst
   die Rolle sauber und schreibst sie:

```bash
.venv/Scripts/python.exe -c "from service.registry import store; store.put_role('session', {...})"
```

5. Er drückt "Alle Rollen auf der offenen Seite prüfen" und sieht "gefunden".

Rollen und Reihenfolge stehen in `service/flow/contract.py` (`STEPS`), erklärt
in `docs/anlernen.md`. Wichtigste Rolle: `signed_in_marker`, etwas das es
**nur** im angemeldeten Zustand gibt.

Er kann Elemente aus einem anderen Browser auch von Hand einfügen ("Eigenen
Eintrag einfügen"). Die stehen mit `source: "eingefuegt"` und rohem HTML in
`raw` in derselben Liste.

## 6. Stand

Fertig und committet: Phase 0 bis 9.

| Phase | Inhalt |
|---|---|
| 0-3 | Gerüst, Ablage, Browser-Betrieb, Zuordnung und Auswahlmodus |
| 4 | Zustände, Bedingungen, Aktionsketten, Vorlagen |
| 5 | Anmeldung, ein vollständiger Durchlauf, Doppelversand-Schutz |
| 6 | Vorgänge, Schwellen, Wachhund, Aufzeichnungen, Speichergrenze |
| 7 | Suchzyklus und Dauerbetrieb |
| 8 | Karte der Ansichten, Korrektur aus einem Vorfall, Systemmeldungen, Ton |
| 9 | Signierte Updates, Verpackung (PyInstaller), Wortlistenprüfung |

**Offen: Phase 10** (24 Stunden Dauerlauf unter echten Bedingungen, danach die
Zeitlimits je Vorgang mit echten Messwerten nachziehen, Bericht über den
Zeitraum). Das Nachziehen der Zeitlimits ist ein ausdrückliches Versprechen an
den Benutzer, nicht optional.

## 7. Was der Benutzer noch tun muss

1. **Rollen anlernen.** Im Sitzungs-Browser ist noch nichts angelernt. Im
   Such-Browser fehlt `item_link` (Menge muss `liste` sein) und es liegen
   leere Rollenhüllen herum, die kein Ablauf braucht.
2. **Geheimnisse für Updates hinterlegen.** Das Schlüsselpaar ist erzeugt, der
   öffentliche Schlüssel steht in `src-tauri/tauri.conf.json`. Im Repository
   fehlen noch `TAURI_SIGNING_PRIVATE_KEY` und
   `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`. Anleitung: `docs/signatur.md`. Den
   privaten Schlüssel und sein Kennwort bekommst du nie.
3. **Testen:** Abnahme 1, 3, 4 (Phase 4), 10 (Phase 5), 7, 8, 9 (Phase 6),
   Suchzyklus (Phase 7), Abnahme 11 (geht erst nach Punkt 2).

Die Wortlistenprüfung ist eingeschaltet (`git config core.hooksPath .githooks`).
Läuft sie in einer frischen Kopie nicht, ist das der Grund.

## 8. Fallen, die schon einmal Zeit gekostet haben

- `bus.publish(kind, **payload)` nimmt `kind` positional. Ein Nutzdatenfeld
  namens `kind` wirft `TypeError`.
- Prüfungen müssen `APPDATA` **und** `LOCALAPPDATA` in einen Testordner legen,
  sonst benutzen und verändern sie das echte angemeldete Browserprofil.
- Der gepackte Dienst braucht einen Konsolenkanal (`--console`). Ein
  fensterloser Bau hat kein stdin/stdout, der Handschlag scheitert lautlos.
- `overlay.js` ist eine Datendatei neben ihrem Modul und muss beim Packen
  ausdrücklich mit. `dienst_bauen.py` bricht ab, wenn sie fehlt.
- Hängende Klicks in den Browser-Prüfungen (`Timeout 30000ms`, "performing
  click action") waren mehrfach der Rechner, nicht der Code. Gegenprobe:
  `git stash -u`, dieselbe Prüfung auf dem letzten Commit laufen lassen.
- Große Python- oder Svelte-Dateien mit dem Write-Werkzeug schreiben.
  Bash-Heredocs sterben an deutschen Apostrophen, und `\\` kann unterwegs zu
  `\` zusammenfallen.
