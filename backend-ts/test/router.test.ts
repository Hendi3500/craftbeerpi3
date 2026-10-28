/**
 * Router-Semantik. Diese Tests sind der Kern der Paritaet: wenn hier
 * etwas nicht stimmt, stimmen Dutzende Endpunkte nicht.
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { noContent } from '../src/http/respond.ts'
import { Router } from '../src/http/router.ts'
import type { Logger } from '../src/logger.ts'

const silent: Logger = {
  debug: () => {},
  info: () => {},
  warning: () => {},
  error: () => {},
}

function makeRouter(): Router {
  return new Router(silent)
    .add('GET', '/api/actor/', 'ActorView:getAll', () => ({ ok: true }))
    .add('POST', '/api/actor/', 'ActorView:post', () => noContent())
    .add('GET', '/api/actor/<int:id>', 'ActorView:getOne', (ctx) => ({
      id: ctx.params.id,
    }))
    .add('GET', '/api/logs/actions', 'LogView:actions', () => [])
    .add('GET', '/api/logs/<file>', 'LogView:download', (ctx) => ({
      file: ctx.params.file,
    }))
    .add('GET', '/api/step/init_step/<step>', 'StepView:initStep', (ctx) => ({
      step: ctx.params.step,
    }))
    .add('GET', '/', 'index', () => ({ root: true }))
}

test('<int:id> matcht nur Ziffern', () => {
  const router = makeRouter()

  const hit = router.resolve('GET', '/api/actor/42')
  assert.equal(hit.kind, 'route')
  if (hit.kind !== 'route') return
  assert.equal(hit.params.id, '42')

  assert.equal(router.resolve('GET', '/api/actor/abc').kind, 'not-found')
})

test('statische Regel gewinnt gegen dynamische', () => {
  const router = makeRouter()

  const staticHit = router.resolve('GET', '/api/logs/actions')
  assert.equal(staticHit.kind, 'route')
  if (staticHit.kind !== 'route') return
  assert.equal(staticHit.spec.endpoint, 'LogView:actions')

  const dynamicHit = router.resolve('GET', '/api/logs/sensor_1.log')
  assert.equal(dynamicHit.kind, 'route')
  if (dynamicHit.kind !== 'route') return
  assert.equal(dynamicHit.spec.endpoint, 'LogView:download')
  assert.equal(dynamicHit.params.file, 'sensor_1.log')
})

test('Trailing Slash: Regel mit Slash leitet um, Regel ohne nicht', () => {
  const router = makeRouter()

  const redirect = router.resolve('GET', '/api/actor')
  assert.deepEqual(redirect, { kind: 'redirect', location: '/api/actor/' })

  // Umgekehrt wird nicht umgeleitet: /api/logs/actions/ ist 404.
  assert.equal(router.resolve('GET', '/api/logs/actions/').kind, 'not-found')
  assert.equal(router.resolve('GET', '/').kind, 'route')
})

test('405 nennt die erlaubten Methoden', () => {
  const router = makeRouter()

  const match = router.resolve('PUT', '/api/actor/')
  assert.equal(match.kind, 'not-allowed')
  if (match.kind !== 'not-allowed') return
  assert.deepEqual(match.allow, ['GET', 'HEAD', 'OPTIONS', 'POST'])
})

test('OPTIONS wird automatisch beantwortet', () => {
  const router = makeRouter()

  const match = router.resolve('OPTIONS', '/api/actor/')
  assert.equal(match.kind, 'options')
  if (match.kind !== 'options') return
  assert.ok(match.allow.includes('POST'))
})

test('HEAD bedient eine GET-Regel', () => {
  const router = makeRouter()

  const match = router.resolve('HEAD', '/api/actor/')
  assert.equal(match.kind, 'route')
  if (match.kind !== 'route') return
  assert.equal(match.spec.method, 'GET')
})

test('Pfad-Parameter werden dekodiert', () => {
  const router = makeRouter()

  const match = router.resolve('GET', '/api/logs/sensor%201.log')
  assert.equal(match.kind, 'route')
  if (match.kind !== 'route') return
  assert.equal(match.params.file, 'sensor 1.log')
})

test('unbekannter Pfad ist 404', () => {
  const router = makeRouter()
  assert.equal(router.resolve('GET', '/api/gibtsnicht/').kind, 'not-found')
})

test('doppelte Route ist ein Programmierfehler', () => {
  const router = makeRouter()
  assert.throws(
    () => router.add('GET', '/api/actor/', 'X:y', () => null),
    /Duplicate route/,
  )
})
