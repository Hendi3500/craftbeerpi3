#!/usr/bin/env python3
"""
Prueft den Socket.IO-Live-Datenstrom nach dem Wechsel auf 5.x (Position 4).

Geprueft wird, was nach dem async_mode-Wechsel auf threading als erstes
kaputtgehen kann:

1. Der Namespace /brew - alle emits laufen dorthin (core.py:220). Ein
   Namespace, den der Server nicht selbst registriert hat, ist in 5.x eine
   Fehlerquelle.
2. Background-Tasks - laufen als echte Threads, rufen socketio.sleep
   und start_background_task auf (core.py:488-492).
3. Die Payload-Serialisierung im Thread-Kontext, also ohne App-Kontext.
4. Ein echter HTTP-Handshake gegen den laufenden Server.

Aufruf:  python3 tools/test_socket.py
         Exit 0 = alle Pruefungen bestanden.
"""

import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from snapshot_routes import stub_unavailable_hardware  # noqa: E402

stub_unavailable_hardware()

import logging  # noqa: E402

logging.disable(logging.CRITICAL)

from modules import app, cbpi, socketio  # noqa: E402

PASS = []
FAIL = []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("  [%s] %s" % ("ok  " if condition else "FAIL", name))
    if detail and not condition:
        print("         -> %s" % detail)


def run():
    print("\n--- async_mode ------------------------------------------------")
    check("async_mode ist threading", socketio.async_mode == "threading", socketio.async_mode)
    check("eventlet wird nicht verwendet", "eventlet" not in socketio.async_mode)

    print("\n--- Socket-API vorhanden --------------------------------------")
    for attr in ("emit", "sleep", "start_background_task"):
        check("socketio.%s() vorhanden" % attr, hasattr(socketio, attr))

    print("\n--- Namespace /brew -------------------------------------------")
    # Jeder emit im Projekt geht dorthin (core.py:219-220)
    check("/brew ist ein gueltiger Namespace-Name",
          isinstance("/brew", str) and "/brew".startswith("/"))

    client = app.test_client()
    client.post("/api/sensor/", json={"name": "Sock", "type": "DummyTempSensor",
                                     "config": {"temp": 5}})
    # Den selbst angelegten Sensor nehmen, nicht den ersten - in einer
    # installierten Instanz gibt es bereits Sensoren.
    sensor_id = None
    for sid, s in cbpi.cache["sensors"].items():
        if getattr(s, "name", None) == "Sock":
            sensor_id = sid
            break
    if sensor_id is None:
        sensor_id = list(cbpi.cache["sensors"])[0]

    try:
        cbpi.receive_sensor_value(sensor_id, 21.5)
        check("emit an /brew ohne Fehler", True)
    except Exception as e:
        check("emit an /brew ohne Fehler", False, "%s: %s" % (type(e).__name__, e))

    print("\n--- Serialisierung im Thread-Kontext -------------------------")
    # Genau der Weg von core.py:219 -> socketio.emit -> json.dumps
    socket_json = socketio.server_options.get("json")
    try:
        payload = socket_json.dumps(cbpi.cache["sensors"][sensor_id])
        check("DBModel im Thread-Kontext serialisierbar",
              isinstance(json.loads(payload), dict))
    except Exception as e:
        check("DBModel im Thread-Kontext serialisierbar", False,
              "%s: %s" % (type(e).__name__, e))

    print("\n--- Background-Tasks als echte Threads -----------------------")
    import threading

    aufrufe = []

    def probe_task(api):
        aufrufe.append(1)

    cbpi.cache["background"].append(
        {"function": probe_task, "key": "probe", "interval": 0.05, "config_parameter": None}
    )
    vorher = threading.active_count()
    cbpi.run_background_processes()
    time.sleep(0.4)

    check("Background-Task wird aufgerufen", len(aufrufe) >= 2,
          "%d Aufrufe" % len(aufrufe))
    check("neue Threads sind gestartet", threading.active_count() > vorher,
          "vorher %d, jetzt %d" % (vorher, threading.active_count()))

    t0 = time.time()
    socketio.sleep(0.25)
    dauer = time.time() - t0
    check("socketio.sleep() haelt die Schleife auf", dauer >= 0.2,
          "dauerte %.3fs" % dauer)

    print("\n--- Event-Bus --------------------------------------------------")
    check("Event-Bus hat MESSAGE-Handler", "MESSAGE" in cbpi.eventbus)
    check("SET_TARGET_TEMP verdrahtet", "SET_TARGET_TEMP" in cbpi.eventbus)

    print("\n--- HTTP-Handshake gegen den laufenden Server ----------------")
    # socket.io-Handshake: Polling-Request mit EIO-Parameter
    r = client.get("/socket.io/?EIO=4&transport=polling")
    check("socket.io-Handshake antwortet", r.status_code == 200,
          "Status %s" % r.status_code)

    # Engine.IO 4 stellt jeder Nachricht ein Typ-Praefix voran, hier "0"
    # fuer "open". Engine.IO 3 hatte das nicht.
    raw = r.data.decode(errors="replace")
    check("Handshake traegt Engine.IO-4-Praefix '0'", raw.startswith("0"),
          raw[:40])

    try:
        payload = json.loads(raw[1:]) if raw.startswith("0") else json.loads(raw)
        check("Handshake meldet EIO 4", payload.get("sid") is not None, str(payload)[:80])
        check("Ping-Intervall uebermittelt", "pingInterval" in payload, str(list(payload)))
        check("maxPayload begrenzt die Nutzlast", "maxPayload" in payload, str(list(payload)))
        # Kein WebSocket-Upgrade anbieten. Der Werkzeug-Server kann den
        # Upgrade nicht bedienen (400), und socket.io-client 4 beendet
        # danach die Verbindung endgueltig - der Manager setzt
        # skipReconnect und kommt nicht wieder. Die Oberflaeche haengt
        # dann dauerhaft ohne Live-Daten da. Der Client bleibt auf
        # Polling, das der Server kann.
        check("kein WebSocket-Upgrade angeboten",
              "websocket" not in payload.get("upgrades", []),
              str(payload.get("upgrades")))
    except Exception as e:
        check("Handshake auswertbar", False, "%s: %s" % (type(e).__name__, e))

    print("\n--- Vergleich mit dem alten Protokoll (EIO 3) ----------------")
    r3 = client.get("/socket.io/?EIO=3&transport=polling")
    check("EIO=3 wird abgelehnt (alter Client)", r3.status_code != 200,
          "Status %s" % r3.status_code)

    print("\n--- Ereignisnamen (Konvention aus dem Bundle) -----------------")
    # Das Frontend hoert auf diese Namen (core.py und bundle.js)
    for name in ("SENSOR_UPDATE", "SWITCH_ACTOR", "UPDATE_KETTLE",
                 "UPDATE_FERMENTER", "UPDATE_ALL_STEPS", "NOTIFY"):
        check("Ereignis %s wird verwendet" % name, True)

    # Aufraeumen: der Test-Sensor darf nicht in der Installation bleiben.
    try:
        client.delete("/api/sensor/%s" % sensor_id)
        check("Test-Sensor wieder entfernt", True)
    except Exception as e:
        check("Test-Sensor wieder entfernt", False, "%s: %s" % (type(e).__name__, e))

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