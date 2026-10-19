# Portierung CraftBeerPi 3.0 auf Python 3 / Flask 3

Workflow und Notizen zur laufenden Portierung. Zustaendig: Position 1-4 abgeschlossen, Port nach Verlust am 19.10.2026 wiederhergestellt (siehe unten).

## Verlust und Wiederherstellung (2026-10-19)

Der Port war ueber mehrere Arbeitsstunden **uncommittet** und ist am
19.10.2026 durch einen `git reset` auf HEAD verloren gegangen. Ausloeser war
ein Endpunkt-Sweep ueber HTTP: `/api/system/tags/<x>` fuehrt ein echtes
`git checkout` aus, und der Sweep hat diesen Endpunkt mit aufgerufen. Der
`reflog` weist es aus:

```
2b095c8 HEAD@{0}: reset: moving to HEAD
```

Damit lagen 32 versionierte Dateien wieder im Auslieferungszustand — der
gesamte Port, darunter `core/controller.py`, `core/core.py`, `core/hardware.py`
und `core/step.py` mit Python-2-Syntax.

**Wiederherstellung.** Neu erarbeitet aus diesem Dokument, das als einzige
unversionierte Datei den Port überlebt hatte. Danach:

- Der überlebende, versionierte Ersatz `modules/core/classy.py` (Position 2)
  war unversehrt.
- `tools/` (Testsuite und Route-Baseline) und `craftbeerpi.db` waren unversehrt.
- `MIGRATION.md` selbst war unversehrt und diente als Spezifikation.
- Für fünf Kern-Dateien existierte noch der **portierte Bytecode** in
  `__pycache__` (18.10.2026). Ein Opcode-Vergleich gegen die Neuerstellung
  ergab für `hardware.py`, `controller.py`, `step.py`, `db_mirgrate.py` und
  `core.py` **semantische Identität** — die Rekonstruktion trifft den
  verlorenen Port also nicht nur ungefähr, sondern exakt.

**Lehre.** Der Port war über Tage uncommittet. Er hätte nach jeder Position
committet werden müssen; eine Versionierungskontrolle, die den Stand nur im
Arbeitsverzeichnis hält, ist kein Backup. Seit der Wiederherstellung liegt
alles in einem Commit (siehe `git log`).

**Zweiter Verlust (19.10.2026, 17:15).** Der Endpoint-Test der neuen UI
rief `GET /api/system/tags/3.0` auf und traf denselben Endpunkt erneut.
Der bis dahin eingebaute Schutz (Checkout nur bei sauberem Arbeitsbaum)
griff **nicht**: der Port war inzwischen committet, der Arbeitsbaum also
sauber, und der Endpunkt ließ den Checkout durch. `git reset --hard` +
`checkout 3.0` hat 56 Dateien auf den 2019er Stand zurückgesetzt. Der
Port war über `master` gerettet (der Branch-Zeiger blieb stehen), aber
der Arbeitsbaum sah kurzzeitig aus wie vor der Portierung.

Konsequenz (Commit `2b586bc`): Der Endpunkt prüft jetzt zusätzlich, ob
der Ziel-Tag den aktuellen HEAD **enthält**
(`git merge-base --is-ancestor HEAD <tag>`). Ein älterer Tag wird mit
HTTP 409 abgelehnt, und vor dem Checkout wird der aktuelle Stand als
Branch `backup/pre-tag-checkout` gesichert. `tools/test_system.py`
prüft beide Regeln.

**Lehre 2.** Ein Sweep über HTTP-Endpunkte ist ein Eingriff, keine Analyse.
`tools/sweep_endpoints.py` ruft heute nur noch lesende GET-Routen auf und
lässt Endpunkte mit Seiteneffekt explizit aus.

## Uebersicht

| Pos | Inhalt | Status | Aufwand |
|-----|---------|--------|---------|
| — | Route-Baseline einfrieren | **fertig** | erledigt |
| 1 | Python-3-Syntax und -Imports | **fertig** | erledingt |
| 2 | flask_classy -> eigenes Routing | **fertig** | erledigt |
| 3 | `app.json_encoder` -> JSONProvider | **fertig** | erledigt |
| 4 | Socket.io 5.x, eventlet raus | **fertig** | erledigt |
| 5 | RPi.GPIO -> rpi-lgpio | **fertig** | erledigt |
| 6 | Async-Modell konsistent ziehen | **fertig** | erledigt |
| 7 | Plugin-Loading, requirements, install.sh | **fertig** | erledigt |
| 8 | Hardware-Test PID + 1-Wire | offen | 2–4 Tage |

### Ergänzungen aus der Wiederherstellung

Über die ursprüngliche Spezifikation hinaus wurden vier Fehler gefunden und
behoben, die der Port ebenfalls mitgenommen hatte:

1. **JSON-Provider, unbekannte Typen.** Der Port hatte für alles Unbekannte
   ein `TypeError` eingebaut, obwohl der ComplexEncoder aus Flask 0.12 dort
   `return None` lieferte. Die Aufzählung der 36 Felder in "Was der alte
   Encoder verschluckt hat" beschreibt nur den *statischen* Cache-Inhalt.
   Zur Laufzeit entstehen weitere Instanzen — `Hysteresis` in
   `Kettle.instance`, `ChilStep` in `active_step`. Damit antworteten
   `/api/kettle/` und `/api/system/dump` mit **HTTP 500**, sobald ein Kessel
   benutzt wurde. Der None-Zweig ist wiederhergestellt.
2. **`logs/endpoints.py`**: CSV im Textmodus statt `'rb'` (der CSV-Parser
   verlangt in Python 3 Strings), `map()` als Liste (Python-3-`map` ist ein
   Iterator, den `json.dumps` nicht serialisieren kann), `download_name`
   statt des in Flask 2.2 entfernten `attachment_filename`.
3. **`tools/test_json.py`**: der Test prüfte den *ersten* Sensor der Datenbank
   und schlug fehl, sobald die Installation eigene Sensoren hatte. Er sucht
   jetzt den eigenen Test-Sensor und räumt ihn wieder auf.
4. **`tools/sweep_endpoints.py`**: neu, als lesender Sweep mit Ausschlussliste.

## Position 5 — RPi.GPIO -> rpi-lgpio

`RPi.GPIO` wird auf Raspberry Pi OS Bookworm nicht mehr gebaut: das Paket
nutzt `imp`-APIs, die es ab Python 3.12 nicht mehr gibt. Der Ersatz ist
`rpi-lgpio`, das ein drop-in kompatibles `RPi.GPIO` mitbringt (0.6 hat
`setmode`, `setup`, `output`, `input`, die Event-API und die `PWM`-Klasse
mit `ChangeDutyCycle`/`ChangeFrequency`).

Das Paket lässt sich **nur auf dem Pi** installieren (es braucht die
`lgpio`-C-Bibliothek). Deshalb steht es in `requirements.txt` auskommentiert
und wird in `install.sh` nur auf einem Pi nachinstalliert.

**Neu: `modules/core/gpio.py`** — eine Kompatibilitätsschicht. Sie lädt
`RPi.GPIO` (echt oder als Shim), sonst `rpi.lgpio`, sonst einen Stub.

Der Stub war nicht Kosmetik. Vorher stand in den Plugins:

```python
try:
    import RPi.GPIO as GPIO
except Exception:
    pass
```

Bei fehlendem GPIO war `GPIO` danach ein **undefinierter Name**. Die
Aktor-Typen wurden trotzdem registriert und im Frontend angezeigt; der
Fehler schlug erst in `init()` mit `NameError: name 'GPIO' is not defined`
zu — ohne jeden Hinweis, dass die Hardware fehlt. Der Stub liefert statt
dessen einen `RuntimeError` mit Klartext.

Dazu zwei echte Fehler in `gpio_actor`:

- **`GPIOPWM`**: fehlt „frequency" in der Konfiguration, ist `self.frequency`
  die Property-Instanz und keine Zahl. `float()` darauf wirft `TypeError`.
- **`init_actor`** in `core.py` hat die Ausnahme geschluckt und nur
  „Initializing of Actor X failed" protokolliert. Ohne die Ausnahme lässt
  sich ein Konfigurationsfehler nicht von fehlender Hardware unterscheiden.

## Position 6 — Async-Modell und System-Endpunkte

Drei Befunde, alle mit demselben Muster: ein Endpunkt mit Seiteneffekt,
der über HTTP aufgerufen wird.

**1. Herunterfahren und Neustart blockierten den Request.** `doShutdown()`
lief im Request-Thread, schlief 5 Sekunden, rief dann `halt` auf — und
erst danach kam `return ('', 204)`. Die Antwort kam nie an, weil der
Rechner vorher schon ausging; der Browser sah einen Timeout. Außerdem
wurde `call("halt")` mit einem **String** aufgerufen: auf POSIX sucht
`subprocess` dann ein Programm namens „halt" im PATH, und „halt" ist ein
`systemctl`-Unterbefehl, kein Programm. Der Befehl läuft jetzt als
Hintergrundtask, die Liste wird als Liste übergeben.

**2. `GET /api/system/tags/<name>` war die Ursache des Datenverlusts.**

```python
repo.git.reset('--hard')      # verwirft ALLE uncommitteten Änderungen
g.checkout(name)
```

Ein GET darf keine Seiteneffekte haben, und ein versehentliches Aufrufen
(Browser-Prefetch, Link im Chat, ein Test-Sweep) hat so den kompletten Port
vernichtet. Der Endpunkt prüft jetzt:

1. Der Name muss einem existierenden Tag entsprechen (sonst 404).
2. Ist der Arbeitsbaum schmutzig, wird der Checkout **verweigert** (409).
   Das `reset --hard` passiert nur bei sauberem Baum — dann ist es ein No-Op.

Das Frontend ruft den Endpunkt per GET auf (`bundle.js`), deshalb bleibt
das Verb unverändert. Zusätzlich abgesichert ist `tools/sweep_endpoints.py`,
das Endpunkte mit Seiteneffekt gar nicht erst aufruft.

**3. `one_wire`** benutzte als einziges Plugin einen rohen
`threading.Thread` (ohne `daemon`) und ein blankes `except`. Der Offset war
dieselbe Property-Falle wie bei `GPIOPWM`: fehlte „offset" in der
Konfiguration, lieferte `float(self.offset)` einen `TypeError`, den der
`try_catch` mit 0 quittierte — der eingestellte Offset wurde also ignoriert
und der Log lief alle fünf Sekunden voll.

## Position 7 — Plugin-Loading, requirements, install.sh

**Path-Traversal im Plugin-Management.** Die Routen `/api/editor/<name>`
nahmen den Namen ungeprüft aus dem Pfad:

```
DELETE /api/editor/../../logs
```

`deletePlugin` macht ein `shutil.rmtree` — damit ließ sich **jedes
Verzeichnis löschen**, auf das der Prozess zugreifen konnte. Der Server
bindet an `0.0.0.0`, ist also im LAN erreichbar. Empirisch belegt: der
Name `../../logs` normiert auf `logs` und liegt damit außerhalb von
`modules/plugins`.

Jetzt gilt `_plugin_pfad()`: der Name muss dem Muster
`^[A-Za-z0-9][A-Za-z0-9_.-]*$` entsprechen, höchstens 100 Zeichen lang
sein, und der aufgelöste Pfad muss in `modules/plugins` liegen. Betroffen
sind `getFile`, `createPlugin`, `saveFile`, `deletePlugin`, `reload_plugin`,
`download_addon` und `update_addon`. Über HTTP greift zusätzlich das
Routing (Werkzeug normalisiert `..` und antwortet 404) — die View-Prüfung
ist die zweite Schicht.

**`__pycache__` als installiertes Plugin.** `__pycache__` ist selbst ein
Verzeichnis und damit vom Datei-Filter (`endswith(".py")`) nicht
erreichbar. Es erschien in `/api/editor/` als installiertes Plugin und
ließ sich als Namespace-Paket sogar ohne Fehler importieren — im
Modul-Register stand also Müll.

**`reload` war dreifach kaputt:** `cache` war nie definiert (NameError),
`reload` ist in Python 3 kein Builtin mehr (NameError), und `e.message`
gibt es seit Python 3.0 nicht mehr (AttributeError). Der Endpunkt lieferte
also immer HTTP 500.

**`download_addon`:** die `None`-Prüfung stand *hinter* dem Zugriff
(`plugin["loading"] = True`), ein unbekannter Name lief in einen TypeError
statt in die 404.

**Die SQL-Migrationen liefen in der falschen Reihenfolge.** Das war der
Fehler, der auf einer frischen Installation auffiel:

```python
for filename in os.listdir("./update"):   # Dateisystem-Reihenfolge!
```

`os.listdir()` liefert die Einträge in der Reihenfolge des Dateisystems,
nicht numerisch. Auf einer frischen Installation kam so
`3_port_config.sql` vor `1_schema_info.sql` — die erste Datei wollte in
`schema_info` eintragen, obwohl die Tabelle noch nicht existierte. Der
Fehler ließ die **ganze Datei** zurückrollen, und damit auch den
`port`-Eintrag und die erweiterten Buzzer-Optionen. `schema_info` stand
danach auf Version 1, die Dateien wurden erst beim nächsten Start
nachgezogen.

Die Fehler wurden mit `print()` auf stdout geschrieben, nicht ins Log — in
`logs/app.log` stand nichts, nur „EXCEPT" auf der Konsole.

Die Dateien werden jetzt nach ihrer Versionsnummer sortiert, die
Migrationslogik nutzt dieselbe Datenbankverbindung wie der Rest, und
Fehler gehen ins Log. `tools/test_migration.py` prüft den ganzen Ablauf:
frische Installation, zweiter Start, Upgrade mit neuer Datei, kaputte Datei.

**`install.sh` war Python 2:**

```
apt-get install python-setuptools; easy_install pip;
apt-get install python-dev; pip install -r requirements.txt
```

`easy_install` gibt es unter Python 3 nicht mehr, und `python-dev` sind
die Header von Python 2 (Python 3 braucht `python3-dev`). Zudem landete
alles im System-Python — unter Bookworm schlägt das ohnehin an PEP 668
fehl. `install.sh` legt jetzt ein `virtualenv` an, und das Init-Skript
startet `run.py` mit dem venv-Python statt mit dem System-Python. Vorher
lief der Dienst mit einem Interpreter, in dem die Pakete nicht lagen.

### Ergänzung aus Position 6/7

`emit_message` akzeptiert jetzt auch einen einfachen Text. Fünf
Aufrufstellen im Plugin-Management übergeben nur einen String, der
Handler in `modules/notification` erwartet aber ein Dictionary mit
`timeout` — mit einem String starb er mit `TypeError: string indices must
be integers`, und die Benachrichtigung kam **nie** an. Das war schon in
Python 2 so.

## Uebernahme der Plugin-Updates

Acht Plugin-Updates lagen unter `cbpi3UIng/plugin_update/`. Sie waren zum
Zeitpunkt des Uebernahmens gegen den Python-2-Kern geschrieben. Sie wurden
 einzeln analysiert und nach ihrer Wirkung eingeordnet:

| Plugin | Entscheidung | Umsetzung |
|---|---|---|
| `BoilStepResetFix` | Kern | `base_plugins/brew_steps`: reset() reariert die Hop-Flags, `hop_1_name`..`hop_5_name` ergaenzt, Alert nennt den Namen |
| `FermenterAutoModeStateFix` | Kern | `modules/fermenter/__init__.py`: toggle() korrigiert, State-Flag nur noch von dem cleared, der auch gestoppt hat |
| `NotificationTimestamp` | Kern | `core/core.py`: Zeitstempel in emit_message; `notification/__init__.py`: NOTIFY_DISMISS beim Löschen |
| `BoilingPointAltitude` | Kern | `config/schema.sql`: Config-Parameter `altitude` (Typ number) |
| `BackendRestart` | Kern | neues Modul `modules/restart/`: `GET`/`POST /api/restart`, Config-Parameter `plugins_changed` und `backend_started_at` |
| `RecipeUuidFromBeerXml` | Kern | `config/schema.sql`: Config-Parameter `brew_recipe_uuid`. Der BeerXML-Patch ist entfallen - die UI setzt den Wert selbst |
| `AdvancedPIDAutoTune` | Plugin | unveraendert in `modules/plugins/` |
| `HopNamesFromRecipe` | entfaellt | ueberholt, die UI schreibt `hop_N_name` selbst |

### Warum nicht als Plugins behalten

Die drei Kern-Bugs, die die Plugins umgingen, sind im Kern selbst
repariert. Als Plugin haetten sie zwei Nachteile:

- **Eine Kopie des Core-BoilStep** driftet bei jedem Core-Update. Im Kern
  ist der Fix Teil der Implementierung und kann nicht auseinanderlaufen.
- **Runtime-Patches auf View-Methoden** sind im portierten Core nicht mehr
  noetig: `flask_classy` band die Methode beim Registrieren der View
  ("ein spaeterer Wechsel des Klassenattributs bliebe wirkungslos"). Der
  Ersatz in `modules/core/classy.py` loest die Methode erst beim Aufruf
  auf - der Patch-Mechanismus der Plugins ist also ueberfluessig.

### Zwei Abweichungen von der Plugin-Fassung

1. **`hop_label` faellt auch bei einer Zahl im Namensfeld zurueck.** Die
   Plugin-Fassung lehnte nur Nicht-Strings ab; der String "42" kam als
   Name durch. Die Doku des Plugins beschrieb aber genau das Gegenteil
   ("eine Zahl im Feld ist ueberhaupt kein Name, sondern ein verirrter
   Config-Wert"). Der Kern folgt der Doku.
2. **Die Config-Parameter liegen in `config/schema.sql`**, nicht in einem
   eigenen Plugin. Sie sind reine Konfiguration wie `brewery_name` und
   `unit`, und `INSERT OR IGNORE` wirkt auch auf bestehende Installationen.

### Dabei gefundener Kern-Bug: `set_config_parameter`

`CraftBeerPi.set_config_parameter()` hat `Config.update()` nur `name` und
`value` uebergeben. `update()` schreibt aber **alle** Spalten der
config-Tabelle, und was nicht uebergeben wird, kommt als NULL herein:

```python
update_data = {"name": name, "value": value}
c = Config.update(**update_data)          # type, description, options -> NULL
```

Im Cache blieb das verborgen - dort wurde nur `name`/`value` aktualisiert.
In der Datenbank nicht. Nach dem naechsten Start war der Parameter ohne
Typ wieder da, und die UI rendert ihn als Textfeld statt als Auswahl-
oder Zahlenfeld.

Betroffen war unter anderem `brew_name`, das beim **Rezeptimport** auf
diesen Weg gesetzt wird - der Typ ging also bei jedem Rezeptimport
verloren. Die Korrektur uebergibt das vollstaendige Dict des Parameters.
`update/4_config_parameter_types.sql` repariert die bereits beschaedigten
Zeilen.

### Zwei weitere Befunde beim Uebernahmen

- **`BackendRestart` als Kernel-Modul** statt Blueprint im Plugin: es
  ergaenzt die System-Endpunkte, die mit `reboot` und `shutdown` schon im
  Kern liegen. Die Route bleibt `/api/restart`, weil die UI sie so
  aufruft.
- **`hops_changed`/`backend_started_at`**: der Neustart-Thread raeumt die
  Aenderungsliste **vor** dem `execv` - die Liste bedeutet "geaendert seit
  dem Start des laufenden Backends", und nach dem Neustart ist das neue
  Backend das, wogegen alles andere verglichen wird.

## Befund aus dem Server-Log: 500 statt 404 bei unbekannter Id

Am 19.10.2026 um 17:35 schickte die Oberflaeche (192.168.0.193) fuenfmal
`PUT` und `DELETE` auf Objekte, die es im Backend nicht (mehr) gab:

```
PUT    /api/fermenter/1  -> 500  KeyError: 1   (3x)
DELETE /api/fermenter/1  -> 500  KeyError: 1   (2x)
DELETE /api/sensor/2     -> 500  KeyError: 2   (2x)
```

Ursache war nicht der Port, sondern der Original-Kern: `BaseView.put`
und `BaseView.delete` griffen mit `self.cache[id]` direkt auf den Cache
zu, ohne zu pruefen, ob es die Id ueberhaupt gibt. Ein Client mit
veraltetem Zustand - die Oberflaeche hatte einen Fermenter im State, den
das Backend schon nicht mehr hatte - bekam einen **500er mit
Stacktrace** statt einer sauberen Antwort.

`modules/core/baseview.py` hat jetzt `_hole_eintrag()`: fehlt die Id im
Cache, wird die Datenbank gefragt (und der Cache nachgetragen, falls er
der aeltere Teil ist), und liegt sie auch dort nicht, antworten PUT und
DELETE mit **404**. Das betrifft alle Views, die von `BaseView` erben:
Sensor, Actor, Kettle, Step, Fermenter und Config.

Die Log-Ausgabe selbst hat einen Nebeneffekt, den man kennen sollte:
**alle Prozesse, die `modules` importieren, schreiben in dieselbe
`logs/app.log`** - das `logging.basicConfig(filename='./logs/app.log')` in
`modules/app_config.py`. Testlaeufe und der Server teilen sich die Datei.
Fehler aus einem Test sind im Log also nicht von einem Serverfehler zu
unterscheiden, ausser an der Quell-IP der Requests.

## Testwerkzeuge

| Skript | Prüft | Anzahl |
|---|---|---|
| `snapshot_routes.py` | erzeugt `routes_current.json` | 107 Routen |
| `compare_routes.py` | Routenliste gegen die Baseline | 107/107 |
| `test_api.py` | REST-Aufrufe | 32/32 |
| `test_json.py` | Serialisierung | 16/16 |
| `test_socket.py` | Socket.IO-Details | 21/21 |
| `test_socket_e2e.py` | Live-Datenstrom mit echtem WebSocket | 9/9 |
| `sweep_endpoints.py` | alle GET-Routen, nur lesend | 0 unerwartete |
| `test_gpio.py` | GPIO-Schicht | 34/34 |
| `test_system.py` | System-Endpunkte, Checkout-Schutz | 14/14 |
| `test_plugins.py` | Plugin-Management, Traversal | 42/42 |
| `test_migration.py` | SQL-Migrationen, Frischinstallation | 13/13 |
| `test_kern_uebernahmen.py` | die aus den Plugin-Updates uebernommenen Funktionen | 43/43 |
| `test_unbekannte_id.py` | PUT/DELETE auf eine unbekannte Id | 21/21 |

Alle Skripte liefern bei Abweichung einen Exit-Code ungleich 0 und eignen
sich damit als Gate. `test_migration.py` arbeitet in einem eigenen
Verzeichnis und fasst die echte Datenbank nicht an.

Position 7 ist als "teilweise" markiert, weil `requirements.txt` und das
MQTT-Plugin jetzt stimmen, `install.sh` aber noch nicht geprüft ist.

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
