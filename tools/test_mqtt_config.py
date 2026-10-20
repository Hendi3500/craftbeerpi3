#!/usr/bin/env python3
"""
Pruefung der MQTT-Konfigurationsparameter (Umbenennung und TLS-Auswahlfeld).

Geprueft wird:

1. Upgrade: eine Installation mit den alten GROSSBUCHSTABEN-Parametern
   (MQTT_SERVER, MQTT_TLS, ...) bekommt die kleingeschriebenen Parameter
   mit denselben Werten. Der Broker darf nach dem Update nicht
   "vergessen" sein.
2. Die SQL-Migration wird umgangen (schema_info steht schon auf der
   neuen Version) - dann uebernimmt das Plugin die Werte selbst und
   entfernt die alten Eintraege.
3. Frische Installation: die Parameter werden mit den Vorgabewerten
   angelegt, TLS ist ein Auswahlfeld mit YES/NO und kein Textfeld.
4. Ein alter TLS-Wert ("true"/"false") wird auf YES/NO umgestellt - ein
   Auswahlfeld, dessen Wert nicht in den Optionen steht, zeigt nichts an.

Der Test arbeitet in eigenen Verzeichnissen und fasst die echte
Datenbank nicht an.

Abruf:  python3 tools/test_mqtt_config.py
         Exit 0 = alle Pruefungen bestanden.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PASS = []
FAIL = []

NEW_NAMES = ["mqtt_server", "mqtt_port", "mqtt_username", "mqtt_password",
              "mqtt_tls", "mqtt_ca_cert", "mqtt_cert", "mqtt_key"]

OLD_NAMES = [n.upper() for n in NEW_NAMES]


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
    """Die App einmal starten (der Import reicht - run_init laeuft dabei)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = directory
    return subprocess.run([sys.executable, "-c", "import modules"],
                          cwd=directory, env=env, capture_output=True,
                          timeout=180)


def _db(directory):
    return sqlite3.connect(os.path.join(directory, "craftbeerpi.db"))


def _rows(db):
    return {r[0]: r for r in db.execute(
        "SELECT name, value, type, description, options FROM config")}


def _make_old(db, tls_value="false"):
    """
    Die Datenbank in den Zustand einer alten Installation zuruecksetzen:
    GROSSBUCHSTABEN, TLS als Textfeld.
    """
    for new, old in zip(NEW_NAMES, OLD_NAMES):
        db.execute("UPDATE config SET name=? WHERE name=?", (old, new))
    db.execute("UPDATE config SET value=?, type='text', options=NULL "
               "WHERE name='MQTT_TLS'", (tls_value,))
    db.execute("UPDATE config SET value='192.168.0.140' WHERE name='MQTT_SERVER'")
    db.commit()


def _check_new(db, label, server="192.168.0.140", tls="NO"):
    rows = _rows(db)
    check("%s: mqtt_server hat den alten Wert" % label,
          rows.get("mqtt_server", (None, None))[1] == server,
          repr(rows.get("mqtt_server")))
    check("%s: mqtt_tls ist '%s'" % (label, tls),
          rows.get("mqtt_tls", (None, None))[1] == tls,
          repr(rows.get("mqtt_tls")))
    check("%s: mqtt_tls ist ein Auswahlfeld" % label,
          rows.get("mqtt_tls", (None, None, None))[2] == "select",
          repr(rows.get("mqtt_tls")))
    options = rows.get("mqtt_tls", (None, None, None, None, None))[4]
    try:
        options = json.loads(options) if options else None
    except (TypeError, ValueError):
        pass
    check("%s: mqtt_tls hat die Optionen YES/NO" % label,
          options == ["YES", "NO"], repr(options))
    check("%s: mqtt_port ist ein Zahlenfeld" % label,
          rows.get("mqtt_port", (None, None, None))[2] == "number",
          repr(rows.get("mqtt_port")))
    check("%s: die alten GROSSBUCHSTABEN sind weg" % label,
          not [n for n in OLD_NAMES if n in rows],
          repr([n for n in OLD_NAMES if n in rows]))
    check("%s: alle kleingeschriebenen Parameter sind da" % label,
          all(n in rows for n in NEW_NAMES),
          repr([n for n in NEW_NAMES if n not in rows]))


def _case_1():
    print("\n--- Upgrade mit Migration ------------------------------------")
    tmp = tempfile.mkdtemp(prefix="cbpi-mqtt-migration-")
    try:
        _copy(tmp)
        _start(tmp)                      # frische Installation
        db = _db(tmp)
        _make_old(db)                    # Zustand einer alten Installation
        # Die Migration zurueckdrehen: schema_info steht wieder auf der
        # Version vor der MQTT-Migration. Der Kern merkt sich die
        # hoechste vergebene Version - es muessen also alle Eintraege ab
        # Version 5 weg, sonst wird die Migration als "bereits gelaufen"
        # uebersprungen.
        db.execute("DELETE FROM schema_info WHERE version>=5")
        db.commit()
        db.close()

        proc = _start(tmp)
        check("Start laeuft durch", proc.returncode == 0,
              proc.stderr.decode(errors="replace")[-400:])

        db = _db(tmp)
        _check_new(db, "Migration")
        versions = [r[0] for r in db.execute("SELECT version FROM schema_info")]
        check("die MQTT-Migration ist verzeichnet", 5 in versions,
              repr(versions))
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _case_2():
    print("\n--- Upgrade ohne Migration (Plugin uebernimmt selbst) --------")
    tmp = tempfile.mkdtemp(prefix="cbpi-mqtt-plugin-")
    try:
        _copy(tmp)
        _start(tmp)
        db = _db(tmp)
        _make_old(db)
        # schema_info bleibt auf der neuen Version - die SQL-Migration
        # laeuft nicht. Das Plugin muss die Werte selbst mitnehmen.
        db.commit()
        db.close()

        proc = _start(tmp)
        check("Start laeuft durch", proc.returncode == 0,
              proc.stderr.decode(errors="replace")[-400:])

        db = _db(tmp)
        _check_new(db, "Plugin")
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _case_3():
    print("\n--- Frische Installation -------------------------------------")
    tmp = tempfile.mkdtemp(prefix="cbpi-mqtt-frisch-")
    try:
        _copy(tmp)
        proc = _start(tmp)
        check("Start laeuft durch", proc.returncode == 0,
              proc.stderr.decode(errors="replace")[-400:])

        db = _db(tmp)
        rows = _rows(db)
        check("mqtt_server ist localhost",
              rows.get("mqtt_server", (None, None))[1] == "localhost",
              repr(rows.get("mqtt_server")))
        check("mqtt_port ist 1883",
              str(rows.get("mqtt_port", (None, None))[1]) == "1883",
              repr(rows.get("mqtt_port")))
        check("mqtt_tls ist NO",
              rows.get("mqtt_tls", (None, None))[1] == "NO",
              repr(rows.get("mqtt_tls")))
        check("mqtt_tls ist ein Auswahlfeld",
              rows.get("mqtt_tls", (None, None, None))[2] == "select",
              repr(rows.get("mqtt_tls")))
        options = rows.get("mqtt_tls", (None, None, None, None, None))[4]
        try:
            options = json.loads(options) if options else None
        except (TypeError, ValueError):
            pass
        check("mqtt_tls hat die Optionen YES/NO", options == ["YES", "NO"],
              repr(options))
        check("keine GROSSBUCHSTABEN angelegt",
              not [n for n in OLD_NAMES if n in rows],
              repr([n for n in OLD_NAMES if n in rows]))
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _case_4():
    print("\n--- Alter TLS-Wert 'true' wird zu YES -------------------------")
    tmp = tempfile.mkdtemp(prefix="cbpi-mqtt-tls-")
    try:
        _copy(tmp)
        _start(tmp)
        db = _db(tmp)
        _make_old(db, tls_value="true")
        db.execute("DELETE FROM schema_info WHERE version=5")
        db.commit()
        db.close()

        _start(tmp)
        db = _db(tmp)
        _check_new(db, "TLS", tls="YES")
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run():
    _case_1()
    _case_2()
    _case_3()
    _case_4()
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
