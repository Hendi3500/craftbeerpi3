/**
 * End-to-End ueber den echten http.Server: Boot, Routing, JSON, Cache.
 */
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import type { AddressInfo } from 'node:net'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { test } from 'node:test'
import { parse as parseYaml } from 'yaml'
import { createApp, type App } from '../src/app.ts'
import type { Logger } from '../src/logger.ts'

const ROOT = resolve(import.meta.dirname, '../..')

const silent: Logger = {
  debug: () => {},
  info: () => {},
  warning: () => {},
  error: () => {},
}

async function boot(): Promise<{ app: App; base: string; cleanup: () => Promise<void> }> {
  const dir = mkdtempSync(join(tmpdir(), 'cbpi-ts-http-'))
  const app = await createApp({
    root: ROOT,
    database: join(dir, 'test.db'),
    logger: silent,
  })

  await new Promise<void>((resolveListen) => {
    app.httpServer.listen(0, '127.0.0.1', resolveListen)
  })
  const address = app.httpServer.address() as AddressInfo

  return {
    app,
    base: `http://127.0.0.1:${address.port}`,
    cleanup: async () => {
      await app.close()
      rmSync(dir, { recursive: true, force: true })
    },
  }
}

test('GET /api/config/ liefert die Konfiguration aus dem Cache', async () => {
  const { base, cleanup } = await boot()
  try {
    const response = await fetch(`${base}/api/config/`)
    assert.equal(response.status, 200)
    assert.equal(response.headers.get('content-type'), 'application/json')

    const body = (await response.json()) as Record<string, Record<string, unknown>>
    assert.equal(body.unit?.value, 'C')
    assert.deepEqual(body.unit?.options, ['C', 'F'])
    assert.equal(body.brewery_name?.value, 'My Home Brewery')
  } finally {
    await cleanup()
  }
})

test('PUT /api/config/<name> aendert nur den Wert', async () => {
  const { base, cleanup } = await boot()
  try {
    const response = await fetch(`${base}/api/config/unit`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: 'F' }),
    })
    assert.equal(response.status, 200)

    const body = (await response.json()) as Record<string, unknown>
    assert.equal(body.value, 'F')
    assert.equal(body.type, 'select')
    assert.equal(body.description, 'Temperature Unit')
  } finally {
    await cleanup()
  }
})

test('unbekannter Config-Parameter ist 400, nicht 500', async () => {
  const { base, cleanup } = await boot()
  try {
    const response = await fetch(`${base}/api/config/gibtsnicht`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: 1 }),
    })
    assert.equal(response.status, 400)
  } finally {
    await cleanup()
  }
})

test('POST /api/config/ bleibt NOT SUPPORTED', async () => {
  const { base, cleanup } = await boot()
  try {
    const response = await fetch(`${base}/api/config/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
    assert.equal(response.status, 400)
    assert.equal(await response.text(), 'NOT SUPPORTED')
  } finally {
    await cleanup()
  }
})

test('/ui ohne Slash leitet per 308 auf /ui/ um', async () => {
  const { base, cleanup } = await boot()
  try {
    const response = await fetch(`${base}/ui`, { redirect: 'manual' })
    assert.equal(response.status, 308)
    assert.equal(response.headers.get('location'), '/ui/')
  } finally {
    await cleanup()
  }
})

test('/api/system/dump enthaelt die Cache-Schluessel', async () => {
  const { base, cleanup } = await boot()
  try {
    const response = await fetch(`${base}/api/system/dump`)
    assert.equal(response.status, 200)
    const body = (await response.json()) as Record<string, unknown>
    for (const key of ['config', 'messages', 'actors', 'kettle', 'steps']) {
      assert.ok(key in body, `Cache-Schluessel fehlt: ${key}`)
    }
  } finally {
    await cleanup()
  }
})

test('/api/system/endpoints liefert Swagger-YAML aus der Registry', async () => {
  const { base, cleanup } = await boot()
  try {
    const response = await fetch(`${base}/api/system/endpoints`)
    assert.equal(response.status, 200)

    // Geparst vergleichen: die Anfuehrungszeichen im YAML unterscheiden
    // sich zwischen PyYAML und dem Node-Paket, der Inhalt nicht.
    const document = parseYaml(await response.text()) as {
      swagger: string
      paths: Record<string, Record<string, unknown>>
    }
    assert.equal(document.swagger, '2.0')
    assert.ok(document.paths['/api/config/']?.GET)
    assert.ok(document.paths['/api/config/<name>']?.PUT)
    assert.ok(document.paths['/api/system/dump']?.GET)
  } finally {
    await cleanup()
  }
})

test('/api/notification/ enthaelt die Spenden-Notification', async () => {
  const { base, cleanup } = await boot()
  try {
    const response = await fetch(`${base}/api/notification/`)
    assert.equal(response.status, 200)
    const body = (await response.json()) as { headline: string }[]
    assert.ok(Array.isArray(body))
    assert.ok(body.some((entry) => entry.headline.includes('donation')))
  } finally {
    await cleanup()
  }
})

test('unbekannte Route ist 404, falsche Methode ist 405', async () => {
  const { base, cleanup } = await boot()
  try {
    assert.equal((await fetch(`${base}/api/gibtsnicht/`)).status, 404)

    const notAllowed = await fetch(`${base}/api/config/`, { method: 'PUT' })
    assert.equal(notAllowed.status, 405)
  } finally {
    await cleanup()
  }
})
