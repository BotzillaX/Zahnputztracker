"""Checks for the rules that must not silently break."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from service.storage import config as config_store  # noqa: E402
from service.storage import database  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("  ok   " if condition else "  FEHL ") + label)
    if not condition:
        FAILURES.append(label)


def test_config() -> None:
    print("Konfiguration")
    defaults = config_store.validate({})
    check(defaults["review_mode"] is True, "Testmodus ist nach der Installation aktiv")
    check(defaults["source"]["idle_behavior"] is False, "Verhaltens-Simulation ist aus")
    check(defaults["sound_on_new"] is True, "Signalton ist an")
    check(
        defaults["browsers"]["search"] == {"width": 1280, "height": 720},
        "Fenstergroesse ist mit 1280x720 vorbelegt",
    )
    check(len(defaults["limits"]) >= 13, "Zeitlimit je Vorgangsname vorhanden")

    for bad, label in (
        ({"source": {"reload_min_s": 20, "reload_max_s": 10}}, "Minimum ueber Maximum wird abgelehnt"),
        ({"storage_cap_mb": 5}, "zu kleine Speicherobergrenze wird abgelehnt"),
        ({"limits": {"submit.send": 99999}}, "unsinniges Zeitlimit wird abgelehnt"),
        ({"answers": [{"label": "", "value": "x"}]}, "Antwort-Paar ohne Bezeichnung wird abgelehnt"),
    ):
        try:
            config_store.validate(bad)
            check(False, label)
        except config_store.ConfigError:
            check(True, label)

    kept = config_store.validate({"eigenes_feld": {"a": 1}})
    check(kept.get("eigenes_feld") == {"a": 1}, "unbekannte Felder bleiben erhalten")


def test_database() -> None:
    print("Datenbank")
    with tempfile.TemporaryDirectory() as folder:
        connection = database.connect(Path(folder) / "test.sqlite")

        database.see(connection, "A", url="u/a", title="Titel A")
        database.see(connection, "B")
        database.set_status(connection, "B", database.STATUS_CONTACTED)
        database.set_status(connection, "C", database.STATUS_PENDING_REVIEW)
        database.set_status(connection, "D", database.STATUS_SKIPPED, reason="Ausschluss")

        offen = database.unknown_keys(connection, ["A", "B", "C", "D", "E"])
        check(offen == ["A", "C", "E"], f"nur unerledigte Kennungen bleiben uebrig ({offen})")
        check(
            database.counts(connection)[database.STATUS_CONTACTED] == 1,
            "Statuszaehlung stimmt",
        )

        # Sending twice must be impossible after a crash.
        database.set_status(connection, "F", database.STATUS_OPEN)
        database.mark_dispatch_started(connection, "F", evidence="bild.png")
        check(len(database.open_dispatches(connection)) == 1, "offener Versand wird erkannt")

        stranded = database.resolve_open_dispatches(connection)
        row = database.items(connection, status=database.STATUS_UNCLEAR)
        check(stranded == ["F"], "abgebrochener Versand landet in der Klaerliste")
        check(len(row) == 1 and row[0]["key"] == "F", "Status ist unklar, nicht kontaktiert")
        check(
            database.unknown_keys(connection, ["F"]) == [],
            "unklare Kennung wird nicht automatisch erneut versendet",
        )

        database.mark_dispatch_started(connection, "B")
        database.mark_dispatch_confirmed(connection, "B")
        check(
            all(entry["key"] != "B" for entry in database.open_dispatches(connection)),
            "bestaetigter Versand gilt als abgeschlossen",
        )
        connection.close()


if __name__ == "__main__":
    test_config()
    test_database()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} Pruefung(en) fehlgeschlagen")
        raise SystemExit(1)
    print("alle Pruefungen bestanden")
