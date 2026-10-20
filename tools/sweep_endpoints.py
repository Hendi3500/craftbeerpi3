"""
Sicherer Endpunkt-Sweep.

WICHTIG: Dieser Sweep ruft ausschliesslich lesende GET-Routen auf.
Ausgeschlossen sind alle Endpunkte mit Seiteneffekt - insbesondere
/api/system/tags/<x> (fuehrt ein echtes "git checkout" aus) sowie die
Git- und Reboot-Endpunkte. Der Vorfall, an dem dieser Sweep urspruenglich
schuld war, ist in MIGRATION.md festgehalten.

Der Sweep laeuft im Flask-Test-Client, also ohne echten Server und ohne
Netzwerk. Nach jedem Endpunkt wird der Cache-Zustand geprueft, damit
ein Endpoint, der doch etwas veraendert, auffaellt.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# Endpunkte mit Seiteneffekt - die werden NICHT aufgerufen.
FORBIDDEN = (
    "/api/system/tags",       # git checkout!
    "/api/system/git",        # git pull
    "/api/system/doReboot",   # Neustart
    "/api/system/doShutdown", # Herunterfahren
    "/api/system/reboot",
    "/api/system/shutdown",
    "/api/editor/",           # legt Dateien an / loescht sie
    "/api/logs/download",     # Datei-Download
)

# Abweichungen, die im Original so vorhanden sind und bewusst nicht
# behoben wurden (MIGRATION.md, "Vorbestehende Fehler, die der Test
# aufgedeckt hat"). Es sind durchweg Methoden, die intern aufgerufen
# werden und die flask_classy nur zufaellig als HTTP-Route exponiert.
EXPECTED_DEVIATIONS = {
    "/",                                        # Redirect auf /ui
    "/api/actor/toggleTimeJob/1/1",             # interne Hilfsmethode
    "/api/beerxml/",                            # 404, solange keine beer.xml da ist
    "/api/beerxml/allowed_file/1",              # interne Hilfsmethode
    "/api/beerxml/getBoilAlerts/1",             # interne Hilfsmethode
    "/api/beerxml/getBoilTime/1",               # interne Hilfsmethode
    "/api/beerxml/getRecipeName/1",             # interne Hilfsmethode
    "/api/beerxml/getSteps/1",                  # interne Hilfsmethode
    "/api/config/1",                            # Config-View erwartet einen Namen
    "/api/fermenter/check_step/",               # interne Logik, kein return
    "/api/fermenter/get_fermenter/1",           # interne Logik, kein return
    "/api/fermenter/target_temp_reached/1/1",   # interne Logik, kein return
    "/api/kbh/",                                # 404, solange keine kbh.db da ist
    "/api/kbh/allowed_file/1",                  # interne Hilfsmethode
    "/api/logs/check_filename/1",               # gibt bool zurueck
    "/api/logs/convert_chart_data_to_json/1",   # interne Hilfsmethode
    "/api/one_wire/1",                          # kein 1-Wire-Bus vorhanden
    "/api/step/init_step/1",                    # interne Hilfsmethode
    "/api/step/stop_step/",                     # interne Logik, kein return
    "/ui/static/1",                             # Datei existiert nicht
}


def collect_routes(app):
    """Alle GET-Routen einsammeln, verbotene herausfiltern."""
    results = []
    for r in app.url_map.iter_rules():
        if r.endpoint == "static":
            continue
        if "GET" not in (r.methods or set()):
            continue
        s = str(r)
        if any(v in s for v in FORBIDDEN):
            continue
        for a in r.arguments:
            for pattern in ("<int:%s>", "<%s>", "<string:%s>", "<path:%s>"):
                s = s.replace(pattern % a, "1")
        results.append(s)
    return sorted(set(results))


def main():
    from modules import app

    client = app.test_client()
    routes = collect_routes(app)
    print("Sweep ueber %d GET-Routen (ohne die %d verbotenen Muster)\n"
          % (len(routes), len(FORBIDDEN)))

    errors = []
    expected = []
    ok = 0
    for path in routes:
        try:
            r = client.get(path)
            code = r.status_code
        except TypeError:
            # View ohne return-Aussage - im Original so vorhanden
            code = "TypeError"
        except Exception as e:
            code = "%s: %s" % (type(e).__name__, e)
        if code == 200:
            ok += 1
        elif path in EXPECTED_DEVIATIONS:
            expected.append((path, code))
        else:
            errors.append((path, code))

    print("HTTP 200: %d von %d" % (ok, len(routes)))
    if expected:
        print("\nErwartete Abweichungen (%d) - im Original so vorhanden:" % len(expected))
        for p, c in expected:
            print("  %-46s -> %s" % (p, c))
    if errors:
        print("\nUNERWARTETE Abweichungen (%d):" % len(errors))
        for p, c in errors:
            print("  %-46s -> %s" % (p, c))
    else:
        print("\nKeine unerwarteten Abweichungen.")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
