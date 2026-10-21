#!/usr/bin/env python3
"""
Die Reihenfolge des Gaer-Schrittplans laesst sich aendern.

Der Kern hat eine Spalte ``order`` in der Step-Tabelle, zaehlt sie bei jedem
neuen Step hoch - und las sie nie wieder. Die Steps kamen damit in der
Reihenfolge zurueck, in der die Zeilen geschrieben wurden, und es gab keinen
Endpunkt, der die Reihenfolge aendert. Die Oberflaeche konnte einen
Schrittplan deshalb nicht anders anzeigen, als er laeuft.

Abgedeckt sind:

1. ``FermenterStep.get_by_fermenter_id`` liefert die Steps nach ihrer
   Reihenfolge sortiert (vorher entschied die Datenbank).
2. ``POST /api/fermenter/<id>/step/sort`` schreibt die neue Reihenfolge in
   die Datenbank **und** stellt die Liste im Cache um - die Liste im Cache ist
   die, aus der der Kern den naechsten Step nimmt, also die, in der die
   Gaerung laeuft.
3. Der Endpunkt weist einen unvollstaendigen Body (ein Step fehlt), eine
   fremde Step-Id, eine doppelte Step-Id und einen Body, der kein JSON ist,
   ab (400) und antwortet 404, wenn es den Fermenter nicht gibt.
4. Eine laufende Gaerung wird nicht umsortiert (409) - der Step, den der
   Regler faehrt, steht im Cache.
5. Die Route des Kerns ``/api/fermenter/<id>/step/<stepid>`` ist nicht
   verdeckt: das Sortieren hat den Weg des Kerns nicht verbaut.
6. Ein geloeschter Fermenter nimmt seine Steps mit - sonst stuenden sie als
   Waisen in der Tabelle, und der naechste Fermenter (SQLite vergibt die Id
   wieder) bekaeme den Schrittplan des gelöschten.

Abruf:  python3 tools/test_fermenter_step_order.py
         Exit 0 = alle Pruefungen bestanden.
"""

import json
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

    app.config["TESTING"] = True

    # Die Modelle brauchen einen App-Kontext (get_db() haengt an ``g``), die
    # Test-Requests bringen ihren eigenen mit.
    with app.app_context():
        return run_checks(app, cbpi)


def run_checks(app, cbpi):
    from modules.fermenter import Fermenter, FermenterStep

    client = app.test_client()

    fermenter = None
    fermenter_id = None
    step_ids = []

    try:
        print("--- Der Testfall im Backend anlegen -------------------------")
        fermenter = Fermenter.insert(name="__test_step_order__", brewname="",
                                     sensor=None, sensor2=None, sensor3=None,
                                     heater=None, cooler=None, logic=None,
                                     config="{}", target_temp=0)
        fermenter_id = fermenter.id

        # Steps, die zu einem geloeschten Fermenter dieser Id gehoeren, sind
        # Waisen (SQLite vergibt die Id wieder). Sie wuerden den Testfall
        # stoeren - und sind genau der Grund, warum der Fermenter seine
        # Steps jetzt mitloescht.
        orphans = FermenterStep.get_by_fermenter_id(fermenter_id)
        for orphan in orphans:
            FermenterStep.delete(orphan.id)

        # Drei Steps, bewusst in der falschen Reihenfolge angelegt: der
        # dritte zuerst, der erste zuletzt. Ohne Sortierung kaeme genau
        # diese Reihenfolge zurueck.
        ids = {}
        for name, order in (("C", 3), ("A", 1), ("B", 2)):
            step = FermenterStep.insert(name=name, days=0, hours=0, minutes=0,
                                        temp=20, direction="H", order=order,
                                        state="I", start=None, end=None,
                                        timer_start=None,
                                        fermenter_id=fermenter_id)
            ids[name] = step.id
            step_ids.append(step.id)

        fermenter.steps = FermenterStep.get_by_fermenter_id(fermenter_id)
        cbpi.cache.setdefault("fermenter", {})[fermenter_id] = fermenter

        print("\n--- Die Steps kommen sortiert zurueck ------------------------")
        names = [s.name for s in FermenterStep.get_by_fermenter_id(fermenter_id)]
        check("get_by_fermenter_id liefert A, B, C", names == ["A", "B", "C"],
              repr(names))

        # Der Cache ist beim Start aus der Datenbank gefuellt - er muss
        # dieselbe Reihenfolge haben, sonst laeuft die Gaerung in einer
        # anderen Reihenfolge als der Plan.
        cached = [s.name for s in fermenter.steps]
        check("der Cache steht in derselben Reihenfolge",
              cached == ["A", "B", "C"], repr(cached))

        print("\n--- Sortieren ueber HTTP -----------------------------------")
        # Die Reihenfolge umdrehen: B, A, C
        body = [[ids["B"], 1], [ids["A"], 2], [ids["C"], 3]]
        r = client.post("/api/fermenter/%s/step/sort" % fermenter_id,
                        data=json.dumps(body),
                        content_type="application/json")
        check("POST /api/fermenter/<id>/step/sort antwortet 204",
              r.status_code == 204, "Status %s: %s" % (r.status_code, r.data[:200]))

        db_steps = FermenterStep.get_by_fermenter_id(fermenter_id)
        check("die Datenbank fuehrt die Schritte in der neuen Reihenfolge",
              [s.name for s in db_steps] == ["B", "A", "C"],
              repr([s.name for s in db_steps]))
        check("die Reihenfolge steht in der Spalte 'order'",
              [s.order for s in db_steps] == [1, 2, 3],
              repr([s.order for s in db_steps]))

        cached = [s.name for s in cbpi.cache["fermenter"][fermenter_id].steps]
        check("die Liste im Cache ist umgestellt - das ist die, aus der der "
              "Kern den naechsten Step nimmt",
              cached == ["B", "A", "C"], repr(cached))

        print("\n--- Unvollstaendige Bodies ----------------------------------")
        r = client.post("/api/fermenter/%s/step/sort" % fermenter_id,
                        data=json.dumps([[ids["A"], 1]]),
                        content_type="application/json")
        check("ein fehlender Step wird abgelehnt (400)", r.status_code == 400,
              "Status %s: %s" % (r.status_code, r.data[:200]))

        r = client.post("/api/fermenter/%s/step/sort" % fermenter_id,
                        data=json.dumps([[ids["A"], 1], [ids["B"], 2],
                                         [999999, 3]]),
                        content_type="application/json")
        check("eine fremde Step-Id wird abgelehnt (400)", r.status_code == 400,
              "Status %s: %s" % (r.status_code, r.data[:200]))

        r = client.post("/api/fermenter/%s/step/sort" % fermenter_id,
                        data=json.dumps([[ids["A"], 1], [ids["A"], 2],
                                         [ids["B"], 3]]),
                        content_type="application/json")
        check("eine doppelte Step-Id wird abgelehnt (400)", r.status_code == 400,
              "Status %s: %s" % (r.status_code, r.data[:200]))

        r = client.post("/api/fermenter/%s/step/sort" % fermenter_id,
                        data="kein json", content_type="application/json")
        check("ein Body, der kein JSON ist, wird abgelehnt (400)",
              r.status_code == 400, "Status %s: %s" % (r.status_code, r.data[:200]))

        check("die Reihenfolge ist nach den Ablehnungen unveraendert",
              [s.name for s in FermenterStep.get_by_fermenter_id(fermenter_id)]
              == ["B", "A", "C"])

        print("\n--- Eine laufende Gaerung wird nicht umsortiert --------------")
        # Der laufende Step steht in der Liste im Cache - der Kern setzt dort
        # den Status "A" (start_fermentation).
        running = cbpi.cache["fermenter"][fermenter_id].steps[0]
        running.state = "A"
        FermenterStep.update(**running.__dict__)

        r = client.post("/api/fermenter/%s/step/sort" % fermenter_id,
                        data=json.dumps([[ids["A"], 1], [ids["B"], 2],
                                         [ids["C"], 3]]),
                        content_type="application/json")
        check("waehrend der Gaerung wird nicht umsortiert (409)",
              r.status_code == 409, "Status %s: %s" % (r.status_code, r.data[:200]))
        check("die Reihenfolge ist unveraendert",
              [s.name for s in FermenterStep.get_by_fermenter_id(fermenter_id)]
              == ["B", "A", "C"])

        running.state = "I"
        FermenterStep.update(**running.__dict__)

        # Auch der Task des Controllers sperrt: der Eintrag in
        # cbpi.cache["fermenter_task"] steht, solange ein Schritt geheizt
        # wird - der Zustand des Steps und der Eintrag fallen nicht in jedem
        # Moment zusammen.
        cbpi.cache.setdefault("fermenter_task", {})[fermenter_id] = running
        try:
            r = client.post("/api/fermenter/%s/step/sort" % fermenter_id,
                            data=json.dumps([[ids["A"], 1], [ids["B"], 2],
                                             [ids["C"], 3]]),
                            content_type="application/json")
            check("waehrend der Gaerung (Task im Cache) wird nicht "
                  "umsortiert (409)", r.status_code == 409,
                  "Status %s: %s" % (r.status_code, r.data[:200]))
        finally:
            cbpi.cache.get("fermenter_task", {}).pop(fermenter_id, None)

        print("\n--- Unbekannter Fermenter ----------------------------------")
        r = client.post("/api/fermenter/999999/step/sort",
                        data=json.dumps([[1, 1]]),
                        content_type="application/json")
        check("ein unbekannter Fermenter antwortet 404", r.status_code == 404,
              "Status %s: %s" % (r.status_code, r.data[:200]))

        print("\n--- Die Route des Kerns ist nicht verdeckt -------------------")
        # "sort" ist keine Step-Id, und die Kern-Regel trifft nur ganze
        # Zahlen - der Kern laeuft also unter seinem eigenen Pfad weiter.
        r = client.delete("/api/fermenter/%s/step/%s" % (fermenter_id, step_ids[0]))
        check("DELETE /api/fermenter/<id>/step/<stepid> antwortet 204",
              r.status_code == 204, "Status %s: %s" % (r.status_code, r.data[:200]))
        check("der Step ist weg",
              step_ids[0] not in [s.id for s in
                                  FermenterStep.get_by_fermenter_id(fermenter_id)])
        step_ids.remove(step_ids[0])

        print("\n--- Ein geloeschter Fermenter nimmt seine Steps mit --------")
        r = client.delete("/api/fermenter/%s" % fermenter_id)
        check("DELETE /api/fermenter/<id> antwortet 204", r.status_code == 204,
              "Status %s: %s" % (r.status_code, r.data[:200]))
        check("die Steps des Fermenters sind mit geloescht",
              FermenterStep.get_by_fermenter_id(fermenter_id) == [],
              repr([s.name for s in FermenterStep.get_by_fermenter_id(fermenter_id)]))
        step_ids = []
        fermenter_id = None

        return len(PASS), len(FAIL)

    finally:
        # Der Testfall verschwindet wieder - auch aus dem Cache.
        try:
            for step_id in step_ids:
                FermenterStep.delete(step_id)
            if fermenter_id is not None:
                Fermenter.delete(fermenter_id)
                cbpi.cache.get("fermenter", {}).pop(fermenter_id, None)
        except Exception as e:
            print("  (Aufraeumen nicht vollstaendig: %s)" % e)


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
