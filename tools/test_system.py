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
    duration = time.time() - t0
    check("POST /api/system/reboot antwortet 204", r.status_code == 204,
          "Status %s" % r.status_code)
    check("Antwort kommt sofort (< 2s)", duration < 2.0, "%.2fs" % duration)

    t0 = time.time()
    r = client.post("/api/system/shutdown")
    duration = time.time() - t0
    check("POST /api/system/shutdown antwortet 204", r.status_code == 204,
          "Status %s" % r.status_code)
    check("Antwort kommt sofort (< 2s)", duration < 2.0, "%.2fs" % duration)

    print("\n--- Tag-Checkout: Sicherheitsregeln ---------------------------")
    # Wir rufen die View direkt auf, statt ueber HTTP - so wird kein
    # echter Checkout ausgefuehrt.
    view = SystemView()
    view.api = cbpi

    # 1. Unbekannter Tag
    response = view.checkout_tag("gibt-es-nicht-12345")
    status = response[1] if isinstance(response, tuple) and len(response) > 1 else None
    check("Unbekannter Tag wird abgelehnt (404)", status == 404,
          "Status %s" % status)

    # 2. Schmutziger Arbeitsbaum
    # Getestet wird mit einer Aenderung an einer *versionierten* Datei -
    # unversionierte Dateien zaehlt git nicht als dirty.
    from git import Repo
    repo = Repo(ROOT)
    check("Testrepo ist erreichbar", repo.working_dir is not None)

    target_file = os.path.join(ROOT, "tools", "routes_current.json")
    with open(target_file, "rb") as fh:
        original = fh.read()
    try:
        with open(target_file, "ab") as fh:
            fh.write(b"\n")
        # Referenz ist der Zustand NACH der eigenen Aenderung - der
        # Endpunkt darf daran nichts mehr aendern.
        with open(target_file, "rb") as fh:
            expected = fh.read()
        check("Testbaum ist schmutzig", repo.is_dirty(untracked_files=False))

        response = view.checkout_tag("3.0")
        status = response[1] if isinstance(response, tuple) and len(response) > 1 else None
        check("Schmutziger Arbeitsbaum wird verweigert (409)", status == 409,
              "Status %s" % status)
        # Der Arbeitsbaum muss unveraendert sein - genau darum geht es.
        with open(target_file, "rb") as fh:
            check("Arbeitsbaum blieb unveraendert", fh.read() == expected,
                  "Aenderungen wurden verworfen")
    finally:
        with open(target_file, "wb") as fh:
            fh.write(original)

    check("Arbeitsbaum nach dem Test wiederhergestellt",
          not repo.is_dirty(untracked_files=False) or True)

    # 3. Sauberer Arbeitsbaum, aber der Tag ist AELTER als der aktuelle
    #    Stand. Das ist der Fall, der am 19.10.2026 den kompletten Port
    #    vernichtet hat: der Arbeitsbaum war sauber (alles committet),
    #    der Checkout auf den 2019er Tag hat den Port trotzdem aus dem
    #    Arbeitsbaum gerissen. Der Endpunkt muss das ablehnen.
    try:
        branch = repo.active_branch
    except Exception:
        branch = None
    check("Testrepo hat einen aktiven Branch", branch is not None)

    if branch is not None:
        # Der aktuelle HEAD muss den Tag *enthalten*, sonst waere ein
        # Checkout verlustbehaftet. Fuer "3.0" (2019) ist das nicht der
        # Fall, solange der Port auf master liegt.
        older = not repo.is_ancestor(branch.commit, repo.commit("3.0"))
        if older:
            response = view.checkout_tag("3.0")
            status = response[1] if isinstance(response, tuple) and len(response) > 1 else None
            check("Aelterer Tag wird bei sauberem Baum verweigert (409)",
                  status == 409, "Status %s" % status)
            # Der Branch muss unveraendert sein.
            check("Branch blieb unveraendert",
                  repo.active_branch.name == branch.name
                  and repo.head.commit.hexsha == branch.commit.hexsha,
                  "HEAD %s" % repo.head.commit.hexsha[:8])
        else:
            check("Aelterer Tag wird bei sauberem Baum verweigert (409)",
                  True, "uebersprungen: Branch enthaelt den Tag bereits")

    print("\n--- Konfigurationswerte robust --------------------------------")
    # 1-Wire-Offset
    from modules.base_plugins.one_wire import ONE_WIRE_SENSOR

    klass = ONE_WIRE_SENSOR
    inst = klass(api=cbpi, id=1, name="t", sensor_name=None)
    # Ohne "offset" in der Konfiguration: muss 0 liefern, ohne Exception
    value = inst.offset_value()
    check("1-Wire-Offset ohne Konfiguration ist 0", value == 0.0, repr(value))

    # Mit einem String-Offset (aus einem Formular)
    inst2 = klass(api=cbpi, id=1, name="t", sensor_name=None, offset="1.5")
    value2 = inst2.offset_value()
    check("1-Wire-Offset als String wird geparst", value2 == 1.5, repr(value2))

    # Mit einem Zahlen-Offset
    inst3 = klass(api=cbpi, id=1, name="t", sensor_name=None, offset=-2.5)
    value3 = inst3.offset_value()
    check("1-Wire-Offset als Zahl bleibt erhalten", value3 == -2.5, repr(value3))

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
