"""Check of states, conditions, action chains and templates.

The first part needs nothing but a temporary directory. The second part
opens one real browser window on an exercise page that is written here in
the test and has nothing to do with any live site.

    .venv\\Scripts\\python.exe -m service.tests.test_engine
"""
import asyncio
import json
import os
import tempfile

_temp = tempfile.mkdtemp(prefix="zt-engine-")
os.environ["APPDATA"] = _temp
# Auch die Browser-Profile liegen im Testordner: eine Pruefung darf das
# echte, angemeldete Sitzungsprofil weder benutzen noch veraendern. Nur
# der Browser selbst wird dort gesucht, wo er wirklich liegt (siehe main).
_echtes_lokal = os.environ.get("LOCALAPPDATA", "")
os.environ["LOCALAPPDATA"] = _temp + "-lokal"

from ..api.events import bus  # noqa: E402
from ..engine import approval, runner, states, templates  # noqa: E402
from ..engine.variables import space  # noqa: E402
from ..registry import model, store  # noqa: E402
from ..runtime import browser_install, instances  # noqa: E402
from ..storage import config as config_store  # noqa: E402

fehler = []


def check(bedingung, label):
    print(("  ok   " if bedingung else "  FEHL ") + label, flush=True)
    if not bedingung:
        fehler.append(label)


def faellt(aufruf, label, fehlerart=model.RegistryError):
    try:
        aufruf()
    except fehlerart:
        check(True, label)
        return
    except Exception as error:  # noqa: BLE001
        check(False, f"{label} (falsche Fehlerart: {type(error).__name__}: {error})")
        return
    check(False, f"{label} (kein Fehler)")


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


def attribut(wert):
    return [{"kind": "attr", "attr": "data-testid", "value": wert}]


def bedingung(art, name):
    return {"kind": art, "role": name}


def zustand(kennung, label, prioritaet, alle, aktionen, oder=None):
    return {
        "id": kennung,
        "label": label,
        "priority": prioritaet,
        "enabled": True,
        "all": alle,
        "any": oder or [],
        "actions": aktionen,
    }


def ereignisse(art):
    return [e for e in bus.replay() if e["kind"] == art]


# --------------------------------------------------------------- Modellteil


def modell_pruefen():
    print("Modell")

    gut = zustand("a_offen", "A offen", 10, [bedingung("sichtbar", "knopf")],
                  [{"type": "klicken", "mode": "automatisch", "role": "knopf"}])
    sauber = model.clean_state(gut)
    check(sauber["priority"] == 10 and sauber["enabled"], "ein vollstaendiger Zustand wird angenommen")
    check(sauber["actions"][0]["mode"] == "automatisch", "der Standardmodus ist automatisch")

    faellt(lambda: model.clean_state(zustand("leer", "Leer", 10, [], [])),
           "ein Zustand ohne jede Bedingung wird abgelehnt")
    faellt(lambda: model.clean_state(zustand("a_offen", "A", 0, [bedingung("sichtbar", "knopf")], [])),
           "eine Prioritaet ausserhalb des Bereichs wird abgelehnt")
    faellt(lambda: model.clean_state(zustand("a_offen", "A", 10, [{"kind": "vielleicht", "role": "knopf"}], [])),
           "eine unbekannte Bedingungsart wird abgelehnt")
    faellt(lambda: model.clean_state(zustand("a_offen", "A", 10, [bedingung("sichtbar", "knopf")],
                                            [{"type": "zaubern", "role": "knopf"}])),
           "eine unbekannte Aktion wird abgelehnt")
    faellt(lambda: model.clean_state(zustand("a_offen", "A", 10, [bedingung("sichtbar", "knopf")],
                                            [{"type": "klicken"}])),
           "eine Aktion ohne Rolle wird abgelehnt")
    faellt(lambda: model.clean_state(zustand("a_offen", "A", 10, [bedingung("sichtbar", "knopf")],
                                            [{"type": "warten", "seconds": 9999}])),
           "eine unsinnige Wartezeit wird abgelehnt")
    faellt(lambda: model.clean_state(zustand("a_offen", "A", 10, [bedingung("sichtbar", "knopf")],
                                            [{"type": "text_eintragen", "role": "knopf",
                                              "source": {"art": "geraten", "name": "x"}}])),
           "eine unbekannte Quelle wird abgelehnt")
    faellt(lambda: model.clean_state(zustand("a_offen", "A", 10, [bedingung("sichtbar", "knopf")],
                                            [{"type": "klicken", "role": "knopf", "mode": "irgendwie"}])),
           "ein unbekannter Ausfuehrungsmodus wird abgelehnt")

    # Verweise muessen auf vorhandene Rollen zeigen.
    faellt(lambda: model.clean_document(
        {"roles": [], "states": [zustand("a_offen", "A", 10, [bedingung("sichtbar", "fehlt")], [])]},
        "search"),
        "ein Verweis auf eine unbekannte Rolle wird abgelehnt")

    beschreibung = model.describe_action(
        model.clean_action({"type": "text_eintragen", "role": "feld",
                            "source": {"art": "geheimnis", "name": "account-password"}}, 1),
        [{"id": "feld", "label": "Kennwortfeld"}])
    check("Kennwortfeld" in beschreibung and "Geheimnis" in beschreibung,
          "die Beschreibung nennt Rolle und Quelle")

    # Bedingungslogik ohne Seite.
    z = model.clean_state(zustand("x_y", "X", 10,
                                  [bedingung("sichtbar", "eins"), bedingung("unsichtbar", "zwei")],
                                  [], [bedingung("sichtbar", "drei"), bedingung("sichtbar", "vier")]))
    check(states.holds(z, {"eins": True, "zwei": False, "drei": True, "vier": False}),
          "UND erfuellt und ein Glied der ODER-Gruppe erfuellt")
    check(not states.holds(z, {"eins": True, "zwei": False, "drei": False, "vier": False}),
          "ohne ein Glied der ODER-Gruppe trifft der Zustand nicht zu")
    check(not states.holds(z, {"eins": True, "zwei": True, "drei": True, "vier": True}),
          "eine verletzte UND-Bedingung reicht zum Ausschluss")


def ablage_pruefen():
    print("Ablage")
    store.save("search", {"roles": [rolle("knopf", attribut("ziel"))], "states": []})
    store.put_state("search", zustand("a_offen", "A offen", 10, [bedingung("sichtbar", "knopf")], []))
    check(len(store.load("search")["states"]) == 1, "ein Zustand wird gespeichert")
    check(store.free_state_id("search", "a_offen") == "a_offen_2",
          "eine belegte Kennung wird durchgezaehlt")
    store.put_state("search", zustand("a_offen", "Neuer Name", 20, [bedingung("sichtbar", "knopf")], []))
    check(len(store.load("search")["states"]) == 1 and store.load("search")["states"][0]["label"] == "Neuer Name",
          "ein zweites Speichern ersetzt statt zu doppeln")
    store.drop_state("search", "a_offen")
    check(store.load("search")["states"] == [], "ein Zustand laesst sich loeschen")
    faellt(lambda: store.drop_state("search", "a_offen"),
           "das Loeschen eines unbekannten Zustands wird abgelehnt")


def vorlagen_pruefen():
    print("Vorlagen")
    store.save("search", {"roles": [], "states": []})
    geladen = templates.load()
    check(len(geladen["templates"]) == len(templates.DEFAULTS) and geladen["enabled"],
          "die Vorlagendatei wird beim ersten Lesen angelegt")
    check(os.path.exists(templates.file_path()), "die Vorlagen liegen in einer eigenen Datei")

    faellt(lambda: templates.apply("search", "vorlage_zustimmung"),
           "eine Vorlage ohne die noetigen Rollen wird abgelehnt", templates.TemplateError)

    store.add_catalogue("search")
    dokument = templates.apply("search", "vorlage_zustimmung")
    check(any(z["origin"] == "vorlage_zustimmung" for z in dokument["states"]),
          "eine geladene Vorlage merkt sich ihre Herkunft")
    zweimal = templates.apply("search", "vorlage_zustimmung")
    check(len(zweimal["states"]) == 2 and zweimal["states"][1]["id"] != zweimal["states"][0]["id"],
          "zweimal laden ergibt zwei Zustaende mit verschiedenen Kennungen")

    templates.drop("vorlage_zustimmung")
    check(all(e["id"] != "vorlage_zustimmung" for e in templates.load()["templates"]),
          "eine einzelne Vorlage laesst sich loeschen")
    check(len(templates.load()["templates"]) == len(templates.DEFAULTS) - 1,
          "die uebrigen Vorlagen bleiben erhalten")

    templates.set_enabled(False)
    check(templates.offered("search") == [], "abgeschaltet wird keine Vorlage angeboten")
    faellt(lambda: templates.apply("search", "vorlage_liste_leer"),
           "abgeschaltet laesst sich auch keine laden", templates.TemplateError)
    templates.set_enabled(True)
    templates.reset()
    check(len(templates.load()["templates"]) == len(templates.DEFAULTS),
          "der mitgelieferte Satz laesst sich wiederherstellen")

    for vorlage in templates.DEFAULTS:
        model.clean_state(vorlage["state"])
    inhalt = json.dumps(templates.DEFAULTS)
    check('"candidates"' not in inhalt, "keine Vorlage bringt ein Erkennungsmerkmal mit")

    store.save("search", {"roles": [], "states": []})


# ------------------------------------------------------------- Browserteil

SEITE = """
<html><body><div id="haupt">
  <button data-testid="zustimmung">Einverstanden</button>
</div></body></html>
"""

FORMULAR = """
<html><body><div id="haupt">
  <input data-testid="name" type="text" />
  <select data-testid="auswahl">
    <option value="">bitte waehlen</option>
    <option value="EINS">Eins</option>
  </select>
  <input data-testid="haken" type="checkbox" />
  <button data-testid="senden">Senden</button>
  <p>Sichtbarer Fliesstext der Uebungsseite.</p>
</div></body></html>
"""

FREMD = "<html><body><main><p>Etwas ganz anderes</p></main></body></html>"

DOPPELT = """
<html><body><div id="haupt">
  <button data-testid="zustimmung">Eins</button>
  <button data-testid="zustimmung">Zwei</button>
</div></body></html>
"""


def registrierung_setzen(zustaende):
    store.save("search", {
        "roles": [
            rolle("zustimmung", attribut("zustimmung")),
            rolle("name", attribut("name")),
            rolle("auswahl", attribut("auswahl")),
            rolle("haken", attribut("haken")),
            rolle("senden", attribut("senden")),
        ],
        "states": zustaende,
    })


async def browser_pruefen(instanz):
    seite = instanz.page

    print("Zustandserkennung")
    registrierung_setzen([
        zustand("zustimmung_offen", "Zustimmung offen", 10,
                [bedingung("sichtbar", "zustimmung")],
                [{"type": "klicken", "role": "zustimmung"},
                 {"type": "warten_verschwunden", "role": "zustimmung", "seconds": 5},
                 {"type": "erneut_pruefen"}]),
        zustand("formular_offen", "Formular offen", 20,
                [bedingung("sichtbar", "name"), bedingung("unsichtbar", "zustimmung")],
                [{"type": "text_eintragen", "role": "name",
                  "source": {"art": "konfiguration", "name": "Vorname"}},
                 {"type": "auswahl_setzen", "role": "auswahl", "value": "EINS"},
                 {"type": "auswahl_setzen", "role": "haken", "value": "ja"},
                 {"type": "text_auslesen", "target": "seitentext"}]),
    ])

    await seite.set_content(SEITE)
    bericht = await runner.state_report(instanz, "search")
    check(bericht["chosen"] == "zustimmung_offen", "der zutreffende Zustand wird erkannt")
    check(bericht["visible"] == {"zustimmung": True, "name": False},
          "jede beteiligte Rolle wird genau einmal geprueft")

    await seite.set_content(FREMD)
    bericht = await runner.state_report(instanz, "search")
    check(bericht["chosen"] == "" and "Kein definierter Zustand" in bericht["reason"],
          "eine unbekannte Ansicht ergibt keinen Zustand")

    print("Aktionsketten")
    einstellungen = config_store.load()
    einstellungen["profile_values"] = [{"label": "Vorname", "value": "Testwert"}]
    config_store.save(einstellungen)

    # Die Kette der Zustimmung endet mit einer erneuten Pruefung; danach
    # steht das Formular, also laeuft die zweite Kette im selben Durchlauf.
    await seite.set_content(SEITE)
    await seite.evaluate(
        "() => { document.querySelector('[data-testid=zustimmung]')"
        ".addEventListener('click', () => { document.body.innerHTML = "
        + json.dumps(FORMULAR.split("<body>")[1].split("</body>")[0])
        + "; }); }"
    )
    bericht = await runner.run_once(instanz, "search")
    check(bericht["stopped"] == "", f"die Kette laeuft durch ({bericht['stopped']})")
    check(len(bericht["rounds"]) == 2, "eine erneute Pruefung startet einen zweiten Durchgang")
    check(await seite.input_value("[data-testid=name]") == "Testwert",
          "der Text kommt aus der Konfiguration in das Feld")
    check(await seite.input_value("[data-testid=auswahl]") == "EINS", "das Auswahlfeld ist gesetzt")
    check(await seite.is_checked("[data-testid=haken]"), "der Haken ist gesetzt")
    check("Fliesstext" in space.get("seitentext"), "der Seitentext liegt in der Variablen")

    print("Kein Raten")
    await seite.set_content(DOPPELT)
    bericht = await runner.run_once(instanz, "search")
    check(bericht["kind"] == "unknown_state" and bericht["rounds"] == [],
          "zwei sichtbare Treffer halten den Lauf an, ohne etwas zu tun")

    await seite.set_content(FREMD)
    bericht = await runner.run_once(instanz, "search")
    check(bericht["kind"] == "unknown_state", "eine unbekannte Ansicht haelt den Lauf an")
    check(len(ereignisse("engine_stopped")) >= 2, "jedes Anhalten wird gemeldet")

    registrierung_setzen([
        zustand("gleichstand_a", "Gleichstand A", 50, [bedingung("sichtbar", "zustimmung")], []),
        zustand("gleichstand_b", "Gleichstand B", 50, [bedingung("sichtbar", "zustimmung")], []),
    ])
    await seite.set_content(SEITE)
    bericht = await runner.run_once(instanz, "search")
    check(bericht["kind"] == "unknown_state" and "Priorität" in bericht["stopped"],
          "zwei gleichrangige Zustaende werden nicht ausgewuerfelt")

    registrierung_setzen([
        zustand("vorrang_a", "Vorrang A", 5, [bedingung("sichtbar", "zustimmung")], []),
        zustand("vorrang_b", "Vorrang B", 50, [bedingung("sichtbar", "zustimmung")], []),
    ])
    bericht = await runner.state_report(instanz, "search")
    check(bericht["chosen"] == "vorrang_a", "die kleinere Zahl hat den Vorrang")

    print("Ausfuehrungsmodi")
    registrierung_setzen([
        zustand("mit_freigabe", "Mit Freigabe", 10, [bedingung("sichtbar", "zustimmung")],
                [{"type": "klicken", "role": "zustimmung", "mode": "freigabe"}]),
    ])
    await seite.set_content(SEITE)
    lauf = asyncio.create_task(runner.run_once(instanz, "search"))
    for _ in range(50):
        if approval.gate.open:
            break
        await asyncio.sleep(0.05)
    check(approval.gate.open, "eine Aktion mit Freigabe haelt an und fragt")
    offen = approval.gate.state()["request"]
    check("zustimmung" in offen["description"], "die Frage nennt, was getan werden soll")
    approval.gate.answer(offen["id"], approval.REFUSED)
    bericht = await lauf
    check(bericht["stopped"] and "abgelehnt" in bericht["stopped"],
          "eine abgelehnte Freigabe beendet den Lauf")

    await seite.set_content(FORMULAR)
    registrierung_setzen([
        zustand("von_hand", "Von Hand", 10, [bedingung("sichtbar", "name")],
                [{"type": "text_eintragen", "role": "name", "mode": "manuell",
                  "source": {"art": "konfiguration", "name": "Vorname"}}]),
    ])
    lauf = asyncio.create_task(runner.run_once(instanz, "search"))
    for _ in range(50):
        if approval.gate.open:
            break
        await asyncio.sleep(0.05)
    check(approval.gate.open, "eine Aktion von Hand haelt ebenfalls an")
    approval.gate.answer(approval.gate.state()["request"]["id"], approval.DONE)
    bericht = await lauf
    check(bericht["stopped"] == "", "nach der Bestaetigung laeuft es weiter")
    check(await seite.input_value("[data-testid=name]") == "",
          "im Modus von Hand traegt die Anwendung nichts ein")

    print("Geheimnisse")
    echt = runner.secrets.get
    runner.secrets.get = lambda name: "streng-geheim-4711"
    try:
        await seite.set_content(FORMULAR)
        registrierung_setzen([
            zustand("geheim", "Geheimnis", 10, [bedingung("sichtbar", "name")],
                    [{"type": "text_eintragen", "role": "name",
                      "source": {"art": "geheimnis", "name": "account-password"}}]),
        ])
        bericht = await runner.run_once(instanz, "search")
        check(await seite.input_value("[data-testid=name]") == "streng-geheim-4711",
              "das Geheimnis landet im Feld")
        strom = json.dumps(list(bus.replay()), ensure_ascii=False)
        check("streng-geheim-4711" not in strom, "das Geheimnis steht in keinem Ereignis")
        check("streng-geheim-4711" not in json.dumps(bericht, ensure_ascii=False),
              "das Geheimnis steht in keinem Bericht")
    finally:
        runner.secrets.get = echt

    print("Variablenraum")
    space.open("kennung-1")
    check(space.report()["entries"] == [], "ein neuer Vorgang beginnt mit leerem Raum")
    space.set("adresse", "abc")
    space.open("kennung-2")
    check(not space.has("adresse"), "der naechste Vorgang sieht nichts vom vorigen")


async def main():
    from playwright.async_api import async_playwright

    modell_pruefen()
    ablage_pruefen()
    vorlagen_pruefen()

    os.environ["LOCALAPPDATA"] = _echtes_lokal
    programm = browser_install.executable()
    os.environ["LOCALAPPDATA"] = _temp + "-lokal"
    if programm is None:
        print("  Der Browser ist nicht geladen, Pruefung nicht moeglich")
        raise SystemExit(1)

    playwright = await async_playwright().start()
    instanz = instances.Instance(instances.SEARCH)
    await instanz.start(playwright, programm, 1280, 720, instances._running_pids(programm))
    try:
        await browser_pruefen(instanz)
    finally:
        await instanz.close()
        await playwright.stop()

    print()
    if fehler:
        print(f"{len(fehler)} Pruefung(en) fehlgeschlagen:")
        for eintrag in fehler:
            print("  - " + eintrag)
        raise SystemExit(1)
    print("Alle Pruefungen bestanden")


if __name__ == "__main__":
    asyncio.run(main())
