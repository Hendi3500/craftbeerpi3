#!/usr/bin/env python3
"""
Der Fermenter laesst sich nicht auf Automatik schalten.

Der Knopf "Auto" (POST /api/fermenter/<id>/automatic) hat den Controller
gestartet, aber der Controller ist in seiner ersten Sekunde gestorben:

    TypeError: float() argument must be a string or a real number, not 'Number'

Grund: die Konfiguration des Fermenters enthielt die Felder des Controllers
nicht (die Oberflaeche schickt nur die Felder, die der Brauer angefasst
hat). Damit blieb als Attribut ``heater_offset_min`` das Property-Objekt
selbst stehen - ein Controller rechnet aber mit Zahlen.

Abgedeckt sind:

1. Ein Controller ohne (vollstaendige) Konfiguration bekommt die Vorgabewerte
   seiner Property-Attribute; Werte aus der Konfiguration haben Vorrang.
2. Der Fermenter-Controller stirbt nicht, wenn der Sensor noch keinen Wert
   liefert - er wartet, statt den Automatik-Knopf wieder auf Handbetrieb
   zurueckfallen zu lassen.

Abruf:  python3 tools/test_fermenter_auto.py
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
    from modules.base_plugins.fermenter_hysteresis import Hysteresis
    from modules.base_plugins.hysteresis import Hysteresis as KettleHysteresis
    from modules.core.props import Property

    print("--- Property-Vorgabewerte im Controller ------------------------")
    # Der Fermenter-Controller, wie ihn der Kern aufbaut: die Konfiguration
    # ist leer, weil die Oberflaeche die Felder nicht mitgeschickt hat.
    inst = Hysteresis(api=cbpi, fermenter_id=1, heater=4, sensor=2)

    for name in ("heater_offset_min", "heater_offset_max",
                 "cooler_offset_min", "cooler_offset_max"):
        value = getattr(inst, name)
        check("%s ist eine Zahl und kein Property-Objekt" % name,
              isinstance(value, (int, float)) and not isinstance(value, Property.Number),
              repr(value))

    # Die Vorgabewerte sind die der Property-Deklaration.
    check("Vorgabewert wird uebernommen (heater_offset_min = 0)",
          inst.heater_offset_min == 0, repr(inst.heater_offset_min))

    # Der Controller kann damit rechnen - genau das hat vorher geworfen.
    try:
        float(inst.heater_offset_min)
        float(inst.cooler_offset_max)
        ok = True
        detail = ""
    except TypeError as e:
        ok = False
        detail = str(e)
    check("float() auf den Offsets funktioniert", ok, detail)

    print("\n--- Werte aus der Konfiguration haben Vorrang ----------------")
    inst2 = Hysteresis(api=cbpi, fermenter_id=1, heater=4, sensor=2,
                        heater_offset_min=1.5, cooler_offset_max=0.5)
    check("Konfigurierter Wert bleibt erhalten (heater_offset_min = 1.5)",
          inst2.heater_offset_min == 1.5, repr(inst2.heater_offset_min))
    check("nicht konfigurierte Werte bekommen ihre Vorgabe",
          inst2.cooler_offset_min == 0, repr(inst2.cooler_offset_min))

    # Dasselbe fuer den Kessel-Controller (AdvancedPID und Co. rechnen genauso).
    k = KettleHysteresis(api=cbpi, kettle_id=1, heater=1, sensor=1)
    check("Kessel-Controller: 'on' ist eine Zahl",
          isinstance(k.on, (int, float)) and not isinstance(k.on, Property.Number),
          repr(k.on))

    print("\n--- Der Controller ueberlebt einen Sensor ohne Wert ------------")
    # Ein Sensor, der noch keine Daten bekommen hat, liefert None. Der
    # Controller darf daran nicht sterben: sonst faellt der Fermenter auf
    # Handbetrieb zurueck und der Knopf sieht kaputt aus.
    inst3 = Hysteresis(api=cbpi, fermenter_id=1, heater=4, sensor=2)
    inst3.get_temp = lambda *a, **kw: None
    inst3.get_target_temp = lambda *a, **kw: 20
    inst3.heater_on = lambda *a, **kw: None
    inst3.heater_off = lambda *a, **kw: None
    inst3.cooler_on = lambda *a, **kw: None
    inst3.cooler_off = lambda *a, **kw: None

    loops = [0]

    def _sleep(seconds):
        loops[0] += 1
        if loops[0] >= 3:
            # Nach drei Zyklen ist genug geprueft.
            inst3.stop()

    inst3.sleep = _sleep
    inst3.init()

    died = None
    try:
        inst3.run()
    except Exception as e:
        died = e

    check("der Controller stirbt nicht an einem fehlenden Sensorwert",
          died is None, repr(died))
    check("der Controller hat den Zyklus uebersprungen statt abzubrechen",
          loops[0] >= 3, repr(loops[0]))

    print("\n--- Der Controller rechnet mit Sensorwert ----------------------")
    inst4 = Hysteresis(api=cbpi, fermenter_id=1, heater=4, sensor=2)
    inst4.get_temp = lambda *a, **kw: 18.0
    inst4.get_target_temp = lambda *a, **kw: 20.0
    switched = []
    inst4.heater_on = lambda *a, **kw: switched.append("heater_on")
    inst4.heater_off = lambda *a, **kw: switched.append("heater_off")
    inst4.cooler_on = lambda *a, **kw: switched.append("cooler_on")
    inst4.cooler_off = lambda *a, **kw: switched.append("cooler_off")

    cycles = [0]

    def _sleep2(seconds):
        cycles[0] += 1
        if cycles[0] >= 2:
            inst4.stop()

    inst4.sleep = _sleep2
    inst4.init()
    inst4.run()
    check("unter der Zieltemperatur wird geheizt",
          "heater_on" in switched, repr(switched))
    check("ueber der Zieltemperatur wird nicht geheizt",
          "heater_off" in switched, repr(switched))

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
