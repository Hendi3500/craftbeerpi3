/**
 * /api/step - CRUD, Sortieren, Start/Next/Reset.
 *
 * Steps sind die einzige Ressource ohne Hardware- und Plugin-Abhaengigkeit
 * und damit der Beleg fuer die BaseView-Maschinerie. Die Ausfuehrung eines
 * Schritts (step_types) fehlt noch (M5); Zustand, Zeitstempel und Events
 * muessen aber schon jetzt dem Original entsprechen.
 */
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
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
  events: { name: string; data: unknown }[]
  close(): Promise<void>
}

async function boot(): Promise<Harness> {
  const dir = mkdtempSync(join(tmpdir(), 'cbpi-ts-step-'))
  const app = await createApp({
    root: ROOT,
    database: join(dir, 'test.db'),
    // logAction schreibt action.log - nie in das Projektverzeichnis.
    logsDir: join(dir, 'logs'),
    logger: silent,
  })

  const events: { name: string; data: unknown }[] = []
  const original = app.api.emit.bind(app.api)
  app.api.emit = (name, data) => {
    events.push({ name, data })
    original(name, data)
  }

  await new Promise<void>((resolveListen) => {
    app.httpServer.listen(0, '127.0.0.1', resolveListen)
  })
  const address = app.httpServer.address() as AddressInfo

  return {
    app,
    base: `http://127.0.0.1:${address.port}`,
    events,
    close: async () => {
      await app.close()
      rmSync(dir, { recursive: true, force: true })
    },
  }
}

async function call(
  base: string,
  path: string,
  method = 'GET',
  body?: unknown,
): Promise<{ status: number; text: string }> {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return { status: response.status, text: await response.text() }
}

async function createStep(
  base: string,
  name: string,
  type = 'DummyStep',
  config: Record<string, unknown> = { temp: 60 },
): Promise<Record<string, unknown>> {
  const response = await call(base, '/api/step/', 'POST', { name, type, config })
  assert.equal(response.status, 200)
  return JSON.parse(response.text) as Record<string, unknown>
}

test('POST vergibt order fortlaufend und setzt state I', async () => {
  const h = await boot()
  try {
    const first = await createStep(h.base, 'Einmaischen')
    const second = await createStep(h.base, 'Kochen')

    assert.equal(first.order, 1)
    assert.equal(first.state, 'I')
    assert.equal(second.order, 2)
    assert.deepEqual(second.config, { temp: 60 })
  } finally {
    await h.close()
  }
})

test('GET /api/step/ liefert ein Array, sortiert nach order', async () => {
  const h = await boot()
  try {
    const first = await createStep(h.base, 'eins')
    const second = await createStep(h.base, 'zwei')

    const response = await call(h.base, '/api/step/')
    assert.equal(response.status, 200)
    const rows = JSON.parse(response.text) as Record<string, unknown>[]
    assert.deepEqual(
      rows.map((row) => row.id),
      [first.id, second.id],
    )
    assert.equal(Array.isArray(rows), true)
  } finally {
    await h.close()
  }
})

test('POST /api/step/sort schreibt die Reihenfolge', async () => {
  const h = await boot()
  try {
    const first = await createStep(h.base, 'eins')
    const second = await createStep(h.base, 'zwei')
    const third = await createStep(h.base, 'drei')

    const response = await call(h.base, '/api/step/sort', 'POST', [
      [third.id, 1],
      [first.id, 2],
      [second.id, 3],
    ])
    assert.equal(response.status, 204)

    const rows = JSON.parse((await call(h.base, '/api/step/')).text) as Record<string, unknown>[]
    assert.deepEqual(
      rows.map((row) => row.name),
      ['drei', 'eins', 'zwei'],
    )

    const event = h.events.filter((entry) => entry.name === 'UPDATE_ALL_STEPS').at(-1)
    assert.deepEqual(
      (event?.data as Record<string, unknown>[]).map((row) => row.name),
      ['drei', 'eins', 'zwei'],
    )
  } finally {
    await h.close()
  }
})

test('start setzt den ersten Schritt auf A und uebernimmt config als stepstate', async () => {
  const h = await boot()
  try {
    const first = await createStep(h.base, 'eins', 'DummyStep', { temp: 65 })
    await createStep(h.base, 'zwei')

    const before = Math.floor(Date.now() / 1000)
    const response = await call(h.base, '/api/step/start', 'POST')
    assert.equal(response.status, 204)

    const rows = JSON.parse((await call(h.base, '/api/step/')).text) as Record<string, unknown>[]
    const active = rows.find((row) => row.id === first.id)
    assert.equal(active?.state, 'A')
    assert.deepEqual(active?.stepstate, { temp: 65 })
    assert.equal(typeof active?.start, 'number')
    assert.ok((active?.start as number) >= before)

    const event = h.events.filter((entry) => entry.name === 'UPDATE_ALL_STEPS').at(-1)
    assert.equal((event?.data as unknown[]).length, 2)
  } finally {
    await h.close()
  }
})

test('next beendet den aktiven Schritt (D) und startet den naechsten', async () => {
  const h = await boot()
  try {
    const first = await createStep(h.base, 'eins')
    const second = await createStep(h.base, 'zwei')

    await call(h.base, '/api/step/start', 'POST')
    const before = Math.floor(Date.now() / 1000)
    assert.equal((await call(h.base, '/api/step/next', 'POST')).status, 204)

    const rows = JSON.parse((await call(h.base, '/api/step/')).text) as Record<string, unknown>[]
    const done = rows.find((row) => row.id === first.id)
    const active = rows.find((row) => row.id === second.id)

    assert.equal(done?.state, 'D')
    assert.equal(typeof done?.end, 'number')
    assert.ok((done?.end as number) >= before)
    assert.equal(active?.state, 'A')
    assert.equal(typeof active?.start, 'number')
  } finally {
    await h.close()
  }
})

test('next ohne wartenden Schritt beendet das Brauen und benachrichtigt', async () => {
  const h = await boot()
  try {
    await createStep(h.base, 'eins')
    await call(h.base, '/api/step/start', 'POST')

    const response = await call(h.base, '/api/step/next', 'POST')
    assert.equal(response.status, 204)

    const rows = JSON.parse((await call(h.base, '/api/step/')).text) as Record<string, unknown>[]
    assert.deepEqual(
      rows.map((row) => row.state),
      ['D'],
    )

    const message = h.app.api.messages().find((entry) => entry.headline === 'Brewing Finished')
    assert.ok(message, 'Brewing Finished fehlt in den Nachrichten')
    assert.equal(message?.message, 'You are done!')
    assert.equal(message?.type, 'success')
    assert.equal(message?.timeout, null)

    const notify = h.events.filter((entry) => entry.name === 'NOTIFY').at(-1)
    assert.equal((notify?.data as { headline?: string }).headline, 'Brewing Finished')
  } finally {
    await h.close()
  }
})

test('start setzt die Zieltemperatur des beendeten Kessels auf 0', async () => {
  const h = await boot()
  try {
    const first = await createStep(h.base, 'eins')
    await call(h.base, '/api/step/start', 'POST')

    // Im Original liegt hier die Plugin-Instanz mit kettle-Attribut.
    h.app.api.cache.set('active_step', { id: first.id, kettle: 4 })

    const targets: unknown[] = []
    h.app.api.bus.on('SET_TARGET_TEMP', (payload) => targets.push(payload))

    await call(h.base, '/api/step/next', 'POST')
    assert.deepEqual(targets, [{ id: 4, temp: 0 }])
  } finally {
    await h.close()
  }
})

test('reset setzt alle Schritte zurueck und leert active_step', async () => {
  const h = await boot()
  try {
    await createStep(h.base, 'eins')
    await createStep(h.base, 'zwei')
    await call(h.base, '/api/step/start', 'POST')
    await call(h.base, '/api/step/next', 'POST')
    h.app.api.cache.set('active_step', { id: 2 })

    const response = await call(h.base, '/api/step/reset', 'POST')
    assert.equal(response.status, 204)

    const rows = JSON.parse((await call(h.base, '/api/step/')).text) as Record<string, unknown>[]
    for (const row of rows) {
      assert.equal(row.state, 'I')
      assert.equal(row.stepstate, null)
      assert.equal(row.start, null)
      assert.equal(row.end, null)
    }
    assert.equal(h.app.api.cache.get('active_step'), null)
  } finally {
    await h.close()
  }
})

test('stop_step leert active_step und antwortet 204', async () => {
  const h = await boot()
  try {
    h.app.api.cache.set('active_step', { id: 1 })
    assert.equal((await call(h.base, '/api/step/stop_step/')).status, 204)
    assert.equal(h.app.api.cache.get('active_step'), null)
  } finally {
    await h.close()
  }
})

test('Sonderrouten antworten 204', async () => {
  const h = await boot()
  try {
    assert.equal((await call(h.base, '/api/step/action/foo', 'POST')).status, 204)
    assert.equal((await call(h.base, '/api/step/reset/current', 'POST')).status, 204)
    assert.equal((await call(h.base, '/api/step/init_step/eins')).status, 204)
  } finally {
    await h.close()
  }
})

test('DELETE /api/step/ loescht alle Schritte', async () => {
  const h = await boot()
  try {
    await createStep(h.base, 'eins')
    await createStep(h.base, 'zwei')

    assert.equal((await call(h.base, '/api/step/', 'DELETE')).status, 204)
    assert.equal((await call(h.base, '/api/step/')).text, '[]')
  } finally {
    await h.close()
  }
})

test('/api/system/dump liefert unter steps den aktuellen Datenbankstand', async () => {
  const h = await boot()
  try {
    const created = await createStep(h.base, 'dumped')
    const dump = JSON.parse((await call(h.base, '/api/system/dump')).text) as Record<string, unknown>
    const steps = dump.steps as Record<string, unknown>[]
    assert.deepEqual(
      steps.map((row) => row.id),
      [created.id],
    )
  } finally {
    await h.close()
  }
})

test('PUT /api/step/<id> aktualisiert einen Schritt', async () => {
  const h = await boot()
  try {
    const created = await createStep(h.base, 'alt')
    const response = await call(h.base, `/api/step/${String(created.id)}`, 'PUT', {
      name: 'neu',
      config: { temp: 70 },
    })
    assert.equal(response.status, 200)
    const body = JSON.parse(response.text) as Record<string, unknown>
    assert.equal(body.name, 'neu')
    assert.deepEqual(body.config, { temp: 70 })

    assert.equal((await call(h.base, '/api/step/9999', 'PUT', { name: 'x' })).status, 404)
    // Ohne Cache (cache_key = None) loescht das Original auch eine
    // unbekannte Id ohne Fehler - DELETE ist idempotent.
    assert.equal((await call(h.base, '/api/step/9999', 'DELETE')).status, 204)
  } finally {
    await h.close()
  }
})
