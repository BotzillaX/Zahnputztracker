"""Check of the browser operation, without the user interface.

Needs the downloaded browser binary and opens two real windows, so it is
not part of the quick test run. Start it by hand:

    .venv\Scripts\python.exe -m service.tests.test_browser
"""
import asyncio
import ctypes
import time

from ..runtime import instances

fehler = []
def check(bed, label):
    print(("  ok   " if bed else "  FEHL ") + label, flush=True)
    if not bed: fehler.append(label)

user32 = ctypes.windll.user32
def fenster(pid):
    treffer = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.GetWindowTextLengthW(hwnd) > 0:
            treffer.append((hwnd, bool(user32.IsWindowVisible(hwnd))))
        return True
    user32.EnumWindows(cb, 0)
    return treffer

async def main():
    fleet = instances.fleet
    t0 = time.time()
    await fleet.start({"search": {"width": 1280, "height": 720},
                       "session": {"width": 1280, "height": 720}})
    print(f"  Startdauer {time.time()-t0:.1f}s", flush=True)

    zustand = fleet.snapshot()
    check(zustand["running"], "beide Instanzen laufen")
    for inst in zustand["instances"]:
        check(inst["running"], f"{inst['label']} laeuft")
        check(inst["pid"] is not None, f"{inst['label']}: Prozess gemeldet")
        check(inst["tabs"] == 1, f"{inst['label']}: genau ein Tab")
        gefunden = [w for pid in inst["pids"] for w in fenster(pid)]
        check(len(gefunden) >= 1, f"{inst['label']}: Fenster gefunden ({len(gefunden)})")

    such = fleet.instance(instances.SEARCH)
    sitzung = fleet.instance(instances.SESSION)

    # Ein-Tab-Regel: eine zweite Seite muss verschwinden.
    await such.context.new_page()
    await asyncio.sleep(1.5)
    check(len(such.context.pages) == 1, "zweite Seite wurde geschlossen")
    check(such.extra_pages_closed == 1, "Schliessung wurde protokolliert")

    # Ein-Tab-Regel bei einem Verweis mit target=_blank.
    await such.page.goto("about:blank")
    await such.page.set_content('<a id="x" href="https://example.com" target="_blank">x</a>')
    await such.page.click("#x")
    await asyncio.sleep(2.0)
    check(len(such.context.pages) == 1, "Verweis mit neuem Tab erzeugt keinen zweiten Tab")

    # Navigation ueber die Adresszeile.
    ziel = await such.navigate("https://example.com", 30)
    check("example.com" in ziel, f"Navigation erreicht das Ziel ({ziel})")
    check(len(such.context.pages) == 1, "nach der Navigation weiterhin ein Tab")

    # Getrennte Profile und getrennte Fingerabdruecke.
    a = await such.page.evaluate("navigator.userAgent")
    await sitzung.navigate("https://example.com", 30)
    b = await sitzung.page.evaluate("navigator.userAgent")
    print(f"  Such-Browser:     {a}", flush=True)
    print(f"  Sitzungs-Browser: {b}", flush=True)
    check(instances._profile_dir("search") != instances._profile_dir("session"),
          "getrennte Profilverzeichnisse")
    check(instances._options_file("session").exists(),
          "Fingerabdruck des Sitzungs-Browsers wurde festgehalten")

    # Sichtbarkeit ist reiner Wunschzustand im Dienst.
    fleet.set_visible("search", True)
    check(any(w["visible"] for w in fleet.wanted_windows()), "Wunsch sichtbar wird gemeldet")
    fleet.set_visible("search", False)
    check(not any(w["visible"] for w in fleet.wanted_windows()), "Wunsch unsichtbar wird gemeldet")

    # Pause haelt an, ohne die Browser zu schliessen.
    fleet.set_paused(True)
    check(fleet.paused and fleet.running, "angehalten, beide Browser bleiben offen")
    check(such.context.pages[0].url == ziel, "Seite blieb beim Anhalten stehen")
    fleet.set_paused(False)

    pids = [p for i in fleet.snapshot()["instances"] for p in i["pids"]]
    await fleet.stop()
    await asyncio.sleep(2)
    check(not fleet.running, "beide Instanzen geschlossen")
    check(all(not fenster(p) for p in pids), "keine Fenster uebrig")

asyncio.run(main())
print()
if fehler:
    print(f"{len(fehler)} Pruefung(en) fehlgeschlagen")
    raise SystemExit(1)
print("alle Pruefungen bestanden")
