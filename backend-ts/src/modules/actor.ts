/**
 * /api/actor - Aktor-Steuerung (on/off/power/toggle).
 *
 * Gegenstueck zu modules/actor/__init__.py. Die Plugin-Instanz (on/off/
 * set_power) kommt vom Plugin-Host (P2, M5); bis dahin antworten die
 * Routen mit 204 und loggen einen Hinweis, genau wie step.ts es tut.
 */
import type { Api } from '../core/api.ts'
import type { PluginInstance } from '../plugins/contract.ts'
import { CacheCallback } from '../json.ts'
import { Table } from '../db.ts'
import type { Db, Row } from '../db.ts'
import { registerBaseView } from '../http/baseview.ts'
import type { Router } from '../http/router.ts'
import { noContent } from '../http/respond.ts'

export class ActorRepository {
  readonly table: Table
  private readonly db: Db

  constructor(db: Db) {
    this.db = db
    this.table = new Table(db, {
      name: 'actor',
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

function actorCache(api: Api): Record<string, Row> | null {
  const value = api.cache.get<Record<string, Row>>('actors')
  if (!value || Array.isArray(value)) return null
  return value
}

function actorTypes(api: Api): Record<string, Row> | null {
  const value = api.cache.get<Record<string, Row>>('actor_types')
  if (!value || Array.isArray(value)) return null
  return value
}

function initActor(api: Api, pluginHost: { create(kind: string, name: string, api: Api, config?: Record<string, unknown>): PluginInstance | undefined }, id: number): void {
  const actors = actorCache(api)
  const actor = actors?.[String(id)]
  if (!actor) return

  const types = actorTypes(api)
  const type = types?.[actor.type as string]
  if (!type) {
    api.log('warning', `Actor type "${String(actor.type)}" not registered (M5) - instance not created`)
    return
  }

  const config = { ...(actor.config as Record<string, unknown> ?? {}), api, id, name: actor.name }
  const instance = pluginHost.create('actor', String(type.name), api, config)
  if (!instance) return

  if (typeof instance.init === 'function') {
    void instance.init()
  }
  actor.state = 0
  actor.power = 100
}

export function registerActorModule(
  router: Router,
  api: Api,
  pluginHost: { create(kind: string, name: string, api: Api, config?: Record<string, unknown>): PluginInstance | undefined },
  repository: ActorRepository,
): void {
  const instances = new Map<number, PluginInstance>()

  function getInstance(id: number): PluginInstance | undefined {
    return instances.get(id)
  }

  function switchActorOn(id: number, power?: unknown): void {
    const instance = getInstance(id)
    if (!instance) {
      api.log('warning', `Actor ${id} has no instance - switch/on ignored (M5)`)
      return
    }
    if (typeof instance.on === 'function') void instance.on(power)
    const actors = actorCache(api)
    const actor = actors?.[String(id)]
    if (actor) {
      actor.state = 1
      if (power !== undefined) actor.power = power
    }
    api.emit('SWITCH_ACTOR', actor)
  }

  function switchActorOff(id: number): void {
    const instance = getInstance(id)
    if (!instance) {
      api.log('warning', `Actor ${id} has no instance - switch/off ignored (M5)`)
      return
    }
    if (typeof instance.off === 'function') void instance.off()
    const actors = actorCache(api)
    const actor = actors?.[String(id)]
    if (actor) actor.state = 0
    api.emit('SWITCH_ACTOR', actor)
  }

  function actorPower(id: number, power: unknown): void {
    const instance = getInstance(id)
    if (!instance) {
      api.log('warning', `Actor ${id} has no instance - power ignored (M5)`)
      return
    }
    if (typeof instance.set_power === 'function') void instance.set_power(power)
    const actors = actorCache(api)
    const actor = actors?.[String(id)]
    if (actor) actor.power = power
    api.emit('SWITCH_ACTOR', actor)
  }

  registerBaseView(router, {
    base: '/api/actor',
    endpoint: 'ActorView',
    table: repository.table,
    api,
    cacheKey: 'actors',
    idConverter: 'int',
    postInit: (row) => {
      row.state = 0
      row.power = 100
    },
    postPost: (row) => {
      initActor(api, pluginHost, Number(row.id))
    },
    postPut: (row) => {
      initActor(api, pluginHost, Number(row.id))
    },
    preDelete: (row) => {
      instances.delete(Number(row.id))
    },
    postDelete: () => {
      api.emit('UPDATE_ALL_ACTORS', repository.all())
    },
  })

  router
    .add('POST', '/api/actor/<int:id>/switch/on', 'ActorView:on', (ctx) => {
      const id = Number(ctx.params.id)
      const power = ctx.params.power ?? undefined
      switchActorOn(id, power)
      return noContent()
    })
    .add('POST', '/api/actor/<int:id>/switch/off', 'ActorView:off', (ctx) => {
      switchActorOff(Number(ctx.params.id ?? ''))
      return noContent()
    })
    .add('POST', '/api/actor/<int:id>/power/<int:power>', 'ActorView:power', (ctx) => {
      actorPower(Number(ctx.params.id ?? ''), ctx.params.power ?? 100)
      return noContent()
    })
    .add('POST', '/api/actor/<int:id>/toggle', 'ActorView:toggle', (ctx) => {
      const id = Number(ctx.params.id ?? '')
      const actors = actorCache(api)
      const actor = actors?.[String(id)]
      if (actor?.state === 0) {
        switchActorOn(id)
      } else {
        switchActorOff(id)
      }
      return noContent()
    })
    .add('POST', '/api/actor/<id>/toggle/<int:t>', 'ActorView:toggleTime', async (ctx) => {
      const id = Number(ctx.params.id ?? '')
      const t = Number(ctx.params.t ?? 0)
      switchActorOn(id)
      setTimeout(() => {
        switchActorOff(id)
      }, t * 1000)
      return noContent()
    })
    .add('POST', '/api/actor/<int:id>/action/<method>', 'ActorView:action', (ctx) => {
      const id = Number(ctx.params.id ?? '')
      const instance = getInstance(id)
      if (!instance) {
        api.log('warning', `Actor ${id} has no instance - action ignored (M5)`)
        return noContent()
      }
      const method = String(ctx.params.method ?? '')
      const impl = instance as Record<string, (...args: unknown[]) => unknown>
      if (typeof impl[method] === 'function') {
        void impl[method]()
      }
      return noContent()
    })

  // Cache-Callback fuer /api/system/dump, wie add_cache_callback("actors", ...)
  api.cache.set('actors', new CacheCallback(() => repository.all()))
}
