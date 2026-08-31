"""Check of the sign in, the contact run and the protection against
sending twice.

Everything runs against exercise pages that are written here in the test.
No live site is involved, the provider of the message text is replaced by
a fixed string, and no credential of the machine is touched.

    .venv\\Scripts\\python.exe -m service.tests.test_flow
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path

_temp = tempfile.mkdtemp(prefix="zt-flow-")
os.environ["APPDATA"] = _temp
_pages = Path(_temp) / "seiten"
_pages.mkdir(parents=True, exist_ok=True)

from ..api.events import bus  # noqa: E402
from ..engine import approval  # noqa: E402
from ..flow import contact as contact_flow  # noqa: E402
from ..flow import contract, login as login_flow  # noqa: E402
from ..registry import store  # noqa: E402
from ..runtime import browser_install, instances  # noqa: E402
from ..storage import config as config_store  # noqa: E402
from ..storage import database  # noqa: E402
from ..telemetry import incidents  # noqa: E402
from ..text import prompt as prompt_builder  # noqa: E402

fehler = []
TEXT = "Guten Tag, hier ist mein Anliegen."


async def warte_auf_freigabe(zuletzt=0, sekunden=30):
    """Auf eine Anfrage warten, die es vorher noch nicht gab."""
    for _ in range(int(sekunden * 10)):
        offen = approval.gate.state()["request"]
        if offen and offen["id"] > zuletzt:
            return offen
        await asyncio.sleep(0.1)
    return None


def check(bedingung, label):
    print(("  ok   " if bedingung else "  FEHL ") + label, flush=True)
    if not bedingung:
        fehler.append(label)


def rolle(name, testid, menge="einzel", antwort=""):
    return {
        "id": name,
        "label": name,
        "scope": "session",
        "menge": menge,
        "notes": "",
        "key_attribute": "",
        "answer": antwort,
        "options": [],
        "candidates": [{"kind": "attr", "attr": "data-testid", "value": testid}],
    }


def seite(name, koerper):
    ziel = _pages / f"{name}.html"
    ziel.write_text(f"<html><body>{koerper}</body></html>", encoding="utf-8")
    return ziel.as_uri()


def eintrag(key):
    verbindung = database.connect()
    try:
        zeilen = [z for z in database.items(verbindung) if z["key"] == key]
        return zeilen[0] if zeilen else None
    finally:
        verbindung.close()


def offene_vermerke():
    verbindung = database.connect()
    try:
        return database.open_dispatches(verbindung)
    finally:
        verbindung.close()


# --------------------------------------------------------------- Uebungsseiten

ANMELDUNG = """
  <input data-testid="kennung" />
  <input data-testid="geheim" type="password" />
  <button data-testid="abschicken" onclick="document.getElementById('konto').style.display='block'">
    Anmelden
  </button>
  <div id="konto" data-testid="konto" style="display:none">Angemeldet</div>
"""

ANMELDUNG_CODE = """
  <input data-testid="kennung" />
  <input data-testid="geheim" type="password" />
  <button data-testid="abschicken" onclick="weiter()">Anmelden</button>
  <div id="codeteil" style="display:none">
    <span data-testid="codemerkmal">Code eingeben</span>
    <input data-testid="codefeld" />
  </div>
  <div id="konto" data-testid="konto" style="display:none">Angemeldet</div>
  <script>
    function weiter() {
      var teil = document.getElementById('codeteil');
      if (teil.style.display === 'none') { teil.style.display = 'block'; return; }
      document.getElementById('konto').style.display = 'block';
    }
  </script>
"""

FORMULAR = """
  <div id="formular" style="display:none">
    <textarea data-testid="nachricht"></textarea>
    <select data-testid="feld-a">
      <option value="">bitte waehlen</option>
      <option value="NEIN">Nein</option>
    </select>
    <input data-testid="feld-b" />
    <button data-testid="absenden" onclick="%s">Senden</button>
  </div>
"""

BESTAETIGT = "document.getElementById('danke').style.display='block'"
NICHTS = "void 0"


def eintragsseite(name, *, ausschluss=False, erledigt=False, formular=True, absenden=BESTAETIGT):
    teile = ['<div data-testid="fertig">Seite fertig</div>', "<p>Sichtbarer Text der Uebungsseite.</p>"]
    if ausschluss:
        teile.append('<div data-testid="gesperrt">Kein Zugriff</div>')
    if erledigt:
        teile.append('<div data-testid="erledigt">Bereits angefragt</div>')
    oeffnen = "document.getElementById('formular').style.display='block'"
    teile.append(f'<button data-testid="oeffnen" onclick="{oeffnen}">Kontakt</button>')
    if formular:
        teile.append(FORMULAR % absenden)
    else:
        teile.append('<div id="formular" style="display:none"><p>Leer</p></div>')
    teile.append('<div id="danke" data-testid="danke" style="display:none">Danke</div>')
    return seite(name, "\n".join(teile))


def registrierung(rollen):
    store.save("session", {"roles": rollen, "states": []})


ALLE_ROLLEN = [
    rolle(contract.SIGNED_IN, "konto"),
    rolle(contract.IDENTITY_FIELD, "kennung"),
    rolle(contract.SECRET_FIELD, "geheim"),
    rolle(contract.SIGN_IN_SUBMIT, "abschicken"),
    rolle(contract.SECOND_FACTOR_MARKER, "codemerkmal"),
    rolle(contract.SECOND_FACTOR_FIELD, "codefeld"),
    rolle(contract.READY_MARKER, "fertig"),
    rolle(contract.ALREADY_MARKER, "erledigt"),
    rolle(contract.OPEN_FORM, "oeffnen"),
    rolle(contract.MESSAGE_FIELD, "nachricht"),
    rolle(contract.SUBMIT_ACTION, "absenden"),
    rolle(contract.CONFIRMATION_MARKER, "danke"),
    rolle("exclusion_marker_a", "gesperrt"),
    rolle("form_field_a", "feld-a", antwort="Haustiere"),
    rolle("form_field_b", "feld-b"),
]


def einstellungen_setzen():
    daten = config_store.load()
    daten["account"]["email"] = "pruefung@example.invalid"
    daten["review_mode"] = False
    daten["confirm_wait_s"] = 0.5
    daten["limits"]["submit.confirm"] = 5
    daten["limits"]["item.open"] = 20
    daten["limits"]["form.open"] = 5
    daten["limits"]["auth.login"] = 15
    daten["answers"] = [{"label": "Haustiere", "value": "NEIN", "display": "Nein"}]
    daten["profile_values"] = [{"label": "Beruf", "value": "Selbstständig"}]
    daten["composer"]["prompt"] = "Schreibe an: {{seitentext}} für {{wert:Beruf}}"
    config_store.save(daten)


# ------------------------------------------------------------------- Prompt


def prompt_pruefen():
    print("Prompt")
    einstellungen = config_store.load()
    gefuellt, benutzt = prompt_builder.build(
        "A {{seitentext}} B {{wert:Beruf}} C {{adresse}}", einstellungen, "TEXT", url="ADR"
    )
    check(gefuellt == "A TEXT B Selbstständig C ADR", "alle Platzhalter werden ersetzt")
    check(set(benutzt) == {"seitentext", "wert:Beruf", "adresse"}, "die benutzten Namen werden gemeldet")
    try:
        prompt_builder.build("{{gibtsnicht}}", einstellungen, "T")
        check(False, "ein unbekannter Platzhalter wird abgelehnt")
    except prompt_builder.PromptError as e:
        check("unbekannt" in str(e), "ein unbekannter Platzhalter wird abgelehnt")
    try:
        prompt_builder.build("{{wert:Fehlt}}", einstellungen, "T")
        check(False, "ein fehlender persoenlicher Wert wird abgelehnt")
    except prompt_builder.PromptError:
        check(True, "ein fehlender persoenlicher Wert wird abgelehnt")


def vertrag_pruefen():
    print("Rollenvertrag")
    registrierung([rolle(contract.READY_MARKER, "fertig")])
    stand = contract.readiness(store.load("session"))
    check(contract.MESSAGE_FIELD in stand["missing_contact"],
          "eine fehlende Pflichtrolle wird benannt")
    registrierung(ALLE_ROLLEN)
    stand = contract.readiness(store.load("session"))
    check(stand["missing_contact"] == [] and stand["missing_sign_in"] == [],
          "mit allen Rollen ist der Ablauf vollstaendig")
    check(len(stand["exclusions"]) == 1, "die Ausschluss-Rollen werden gefunden")
    check(len(stand["fields"]) == 2, "die Formularfelder werden gefunden")
    check([f for f in stand["fields"] if f["answer"] == "Haustiere"],
          "die Zuordnung eines Antwort-Paars steht an der Rolle")


# ------------------------------------------------------------------ Ablaeufe


async def anmeldung_pruefen(instanz):
    print("Anmeldung")
    registrierung(ALLE_ROLLEN)
    await instanz.navigate(seite("anmeldung", ANMELDUNG), 20)
    stand = await login_flow.state(instanz)
    check(stand["known"] and not stand["signed_in"], "der abgemeldete Zustand wird erkannt")

    ergebnis = await login_flow.sign_in(instanz)
    check(ergebnis["signed_in"], "die Anmeldung gelingt")
    check(await instanz.page.input_value("[data-testid=kennung]") == "pruefung@example.invalid",
          "die Kennung kommt aus den Einstellungen")
    check(await instanz.page.input_value("[data-testid=geheim]") == "geheim-4711",
          "das Geheimnis kommt aus dem Anmeldeinformationsspeicher")
    strom = json.dumps(list(bus.replay()), ensure_ascii=False)
    check("geheim-4711" not in strom, "das Geheimnis steht in keinem Ereignis")

    ergebnis = await login_flow.ensure(instanz)
    check(ergebnis["already"], "eine bestehende Anmeldung wird nicht wiederholt")

    print("Code-Abfrage")
    await instanz.navigate(seite("anmeldung-code", ANMELDUNG_CODE), 20)
    lauf = asyncio.create_task(login_flow.sign_in(instanz))
    offen = await warte_auf_freigabe()
    check(offen is not None, "bei einer Code-Abfrage wird angehalten und gefragt")
    check(offen.get("wants_text"), "die Anfrage verlangt eine Eingabe")
    approval.gate.answer(offen["id"], approval.ALLOWED, "123456")
    ergebnis = await lauf
    check(ergebnis["signed_in"], "nach dem Code ist die Anmeldung fertig")
    check(await instanz.page.input_value("[data-testid=codefeld]") == "123456",
          "der Code wird eingetragen")


async def vorgang_pruefen(instanz):
    print("Kontaktvorgang")
    registrierung(ALLE_ROLLEN)
    ziel = eintragsseite("eintrag-gut")
    ergebnis = await contact_flow.contact(instanz, "schluessel-1", ziel, "Titel eins")
    check(ergebnis["status"] == database.STATUS_CONTACTED, f"der Vorgang endet als kontaktiert ({ergebnis['reason']})")
    check(ergebnis["text"] == TEXT, "der erzeugte Text wird gesendet")
    zeile = eintrag("schluessel-1")
    check(zeile and zeile["status"] == database.STATUS_CONTACTED, "die Datenbank kennt den Eintrag als kontaktiert")
    check(zeile and zeile["message"] == TEXT, "der gesendete Text ist festgehalten")
    check(not [z for z in offene_vermerke() if z["key"] == "schluessel-1"],
          "der Versandvermerk ist bestaetigt")

    verbindung = database.connect()
    try:
        offen = database.unknown_keys(verbindung, ["schluessel-1", "neu"])
    finally:
        verbindung.close()
    check(offen == ["neu"], "ein kontaktierter Eintrag wird nicht erneut angeboten")

    print("Ausschluss und bereits erledigt")
    ergebnis = await contact_flow.contact(instanz, "schluessel-2", eintragsseite("eintrag-sperre", ausschluss=True))
    check(ergebnis["status"] == database.STATUS_SKIPPED and "Ausschluss" in ergebnis["reason"],
          "ein gesperrter Eintrag wird uebersprungen und begruendet")
    ergebnis = await contact_flow.contact(instanz, "schluessel-3", eintragsseite("eintrag-erledigt", erledigt=True))
    check(ergebnis["status"] == database.STATUS_ALREADY, "ein bereits erledigter Eintrag wird nicht gesendet")

    print("Formular erscheint nicht")
    ergebnis = await contact_flow.contact(instanz, "schluessel-4", eintragsseite("eintrag-leer", formular=False))
    check(ergebnis["status"] == database.STATUS_SKIPPED and "verfügbar" in ergebnis["reason"],
          "ohne Nachrichtenfeld gilt der Eintrag als nicht mehr verfuegbar")
    check(eintrag("schluessel-4")["status"] != database.STATUS_CONTACTED,
          "und wird gerade nicht als kontaktiert vermerkt")

    print("Keine Bestaetigung")
    vorher = len(incidents.listing())
    ergebnis = await contact_flow.contact(instanz, "schluessel-5",
                                          eintragsseite("eintrag-stumm", absenden=NICHTS))
    check(ergebnis["status"] == database.STATUS_UNCLEAR, "ohne Bestaetigung gilt der Versand als unklar")
    check(ergebnis["incident"], "dazu wird ein Vorfall geschrieben")
    check(len(incidents.listing()) == vorher + 1, "der Vorfall steht in der Liste")
    daten = incidents.read(ergebnis["incident"])
    check(daten["url"].startswith("file:"), "der Vorfall haelt die Adresse fest")
    check(len(daten["roles"]["found"]) > 0, "der Vorfall nennt die gefundenen Rollen")
    check((incidents.root() / ergebnis["incident"] / "bericht.md").is_file(),
          "der Vorfall hat eine lesbare Zusammenfassung")
    check((incidents.root() / ergebnis["incident"] / "bild.png").is_file(),
          "der Vorfall hat ein Bild")
    kopie = (incidents.root() / ergebnis["incident"] / "seite.html").read_text(encoding="utf-8")
    check("data-zt-ui" not in kopie, "das Overlay ist nicht Teil der Kopie")

    print("Anbieter antwortet nicht")
    echt = contact_flow.generate

    async def kaputt(prompt, einstellungen):
        raise contact_flow.ComposerError("Der Anbieter ist nicht erreichbar")

    contact_flow.generate = kaputt
    try:
        ergebnis = await contact_flow.contact(instanz, "schluessel-6", eintragsseite("eintrag-llm"))
    finally:
        contact_flow.generate = echt
    check(ergebnis["status"] == database.STATUS_FAILED, "ohne Text wird nichts gesendet")
    check(ergebnis["incident"], "der Fehlschlag wird als Vorfall festgehalten")
    check(not [z for z in offene_vermerke() if z["key"] == "schluessel-6"],
          "es wurde kein Versandvermerk geschrieben")


async def testmodus_pruefen(instanz):
    print("Testmodus")
    daten = config_store.load()
    daten["review_mode"] = True
    config_store.save(daten)
    try:
        ziel = eintragsseite("eintrag-test")

        # Erste Freigabe ablehnen: es wird nichts erzeugt und nichts gesendet.
        lauf = asyncio.create_task(contact_flow.contact(instanz, "schluessel-7", ziel))
        offen = await warte_auf_freigabe()
        check(offen and offen["mode"] == "vorschau", "vor dem Erzeugen wird gefragt")
        check(offen.get("screenshot"), "die Vorschau bringt ein Bild mit")
        check(any(f["answer"] == "Haustiere" for f in offen["fields"]),
              "die Vorschau zeigt die geplanten Formularfelder")
        check(eintrag("schluessel-7")["status"] == database.STATUS_PENDING_REVIEW,
              "solange gilt der Eintrag als wartend")
        approval.gate.answer(offen["id"], approval.REFUSED)
        ergebnis = await lauf
        check(ergebnis["status"] == database.STATUS_OPEN and not ergebnis["text"],
              "nach dem Ablehnen bleibt der Eintrag offen und ohne Text")

        # Zweite Freigabe ablehnen: erzeugt, aber nicht gesendet.
        lauf = asyncio.create_task(contact_flow.contact(instanz, "schluessel-8", ziel))
        moden = []
        zuletzt = 0
        for _ in range(2):
            offen = await warte_auf_freigabe(zuletzt)
            if offen is None:
                break
            zuletzt = offen["id"]
            moden.append(offen["mode"])
            if offen["mode"] == "vorschau":
                approval.gate.answer(offen["id"], approval.ALLOWED)
            else:
                check(offen.get("text") == TEXT, "die zweite Freigabe zeigt den fertigen Text")
                approval.gate.answer(offen["id"], approval.REFUSED)
        ergebnis = await lauf
        check(moden == ["vorschau", "versand"], "es wird zweimal gefragt, in dieser Reihenfolge")
        check(ergebnis["status"] == database.STATUS_OPEN, "ein abgelehnter Versand bleibt offen")
        check(not [z for z in offene_vermerke() if z["key"] == "schluessel-8"],
              "ohne Freigabe wird kein Versandvermerk geschrieben")

        # Beide erlauben: der Eintrag geht raus.
        lauf = asyncio.create_task(contact_flow.contact(instanz, "schluessel-9", ziel))
        zuletzt = 0
        for _ in range(2):
            offen = await warte_auf_freigabe(zuletzt)
            if offen is None:
                break
            zuletzt = offen["id"]
            approval.gate.answer(offen["id"], approval.ALLOWED)
        ergebnis = await lauf
        check(ergebnis["status"] == database.STATUS_CONTACTED, "nach beiden Freigaben wird gesendet")
    finally:
        daten = config_store.load()
        daten["review_mode"] = False
        config_store.save(daten)


async def unklar_pruefen(instanz):
    print("Status unklar")
    from ..flow import manager as flow_manager

    liste = flow_manager.open_dispatches()
    check(any(z["key"] == "schluessel-5" for z in liste["unclear"]),
          "der unklare Eintrag steht auf der Liste")
    flow_manager.decide("schluessel-5", "erneut")
    check(eintrag("schluessel-5")["status"] == database.STATUS_OPEN,
          "nach der Entscheidung 'erneut' ist der Eintrag wieder offen")
    check(not [z for z in offene_vermerke() if z["key"] == "schluessel-5"],
          "der offene Vermerk ist damit erledigt")
    flow_manager.decide("schluessel-5", "kontaktiert")
    check(eintrag("schluessel-5")["status"] == database.STATUS_CONTACTED,
          "die Entscheidung 'erledigt' setzt den Status")


async def main():
    from playwright.async_api import async_playwright

    einstellungen_setzen()
    prompt_pruefen()
    vertrag_pruefen()

    programm = browser_install.executable()
    if programm is None:
        print("  Der Browser ist nicht geladen, Pruefung nicht moeglich")
        raise SystemExit(1)

    # Kein Zugriff auf echte Anmeldedaten und keinen echten Anbieter.
    echt_secret = login_flow.secrets.get
    login_flow.secrets.get = lambda name: "geheim-4711"

    async def text_erzeugen(prompt, einstellungen):
        return TEXT

    echt_generate = contact_flow.generate
    contact_flow.generate = text_erzeugen

    playwright = await async_playwright().start()
    instanz = instances.Instance(instances.SESSION)
    await instanz.start(playwright, programm, 1280, 720, instances._running_pids(programm))
    try:
        await anmeldung_pruefen(instanz)
        await vorgang_pruefen(instanz)
        await testmodus_pruefen(instanz)
        await unklar_pruefen(instanz)
    finally:
        login_flow.secrets.get = echt_secret
        contact_flow.generate = echt_generate
        await instanz.close()
        await playwright.stop()

    print()
    if fehler:
        print(f"{len(fehler)} Pruefung(en) fehlgeschlagen:")
        for eintragstext in fehler:
            print("  - " + eintragstext)
        raise SystemExit(1)
    print("Alle Pruefungen bestanden")


if __name__ == "__main__":
    asyncio.run(main())
