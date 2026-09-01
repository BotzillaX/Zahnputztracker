# Anlernen

Die Anwendung weiß von sich aus nichts über die Seite, mit der sie
arbeitet. Sie kennt nur eine feste Liste von **Rollen**: „das Feld für
die Kennung", „das Absende-Element". Welches Element auf der Seite eine
Rolle ausfüllt, entscheidet allein der Benutzer.

## Arbeitsteilung

Der Benutzer zeigt auf Elemente. Das Benennen, das Wählen der
Erkennungsmerkmale und das Schreiben in die Registrierung übernimmt die
unterstützende KI. Die Oberfläche hat dafür kein Formular mehr.

1. Reiter Registrierung, Browser wählen
2. „Auswahlmodus starten"
3. Im Browser-Fenster Element anfahren. Pfeil hoch/runter wechselt die
   Ebene, Pfeil links/rechts den Nachbarn, **Enter übernimmt**.
   Der Modus bleibt an: mehrere Elemente nacheinander sind der Normalfall.
   **Esc beendet.**
4. Jede Auswahl steht nummeriert unter „Ausgewählt" und liegt zusätzlich
   in der Zwischenablage
5. Der KI sagen, was welche Nummer ist („das erste ist der Anmelden-Knopf,
   das zweite ist das Merkmal für angemeldet")
6. „Alle Rollen auf der offenen Seite prüfen": jede geschriebene Rolle
   muss „gefunden" melden

Jede Auswahl liegt in `%APPDATA%\Zahnputztracker\auswahl.json`, mit
Reihenfolge, Zeitpunkt, Adresse und den erzeugten Erkennungsmerkmalen.
Die Liste überlebt einen Neustart und fasst die letzten 50 Auswahlen.

**Element aus einem anderen Browser:** unter „Ausgewählt" gibt es
„Eigenen Eintrag einfügen". Dort das kopierte HTML einfügen, eine Notiz
dazu, fertig. Der Eintrag reiht sich mit derselben Nummerierung ein und
ist als „von Hand" gekennzeichnet.

## Was „prüfen" aussagt

Geprüft wird gegen die Seite, die im Browser gerade offen ist:

| Meldung | Bedeutung |
|---|---|
| gefunden | Das erste Erkennungsmerkmal hat gegriffen. So soll es sein. |
| gefunden (Degradierung) | Ein schwächeres Merkmal musste einspringen. Läuft, ist aber ein Vorbote. |
| nicht gefunden | Kein Merkmal greift. Entweder ist die Seite eine andere, oder die Rolle muss neu angelernt werden. |
| mehrdeutig | Mehrere sichtbare Treffer bei Menge `einzel`. Die Anwendung sucht sich keinen davon aus. |

## Die Rollen

Die Oberfläche zeigt sie unter „Ablauf und Rollen" in der Reihenfolge,
in der sie benutzt werden, mit je einem Satz dazu. Kurzfassung:

**Such-Browser, Suchlauf**
- `item_link` (Menge `liste`): der Verweis einer Zeile der Trefferliste

**Sitzungs-Browser, Anmeldung**
- `sign_in_entry` (optional), `identity_field`, `secret_field`,
  `primary_action_a`, `second_factor_marker` und `second_factor_field`
  (optional), `signed_in_marker`
- `signed_in_marker` ist die wichtigste: etwas, das es **nur** im
  angemeldeten Zustand gibt. Daran wird vor jedem Vorgang geprüft, ob die
  Anmeldung noch steht.

**Sitzungs-Browser, ein Eintrag**
- `ready_marker`, `exclusion_marker…` (mehrere möglich, optional),
  `already_marker` (optional), `primary_action_b` (optional),
  `message_field`, `form_field…` (mehrere möglich, optional),
  `submit_action`, `confirmation_marker` (optional)

Rollen, die in keinem Ablauf vorkommen, werden getrennt aufgeführt. Sie
tun nichts und können weg.
