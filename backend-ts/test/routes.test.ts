/**
 * Route-Paritaet gegen tools/routes_baseline.json.
 *
 * Stufe 1 (immer): jede registrierte Route muss in der Baseline stehen.
 * Stufe 3 (CBPI_STRICT_ROUTES=1): die Mengen muessen gleich sein. Das ist
 * das Gate ab M2.
 */
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { test } from 'node:test'
import { createApp } from '../src/app.ts'
import type { Logger } from '../src/logger.ts'

const ROOT = resolve(import.meta.dirname, '../..')

const silent: Logger = {
  debug: () => {},
  info: () => {},
  warning: () => {},
  error: () => {},
}

interface BaselineRoute {
  endpoint: string
  methods: string[]
  rule: string
}

test('registrierte Routen sind Teil der Baseline', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'cbpi-ts-routes-'))
  const app = await createApp({
    root: ROOT,
    database: join(dir, 'test.db'),
    logger: silent,
  })

  try {
    const baseline = JSON.parse(
      readFileSync(join(ROOT, 'tools', 'routes_baseline.json'), 'utf8'),
    ) as BaselineRoute[]

    const known = new Set(
      baseline.flatMap((route) =>
        route.methods.map((method) => `${method} ${route.rule}`),
      ),
    )
    const expectedEndpoints = new Map(
      baseline.flatMap((route) =>
        route.methods.map(
          (method) => [`${method} ${route.rule}`, route.endpoint] as const,
        ),
      ),
    )
    const specs = app.router.specs()
    const registered = specs.map((route) => `${route.method} ${route.rule}`)

    const unknown = registered.filter((route) => !known.has(route))
    assert.deepEqual(unknown, [], `Routen nicht in der Baseline: ${unknown.join(', ')}`)

    // Der Endpunktname steht im url_map des Originals und wird u. a. von
    // /api/system/endpoints benutzt. Ein abweichender Name faellt sonst
    // erst beim Fixture-Vergleich auf.
    const wrongEndpoints = specs
      .filter(
        (route) =>
          expectedEndpoints.get(`${route.method} ${route.rule}`) !==
          route.endpoint,
      )
      .map((route) => `${route.method} ${route.rule} -> ${route.endpoint}`)
    assert.deepEqual(
      wrongEndpoints,
      [],
      `Endpunktnamen weichen ab: ${wrongEndpoints.join(', ')}`,
    )

    const coverage = new Set(registered).size
    console.log(`Route coverage: ${coverage}/${known.size} (${Math.round((coverage / known.size) * 100)}%)`)

    if (process.env.CBPI_STRICT_ROUTES === '1') {
      assert.equal(coverage, known.size, 'Route-Baseline nicht vollstaendig abgedeckt')
    }
  } finally {
    await app.close()
    rmSync(dir, { recursive: true, force: true })
  }
})
