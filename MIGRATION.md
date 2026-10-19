# Portierung CraftBeerPi 3.0 auf Python 3 / Flask 3

Workflow und Notizen zur laufenden Portierung. Zustaendig: Position 1 abgeschlossen.

## Uebersicht

| Pos | Inhalt | Status | Aufwand |
|-----|---------|--------|---------|
| — | Route-Baseline einfrieren | **fertig** | erledigt |
| 1 | Python-3-Syntax und -Imports | **fertig** | erledigt |
| 2 | flask_classy -> eigenes Routing | **fertig** | erledigt |
| 3 | `app.json_encoder` -> JSONProvider | **fertig** | erledigt |
| 4 | Socket.io 5.x, eventlet raus | **fertig** | erledigt |
| 5 | RPi.GPIO -> rpi-lgpio | offen | 0,5 Tage |
| 6 | Async-Modell konsistent ziehen | offen | 0,5 Tage |
| 7 | Plugin-Loading, requirements, install.sh | offen | 0,5 Tage |
| 8 | Hardware-Test PID + 1-Wire | offen | 2–4 Tage |

## Das Route-Gate

Vor Position 2 ist die vollstaendige URL-Liste mit dem **echten** flask_classy 0.6.10
erfasst worden, nicht per Nachbau:

- `tools/routes_baseline.json` — 107 Routen / 107 Methoden
- `tools/snapshot_routes.py` — erzeugt `routes_current.json` aus der laufenden App
- `tools/compare_routes.py` — vergleicht gegen die Baseline, Exit 1 bei Abweichung

Ablauf bei jedem Umbau-Schritt:

```bash
python3 tools/snapshot_routes.py
python3 tools/compare_routes.py
python3 tools/test_api.py
python3 tools/test_json.py
python3 tools/test_socket.py
python3 tools/test_socket_e2e.py
```

`test_api.py` schickt 32 echte Requests gegen die laufende App und prueft
Statuscodes und Antworten. Notwendig, weil die Route-Liste identisch sein kann,
wahrend die Endpunkte trotzdem falsch dispatchen.

### Warum das Gate noetig ist

Der wahrscheinlichste Fehler beim Umbau auf `MethodView` ist das **Wegfallen der
Trailing-Slashes**. Flask 2 leitet `/api/actor` automatisch auf `/api/actor/` um,
Flask 3 nicht mehr. 26 der 107 Routen enden auf einem Slash:

```
/  /api/actor/  /api/beerxml/  /api/config/  /api/editor/
/api/editor/<name>/reload/  /api/fermenter/  /api/fermenter/check_step/
/api/kbh/  /api/kettle/  /api/logs/  /api/notification/
/api/recipe/import/v1/  /api/sensor/  /api/step/  /api/step/stop_step/
/api/system/doReboot/  /api/system/doShutdown/  /ui/
```

Sie entstehen in flask_classy aus zwei Regeln, die beim Umbaufachlich erhalten
bleiben muessen (flask_classy.py:118-135):

- `route()`-Dekorator: `rule` wird unveraendert uebernommen, Slash bleibt
- `get`/`post`/`put`/`delete`/`index`: `build_rule("/", ...)` ergibt
  `<base>/`, und der Slash wird **nur** entfernt, wenn `trailing_slash` falsch ist
  — flask_classy hat hier `trailing_slash = True` als Default (Zeile 51)

Methoden ohne Route-Dekorator bekommen `/<methodenname>`, ebenfalls mit Slash.

### flask_classy laeuft unter Flask 3 nicht

Zwei Importe fehlen, beide entfernt upstream:

- `werkzeug.routing.parse_rule` — entfernt in Werkzeug 2.3. Wird in flask_classy
  nur fuer `base_args` benutzt (Zeile 259-260).
- `inspect.getargspec` — entfernt in Python 3.11. Wird nur fuer die
  Argumentliste benutzt (Zeile 297-298).

`snapshot_routes.py` faellt beide Luecken in einem Shim, **nur wenn
flask_classy fehlt**. Seit Position 2 wird die Bibliothek nicht mehr
benoetigt, der Shim laeuft also ins Leere und kann mit Position 3 endgueltig
wegfallen.

## Position 2 — flask_classy raus

`flask_classy 0.6.10` (Release 01.04.2014) ist durch `modules/core/classy.py`
ersetzt, 190 Zeilen. Der Import wurde in allen 15 View-Dateien umgestellt,
`requirements.txt` wurde **noch nicht** angefasst (das ist Position 7).

### Warum kein Standard-MethodView

flask_classy routet nach **Methodennamen**, Flask routet nach **HTTP-Verb**.
Bei `/api/step/` wuerde ein Standard-MethodView kollidieren: `getAll` ist eine
GET-Route, aber es gibt dort auch `/api/step/reset` (POST) und
`/api/step/action/<method>` (POST). Die Nachbildung in `classy.py` dispatcht
deshalb weiter ueber den Methodennamen — das ist der Grund, warum die
107 Routen unveraendert bleiben.

### Drei Details, die beim Nachbauen entscheidend waren

Alle drei sind im Quelltext von flask_classy nachzuschlagen, nicht zu raten:

1. **Argumente werden nur im `else`-Zweig angehaengt.** `build_rule(rule)`
   bekommt im `@route`-Zweig (Zeile 106) und bei `get`/`post`/`put`/`delete`
   (Zeile 128) **kein** `method` uebergeben — Argumente werden also nicht
   angehaengt. Nur bei undekorierten Methoden (`flask_classy.py:137`) passiert
   das, daher `/api/step/init_step/<step>`. Ohne diese Unterscheidung wird aus
   `/api/config/<name>` das kaputte `/api/config/<id>/<id>`.

2. **Mehrfach dekorierte Methoden bekommen eigene Endpoints.**
   `StepView.start` traegt `@route('/next')` **und** `@route('/start')`; dafuer
   vergibt flask_classy `View:start_0` und `View:start_1` (Zeile 115-118).

3. **Geerbte `MethodView`-Methoden sind keine Routen.** `dispatch_request`,
   `methods` und `provide_automatic_options` muessen beim member-Scan
   uebersprungen werden, sonst entstehen Geisterrouten wie
   `/api/step/dispatch_request/`.

### Vorbestehende Fehler, die der Test aufgedeckt hat

Diese sind **nicht** durch den Umbau entstanden und in Python 2 ebenfalls
vorhanden. Flask 2 hat sie mit `TypeError` quittiert, seit Flask 2.2/3 ist das
Verhalten eindeutig. Sie sind in `test_api.py` als Vorbesteher markiert und
nicht behoben:

- `StepView.stop_step()` gibt keinen Response zurueck
  (`modules/steps/__init__.py:98-106`) — die Route `GET /api/step/stop_step/`
  kann nie antworten.
- `FermenterView.check_step()` ebenso (`modules/fermenter/__init__.py:263-287`).
  Die Methode ist eigentlich Background-Logik und sollte keine GET-Route sein.
- `LogView.actions()` gibt bei fehlender Logdatei `return` **ohne Wert**
  zurueck (`modules/logs/endpoints.py:22`), und oeffnet die Datei mit `'rb'`
  fuer den CSV-Parser (Zeile 25).

### Zusaetzlich gefixt

- `yaml.load()` ohne Loader wirft seit PyYAML 6 einen `TypeError`. Zwei Stellen:
  `system/endpoints.py:133` und `addon/endpoints.py:136` → jetzt `safe_load`.
- Das Gate wurde gehaertet: ein fehlgeschlagener oder leerer Snapshot meldet
  jetzt Fehler statt "OK" zu liefern. Zuvor hat es bei kaputtem `classy.py`
  ein gruenes Gate gegen veraltete Daten gezeigt.

## Position 1 — was geaendert wurde

59 Zeilen in 24 Dateien. Inhaltlich:

**Syntax** — 22 `print`-Statements, 8 `iteritems`, 1 `has_key`.

**Imports** — 12 implizite relative Imports, die unter Python 3
`ModuleNotFoundError` werfen, ohne dass es die Syntax-Pruefung bemerkt:
`from props import *` (core.py:15), `from hardware import *` (core.py:17),
`from db import get_db` (db_mirgrate.py:4), `import endpoints` (4x),
`import beerxml/kbh/restapi`, `from app_config import` (2x),
`from thread import start_new_thread`, `import urllib` (ungenutzt, entfernt).

**Laufzeitfehler, die erst der Starttest zeigte:**

1. **`async` als Parameter** (core.py:381) — reserviertes Keyword seit Python 3.7.
   Umbenannt in `async_`. **Breaking fuer externe Plugins:** Wer
   `@cbpi.event("X", async=True)` schreibt, muss auf `async_=` umstellen. Der
   dict-Key `"async"` bleibt bewusst String, damit `emit_event` weiter greift.

2. **`None >= int`** (db_mirgrate.py:7) — beim ersten Start ist `schema_info`
   leer, `max(version)` liefert `None`. Python 2 toleriert das, Python 3 wirft
   `TypeError`. **Ein frischer Start bricht ohne diesen Fix komplett ab.**

3. **`fo.write("")`** in eine mit `"wb"` geoeffnete Datei -> `b""`.

4. **`log_action`** schrieb `b'Bereich'` — die Bytes-Repraesentation landete in
   `logs/action.log`. Kein Crash, aber das Log wird unlesbar.

6. **`yaml.load()` ohne Loader** (Position 2, aufgefallen im Funktionstest) —
   zwei Stellen auf `safe_load` umgestellt.

5. **`print(f)`** in `system/endpoints.py` — reine Debug-Ausgabe beim Erzeugen
   des Swagger-Dokuments.

### Verifikation

Nicht nur geparst, sondern gestartet: alle Dateien unter Python 3.14, alle
Imports aufloesbar, und ein echter Startlauf bis zum Server-Bind — Datenbank
aufgebaut, 4 Actor-Typen, 2 Sensor-Typen, 5 Step-Typen, 5 Background-Tasks,
Event-Bus mit beiden Handlern, 107 Routen registriert.

### Offen aus Position 1

Die App startet, laeuft aber noch nicht. `flask.json.JSONEncoder` ist entfernt,
`socketio.run()` verlangt `allow_unsafe_werkzeug`. Das sind Position 3 und 4.

## Risiken, die ausserhalb des Kernels liegen

**Externe Plugins.** `modules/plugins/` war zur Laufzeit leer; echte Plugins
kommen per GitPython aus `modules/addon/endpoints.py`. Das einzige dort
tatsächlich vorhandene Plugin war `MQTTPlugin`, ein Python-2-Stand von 2018.
Es wurde nach Python 3 portiert und ist jetzt Kernbestandteil unter
`modules/base_plugins/mqtt` (mit `paho-mqtt` in `requirements.txt`). Weitere
über den Editor nachinstallierte Plugins bleiben das größte offene Risiko in
der Aufwandsschätzung — nicht der Kern.

**Integer-Division.** `target_temp`, `temp`, `height` stehen im Schema als
`INTEGER`. SQLite hat INTEGER-Affinitaet und speichert 66.5 als REAL, das faellt
kaum auf. Im Kern wurden keine Divisionsfehler gefunden, in Plugins aber moeglich.
## Position 3 — JSON-Serialisierung

`app.json_encoder` ist seit Flask 2.2 entfernt. Ersetzt durch
`ComplexJSONProvider` in `modules/app_config.py`, abgeleitet von
`DefaultJSONProvider`.

### Der entscheidende Punkt: App-Kontext

Die Serialisierung wird an zwei Stellen gebraucht, und nur eine davon
funktioniert mit `app.json`:

| Ort | Kontext | Funktioniert `app.json`? |
|---|---|---|
| REST (`json.dumps` in den Views) | Request-Kontext | ja |
| Socket.IO (`cbpi.emit`, core.py:220) | **ohne** Kontext, aus Background-Tasks | nein |

Empirisch geprueft, nicht geraten:

```
ausserhalb des App-Kontexts:  TypeError: Object of type Sensor is not JSON serializable
innerhalb des App-Kontexts:    {"config": null, "hide": 0, "id": 1, ...}
```

flask-socketio 5.x erkennt `json=flask_json` und ersetzt es durch einen
`FlaskSafeJSON`-Wrapper, der den App-Kontext erzwingt
(`flask_socketio/__init__.py:216-233`). Genau daran haengt der komplette
Live-Datenstrom. Faellt der `json=json`-Parameter in `app_config.py:50` weg,
faellt jede Temperaturmeldung. `test_json.py` prueft beide Weise getrennt.

### Was der alte Encoder verschluckt hat

Der ComplexEncoder aus Flask 0.12 gab fuer jeden unbekannten Typ
`return None` zurueck — im `else`-Zweig, ohne Meldung. Ein Vergleich des
alten und des neuen Serialisierers ueber den gesamten Cache ergibt
**36 Felder**, die vorher `null` waren:

- `actor_types`/`sensor_types`/`step_types`/`controller_types` → `class`
  (13 Plugin-Klassen)
- `background[].function` (5 Background-Tasks)
- `init[].function` (9 Initializer)
- `steps` (Cache-Callback)

Der Provider gibt stattdessen `{"name": ..., "module": ...}` zurueck. Fuer
den Cache-Callback gilt die Sonderregel: er wird ausgefuehrt, weil er mit
`callback = True` markiert ist (`core.py:231`).

Warum das nicht nur Kosmetik ist: `GET /api/system/dump` liefert genau diesen
Cache, und das Frontend laedt ihn beim Start (`load_state` → `LOAD_STATE`,
gefunden in `bundle.js`). Beim ersten Versuch mit striktem Provider lieferte
der Endpunkt **HTTP 500** — die UI waere ohne Daten gestartet.

Gegengeprueft, dass die Erweiterung additiv bleibt: das Bundle greift auf
**kein** `class`- oder `function`-Feld aus dem Dump zu. Top-Level-Schluessel
sind alt wie neu identisch, keine Schluessel gehen verloren.

### Nachgetragen: Test-Harness aufgeraeumt

`test_api.py` aktivierte previously eine provisorische ComplexEncoder-Variante,
weil der echte Encoder fehlte. Das ist jetzt ersatzlos weg — alle drei
Testskripte laufen ohne jeden Shim und benutzen den echten Code:

- `snapshot_routes.py` 107 Routen, Baseline identisch
- `test_api.py` 32 von 32
- `test_json.py` 13 von 13

Die beiden flask_classy-Shims (`parse_rule`, `getargspec`) sind ebenfalls
entfernt, seit Position 2 das Routing selbst uebernimmt.

## Position 4 — Socket.IO 5.x, eventlet raus

eventlet ist deprecated und nur noch im Bugfix-Modus. `async_mode="threading"`
ist gesetzt, weil der Server **keine** Socket-Events empfängt — der Socket ist
reiner Server→Client-Push (`core.py:219-220`). Damit entfällt der einzige
Grund, der für eventlet gesprochen hätte: kooperative Nebenläufigkeit zwischen
I/O-Warten.

Alle elf `socketio.*`-Aufrufstellen bleiben unverändert gültig:
`socketio.emit`, `socketio.sleep`, `socketio.start_background_task` sind in
5.7.0 vorhanden.

### Zwei Fallen, die den Betrieb komplett gebrochen hätten

**1. `run.py` startet nicht mehr.** Flask-SocketIO 5.x verweigert den
Werkzeug-Webserver, wenn kein TTY vorhanden ist (`__init__.py:660-670`):

```
RuntimeError: The Werkzeug web server is not designed to run in production.
```

`config/craftbeerpiboot` startet per `start-stop-daemon --background` — also
**ohne TTY**. Ohne `allow_unsafe_werkzeug=True` wäre der Dienst auf dem
Raspberry Pi nie hochgekommen. Gegenprobe bestätigt: mit stdin geschlossen und
ohne das Flag bricht `run.py` sofort mit Exit ≠ 0 ab.

**2. Namespace `/brew` wird abgelehnt.** python-socketio 5.x prüft jeden
Connect gegen eine Whitelist (`server.py:519-523`) und sendet sonst
`Unable to connect`. `/brew` hat im Projekt keinen Handler, weil der Socket
reiner Push ist — es hätte also gereicht, überall zu emittieren und trotzdem
kann sich kein Client verbinden.

Dabei ist die Liste eine **Ersetzung, keine Erweiterung**:

```python
self.namespaces = namespaces or ['/']     # base_server.py:65
```

Mit `namespaces=["/brew"]` wird auch der Default-Namespace `/` abgelehnt.
Beides muss genannt werden: `namespaces=["/", "/brew"]`.

Der Fehler war beim Testen sichtbar, nicht beim Lesen:

```
socketio.exceptions.ConnectionError: One or more namespaces failed to connect: /brew
```

### Verifikation

`test_socket_e2e.py` startet einen echten Server, verbindet einen echten
Client über WebSocket und wartet auf die Events. Damit ist der komplette Weg
belegt: Background-Task/Request → `cbpi.emit` → Namespace `/brew` →
Serialisierung ohne App-Kontext → Engine.IO 4 → WebSocket → Client.

9 von 9 Prüfungen bestanden, davon:

- `SENSOR_UPDATE` mit Messwert
- `NOTIFY`
- `UPDATE_ALL_STEPS`
- Transport ist WebSocket, nicht nur Long-Polling

Zusätzlich der Betriebsfall: `run.py` mit geschlossenem stdin gestartet,
Antwortet auf `/api/config/` (HTTP 200, 17 Konfigurationen) und auf
`/socket.io/?EIO=4` (HTTP 200, Prefix `0` — das Message-Format von Engine.IO 4
hat kein Äquivalent in Engine.IO 3).

Ein Client mit `EIO=3` wird abgelehnt. Das ist die erwartete Folge: das alte
`bundle.js` spricht das alte Protokoll, die Live-Anzeigen dort funktionieren
nicht mehr. Die REST-Schnittstelle ist davon nicht betroffen.

### requirements.txt

Neu:

```
Flask==3.1.3          PyYAML>=6.0
Flask-SocketIO==5.7.0 requests>=2.32
python-socketio==5.17.0    GitPython>=3.1
python-engineio==4.14.0     python-dateutil>=2.9
Werkzeug==3.1.9            simple-websocket>=1.1
```

Entfernt: `eventlet`, `greenlet`, `flask-classy`, `httplib2`,
`python-mimeparse`.

`simple-websocket` ist neu und nötig: im Modus `threading` stellt nur dieses
Paket den WebSocket-Transport bereit, sonst fallen die Verbindungen auf
Long-Polling zurück.

`RPi.GPIO` steht weiterhin nicht in der Liste — auf Bookworm nicht
verfügbar, das ist Position 5.
