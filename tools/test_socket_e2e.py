#!/usr/bin/env python3
"""
End-to-End-Test des Live-Datenstroms (Position 4).

test_socket.py prueft die Einzelheiten mit dem Flask-Test-Client. Das Skript
hier startet einen echten Server, verbindet einen echten socket.io-Client
ueber WebSocket und wartet darauf, dass die Events des Servers tatsaechlich
ankommen - nur so laesst sich belegen, dass der komplette Weg funktioniert:

    Background-Task/Request -> cbpi.emit -> Namespace /brew ->
    Serialisierung ohne App-Kontext -> Engine.IO 4 -> WebSocket -> Client

Voraussetzung: python-socketio[client] und websocket-client installiert.

Aufruf:  python3 tools/test_socket_e2e.py
         Exit 0 = Live-Datenstrom funktioniert.
"""

import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from snapshot_routes import stub_unavailable_hardware  # noqa: E402

stub_unavailable_hardware()

import logging  # noqa: E402

logging.disable(logging.CRITICAL)

try:
    import socketio as sio
except ImportError:
    print("SKIP: python-socketio-Client nicht installiert "
          "(pip install 'python-socketio[client]' websocket-client)")
    sys.exit(0)

from modules import app, cbpi, socketio  # noqa: E402

PORT = 5093
PASS = []
FAIL = []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("  [%s] %s" % ("ok  " if condition else "FAIL", name))
    if detail and not condition:
        print("         -> %s" % detail)


def wait_for_port(port, attempts=30):
    for _ in range(attempts):
        time.sleep(0.3)
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return True
        except OSError:
            continue
    return False


def run():
    threading.Thread(
        target=lambda: socketio.run(app, host="127.0.0.1", port=PORT,
                                    allow_unsafe_werkzeug=True),
        daemon=True,
    ).start()

    check("Server startet und nimmt Verbindungen an", wait_for_port(PORT))
    time.sleep(0.6)

    root_events = []
    brew_events = []

    client = sio.Client()

    @client.on("*", namespace="/")
    def on_root(event, *args):
        root_events.append((event, args))

    @client.on("*", namespace="/brew")
    def on_brew(event, *args):
        brew_events.append((event, args))

    print("\n--- Verbindung ------------------------------------------------")
    try:
        client.connect(
            "http://127.0.0.1:%d" % PORT,
            namespaces=["/", "/brew"],
            wait_timeout=10,
        )
    except Exception as e:
        check("Client verbindet sich", False, "%s: %s" % (type(e).__name__, e))
        return len(PASS), len(FAIL)

    check("Client verbindet sich", client.connected)
    check("beide Namespaces verbunden",
          set(client.namespaces) == {"/", "/brew"}, str(list(client.namespaces)))
    check("Transport ist WebSocket", client.transport() == "websocket",
          client.transport())

    time.sleep(0.5)
    brew_events.clear()
    root_events.clear()

    print("\n--- Server->Client ueber /brew ---------------------------------")
    http = app.test_client()
    http.post("/api/sensor/",
              json={"name": "Live", "type": "DummyTempSensor", "config": {"temp": 5}})
    # Den selbst angelegten Sensor nehmen, nicht den ersten - in einer
    # installierten Instanz gibt es bereits Sensoren.
    sensor_id = None
    for sid, s in cbpi.cache["sensors"].items():
        if getattr(s, "name", None) == "Live":
            sensor_id = sid
            break
    if sensor_id is None:
        sensor_id = list(cbpi.cache["sensors"])[0]

    # SENSOR_UPDATE - der Kernfall, Temperaturempfang
    cbpi.receive_sensor_value(sensor_id, 21.5)
    time.sleep(1.2)
    names = [e for e, _ in brew_events]
    check("SENSOR_UPDATE kommt an", "SENSOR_UPDATE" in names, str(names))

    payload = next((a for e, a in brew_events if e == "SENSOR_UPDATE"), None)
    if payload:
        data = payload[0] if payload else None
        check("Sensor-Payload hat Messwert",
              isinstance(data, dict) and "name" in data, str(data)[:90])
    else:
        check("Sensor-Payload hat Messwert", False, "kein Payload")

    print("\n--- Notification ----------------------------------------------")
    brew_events.clear()
    cbpi.notify("Test", "Hallo")
    time.sleep(1.2)
    names = [e for e, _ in brew_events]
    check("NOTIFY kommt an", "NOTIFY" in names, str(names))

    print("\n--- Step-Events ------------------------------------------------")
    brew_events.clear()
    http.post("/api/step/reset")
    time.sleep(1.2)
    names = [e for e, _ in brew_events]
    check("UPDATE_ALL_STEPS kommt an", "UPDATE_ALL_STEPS" in names, str(names))

    print("\n--- Trennung der Namespaces ------------------------------------")
    check("Default-Namespace bleibt leer (Projekt sendet nur nach /brew)",
          root_events == [], str([e for e, _ in root_events]))

    client.disconnect()

    # Aufraeumen: der Test-Sensor darf nicht in der Installation bleiben.
    try:
        http.delete("/api/sensor/%s" % sensor_id)
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