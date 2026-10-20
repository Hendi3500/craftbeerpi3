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

NEUE_NAMEN = ["mqtt_server", "mqtt_port", "mqtt_username", "mqtt_password",
              "mqtt_tls", "mqtt_ca_cert", "mqtt_cert", "mqtt_key"]

ALTE_NAMEN = [n.upper() for n in NEUE_NAMEN]


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
    """Die App einmal starten (der Import reicht - run_init laeuft dabei)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = verzeichnis
    return subprocess.run([sys.executable, "-c", "import modules"],
                          cwd=verzeichnis, env=env, capture_output=True,
                          timeout=180)


def _db(verzeichnis):
    return sqlite3.connect(os.path.join(verzeichnis, "craftbeerpi.db"))


def _zeilen(db):
    return {r[0]: r for r in db.execute(
        "SELECT name, value, type, description, options FROM config")}


def _mache_alt(db, tls_wert="false"):
    """
    Die Datenbank in den Zustand einer alten Installation zuruecksetzen:
    GROSSBUCHSTABEN, TLS als Textfeld.
    """
    for neu, alt in zip(NEUE_NAMEN, ALTE_NAMEN):
        db.execute("UPDATE config SET name=? WHERE name=?", (alt, neu))
    db.execute("UPDATE config SET value=?, type='text', options=NULL "
               "WHERE name='MQTT_TLS'", (tls_wert,))
    db.execute("UPDATE config SET value='192.168.0.140' WHERE name='MQTT_SERVER'")
    db.commit()


def _pruefe_neu(db, label, server="192.168.0.140", tls="NO"):
    zeilen = _zeilen(db)
    check("%s: mqtt_server hat den alten Wert" % label,
          zeilen.get("mqtt_server", (None, None))[1] == server,
          repr(zeilen.get("mqtt_server")))
    check("%s: mqtt_tls ist '%s'" % (label, tls),
          zeilen.get("mqtt_tls", (None, None))[1] == tls,
          repr(zeilen.get("mqtt_tls")))
    check("%s: mqtt_tls ist ein Auswahlfeld" % label,
          zeilen.get("mqtt_tls", (None, None, None))[2] == "select",
          repr(zeilen.get("mqtt_tls")))
    optionen = zeilen.get("mqtt_tls", (None, None, None, None, None))[4]
    try:
        optionen = json.loads(optionen) if optionen else None
    except (TypeError, ValueError):
        pass
    check("%s: mqtt_tls hat die Optionen YES/NO" % label,
          optionen == ["YES", "NO"], repr(optionen))
    check("%s: mqtt_port ist ein Zahlenfeld" % label,
          zeilen.get("mqtt_port", (None, None, None))[2] == "number",
          repr(zeilen.get("mqtt_port")))
    check("%s: die alten GROSSBUCHSTABEN sind weg" % label,
          not [n for n in ALTE_NAMEN if n in zeilen],
          repr([n for n in ALTE_NAMEN if n in zeilen]))
    check("%s: alle kleingeschriebenen Parameter sind da" % label,
          all(n in zeilen for n in NEUE_NAMEN),
          repr([n for n in NEUE_NAMEN if n not in zeilen]))


def _fall_1():
    print("\n--- Upgrade mit Migration ------------------------------------")
    tmp = tempfile.mkdtemp(prefix="cbpi-mqtt-migration-")
    try:
        _kopiere(tmp)
        _starte(tmp)                      # frische Installation
        db = _db(tmp)
        _mache_alt(db)                    # Zustand einer alten Installation
        # Die Migration zurueckdrehen: schema_info steht wieder auf der
        # Version vor der MQTT-Migration.
        db.execute("DELETE FROM schema_info WHERE version=5")
        db.commit()
        db.close()

        proc = _starte(tmp)
        check("Start laeuft durch", proc.returncode == 0,
              proc.stderr.decode(errors="replace")[-400:])

        db = _db(tmp)
        _pruefe_neu(db, "Migration")
        versionen = [r[0] for r in db.execute("SELECT version FROM schema_info")]
        check("die MQTT-Migration ist verzeichnet", 5 in versionen,
              repr(versionen))
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _fall_2():
    print("\n--- Upgrade ohne Migration (Plugin uebernimmt selbst) --------")
    tmp = tempfile.mkdtemp(prefix="cbpi-mqtt-plugin-")
    try:
        _kopiere(tmp)
        _starte(tmp)
        db = _db(tmp)
        _mache_alt(db)
        # schema_info bleibt auf der neuen Version - die SQL-Migration
        # laeuft nicht. Das Plugin muss die Werte selbst mitnehmen.
        db.commit()
        db.close()

        proc = _starte(tmp)
        check("Start laeuft durch", proc.returncode == 0,
              proc.stderr.decode(errors="replace")[-400:])

        db = _db(tmp)
        _pruefe_neu(db, "Plugin")
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _fall_3():
    print("\n--- Frische Installation -------------------------------------")
    tmp = tempfile.mkdtemp(prefix="cbpi-mqtt-frisch-")
    try:
        _kopiere(tmp)
        proc = _starte(tmp)
        check("Start laeuft durch", proc.returncode == 0,
              proc.stderr.decode(errors="replace")[-400:])

        db = _db(tmp)
        zeilen = _zeilen(db)
        check("mqtt_server ist localhost",
              zeilen.get("mqtt_server", (None, None))[1] == "localhost",
              repr(zeilen.get("mqtt_server")))
        check("mqtt_port ist 1883",
              str(zeilen.get("mqtt_port", (None, None))[1]) == "1883",
              repr(zeilen.get("mqtt_port")))
        check("mqtt_tls ist NO",
              zeilen.get("mqtt_tls", (None, None))[1] == "NO",
              repr(zeilen.get("mqtt_tls")))
        check("mqtt_tls ist ein Auswahlfeld",
              zeilen.get("mqtt_tls", (None, None, None))[2] == "select",
              repr(zeilen.get("mqtt_tls")))
        optionen = zeilen.get("mqtt_tls", (None, None, None, None, None))[4]
        try:
            optionen = json.loads(optionen) if optionen else None
        except (TypeError, ValueError):
            pass
        check("mqtt_tls hat die Optionen YES/NO", optionen == ["YES", "NO"],
              repr(optionen))
        check("keine GROSSBUCHSTABEN angelegt",
              not [n for n in ALTE_NAMEN if n in zeilen],
              repr([n for n in ALTE_NAMEN if n in zeilen]))
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _fall_4():
    print("\n--- Alter TLS-Wert 'true' wird zu YES -------------------------")
    tmp = tempfile.mkdtemp(prefix="cbpi-mqtt-tls-")
    try:
        _kopiere(tmp)
        _starte(tmp)
        db = _db(tmp)
        _mache_alt(db, tls_wert="true")
        db.execute("DELETE FROM schema_info WHERE version=5")
        db.commit()
        db.close()

        _starte(tmp)
        db = _db(tmp)
        _pruefe_neu(db, "TLS", tls="YES")
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run():
    _fall_1()
    _fall_2()
    _fall_3()
    _fall_4()
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
