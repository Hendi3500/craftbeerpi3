# backend-ts — Gerüst (M1)

TypeScript-Backend für CraftBeerPi 3. Der Plan steht in
[`../REWRITE-TS.md`](../REWRITE-TS.md).

**Status: M1 + Logs (M2a).** Bootpfad, Flask-kompatibler Router, SQLite
samt Migrationen, Config/Notification, `/api/system/*`, die `BaseView`-
Maschinerie, das `step`-Modul (CRUD, Sortieren, Start/Next/Reset) und
`/api/logs/*` laufen. Die Python-Seite wird nicht angefasst.

## Schnellstart

```bash
cd backend-ts
npm install
npm start                 # Port aus der Datenbank, sonst 5000
```

Umgebungsvariablen wie beim Python-Backend:

| Variable | Bedeutung |
|---|---|
| `CBPI_PORT` | Port, hat Vorrang vor der Datenbank |
| `CBPI_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `CBPI_LOG_STDOUT` | `1` schreibt ins Terminal statt `logs/app.log` |
| `CBPI_DB` | Pfad zur SQLite-Datei (Default `<root>/craftbeerpi.db`) |
| `CBPI_ROOT` | Projektwurzel (Default: Elternverzeichnis von `backend-ts/`) |
| `CBPI_STRICT_ROUTES` | `1` verlangt die vollständige Route-Baseline (Gate ab M2) |

Für einen Test gegen die echte Datenbank **ohne** sie zu verändern:

```bash
cp ../craftbeerpi.db /tmp/cbpi-test.db
CBPI_DB=/tmp/cbpi-test.db CBPI_PORT=5099 CBPI_LOG_STDOUT=1 npm start
```

## Was in M1 funktioniert

| Bereich | Routen |
|---|---|
| Meta | `GET /`, `GET /ui/`, `GET /ui/static/<path:filename>`, `GET /static/<path:filename>` |
| Config | `GET /api/config/`, `PUT /api/config/<name>`, die drei `NOT SUPPORTED`-Fälle |
| Notification | `GET /api/notification/`, `DELETE /api/notification/<id>` |
| System | `GET /api/system/dump`, `GET /api/system/endpoints` |
| Steps | 14 Routen: CRUD, `sort`, `reset`, `reset/current`, `start`, `next`, `stop_step`, `action`, `init_step` |
| Logs | 8 Routen: Liste, `actions`, `read_log_as_json`, `check_filename`, Download, Loeschen, Chart-Daten |
| Socket | Namespace `/brew`, Events kommen an |

**35 von 110 Routen.** Die Abdeckung meldet `test/routes.test.ts` bei
jedem Lauf; der Test prüft zusätzlich, dass die Endpunktnamen exakt der
Python-`url_map` entsprechen.

## Was noch fehlt

- `M1`: fertig bis auf die Schritt-Ausführung über `step_types`; sie
  braucht die Plugin-Laufzeit aus M5 (D-9).
- `M2`: actor, sensor, kettle, fermenter, system (Rest), restart, editor,
  recipe_import. actor/sensor/kettle sind ohne Plugin-Typen blockiert.
- `M3`: Socket-Payloads und die `MESSAGE`→`NOTIFY`-Kette sind vorhanden,
  die fachlichen Events folgen mit den Modulen.
- `M4`: Hardware (GPIO, 1-Wire, MQTT, Buzzer).
- `M5`: Plugin-Laufzeit. Discovery läuft bereits (11 Plugins gefunden),
  `loadAll()` ist bewusst ein No-op mit Warnung.

## Tests

```bash
npm test            # 78 Tests: Router, JSON, DB, HTTP, BaseView, Steps, Logs, Route-Baseline
npm run typecheck   # tsc --noEmit
```

Bemerkenswert: `GET /api/config/` ist **byte-identisch** zu dem, was
`json.dumps(..., sort_keys=True)` aus derselben Datenbank liefert —
inklusive der Separatoren `", "` / `": "` und der ASCII-Escapes. Dieses
Detail ist die Grundlage für die Golden-Fixtures in M6.

## Aufbau

```
src/
  index.ts          Start (run.py)
  app.ts            Aufbau ohne Listen - wird auch von Tests benutzt
  db.ts             SQLite, Migrationen, Table (DBModel-Ersatz)
  json.ts           kanonisches JSON (Flask-Parität)
  env.ts            Umgebungsvariablen
  logger.ts         logs/app.log, gleiches Format
  socket.ts         socket.io, /brew
  core/             Cache, EventBus, Api-Fassade
  http/             Router, Antworten, statische Dateien, Routen
    baseview.ts     generische CRUD-Views (5 Routen je Ressource)
  modules/          Domain-Module (step.ts, logs.ts)
  plugins/          Vertrag + Discovery (Laufzeit offen)
test/               node:test
```

## Bewusste Abweichungen

Siehe `REWRITE-TS.md` Abschnitt 8. Kurz: `Content-Type` ist
`application/json` (D-1), `update()` schreibt nur übergebene Spalten
(D-2), `endpoints` verändert die Routentabelle nicht (D-3),
Migrationsfehler brechen den Start ab (D-7), Step-Sonderrouten sind bis
M5 No-ops bzw. antworten 204 (D-9), `PUT` einer unbekannten Id ist immer
404 (D-10), `convert_chart_data_to_json` ist 400 statt 500 (D-11).
