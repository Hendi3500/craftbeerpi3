/**
 * BaseView-Maschinerie (modules/core/baseview.py).
 *
 * Geprueft wird das Verhalten, auf das sich alle sechs CRUD-Views
 * verlassen: Cache vor Datenbank, Nachladen, 404 bei unbekannter Id,
 * null bei GET, Projektion auf deklarierte Felder und die Reihenfolge
 * der Hooks.
 */
import assert from 'node:assert/strict'
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { test } from 'node:test'
import type { Api } from '../src/core/api.ts'
import { Cache } from '../src/core/cache.ts'
import { Db, Table } from '../src/db.ts'
import {
  initViewCache,
  registerBaseView,
  type BaseViewHooks,
} from '../src/http/baseview.ts'
import { Router } from '../src/http/router.ts'
import type { Logger } from '../src/logger.ts'

const silent: Logger = {
  debug: () => {},
  info: () => {},
  warning: () => {},
  error: () => {},
}

interface Harness {
  db: Db
  cache: Cache
  api: Api
  table: Table
  base: string
  close(): Promise<void>
}

async function boot(
  options: { cacheKey?: string | null; hooks?: BaseViewHooks } = {},
): Promise<Harness> {
  const db = new Db(':memory:')
  db.conn.exec(`
    CREATE TABLE thing (
      id INTEGER PRIMARY KEY NOT NULL,
      name VARCHAR(80),
      config VARCHAR(255),
      height INTEGER
    )
  `)

  const table = new Table(db, {
    name: 'thing',
    fields: ['name', 'config'],
    jsonFields: ['config'],
  })

  const cache = new Cache()
  const cacheKey = options.cacheKey === undefined ? 'things' : options.cacheKey
  if (cacheKey !== null) cache.set(cacheKey, {})

  const api = { cache } as unknown as Api
  const router = new Router(silent)
  registerBaseView(router, {
    base: '/things',
    endpoint: 'ThingView',
    table,
    api,
    cacheKey,
    ...options.hooks,
  })

  const server: Server = createServer((req, res) => {
    void router.handle(req, res)
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address() as AddressInfo

  return {
    db,
    cache,
    api,
    table,
    base: `http://127.0.0.1:${address.port}`,
    close: async () => {
      await new Promise<void>((resolve) => server.close(() => resolve()))
      db.close()
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

test('POST schreibt in DB und Cache, GET liest aus dem Cache', async () => {
  const h = await boot()
  try {
    const created = await call(h.base, '/things/', 'POST', {
      name: 'erster',
      config: { level: 1 },
      // Nicht deklariert: darf weder in der Antwort noch im Cache landen.
      height: 12,
    })
    assert.equal(created.status, 200)
    assert.deepEqual(JSON.parse(created.text), {
      id: 1,
      name: 'erster',
      config: { level: 1 },
    })

    assert.deepEqual(h.cache.get('things'), {
      1: { id: 1, name: 'erster', config: { level: 1 } },
    })

    const all = await call(h.base, '/things/')
    assert.equal(all.text, '{"1": {"config": {"level": 1}, "id": 1, "name": "erster"}}')
  } finally {
    await h.close()
  }
})

test('GET einer unbekannten Id ist 200 mit null', async () => {
  const h = await boot()
  try {
    const response = await call(h.base, '/things/99')
    assert.equal(response.status, 200)
    assert.equal(response.text, 'null')
  } finally {
    await h.close()
  }
})

test('PUT aktualisiert den Cache-Eintrag und behaelt nicht gesendete Felder', async () => {
  const h = await boot()
  try {
    await call(h.base, '/things/', 'POST', { name: 'alt', config: { a: 1 } })

    const updated = await call(h.base, '/things/1', 'PUT', { name: 'neu' })
    assert.equal(updated.status, 200)
    assert.deepEqual(JSON.parse(updated.text), {
      id: 1,
      name: 'neu',
      config: { a: 1 },
    })

    const stored = h.table.one(1)
    assert.equal(stored?.name, 'neu')
    assert.deepEqual(stored?.config, { a: 1 })
  } finally {
    await h.close()
  }
})

test('PUT und DELETE einer unbekannten Id sind 404', async () => {
  const h = await boot()
  try {
    assert.equal((await call(h.base, '/things/42', 'PUT', { name: 'x' })).status, 404)
    assert.equal((await call(h.base, '/things/42', 'DELETE')).status, 404)
  } finally {
    await h.close()
  }
})

test('DELETE entfernt aus Cache und Datenbank und antwortet 204', async () => {
  const h = await boot()
  try {
    await call(h.base, '/things/', 'POST', { name: 'weg' })
    const deleted = await call(h.base, '/things/1', 'DELETE')
    assert.equal(deleted.status, 204)
    assert.equal(deleted.text, '')
    assert.equal(h.table.one(1), null)
    assert.deepEqual(h.cache.get('things'), {})
  } finally {
    await h.close()
  }
})

test('fehlt die Zeile im Cache, traegt erst PUT sie nach', async () => {
  const h = await boot()
  try {
    h.db.conn
      .prepare('INSERT INTO thing (id, name, config) VALUES (?, ?, ?)')
      .run(7, 'nachtrag', '{"x":2}')

    // getOne fragt im Original nur den Cache und liefert deshalb null -
    // nachgeladen wird ausschliesslich in _get_entry (PUT/DELETE).
    const missing = await call(h.base, '/things/7')
    assert.equal(missing.status, 200)
    assert.equal(missing.text, 'null')
    assert.deepEqual(h.cache.get('things'), {})

    const updated = await call(h.base, '/things/7', 'PUT', { name: 'geaendert' })
    assert.equal(updated.status, 200)
    assert.deepEqual(JSON.parse(updated.text), {
      id: 7,
      name: 'geaendert',
      config: { x: 2 },
    })
    assert.deepEqual(h.cache.get('things'), {
      7: { id: 7, name: 'geaendert', config: { x: 2 } },
    })
  } finally {
    await h.close()
  }
})

test('Hooks laufen in der Reihenfolge des Originals', async () => {
  const calls: string[] = []
  const h = await boot({
    hooks: {
      prePost: (data) => {
        calls.push('prePost')
        data.name = 'von-prePost'
      },
      postPost: () => calls.push('postPost'),
      prePut: () => calls.push('prePut'),
      postPut: () => calls.push('postPut'),
      preDelete: () => calls.push('preDelete'),
      postDelete: () => calls.push('postDelete'),
    },
  })
  try {
    await call(h.base, '/things/', 'POST', { name: 'roh' })
    await call(h.base, '/things/1', 'PUT', { name: 'neu' })
    await call(h.base, '/things/1', 'DELETE')

    assert.deepEqual(calls, [
      'prePost',
      'postPost',
      'prePut',
      'postPut',
      'preDelete',
      'postDelete',
    ])
  } finally {
    await h.close()
  }
})

test('cacheKey null laesst den Cache unberuehrt', async () => {
  const h = await boot({ cacheKey: null })
  try {
    await call(h.base, '/things/', 'POST', { name: 'db-only' })
    assert.deepEqual(h.cache.snapshot(), {})
    assert.equal((await call(h.base, '/things/1')).text, '{"config": null, "id": 1, "name": "db-only"}')
  } finally {
    await h.close()
  }
})

test('ein Array-Cache wird bei GET durchsucht', async () => {
  const h = await boot()
  try {
    h.cache.set('things', [{ id: 5, name: 'liste', config: null }])
    assert.equal(
      (await call(h.base, '/things/5')).text,
      '{"config": null, "id": 5, "name": "liste"}',
    )
    assert.equal((await call(h.base, '/things/6')).text, 'null')
  } finally {
    await h.close()
  }
})

test('initViewCache fuellt den Cache und ruft postInit', async () => {
  const h = await boot()
  try {
    h.db.conn
      .prepare('INSERT INTO thing (id, name, config) VALUES (?, ?, ?)')
      .run(1, 'a', null)
    h.db.conn
      .prepare('INSERT INTO thing (id, name, config) VALUES (?, ?, ?)')
      .run(2, 'b', '{"k":true}')

    const seen: unknown[] = []
    initViewCache({
      base: '/things',
      endpoint: 'ThingView',
      table: h.table,
      api: h.api,
      cacheKey: 'things',
      postInit: (row) => seen.push(row.id),
    })

    assert.deepEqual(seen, [1, 2])
    assert.deepEqual(h.cache.get('things'), {
      1: { id: 1, name: 'a', config: null },
      2: { id: 2, name: 'b', config: { k: true } },
    })
  } finally {
    await h.close()
  }
})

test('<int:id> matcht nur Ziffern', async () => {
  const h = await boot()
  try {
    assert.equal((await call(h.base, '/things/abc')).status, 404)
  } finally {
    await h.close()
  }
})
