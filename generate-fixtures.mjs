#!/usr/bin/env node
/**
 * M6: Golden Fixture Generation
 *
 * Captures actual HTTP responses from the running TS backend
 * for all GET endpoints (read-only) to compare against Python baseline.
 *
 * Usage:
 *   CBPI_DB=/path/to/craftbeerpi.db node generate-fixtures.mjs
 */

import { createApp } from './backend-ts/src/app.ts'
import { rootDir } from './backend-ts/src/env.ts'
import { mkdirSync, writeFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const ROUTES_TO_CAPTURE = [
  { method: 'GET', path: '/api/config/', name: 'get_api_config' },
  { method: 'GET', path: '/api/actor/', name: 'get_api_actor' },
  { method: 'GET', path: '/api/sensor/', name: 'get_api_sensor' },
  { method: 'GET', path: '/api/kettle/', name: 'get_api_kettle' },
  { method: 'GET', path: '/api/fermenter/', name: 'get_api_fermenter' },
  { method: 'GET', path: '/api/step/', name: 'get_api_step' },
  { method: 'GET', path: '/api/logs/', name: 'get_api_logs' },
  { method: 'GET', path: '/api/notification/', name: 'get_api_notification' },
  { method: 'GET', path: '/api/system/dump', name: 'get_api_system_dump' },
  { method: 'GET', path: '/api/system/endpoints', name: 'get_api_system_endpoints' },
  { method: 'GET', path: '/api/editor/', name: 'get_api_editor' },
  { method: 'GET', path: '/api/editor/list', name: 'get_api_editor_list' },
]

async function main() {
  const dbFile = process.env.CBPI_DB || join(rootDir(), 'craftbeerpi.db')
  if (!existsSync(dbFile)) {
    console.error(`Database not found: ${dbFile}`)
    console.error('Set CBPI_DB to point to a craftbeerpi.db file')
    process.exit(1)
  }

  console.log(`Using database: ${dbFile}`)
  console.log('Starting TS backend...')

  const app = await createApp({
    root: rootDir(),
    database: dbFile,
    logger: {
      debug: () => {},
      info: () => {},
      warning: () => {},
      error: () => {},
    },
  })

  await new Promise((resolve) => {
    app.httpServer.listen(0, '127.0.0.1', resolve)
  })

  const address = app.httpServer.address()
  const baseUrl = `http://127.0.0.1:${address.port}`
  console.log(`Server running at ${baseUrl}`)

  const fixtureDir = join(rootDir(), 'backend-ts', 'fixtures')
  mkdirSync(fixtureDir, { recursive: true })

  console.log('\nCapturing fixtures...')

  for (const route of ROUTES_TO_CAPTURE) {
    try {
      const url = `${baseUrl}${route.path}`
      const response = await fetch(url, { method: route.method })

      if (!response.ok) {
        console.warn(`  ${route.method} ${route.path} -> ${response.status} (skipped)`)
        continue
      }

      const text = await response.text()
      const jsonData = JSON.parse(text)
      const canonical = JSON.stringify(jsonData, Object.keys(jsonData).sort(), null)

      const fixturePath = join(fixtureDir, `${route.name}.json`)
      writeFileSync(fixturePath, canonical)
      console.log(`  OK ${route.method} ${route.path} -> ${fixturePath}`)
    } catch (error) {
      console.error(`  X ${route.method} ${route.path}: ${error.message}`)
    }
  }

  console.log('\nFixture generation complete.')
  console.log(`Fixtures saved to: ${fixtureDir}`)
  console.log('\nNext: Run Python backend fixture generator and compare.')

  await app.close()
}

main().catch((err) => {
  console.error('Fixture generation failed:', err)
  process.exit(1)
})
