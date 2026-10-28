# Backend-Rewrite in TypeScript

**Status:** Entscheidung steht — Variante **A, Big-Bang**, Plugin-System
bewusst noch **offen** (siehe Abschnitt 9).

**Stand:** **M1 umgesetzt, M2a begonnen** (`backend-ts/`, 35 von 110
Routen). Der Router, SQLite samt Migrationen, Config, Notification,
`/api/system/*`, die `BaseView`-Maschinerie, das `step`-Modul (14 Routen)
und `logs` (8 Routen) laufen. `GET /api/config/` und `GET /api/step/`
sind byte-identisch zur Python-Antwort aus derselben Datenbank, ebenso
`/api/logs/actions` auf der echten `action.log`. Die Python-Seite ist
unverändert.

Dieses Dokument ist der Arbeitsplan. Es beschreibt, was gebaut wird, in
welcher Reihenfolge, woran jeder Schritt gemessen wird und welche
bewussten Abweichungen es zum Python-Backend gibt. Das Gerüst liegt in
[`backend-ts/`](backend-ts/README.md); die Python-Seite bleibt unverändert
lauffähig, bis der Schnitt in M6 stattfindet.

---

## 1. Ziel und Nicht-Ziele

**Ziel**

- Ein Backend in TypeScript, das die **110 Routen** aus
  `tools/routes_baseline.json` vollständig und mit identischem Verhalten
  bedient.
- Socket.IO mit den Namespaces `/` und `/brew` und denselben 12 Events.
- Das Plugin-System wird in TypeScript fortgeführt (Laufzeitmodell in
  Abschnitt 9 festgelegt).
- Bestehende `craftbeerpi.db` und `update/*.sql` bleiben gültig.
- Beide Oberflächen (`/ui` und die externe `cbpi3-ui`) laufen ohne
  Änderung weiter.

**Nicht-Ziele**

- Kein Umbau der REST-Semantik, keine „schöneren" URLs, keine
  API-Versionierung. Das Frontend ist der Vertrag.
- Kein Datenbank-Redesign, kein ORM-Umzug.
- Kein Umbau der Oberfläche.
- Keine neuen Features während der Portierung.

---

## 2. Leitplanken

Diese fünf Regeln entscheiden über Erfolg oder Misserfolg. Sie sind
teurer als jede Framework-Wahl.

1. **Die Route-Baseline ist die Spezifikation.** `tools/routes_baseline.json`
   wird nicht angepasst, sondern abgearbeitet. Ausnahmen brauchen einen
   Eintrag in Abschnitt 8.
2. **Golden Fixtures vor dem Schnitt.** Solange Python noch läuft, werden
   für alle lesenden Endpunkte echte Antworten als Fixtures abgelegt
   (`backend-ts/fixtures/`). Der TS-Stand muss sie byte-gleich liefern —
   nicht „ähnlich".
3. **`craftbeerpi.db` ist heilig.** Tests arbeiten auf einer Kopie in
   `CBPI_DB`; die echte Datei wird nur gelesen.
4. **Ein Bereich, ein Gate.** Kein Bereich gilt als fertig, bevor die
   zugehörigen Python-Tests gegen TS laufen.
5. **Abweichungen werden benannt, nicht versteckt.** Alles, was anders
   ist, steht in Abschnitt 8 und hat einen Test.

---

## 3. Architektur

```
┌──────────────────────────────────────────────────────────────┐
│ Node 22+ / ESM                                                │
│                                                               │
│  http.Server ──┬── Router (Flask-kompatibel)                  │
│                │      ├── /api/*      Domain-Module            │
│                │      ├── /ui/*       statisch (altes UI)      │
│                │      └── /static/*                            │
│                │                                               │
│                └── socket.io  (/, /brew)                       │
│                                                               │
│  Core:  Db (better-sqlite3) · Cache · EventBus · Background   │
│  Plugins: PluginHost (Vertrag fix, Laufzeit offen)            │
└──────────────────────────────────────────────────────────────┘
```

**Warum ein eigener Router und nicht Fastify/Express?**
Weil Parität hier wichtiger ist als Routing-Komfort. Flask-Regeln sind
nicht REST-üblich:

- `/api/step/` und `/api/step` sind verschiedene Dinge
  (Trailing-Slash-Redirect nur in eine Richtung),
- `<int:id>` matcht `\d+`, nicht „irgendein Segment",
- statische Regeln gewinnen gegen dynamische (`/api/logs/actions` vor
  `/api/logs/<file>`),
- Methoden werden pro Regel geprüft, nicht pro Pfad.

Ein 180-Zeilen-Matcher bildet das exakt ab. Fastify obendrauf zu setzen
hieße, dessen Routing zu verbiegen. Das Python-Backend macht aus
demselben Grund einen eigenen `classy`-Ersatz.

**Warum `better-sqlite3`?**
Synchron, ein Prozess, dieselbe Datei, kein Connection-Pool, keine
Transaktionsüberraschungen. Auf einem Pi ist die Performance irrelevant,
die Vorhersagbarkeit nicht.

**Warum kein ORM?**
`DBModel` ist 130 Zeilen. Ein ORM würde das Schema neu interpretieren und
die Kompatibilität zur bestehenden Datenbank gefährden.

---

## 4. Verzeichnislayout

```
backend-ts/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.ts              # Boot: DB, Cache, Router, Socket, Listen
│   ├── env.ts                # CBPI_PORT / CBPI_LOG_LEVEL / CBPI_LOG_STDOUT
│   ├── logger.ts             # gleiches Format wie Python (logs/app.log)
│   ├── db.ts                 # Verbindung, Schema, Migrationen, Table
│   ├── json.ts               # kanonisches JSON (sortiert, ASCII)
│   ├── socket.ts             # socket.io, Namespace /brew
│   ├── core/
│   │   ├── cache.ts          # cbpi.cache
│   │   ├── events.ts         # EventBus (MESSAGE, SET_TARGET_TEMP, …)
│   │   └── api.ts            # CraftBeerPi-Fassade (emit, notify, config)
│   ├── http/
│   │   ├── router.ts         # Flask-kompatibler Matcher
│   │   ├── respond.ts        # Response, json(), text(), noContent()
│   │   ├── static.ts         # /ui und /static
│   │   └── routes/           # ein Modul pro Bereich
│   ├── modules/              # Domain: actor, sensor, kettle, step, …
│   └── plugins/
│       ├── contract.ts       # Plugin-Vertrag (Laufzeit offen)
│       └── host.ts           # Discovery; Ausführung folgt in M5
├── test/                     # node:test
└── fixtures/                 # Golden Responses aus der Python-Phase
```

---

## 5. Meilensteine

Jeder Meilenstein hat ein **Gate**: die Bedingung, ohne die der nächste
nicht beginnt.

### M0 — Gerüst (abgeschlossen)

- Router, DB, Cache, EventBus, Socket, Logger, statische Auslieferung.
- Referenzmodul: `config` (vollständig) und `notification` (vollständig).
- Route-Registry mit Abgleich gegen die Baseline.
- Tests: Router-Semantik, JSON-Kanonik, DB-Roundtrip, Route-Subset.

**Gate:** `npm test` grün; Server startet gegen eine Kopie der echten DB;
`GET /api/config/` liefert denselben Inhalt wie Python. — **erfüllt.**

### M1 — Kern (abgeschlossen bis auf Plugin-Ausführung)

- `Table`/`DBModel`-Vollständigkeit: JSON-Felder, `order_by`, `as_array`
  und Projektion auf die deklarierten Felder (wie `DBModel.__init__`).
- `BaseView` mit Hooks, Cache-Init und dem Nachladen aus `_get_entry`.
- JSON-Provider-Äquivalent: `CacheCallback`, Klassen/Funktionen,
  `__json__`/`toJSON`, `null` für Unbekanntes, Zyklen.
- Erstes Domain-Modul: `step` (CRUD, `sort`, `reset`, `start`/`next`,
  `stop_step`, `action`, `init_step`, Dump-Callback).

Noch offen und deshalb in M2/M5: die Ausführung eines Schritts über
`step_types` und damit `init_step`, `action` und `reset/current` als
echte Operationen. Die Routen, Zustände und Events sind vorhanden; die
Plugin-Instanz fehlt (siehe D-9).

**Gate:** `test_json.py` und der Step-Teil von `test_api.py` als
TS-Tests portiert und grün. — **erfüllt** (68 Tests).

### M2 — Domain

Reihenfolge nach Risiko, nicht nach Alphabet:

1. `actor`, `sensor` (Hardware-API, Backgroundtasks) — **blockiert durch
   die Plugin-Entscheidung** (Abschnitt 9)
2. `kettle` (Controller-Lebenszyklus) — `steps` ist mit M1 fertig
3. `fermenter` (Steps, Automatik, Sortierung)
4. `logs` (fertig), `system` (Rest), `restart`, `editor`,
   `recipe_import` (`beerxml`, `kbh`) — ohne Plugins machbar (M2a)

**Gate:** `sweep_endpoints.py` (nur lesend) läuft gegen TS durch, plus
`test_unbekannte_id.py`, `test_fermenter_step_order.py`,
`test_step_reset.py`.

### M3 — Socket.IO

- Namespace `/brew`, 12 Events, gleiche Payloads.
- `MESSAGE` → `NOTIFY`-Kette inkl. persistentem Cache.
- Verbindungsverhalten (Polling, Upgrades, CORS) dokumentiert.

**Gate:** `test_socket.py` und `test_socket_e2e.py` grün gegen TS.

### M4 — Hardware

- GPIO (Pi), 1-Wire (`/sys/bus/w1`), MQTT (`mqtt.js`), Buzzer.
- Auf Nicht-Pi-Systemen: sauberer Stub mit derselben Log-Meldung.

**Gate:** `test_gpio.py`, `test_mqtt_config.py`, `test_telegram_plugin.py`
(soweit nicht plugin-abhängig) grün.

### M5 — Plugin-System

- Laufzeitmodell nach Entscheidung aus Abschnitt 9.
- Portierung von 7 Base-Plugins und 4 mitgelieferten Plugins.
- Editor-API (`/api/editor/*`) inkl. Pfadprüfung, Download, Reload.

**Gate:** `test_plugins.py`, `test_plugin_properties.py`, Plugin-Editor
Roundtrip (anlegen, speichern, neu laden, löschen).

### M6 — Schnitt

- Golden-Fixture-Vergleich über alle lesenden Routen.
- Parallellauf beider Backends auf getrennten Ports, Diff der Antworten.
- Umschalten des Dienstes, Python bleibt als Branch/Tag erreichbar.

**Gate:** alle Tests grün, keine Fixture-Abweichung, ein echter Brautag
auf dem Pi.

---

## 6. Paritätsstrategie

### 6.1 Routen

Die Registry ist Code (`src/http/routes/*`), die Baseline ist der Test.
`test/routes.test.ts` prüft in drei Stufen:

1. **Teilmenge:** jede implementierte Route existiert in der Baseline
   (kein erfundenes `/api/...`).
2. **Eindeutigkeit:** kein Duplikat aus Methode + Regel.
3. **Vollständigkeit:** ab M2 exakt 110 Einträge, per `CBPI_STRICT_ROUTES=1`.

Die Regelstrings werden **wörtlich** übernommen (`<int:id>`,
`<path:filename>`), damit ein Diff der Baseline lesbar bleibt.

### 6.2 Antworten

Vor dem Schnitt erzeugt ein Capture-Lauf Fixtures:

```
GET /api/config/            → fixtures/get_api_config.json
GET /api/actor/             → fixtures/get_api_actor.json
GET /api/system/dump        → fixtures/get_api_system_dump.json
…
```

Fixtures werden **kanonisch** verglichen: Schlüssel sortiert, UTF-8 als
ASCII-Escapes, Zahlen ohne Formatabweichung. Genau so serialisiert das
Python-Backend (Flask `DefaultJSONProvider` mit `sort_keys=True`).
Wichtig sind dabei auch die Separatoren `", "` und `": "`: `json.dumps`
schreibt sie mit Leerzeichen, `JSON.stringify` nicht. `src/json.ts`
bildet das nach — der M0-Test gegen die echte Datenbank war damit
byte-identisch.

### 6.3 Fehlercodes

Die Testmatrix aus `tools/test_api.py` wird 1:1 portiert. Besonders:

| Fall | Erwartung |
|---|---|
| unbekannte Id bei `GET`/`PUT`/`DELETE` | 404, kein 500 |
| `GET /api/config/<id>` | 400 `NOT SUPPORTED` |
| `POST /api/config/` | 400 `NOT SUPPORTED` |
| Restart bei laufendem Schritt | 409 |
| `GET /api/actor/<int:id>` mit `abc` | 404 (Konverter) |
| `/api/step` ohne Slash | 308 auf `/api/step/` |

---

## 7. Socket-Vertrag

| Namespace | Richtung | Events |
|---|---|---|
| `/brew` | Server → Client | `SENSOR_UPDATE`, `SWITCH_ACTOR`, `UPDATE_KETTLE`, `UPDATE_KETTLE_TARGET_TEMP`, `UPDATE_FERMENTER`, `UPDATE_FERMENTER_TARGET_TEMP`, `UPDATE_FERMENTER_BREWNAME`, `UPDATE_ALL_STEPS`, `UPDATE_CONFIG`, `NOTIFY`, `NOTIFY_DISMISS`, `RESTART_SCHEDULED` |

- Keine Client→Server-Handler. Der Socket ist reiner Push.
- `MESSAGE` ist **kein** Socket-Event, sondern der interne Eventbus, der
  `NOTIFY` erzeugt (und persistente Nachrichten in `cache.messages` legt).
- `io.of('/brew')` muss ohne registrierten Handler erreichbar sein.
- CORS offen (`origin: '*'`), wie im Python-Backend — das Backend bindet
  nur im LAN.

---

## 8. Bewusste Abweichungen

Diese Punkte werden **nicht** 1:1 übernommen. Jeder bekommt einen Test
und, wo sinnvoll, einen Hinweis in `BUGS.md`.

| Nr. | Abweichung | Grund |
|---|---|---|
| D-1 | JSON-Antworten mit `Content-Type: application/json` statt `text/html; charset=utf-8` | Flask liefert bei `return json.dumps(...)` versehentlich HTML. Kein bekannter Client prüft das; `res.json()` ignoriert es. |
| D-2 | `Table.update()` schreibt nur übergebene Spalten | Behebt B-08 (nicht übergebene Spalten wurden `NULL`). `BaseView.put()` übergibt ohnehin das vollständige Objekt. |
| D-3 | `GET /api/system/endpoints` verändert die Routentabelle nicht | Behebt B-01 (HEAD/OPTIONS wurden aus der globalen Map entfernt). |
| D-4 | Restart wechselt die PID (`spawn` + `exit` statt `execv`) | Node kennt kein `execv`. Der Dienst wird über Supervisor/systemd neu gestartet; `start-stop-daemon`-PID-Datei braucht einen Wrapper. Wird in M2 entschieden und dokumentiert. |
| D-5 | Unbekannte Typen im Cache werden `null` (wie bisher), aber mit Debug-Log | Gleiches Verhalten, bessere Diagnose. |
| D-6 | Plugin-Laufzeit ist in M0–M4 deaktiviert (Discovery ja, Ausführung nein) | Entscheidung in Abschnitt 9 offen; der Vertrag steht trotzdem fest. |
| D-7 | Migrationsfehler brechen den Start ab, statt übersprungen zu werden | Behebt B-04. Eine halb angewendete Migration ist schlimmer als ein lauter Start. |
| D-8 | Unbekannter Config-Parameter bei `PUT` ist 400, nicht 500 | Der Kern läuft in einen `KeyError`; das ist ein Client-Fehler. |
| D-9 | `POST /api/step/action/<method>`, `GET /api/step/init_step/<step>` und `POST /api/step/reset/current` sind bis M5 No-ops; `GET /api/step/stop_step/` antwortet 204 statt 500 | Ohne registrierte `step_types` gibt es keine Schritt-Instanz. Python würde bei `action`/`reset/current` mit `AttributeError` (500) scheitern, bei `init_step` einen String als Schritt interpretieren und bei `stop_step` ohne `return` einen `TypeError` (500) auslösen. Zustände, Routen und Events bleiben unverändert. |
| D-10 | `PUT` einer unbekannten Id ist auch ohne Cache (StepView) 404 | Python schreibt nichts und gibt trotzdem das eingesendete Modell mit 200 zurück. Der Cache-Zweig liefert dort bereits 404; beide Wege verhalten sich jetzt gleich. |
| D-11 | `GET /api/logs/convert_chart_data_to_json/<chart_data>` ist 400, nicht 500 | Der Pfadparameter ist immer ein String; Python behandelt ihn wie ein dict und scheitert garantiert mit `TypeError`. Ein klarer Client-Fehler ist ehrlicher als ein 500er. Die Auto-Route bleibt bestehen, weil sie in der Baseline steht. |

---

## 9. Plugin-System — Vertrag jetzt, Laufzeit später

Die Entscheidung ist vertagt, die **Schnittstelle** nicht. `src/plugins/contract.ts`
definiert bereits alles, was ein Plugin liefern muss; die vier möglichen
Laufzeiten (P1 Decorator, P2 Manifest, P3 Worker, P4 Python-Bridge)
füllen nur noch `PluginHost` aus.

```ts
interface PluginManifest {
  kind: 'actor' | 'sensor' | 'controller' | 'fermentation_controller' | 'step'
  name: string
  properties: PropertyDescriptor[]
  actions?: { method: string; label: string }[]
  create(api: PluginApi, config: Record<string, unknown>): PluginInstance
}
```

Damit ist M5 unabhängig von der Entscheidung vorbereitet, und die
Property-Introspektion (das, was `/api/system/dump` und die
Konfigurationsdialoge speist) hat schon jetzt eine feste Form.

**Was die Entscheidung beeinflusst:**

- P1/P2/P3: Python-Plugins aus `modules/plugins/` laufen nicht mehr.
- P4: Python bleibt dauerhaft im Boot-Pfad, dafür bleibt das Ökosystem.
- Der Editor (`/api/editor`) muss in jedem Fall auf das neue Format
  zeigen; Downloads aus `plugins.yaml` liefern Python-Code und wären
  für P1–P3 unbrauchbar.

---

## 10. Risiken

| Risiko | Wirkung | Gegenmaßnahme |
|---|---|---|
| JSON-Details weichen ab (Klassen, `null`, Sortierung) | Frontend zeigt leere Felder | Fixtures + `test_json` ab M1 |
| Trailing-Slash/Converter falsch | 404/308 an falscher Stelle | eigener Router + Baseline-Test |
| Plugin-Ökosystem bricht | Nutzer können alte Plugins nicht weiterverwenden | Entscheidung in M5, P4 als Notausgang |
| GPIO unter Node ist unzuverlässig | Kessel heizt unkontrolliert | Hardware-Gate in M4, Pi-Test vor Schnitt |
| Restart-Strategie | Dienst startet nicht wieder | D-4 vor M2 festlegen, Supervisor-Test |
| Zwei Backends auf einer DB | doppelte Backgroundtasks, konkurrierende Schreiber | Parallelbetrieb nur lesend bzw. getrennte DB-Kopie |
| Zeitdruck verleitet zum „schnell mal anders" | stille Regression | Gate pro Meilenstein, keine Ausnahmen |

---

## 11. Aufwand

| Meilenstein | Inhalt | Schätzung |
|---|---|---|
| M0 | Gerüst, Router, DB, Config, Notification | 3–5 Tage |
| M1 | Kern, BaseView, JSON, Cache, Events | 2–3 Wochen |
| M2 | Domain (6 Ressourcen + Steps/Fermenter + Logs/System/Restart/Import) | 4–6 Wochen |
| M3 | Socket.IO | 3–5 Tage |
| M4 | Hardware (GPIO, 1-Wire, MQTT, Buzzer) | 2–3 Wochen |
| M5 | Plugins (Laufzeit + 11 Plugins) | 3–5 Wochen |
| M6 | Fixtures, Parallellauf, Schnitt, Pi-Test | 1–2 Wochen |

**Summe: 11–18 Wochen** für eine Person. Der größte Einzelposten ist
MQTT (893 Zeilen) plus die Plugin-Introspektion; der riskanteste ist
GPIO.

---

## 12. Offene Entscheidungen

1. **Plugin-Laufzeit** (P1/P2/P3/P4) — blockiert M5, nicht M0–M4.
2. **Restart** (D-4): Supervisor, systemd oder Wrapper-Skript.
3. **Hardware**: native Node-Bindings oder Python-Sidecar nur für GPIO.
4. **Deployment**: `npm` + systemd, Docker wie bisher, oder beides.
5. **Repository**: `backend-ts/` im selben Repo (aktueller Stand) oder
   eigenes Repo mit Submodule.
