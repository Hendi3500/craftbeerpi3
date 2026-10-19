#!/usr/bin/env python3
"""
Vergleicht die aktuelle Route-Liste gegen die eingefrorene Baseline.

Das ist das Sicherheitsnetz fuer Position 2 (flask_classy -> MethodView) und
Position 3 (Flask-3-JSON). Vor dem Umbau wird routes_baseline.json erzeugt,
nachher routes_current.json; dieses Skript meldet jede Abweichung.

Verglichen werden drei Dinge pro URL:
  1. die Regel selbst (inklusive Slash und Parameter-Konverter)
  2. die HTTP-Methoden
  3. ob die Regel ueberhaupt noch existiert bzw. neu dazugekommen ist

Aufruf:
    python3 tools/compare_routes.py [current.json]
    Exit 0 = identisch, Exit 1 = Abweichung.
"""

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HERE, "routes_baseline.json")


def load(path):
    with io.open(path, encoding="utf-8") as fh:
        rows = json.load(fh)
    out = {}
    for r in rows:
        for method in r["methods"]:
            out[(r["rule"], method)] = r.get("endpoint", "")
    return out


def main():
    current_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "routes_current.json")

    if not os.path.exists(current_path):
        print("FEHLT: %s" % current_path)
        print("Zuerst ausfuehren:  python3 tools/snapshot_routes.py")
        return 1

    try:
        with io.open(current_path, encoding="utf-8") as fh:
            raw = fh.read()
        if not raw.strip():
            print("FEHLER: %s ist leer." % current_path)
            print("Der Snapshot ist fehlgeschlagen - Gate nicht aussagekraeftig.")
            return 1
        rows = json.loads(raw)
    except ValueError as e:
        print("FEHLER: %s ist unlesbar (%s)." % (current_path, e))
        return 1

    if not rows:
        print("FEHLER: %s enthaelt keine Routen." % current_path)
        return 1

    base = load(BASELINE)
    cur = load(current_path)

    added = sorted(set(cur) - set(base))
    removed = sorted(set(base) - set(cur))
    endpoint_changed = sorted(
        (k for k in set(base) & set(cur) if base[k] != cur[k]),
        key=lambda k: (k[0], k[1]),
    )

    print("Baseline: %d Routen | Aktuell: %d Routen" % (len(base), len(cur)))

    ok = True

    if removed:
        ok = False
        print("\nFEHLEND (%d) - nicht mehr erreichbar:" % len(removed))
        for rule, method in removed:
            print("  - %-8s %s" % (method, rule))

    if added:
        ok = False
        print("\nNEU (%d) - nicht in der Baseline:" % len(added))
        for rule, method in added:
            print("  + %-8s %s  -> %s" % (method, rule, cur[(rule, method)]))

    if endpoint_changed:
        # Der Endpoint darf sich aendern (MethodView nutzt andere Namen),
        # die Regel selbst aber nicht. Deshalb nur Hinweis.
        print("\nHINWEIS (%d): Rule gleich, Endpoint umbenannt:" % len(endpoint_changed))
        for rule, method in endpoint_changed:
            print("  ~ %-8s %s: %s -> %s" % (method, rule, base[(rule, method)], cur[(rule, method)]))

    if ok:
        print("\nOK: Route-Liste identisch zur Baseline.")
        return 0

    print("\nFEHLGESCHLAGEN: %d entfernt, %d hinzugefuegt." % (len(removed), len(added)))
    return 1


if __name__ == "__main__":
    sys.exit(main())