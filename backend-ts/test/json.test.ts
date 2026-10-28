import assert from 'node:assert/strict'
import { test } from 'node:test'
import { canonicalize, stringify } from '../src/json.ts'

test('Objektschluessel werden sortiert', () => {
  assert.equal(stringify({ b: 1, a: 2 }), '{"a": 2, "b": 1}')
})

test('Separatoren wie json.dumps: Komma und Doppelpunkt mit Leerzeichen', () => {
  assert.equal(stringify({ a: 1, b: 2 }), '{"a": 1, "b": 2}')
  assert.equal(stringify([1, 2, 3]), '[1, 2, 3]')
  assert.equal(stringify([]), '[]')
  assert.equal(stringify({}), '{}')
})

test('Nicht-ASCII wird escaped wie bei Flask', () => {
  assert.equal(stringify({ name: 'Bräu' }), '{"name": "Br\\u00e4u"}')
})

test('undefined wird null statt weggelassen', () => {
  assert.equal(
    stringify({ a: undefined, b: [1, undefined] }),
    '{"a": null, "b": [1, null]}',
  )
})

test('verschachtelte Strukturen werden rekursiv sortiert', () => {
  assert.equal(
    stringify({ z: [{ b: 1, a: 2 }], a: { d: 4, c: 3 } }),
    '{"a": {"c": 3, "d": 4}, "z": [{"a": 2, "b": 1}]}',
  )
})

test('Strings mit Sonderzeichen bleiben korrekt', () => {
  assert.equal(stringify({ text: 'a,b:c"d' }), '{"text": "a,b:c\\"d"}')
})

test('canonicalize veraendert das Original nicht', () => {
  const source = { b: 1, a: 2 }
  canonicalize(source)
  assert.deepEqual(Object.keys(source), ['b', 'a'])
})
