#!/usr/bin/env python3
"""
Prueft die JSON-Serialisierung fuer REST und Socket.IO (Position 3).

Der Provider (ComplexJSONProvider) wird an zwei Stellen gebraucht:

1. REST - json.dumps() in den Views, laeuft im App-Kontext
2. Socket.IO - cbpi.emit() aus Background-Tasks heraus, laeuft AUSSERHALB
   des App-Kontexts (core.py:220)

Punkt 2 ist der heikle: flask.json.dumps greift nur im App-Kontext auf app.json
zu. flask-socketio wrappt das Modul deshalb in einen FlaskSafeJSON-Wrapper, der
den Kontext erzwingt (flask_socketio/__init__.py:216-233). Ohne diesen Wrapper
faellt jede Socket-Meldung mit einem TypeError auf die Nase.

Geprueft werden deshalb beide Wege getrennt, ausserhalb des Kontexts.

Aufruf:  python3 tools/test_json.py
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

import logging  # noqa: E402

logging.disable(logging.CRITICAL)

from modules import app, cbpi  # noqa: E402
from modules.app_config import ComplexJSONProvider  # noqa: E402
from flask import json as flask_json  # noqa: E402

PASS = []
FAIL = []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("  [%s] %s" % ("ok  " if condition else "FAIL", name))
    if detail and not condition:
        print("         -> %s" % detail)


def safe_get(client, url):
    """
    GET, das auch Views ohne return-Aussage abfaengt - mehrere Routen rufen
    intern genutzte Methoden ohne Response auf.
    """
    try:
        r = client.get(url)
        return r.status_code, r.data
    except TypeError:
        return "TypeError", b""


def run():
    client = app.test_client()

    print("\n--- Provider installiert -----------------------------------------")
    check(
        "app.json ist ComplexJSONProvider",
        isinstance(app.json, ComplexJSONProvider),
        type(app.json).__name__,
    )

    print("\n--- REST: DBModel im App-Kontext ---------------------------------")
    client.post(
        "/api/sensor/",
        json={"name": "JsonSensor", "type": "DummyTempSensor", "config": {"temp": 5}},
    )

    status, body = 200, client.get("/api/sensor/").data
    sensors = json.loads(body)
    check("GET /api/sensor/ = 200", status == 200)
    check("Sensor serialisiert", isinstance(sensors, (list, dict)))

    # Nicht "den ersten Sensor" nehmen: in einer installierten Instanz gibt
    # es bereits Sensoren (z. B. den MQTT-Sensor). Gesucht ist der, den der
    # Test gerade selbst angelegt hat.
    values = list(sensors.values()) if isinstance(sensors, dict) else sensors
    matches = [s for s in values if isinstance(s, dict) and s.get("name") == "JsonSensor"]
    found = matches[-1] if matches else None
    check("Sensor-Payload enthaelt name", isinstance(found, dict) and found.get("name") == "JsonSensor",
          str(found)[:80])

    print("\n--- Socket.IO: Serialisierung ausserhalb des Kontextes -----------")
    # Das ist der Weg, den cbpi.emit() nimmt (core.py:219-220)
    socket_json = cbpi.socketio.server_options.get("json")
    check("SocketIO hat ein json-Modul", socket_json is not None and hasattr(socket_json, "dumps"),
          str(socket_json))

    # Der eigene Test-Sensor, damit die Pruefung unabhaengig von vorhandenen
    # Sensoren in der Datenbank ist.
    own_ids = [sid for sid, s in cbpi.cache.get("sensors").items()
               if getattr(s, "name", None) == "JsonSensor"]
    sensor_ids = own_ids or list(cbpi.cache.get("sensors").keys())

    if socket_json is not None and sensor_ids:
        sensor = cbpi.cache["sensors"][sensor_ids[-1]]
        try:
            payload = socket_json.dumps(sensor)
            parsed = json.loads(payload)
            check("Sensor laesst sich ohne App-Kontext serialisieren",
                  isinstance(parsed, dict) and parsed.get("name") == "JsonSensor",
                  payload[:100])
        except Exception as e:
            check("Sensor laesst sich ohne App-Kontext serialisieren", False,
                  "%s: %s" % (type(e).__name__, e))

    print("\n--- Gegenprobe: ausserhalb des Kontexts ohne Wrapper ------------")
    # Zeigt, warum der Wrapper noetig ist
    try:
        flask_json.dumps(cbpi.cache["sensors"][sensor_ids[-1]])
        outside_ok = True
        outside_detail = ""
    except TypeError as e:
        outside_ok = False
        outside_detail = str(e)

    check(
        "flask_json.dumps scheitert ausserhalb des Kontexts (erwartet)",
        not outside_ok,
        "sollte scheitern, tat es aber nicht",
    )
    check(
        "...und genau deshalb ist der FlaskSafeJSON-Wrapper noetig",
        outside_ok is False and socket_json is not None,
        outside_detail,
    )

    print("\n--- Unbekannte Typen -------------------------------------------")
    class Unknown(object):
        pass

    # Der ComplexEncoder aus Flask 0.12 gab fuer jeden unbekannten Typ
    # "return None" zurueck. Das strikte TypeError, das der Port zunaechst
    # eingefuehrt hatte, trifft aber zur Laufzeit die Instanzen, die erst
    # waehrend des Betriebs entstehen (Hysteresis in Kettle.instance,
    # ChilStep in active_step). Damit lieferten /api/kettle/ und
    # /api/system/dump HTTP 500, sobald ein Kessel benutzt wurde.
    # Der None-Zweig ist deshalb dokumentiertes Verhalten, kein Versehen.
    with app.app_context():
        result = json.loads(flask_json.dumps(Unknown()))
    check("unbekannter Typ wird zu null (wie ComplexEncoder 0.12)",
          result is None, repr(result))

    # Der eigentliche Nutzen: die Endpunkte duerfen nicht mehr mit 500
    # antworten, wenn zur Laufzeit Instanzen im Cache liegen.
    kettle_ids = list(cbpi.cache.get("kettle", {}).keys())
    if kettle_ids:
        status, _ = safe_get(client, "/api/kettle/")
        check("/api/kettle/ antwortet trotz Laufzeit-Instanzen mit 200",
              status == 200, str(status))

    status, _ = safe_get(client, "/api/system/dump")
    check("/api/system/dump antwortet trotz Laufzeit-Instanzen mit 200",
          status == 200, str(status))

    print("\n--- Callback-Objekte (add_cache_callback) -----------------------")
    check("steps-Callback registriert", "steps" in cbpi.cache, str(list(cbpi.cache)[:12]))

    print("\n--- Cache-Dump (/api/system/dump) --------------------------------")
    try:
        r = client.get("/api/system/dump")
        check("GET /api/system/dump = 200", r.status_code == 200, "Status %s" % r.status_code)
        parsed = json.loads(r.data)
        check("Cache serialisiert", isinstance(parsed, dict))
        check("Cache enthaelt actor_types", "actor_types" in parsed, str(list(parsed)[:10]))
    except Exception as e:
        check("GET /api/system/dump", False, "%s: %s" % (type(e).__name__, e))

    # Aufraeumen: der Test legt einen Sensor an und muss ihn auch wieder
    # entfernen - sonst sammelt sich in einer echten Installation bei jedem
    # Lauf ein "JsonSensor" in der Datenbank.
    for sid in own_ids:
        try:
            client.delete("/api/sensor/%s" % sid)
        except Exception:
            pass
    if own_ids:
        rest = json.loads(client.get("/api/sensor/").data)
        values = list(rest.values()) if isinstance(rest, dict) else rest
        check("Test-Sensor wieder entfernt",
              not [s for s in values if isinstance(s, dict) and s.get("name") == "JsonSensor"],
              str([s.get("name") for s in values]))

    return len(PASS), len(FAIL)


def main():
    p, f = run()
    print("\n" + "=" * 62)
    print("Bestanden: %d   Fehlgeschlagen: %d" % (p, f))
    if f:
        print("\nFehlgeschlagen:")
        for name in FAIL:
            print("  - %s" % name)
    print("=" * 62)
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())