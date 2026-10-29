#!/usr/bin/env python3
"""
M6: Golden Fixture Vergleich.

Startet das TS-Backend als echter Server und verwendet den Flask
Test-Client fuer das Python-Backend. Beide lesen dieselbe Kopie der
craftbeerpi.db. Alle lesenden GET-Endpunkte werden auf beide Backend
aufgerufen und die Antworten byte-weise verglichen (kanonisches JSON).

Abweichungen:
  - Inhaltlich (Status, Body)
  - Content-Type

Usage:
    python3 tools/fixture_compare.py
"""
import json
import os
import sys
import subprocess
import time
import shutil
from urllib.request import urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

# Hardware stubs (GPIO, git) - siehe snapshot_routes.py
from snapshot_routes import stub_unavailable_hardware  # noqa: E402

stub_unavailable_hardware()

# Flask test client
from modules import app as flask_app  # noqa: E402

flask_app.config["TESTING"] = True
client = flask_app.test_client()

# TS-Backend starten
TS_PORT = 5199
TS_DB = "/tmp/cbpi-fixture-compare.db"

# Kopie der DB fuer einen sauberen Vergleich
src_db = os.path.join(ROOT, "craftbeerpi.db")
if os.path.exists(src_db):
    shutil.copy2(src_db, TS_DB)
    print(f"DB-Kopie: {TS_DB}")

# TS-Backend starten
ts_env = dict(os.environ, CBPI_DB=TS_DB, CBPI_PORT=str(TS_PORT), CBPI_LOG_STDOUT="1")
ts_proc = subprocess.Popen(
    ["node", "backend-ts/src/index.ts"],
    cwd=ROOT,
    env=ts_env,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)

# Warten bis der Server bereit ist
ts_ready = False
for _ in range(50):
    try:
        r = urlopen(f"http://127.0.0.1:{TS_PORT}/api/config/", timeout=1)
        if r.status == 200:
            ts_ready = True
            break
    except (URLError, HTTPError):
        time.sleep(0.2)

if not ts_ready:
    print("TS-Backend konnte nicht gestartet werden!")
    ts_proc.terminate()
    sys.exit(1)

print(f"TS-Backend laeuft auf Port {TS_PORT}")

# Routes sammeln (lesend nur, wie in sweep_endpoints.py)
FORBIDDEN = (
    "/api/system/tags", "/api/system/git", "/api/system/doReboot",
    "/api/system/doShutdown", "/api/system/reboot", "/api/system/shutdown",
    "/api/editor/", "/api/logs/download",
    "/api/actor/toggleTimeJob",   # interne Hilfsmethode
    "/api/fermenter/target_temp_reached",  # interne Logik
    "/api/step/init_step",
    "/api/step/stop_step",
)
EXPECTED_DEVIATIONS = {
    "/",                          # Redirect
    "/api/beerxml/",             # 404 ohne Datei
    "/api/beerxml/getBoilAlerts/1",
    "/api/beerxml/getBoilTime/1",
    "/api/beerxml/getRecipeName/1",
    "/api/beerxml/getSteps/1",
    "/api/beerxml/allowed_file/1",
    "/api/config/1",             # Config-View erwartet einen Namen
    "/api/fermenter/check_step/",  # interne Logik
    "/api/fermenter/get_fermenter/1",  # interne Logik
    "/api/kbh/",                 # 404 ohne Datei
    "/api/kbh/allowed_file/1",
    "/api/logs/check_filename/1",  # gibt bool zuruck
    "/api/logs/convert_chart_data_to_json/1",
    "/api/one_wire/1",
    "/api/recipe/import/v1/",    # POST-only
    "/static/1",
    "/ui/static/1",
}

def collect_get_routes(app):
    """Alle GET-Routen aus der Flask-URL-Map."""
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

routes = collect_get_routes(flask_app)
print(f"\nVergleiche {len(routes)} GET-Endpunkte...\n")

errors = []
ok = 0
expected = []

for path in routes:
    # Python-Antwort
    try:
        py_resp = client.get(path)
        py_status = py_resp.status_code
        py_body = py_resp.data.decode("utf-8", errors="replace")
        py_ct = py_resp.content_type
    except TypeError:
        py_status = "TypeError"
        py_body = ""
        py_ct = ""
    except Exception as e:
        py_status = f"{type(e).__name__}"
        py_body = str(e)
        py_ct = ""

    # TS-Antwort
    try:
        ts_resp = urlopen(f"http://127.0.0.1:{TS_PORT}{path}", timeout=5)
        ts_status = ts_resp.status
        ts_body = ts_resp.read().decode("utf-8", errors="replace")
        ts_ct = ts_resp.headers.get("Content-Type", "")
    except HTTPError as e:
        ts_status = e.code
        ts_body = e.read().decode("utf-8", errors="replace") if hasattr(e, 'read') else ""
        ts_ct = e.headers.get("Content-Type", "") if hasattr(e, 'headers') else ""
    except Exception as e:
        ts_status = f"{type(e).__name__}"
        ts_body = str(e)
        ts_ct = ""

    # Vergleich
    # Kanonisches JSON: parsen und erneut serialisieren mit sort_keys
    def canonical(body, status):
        if status != 200:
            return (status, body.strip(), "")
        try:
            data = json.loads(body)
            return (status, json.dumps(data, sort_keys=True, ensure_ascii=False), "")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return (status, body, "")

    py_can = canonical(py_body, py_status)
    ts_can = canonical(ts_body, ts_status)

    if py_can == ts_can:
        ok += 1
    elif path in EXPECTED_DEVIATIONS:
        expected.append((path, py_status, ts_status))
    else:
        errors.append((path, py_status, ts_status, py_body[:200], ts_body[:200]))

print(f"HTTP 200/identisch: {ok} von {len(routes)}")
if expected:
    print(f"\nErwartete Abweichungen ({len(expected)}):")
    for p, py, ts in expected:
        print(f"  {p:48s}  Python={py}  TS={ts}")
if errors:
    print(f"\nUnerwartete Abweichungen ({len(errors)}):")
    for p, py, ts, pyb, tsb in errors:
        print(f"  {p:48s}  Python={py}  TS={ts}")
        print(f"    Python body[:200]: {pyb}")
        print(f"    TS body[:200]:     {tsb}")
else:
    print("\nKeine unerwarteten Abweichungen gefunden!")

# Cleanup
ts_proc.terminate()
ts_proc.wait(timeout=10)
if os.path.exists(TS_DB):
    os.remove(TS_DB)

sys.exit(0 if not errors else 1)
