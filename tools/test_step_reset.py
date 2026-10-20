#!/usr/bin/env python3
"""
Der Reset der Brauschritte hat nicht das getan, was er versprochen hat.

Drei Fehler, alle in derselben Familie:

1. "Reset All" hat die Schritte auf "idle" gesetzt, aber die
   Zieltemperatur des Kessels stehen lassen. Der Kessel hat weiter auf
   die Temperatur des Schritts geheizt, ohne dass ein Schritt lief, der
   das verlangt hat.

2. Der Timer eines Schritts war kaputt. "timer_end" war das
   Property-Objekt aus der Klassendefinition und keine Zahl:
   start_timer() hat deshalb nie angehalten (der Test "self.timer_end
   is not None" war immer wahr) und is_timer_finished() hat bei jedem
   Durchlauf einen TypeError geworfen - der Schritt-Task ist damit im
   Sekundentakt gestorben.

3. Ein Rezept mit weniger als fuenf Hopgaben hat den Brauschritt
   abgeschossen: check_hop_timer() rechnet mit int(value), und value
   war None fuer die Slots, die das Rezept nicht belegt.

Abruf:  python3 tools/test_step_reset.py
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
    from modules import cbpi
    from modules.base_plugins.brew_steps import BoilStep, ChilStep, MashInStep
    from modules.core.props import Property
    from modules.steps import StepView

    print("--- Der Timer eines Schritts ----------------------------------")
    # So baut der Kern einen Schritt (modules/steps/__init__.py:init_step).
    inst = ChilStep(name="Pause", api=cbpi, id=4, timer=30,
                    managed_fields=["timer"])
    inst.init()

    check("timer_end ist eine Zahl und kein Property-Objekt",
          not isinstance(inst.timer_end, Property.Number), repr(inst.timer_end))
    check("der Timer laeuft noch nicht", inst.is_timer_running() is False)

    inst.start_timer(30 * 60)
    check("der Timer laeuft nach start_timer()", inst.is_timer_running() is True)
    check("is_timer_finished() wirft keinen TypeError",
          inst.is_timer_finished() in (True, False), repr(inst.is_timer_finished()))

    print("\n--- Ein Schritt ohne vollstaendige Konfiguration ------------")
    mash = MashInStep(name="Einmaischen", api=cbpi, id=1, kettle=1,
                      managed_fields=["temp"])
    check("der Schritt rechnet mit einer Zahl, nicht mit einem Property-Objekt",
          not isinstance(mash.temp, Property.Number), repr(mash.temp))

    print("\n--- Hop-Slots, die das Rezept nicht belegt ------------------")
    # Das Rezept des Brauers: drei Hopgaben, fuenf Slots.
    boil = BoilStep(name="Boil", api=cbpi, id=6, timer=60,
                    hop_1=0, hop_1_name="Herkules",
                    hop_2=30, hop_2_name="El Dorado",
                    hop_3=60, hop_3_name="El Dorado",
                    kettle="1", temp=98.5,
                    managed_fields=["temp", "timer", "hop_1", "hop_2", "hop_3"])
    boil.start_timer(60 * 60)
    error = None
    try:
        for num in range(1, 6):
            boil.check_hop_timer(num, getattr(boil, "hop_%s" % num))
    except Exception as e:
        error = e
    check("ein leerer Hop-Slot wirft keinen TypeError", error is None, repr(error))

    print("\n--- Der Reset beendet auch das Heizen ------------------------")
    # Der Kessel 1 steht auf 69 Grad, weil der Schritt "Einmaischen" ihn
    # auf seine Temperatur gesetzt hat. Nach dem Reset muss der Kessel
    # wieder auf 0 stehen - sonst heizt er ohne laufenden Schritt weiter.
    applied = []
    original_emit = cbpi.emit_event

    def _catch_error(name, **kwargs):
        applied.append((name, kwargs))
        return original_emit(name, **kwargs)

    class FakeStep(object):
        id = 1
        kettle = 1

        def finish(self):
            pass

    cbpi.emit_event = _catch_error
    original_active = cbpi.cache.get("active_step")
    cbpi.cache["active_step"] = FakeStep()
    try:
        StepView().stop_step()
    finally:
        cbpi.emit_event = original_emit
        cbpi.cache["active_step"] = original_active

    matches = [k for (n, k) in applied
               if n == "SET_TARGET_TEMP" and k.get("temp") == 0]
    check("der Reset setzt die Zieltemperatur des Kessels auf 0",
          len(matches) == 1, repr(applied))
    check("der Reset nennt den richtigen Kessel",
          bool(matches) and matches[0].get("id") == 1, repr(matches))

    print("\n--- Der Socket bietet keinen Websocket-Upgrade an -----------")
    # Der Werkzeug-Server kann den Upgrade nicht bedienen (400). Der
    # Client beendet danach die Verbindung und verbindet sich nicht
    # wieder - die Oberflaeche haengt dann ohne Live-Daten da.
    from modules import socketio
    check("der Server bietet kein Websocket-Upgrade an",
          socketio.server.eio.allow_upgrades is False,
          repr(socketio.server.eio.allow_upgrades))

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
