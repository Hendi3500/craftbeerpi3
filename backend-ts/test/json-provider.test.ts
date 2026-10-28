/**
 * ComplexJSONProvider-Paritaet (modules/app_config.py).
 *
 * Der Provider ist der Grund, warum /api/system/dump und /api/kettle/
 * ueberhaupt antworten: im Cache liegen Klassen, Funktionen, Callbacks
 * und Laufzeitobjekte. Jeder Zweig hat eine Entsprechung im Original und
 * wird hier einzeln geprueft.
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  CacheCallback,
  setJsonDiagnostics,
  stringify,
} from '../src/json.ts'

test('CacheCallback wird ausgefuehrt', () => {
  const callback = new CacheCallback(() => ({ answer: 42 }))
  assert.equal(stringify(callback), '{"answer": 42}')
})

test('CacheCallback liefert den aktuellen Stand, nicht den Stand beim Anlegen', () => {
  let state = [1]
  const callback = new CacheCallback(() => state)
  assert.equal(stringify(callback), '[1]')
  state = [1, 2]
  assert.equal(stringify(callback), '[1, 2]')
})

test('Klasse wird zu {name, module}', () => {
  class DummyActor {}
  Object.defineProperty(DummyActor, '__module__', {
    value: 'modules.plugins.dummy',
  })
  assert.equal(
    stringify(DummyActor),
    '{"module": "modules.plugins.dummy", "name": "DummyActor"}',
  )
})

test('Funktion wird zu {name, module}', () => {
  function backgroundTask(): void {}
  Object.defineProperty(backgroundTask, '__module__', {
    value: 'modules.plugins.task',
  })
  assert.equal(
    stringify(backgroundTask),
    '{"module": "modules.plugins.task", "name": "backgroundTask"}',
  )
})

test('Funktion ohne __module__ hat module: null', () => {
  const fn = function unnamed(): void {}
  assert.equal(stringify(fn), '{"module": null, "name": "unnamed"}')
})

test('unbekannte Klasseninstanz wird null und meldet den Typ', () => {
  const seen: string[] = []
  setJsonDiagnostics({ unknown: (name) => seen.push(name) })

  class Hysteresis {
    target = 60
  }
  try {
    assert.equal(stringify(new Hysteresis()), 'null')
    assert.deepEqual(seen, ['Hysteresis'])
  } finally {
    setJsonDiagnostics({})
  }
})

test('__json__ gewinnt gegen toJSON', () => {
  // Ein normales Objektliteral mit diesen Schluesseln ist in Python ein
  // dict und wird als dict serialisiert; der Hook zaehlt nur fuer
  // Instanzen, deshalb hier eine Klasse.
  class Custom {
    __json__(): unknown {
      return { from: '__json__' }
    }

    toJSON(): unknown {
      return { from: 'toJSON' }
    }
  }
  assert.equal(stringify(new Custom()), '{"from": "__json__"}')
})

test('toJSON wird benutzt, wenn kein __json__ vorhanden ist', () => {
  assert.equal(stringify(new Date('2020-01-02T03:04:05.000Z')), '"2020-01-02T03:04:05.000Z"')
})

test('Map wird zum Objekt', () => {
  const map = new Map<unknown, unknown>([
    ['b', 2],
    [1, 'eins'],
  ])
  assert.equal(stringify(map), '{"1": "eins", "b": 2}')
})

test('Zyklen werden zu null statt zu einem Stack Overflow', () => {
  const node: Record<string, unknown> = { name: 'root' }
  node.self = node
  assert.equal(stringify(node), '{"name": "root", "self": null}')
})

test('dieselbe Instanz an zwei Stellen wird zweimal serialisiert', () => {
  const shared = { id: 1 }
  assert.equal(stringify({ a: shared, b: shared }), '{"a": {"id": 1}, "b": {"id": 1}}')
})

test('BigInt bleibt eine exakte Ganzzahl', () => {
  assert.equal(stringify({ id: 9007199254740993n }), '{"id": 9007199254740993}')
})

test('NaN und Infinity werden null wie in Python', () => {
  assert.equal(stringify({ a: Number.NaN, b: Infinity }), '{"a": null, "b": null}')
})
