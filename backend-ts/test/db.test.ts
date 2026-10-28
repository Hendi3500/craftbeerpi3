import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { test } from 'node:test'
import { Db, Table, type Row } from '../src/db.ts'

const ROOT = resolve(import.meta.dirname, '../..')

function withDb(run: (db: Db, config: Table) => void): void {
  const dir = mkdtempSync(join(tmpdir(), 'cbpi-ts-'))
  const db = new Db(join(dir, 'test.db'))
  try {
    db.initSchema(ROOT)
    db.migrate(ROOT)
    const config = new Table(db, {
      name: 'config',
      fields: ['type', 'value', 'description', 'options'],
      primaryKey: 'name',
      jsonFields: ['options'],
    })
    run(db, config)
  } finally {
    db.close()
    rmSync(dir, { recursive: true, force: true })
  }
}

test('Schema und Migrationen laufen auf einer frischen Datenbank', () => {
  const dir = mkdtempSync(join(tmpdir(), 'cbpi-ts-'))
  const db = new Db(join(dir, 'test.db'))
  try {
    db.initSchema(ROOT)
    const first = db.migrate(ROOT)
    assert.equal(first.current, 6)
    assert.deepEqual(first.applied, [1, 2, 3, 4, 5, 6])

    const second = db.migrate(ROOT)
    assert.deepEqual(second.applied, [])
    assert.equal(second.current, 6)
  } finally {
    db.close()
    rmSync(dir, { recursive: true, force: true })
  }
})

test('JSON-Felder werden beim Lesen geparst', () => {
  withDb((_db, config) => {
    const all = config.all() as Record<string, Row>
    assert.deepEqual(all.unit?.options, ['C', 'F'])
    assert.equal(all.unit?.value, 'C')
  })
})

test('update schreibt nur uebergebene Spalten (D-2)', () => {
  withDb((_db, config) => {
    const updated = config.update({ name: 'unit', value: 'F' })
    assert.equal(updated.value, 'F')
    assert.equal(updated.type, 'select')
    assert.equal(updated.description, 'Temperature Unit')
    assert.deepEqual(updated.options, ['C', 'F'])
  })
})

test('insert und delete runden das CRUD ab', () => {
  withDb((_db, config) => {
    const inserted = config.insert({
      name: 'ts_test_parameter',
      type: 'text',
      value: 'hallo',
      description: 'nur fuer den Test',
      options: null,
    })
    assert.equal(inserted.name, 'ts_test_parameter')
    assert.equal(inserted.value, 'hallo')
    assert.equal(inserted.options, null)

    const found = config.one('ts_test_parameter')
    assert.equal(found?.value, 'hallo')

    config.delete('ts_test_parameter')
    assert.equal(config.one('ts_test_parameter'), null)
  })
})

test('update ohne Primaerschluessel ist ein Fehler (B-28)', () => {
  withDb((_db, config) => {
    assert.throws(() => config.update({ value: 'F' }), /without primary key/)
  })
})
