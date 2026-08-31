"""Check of the picker, the recognition candidates and the page catalogue.

Opens one real browser window on a locally built exercise page. The page
is written here in the test and has nothing to do with any live site.

    .venv\\Scripts\\python.exe -m service.tests.test_picker
"""
import asyncio
import os
import tempfile

# Roaming data (registry, catalogue) into a temporary directory. The
# local directory stays real, the browser binary lives there.
_temp = tempfile.mkdtemp(prefix="zt-picker-")
os.environ["APPDATA"] = _temp

from ..api.events import bus  # noqa: E402
from ..atlas import catalog  # noqa: E402
from ..picker import snapshot as snapshot_view  # noqa: E402
from ..picker.session import picker  # noqa: E402
from ..registry import model, resolve  # noqa: E402
from ..runtime import browser_install, instances  # noqa: E402

fehler = []


def check(bedingung, label):
    print(("  ok   " if bedingung else "  FEHL ") + label, flush=True)
    if not bedingung:
        fehler.append(label)


def rolle(name, kandidaten, menge="einzel"):
    return {
        "id": name,
        "label": name,
        "scope": "search",
        "menge": menge,
        "notes": "",
        "key_attribute": "",
        "options": [],
        "candidates": kandidaten,
    }


def ereignis(art):
    return [e for e in bus.replay() if e["kind"] == art]


SEITE = """
<html><head><title>Uebungsseite</title></head><body>
  <div id="haupt">
    <button data-testid="ziel-a" id="knopf-a">Weiter</button>
    <div class="karte" data-item="1"><h2>Titel eins</h2><a href="/a/1">oeffnen</a></div>
    <div class="karte" data-item="2"><h2>Titel zwei</h2><a href="/a/2">oeffnen</a></div>
    <button data-testid="doppelt" style="display:none">Verborgen</button>
    <button data-testid="doppelt">Sichtbar</button>
    <button data-testid="zweimal">A</button>
    <button data-testid="zweimal">B</button>
    <select data-testid="auswahl">
      <option value="">bitte waehlen</option>
      <option value="EINS">Eins</option>
      <option value="ZWEI">Zwei</option>
    </select>
  </div>
</body></html>
"""

ZWEITE_SEITE = "<html><body><main><p>Andere Ansicht</p><button>Zurueck</button></main></body></html>"


async def main():
    from playwright.async_api import async_playwright

    programm = browser_install.executable()
    if programm is None:
        print("  Der Browser ist nicht geladen, Pruefung nicht moeglich")
        raise SystemExit(1)

    playwright = await async_playwright().start()
    instanz = instances.Instance(instances.SEARCH)
    await instanz.start(playwright, programm, 1280, 720, instances._running_pids(programm))
    seite = instanz.page
    try:
        await seite.set_content(SEITE)

        # --------------------------------------------------------- Overlay da
        vorhanden = await seite.evaluate("() => typeof window.__ztOverlay === 'object'")
        check(vorhanden, "Overlay ist nach dem Seitenaufbau vorhanden")

        # ------------------------------------------- Merkmale (Spec 2.4)
        knopf = await seite.evaluate(
            "() => window.__ztOverlay.describe(document.querySelector('#knopf-a'))"
        )
        arten = [k["kind"] for k in knopf["candidates"]]
        check(arten[0] == "attr", f"Datenattribut steht an erster Stelle ({arten})")
        check(arten == sorted(arten, key=lambda a: model.KINDS.index(a)),
              "die Merkmale stehen in der Reihenfolge der Spezifikation")
        check(any(k["kind"] == "aria" and k["role"] == "button" for k in knopf["candidates"]),
              "Rolle und Name wurden erkannt")
        check(any(k["kind"] == "text" and k["value"] == "Weiter" for k in knopf["candidates"]),
              "sichtbarer Text wurde erkannt")
        check(knopf["visible"], "Sichtbarkeit wird gemeldet")
        pfad = [k for k in knopf["candidates"] if k["kind"] == "path"][0]["value"]
        check(
            await seite.evaluate("(p) => document.querySelectorAll(p).length", pfad) == 1,
            f"der Strukturpfad ist ein gueltiger Ausdruck und trifft genau einmal ({pfad})",
        )

        erzeugt = await seite.evaluate(
            "() => { const b=document.createElement('button');"
            " b.id='tab-panel-8837219'; b.textContent='x'; document.body.appendChild(b);"
            " const d = window.__ztOverlay.describe(b); b.remove(); return d; }"
        )
        check(not any(k["kind"] == "id" for k in erzeugt["candidates"]),
              "eine erzeugt wirkende Kennung wird nicht als Merkmal genommen")

        auswahl = await seite.evaluate(
            "() => window.__ztOverlay.describe(document.querySelector('[data-testid=auswahl]'))"
        )
        check([o["value"] for o in auswahl["options"]] == ["", "EINS", "ZWEI"],
              "alle Werte eines Auswahlfeldes werden ausgelesen")

        # ------------------------------------------------- Wiederfinden
        treffer = await resolve.locate(seite, rolle("a", knopf["candidates"]))
        check(treffer.found and treffer.step == 0 and not treffer.degraded,
              "das erste Merkmal greift, keine Degradierung")
        check(await seite.locator("[data-zt-hit]").count() == 1,
              "genau ein Element ist markiert")

        degradiert = await resolve.locate(
            seite,
            rolle("b", [
                {"kind": "attr", "attr": "data-testid", "value": "gibt-es-nicht"},
                {"kind": "aria", "role": "button", "value": "Weiter"},
            ]),
        )
        check(degradiert.found and degradiert.step == 1 and degradiert.degraded,
              "Ausweichen auf ein schwaecheres Merkmal wird als Degradierung gemeldet")
        check(bool(ereignis("degraded")), "die Degradierung steht im Ereignisstrom")

        doppelt = await resolve.locate(
            seite, rolle("c", [{"kind": "attr", "attr": "data-testid", "value": "doppelt"}])
        )
        check(doppelt.found and doppelt.count == 1,
              "bei verborgenem Zwilling wird das sichtbare Element genommen")
        check(bool(ereignis("duplicate_resolved")), "der Mehrfachtreffer wurde protokolliert")

        try:
            await resolve.locate(
                seite, rolle("d", [{"kind": "attr", "attr": "data-testid", "value": "zweimal"}])
            )
            check(False, "zwei sichtbare Treffer gelten als unbekannter Zustand")
        except resolve.UnknownState:
            check(True, "zwei sichtbare Treffer gelten als unbekannter Zustand")

        liste = await resolve.locate(
            seite, rolle("e", [{"kind": "path", "value": ".karte"}], menge="liste")
        )
        check(liste.found and liste.count == 2, "eine Listenrolle markiert alle Treffer")

        nichts = await resolve.locate(
            seite, rolle("f", [{"kind": "text", "value": "steht nirgends"}])
        )
        check(not nichts.found and nichts.reason, "kein Treffer wird als solcher gemeldet")

        leer = await resolve.locate(seite, rolle("g", []))
        check(not leer.found, "eine nicht angelernte Rolle findet nichts")
        check(await seite.locator("[data-zt-hit]").count() == 0,
              "nach der Suche bleibt keine Markierung zurueck")

        # ------------------------------------------------- Auswahl von Hand
        await picker.start(seite, "search")
        check(picker.active, "Auswahlmodus laeuft")
        kasten = await seite.locator(".karte h2").first.bounding_box()
        await seite.mouse.move(kasten["x"] + kasten["width"] / 2, kasten["y"] + kasten["height"] / 2)
        await asyncio.sleep(0.3)

        kopie = await seite.evaluate("() => window.__ztOverlay.snapshot()")
        check("data-zt-ui" not in kopie, "das Overlay steht in keiner gespeicherten Kopie")

        await seite.keyboard.press("ArrowUp")
        await asyncio.sleep(0.2)
        await seite.keyboard.press("Enter")
        await asyncio.sleep(0.5)
        gewaehlt = picker.pick
        check(gewaehlt is not None, "die Auswahl kam beim Dienst an")
        if gewaehlt:
            check(gewaehlt["element"]["tag"] == "div",
                  f"die Pfeiltaste hat die Ebene gewechselt ({gewaehlt['element']['tag']})")
            check(any(k["kind"] == "attr" and k["attr"] == "data-item"
                      for k in gewaehlt["element"]["candidates"]),
                  "zur Auswahl wurden Merkmale erzeugt")
        check(not picker.active, "Enter beendet den Auswahlmodus")

        await picker.start(seite, "search")
        await seite.keyboard.press("Escape")
        await asyncio.sleep(0.3)
        check(not picker.active, "Esc bricht ab")

        # ------------------------------------------------- Seiten-Katalog
        erste = await catalog.capture(seite, "search", trigger="Pruefung")
        check(erste is not None, "die Ansicht steht im Katalog")
        check("Pruefung" in erste["arrivals"], "der Weg in die Ansicht wurde vermerkt")
        nochmal = await catalog.capture(seite, "search", trigger="Pruefung")
        check(nochmal["view"] == erste["view"] and nochmal["count"] == erste["count"] + 1,
              "eine bekannte Ansicht erhoeht nur den Zaehler")
        await seite.set_content(ZWEITE_SEITE)
        andere = await catalog.capture(seite, "search", trigger="Pruefung")
        check(andere["view"] != erste["view"], "eine andere Struktur ist eine neue Ansicht")
        check(len(catalog.views("search")) == 2, "beide Ansichten stehen im Katalog")

        gesichert = catalog.snapshot_file("search", erste["view"])
        inhalt = gesichert.read_text(encoding="utf-8")
        check("data-zt-ui" not in inhalt, "auch die gesicherte Kopie ist frei vom Overlay")
        check(catalog.screenshot_file("search", erste["view"]).stat().st_size > 0,
              "zur Ansicht wurde ein Bild gesichert")
        check(str(catalog.root()).startswith(_temp), "der Katalog liegt ausserhalb des Programms")

        # ------------------------------------- Picker auf gespeicherter Kopie
        gefaehrlich = gesichert.parent / "mit-skript.html"
        gefaehrlich.write_text(
            "<html><head><title>Kopie</title></head><body>"
            "<script>document.title='geraten'</script>"
            "<button onclick=\"document.title='geklickt'\" data-testid='ziel-a'>Weiter</button>"
            "<img src='http://beispiel.invalid/bild.png'>"
            "</body></html>",
            encoding="utf-8",
        )
        entschaerft = snapshot_view.defuse(gefaehrlich.read_text(encoding="utf-8"))
        check("<script" not in entschaerft.lower(), "Skripte werden aus der Kopie entfernt")
        check("onclick" not in entschaerft.lower(), "Ereignisbehandler werden entfernt")

        geoeffnet = await snapshot_view.open_on(seite, gefaehrlich)
        check(geoeffnet["url"].startswith("file:"), "die Kopie wird oertlich geoeffnet")
        check(await seite.title() != "geraten", "kein Skript der Kopie ist gelaufen")
        auf_kopie = await resolve.locate(
            seite, rolle("h", [{"kind": "attr", "attr": "data-testid", "value": "ziel-a"}])
        )
        check(auf_kopie.found, "der Picker findet Rollen auch auf der Kopie")
        check(len(catalog.views("search")) == 2, "eine geoeffnete Kopie kommt nicht in den Katalog")

        # Die Sperre darf nicht haengen bleiben: der naechste Aufruf einer
        # Adresse hebt sie auf, sonst waere der Browser danach taub.
        ziel_kopie = gesichert.as_uri()
        erreicht = await instanz.navigate(ziel_kopie, 20)
        check(erreicht == ziel_kopie, "nach der Kopie ist der Browser wieder ansprechbar")
        await snapshot_view.release(seite)

        # Signatur: die Anzahl der Eintraege darf keine neue Ansicht ergeben.
        gerippe = "<html><body><main>%s<button>Weiter</button></main></body></html>"
        eintrag = "<div class='k' data-item='x'><h2>t</h2></div>"
        await seite.set_content(gerippe % (eintrag * 3))
        wenige = await seite.evaluate("() => window.__ztOverlay.signature()")
        await seite.set_content(gerippe % (eintrag * 17))
        viele = await seite.evaluate("() => window.__ztOverlay.signature()")
        check(wenige == viele, "mehr Eintraege ergeben dieselbe Ansicht")
        await seite.set_content(gerippe % (eintrag * 3 + "<select><option>a</option></select>"))
        anders = await seite.evaluate("() => window.__ztOverlay.signature()")
        check(anders != wenige, "eine andere Art von Element ergibt eine andere Ansicht")
    finally:
        await instanz.close()
        await playwright.stop()


asyncio.run(main())
print()
if fehler:
    print(f"{len(fehler)} Pruefung(en) fehlgeschlagen")
    raise SystemExit(1)
print("alle Pruefungen bestanden")
