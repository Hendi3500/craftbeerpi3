#!/usr/bin/env python3
"""
Pruefung: Aendern und Loeschen einer unbekannten Id.

Ein Client kann eine Id schicken, die es nicht (mehr) gibt - etwa, weil
sein Zustand aelter ist als der des Backends. Der Kern hat dann mit
self.cache[id] auf einen KeyError gelaufen und mit HTTP 500 plus
Stacktrace geantwortet.

Siehe den Vorfall vom 2026-10-19: die Oberflaeche hat einen Fermenter
und einen Sensor geloescht, die im Backend schon weg waren.

Geprueft wird fuer alle Views, die von BaseView erben:
  - PUT auf eine unbekannte Id  -> 404
  - DELETE auf eine unbekannte Id -> 404
  - PUT auf eine bekannte Id funktioniert weiterhin
  - DELETE auf eine bekannte Id funktioniert weiterhin

Abruf:  python3 tools/test_unbekannte_id.py
         Exit 0 = alle Pruefungen bestanden.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PASS = []
FAIL = []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("  [%s] %s" % ("ok  " if condition else "FAIL", name))
    if detail and not condition:
        print("         -> %s" % detail)


def run():
    from modules import app, cbpi

    app.config["TESTING"] = True
    client = app.test_client()

    # Die Views, die von BaseView erben. Fuer jeden wird ein Objekt
    # angelegt, geaendert und wieder geloescht - und derselbe Aufruf
    # mit einer Id, die es nicht gibt.
    views = [
        ("Sensor", "/api/sensor/", {"name": "IdTestSensor", "type": "DummyTempSensor",
                                     "config": {"temp": 5}}),
        ("Actor", "/api/actor/", {"name": "IdTestActor", "type": "Dummy",
                                  "config": {}}),
        ("Kettle", "/api/kettle/", {"name": "IdTestKettle", "type": "Kettle",
                                    "config": {}}),
    ]

    for name, path, data in views:
        print("\n--- %s ------------------------------------------------" % name)

        r = client.post(path, json=data)
        check("POST %s legt ein Objekt an" % name, r.status_code == 200,
              "Status %s" % r.status_code)
        if r.status_code != 200:
            continue
        import json as _json
        obj = _json.loads(r.data)
        id = obj.get("id")

        # 1. PUT auf eine unbekannte Id
        r = client.put("%s%d" % (path, id + 9000), json=dict(data, name="X"))
        check("PUT auf unbekannte Id -> 404", r.status_code == 404,
              "Status %s" % r.status_code)

        # 2. DELETE auf eine unbekannte Id
        r = client.delete("%s%d" % (path, id + 9000))
        check("DELETE auf unbekannte Id -> 404", r.status_code == 404,
              "Status %s" % r.status_code)

        # 3. PUT auf die bekannte Id funktioniert weiter
        r = client.put("%s%d" % (path, id), json=dict(data, name="IdTestGeaendert"))
        check("PUT auf bekannte Id -> 200", r.status_code == 200,
              "Status %s: %s" % (r.status_code, r.data[:100]))

        # 4. DELETE auf die bekannte Id funktioniert weiter
        r = client.delete("%s%d" % (path, id))
        check("DELETE auf bekannte Id -> 204", r.status_code == 204,
              "Status %s" % r.status_code)

        # 5. Das Objekt ist danach wirklich weg
        r = client.get("%s%d" % (path, id))
        rest = r.data.decode(errors="replace")
        check("geloeschtes Objekt ist nicht mehr da",
              rest.strip() in ("null", "", "{}"), rest[:80])

    print("\n--- Sensor2: der konkrete Vorfall --------------------------")
    # Genau der Fall aus dem Log: eine Sensor-Id, die es nicht gibt.
    #
    # Wichtig: die Id wird **gesucht** und nicht fest eingetragen. Die
    # Id-Vergabe in SQLite ist bei "id INTEGER PRIMARY KEY" ohne
    # AUTOINCREMENT "max(id) + 1" - eine geloeschte Id wird also
    # wieder vergeben. Legt ein anderer Testlauf einen Sensor an und
    # bricht danach ab, liegt genau diese Id noch in der Datenbank, und
    # der Test schlaegt fehl, obwohl der Kern genau richtig antwortet
    # (die Id existiert, also ist 204 die richtige Antwort).
    #
    # Der Test sucht sich deshalb selbst eine Id, die es sicher nicht
    # gibt, und raeumt die Reste eines abgebrochenen Laufs vorher weg.
    import sqlite3 as _sqlite3

    db_path = os.path.join(ROOT, "craftbeerpi.db")
    taken_ids = set()

    try:
        db = _sqlite3.connect(db_path)
        db.row_factory = _sqlite3.Row
        for table, column in (("sensor", "id"), ("fermenter", "id")):
            for row in db.execute("SELECT %s FROM %s" % (column, table)):
                taken_ids.add(int(row[0]))
        db.close()
    except Exception:
        pass

    # Reste eines abgebrochenen Laufs entfernen: die Testobjekte
    # heissen eindeutig, ein liegengebliebener Rest wird hier
    # weggeraeumt, damit der Test nicht an ihm scheitert.
    try:
        db = _sqlite3.connect(db_path)
        for table in ("sensor", "fermenter"):
            db.execute("DELETE FROM %s WHERE name LIKE 'IdTest%%'" % table)
        db.commit()
        db.close()
    except Exception:
        pass

    def _free_id():
        """Eine Id, die es in beiden Tabellen sicher nicht gibt."""
        candidate = 2
        while candidate in taken_ids:
            candidate += 1
        return candidate

    sensor_id = _free_id()
    r = client.delete("/api/sensor/%d" % sensor_id)
    check("DELETE /api/sensor/%d (unbekannt) -> 404 statt 500" % sensor_id,
          r.status_code == 404, "Status %s" % r.status_code)

    fermenter_id = _free_id()
    r = client.delete("/api/fermenter/%d" % fermenter_id)
    check("DELETE /api/fermenter/%d (unbekannt) -> 404 statt 500" % fermenter_id,
          r.status_code == 404, "Status %s" % r.status_code)
    r = client.put("/api/fermenter/%d" % fermenter_id, json={"name": "X"})
    check("PUT /api/fermenter/%d (unbekannt) -> 404 statt 500" % fermenter_id,
          r.status_code == 404, "Status %s" % r.status_code)

    print("\n--- Chart-Endpoint: unbekannte Id --------------------------")
    # /api/logs/<t>/<id> liest direkt aus dem Cache. Fehlt die Id, gab
    # es einen 500er mit AttributeError ('NoneType' hat kein 'logic').
    # Die Oberflaeche fragt die Charts fuer alle Kessel, Sensoren und
    # Fermenter an - ein zwischenzeitlich geloeschtes Objekt hat sie
    # damit immer getroffen.
    for t, name in (("s", "Sensor"), ("k", "Kessel"), ("f", "Fermenter")):
        r = client.post("/api/logs/%s/99999" % t, json={})
        check("POST /api/logs/%s/99999 (unbekannt) -> 404 statt 500" % t,
              r.status_code == 404, "Status %s" % r.status_code)

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
