# -*- coding: utf-8 -*-
"""
GPIO-Kompatibilitaetsschicht fuer Python 3 / Raspberry Pi OS Bookworm.

Hintergrund
-----------
``RPi.GPIO`` wird auf Raspberry Pi OS Bookworm nicht mehr gebaut - das Paket
nutzt ``imp``-APIs, die es ab Python 3.12 nicht mehr gibt. Der Ersatz ist
``rpi-lgpio`` (in requirements.txt). Das Paket bringt ein drop-in
kompatibles ``RPi.GPIO`` mit, der Import ``import RPi.GPIO as GPIO`` bleibt
also unveraendert gueltig.

Diese Schicht kapselt den Import und liefert in **jedem** Fall ein
benutzbares Objekt:

- auf dem Pi mit installiertem rpi-lgpio: das echte GPIO-Modul
- ohne GPIO (Container, Entwicklerrechner, kein Pi): ein Stub, der beim
  Zugriff eine klare Meldung loggt und einen RuntimeError mit Klartext
  ausloest.

Warum der Stub wichtig ist: vorher stand im Plugin ein

    try:
        import RPi.GPIO as GPIO
    except Exception:
        pass

Bei fehlendem GPIO war ``GPIO`` danach ein **undefinierter Name**. Die
Aktor-Typen wurden trotzdem registriert, und der Fehler schlug erst in
``init()`` mit ``NameError: name 'GPIO' is not defined`` zu - ohne jeden
Hinweis darauf, dass die Hardware fehlt. Der Stub macht aus dem
undefinierten Namen eine klare Aussage.
"""

import logging

_log = logging.getLogger(__name__)


class _StubPWM(object):
    """
    PWM-Platzhalter fuer Systeme ohne GPIO-Zugriff.

    Eigene Klasse statt einer verschachtelten: so hat sie keinen
    Zugriff auf die Stub-Instanz und kann den Fehler selbst klaeren.
    """

    def __init__(self, channel, frequency):
        raise RuntimeError(
            "GPIO not available (PWM). On the Raspberry Pi the package "
            "'rpi-lgpio' is required.")

    def start(self, dc):
        pass

    def stop(self):
        pass

    def ChangeDutyCycle(self, dc):
        pass

    def ChangeFrequency(self, freq):
        pass


class GPIOStub(object):
    """
    Platzhalter fuer Systeme ohne GPIO-Zugriff.

    Verhaelt sich wie das GPIO-Modul, meldet aber jeden Zugriff als
    Fehler. Die Konstanten entsprechen den Werten aus RPi.GPIO.
    """

    # Konstanten aus RPi.GPIO
    HIGH = 1
    LOW = 0
    OUT = 0
    IN = 1
    BOARD = 10
    BCM = 11
    PUD_OFF = 20
    PUD_DOWN = 21
    PUD_UP = 22
    HARD_PWM = 0
    SOFTWARE_PWM = 1
    VERSION = "stub"

    def __init__(self):
        self._reported = False

    def _report(self, what):
        if not self._reported:
            self._reported = True
            _log.error(
                "GPIO not available: %s cannot be executed. On the "
                "Raspberry Pi install the package 'rpi-lgpio' "
                "(pip install rpi-lgpio).", what)
        raise RuntimeError(
            "GPIO not available (%s). On the Raspberry Pi the package "
            "'rpi-lgpio' is required." % what)

    def setmode(self, mode):
        self._report("setmode")

    def getmode(self):
        return None

    def setup(self, channel, direction, pull_up_down=PUD_OFF, initial=None):
        self._report("setup")

    def output(self, channel, value):
        self._report("output")

    def input(self, channel):
        self._report("input")

    def cleanup(self, channel=None):
        self._report("cleanup")

    def add_event_detect(self, channel, edge, callback=None, bouncetime=None):
        self._report("add_event_detect")

    def remove_event_detect(self, channel, edge=None, callback=None):
        self._report("remove_event_detect")

    def event_detected(self, channel):
        self._report("event_detected")

    def wait_for_edge(self, channel, edge, bouncetime=None, timeout=None):
        self._report("wait_for_edge")

    def add_event_callback(self, channel, callback):
        self._report("add_event_callback")

    def setwarnings(self, state):
        pass

    def gpio_function(self, channel):
        self._report("gpio_function")

    PWM = _StubPWM


def _load_gpio():
    """
    GPIO-Modul laden. Reihenfolge:

    1. ``RPi.GPIO`` - das echte Modul oder der drop-in-Shim von rpi-lgpio
    2. ``rpi.lgpio`` - die native API von rpi-lgpio, falls jemand nur dieses
       Paket installiert hat
    3. Stub
    """
    try:
        import RPi.GPIO as GPIO
        _log.info("GPIO: RPi.GPIO available (version %s)",
                  getattr(GPIO, "VERSION", "?"))
        return GPIO
    except Exception as e:
        _log.info("GPIO: RPi.GPIO not available (%s)", e)

    try:
        import rpi.lgpio as GPIO
        _log.info("GPIO: rpi.lgpio available")
        return GPIO
    except Exception as e:
        _log.info("GPIO: rpi.lgpio not available (%s)", e)

    _log.warning("GPIO: no access to the GPIO interface. Actors of type "
                 "GPIOSimple/GPIOPWM/RelayBoard and the buzzer do not work. "
                 "On the Raspberry Pi 'pip install rpi-lgpio' solves the "
                 "problem.")
    return GPIOStub()


GPIO = _load_gpio()

# Verfuegbar, wenn wirklich echtes GPIO da ist. Die Plugins pruefen das
# vor dem Zugriff, damit sie sauber abbrechen statt einen Stub-Fehler
# in einem Hintergrundthread auszuloesen.
GPIO_AVAILABLE = not isinstance(GPIO, GPIOStub)
