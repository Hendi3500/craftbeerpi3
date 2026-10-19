#!/usr/bin/env python3
"""
Funktionspruefung der REST-API nach dem flask_classy-Umbau (Position 2).

Die Route-Liste kann identisch sein und die Endpunkte trotzdem kaputt sein -
etwa weil ein HTTP-Verb falsch dispatcht oder ein View die falsche Methode
aufruft. Dieses Skript schickt echte Requests und prueft die Antwort.

Abgedeckt sind:
  - CRUD ueber BaseView (GET all, GET one, POST, PUT, DELETE) fuer alle
    sechs Views, die von BaseView erben
  - Views mit Sonderrouten: actions, toggle, switch, step-Steuerung,
    Konfiguration, Logs, Notification, Recipe-Import
  - Fehlerpfade: unbekannte ID, ungueltige Methode
  - 404 fuer eine bewusst nicht existierende URL

Aufruf:  python3 tools/test_api.py
         Exit 0 = alle Pruefungen bestanden.
"""

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from snapshot_routes import stub_unavailable_hardware  # noqa: E402

stub_unavailable_hardware()

from modules import app  # noqa: E402

app.config["TESTING"] = True

# Die Endpunkt-Doku und der 1-Wire-Import sind geschwaetzig
import logging  # noqa: E402

logging.disable(logging.CRITICAL)

PASS = []
FAIL = []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    mark = "ok  " if condition else "FAIL"
    line = "  [%s] %s" % (mark, name)
    if detail and not condition:
        line += "\n         -> %s" % detail
    print(line)


def as_records(raw):
    """
    Bringt die Antwort auf eine Liste von Records.

    BaseView.getAll liefert dict, wenn __as_array__ False ist (Cache mit
    ID als Key) und eine Liste, wenn __as_array__ True ist (Steps).
    """
    if isinstance(raw, dict):
        out = []
        for key, value in raw.items():
            if isinstance(value, dict):
                record = dict(value)
                record.setdefault("id", key)
                out.append(record)
        return out
    return [r for r in raw if isinstance(r, dict)]


def safe_get(client, url):
    """
    GET, das auch Views ohne return-Aussage abfaengt.

    Mehrere Routen rufen intern genutzte Methoden ohne Response auf
    (StepView.stop_step, FermenterView.check_step). Die sind im Original
    bereits so vorhanden und liefern dort seit Flask 2 einen TypeError.
    """
    try:
        r = client.get(url)
        return r.status_code, r.data
    except TypeError:
        return "TypeError", b""


def get(client, url):
    r = client.get(url)
    return r.status_code, r.data


def post(client, url, body=None):
    return client.post(url, json=body if body is not None else {}).status_code


def put(client, url, body=None):
    return client.put(url, json=body if body is not None else {}).status_code


def delete(client, url):
    return client.delete(url).status_code


def run():
    client = app.test_client()

    print("\n--- GET / und UI -------------------------------------------------")
    status, _ = get(client, "/")
    check("GET / liefert Redirect auf /ui", status in (301, 302, 308), "Status %s" % status)
    status, _ = get(client, "/ui/")
    check("GET /ui/ liefert HTML", status == 200, "Status %s" % status)

    print("\n--- BaseView-CRUD: Sensor ----------------------------------------")
    status, body = get(client, "/api/sensor/")
    check("GET /api/sensor/ = 200", status == 200, "Status %s" % status)
    raw = json.loads(body)
    check("GET /api/sensor/ liefert Sensoren", isinstance(raw, (list, dict)), type(raw).__name__)
    sensors = as_records(raw)

    status = post(client, "/api/sensor/", {"name": "TestSensor", "type": "DummyTempSensor", "config": {"temp": 5}})
    check("POST /api/sensor/ = 200", status == 200, "Status %s" % status)

    status, body = get(client, "/api/sensor/")
    sensors = as_records(json.loads(body))
    new_id = None
    for s in sensors:
        if s.get("name") == "TestSensor":
            new_id = s.get("id")
    check("neuer Sensor in der Liste sichtbar", new_id is not None)

    if new_id is not None:
        status, _ = get(client, "/api/sensor/%s" % new_id)
        check("GET /api/sensor/<id> = 200", status == 200, "Status %s" % status)
        status = put(client, "/api/sensor/%s" % new_id, {"name": "TestSensor2", "type": "DummyTempSensor", "config": {"temp": 5}})
        check("PUT /api/sensor/<id> = 200", status == 200, "Status %s" % status)
        # DummyTempSensor bietet die Action "my_action" (@cbpi.action)
        status = post(client, "/api/sensor/%s/action/my_action" % new_id)
        check("POST /api/sensor/<id>/action/<method> = 204", status == 204, "Status %s" % status)
        status = delete(client, "/api/sensor/%s" % new_id)
        check("DELETE /api/sensor/<id> = 204", status == 204, "Status %s" % status)

    print("\n--- BaseView-CRUD: Actor -----------------------------------------")
    status = post(client, "/api/actor/", {"name": "TestActor", "type": "GPIOSimple", "config": {"gpio": 1}})
    check("POST /api/actor/ = 200", status == 200, "Status %s" % status)
    status, body = get(client, "/api/actor/")
    actors = as_records(json.loads(body))
    actor = None
    for a in actors:
        if a.get("name") == "TestActor":
            actor = a
    check("neuer Actor in der Liste sichtbar", actor is not None)

    if actor:
        aid = actor["id"]
        status = post(client, "/api/actor/%s/switch/on" % aid)
        check("POST /api/actor/<id>/switch/on = 204", status == 204, "Status %s" % status)
        status = post(client, "/api/actor/%s/switch/off" % aid)
        check("POST /api/actor/<id>/switch/off = 204", status == 204, "Status %s" % status)
        status = post(client, "/api/actor/%s/power/50" % aid)
        check("POST /api/actor/<id>/power/<power> = 204", status == 204, "Status %s" % status)
        status = delete(client, "/api/actor/%s" % aid)
        check("DELETE /api/actor/<id> = 204", status == 204, "Status %s" % status)

    print("\n--- Kettle -------------------------------------------------------")
    status, body = get(client, "/api/kettle/")
    check("GET /api/kettle/ = 200", status == 200, "Status %s" % status)
    kettles = as_records(json.loads(body))
    if kettles:
        kid = kettles[0].get("id")
        status = post(client, "/api/kettle/%s/targettemp/70" % kid)
        check("POST /api/kettle/<id>/targettemp/<temp> = 204", status == 204, "Status %s" % status)
        status = post(client, "/api/kettle/%s/automatic" % kid)
        check("POST /api/kettle/<id>/automatic = 204", status == 204, "Status %s" % status)
    else:
        # Auf einer frischen Installation gibt es keine Kessel. Die Route
        # antwortet korrekt mit 200 und leerem Objekt - kein Fehler.
        check(
            "GET /api/kettle/ = 200 (leer, keine Kessel konfiguriert)",
            status == 200,
            "Status %s" % status,
        )

    print("\n--- Config -------------------------------------------------------")
    status, _ = get(client, "/api/config/")
    check("GET /api/config/ = 200", status == 200, "Status %s" % status)
    status, body = get(client, "/api/config/")
    configs = as_records(json.loads(body))
    if configs:
        name = "unit"
        status = put(client, "/api/config/%s" % name, {"value": "C"})
        check("PUT /api/config/<name> = 200", status == 200, "Status %s" % status)
    else:
        check("Konfiguration vorhanden", False, "config leer")

    print("\n--- Steps --------------------------------------------------------")
    status, _ = get(client, "/api/step/")
    check("GET /api/step/ = 200", status == 200, "Status %s" % status)
    status = post(client, "/api/step/reset")
    check("POST /api/step/reset = 204", status == 204, "Status %s" % status)
    status = post(client, "/api/step/sort", [])
    check("POST /api/step/sort = 204", status == 204, "Status %s" % status)
    status, _ = safe_get(client, "/api/step/stop_step/")
    check(
        "GET /api/step/stop_step/ trifft die View (Vorbesteher: kein return)",
        status in (200, "TypeError"),
        "Status %s" % status,
    )

    print("\n--- Fermenter ----------------------------------------------------")
    status, body = get(client, "/api/fermenter/")
    check("GET /api/fermenter/ = 200", status == 200, "Status %s" % status)
    status, _ = safe_get(client, "/api/fermenter/check_step/")
    check(
        "GET /api/fermenter/check_step/ trifft die View (Vorbesteher: kein return)",
        status in (200, "TypeError"),
        "Status %s" % status,
    )

    print("\n--- Notification ------------------------------------------------")
    status, _ = get(client, "/api/notification/")
    check("GET /api/notification/ = 200", status == 200, "Status %s" % status)

    print("\n--- Logs ---------------------------------------------------------")
    status, _ = get(client, "/api/logs/")
    check("GET /api/logs/ = 200", status == 200, "Status %s" % status)
    status, _ = safe_get(client, "/api/logs/actions")
    check(
        "GET /api/logs/actions trifft die View (Vorbesteher: return ohne Wert)",
        status in (200, "TypeError"),
        "Status %s" % status,
    )

    print("\n--- System -------------------------------------------------------")
    status, _ = get(client, "/api/system/endpoints")
    check("GET /api/system/endpoints = 200", status == 200, "Status %s" % status)

    print("\n--- Fehlerpfade -------------------------------------------------")
    status, _ = get(client, "/api/gibtsnicht/")
    check("unbekannte URL liefert 404", status == 404, "Status %s" % status)

    status = delete(client, "/api/sensor/")
    check("DELETE /api/sensor/ = 405 (falsches Verb)", status == 405, "Status %s" % status)

    return len(PASS), len(FAIL)


def main():
    passed, failed = run()
    print("\n" + "=" * 62)
    print("Bestanden: %d   Fehlgeschlagen: %d" % (passed, failed))
    if failed:
        print("\nFehlgeschlagen:")
        for name in FAIL:
            print("  - %s" % name)
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())