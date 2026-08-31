"""Check of the registry: storing, versioning, export and import.

Needs no browser. Works in a temporary directory, so nothing of the
real installation is touched.

    .venv\\Scripts\\python.exe -m service.tests.test_registry
"""
import json
import os
import tempfile

_temp = tempfile.mkdtemp(prefix="zt-registry-")
os.environ["APPDATA"] = _temp
os.environ["LOCALAPPDATA"] = _temp

from ..registry import model, store  # noqa: E402

fehler = []


def check(bedingung, label):
    print(("  ok   " if bedingung else "  FEHL ") + label, flush=True)
    if not bedingung:
        fehler.append(label)


def refuses(call, label):
    try:
        call()
    except model.RegistryError:
        check(True, label)
        return
    check(False, label)


print(f"  Arbeitsverzeichnis {_temp}", flush=True)

# Leerer Ausgangszustand (Spec 2.2)
leer = store.load("search")
check(leer["roles"] == [], "Registrierung ist am Anfang leer")
check(leer["version"] == 0, "noch keine Fassung")
refuses(lambda: store.load("unsinn"), "unbekannte Instanz wird abgelehnt")

# Grundkatalog: Rollen ohne jedes Merkmal
store.add_catalogue("search")
katalog = store.load("search")
check(len(katalog["roles"]) == len(model.BASE_CATALOGUE["search"]), "Grundkatalog uebernommen")
check(
    all(not rolle["candidates"] for rolle in katalog["roles"]),
    "keine Rolle des Katalogs bringt ein Merkmal mit",
)
check(katalog["version"] == 1, "erste Fassung geschrieben")
store.add_catalogue("search")
check(
    len(store.load("search")["roles"]) == len(katalog["roles"]),
    "zweites Uebernehmen legt nichts doppelt an",
)

# Eine angelernte Rolle
rolle = {
    "id": "test_ziel",
    "label": "Testziel",
    "menge": "einzel",
    "notes": "von Hand",
    "key_attribute": "data-key",
    "candidates": [
        {"kind": "attr", "attr": "data-key", "value": "abc"},
        {"kind": "aria", "role": "button", "value": "Weiter"},
        {"kind": "text", "value": "Weiter"},
    ],
}
stand = store.put_role("search", rolle)
check(stand["version"] == 3, "jede Aenderung erzeugt eine neue Fassung")
gespeichert = store.role("search", "test_ziel")
check(gespeichert["candidates"][0]["kind"] == "attr", "Merkmale bleiben in ihrer Reihenfolge")
check(gespeichert["key_attribute"] == "data-key", "Kennungstraeger gespeichert")

# Ablehnungen mit Begruendung statt stiller Reparatur
refuses(lambda: store.put_role("search", {**rolle, "id": "Gross"}), "Kennung mit Grossbuchstaben abgelehnt")
refuses(lambda: store.put_role("search", {**rolle, "label": " "}), "Rolle ohne Anzeigename abgelehnt")
refuses(lambda: store.put_role("search", {**rolle, "menge": "viele"}), "unbekannte Menge abgelehnt")
refuses(
    lambda: store.put_role("search", {**rolle, "candidates": [{"kind": "attr", "value": "x"}]}),
    "Attributmerkmal ohne Attributnamen abgelehnt",
)
refuses(
    lambda: store.save("search", {"roles": [rolle, rolle]}),
    "doppelte Kennung abgelehnt",
)

# Versionshistorie und Ruecksetzen
verlauf = store.history("search")
check(len(verlauf) >= 2, f"Fassungen archiviert ({len(verlauf)})")
check(verlauf[0]["version"] > verlauf[-1]["version"], "neueste Fassung zuerst")

vorher = len(store.load("search")["roles"])
store.drop_role("search", "test_ziel")
check(store.role("search", "test_ziel") is None, "Rolle geloescht")
zurueck = store.restore("search", stand["version"])
check(store.role("search", "test_ziel") is not None, "Ruecksetzen holt die Rolle zurueck")
check(len(zurueck["roles"]) == vorher, "Ruecksetzen stellt den ganzen Stand her")
check(
    zurueck["version"] > stand["version"],
    "Ruecksetzen ist selbst eine neue Fassung, nichts geht verloren",
)
refuses(lambda: store.restore("search", 999), "unbekannte Fassung wird abgelehnt")

# Export und Import
ergebnis = store.export("search")
check(os.path.isfile(ergebnis["path"]), "Export geschrieben")
inhalt = json.loads(open(ergebnis["path"], encoding="utf-8").read())
check(inhalt["scope"] == "search", "Export nennt seine Instanz")
refuses(lambda: store.import_document("session", inhalt), "Import in die falsche Instanz abgelehnt")
refuses(lambda: store.import_document("search", "kein json"), "unlesbare Datei abgelehnt")
store.import_document("search", inhalt)
check(store.load("search")["version"] > zurueck["version"], "Import erzeugt eine neue Fassung")

# Getrennte Registrierung je Instanz (Spec 2.10)
check(store.load("session")["roles"] == [], "die zweite Instanz bleibt unberuehrt")
store.add_catalogue("session")
check(
    {r["id"] for r in store.load("session")["roles"]}
    != {r["id"] for r in store.load("search")["roles"]},
    "beide Instanzen haben eigene Rollen",
)

# Freie Kennungen
check(store.free_id("search", "rolle").startswith("rolle"), "freie Kennung wird vorgeschlagen")
store.put_role("search", {**rolle, "id": "rolle"})
check(store.free_id("search", "rolle") == "rolle_2", "belegte Kennung wird hochgezaehlt")
check(
    bool(model.ID_PATTERN.match(store.free_id("search", "Mit Leer!"))),
    "aus einem unsauberen Wunsch wird eine zulaessige Kennung",
)

# Nichts liegt im Projektordner
check(str(store.root()).startswith(_temp), "die Registrierung liegt ausserhalb des Programms")

print()
if fehler:
    print(f"{len(fehler)} Pruefung(en) fehlgeschlagen")
    raise SystemExit(1)
print("alle Pruefungen bestanden")
