#!/usr/bin/env python3
"""
Pruefung der SQL-Migrationen (Position 7, Frischinstallation).

Geprueft wird:

1. Die Migrationsdateien werden nach Versionsnummer sortiert
   ausgefuehrt, nicht in der Reihenfolge des Dateisystems.
2. Eine frische Installation erhaelt alle Konfigurationszeilen aus den
   Migrationen. Vorher lief auf einer frischen Installation zuerst
   3_port_config.sql, weil os.listdir() die Reihenfolge des
   Dateisystems liefert - die Datei wollte in schema_info eintragen,
   obwohl die Tabelle noch nicht existierte. Der Fehler liess die
   Datei zurueckrollen und damit auch den Port-Eintrag.
3. Ein zweiter Start fuehrt nichts erneut aus.
4. Eine neue Migrationsdatei laeuft, die alten werden uebersprungen.
5. Fehler landen im Log und nicht auf stdout.

Der Test arbeitet in einem eigenen Verzeichnis und fasst die echte
Datenbank nicht an.

Abruf:  python3 tools/test_migration.py
         Exit 0 = alle Pruefungen bestanden.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PASS = []
FAIL = []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("  [%s] %s" % ("ok  " if condition else "FAIL", name))
    if detail and not condition:
        print("         -> %s" % detail)


def _copy(target):
    """Projekt in ein frisches Verzeichnis kopieren."""
    for entry in ("modules", "config", "update", "logs"):
        source = os.path.join(ROOT, entry)
        if os.path.isdir(source):
            shutil.copytree(source, os.path.join(target, entry),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    os.makedirs(os.path.join(target, "upload"), exist_ok=True)
    shutil.copy(os.path.join(ROOT, "run.py"), os.path.join(target, "run.py"))
    shutil.copy(os.path.join(ROOT, "requirements.txt"),
                os.path.join(target, "requirements.txt"))


def _start(directory):
    """Die App einmal starten (Import genuegt - run_init laeuft beim Import)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = directory
    proc = subprocess.run(
        [sys.executable, "-c", "import modules"],
        cwd=directory, env=env, capture_output=True, timeout=120)
    return proc


def _db(directory):
    import sqlite3
    return sqlite3.connect(os.path.join(directory, "craftbeerpi.db"))


def run():
    tmp = tempfile.mkdtemp(prefix="cbpi-migration-")
    print("Testverzeichnis: %s" % tmp)
    try:
        _copy(tmp)

        print("\n--- Erste Installation (leere Datenbank) -------------------")
        proc = _start(tmp)
        check("Start laeuft durch", proc.returncode == 0,
              proc.stderr.decode(errors="replace")[-300:])
        output = proc.stdout.decode(errors="replace")
        check("keine Migrationsfehler auf stdout", "EXCEPT" not in output,
              output[-200:])

        # Die erwarteten Versionen aus dem update/-Verzeichnis ableiten.
        # Fest verdrahtete Zahlen brechen bei jeder neuen Migration.
        expected = sorted(int(f.split("_")[0]) for f in os.listdir(
            os.path.join(tmp, "update")) if f.endswith(".sql"))

        db = _db(tmp)
        versions = [r[0] for r in db.execute(
            "SELECT version FROM schema_info ORDER BY id")]
        check("schema_info hat die erwartete Version", versions == expected,
              "%s, erwartet %s" % (versions, expected))

        # Die Zeilen aus den Migrationen muessen da sein
        port = db.execute("SELECT value FROM config WHERE name='port'").fetchone()
        check("port-Config aus 3_port_config.sql vorhanden", port is not None,
              repr(port))
        check("port-Config hat den Wert 5000",
              port is not None and str(port[0]) == "5000", repr(port))

        buzzer = db.execute("SELECT options FROM config WHERE name='buzzer'").fetchone()
        check("Buzzer-Optionen aus 2_more_buzzer.sql vorhanden",
              buzzer is not None and "27" in str(buzzer[0]), repr(buzzer))

        # Reihenfolge in schema_info muss der Versionsnummer entsprechen
        pairs = db.execute(
            "SELECT version, filename FROM schema_info ORDER BY id").fetchall()
        check("Migrationen in Versionsreihenfolge ausgefuehrt",
              [p[0] for p in pairs] == sorted(p[0] for p in pairs),
              str(pairs))
        db.close()

        print("\n--- Zweiter Start (Datenbank ist aktuell) -------------------")
        proc = _start(tmp)
        output = proc.stdout.decode(errors="replace")
        check("keine Migrationsfehler auf stdout", "EXCEPT" not in output,
              output[-200:])
        db = _db(tmp)
        count = db.execute("SELECT COUNT(*) FROM schema_info").fetchone()[0]
        check("keine Migration doppelt ausgefuehrt", count == len(expected),
              "%d Eintraege, erwartet %d" % (count, len(expected)))
        db.close()

        print("\n--- Neue Migration (Upgrade) ------------------------------")
        # Die naechste freie Version nehmen. Eine Datei mit einer bereits
        # vergebenen Version wird uebersprungen - die Versionsnummer ist
        # der Schluessel, nicht nur ein Ordnungsmerkmal.
        new_version = max(expected) + 1
        with open(os.path.join(tmp, "update",
                               "%d_test_upgrade.sql" % new_version), "w") as f:
            f.write("INSERT OR IGNORE INTO config VALUES "
                    "('test_migration_%d', 'ja', 'text', 'Test', NULL );\n" % new_version)
        proc = _start(tmp)
        db = _db(tmp)
        new = db.execute("SELECT value FROM config WHERE name='test_migration_%d'"
                         % new_version).fetchone()
        check("neue Migration wurde ausgefuehrt", new is not None, repr(new))
        count = db.execute("SELECT COUNT(*) FROM schema_info").fetchone()[0]
        check("nur die neue Migration kam dazu", count == len(expected) + 1,
              "%d Eintraege, erwartet %d" % (count, len(expected) + 1))
        db.close()

        print("\n--- Fehler landen im Log -----------------------------------")
        # Eine kaputte Migration schreiben - wieder mit einer freien Version,
        # sonst wird sie uebersprungen, statt zu scheitern.
        broken_version = max(expected) + 2
        broken_name = "%d_kaputt.sql" % broken_version
        with open(os.path.join(tmp, "update", broken_name), "w") as f:
            f.write("THIS IS NOT VALID SQL;\n")
        proc = _start(tmp)
        log = open(os.path.join(tmp, "logs", "app.log")).read()
        check("Migrationsfehler steht im Log", ("Migration %s" % broken_name) in log,
              log[-300:])
        check("Migrationsfehler steht nicht auf stdout",
              "EXCEPT" not in proc.stdout.decode(errors="replace"))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return len(PASS), len(FAIL)


def main():
    p, f = run()
    print("\n%d von %d Pruefungen bestanden" % (p, p + f))
    if f:
        print("Fehlgeschlagen: %d" % f)
        for name in FAIL:
            print("  - %s" % name)
        return 1
    print("ALLE PRUEFUNGEN BESTANDEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
