#!/usr/bin/env python3
"""
Pruefung der GPIO-Kompatibilitaetsschicht (Position 5).

Ohne Raspberry Pi gibt es kein echtes GPIO. Der Test prueft deshalb
zwei Dinge:

1. Der Import funktioniert in jeder Umgebung und liefert ein Objekt mit
   der vollstaendigen API.
2. Ohne echtes GPIO loest jeder Zugriff einen RuntimeError mit
   Klartext aus - nicht den NameError, den der alte Import-Pfad erzeugt
   hat ("name 'GPIO' is not defined").

Zusaetzlich wird geprueft, dass der Stub dieselben Konstanten hat wie
RPi.GPIO, weil die Aktor-Plugins ueber GPIO.BCM, GPIO.OUT, GPIO.HIGH
und GPIO.LOW gehen.

Abruf:  python3 tools/test_gpio.py
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
    print("--- GPIO-Kompatibilitaetsschicht -------------------------------")
    from modules.core import gpio

    check("Import funktioniert", True)
    check("GPIO-Objekt vorhanden", gpio.GPIO is not None)
    check("GPIO_AVAILABLE ist ein Boolean", isinstance(gpio.GPIO_AVAILABLE, bool))

    print("\n--- Konstanten (RPi.GPIO-kompatibel) --------------------------")
    for name, value in (("BCM", 11), ("BOARD", 10), ("OUT", 0), ("IN", 1),
                        ("HIGH", 1), ("LOW", 0), ("PUD_OFF", 20),
                        ("PUD_DOWN", 21), ("PUD_UP", 22)):
        check("GPIO.%s == %s" % (name, value), getattr(gpio.GPIO, name, None) == value,
              repr(getattr(gpio.GPIO, name, None)))

    print("\n--- API-Vollstaendigkeit --------------------------------------")
    for method in ("setmode", "setup", "output", "input", "cleanup",
                   "add_event_detect", "remove_event_detect",
                   "event_detected", "wait_for_edge", "getmode",
                   "setwarnings", "gpio_function"):
        check("GPIO.%s vorhanden" % method,
              callable(getattr(gpio.GPIO, method, None)))
    check("GPIO.PWM vorhanden", getattr(gpio.GPIO, "PWM", None) is not None)

    print("\n--- Verhalten ohne echtes GPIO --------------------------------")
    if gpio.GPIO_AVAILABLE:
        print("  (echtes GPIO vorhanden - der Stub-Zweig wird nicht geprueft)")
    else:
        # Jeder Zugriff muss einen RuntimeError mit Klartext liefern.
        try:
            gpio.GPIO.setmode(gpio.GPIO.BCM)
            check("setmode meldet RuntimeError", False, "kein Fehler geworfen")
        except RuntimeError as e:
            check("setmode meldet RuntimeError", True)
            check("RuntimeError nennt rpi-lgpio", "rpi-lgpio" in str(e), str(e))
        except NameError as e:
            check("setmode meldet RuntimeError", False,
                  "NameError statt RuntimeError: %s" % e)

        try:
            gpio.GPIO.output(17, 1)
            check("output meldet RuntimeError", False, "kein Fehler geworfen")
        except RuntimeError:
            check("output meldet RuntimeError", True)
        except NameError as e:
            check("output meldet RuntimeError", False, "NameError: %s" % e)

        try:
            gpio.GPIO.PWM(17, 50)
            check("PWM meldet RuntimeError", False, "kein Fehler geworfen")
        except RuntimeError:
            check("PWM meldet RuntimeError", True)
        except NameError as e:
            check("PWM meldet RuntimeError", False, "NameError: %s" % e)

    print("\n--- Aktor-Plugins nutzen die Schicht --------------------------")
    from modules.base_plugins.gpio_actor import GPIOSimple, GPIOPWM, RelayBoard
    from modules.buzzer import Buzzer

    check("GPIOSimple importiert", GPIOSimple is not None)
    check("GPIOPWM importiert", GPIOPWM is not None)
    check("RelayBoard importiert", RelayBoard is not None)
    check("Buzzer importiert", Buzzer is not None)

    print("\n--- Frequenz-Fallback im GPIOPWM ------------------------------")
    # Ohne "frequency" in der Konfiguration ist self.frequency die
    # Property-Instanz. on() darf daran nicht mit TypeError scheitern.
    klass = GPIOPWM
    try:
        inst = klass(api=None, id=1, name="t", gpio=17)
        # on() ohne echtes GPIO wirft den Stub-Fehler - das ist erwartet.
        # Entscheidend ist, dass NICHT der TypeError aus float(Property)
        # kommt.
        try:
            inst.on(power=50)
        except TypeError as e:
            check("on() scheitert nicht an float(Property)", False, str(e))
        except RuntimeError:
            check("on() scheitert nicht an float(Property)", True)
        except Exception as e:
            check("on() scheitert nicht an float(Property)", True,
                  "erwarteter Fehler: %s" % type(e).__name__)
    except Exception as e:
        check("GPIOPWM instanziierbar", False, "%s: %s" % (type(e).__name__, e))

    return len(PASS), len(FAIL)


def main():
    p, f = run()
    print("\n%d von %d Pruefungen bestanden" % (p, p + f))
    if f:
        print("Fehlgeschlagen: %s" % ", ".join(f))
        return 1
    print("ALLE PRUEFUNGEN BESTANDEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
