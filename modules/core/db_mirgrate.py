# -*- coding: utf-8 -*-
"""
SQL-Migrationen aus ./update ausfuehren.

Der Ablauf beim Start:

1. Die vorhandene Version aus der Tabelle ``schema_info`` lesen.
2. Alle Dateien aus ./update, die eine hoehere Version haben, ausfuehren.
3. Die ausgefuehrte Version in ``schema_info`` festhalten.

Zwei Fehler, die hier behoben wurden:

**Die Dateien wurden nicht sortiert.** ``os.listdir()`` liefert die
Eintraege in der Reihenfolge des Dateisystems, nicht numerisch. Auf
einer frischen Installation kam so ``3_port_config.sql`` vor
``1_schema_info.sql`` - die erste Datei wollte in ``schema_info``
eintragen, obwohl die Tabelle noch nicht existierte. Der Fehler liess
die Datei zurueckrollen, und damit auch alles andere aus ihr: der
Config-Eintrag fuer den Port und die erweiterten Buzzer-Optionen
fehlten nach der Installation. ``schema_info`` stand danach auf
Version 1, die Dateien wurden erst beim naechsten Start nachgezogen.
Die Dateien werden jetzt nach ihrer Versionsnummer sortiert.

**Die Fehler waren unsichtbar.** Der Fehler wurde mit ``print()`` auf
stdout geschrieben, nicht ins Log. In ``logs/app.log`` stand nichts.
"""

import os
import sqlite3

from modules import cbpi
from modules.core.db import get_db


def _version_von_dateiname(filename):
    """Versionsnummer aus einem Dateinamen wie '3_port_config.sql'."""
    try:
        return int(filename[:filename.index('_')])
    except (ValueError, IndexError):
        return None


def _dateien_sortieren():
    """
    Die SQL-Dateien aus ./update nach Versionsnummer sortiert.

    Rueckgabe: Liste von (version, dateiname), nur fuer Dateien mit
    sauberer Versionsnummer.
    """
    ergebnis = []
    if not os.path.isdir("./update"):
        return ergebnis
    for filename in os.listdir("./update"):
        if not filename.endswith(".sql"):
            continue
        version = _version_von_dateiname(filename)
        if version is None:
            cbpi.app.logger.warning(
                "Migration %s wird uebersprungen - der Dateiname muss mit "
                "<version>_ beginnen", filename)
            continue
        ergebnis.append((version, filename))
    # Nach Version sortieren, bei gleicher Version nach Name - damit ist
    # die Reihenfolge unabhaengig vom Dateisystem.
    ergebnis.sort(key=lambda paar: (paar[0], paar[1]))
    return ergebnis


def execute_file(current_version, data, conn):
    """
    Eine Migrationsdatei ausfuehren.

    current_version ist None, wenn die Tabelle schema_info noch nicht
    existiert (frische Installation). Python 2 verglich None >= int und
    wertete das als "nicht ueberspringen", Python 3 wirft TypeError -
    ein frischer Start bricht ohne diese Zeile ab.
    """
    if current_version is not None and current_version >= data["version"]:
        cbpi.app.logger.info("SKIP DB FILE: %s" % data["file"])
        return False

    with open('./update/%s' % data["file"], 'r') as f:
        d = f.read()
    sqlCommands = d.split(";")

    # Die Datei wird atomar angewendet: alle ihre Statements und der
    # Eintrag in schema_info gehen gemeinsam in einen Savepoint.
    # Passiert mitten in der Datei ein Fehler, wird der Savepoint
    # zurueckgerollt - die Datei hat dann gar nichts bewirkt.
    #
    # Warum das noetig ist: die Connection hier ist die des
    # Application-Contexts (``get_db()``), nicht eine eigene. Ohne
    # Savepoint blieb nach einem Fehler eine offene Transaktion
    # zurueck, in der die bis dahin ausgefuehrten Statements standen. Die
    # *naechste* Migrationsdatei committete dann alles mit - auch den
    # halb angewendeten Teil der fehlgeschlagenen Datei. Die Datenbank
    # hatte damit einen Zustand, den keine der beiden Dateien
    # beschreibt.
    #
    # In Python 2 lief jede Datei in einer eigenen Connection im
    # ``with``-Block, und der Block rollte bei einem Fehler die ganze
    # Datei zurueck. Diese Eigenschaft ist hier wiederhergestellt - ohne
    # eine zweite Connection, damit die geteilte Transaktion des
    # Application-Contexts intakt bleibt.
    savepoint = "cbpi_migration_%s" % data["version"]
    cur = conn.cursor()
    cur.execute("SAVEPOINT %s" % savepoint)

    try:
        for s in sqlCommands:
            if s.strip():
                cur.execute(s)
        cur.execute("INSERT INTO schema_info (version,filename) values (?,?)",
                    (data["version"], data["file"]))
    except Exception:
        # Die Datei zurueckrollen. Der Savepoint wird aufgeloest, damit
        # kein offener Savepoint liegen bleibt, aber die halbe Datei ist
        # weg.
        try:
            cur.execute("ROLLBACK TO SAVEPOINT %s" % savepoint)
        except sqlite3.Error:
            # Der Rollback ist selbst fehlgeschlagen - dann bleibt nur
            # die ganze Transaktion zurueckzuwerfen.
            conn.rollback()
        try:
            cur.execute("RELEASE SAVEPOINT %s" % savepoint)
        except sqlite3.Error:
            pass
        # Die Ausnahme wird nach oben durchgereicht und dort protokolliert.
        raise

    cur.execute("RELEASE SAVEPOINT %s" % savepoint)
    conn.commit()
    cbpi.app.logger.info("APPLIED DB FILE: %s" % data["file"])
    return True


@cbpi.initalizer(order=-9999)
def init(app=None):

    with cbpi.app.app_context():
        conn = get_db()
        cur = conn.cursor()
        current_version = None
        try:
            cur.execute("SELECT max(version) as m FROM schema_info")
            m = cur.fetchone()
            current_version = m["m"]
        except sqlite3.OperationalError:
            # schema_info existiert noch nicht - frische Installation.
            current_version = None
        except Exception as e:
            cbpi.app.logger.error("Schema-Version nicht lesbar: %s" % e)
            current_version = None

        for version, filename in _dateien_sortieren():
            d = {"version": version, "file": filename}
            try:
                # current_version darf nur bei einer tatsaechlich
                # ausgefuehrten Datei fortschreiten. Sonst setzt der
                # Sprung auf die uebersprungene Datei den Zaehler zurueck
                # und alle folgenden Dateien werden erneut ausgefuehrt.
                if execute_file(current_version, d, conn):
                    current_version = version
            except sqlite3.OperationalError as err:
                # Im Log statt auf stdout - ein Migrationsfehler darf nicht
                # stillschweigend bleiben.
                cbpi.app.logger.error("Migration %s fehlgeschlagen: %s"
                                       % (filename, err))
            except Exception as e:
                cbpi.app.logger.error("Migration %s fehlgeschlagen: %s: %s"
                                       % (filename, type(e).__name__, e))
