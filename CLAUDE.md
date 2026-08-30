# Projektregeln

Die vollständige Spezifikation steht in `privat/spec.md` und ist bindend.
Abschnitt 0 (Leseregeln) und Abschnitt 2 (Trennung von Code und Zuordnung)
haben Vorrang vor allem anderen.

`privat/anlage-a-seitenwissen.md` ist ausschließlich Referenz für den
Rollen-Katalog und die Konfigurationsstruktur. Kein einziger Wert daraus
(Selektoren, Attributnamen, Auswahlwerte, Adressen) darf in den Code. Diese
Werte gelangen nur über das Anlernen durch den Benutzer in die lokale
Zuordnung.

Der Ordner `privat/` wird niemals committet (steht in `.gitignore`). Das gilt
auch für die Spezifikation selbst, weil sie den Anwendungsfall benennt.

In Commit-Nachrichten, Dateinamen, Klassennamen, Kommentaren und Release-Notes
kommen keine Begriffe vor, die den Anwendungsfall erkennen lassen
(privat/spec.md Abschnitt 14). Code und Commits sind englisch, alles für den
Benutzer Sichtbare deutsch.

Bei Unklarheiten: fragen, nicht raten. Keine Funktionen bauen, die nicht in der
Spezifikation stehen.
