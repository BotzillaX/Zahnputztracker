"""Check of the observability: log, reference values, thresholds,
watchdog, recovery, recordings, report and the storage limit.

The parts that need no browser run on their own. The two thresholds are
checked against a real browser on an exercise page written here, because
the point of the whole thing is what it holds of a page.

    .venv\\Scripts\\python.exe -m service.tests.test_telemetry
"""
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

_temp = tempfile.mkdtemp(prefix="zt-telemetry-")
_echtes_lokal = os.environ.get("LOCALAPPDATA", "")
os.environ["APPDATA"] = _temp
# Auch die Aufzeichnungen liegen im Testordner. Nur der Browser selbst
# wird dort gesucht, wo er wirklich liegt (siehe main).
os.environ["LOCALAPPDATA"] = _temp + "-lokal"
_pages = Path(_temp) / "seiten"
_pages.mkdir(parents=True, exist_ok=True)

from ..api.events import bus  # noqa: E402
from ..registry import store  # noqa: E402
from ..runtime import browser_install, instances  # noqa: E402
from ..storage import config as config_store  # noqa: E402
from ..storage import paths  # noqa: E402
from ..telemetry import (  # noqa: E402
    frames,
    housekeeping,
    incidents,
    journal,
    notify,
    report,
    spans,
    stats,
    tracing,
    watchdog,
)

fehler = []


def check(bedingung, label):
    print(("  ok   " if bedingung else "  FEHL ") + label, flush=True)
    if not bedingung:
        fehler.append(label)


def seite(name, koerper):
    ziel = _pages / f"{name}.html"
    ziel.write_text(f"<html><body>{koerper}</body></html>", encoding="utf-8")
    return ziel.as_uri()


def rolle(name, testid):
    return {
        "id": name,
        "label": name,
        "scope": "session",
        "menge": "einzel",
        "notes": "",
        "key_attribute": "",
        "answer": "",
        "options": [],
        "candidates": [{"kind": "attr", "attr": "data-testid", "value": testid}],
    }


class Ereignisse:
    """Mitschnitt des Ereignisstroms fuer die Pruefungen."""

    def __init__(self):
        self.gesehen = []
        bus.add_sink(self.gesehen.append)

    def art(self, kind):
        return [e for e in self.gesehen if e.get("kind") == kind]

    def leeren(self):
        self.gesehen.clear()


# ------------------------------------------------------------------ Protokoll


def protokoll_pruefen():
    print("Protokoll")
    paths.ensure_layout()
    journal.write("pruefung", wert=1, text="Umlaute: äöü")
    journal.write("pruefung", wert=2)
    zeilen = journal.read(events=("pruefung",))
    check(len(zeilen) == 2, "jede Zeile steht fuer sich in der Tagesdatei")
    check(zeilen[0]["wert"] == 1 and zeilen[0]["text"].endswith("äöü"),
          "der Inhalt kommt unveraendert zurueck")

    ziel = journal.file_for()
    with ziel.open("a", encoding="utf-8") as strom:
        strom.write("{kaputt\n")
    journal.write("pruefung", wert=3)
    zeilen = journal.read(events=("pruefung",))
    check(len(zeilen) == 3, "eine kaputte Zeile kostet nur diese Zeile")

    alt = journal.directory() / "2020-01-01.jsonl"
    alt.write_text('{"ev":"alt"}\n', encoding="utf-8")
    entfernt = journal.prune(30)
    check("2020-01-01" in entfernt and not alt.exists(),
          "was aelter als die Aufbewahrung ist, wird geloescht")
    check(journal.file_for().exists(), "der heutige Tag bleibt liegen")

    journal.attach()
    bus.publish("degraded", role="test", label="Test", step=1, kind_label="Text")
    bus.publish("ping", message="nicht interessant")
    heute = journal.read()
    check(any(z.get("ev") == "degraded" for z in heute),
          "eine Abstufung wird aus dem Ereignisstrom mitgeschrieben")
    check(not any(z.get("ev") == "ping" for z in heute),
          "belanglose Ereignisse landen nicht in der Datei")


# --------------------------------------------------------------- Referenzwerte


def referenz_pruefen():
    print("Referenzwerte")
    stats.reset()
    urteil = stats.record("form.open", "session", 1000)
    check(urteil["cold"] and not urteil["recorded"],
          "die erste Messung eines Vorgangs zaehlt nicht (kalter Start)")

    for _ in range(4):
        stats.record("form.open", "session", 1000)
    check(not stats.reference("form.open", "session")["known"],
          f"unter {stats.MIN_SAMPLES} Messungen wird nur gesammelt")

    for _ in range(20):
        stats.record("form.open", "session", 1000)
    basis = stats.reference("form.open", "session")
    check(basis["known"] and abs(basis["median_ms"] - 1000) < 1,
          "der Median steht auf dem gemessenen Wert")
    check(stats.rate("form.open", "session", 1050)["level"] == stats.NORMAL,
          "eine gewoehnliche Laufzeit ist normal")
    check(stats.rate("form.open", "session", 30000)["level"] == stats.CRITICAL,
          "das Dreissigfache ist kritisch")

    stats.record("form.open", "session", 30000)
    check(abs(stats.reference("form.open", "session")["median_ms"] - 1000) < 50,
          "ein einzelner Ausreisser verschiebt den Median nicht")
    check(stats.soft_threshold("form.open", "session") > 1000,
          "die weiche Schwelle liegt ueber dem ueblichen Wert")

    stats.flush(force=True)
    stats._state = None
    check(stats.reference("form.open", "session")["known"],
          "die Referenzwerte ueberleben einen Neustart")
    check(not stats.reference("submit.send", "session")["known"],
          "ein Vorgang ohne Messung hat keine Referenz")


# ----------------------------------------------------------------- Span-Modell


async def spans_pruefen():
    print("Vorgangsmessung")
    strom = Ereignisse()
    spans.forget()
    async with spans.span("auth.check", scope="session", key="abc") as offen:
        check(len(spans.open_spans()) == 1, "ein laufender Vorgang ist sichtbar")
        check(offen.report()["name"] == "auth.check", "er kennt seinen Namen")
        await asyncio.sleep(0.05)
    check(not spans.open_spans(), "danach ist er nicht mehr offen")
    letzte = spans.recent(5)
    check(letzte and letzte[0]["name"] == "auth.check", "er steht in der Zeitleiste")
    check(letzte[0]["status"] == spans.OK, "und gilt als in Ordnung")
    check(len(strom.art("span_start")) == 1 and len(strom.art("span_end")) == 1,
          "Anfang und Ende gehen als Ereignis hinaus")
    check(any(z.get("ev") == "span_end" for z in journal.read()),
          "das Ende steht auch in der Tagesdatei")

    try:
        async with spans.span("auth.check", scope="session"):
            raise RuntimeError("mit Absicht")
    except RuntimeError:
        pass
    check(spans.recent(1)[0]["status"] == spans.ERROR,
          "ein Fehler im Vorgang wird als Fehler vermerkt")

    async with spans.span("state.detect", scope="session") as offen:
        spans.pause()
        gemessen = offen.elapsed_ms
        await asyncio.sleep(0.4)
        check(offen.elapsed_ms - gemessen < 50,
              "waehrend einer offenen Freigabe steht die Uhr still")
        spans.resume()

    stufe = spans.level()
    check(stufe["level"] in ("normal", "auffaellig", "blockiert"),
          "die Statusanzeige kennt drei Stufen")

    for _ in range(30):
        stats.record("state.detect", "session", 100)
    async with spans.span("state.detect", scope="session"):
        await asyncio.sleep(1.2)
    check(spans.recent(1)[0]["level"] == stats.CRITICAL,
          "eine deutlich zu lange Laufzeit wird als kritisch bewertet")
    check(len(strom.art("notification")) >= 1,
          "und wird gemeldet")
    check(spans.level()["level"] in ("auffaellig", "normal"),
          "eine einzelne Auffaelligkeit ist noch keine Haeufung")


# -------------------------------------------------------------------- Bericht


def bericht_pruefen():
    print("Bericht")
    text = report.build()
    check(text.startswith("# Bericht "), "der Bericht hat eine Ueberschrift mit Tag")
    check("## Laufzeiten je Vorgang" in text, "er listet die Laufzeiten je Vorgang")
    check("auth.check" in text, "ein gemessener Vorgang steht darin")
    check("## Blockaden" in text and "## Abgestufte Erkennungsmerkmale" in text,
          "Blockaden und Abstufungen haben eigene Abschnitte")
    ziel = report.write()
    check(ziel.is_file() and ziel.read_text(encoding="utf-8") == text,
          "der Bericht laesst sich als Datei ablegen")
    check(report.listing() and report.listing()[0]["name"] == ziel.name,
          "und steht danach in der Liste")


# ------------------------------------------------------------ Speichergrenze


def speicher_pruefen():
    print("Speichergrenze")
    einstellungen = config_store.load()
    einstellungen["storage_cap_mb"] = 50
    einstellungen["retention_days_incident"] = 7
    config_store.save(einstellungen)

    def vorfall(stempel, groesse_kb=200):
        ordner = incidents.root() / f"{stempel}-pruefung"
        ordner.mkdir(parents=True, exist_ok=True)
        (ordner / "daten.json").write_text(
            json.dumps({"incident": ordner.name, "at": "", "scope": "session",
                        "operation": "pruefung", "reason": "", "roles": {},
                        "stages": [], "material": {}}),
            encoding="utf-8",
        )
        (ordner / "gross.bin").write_bytes(b"x" * (groesse_kb * 1024))
        return ordner

    alt = vorfall("20200101T120000")
    neu = vorfall("20990101T120000")
    ergebnis = housekeeping.sweep()
    check(not alt.exists(), "ein Vorfall jenseits der Aufbewahrung wird geloescht")
    check(neu.exists(), "ein frischer Vorfall bleibt")
    check(alt.name in ergebnis["incidents"], "das Loeschen wird berichtet")

    einstellungen["storage_cap_mb"] = 50
    config_store.save(einstellungen)
    for nummer in range(1, 6):
        vorfall(f"2099010{nummer}T120000", groesse_kb=12_000)
    verbrauch = housekeeping.usage()
    check(verbrauch["recordings_bytes"] > 50 * 1024 * 1024, "die Aufzeichnungen sind ueber der Grenze")
    ergebnis = housekeeping.sweep()
    danach = housekeeping.usage()
    check(danach["recordings_bytes"] <= 50 * 1024 * 1024,
          "bei erreichter Obergrenze wird geloescht, bis es passt")
    check(len(ergebnis["incidents"]) >= 1, "und zwar die aeltesten zuerst")
    check(danach["cap_mb"] == 50 and "log_bytes" in danach,
          "der Verbrauch wird nach Datenart ausgewiesen")


# ---------------------------------------------------- Vorfall mit zwei Stufen


UEBUNG = """
  <h1 data-testid="ueberschrift">Uebungsseite</h1>
  <p data-testid="text">Ein Satz, der im Vorfall stehen soll.</p>
"""


async def schwellen_pruefen(instanz):
    print("Weiche und harte Schwelle")
    dokument = store.load("session")
    dokument["roles"] = [rolle("ueberschrift", "ueberschrift"), rolle("fehlt", "gibtesnicht")]
    store.save("session", dokument)
    await instanz.navigate(seite("uebung", UEBUNG), 30)

    einstellungen = config_store.load()
    einstellungen["limits"]["search.reload"] = 5
    config_store.save(einstellungen)

    stats.reset()
    for _ in range(30):
        stats.record("search.reload", "session", 200)

    strom = Ereignisse()
    spans.forget()
    frames.attach(instanz)
    # Genug Zeit fuer wenigstens ein Bild im Ringpuffer.
    await asyncio.sleep(frames.INTERVAL_S * 2 + 0.5)

    async def halten():
        async with spans.span("search.reload", instance=instanz):
            await asyncio.sleep(9)

    aufgabe = asyncio.create_task(halten())
    weich = None
    for _ in range(120):
        await asyncio.sleep(0.1)
        await watchdog.inspect()
        offen = spans.open_spans()
        if offen and offen[0].soft_hit:
            weich = offen[0].incident
            break
    check(weich is not None, "die weiche Schwelle greift, waehrend der Vorgang noch laeuft")
    check(len(strom.art("span_slow")) == 1, "sie wird als Ereignis gemeldet")

    hart = None
    for _ in range(200):
        await asyncio.sleep(0.1)
        await watchdog.inspect()
        offen = spans.open_spans()
        if offen and offen[0].hard_hit:
            hart = offen[0].incident
            break
        if not offen:
            break
    check(hart is not None and hart == weich,
          "die harte Schwelle schreibt in denselben Vorfall")
    await asyncio.wait_for(aufgabe, timeout=20)

    daten = incidents.read(weich)
    check(len(daten["stages"]) == 2, "der Vorfall haelt beide Erfassungen fest")
    check(daten["stages"][0]["stage"] == incidents.SOFT
          and daten["stages"][1]["stage"] == incidents.HARD,
          "erst die weiche, dann die harte")
    ordner = Path(daten["path"])
    zweite = ordner / daten["stages"][1]["folder"]
    check((ordner / "bild.png").is_file() and (zweite / "bild.png").is_file(),
          "zu jeder Erfassung gehoert ein Bild")
    check((ordner / "seite.html").is_file() and (ordner / "text.txt").is_file(),
          "dazu die Kopie der Seite und der sichtbare Text")
    erste = daten["stages"][0]
    check(erste.get("viewport", {}).get("width", 0) > 0 and erste.get("zoom"),
          "Fenstergroesse und Zoomstufe stehen dabei")
    check([r for r in erste["roles"]["found"] if r["role"] == "ueberschrift"],
          "die gefundenen Rollen sind benannt")
    check([r for r in erste["roles"]["missing"] if r["role"] == "fehlt"],
          "und die erwarteten, die fehlen")
    check(daten["context"]["span"] == "search.reload" and daten["context"]["median_ms"] > 0,
          "der Vorfall nennt den Vorgang und seinen Referenzwert")
    check(daten["material"]["frames"] >= 1,
          "die Bildfolge aus dem Ringpuffer liegt daneben")
    check((ordner / "bilder").is_dir(), "und zwar im Ordner bilder")
    bericht_text = (ordner / "bericht.md").read_text(encoding="utf-8")
    check("Erwartet, aber nicht gefunden" in bericht_text and "fehlt" in bericht_text,
          "die Zusammenfassung ist ohne Werkzeug lesbar")

    check(len(strom.art("span_blocked")) == 1, "die Blockade steht im Protokoll")
    meldungen = [e for e in strom.art("notification") if e.get("topic") == notify.BLOCKED]
    check(len(meldungen) >= 1, "und wird als Benachrichtigung gemeldet")

    # Der Kern holt sich die Meldungen ueber eine kurze Warteschlange und
    # fragt jeweils nach allem hinter der Nummer, die er zuletzt gesehen
    # hat. Zweimal dieselbe Meldung waere eine zweite Systemmeldung.
    warteschlange = notify.pending(0)
    check(any(m.get("topic") == notify.BLOCKED for m in warteschlange["messages"]),
          "die Blockade steht auch in der Warteschlange fuer den Kern")
    check(all(m.get("number") for m in warteschlange["messages"]),
          "jede Meldung traegt eine laufende Nummer")
    check(notify.pending(warteschlange["number"])["messages"] == [],
          "nach dem Abholen ist nichts Neues mehr offen")
    notify.notify(notify.CODE, "Pruefung")
    nachgereicht = notify.pending(warteschlange["number"])["messages"]
    check(len(nachgereicht) == 1 and nachgereicht[0]["topic"] == notify.CODE,
          "eine spaetere Meldung wird genau einmal nachgereicht")

    check(len(strom.art("recovery_started")) == 1,
          "danach laeuft die Wiederherstellung an")
    stufen = strom.art("recovery_stage")
    check(any(e["stage"] == "zustand" for e in stufen),
          "sie beginnt mit der Zustandspruefung")

    check(spans.recent(1)[0]["status"] == spans.BLOCKED,
          "der beendete Vorgang gilt als blockiert")
    check(spans.level()["level"] == "blockiert", "die Statusanzeige steht auf blockiert")

    liste = [e for e in incidents.listing() if e["incident"] == weich]
    check(liste and liste[0]["stages"] == 2 and liste[0]["span"] == "search.reload",
          "der Vorfall steht mit seinen Angaben in der Liste")

    dateien = [d["name"] for d in incidents.files_of(weich)]
    check("bericht.md" in dateien and any(n.startswith("bilder/") for n in dateien),
          "alle Dateien des Ordners sind abrufbar")
    verweigert = False
    try:
        incidents.file_of(weich, "../../config.json")
    except (ValueError, FileNotFoundError):
        verweigert = True
    check(verweigert, "ein Pfad aus dem Ordner heraus wird abgelehnt")

    await frames.detach(instanz.role)


# ------------------------------------------------------------------ Referenz


async def aufzeichnung_pruefen(instanz):
    print("Aufzeichnung und Referenzdurchlauf")
    zyklus = await tracing.begin(instanz, "pruefung")
    if not zyklus.recording:
        print("  Der Browser zeichnet nicht auf, dieser Teil wird uebersprungen")
        return
    tracing.note_success(instanz.role, "auth.check")
    datei = await tracing.end(instanz, 20)
    check(datei is not None and datei.is_file(),
          "ein Zyklus mit einem erfolgreichen Vorgang wird als Referenz behalten")
    verweis = tracing.reference_for("auth.check", instanz.role)
    check(verweis is not None and Path(verweis["path"]).is_file(),
          "der Referenzdurchlauf ist auffindbar")

    zyklus = await tracing.begin(instanz, "unauffaellig")
    vorher = len(tracing.recent(instanz.role, 50))
    await tracing.end(instanz, 20)
    check(len(tracing.recent(instanz.role, 50)) == vorher,
          "ein unauffaelliger Zyklus wird verworfen")

    await tracing.begin(instanz, "auffaellig")
    tracing.mark(instanz.role, "mit Absicht")
    datei = await tracing.end(instanz, 20)
    check(datei is not None and datei.is_file(), "ein auffaelliger Zyklus wird geschrieben")

    dokument = store.load("session")
    name = await incidents.capture(
        instanz, dokument, "referenzpruefung", "mit Absicht",
        material=True, span_name="auth.check",
    )
    daten = incidents.read(name)
    check(daten["material"]["reference"] is not None,
          "ein Vorfallsordner enthaelt den letzten erfolgreichen Referenzdurchlauf")
    check((Path(daten["path"]) / "referenz" / daten["material"]["reference"]["file"]).is_file(),
          "und zwar als Datei zum Oeffnen")
    check(daten["material"]["traces"] >= 1,
          "die Aufzeichnungen der letzten Zyklen liegen daneben")


# ------------------------------------------------------------------ Ausfuehrung


async def main():
    from playwright.async_api import async_playwright

    protokoll_pruefen()
    referenz_pruefen()
    await spans_pruefen()
    bericht_pruefen()
    speicher_pruefen()

    os.environ["LOCALAPPDATA"] = _echtes_lokal
    programm = browser_install.executable()
    os.environ["LOCALAPPDATA"] = _temp + "-lokal"
    if programm is None:
        print("  Der Browser ist nicht geladen, Pruefung nicht moeglich")
        raise SystemExit(1)

    playwright = await async_playwright().start()
    instanz = instances.Instance(instances.SESSION)
    await instanz.start(playwright, programm, 1280, 720, instances._running_pids(programm))
    try:
        await schwellen_pruefen(instanz)
        await aufzeichnung_pruefen(instanz)
    finally:
        await frames.detach_all()
        await instanz.close()
        await playwright.stop()

    print()
    if fehler:
        print(f"{len(fehler)} Pruefung(en) fehlgeschlagen:")
        for text in fehler:
            print("  - " + text)
        raise SystemExit(1)
    print("Alle Pruefungen bestanden")


if __name__ == "__main__":
    asyncio.run(main())
