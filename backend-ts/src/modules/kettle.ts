/**
 * /api/kettle - Kesselsteuerung (CRUD, target_temp, automatic).
 *
 * Gegenstueck zu modules/kettle/__init__.py. Kessel sind Ladestandards,
 * kein Plugin (P2); die Controller-Lebenszyklus ist im Python-Core, hier
 * wird der Zustand nach @cbpi.backgroundtask read_target_temps gehalten.
 */
import { Api } from '../core/api.ts'
import { Table } from '../db.ts'
import type { Db, Row } from '../db.ts'
import { registerBaseView } from '../http/baseview.ts'
import type { Router } from '../http/router.ts'
import { noContent } from '../http/respond.ts'

export class KettleRepository {
  readonly table: Table
  private readonly db: Db

  constructor(db: Db) {
    this.db = db
    this.table = new Table(db, {
      name: 'kettle',
      fields: ['name', 'sensor', 'heater', 'automatic', 'logic', 'config', 'agitator', 'target_temp'],
      primaryKey: 'id',
      jsonFields: ['config'],
    })
  }

  all(): Row[] {
    return this.table.all() as Row[]
  }

  one(id: string | number): Row | null {
    return this.table.one(id)
  }

  insert(data: Row): Row {
    return this.table.insert(data)
  }

  update(id: string | number, patch: Row): Row {
    return this.table.update({ id, ...patch })
  }

  delete(id: string | number): void {
    this.table.delete(id)
  }
}

export function registerKettleModule(
  router: Router,
  api: Api,
  repository: KettleRepository,
): void {
  registerBaseView(router, {
    base: '/api/kettle',
    endpoint: 'KettleView',
    table: repository.table,
    api,
    cacheKey: 'kettle',
    idConverter: 'int',
    prePost: (data) => {
      data.target_temp = 0
    },
    postInit: (obj) => {
      obj.state = false
    },
    postPost: (m) => {
      // Cache aktualisieren, aber keine Plugin-Instanz stoppen (M5: noop)
      m.state = false
    },
    postPut: (m) => {
      // State nach Update zuruecksetzen
      m.state = false
    },
    preDelete: (row) => {
      api.emit('UPDATE_ALL_KETTLES', repository.all())
    },
    postDelete: () => {
      api.emit('UPDATE_ALL_KETTLES', repository.all())
    },
  })

  router
    .add('POST', '/api/kettle/<int:id>/targettemp/<temp>', 'KettleView:postTargetTemp', (ctx) => {
      const id = Number(ctx.params.id)
      const temp = Number(ctx.params.temp)

      // Cache aktualisieren
      const kettleCache = api.cache.get<Record<string, Row>>('kettle')
      if (kettleCache) {
        const entry = kettleCache[String(id)]
        if (entry) {
          entry.target_temp = temp
        }
      }

      // Datenbank updaten
      const model = repository.update(id, { target_temp: temp })
      api.emit('UPDATE_KETTLE_TARGET_TEMP', { id, target_temp: temp })
      return noContent()
    })
    .add('POST', '/api/kettle/<int:id>/automatic', 'KettleView:toggle', (ctx) => {
      const id = Number(ctx.params.id ?? '')
      const kettleCache = api.cache.get<Record<string, Row>>('kettle')
      if (kettleCache) {
        const entry = kettleCache[String(id)]
        if (entry) {
          const currentState = entry.state === true
          entry.state = !currentState
        }
      }
      api.emit('UPDATE_KETTLE', id)
      return noContent()
    })
}