#!/usr/bin/env python3
"""
Pruefung des portierten CascadeControl-Plugins.

Abgedeckt sind:

1. Die Regelalgorithmen PID und Hysteresis.
2. Die Hysteresis-Logik fuer alle vier Faelle (heizen/kuehlen x ueber/unter
   Sollwert) - mit dem Vergleich zur Original-Fassung, die einen
   Operator-Vorrang-Fehler hatte.
3. Die Sensor-Id-Ermittlung: Zahl, Ziffern-String, leer, Muell.
4. Die Einheiten-Ermittlung zum Importzeitpunkt, wenn der Config-Cache
   noch leer ist.

Abruf:  python3 tools/test_cascadecontrol.py
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
    from modules.plugins.CascadeControl import (
        Hysteresis, PID, sensor_id, temperature_einheit)

    print("--- PID ---------------------------------------------------------")
    # Der Konstruktor der Vorlage war "def **init**" - ein SyntaxError.
    # Ohne den Fix waere die Instanziierung nie gelungen.
    pid = PID(kp=7.0, ki=0.1, kd=0.5, output_min=0.0, output_max=100.0,
              integrator_error_max=1.0, integrator_initial=0.0)
    check("PID laesst sich erzeugen", pid is not None)
    check("integrator_max = (max-min)/ki = 100/0.1 = 1000",
          abs(pid.integrator_max - 1000.0) < 1e-6, repr(pid.integrator_max))

    # Erste Iteration: P-Anteil wirkt sofort
    ausgang = pid.update(current=50.0, target=60.0)
    check("erste Iteration liefert den P-Anteil (kp*Fehler = 7*10 = 70)",
          abs(ausgang - 70.0) < 1e-6, repr(ausgang))

    # Ausgang bleibt im Bereich
    for Ziel in (-100.0, 0.0, 50.0, 100.0):
        wert = pid.update(current=0.0, target=Ziel)
        check("Ausgang bei Ziel %s bleibt in 0..100" % Ziel,
              0.0 <= wert <= 100.0, repr(wert))

    # ki = 0 -> kein Integrator
    pid0 = PID(1.0, 0.0, 0.0, 0.0, 100.0, 1.0, 0.0)
    check("ki=0 ergibt integrator_max = 0", pid0.integrator_max == 0.0,
          repr(pid0.integrator_max))

    # Initialer Integrator wird auf das Maximum begrenzt
    pid2 = PID(1.0, 0.1, 0.0, 0.0, 100.0, 1.0, 99999.0)
    check("zu grosser Initial-Integrator wird begrenzt",
          abs(pid2.integrator - pid2.integrator_max) < 1e-6,
          repr(pid2.integrator))

    print("\n--- Hysteresis: die vier Faelle ---------------------------")
    # on_min/on_max/off_min = 0, damit die Zeitbedingungen nicht stoeren
    # und der reine Zustandsuebergang geprueft wird.

    faelle = [
        # (positive, current, target, erwartet, Beschreibung)
        (True, 3.0, 5.0, True, "heizen, Istwert unter Sollwert -> AN"),
        (True, 7.0, 5.0, False, "heizen, Istwert ueber Sollwert -> AUS"),
        (False, 7.0, 5.0, True, "kuehlen, Istwert ueber Sollwert -> AN"),
        (False, 3.0, 5.0, False, "kuehlen, Istwert unter Sollwert -> AUS"),
    ]

    for positive, current, target, erwartet, text in faelle:
        h = Hysteresis(positive, on_min=0, on_max=9999, off_min=0)
        ist_an = h.update(current, target)
        check(text, ist_an is erwartet, "-> %r" % ist_an)

    print("\n--- Hysteresis: Vergleich mit der Original-Fassung ----------")
    # Die Original-Fassung hatte "not(self.positive) & (current >= target)".
    # Ohne Klammern liest Python "not (self.positive & (current >= target))".
    # Bei der negativen Aktion galt damit der Fall "Istwert unter
    # Sollwert" faelschlich als AN.
    def original_update(positive, current, target, on_min=0, on_max=9999, off_min=0):
        """Die Logik der Vorlage, woertlich uebernommen."""
        last_change = time.time()
        on = False
        interval = time.time() - last_change
        if (positive & (current <= target)) | (not(positive) & (current >= target)):
            if on:
                on = True
            else:
                if interval < off_min:
                    on = False
                else:
                    last_change = time.time()
                    on = True
        elif (positive & (current > target)) | (not(positive) & (current < target)):
            if on:
                if interval < on_min:
                    on = True
                else:
                    last_change = time.time()
                    on = False
            else:
                on = False
        return on

    original = original_update(False, 3.0, 5.0)
    check("die Vorlage lieferte bei kuehlen/unter Sollwert faelschlich AN",
          original is True, repr(original))
    h = Hysteresis(False, on_min=0, on_max=9999, off_min=0)
    check("der Port liefert dort korrekt AUS", h.update(3.0, 5.0) is False)

    print("\n--- Hysteresis: Zeitbedingungen -----------------------------")
    # on_min: einmal AN, bleibt mindestens on_min Sekunden AN
    h = Hysteresis(True, on_min=60, on_max=9999, off_min=0)
    h.update(3.0, 5.0)          # wird AN
    check("Hysteresis ist AN", h.on is True, repr(h.on))
    h.update(7.0, 5.0)          # soll AUS, ist aber noch in on_min
    check("on_min haelt den Actor an", h.on is True, repr(h.on))

    # off_min: einmal AUS, bleibt mindestens off_min Sekunden AUS
    h2 = Hysteresis(True, on_min=0, on_max=9999, off_min=60)
    h2.update(7.0, 5.0)         # ist AUS
    check("Hysteresis ist AUS", h2.on is False, repr(h2.on))
    h2.update(3.0, 5.0)         # soll AN, ist aber noch in off_min
    check("off_min haelt den Actor aus", h2.on is False, repr(h2.on))

    print("\n--- sensor_id -------------------------------------------------")
    check("Zahl wird uebernommen", sensor_id(3) == 3, repr(sensor_id(3)))
    check("Ziffern-String wird uebernommen", sensor_id("3") == 3, repr(sensor_id("3")))
    check("String mit Leerzeichen", sensor_id(" 3 ") == 3, repr(sensor_id(" 3 ")))
    check("None -> None", sensor_id(None) is None, repr(sensor_id(None)))
    check("leerer String -> None", sensor_id("") is None, repr(sensor_id("")))
    check("Text -> None", sensor_id("Sensor1") is None, repr(sensor_id("Sensor1")))
    check("bool -> None", sensor_id(True) is None, repr(sensor_id(True)))

    print("\n--- temperature_einheit --------------------------------------")
    einheit = temperature_einheit()
    check("einheit ist C oder F", einheit in ("C", "F"), repr(einheit))

    # Der Config-Cache ist beim Import der Plugins leer. Der Helfer muss
    # trotzdem die eingestellte Einheit finden.
    from modules import cbpi
    vorher = cbpi.cache.get("config")
    try:
        cbpi.cache["config"] = {}
        check("mit leerem Config-Cache wird die Einheit trotzdem gefunden",
              temperature_einheit() in ("C", "F"), repr(temperature_einheit()))
    finally:
        cbpi.cache["config"] = vorher

    print("\n--- Controller-Registrierung ---------------------------------")
    typen = cbpi.cache.get("controller_types", {})
    for name in ("CascadePID", "AdvancedPID", "CascadeHysteresis",
                 "AdvancedHysteresis"):
        check("%s ist registriert" % name, name in typen, str(sorted(typen)))

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
