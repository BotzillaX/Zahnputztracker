"""Check of the search cycle: identifiers, the whole list, the order.

Everything runs against exercise pages written here in the test. No live
site is involved and the provider of the message text is replaced by a
fixed string.

    .venv\\Scripts\\python.exe -m service.tests.test_search
"""
import asyncio
import os
import tempfile
from pathlib import Path

_temp = tempfile.mkdtemp(prefix="zt-search-")
os.environ["APPDATA"] = _temp
# Auch die Browser-Profile liegen im Testordner: eine Pruefung darf das
# echte, angemeldete Sitzungsprofil weder benutzen noch veraendern. Nur
# der Browser selbst wird dort gesucht, wo er wirklich liegt (siehe main).
_echtes_lokal = os.environ.get("LOCALAPPDATA", "")
os.environ["LOCALAPPDATA"] = _temp + "-lokal"
_pages = Path(_temp) / "seiten"
_pages.mkdir(parents=True, exist_ok=True)

from ..api.events import bus  # noqa: E402
from ..flow import contact as contact_flow  # noqa: E402
from ..flow import contract, keys  # noqa: E402
from ..flow import login as login_flow  # noqa: E402
from ..flow import search as search_flow  # noqa: E402
from ..registry import store  # noqa: E402
from ..runtime import browser_install, instances  # noqa: E402
from ..storage import config as config_store  # noqa: E402
from ..storage import database  # noqa: E402

fehler = []
# Der Ereignisstrom vergisst alte Eintraege. Die Reihenfolge der Funde
# wird deshalb mitgeschrieben, statt sie spaeter nachzulesen.
gefunden = []
bus.add_sink(lambda e: gefunden.append(e["key"]) if e["kind"] == "item_found" else None)
TEXT = "Guten Tag, hier ist mein Anliegen."
VORLAGE = ""


def check(bedingung, label):
    print(("  ok   " if bedingung else "  FEHL ") + label, flush=True)
    if not bedingung:
        fehler.append(label)


def seite(name, koerper):
    ziel = _pages / f"{name}.html"
    ziel.write_text(f"<html><body>{koerper}</body></html>", encoding="utf-8")
    return ziel.as_uri()


def rolle(name, testid, scope="session", menge="einzel"):
    return {
        "id": name,
        "label": name,
        "scope": scope,
        "menge": menge,
        "notes": "",
        "key_attribute": "",
        "answer": "",
        "options": [],
        "candidates": [{"kind": "attr", "attr": "data-testid", "value": testid}],
    }


# --------------------------------------------------------------- Uebungsseiten

FORMULAR = """
  <div id="formular" style="display:none">
    <textarea data-testid="nachricht"></textarea>
    <button data-testid="absenden"
            onclick="document.getElementById('danke').style.display='block'">Senden</button>
  </div>
"""


def eintragsseite(kennung, fertig=True):
    teile = []
    if fertig:
        teile.append('<div data-testid="fertig">Seite fertig</div>')
    teile.append(f"<p>Sichtbarer Text zu {kennung}.</p>")
    teile.append(
        '<button data-testid="oeffnen" '
        "onclick=\"document.getElementById('formular').style.display='block'\">Kontakt</button>"
    )
    teile.append(FORMULAR)
    teile.append('<div id="danke" data-testid="danke" style="display:none">Danke</div>')
    return seite(f"eintrag-{kennung}", "\n".join(teile))


def trefferliste(name, kennungen, kaputte=0):
    """Eine Ergebnisseite. Die Liste steht neueste zuerst."""
    zeilen = []
    for kennung in kennungen:
        zeilen.append(
            f'<div data-testid="treffer"><a href="eintrag-{kennung}.html?ref=liste">'
            f"Eintrag {kennung}</a></div>"
        )
    for nummer in range(kaputte):
        zeilen.append(
            f'<div data-testid="treffer"><a href="ganz-woanders-{nummer}.html">Fremd</a></div>'
        )
    return seite(name, "\n".join(zeilen))


# ------------------------------------------------------------------ Kennungen


def kennungen_pruefen():
    print("Kennungen aus der Adressvorlage")
    vorlage = "https://beispiel.invalid/x/{kennung}"
    check(keys.usable(vorlage), "eine Vorlage mit genau einem Platzhalter ist brauchbar")
    check(not keys.usable("https://beispiel.invalid/x/"), "ohne Platzhalter nicht")
    check(not keys.usable("https://beispiel.invalid/{kennung}/{kennung}"),
          "mit zwei Platzhaltern auch nicht")
    check(keys.key_of("https://beispiel.invalid/x/4711", vorlage) == "4711",
          "die Kennung wird aus der Adresse gelesen")
    check(keys.key_of("https://beispiel.invalid/x/4711?spur=1#unten", vorlage) == "4711",
          "Parameter und Sprungmarke aendern die Kennung nicht")
    check(keys.key_of("https://beispiel.invalid/y/4711", vorlage) == "",
          "eine fremde Adresse liefert keine Kennung")
    check(keys.key_of("https://beispiel.invalid/x/4711/mehr", vorlage) == "",
          "und eine tiefere Adresse auch nicht")
    check(keys.key_of("x/4711", vorlage, base="https://beispiel.invalid/liste") == "4711",
          "ein relativer Verweis wird an der Seite aufgeloest")
    check(keys.address_of("4711", vorlage) == "https://beispiel.invalid/x/4711",
          "aus der Kennung entsteht wieder eine Adresse")
    check(keys.key_of("", vorlage) == "" and keys.address_of("", vorlage) == "",
          "ohne Angabe wird nichts erfunden")


# ------------------------------------------------------------------- Vorpruefung


def vorpruefung(instanz):
    print("Vorpruefung vor dem Start")

    def scheitert(text):
        try:
            search_flow.loop.check(instanz)
            return ""
        except search_flow.SearchError as e:
            return str(e) if text in str(e) else f"anderer Grund: {e}"

    daten = config_store.load()
    daten["source"]["url"] = ""
    config_store.save(daten)
    check(scheitert("Adresse") != "", "ohne Adresse der Ergebnisseite startet nichts")

    daten = config_store.load()
    daten["source"]["url"] = "file:///liste"
    daten["source"]["item_url_template"] = "file:///ohne-platzhalter"
    config_store.save(daten)
    check(scheitert("Platzhalter") != "", "ohne Platzhalter in der Vorlage startet nichts")

    daten = config_store.load()
    daten["source"]["item_url_template"] = VORLAGE
    config_store.save(daten)
    store.save("search", {"roles": [], "states": []})
    check(scheitert("fehlt") != "", "ohne angelernte Rolle startet nichts")

    store.save("search", {"roles": [rolle(contract.ITEM_LINK, "treffer", scope="search")],
                          "states": []})
    check(scheitert("liste") != "", "mit der Menge 'einzel' startet nichts")

    store.save("search", {"roles": [rolle(contract.ITEM_LINK, "treffer", scope="search",
                                          menge="liste")], "states": []})
    try:
        search_flow.loop.check(instanz)
        check(True, "mit Adresse, Vorlage und Rolle ist alles bereit")
    except search_flow.SearchError as e:
        check(False, f"mit Adresse, Vorlage und Rolle ist alles bereit ({e})")


# ---------------------------------------------------------------------- Lauf


async def warte_bis(bedingung, sekunden=90):
    for _ in range(int(sekunden * 10)):
        if bedingung():
            return True
        await asyncio.sleep(0.1)
    return False


def gefundene_reihenfolge():
    return list(gefunden)


def zeile(key):
    verbindung = database.connect()
    try:
        treffer = [z for z in database.items(verbindung) if z["key"] == key]
        return treffer[0] if treffer else None
    finally:
        verbindung.close()


async def lauf_pruefen(suche, sitzung):
    print("Suchzyklus")
    # Die Liste steht neueste zuerst: c ist das juengste, a das aelteste.
    for kennung in ("a", "b", "c"):
        eintragsseite(kennung)
    liste = trefferliste("liste", ["c", "b", "a"], kaputte=1)

    daten = config_store.load()
    daten["source"]["url"] = liste
    daten["source"]["item_url_template"] = VORLAGE
    daten["source"]["reload_min_s"] = 1
    daten["source"]["reload_max_s"] = 1
    config_store.save(daten)

    vorher = len(gefundene_reihenfolge())
    lauf = asyncio.create_task(search_flow.loop.run(suche, sitzung))
    fertig = await warte_bis(lambda: search_flow.loop.contacted >= 3)
    check(fertig, "alle drei neuen Eintraege werden bearbeitet")

    reihenfolge = gefundene_reihenfolge()[vorher:]
    check(reihenfolge[:3] == ["a", "b", "c"],
          f"und zwar in umgekehrter Listenreihenfolge, aeltester zuerst ({reihenfolge[:3]})")
    check(search_flow.loop.last_seen == 3,
          f"die gesamte Trefferliste wird gelesen ({search_flow.loop.last_seen})")
    check(search_flow.loop.unreadable == 1,
          "ein Verweis ohne erkennbare Kennung wird gezaehlt, nicht geraten")
    for kennung in ("a", "b", "c"):
        z = zeile(kennung)
        check(z is not None and z["status"] == database.STATUS_CONTACTED,
              f"Eintrag {kennung} ist als kontaktiert dokumentiert "
              f"({z and z['status']}: {z and z['reason']})")

    # Zweiter Durchgang: nichts davon ist noch neu.
    zyklus = search_flow.loop.cycles
    await warte_bis(lambda: search_flow.loop.cycles > zyklus)
    await warte_bis(lambda: search_flow.loop.last_new == 0, 30)
    check(search_flow.loop.last_new == 0, "bekannte Eintraege werden nicht erneut bearbeitet")
    check(search_flow.loop.contacted == 3, "und es wird nichts doppelt gesendet")

    lauf.cancel()
    try:
        await lauf
    except asyncio.CancelledError:
        pass
    check(not search_flow.loop.running, "nach dem Abbruch laeuft der Zyklus nicht mehr")


async def nachschub_pruefen(suche, sitzung):
    print("Nachschub und Zurueckstellen")
    # d und e kommen gleichzeitig dazu, f hat keine fertige Seite.
    for kennung in ("d", "e"):
        eintragsseite(kennung)
    eintragsseite("f", fertig=False)
    liste = trefferliste("liste2", ["f", "e", "d", "c", "b", "a"])

    daten = config_store.load()
    daten["source"]["url"] = liste
    daten["limits"]["item.open"] = 5
    config_store.save(daten)

    vorher = search_flow.loop.contacted
    lauf = asyncio.create_task(search_flow.loop.run(suche, sitzung))
    fertig = await warte_bis(lambda: search_flow.loop.contacted >= vorher + 2)
    check(fertig, "ein Schwung mehrerer neuer Eintraege wird vollstaendig verarbeitet")
    await warte_bis(lambda: "f" in search_flow.loop.deferred, 60)
    check("f" in search_flow.loop.deferred,
          "ein Eintrag ohne Ergebnis wird fuer diesen Lauf zurueckgestellt")
    zyklus = search_flow.loop.cycles
    await warte_bis(lambda: search_flow.loop.cycles > zyklus + 1, 60)
    check(search_flow.loop.contacted == vorher + 2,
          "und im naechsten Zyklus nicht sofort wieder aufgegriffen")

    lauf.cancel()
    try:
        await lauf
    except asyncio.CancelledError:
        pass


async def pause_pruefen():
    print("Pause")
    check(await warte_bis(lambda: True), "ohne Grund wird nicht gewartet")
    instances.fleet.paused = True
    try:
        await asyncio.wait_for(search_flow.loop._hold(), timeout=1.0)
        check(False, "bei Pause wartet der Zyklus")
    except asyncio.TimeoutError:
        check(True, "bei Pause wartet der Zyklus")
    finally:
        instances.fleet.paused = False
    await asyncio.wait_for(search_flow.loop._hold(), timeout=2.0)
    check(True, "nach dem Fortsetzen geht es weiter")


# ---------------------------------------------------------------------- Start


async def main():
    global VORLAGE
    from playwright.async_api import async_playwright

    VORLAGE = (_pages / "eintrag-{kennung}.html").as_uri().replace("%7Bkennung%7D", "{kennung}")

    daten = config_store.load()
    daten["review_mode"] = False
    daten["confirm_wait_s"] = 0.5
    daten["limits"]["submit.confirm"] = 5
    daten["limits"]["form.open"] = 5
    daten["composer"]["prompt"] = "Schreibe: {{seitentext}}"
    config_store.save(daten)

    store.save("session", {"roles": [
        rolle(contract.READY_MARKER, "fertig"),
        rolle(contract.OPEN_FORM, "oeffnen"),
        rolle(contract.MESSAGE_FIELD, "nachricht"),
        rolle(contract.SUBMIT_ACTION, "absenden"),
        rolle(contract.CONFIRMATION_MARKER, "danke"),
    ], "states": []})

    kennungen_pruefen()

    os.environ["LOCALAPPDATA"] = _echtes_lokal
    programm = browser_install.executable()
    os.environ["LOCALAPPDATA"] = _temp + "-lokal"
    if programm is None:
        print("  Der Browser ist nicht geladen, Pruefung nicht moeglich")
        raise SystemExit(1)

    async def text_erzeugen(prompt, einstellungen):
        return TEXT

    async def angemeldet(instanz):
        return {"already": True, "signed_in": True}

    echt_generate = contact_flow.generate
    echt_ensure = login_flow.ensure
    contact_flow.generate = text_erzeugen
    login_flow.ensure = angemeldet

    playwright = await async_playwright().start()
    suche = instances.Instance(instances.SEARCH)
    sitzung = instances.Instance(instances.SESSION)
    laufend = instances._running_pids(programm)
    await suche.start(playwright, programm, 1280, 720, laufend)
    await sitzung.start(playwright, programm, 1280, 720, instances._running_pids(programm))
    try:
        vorpruefung(suche)
        await lauf_pruefen(suche, sitzung)
        await nachschub_pruefen(suche, sitzung)
        await pause_pruefen()
    finally:
        contact_flow.generate = echt_generate
        login_flow.ensure = echt_ensure
        await suche.close()
        await sitzung.close()
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
