/**
 * BaseView - Gegenstueck zu modules/core/baseview.py.
 *
 * Registriert die fuenf CRUD-Routen einer Ressource. Die Hooks heissen
 * wie im Original, damit die Portierung der Domain-Module mechanisch
 * bleibt:
 *
 *   prePost(data)        vor dem Insert (z. B. order/state fuer Steps)
 *   postPost(row)        nach dem Insert (z. B. Actor initialisieren)
 *   prePut(row)          vor dem Update
 *   postPut(row)         nach dem Update
 *   preDelete(row)       vor dem Loeschen
 *   postDelete(id)       nach dem Loeschen
 *   postInit(row)        beim Fuellen des Caches
 *
 * Besonderheit von StepView: dort ist cache_key im Python-Core None,
 * deshalb laufen alle CRUD-Zugriffe direkt gegen die Datenbank. Der
 * Cache-Schluessel "steps" ist nur ein Callback fuer /api/system/dump.
 * Genau so wird es hier abgebildet (cacheKey: null).
 */
import type { Api } from '../core/api.ts'
import type { Row, Table } from '../db.ts'
import { HttpError, type Router } from './router.ts'
import { json, noContent } from './respond.ts'

export interface BaseViewHooks {
  prePost?: (data: Row) => void
  postPost?: (row: Row) => void
  prePut?: (row: Row) => void
  postPut?: (row: Row) => void
  preDelete?: (row: Row) => void
  postDelete?: (id: string | number) => void
  postInit?: (row: Row) => void
}

export interface BaseViewOptions extends BaseViewHooks {
  /** z. B. "/api/step" */
  base: string
  /** Endpunkt-Prefix fuer Fehlermeldungen, z. B. "StepView" */
  endpoint: string
  table: Table
  api: Api
  /**
   * Cache-Schluessel oder null.
   * null = kein Cache (StepView im Original).
   */
  cacheKey: string | null
  /** Standard "int" (<int:id>). */
  idConverter?: 'int' | 'string'
  allowCreate?: boolean
  allowDelete?: boolean
  allowUpdate?: boolean
}

type CacheMap = Record<string, Row>

function cachedMap(api: Api, key: string | null): CacheMap | null {
  if (key === null) return null
  const value = api.cache.get(key)
  if (value === null || value === undefined) return null
  if (Array.isArray(value)) return null
  if (typeof value !== 'object') return null
  return value as CacheMap
}

function cachedArray(api: Api, key: string | null): Row[] | null {
  if (key === null) return null
  const value = api.cache.get(key)
  return Array.isArray(value) ? (value as Row[]) : null
}

function idOf(row: Row, table: Table): string {
  return String(row[table.primaryKey])
}

function missing(id: string): HttpError {
  return new HttpError(404, `Not found: ${id}`)
}

/** Cache aus der Datenbank fuellen (BaseView.init_cache). */
export function initViewCache(options: BaseViewOptions): void {
  if (options.cacheKey === null) return

  const rows = options.table.all()
  if (Array.isArray(rows)) {
    for (const row of rows) options.postInit?.(row)
    options.api.cache.set(options.cacheKey, rows)
    return
  }

  for (const row of Object.values(rows)) options.postInit?.(row)
  options.api.cache.set(options.cacheKey, rows)
}

/**
 * Eintrag aus dem Cache, mit Nachladen aus der Datenbank.
 *
 * Ein Client kann eine Id schicken, die sein Zustand noch kennt, die es
 * aber nicht mehr gibt. Umgekehrt kann die Zeile in der Datenbank
 * stehen, aber (noch) nicht im Cache - dann wird sie nachgetragen.
 */
function getEntry(options: BaseViewOptions, id: string): Row | null {
  const map = cachedMap(options.api, options.cacheKey)
  if (!map) return null

  const entry = map[id]
  if (entry) return entry

  const fromDb = options.table.one(id)
  if (fromDb) map[id] = fromDb
  return fromDb
}

export function registerBaseView(
  router: Router,
  options: BaseViewOptions,
): void {
  const { base, endpoint, table, api } = options
  const converter = options.idConverter ?? 'int'
  const oneRule = `${base}/<${converter}:id>`

  router.add('GET', `${base}/`, `${endpoint}:getAll`, () => {
    const map = cachedMap(api, options.cacheKey)
    if (map) return json(map)

    const array = cachedArray(api, options.cacheKey)
    if (array) return json(array)

    return json(table.all())
  })

  router.add('GET', oneRule, `${endpoint}:getOne`, (ctx) => {
    const id = ctx.params.id ?? ''

    const map = cachedMap(api, options.cacheKey)
    if (map) return json(map[id] ?? null)

    const array = cachedArray(api, options.cacheKey)
    if (array) {
      return json(array.find((row) => idOf(row, table) === id) ?? null)
    }

    return json(table.one(id))
  })

  if (options.allowCreate !== false) {
    router.add('POST', `${base}/`, `${endpoint}:post`, async (ctx) => {
      const data = await ctx.json<Row>()
      options.prePost?.(data)

      const row = table.insert(data)

      const map = cachedMap(api, options.cacheKey)
      if (map) {
        map[idOf(row, table)] = row
      } else if (options.cacheKey !== null) {
        // Liste (z. B. Steps): Reihenfolge kommt aus der Datenbank.
        api.cache.set(options.cacheKey, table.all())
      }

      options.postPost?.(row)
      return json(row)
    })
  }

  if (options.allowUpdate !== false) {
    router.add('PUT', oneRule, `${endpoint}:put`, async (ctx) => {
      const id = ctx.params.id ?? ''
      const data = await ctx.json<Row>()
      data[table.primaryKey] = converter === 'int' ? Number(id) : id

      // Laufzeitobjekte gehoeren nicht in die Datenbank.
      delete data.instance

      const map = cachedMap(api, options.cacheKey)
      if (map) {
        const entry = getEntry(options, id)
        if (!entry) throw missing(id)

        options.prePut?.(entry)
        Object.assign(entry, data)
        table.update(entry)
        options.postPut?.(entry)
        return json(entry)
      }

      const existing = table.one(id)
      if (!existing) throw missing(id)

      options.prePut?.(existing)
      const updated = table.update({ ...existing, ...data })
      options.postPut?.(updated)
      return json(updated)
    })
  }

  if (options.allowDelete !== false) {
    router.add('DELETE', oneRule, `${endpoint}:delete`, (ctx) => {
      const id = ctx.params.id ?? ''

      const map = cachedMap(api, options.cacheKey)
      if (map) {
        const entry = getEntry(options, id)
        if (!entry) throw missing(id)

        options.preDelete?.(entry)
        delete map[id]
        table.delete(id)
        options.postDelete?.(id)
        return noContent()
      }

      const existing = table.one(id)
      if (existing) options.preDelete?.(existing)
      table.delete(id)
      if (options.cacheKey !== null) {
        api.cache.set(options.cacheKey, table.all())
      }
      options.postDelete?.(id)
      return noContent()
    })
  }
}
