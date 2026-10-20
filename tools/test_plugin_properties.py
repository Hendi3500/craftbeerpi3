#!/usr/bin/env python3
"""
Die Plugins muessen ihre Konfigurationsfelder behalten.

Der Konfigurationsdialog in der Oberflaeche zeigt die Felder eines
Plugins anhand der Property-Definitionen, die das Backend beim Import
auswertet und in ``cbpi.cache["step_types"]`` (und den anderen
Typ-Caches) ablegt. Ohne diese Definitionen gibt es im Dialog kein
Temperaturfeld, keinen Timer und keine Hopgaben.

Diese Definitionen stehen als Klassenattribut an dem Plugin:

    temp = Property.Number("Temperature", configurable=True)

Seit die Konstruktoren die Property-Attribute aufloesen (siehe
``modules.core.props.apply_property_defaults``) traegt die *Instanz*
an dieser Stelle keinen Property mehr, sondern den Wert. Die
Auswertung darf deshalb nicht mehr die Instanz ansehen, sondern die
Klasse - sonst findet sie nichts, und alle Felder verschwinden.

Geprueft werden beide Seiten desselben Problems: die Klasse muss die
Property noch haben (der Dialog braucht sie), und die Instanz muss
Werte liefern (der Controller rechnet damit).

Abruf:  python3 tools/test_plugin_properties.py
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
    from modules import cbpi
    from modules.core.props import Property, PropertyType

    print("--- Die Brauschritte haben ihre Felder ------------------------")
    # Die Felder, die ein Brauschritt im Dialog zeigen muss.
    erwartet = {
        "MashStep": ["temp", "timer", "kettle"],
        "MashInStep": ["temp", "kettle"],
        "ChilStep": ["timer"],
        "BoilStep": ["temp", "timer", "kettle",
                     "hop_1", "hop_2", "hop_3", "hop_4", "hop_5",
                     "hop_1_name", "hop_2_name", "hop_3_name",
                     "hop_4_name", "hop_5_name"],
        "PumpStep": ["timer", "pump"],
    }

    step_types = cbpi.cache.get("step_types") or {}

    for typ, felder in erwartet.items():
        eintrag = step_types.get(typ)
        if eintrag is None:
            check("der Schritttyp %s ist registriert" % typ, False)
            continue

        vorhanden = [p.get("name") for p in eintrag.get("properties", [])]
        fehlend = [f for f in felder if f not in vorhanden]
        check("%s hat %d Properties" % (typ, len(vorhanden)),
              len(vorhanden) > 0, repr(vorhanden))
        check("%s hat die Felder %s" % (typ, ", ".join(felder)),
              not fehlend, "fehlend: %s" % repr(fehlend))

    print("\n--- Jeder Schritttyp hat mindestens ein Feld -------------------")
    for typ, eintrag in sorted(step_types.items()):
        check("%s hat mindestens ein Property" % typ,
              len(eintrag.get("properties", [])) > 0,
              repr(eintrag.get("properties")))

    print("\n--- Die anderen Pluginarten auch ----------------------------")
    for key, mindestens in (("actor_types", 1), ("sensor_types", 1),
                            ("controller_types", 1),
                            ("fermentation_controller_types", 1)):
        for typ, eintrag in sorted((cbpi.cache.get(key) or {}).items()):
            # Der Dummy-Aktor hat absichtlich keine Felder.
            if typ == "Dummy":
                continue
            check("%s/%s hat Properties" % (key, typ),
                  len(eintrag.get("properties", [])) >= mindestens,
                  repr(eintrag.get("properties")))

    print("\n--- Klasse und Instanz gleichzeitig --------------------------")
    # Die beiden Anforderungen widersprechen sich nicht: die Klasse
    # traegt die Definition, die Instanz den Wert.
    for typ, eintrag in sorted(step_types.items()):
        klasse = eintrag.get("class")
        if klasse is None:
            continue
        for name in [p.get("name") for p in eintrag.get("properties", [])]:
            attribut = getattr(klasse, name, None)
            # StepProperty hat eigene Klassen fuer Actor, Sensor und
            # Kettle - deshalb wird gegen die gemeinsame Basis geprueft.
            check("%s.%s ist an der Klasse eine Property" % (typ, name),
                  isinstance(attribut, PropertyType),
                  repr(attribut))

    print("\n--- Die Instanz rechnet mit Werten ---------------------------")
    from modules.base_plugins.brew_steps import BoilStep, MashStep

    mash = MashStep(api=cbpi, id=1, name="Rast", kettle=1, temp=67, timer=45)
    check("MashStep.temp ist eine Zahl",
          isinstance(mash.temp, (int, float)) and not isinstance(mash.temp, Property.Number),
          repr(mash.temp))
    check("MashStep.timer ist eine Zahl",
          isinstance(mash.timer, (int, float)) and not isinstance(mash.timer, Property.Number),
          repr(mash.timer))
    check("MashStep.kettle ist eine Zahl",
          isinstance(mash.kettle, (int, float)), repr(mash.kettle))

    boil = BoilStep(api=cbpi, id=6, name="Kochen", kettle=1, temp=98.5, timer=60)
    check("BoilStep.hop_1 ist aufgeloest und keine Property mehr",
          not isinstance(boil.hop_1, Property.Number), repr(boil.hop_1))
    check("BoilStep.hop_1_name ist ein Text",
          isinstance(boil.hop_1_name, str), repr(boil.hop_1_name))
    check("BoilStep.hop_1 aus der Konfiguration gewinnt",
          BoilStep(api=cbpi, id=6, hop_1=30).hop_1 == 30,
          repr(BoilStep(api=cbpi, id=6, hop_1=30).hop_1))

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
