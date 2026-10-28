/**
 * /api/sensor - Sensorenintrospection (CRUD, Aktion).
 *
 * Gegenstueck zu modules/sensors/__init__.py. Sensoren koennen passiv (lesen)
 * oder aktiv (lesen+schreiben) sein, sind aber keine Hardware-APIs; ihre
 * Implementierung kommt von Plugins (P2). Bis dahin sind die Routen
 * No-Ops (D-6) und loggen einen verlaesslichen Trace.
 */
import type { Api } from '../core/api.ts'
import type { PluginInstance } from '../plugins/contract.ts'
import { CacheCallback } from '../json.ts'
import { Table } from '../db.ts'
import type { Db, Row } from '../db.ts'
import { registerBaseView } from '../http/baseview.ts'
import type { Router } from '../http/router.ts'
import { noContent } from '../http/respond.ts'

export class SensorRepository {
  readonly table: Table
  private readonly db: Db

  constructor(db: Db) {
    this.db = db
    this.table = new Table(db, {
      name: 'sensor',
      fields: ['name', 'type', 'config', 'hide'],
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

function sensorCache(api: Api): Record<string, Row> | null {
  const value = api.cache.get<Record<string, Row>>('sensors')
  if (!value || Array.isArray(value)) return null
  return value
}

function sensorTypes(api: Api): Record<string, Row> | null {
  const value = api.cache.get<Record<string, Row>>('sensor_types')
  if (!value || Array.isArray(value)) return null
  return value
}

function initSensor(api: Api, pluginHost: { create(kind: string, name: string, api: Api, config?: Record<string, unknown>): PluginInstance | undefined }, id: number): void {
  const sensors = sensorCache(api)
  const sensor = sensors?.[String(id)]
  if (!sensor) return

  const types = sensorTypes(api)
  const type = types?.[sensor.type as string]
  if (!type) {
    api.log('warning', `Sensor type "${String(sensor.type)}" not registered (M5) - instance not created`)
    return
  }

  const config = { ...(sensor.config as Record<string, unknown> ?? {}), api, id, name: sensor.name }
  const instance = pluginHost.create('sensor', String(type.name), api, config)
  if (!instance) return

  if (typeof instance.init === 'function') {
    void instance.init()
  }
  sensor.mode = 'P' // passive für jetzt, aktiv für Plugins
}

export function registerSensorModule(
  router: Router,
  api: Api,
  pluginHost: { create(kind: string, name: string, api: Api, config?: Record<string, unknown>): PluginInstance | undefined },
  repository: SensorRepository,
): void {
  const instances = new Map<number, PluginInstance>()

  function getInstance(id: number): PluginInstance | undefined {
    return instances.get(id)
  }

  registerBaseView(router, {
    base: '/api/sensor',
    endpoint: 'SensorView',
    table: repository.table,
    api,
    cacheKey: 'sensors',
    idConverter: 'int',
    postInit: (row) => {
      row.mode = 'P' // standard, Plugins setzen Mode="A"
    },
    postPost: (row) => {
      initSensor(api, pluginHost, Number(row.id))
    },
    postPut: (row) => {
      const old = getInstance(Number(row.id))
      if (old && typeof old.stop === 'function') {
        void old.stop()
      }
      initSensor(api, pluginHost, Number(row.id))
    },
    preDelete: (row) => {
      const instance = getInstance(Number(row.id))
      if (instance && typeof instance.stop === 'function') {
        void instance.stop()
      }
      instances.delete(Number(row.id))
    },
    postDelete: () => {
      api.emit('UPDATE_ALL_SENSORS', repository.all())
    },
  })

  router
    .add('POST', '/api/sensor/<int:id>/action/<method>', 'SensorView:action', (ctx) => {
      const id = Number(ctx.params.id ?? '')
      const instance = getInstance(id)
      if (!instance) {
        api.log('warning', `Sensor ${id} has no instance - action ignored (M5)`)
        return noContent()
      }
      const method = String(ctx.params.method ?? '')
      const impl = instance as Record<string, (...args: unknown[]) => unknown>
      if (typeof impl[method] === 'function') {
        void impl[method]()
      }
      return noContent()
    })

  // Cache-Callback fuer /api/system/dump, wie add_cache_callback("sensors", ...)
  api.cache.set('sensors', new CacheCallback(() => repository.all()))
}
