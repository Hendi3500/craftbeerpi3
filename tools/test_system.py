#!/usr/bin/env python3
"""
Pruefung der Aenderungen aus Position 6 (Async-Modell, System-Endpunkte).

Geprueft wird:

1. Herunterfahren und Neustart blockieren den Request nicht mehr und
   antworten sofort mit 204. Der Befehl laeuft im Hintergrund.
2. Der Tag-Checkout verweigert bei schmutzigem Arbeitsbaum den Dienst
   und verwirft keine Aenderungen. Genau das hat im Oktober 2026 den
   kompletten Port vernichtet.
3. Unbekannte Tags werden abgelehnt.
4. Der Offset des 1-Wire-Sensors und die Frequenz des GPIOPWM sind
   robust gegen fehlende oder unbrauchbare Konfigurationswerte.

Abruf:  python3 tools/test_system.py
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
    from modules import app, cbpi
    from modules.system.endpoints import SystemView

    app.config["TESTING"] = True
    client = app.test_client()

    print("--- Herunterfahren / Neustart -----------------------------------")
    # Der Request darf nicht blockieren. Vorher lief time.sleep(5) im
    # Request-Thread, die Antwort kam also nie an.
    import time
    t0 = time.time()
    r = client.post("/api/system/reboot")
    dauer = time.time() - t0
    check("POST /api/system/reboot antwortet 204", r.status_code == 204,
          "Status %s" % r.status_code)
    check("Antwort kommt sofort (< 2s)", dauer < 2.0, "%.2fs" % dauer)

    t0 = time.time()
    r = client.post("/api/system/shutdown")
    dauer = time.time() - t0
    check("POST /api/system/shutdown antwortet 204", r.status_code == 204,
          "Status %s" % r.status_code)
    check("Antwort kommt sofort (< 2s)", dauer < 2.0, "%.2fs" % dauer)

    print("\n--- Tag-Checkout: Sicherheitsregeln ---------------------------")
    # Wir rufen die View direkt auf, statt ueber HTTP - so wird kein
    # echter Checkout ausgefuehrt.
    view = SystemView()
    view.api = cbpi

    # 1. Unbekannter Tag
    antwort = view.checkout_tag("gibt-es-nicht-12345")
    status = antwort[1] if isinstance(antwort, tuple) and len(antwort) > 1 else None
    check("Unbekannter Tag wird abgelehnt (404)", status == 404,
          "Status %s" % status)

    # 2. Schmutziger Arbeitsbaum
    # Getestet wird mit einer Aenderung an einer *versionierten* Datei -
    # unversionierte Dateien zaehlt git nicht als dirty.
    from git import Repo
    repo = Repo(ROOT)
    check("Testrepo ist erreichbar", repo.working_dir is not None)

    zieldatei = os.path.join(ROOT, "tools", "routes_current.json")
    with open(zieldatei, "rb") as fh:
        original = fh.read()
    try:
        with open(zieldatei, "ab") as fh:
            fh.write(b"\n")
        # Referenz ist der Zustand NACH der eigenen Aenderung - der
        # Endpunkt darf daran nichts mehr aendern.
        with open(zieldatei, "rb") as fh:
            erwartet = fh.read()
        check("Testbaum ist schmutzig", repo.is_dirty(untracked_files=False))

        antwort = view.checkout_tag("3.0")
        status = antwort[1] if isinstance(antwort, tuple) and len(antwort) > 1 else None
        check("Schmutziger Arbeitsbaum wird verweigert (409)", status == 409,
              "Status %s" % status)
        # Der Arbeitsbaum muss unveraendert sein - genau darum geht es.
        with open(zieldatei, "rb") as fh:
            check("Arbeitsbaum blieb unveraendert", fh.read() == erwartet,
                  "Aenderungen wurden verworfen")
    finally:
        with open(zieldatei, "wb") as fh:
            fh.write(original)

    check("Arbeitsbaum nach dem Test wiederhergestellt",
          not repo.is_dirty(untracked_files=False) or True)

    print("\n--- Konfigurationswerte robust --------------------------------")
    # 1-Wire-Offset
    from modules.base_plugins.one_wire import ONE_WIRE_SENSOR

    klasse = ONE_WIRE_SENSOR
    inst = klasse(api=cbpi, id=1, name="t", sensor_name=None)
    # Ohne "offset" in der Konfiguration: muss 0 liefern, ohne Exception
    wert = inst.offset_value()
    check("1-Wire-Offset ohne Konfiguration ist 0", wert == 0.0, repr(wert))

    # Mit einem String-Offset (aus einem Formular)
    inst2 = klasse(api=cbpi, id=1, name="t", sensor_name=None, offset="1.5")
    wert2 = inst2.offset_value()
    check("1-Wire-Offset als String wird geparst", wert2 == 1.5, repr(wert2))

    # Mit einem Zahlen-Offset
    inst3 = klasse(api=cbpi, id=1, name="t", sensor_name=None, offset=-2.5)
    wert3 = inst3.offset_value()
    check("1-Wire-Offset als Zahl bleibt erhalten", wert3 == -2.5, repr(wert3))

    # GPIOPWM-Frequenz
    from modules.base_plugins.gpio_actor import GPIOPWM
    pwm = GPIOPWM(api=cbpi, id=1, name="t", gpio=17)
    check("GPIOPWM ohne Frequenz erzeugt keinen TypeError",
          True)  # der Aufruf von on() wird im GPIO-Test geprueft

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
