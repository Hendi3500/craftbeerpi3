#!/usr/bin/env python3
"""
Pruefung der aus den Plugin-Updates in den Kern uebernommenen Funktionen.

Abgedeckt sind:

1. BoilStep: reset() reariert die Hop-Flags, hop_label() nutzt den
   konfigurierten Namen und faellt sonst auf die Nummer zurueck.
2. FermenterView.toggle: das State-Flag wird nur noch von dem cleared,
   der auch gestoppt hat - und ein Fermenter ohne Controller bleibt auf
   Handbetrieb.
3. emit_message: jede Message traegt einen Zeitstempel.
   NotificationView.dismiss: emittiert NOTIFY_DISMISS.
4. Die neuen Config-Parameter altitude, brew_recipe_uuid, plugins_changed
   und backend_started_at existieren mit dem richtigen Typ.
5. /api/restart: Status und Planung. Der echte Neustart wird dabei
   unterbunden - ein ausgefuehrter execv wuerde den Testprozess ersetzen.

Abruf:  python3 tools/test_kern_uebernahmen.py
         Exit 0 = alle Pruefungen bestanden.
"""

import os
import sys
import time

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
    from modules.base_plugins.brew_steps import BoilStep
    from modules.core.props import Property

    app.config["TESTING"] = True
    client = app.test_client()

    print("--- BoilStep: Hop-Namen ----------------------------------------")
    # Der BoilStep ohne Hop-Namen: der Alert nennt die Nummer
    inst = BoilStep(api=cbpi, id=1, name="t", temp=100, timer=90,
                    hop_1=60, hop_2=30, hop_3=15, hop_4=5, hop_5=1)
    check("hop_label ohne Namen -> 'Hop 1'",
          inst.hop_label(1) == "Hop 1", repr(inst.hop_label(1)))

    # Name gesetzt
    inst.hop_1_name = "Magnum"
    check("hop_label mit Namen -> 'Magnum'",
          inst.hop_label(1) == "Magnum", repr(inst.hop_label(1)))

    # Leerer Name -> Nummer
    inst.hop_2_name = ""
    check("hop_label mit leerem Namen -> 'Hop 2'",
          inst.hop_label(2) == "Hop 2", repr(inst.hop_label(2)))

    # Nur Leerzeichen -> Nummer
    inst.hop_3_name = "   "
    check("hop_label mit Blank -> 'Hop 3'",
          inst.hop_label(3) == "Hop 3", repr(inst.hop_label(3)))

    # Eine Zahl im Namensfeld ist kein Name
    inst.hop_4_name = "42"
    check("hop_label mit Zahl -> 'Hop 4'",
          inst.hop_label(4) == "Hop 4", repr(inst.hop_label(4)))

    print("\n--- BoilStep: reset() reariert die Hop-Flags -------------------")
    for n in range(1, 6):
        setattr(inst, "hop_%s_added" % n, True)
    inst.reset()
    flags = [getattr(inst, "hop_%s_added" % n) for n in range(1, 6)]
    check("alle Hop-Flags nach reset() geloescht",
          all(f is None for f in flags), repr(flags))
    check("Hop-Namen ueberstehen reset() (Config, kein State)",
          inst.hop_1_name == "Magnum", repr(inst.hop_1_name))

    print("\n--- BoilStep: Properties deklariert ----------------------------")
    for n in range(1, 6):
        prop = getattr(BoilStep, "hop_%s_name" % n, None)
        check("hop_%s_name ist eine Text-Property" % n,
              isinstance(prop, Property.Text), repr(prop))

    print("\n--- FermenterView.toggle ---------------------------------------")
    from modules.fermenter import FermenterView

    class FakeFermenter(object):
        def __init__(self, logic=None, state=False):
            self.id = 1
            self.name = "Testfermenter"
            self.logic = logic
            self.state = state
            self.config = {}
            self.heater = None
            self.sensor = None
            self.instance = None

    view = FermenterView()
    view.api = cbpi

    # 1. Ohne konfigurierten Controller bleibt der Fermenter auf Handbetrieb
    f = FakeFermenter(logic=None, state=False)
    cbpi.cache["fermenter"] = {1: f}
    response = view.toggle(1)
    check("toggle ohne Controller antwortet 204", response == ('', 204), repr(response))
    check("Fermenter ohne Controller bleibt auf Handbetrieb",
          f.state is False, repr(f.state))

    # 2. Automatik -> Handbetrieb: der Flag bleibt Handbetrieb
    class FakeController(object):
        def __init__(self, *a, **kw):
            self.stopped = False
            # Der Controller laeuft, bis er gestoppt wird - wie ein echter
            # Regelungs-Controller. Ein Controller, der sofort zurueckkehrt,
            # wuerde das Flag (korrekterweise) wieder auf Handbetrieb setzen.
            self.running = True
        def init(self):
            pass
        def run(self):
            while self.running:
                time.sleep(0.05)
        def stop(self):
            self.stopped = True
            self.running = False

    class FakeLogic(object):
        @staticmethod
        def get(name):
            return {"class": FakeController}

    original_get = cbpi.get_fermentation_controller
    cbpi.get_fermentation_controller = FakeLogic.get
    try:
        f2 = FakeFermenter(logic="Hysteresis", state=False)
        cbpi.cache["fermenter"] = {1: f2}
        view.toggle(1)
        check("toggle startet den Controller -> Automatik",
              f2.state is True, repr(f2.state))
        check("Controller-Instanz ist gesetzt", f2.instance is not None)

        # Der Controller laeuft - das Flag bleibt auf Automatik
        time.sleep(0.4)
        check("waehrend der Controller laeuft bleibt es auf Automatik",
              f2.state is True, repr(f2.state))

        # Jetzt auf Handbetrieb
        view.toggle(1)
        check("toggle stoppt den Controller -> Handbetrieb",
              f2.state is False, repr(f2.state))
        check("Controller wurde gestoppt", f2.instance is None)

        # Und der zurueckkehrende Task darf es nicht wieder aufdrehen
        time.sleep(0.4)
        check("nach dem Stop bleibt es auf Handbetrieb",
              f2.state is False, repr(f2.state))
    finally:
        cbpi.get_fermentation_controller = original_get
        cbpi.cache["fermenter"] = {}

    print("\n--- Notification: Zeitstempel ----------------------------------")
    receiver = []
    original_emit = cbpi.emit_event

    def _catch_error(name, **kwargs):
        if name == "MESSAGE":
            receiver.append(kwargs.get("message"))
        return original_emit(name, **kwargs)

    cbpi.emit_event = _catch_error
    try:
        cbpi.emit_message({"id": "x", "type": "info", "headline": "H",
                           "message": "M", "timeout": None})
        check("Message traegt einen Zeitstempel",
              bool(receiver) and receiver[-1].get("timestamp") is not None,
              repr(receiver[-1]) if receiver else "keine Message")
        stamp = receiver[-1].get("timestamp")
        # Epoch-Millisekunden: ungefaehr jetzt
        check("Zeitstempel ist in Millisekunden (UTC)",
              abs(stamp / 1000.0 - time.time()) < 60, repr(stamp))

        # Ein zweiter Aufruf stempelt nicht erneut
        cbpi.emit_message({"id": "y", "type": "info", "headline": "H",
                           "message": "M", "timeout": None, "timestamp": 12345})
        check("bereits gestempelte Message wird nicht neu gestempelt",
              receiver[-1].get("timestamp") == 12345,
              repr(receiver[-1].get("timestamp")))
    finally:
        cbpi.emit_event = original_emit

    print("\n--- Notification: NOTIFY_DISMISS ------------------------------")
    events = []
    original_emit2 = cbpi.emit
    cbpi.emit = lambda key, data: events.append((key, data))
    try:
        cbpi.cache["messages"] = [
            {"id": "m1", "type": "info", "headline": "H", "message": "M", "timeout": None},
            {"id": "m2", "type": "info", "headline": "H", "message": "M", "timeout": None},
        ]
        r = client.delete("/api/notification/m1")
        check("DELETE /api/notification/<id> antwortet 204", r.status_code == 204,
              "Status %s" % r.status_code)
        check("Message ist aus dem Cache raus",
              [m["id"] for m in cbpi.cache["messages"]] == ["m2"],
              repr(cbpi.cache["messages"]))
        check("NOTIFY_DISMISS wurde emittiert",
              ("NOTIFY_DISMISS", "m1") in events, repr(events))
    finally:
        cbpi.emit = original_emit2
        cbpi.cache["messages"] = []

    print("\n--- Config-Parameter -------------------------------------------")
    r = client.get("/api/config/")
    import json as _json
    config = _json.loads(r.data)
    for name, param_type in (("altitude", "number"),
                             ("brew_recipe_uuid", "text"),
                             ("plugins_changed", "text"),
                             ("backend_started_at", "text")):
        entry = config.get(name)
        check("Config-Parameter %s existiert" % name, entry is not None)
        if entry is not None:
            check("Config-Parameter %s hat den Typ %s" % (name, param_type),
                  entry.get("type") == param_type, repr(entry.get("type")))

    print("\n--- /api/restart ----------------------------------------------")
    import modules.restart as restart_modul

    # Die Sockets unererbbar machen: sonst erbt das neue Prozessbild den
    # Listening-Socket des Werkzeug-Servers und der neue Server kann den
    # Port nicht binden - das Backend steht dann nicht mehr.
    # Siehe _make_sockets_non_inheritable() in modules/restart/__init__.py.
    import socket as _socket
    probe = _socket.socket()
    try:
        probe.bind(("127.0.0.1", 0))
        os.set_inheritable(probe.fileno(), True)
        check("der Test-Socket ist ererbbar (Ausgangslage)",
              os.get_inheritable(probe.fileno()) is True)
        count = restart_modul._make_sockets_non_inheritable()
        check("der Socket ist danach unererbbar",
              os.get_inheritable(probe.fileno()) is False)
        check("die Aenderung wird gemeldet", count >= 1, repr(count))
    finally:
        probe.close()

    r = client.get("/api/restart")
    check("GET /api/restart antwortet 200", r.status_code == 200,
          "Status %s" % r.status_code)
    response = _json.loads(r.data)
    check("GET /api/restart meldet 'available'",
          response.get("available") is True, repr(response))
    check("GET /api/restart meldet 'pending'",
          response.get("pending") is False, repr(response))

    # Der echte Neustart wird unterbunden: ein execv wuerde den
    # Testprozess ersetzen.
    executed = []
    original_exec = restart_modul.os.execv
    original_brewing = restart_modul._is_brewing
    restart_modul.os.execv = lambda *args: executed.append(args)
    try:
        # 1. Ein laufender Brauschritt blockiert den Neustart. Das wird
        #    simuliert, damit der Test nicht vom Zustand der echten
        #    Datenbank abhaengt - in einer laufenden Installation kann
        #    gerade ein Schritt aktiv sein.
        restart_modul._is_brewing = lambda: True
        r = client.post("/api/restart", json={"delay": 1})
        check("POST waehrend eines Brauschritts antwortet 409", r.status_code == 409,
              "Status %s" % r.status_code)
        response = _json.loads(r.data)
        check("die 409 nennt das laufende Brauschritt", response.get("brewing") is True,
              repr(response))

        # 2. Mit force geht es auch bei laufendem Schritt
        r = client.post("/api/restart", json={"delay": 1, "force": True})
        check("POST mit force antwortet 202", r.status_code == 202,
              "Status %s" % r.status_code)
        response = _json.loads(r.data)
        check("Antwort meldet 'pending'", response.get("pending") is True, repr(response))

        # 3. Ein zweiter Request waehrend des Countdowns -> 409
        r = client.post("/api/restart", json={"delay": 1, "force": True})
        check("zweiter POST antwortet 409", r.status_code == 409,
              "Status %s" % r.status_code)

        # Der Countdown laeuft, der Neustart passiert aber nicht wirklich
        time.sleep(1.6)
        check("der Neustart wurde tatsaechlich ausgefuehrt (execv unterbunden)",
              len(executed) == 1, repr(executed))
    finally:
        restart_modul.os.execv = original_exec
        restart_modul._is_brewing = original_brewing
        restart_modul._pending = None

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
