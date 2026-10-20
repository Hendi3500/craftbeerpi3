#!/usr/bin/env python3
"""
Erzeugt routes_current.json aus der laufenden App.

Wird nach jedem Umbau-Schritt ausgefuehrt und mit compare_routes.py gegen
routes_baseline.json geprueft.

RPi.GPIO und git gibt es nicht auf jedem Rechner - die werden fuer den
Snapshot nur gestubbt, sonst schlaegt der Import fehl.

Aufruf:  python3 tools/snapshot_routes.py
         python3 tools/snapshot_routes.py --out path.json
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def stub_unavailable_hardware():
    """RPi.GPIO und git gibt es nicht auf jedem Rechner - nur fuer den Snapshot stubben."""
    import types

    try:
        import RPi.GPIO  # noqa: F401

        has_gpio = True
    except ImportError:
        has_gpio = False

    if not has_gpio:
        rpi = types.ModuleType("RPi")
        gpio = types.ModuleType("RPi.GPIO")

        class _FakePWM(object):
            def __init__(self, channel, frequency):
                self.channel = channel
                self.frequency = frequency

            def start(self, duty_cycle=0):
                pass

            def ChangeFrequency(self, frequency):
                self.frequency = frequency

            def ChangeDutyCycle(self, duty_cycle):
                pass

            def stop(self):
                pass

        for attr in ("setmode", "setup", "output", "input", "add_event_detect"):
            setattr(gpio, attr, lambda *a, **k: None)
        for attr in ("HIGH", "LOW", "OUT", "IN", "BCM", "BOARD", "PUD_OFF"):
            setattr(gpio, attr, 1)
        gpio.PWM = _FakePWM
        rpi.GPIO = gpio
        sys.modules["RPi"] = rpi
        sys.modules["RPi.GPIO"] = gpio

    try:
        import git  # noqa: F401
    except ImportError:
        g = types.ModuleType("git")
        g.Repo = type("Repo", (object,), {})
        g.Git = type("Git", (object,), {})
        g.GitCommandError = type("GitCommandError", (Exception,), {})
        sys.modules["git"] = g


def main():
    out = os.path.join(HERE, "routes_current.json")
    args = sys.argv[1:]
    if args and args[0] == "--out" and len(args) > 1:
        out = args[1]

    stub_unavailable_hardware()

    from modules import app

    rows = []
    for rule in app.url_map.iter_rules():
        methods = sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))
        if not methods:
            continue
        rows.append(
            {
                "rule": rule.rule,
                "methods": methods,
                "endpoint": rule.endpoint,
            }
        )

    rows.sort(key=lambda r: (r["rule"], ",".join(r["methods"])))

    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")

    print("%d Routen / %d Methoden -> %s" % (len(rows), sum(len(r["methods"]) for r in rows), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())