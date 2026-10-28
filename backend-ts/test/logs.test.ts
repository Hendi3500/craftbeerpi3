/**
 * /api/logs - Dateiliste, Aktionen, CSV-Logs, Download, Loeschen.
 *
 * Die Tests arbeiten in einem temporaeren logs-Verzeichnis; das echte
 * Projekt-Log wird nicht angefasst.
 */
import assert from 'node:assert/strict'
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import type { AddressInfo } from 'node:net'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { test } from 'node:test'
import { createApp, type App } from '../src/app.ts'
import type { Logger } from '../src/logger.ts'

const ROOT = resolve(import.meta.dirname, '../..')

const silent: Logger = {
  debug: () => {},
  info: () => {},
  warning: () => {},
  error: () => {},
}

interface Harness {
  app: App
  base: string
  dir: string
  close(): Promise<void>
}

async function boot(): Promise<Harness> {
  const baseDir = mkdtempSync(join(tmpdir(), 'cbpi-ts-logs-'))
  const dir = join(baseDir, 'logs')
  const app = await createApp({
    root: ROOT,
    database: join(baseDir, 'test.db'),
    logsDir: dir,
    logger: silent,
  })

  await new Promise<void>((resolveListen) => {
    app.httpServer.listen(0, '127.0.0.1', resolveListen)
  })
  const address = app.httpServer.address() as AddressInfo

  return {
    app,
    base: `http://127.0.0.1:${address.port}`,
    dir,
    close: async () => {
      await app.close()
      rmSync(baseDir, { recursive: true, force: true })
    },
  }
}

async function call(
  base: string,
  path: string,
  method = 'GET',
  body?: unknown,
): Promise<{ status: number; text: string; headers: Headers }> {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return {
    status: response.status,
    text: await response.text(),
    headers: response.headers,
  }
}

test('GET /api/logs/ listet nur .log-Dateien', async () => {
  const h = await boot()
  try {
    assert.equal((await call(h.base, '/api/logs/')).text, '[]')

    mkdirSync(h.dir, { recursive: true })
    writeFileSync(join(h.dir, 'app.log'), '')
    writeFileSync(join(h.dir, 'sensor_1.log'), '')
    writeFileSync(join(h.dir, 'notiz.txt'), '')

    const listed = JSON.parse((await call(h.base, '/api/logs/')).text) as string[]
    assert.deepEqual(listed.sort(), ['app.log', 'sensor_1.log'])
  } finally {
    await h.close()
  }
})

test('GET /api/logs/actions liest Zeitstempel und Text', async () => {
  const h = await boot()
  try {
    assert.equal((await call(h.base, '/api/logs/actions')).text, '[]')

    mkdirSync(h.dir, { recursive: true })
    writeFileSync(
      join(h.dir, 'action.log'),
      [
        '2020-01-02 03:04:05,Erster Eintrag',
        'kaputt,ignoriert',
        '2020-01-02 03:04:06,Zweiter, mit Komma',
        '"2020-01-02 03:04:07","Quoted"',
        '',
      ].join('\n'),
    )

    const rows = JSON.parse(
      (await call(h.base, '/api/logs/actions')).text,
    ) as [number, string][]

    // 2020-01-02T03:04:05Z wie strptime - nicht lokale Zeitzone.
    assert.deepEqual(rows, [
      [1577934245000, 'Erster Eintrag'],
      [1577934246000, 'Zweiter'],
      [1577934247000, 'Quoted'],
    ])
  } finally {
    await h.close()
  }
})

test('GET /api/logs/read_log_as_json parst Messwerte', async () => {
  const h = await boot()
  try {
    assert.equal(
      (await call(h.base, '/api/logs/read_log_as_json/sensor/1')).text,
      '[]',
    )

    mkdirSync(h.dir, { recursive: true })
    writeFileSync(
      join(h.dir, 'sensor_1.log'),
      [
        '2020-01-02 03:04:05,20.5',
        'kein Zeitstempel,1.0',
        '2020-01-02 03:04:06,21',
        '2020-01-02 03:04:07,abc',
      ].join('\n'),
    )

    const rows = JSON.parse(
      (await call(h.base, '/api/logs/read_log_as_json/sensor/1')).text,
    ) as [number, number][]
    assert.deepEqual(rows, [
      [1577934245000, 20.5],
      [1577934246000, 21],
    ])
  } finally {
    await h.close()
  }
})

test('GET /api/logs/check_filename antwortet mit JSON-Boolean', async () => {
  const h = await boot()
  try {
    assert.equal((await call(h.base, '/api/logs/check_filename/app.log')).text, 'true')
    assert.equal((await call(h.base, '/api/logs/check_filename/app.txt')).text, 'false')
    assert.equal((await call(h.base, '/api/logs/check_filename/a%20b.log')).text, 'false')
  } finally {
    await h.close()
  }
})

test('DELETE /api/logs/<file> loescht nur gueltige Dateinamen', async () => {
  const h = await boot()
  try {
    mkdirSync(h.dir, { recursive: true })
    writeFileSync(join(h.dir, 'app.log'), 'inhalt')

    const invalid = await call(h.base, '/api/logs/notiz.txt', 'DELETE')
    assert.equal(invalid.status, 404)
    assert.equal(invalid.text, 'File Not Found')

    const deleted = await call(h.base, '/api/logs/app.log', 'DELETE')
    assert.equal(deleted.status, 204)
    assert.throws(() => readFileSync(join(h.dir, 'app.log')))

    // Unbekannte, aber gueltige Datei: 204 wie im Original.
    assert.equal((await call(h.base, '/api/logs/fehlt.log', 'DELETE')).status, 204)
  } finally {
    await h.close()
  }
})

test('GET /api/logs/download liefert die Datei als Attachment', async () => {
  const h = await boot()
  try {
    mkdirSync(h.dir, { recursive: true })
    writeFileSync(join(h.dir, 'app.log'), 'zeile 1\nzeile 2\n')

    const response = await call(h.base, '/api/logs/download/app.log')
    assert.equal(response.status, 200)
    assert.equal(response.text, 'zeile 1\nzeile 2\n')
    assert.equal(
      response.headers.get('content-disposition'),
      'attachment; filename=app.log',
    )
    assert.equal(
      response.headers.get('content-type'),
      'application/octet-stream',
    )
    assert.equal(response.headers.get('cache-control')?.includes('no-cache'), true)

    assert.equal((await call(h.base, '/api/logs/download/fehlt.log')).status, 404)
    assert.equal((await call(h.base, '/api/logs/download/notiz.txt')).status, 404)
  } finally {
    await h.close()
  }
})

test('POST /api/logs/s/<id> liefert Name und Messwerte des Sensors', async () => {
  const h = await boot()
  try {
    mkdirSync(h.dir, { recursive: true })
    writeFileSync(join(h.dir, 'sensor_1.log'), '2020-01-02 03:04:05,20\n')

    assert.equal((await call(h.base, '/api/logs/s/1', 'POST', {})).status, 404)

    h.app.api.cache.set('sensors', {
      1: { id: 1, name: 'Maische', type: 'DummyTempSensor' },
    })

    const response = await call(h.base, '/api/logs/s/1', 'POST', {})
    assert.equal(response.status, 200)
    assert.deepEqual(JSON.parse(response.text), [
      { name: 'Maische', data: [[1577934245000, 20]] },
    ])

    // Unbekannter Typ bleibt eine leere Liste.
    assert.equal((await call(h.base, '/api/logs/x/1', 'POST', {})).text, '[]')
  } finally {
    await h.close()
  }
})

test('POST /api/logs/k/<id> ohne Controller ist 404', async () => {
  const h = await boot()
  try {
    assert.equal((await call(h.base, '/api/logs/k/1', 'POST', {})).status, 404)

    h.app.api.cache.set('kettle', { 1: { id: 1, name: 'Kessel', logic: 'PID' } })
    assert.equal((await call(h.base, '/api/logs/k/1', 'POST', {})).status, 404)
  } finally {
    await h.close()
  }
})

test('convert_chart_data_to_json ist ein klarer Client-Fehler (D-11)', async () => {
  const h = await boot()
  try {
    const response = await call(h.base, '/api/logs/convert_chart_data_to_json/foo')
    assert.equal(response.status, 400)
  } finally {
    await h.close()
  }
})

test('logAction schreibt action.log, actions liest die Zeile zurueck', async () => {
  const h = await boot()
  try {
    h.app.api.logAction('Start Step Einmaischen')

    const rows = JSON.parse(
      (await call(h.base, '/api/logs/actions')).text,
    ) as [number, string][]
    assert.equal(rows.length, 1)
    assert.equal(rows[0]?.[1], 'Start Step Einmaischen')
    // localTimestamp schreibt Wanduhrzeit; timestampToMillis liest sie
    // wie strptime als UTC. Verglichen wird deshalb mit derselben
    // Umrechnung, nicht mit Date.now() (das waere die Zeitzone).
    const now = new Date()
    const expected = Date.UTC(
      now.getFullYear(),
      now.getMonth(),
      now.getDate(),
      now.getHours(),
      now.getMinutes(),
      now.getSeconds(),
    )
    assert.ok(Math.abs((rows[0]?.[0] ?? 0) - expected) < 5000)
  } finally {
    await h.close()
  }
})
