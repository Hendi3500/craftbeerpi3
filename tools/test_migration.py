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


def _kopiere(ziel):
    """Projekt in ein frisches Verzeichnis kopieren."""
    for eintrag in ("modules", "config", "update", "logs"):
        quelle = os.path.join(ROOT, eintrag)
        if os.path.isdir(quelle):
            shutil.copytree(quelle, os.path.join(ziel, eintrag),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    os.makedirs(os.path.join(ziel, "upload"), exist_ok=True)
    shutil.copy(os.path.join(ROOT, "run.py"), os.path.join(ziel, "run.py"))
    shutil.copy(os.path.join(ROOT, "requirements.txt"),
                os.path.join(ziel, "requirements.txt"))


def _starte(verzeichnis):
    """Die App einmal starten (Import genuegt - run_init laeuft beim Import)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = verzeichnis
    proc = subprocess.run(
        [sys.executable, "-c", "import modules"],
        cwd=verzeichnis, env=env, capture_output=True, timeout=120)
    return proc


def _db(verzeichnis):
    import sqlite3
    return sqlite3.connect(os.path.join(verzeichnis, "craftbeerpi.db"))


def run():
    tmp = tempfile.mkdtemp(prefix="cbpi-migration-")
    print("Testverzeichnis: %s" % tmp)
    try:
        _kopiere(tmp)

        print("\n--- Erste Installation (leere Datenbank) -------------------")
        proc = _starte(tmp)
        check("Start laeuft durch", proc.returncode == 0,
              proc.stderr.decode(errors="replace")[-300:])
        ausgabe = proc.stdout.decode(errors="replace")
        check("keine Migrationsfehler auf stdout", "EXCEPT" not in ausgabe,
              ausgabe[-200:])

        # Die erwarteten Versionen aus dem update/-Verzeichnis ableiten.
        # Fest verdrahtete Zahlen brechen bei jeder neuen Migration.
        erwartet = sorted(int(f.split("_")[0]) for f in os.listdir(
            os.path.join(tmp, "update")) if f.endswith(".sql"))

        db = _db(tmp)
        versionen = [r[0] for r in db.execute(
            "SELECT version FROM schema_info ORDER BY id")]
        check("schema_info hat die erwartete Version", versionen == erwartet,
              "%s, erwartet %s" % (versionen, erwartet))

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
        paare = db.execute(
            "SELECT version, filename FROM schema_info ORDER BY id").fetchall()
        check("Migrationen in Versionsreihenfolge ausgefuehrt",
              [p[0] for p in paare] == sorted(p[0] for p in paare),
              str(paare))
        db.close()

        print("\n--- Zweiter Start (Datenbank ist aktuell) -------------------")
        proc = _starte(tmp)
        ausgabe = proc.stdout.decode(errors="replace")
        check("keine Migrationsfehler auf stdout", "EXCEPT" not in ausgabe,
              ausgabe[-200:])
        db = _db(tmp)
        anzahl = db.execute("SELECT COUNT(*) FROM schema_info").fetchone()[0]
        check("keine Migration doppelt ausgefuehrt", anzahl == len(erwartet),
              "%d Eintraege, erwartet %d" % (anzahl, len(erwartet)))
        db.close()

        print("\n--- Neue Migration (Upgrade) ------------------------------")
        # Die naechste freie Version nehmen. Eine Datei mit einer bereits
        # vergebenen Version wird uebersprungen - die Versionsnummer ist
        # der Schluessel, nicht nur ein Ordnungsmerkmal.
        neue_version = max(erwartet) + 1
        with open(os.path.join(tmp, "update",
                               "%d_test_upgrade.sql" % neue_version), "w") as f:
            f.write("INSERT OR IGNORE INTO config VALUES "
                    "('test_migration_%d', 'ja', 'text', 'Test', NULL );\n" % neue_version)
        proc = _starte(tmp)
        db = _db(tmp)
        neu = db.execute("SELECT value FROM config WHERE name='test_migration_%d'"
                         % neue_version).fetchone()
        check("neue Migration wurde ausgefuehrt", neu is not None, repr(neu))
        anzahl = db.execute("SELECT COUNT(*) FROM schema_info").fetchone()[0]
        check("nur die neue Migration kam dazu", anzahl == len(erwartet) + 1,
              "%d Eintraege, erwartet %d" % (anzahl, len(erwartet) + 1))
        db.close()

        print("\n--- Fehler landen im Log -----------------------------------")
        # Eine kaputte Migration schreiben - wieder mit einer freien Version,
        # sonst wird sie uebersprungen, statt zu scheitern.
        kaputt_version = max(erwartet) + 2
        kaputt_name = "%d_kaputt.sql" % kaputt_version
        with open(os.path.join(tmp, "update", kaputt_name), "w") as f:
            f.write("THIS IS NOT VALID SQL;\n")
        proc = _starte(tmp)
        log = open(os.path.join(tmp, "logs", "app.log")).read()
        check("Migrationsfehler steht im Log", ("Migration %s" % kaputt_name) in log,
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
