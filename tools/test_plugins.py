#!/usr/bin/env python3
"""
Pruefung des Plugin-Managements (Position 7).

Geprueft wird:

1. Pfad-Traversal: Ein Name wie "../../logs" darf weder loeschen noch
   schreiben noch lesen. Vorher loeschte deletePlugin damit jedes
   Verzeichnis, auf das der Prozess zugreifen konnte - der Server lauscht
   an 0.0.0.0, ist also im LAN erreichbar.
2. __pycache__ und andere Junk-Verzeichnisse erscheinen nicht als
   installierte Plugins und werden nicht geladen.
3. Der Reload-Endpunkt funktioniert (vorher: NameError wegen undefiniertem
   "cache", NameError wegen "reload" als Builtin und AttributeError wegen
   "e.message").
4. Der Download-Endpunkt gibt bei unbekanntem Namen 404 statt 500.

Abruf:  python3 tools/test_plugins.py
         Exit 0 = alle Pruefungen bestanden.
"""

import json
import os
import shutil
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
    from modules.addon import endpoints

    app.config["TESTING"] = True
    client = app.test_client()

    print("--- Namensvalidierung ------------------------------------------")
    for boese in ("../../logs", "../../../tmp", "..", ".", "/etc",
                  "a/b", "a\\b", "", "x" * 300):
        pfad = endpoints._plugin_pfad(boese)
        check("Name %-18r wird abgelehnt" % boese, pfad is None,
              "-> %r" % pfad)

    print("\n--- Erlaubte Namen --------------------------------------------")
    for gut in ("MQTTPlugin", "mein_plugin", "plugin-1", "Plugin2"):
        pfad = endpoints._plugin_pfad(gut)
        check("Name %-18r wird akzeptiert" % gut, pfad is not None,
              "-> %r" % pfad)

    print("\n--- Traversal ueber HTTP --------------------------------------")
    # Ueber HTTP greift zuerst das Routing: Werkzeug normalisiert ".."
    # im Pfad, der Request passt auf keine Route und es kommt ein 404.
    # Die View bekommt den Namen also gar nicht erst zu sehen.
    #
    # Der eigentliche Schutz sitzt in _plugin_pfad() - der wird unten
    # direkt an der View geprueft, weil dort ein Request-Client nicht
    # dazwischenkommt.
    for methode, pfad, was in (
            ("delete", "/api/editor/../../logs", "DELETE"),
            ("put", "/api/editor/../../logs", "PUT"),
            ("post", "/api/editor/../../logs", "POST"),
            ("get", "/api/editor/../../logs", "GET")):
        r = getattr(client, methode)(pfad, data=b"x")
        check("%s mit Traversal wird nicht ausgefuehrt (%s)" % (was, r.status_code),
              r.status_code in (400, 404), "Status %s" % r.status_code)

    if os.path.isdir(os.path.join(ROOT, "logs")):
        check("logs-Verzeichnis existiert noch",
              os.path.isdir(os.path.join(ROOT, "logs")))

    print("\n--- Traversal direkt an der View ------------------------------")
    # Ohne den Request-Client - so pruefen wir die Schicht, die wirklich
    # schuetzt, falls sich das Routing aendert.
    r = endpoints.deletePlugin("../logs")
    check("deletePlugin lehnt Traversal ab (400)",
          isinstance(r, tuple) and r[1] == 400, repr(r))
    r = endpoints.createPlugin("../logs")
    check("createPlugin lehnt Traversal ab (400)",
          isinstance(r, tuple) and r[1] == 400, repr(r))
    r = endpoints.saveFile("../logs")
    check("saveFile lehnt Traversal ab (400)",
          isinstance(r, tuple) and r[1] == 400, repr(r))
    r = endpoints.reload_plugin("../logs")
    check("reload_plugin lehnt Traversal ab (400)",
          isinstance(r, tuple) and r[1] == 400, repr(r))
    r = endpoints.download_addon("../logs")
    check("download_addon lehnt Traversal ab (400)",
          isinstance(r, tuple) and r[1] == 400, repr(r))
    r = endpoints.update_addon("../logs")
    check("update_addon lehnt Traversal ab (400)",
          isinstance(r, tuple) and r[1] == 400, repr(r))

    print("\n--- __pycache__ taucht nicht als Plugin auf --------------------")
    r = client.get("/api/editor/")
    try:
        liste = json.loads(r.data)
    except Exception:
        liste = None
    check("GET /api/editor/ liefert eine Liste", isinstance(liste, list),
          repr(r.data)[:80])
    if isinstance(liste, list):
        check("__pycache__ ist nicht in der Liste", "__pycache__" not in liste,
              str(liste))
        check("nur echte Verzeichnisse in der Liste",
              all(os.path.isdir(os.path.join(endpoints.PLUGIN_DIR, n))
                  for n in liste), str(liste))

    print("\n--- Modul-Register --------------------------------------------")
    check("__pycache__ nicht im Modul-Register",
          "__pycache__" not in endpoints.modules,
          str([k for k in endpoints.modules if k.startswith("_")]))
    check("base_plugin mqtt geladen", "mqtt" in endpoints.modules,
          str(sorted(endpoints.modules)))

    print("\n--- Reload-Endpunkt -------------------------------------------")
    # Einen echten, minimalen Plugin-Ordner anlegen
    testname = "TestPluginReload"
    testdir = os.path.join(ROOT, "modules", "plugins", testname)
    os.makedirs(testdir, exist_ok=True)
    with open(os.path.join(testdir, "__init__.py"), "w") as f:
        f.write("MARKER = 1\n")
    try:
        r = client.post("/api/editor/%s/reload/" % testname)
        check("Reload eines neuen Plugins antwortet 204", r.status_code == 204,
              "Status %s: %s" % (r.status_code, r.data[:120]))
        check("Plugin steht danach im Register", testname in endpoints.modules,
              str(sorted(endpoints.modules)))

        # Nochmal reloaden - der Modul-Pfad muss funktionieren
        r = client.post("/api/editor/%s/reload/" % testname)
        check("Reload eines bekannten Plugins antwortet 204",
              r.status_code == 204, "Status %s: %s" % (r.status_code, r.data[:120]))

        r = client.post("/api/editor/../../logs/reload/")
        check("Reload mit Traversal wird nicht ausgefuehrt",
              r.status_code in (400, 404), "Status %s" % r.status_code)
    finally:
        shutil.rmtree(testdir, ignore_errors=True)
        endpoints.modules.pop(testname, None)

    print("\n--- Download-Endpunkt -----------------------------------------")
    r = client.post("/api/editor/gibt-es-nicht/download")
    check("Download eines unbekannten Plugins antwortet 404",
          r.status_code == 404, "Status %s" % r.status_code)

    r = client.post("/api/editor/../../logs/download")
    check("Download mit Traversal wird nicht ausgefuehrt",
          r.status_code in (400, 404), "Status %s" % r.status_code)

    print("\n--- Anlegen und Loeschen im Normalfall ------------------------")
    name = "TestPluginNormal"
    r = client.put("/api/editor/%s" % name)
    check("PUT legt ein Plugin an (204)", r.status_code == 204,
          "Status %s" % r.status_code)
    check("Verzeichnis existiert",
          os.path.isdir(os.path.join(ROOT, "modules", "plugins", name)))

    r = client.post("/api/editor/%s" % name, data=b"X = 2\n")
    check("POST speichert den Code (204)", r.status_code == 204,
          "Status %s" % r.status_code)
    with open(os.path.join(ROOT, "modules", "plugins", name, "__init__.py")) as f:
        check("Code wurde geschrieben", f.read() == "X = 2\n")

    r = client.get("/api/editor/%s" % name)
    check("GET liefert den Code (200)", r.status_code == 200,
          "Status %s" % r.status_code)

    r = client.delete("/api/editor/%s" % name)
    check("DELETE entfernt das Plugin (204)", r.status_code == 204,
          "Status %s" % r.status_code)
    check("Verzeichnis ist weg",
          not os.path.isdir(os.path.join(ROOT, "modules", "plugins", name)))

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
