/**
 * /api/fermenter - Gärsteuerung (Fermenter + verschachtelte Steps).
 *
 * Gegenstueck zu modules/fermenter/__init__.py. Nested Resources:
 *   GET /api/fermenter/                          -> alle Fermenter
 *   GET /api/fermenter/<id>                      -> ein Fermenter
 *   POST /api/fermenter/                         -> Fermenter anlegen
 *   PUT /api/fermenter/<id>                      -> Fermenter aendern
 *   DELETE /api/fermenter/<id>                   -> Fermenter + Steps loeschen
 *   POST /api/fermenter/<id>/targettemp/<temp>   -> Zieltemperatur
 *   POST /api/fermenter/<id>/brewname            -> Brauname
 *   POST /api/fermenter/<id>/step                -> Step anlegen
 *   PUT /api/fermenter/<id>/step/<stepid>        -> Step aendern
 *   DELETE /api/fermenter/<id>/step/<stepid>     -> Step loeschen
 *   POST /api/fermenter/<id>/step/sort           -> Steps sortieren
 *   POST /api/fermenter/<id>/start               -> Gaerung starten/next
 *   POST /api/fermenter/<id>/reset               -> Plan zuruecksetzen
 *   POST /api/fermenter/<id>/automatic           -> Automatik toggle
 */
import type { Api } from '../core/api.ts'
import { CacheCallback } from '../json.ts'
import { Table } from '../db.ts'
import type { Db, Row } from '../db.ts'
import { registerBaseView } from '../http/baseview.ts'
import type { Router } from '../http/router.ts'
import { json, noContent } from '../http/respond.ts'

export class FermenterRepository {
  readonly table: Table
  private readonly db: Db

  constructor(db: Db) {
    this.db = db
    this.table = new Table(db, {
      name: 'fermenter',
      fields: ['name', 'brewname', 'sensor', 'sensor2', 'sensor3', 'heater', 'cooler', 'logic', 'config', 'target_temp'],
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

export class FermenterStepRepository {
  readonly table: Table
  private readonly db: Db

  constructor(db: Db) {
    this.db = db
    this.table = new Table(db, {
      name: 'fermenter_step',
      fields: ['name', 'days', 'hours', 'minutes', 'temp', 'direction', 'order', 'state', 'start', 'end', 'timer_start', 'fermenter_id'],
      primaryKey: 'id',
      jsonFields: [],
      orderBy: 'order',
    })
  }

  all(): Row[] {
    return this.table.all() as Row[]
  }

  one(id: string | number): Row | null {
    return this.table.one(id)
  }

  byFermenter(fermenterId: number): Row[] {
    const sql = `SELECT * FROM "fermenter_step" WHERE fermenter_id = ? ORDER BY CASE WHEN "order" IS NULL THEN 1 ELSE 0 END, "order", id`
    const rows = this.db.conn.prepare(sql).all(fermenterId) as Row[]
    return rows.map((row) => ({
      id: row.id,
      name: row.name,
      days: row.days,
      hours: row.hours,
      minutes: row.minutes,
      temp: row.temp,
      direction: row.direction,
      order: row.order,
      state: row.state,
      start: row.start,
      end: row.end,
      timer_start: row.timer_start,
      fermenter_id: row.fermenter_id,
    }))
  }

  maxOrder(fermenterId: number): number | null {
    const row = this.db.conn
      .prepare('SELECT max("order") AS "order" FROM "fermenter_step" WHERE fermenter_id = ?')
      .get(fermenterId) as { order: number | null } | undefined
    return row?.order ?? null
  }

  updateState(id: number, state: string): void {
    this.db.conn.prepare('UPDATE "fermenter_step" SET state = ? WHERE id = ?').run(state, id)
  }

  updateTimer(id: number, timer: number): void {
    this.db.conn.prepare('UPDATE "fermenter_step" SET timer_start = ? WHERE id = ?').run(timer, id)
  }

  update(data: Row): Row {
    return this.table.update(data)
  }

  resetAll(fermenterId: number): void {
    this.db.conn
      .prepare('UPDATE "fermenter_step" SET state = ?, start = NULL, end = NULL, timer_start = NULL WHERE fermenter_id = ?')
      .run('I', fermenterId)
  }

  setOrders(pairs: [number, number][]): void {
    const stmt = this.db.conn.prepare('UPDATE "fermenter_step" SET "order" = ? WHERE id = ?')
    const apply = this.db.conn.transaction(() => {
      for (const [id, order] of pairs) stmt.run(order, id)
    })
    apply()
  }

  delete(id: number): void {
    this.db.conn.prepare('DELETE FROM "fermenter_step" WHERE id = ?').run(id)
  }

  deleteByFermenterId(fermenterId: number): void {
    this.db.conn.prepare('DELETE FROM "fermenter_step" WHERE fermenter_id = ?').run(fermenterId)
  }
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000)
}

function normaliseStepData(data: Row): Row {
  const result = { ...data }
  for (const field of ['days', 'hours', 'minutes', 'temp'] as const) {
    if (result[field] === '' || result[field] === undefined) result[field] = 0
  }
  if (result.name === '' || result.name === undefined) result.name = 'NO NAME'
  return result
}

function parseStepOrder(body: unknown, steps: Row[]): [number, number][] | null {
  if (!Array.isArray(body) || body.length === 0) return null

  const known = new Set(steps.map((s) => Number(s.id)))
  const pairs: [number, number][] = []
  const seen = new Set<number>()

  for (let index = 0; index < body.length; index++) {
    const entry = body[index]
    let stepId: number
    let order: number

    if (Array.isArray(entry) || entry instanceof Array) {
      if (entry.length !== 2) return null
      stepId = Number(entry[0])
      order = Number(entry[1])
    } else {
      stepId = Number(entry)
      order = index + 1
    }

    if (!Number.isFinite(stepId) || !Number.isFinite(order)) return null
    if (!known.has(stepId) || seen.has(stepId)) return null

    seen.add(stepId)
    pairs.push([stepId, order])
  }

  if (pairs.length !== steps.length) return null
  return pairs
}

export function registerFermenterModule(
  router: Router,
  api: Api,
  fermenterRepo: FermenterRepository,
  stepRepo: FermenterStepRepository,
): void {
  registerBaseView(router, {
    base: '/api/fermenter',
    endpoint: 'FermenterView',
    table: fermenterRepo.table,
    api,
    cacheKey: 'fermenter',
    idConverter: 'int',
    postInit: (obj) => {
      obj.state = false
      obj.steps = stepRepo.byFermenter(Number(obj.id))
    },
    postPost: (m) => {
      m.state = false
      m.steps = []
    },
    prePut: (m) => {
      m.state = false
    },
    postPut: (m) => {
      resetFermenter(api, stepRepo, Number(m.id))
    },
    postDelete: (id) => {
      stepRepo.deleteByFermenterId(Number(id))
      api.emit('UPDATE_ALL_FERMENTERS', fermenterRepo.all())
    },
  })

  // targettemp
  router.add('POST', '/api/fermenter/<int:id>/targettemp/<temp>', 'FermenterView:postTargetTemp', (ctx) => {
    const id = Number(ctx.params.id)
    const temp = Number(ctx.params.temp)
    if (!Number.isFinite(temp)) return json({ message: 'Invalid temp' }, 500)

    const cache = api.cache.get<Record<string, Row>>('fermenter')
    const entry = cache?.[String(id)]
    if (entry) entry.target_temp = temp

    fermenterRepo.update(id, { target_temp: temp })
    api.emit('UPDATE_FERMENTER_TARGET_TEMP', { id, target_temp: temp })
    return noContent()
  })

  // brewname
  router.add('POST', '/api/fermenter/<int:id>/brewname', 'FermenterView:postBrewName', async (ctx) => {
    const id = Number(ctx.params.id)
    const body = await ctx.json<{ brewname?: string }>()
    const brewname = body?.brewname ?? ''

    const cache = api.cache.get<Record<string, Row>>('fermenter')
    const entry = cache?.[String(id)]
    if (entry) entry.brewname = brewname

    fermenterRepo.update(id, { brewname })
    api.emit('UPDATE_FERMENTER_BREWNAME', { id, brewname })
    return noContent()
  })

  // step CRUD
  router.add('POST', '/api/fermenter/<int:id>/step', 'FermenterView:postStep', async (ctx) => {
    const id = Number(ctx.params.id)
    const data = await ctx.json<Row>()
    const norm = normaliseStepData(data)

    const orderMax = stepRepo.maxOrder(id)
    norm.order = (orderMax ?? 0) + 1
    norm.state = 'I'
    norm.fermenter_id = id

    const step = stepRepo.update(norm)

    const cache = api.cache.get<Record<string, Row>>('fermenter')
    const fermenter = cache?.[String(id)]
    if (fermenter) {
      const steps = (fermenter.steps as Row[] | undefined) ?? []
      steps.push(step)
      fermenter.steps = steps
    }

    api.emit('UPDATE_FERMENTER', cache?.[String(id)])
    return noContent()
  })

  router.add('PUT', '/api/fermenter/<int:id>/step/<int:stepid>', 'FermenterView:putStep', async (ctx) => {
    const id = Number(ctx.params.id)
    const stepId = Number(ctx.params.stepid)
    const data = await ctx.json<Row>()
    const norm = normaliseStepData(data)
    norm.id = stepId
    norm.fermenter_id = id

    const cache = api.cache.get<Record<string, Row>>('fermenter')
    const fermenter = cache?.[String(id)]
    if (fermenter) {
      const steps = (fermenter.steps as Row[] | undefined) ?? []
      for (const s of steps) {
        if (Number(s.id) === stepId) {
          Object.assign(s, norm)
          break
        }
      }
      stepRepo.update(norm)
    }

    api.emit('UPDATE_FERMENTER', cache?.[String(id)])
    return noContent()
  })

  router.add('DELETE', '/api/fermenter/<int:id>/step/<int:stepid>', 'FermenterView:deleteStep', (ctx) => {
    const id = Number(ctx.params.id)
    const stepId = Number(ctx.params.stepid)

    const cache = api.cache.get<Record<string, Row>>('fermenter')
    const fermenter = cache?.[String(id)]
    if (fermenter) {
      const steps = (fermenter.steps as Row[] | undefined) ?? []
      const idx = steps.findIndex((s) => Number(s.id) === stepId)
      if (idx >= 0) {
        steps.splice(idx, 1)
        fermenter.steps = steps
      }
    }
    stepRepo.delete(stepId)
    api.emit('UPDATE_FERMENTER', cache?.[String(id)])
    return noContent()
  })

  // sort
  router.add('POST', '/api/fermenter/<int:id>/step/sort', 'FermenterView:sortSteps', async (ctx) => {
    const id = Number(ctx.params.id)

    const cache = api.cache.get<Record<string, Row>>('fermenter')
    const fermenter = cache?.[String(id)]
    if (!fermenter) return json({ message: `There is no fermenter ${id}` }, 404)

    const steps = (fermenter.steps as Row[] | undefined) ?? []
    if (steps.length === 0) return json({ message: 'The fermenter has no steps' }, 400)

    const running = (api.cache.get<Record<string, unknown>>('fermenter_task')?.[String(id)] !== undefined) ||
      steps.some((s) => s.state === 'A')

    if (running) {
      return json({
        message: 'The fermentation is running. Stop it before changing the order of the steps.',
      }, 409)
    }

    const body = await ctx.json<unknown>()
    const pairs = parseStepOrder(body, steps)
    if (!pairs) {
      return json({
        message: 'The body must list every step of the fermenter with its new order.',
      }, 400)
    }

    stepRepo.setOrders(pairs)

    const byId = new Map(steps.map((s) => [Number(s.id), s]))
    fermenter.steps = pairs
      .slice()
      .sort((a, b) => a[1] - b[1])
      .map(([stepId]) => byId.get(stepId)!)

    api.emit('UPDATE_FERMENTER', fermenter)
    return noContent()
  })

  // start fermentation
  router.add('POST', '/api/fermenter/<int:id>/start', 'FermenterView:start_fermentation', (ctx) => {
    const id = Number(ctx.params.id)

    const cache = api.cache.get<Record<string, Row>>('fermenter')
    const fermenter = cache?.[String(id)]
    if (!fermenter) return noContent()

    const steps = (fermenter.steps as Row[] | undefined) ?? []

    const activeStep = steps.find((s) => s.state === 'A')
    const inactiveStep = steps.find((s) => s.state === 'I')

    if (activeStep) {
      activeStep.state = 'D'
      activeStep.end = nowSeconds()
      stepRepo.updateState(Number(activeStep.id), 'D')

      const taskCache = api.cache.get<Record<string, unknown>>('fermenter_task')
      if (taskCache) delete taskCache[String(id)]
    }

    if (inactiveStep) {
      const currentTemp = 20 // Placeholder for get_sensor_value
      inactiveStep.state = 'A'
      inactiveStep.start = nowSeconds()
      inactiveStep.direction = currentTemp >= Number(inactiveStep.temp) ? 'C' : 'H'
      stepRepo.updateState(Number(inactiveStep.id), 'A')

      // Set target temp on fermenter
      fermenter.target_temp = Number(inactiveStep.temp)
      api.emit('UPDATE_FERMENTER_TARGET_TEMP', { id, target_temp: Number(inactiveStep.temp) })

      const taskCache = api.cache.getOr<Record<string, unknown>>('fermenter_task', () => ({}))
      taskCache[String(id)] = inactiveStep
      api.cache.set('fermenter_task', taskCache)
    }

    api.emit('UPDATE_FERMENTER', fermenter)
    return noContent()
  })

  // reset
  router.add('POST', '/api/fermenter/<int:id>/reset', 'FermenterView:reset', (ctx) => {
    const id = Number(ctx.params.id)
    resetFermenter(api, stepRepo, id)
    api.emit('UPDATE_FERMENTER', api.cache.get<Record<string, Row>>('fermenter')?.[String(id)])
    return noContent()
  })

  // automatic toggle
  router.add('POST', '/api/fermenter/<int:id>/automatic', 'FermenterView:toggle', async (ctx) => {
    const id = Number(ctx.params.id)
    const cache = api.cache.get<Record<string, Row>>('fermenter')
    const fermenter = cache?.[String(id)]
    if (!fermenter) return noContent()

    const wasRunning = fermenter.state === true

    try {
      if (wasRunning) {
        // stop
        fermenter.state = false
        const taskCache = api.cache.get<Record<string, unknown>>('fermenter_task')
        if (taskCache) delete taskCache[String(id)]
      } else {
        // start - would need controller instantiation (M5)
        fermenter.state = true
      }

      // Start/stop controller instance if present
      const instance = (fermenter as Record<string, unknown>).instance as { run?: () => unknown; stop?: () => unknown } | undefined
      if (fermenter.state === true) {
        if (instance && typeof instance.run === 'function') {
          try {
            void instance.run()
          } catch (error) {
            api.log('warning', `Fermenter ${id} controller run() failed: ${String(error)}`)
          }
        }
      } else if (instance && typeof instance.stop === 'function') {
        try {
          void instance.stop()
        } catch (error) {
          api.log('warning', `Fermenter ${id} controller stop() failed: ${String(error)}`)
        }
      }
    } catch (error) {
      api.log('error', `Switching the fermenter ${id} failed: ${String(error)}`)
      api.notify('Switching the fermenter failed', 'Please check the configuration of the fermenter', 'danger', null)
      fermenter.state = false
      return noContent()
    }

    api.emit('UPDATE_FERMENTER', fermenter)
    return noContent()
  })

  // check step
  router.add('GET', '/api/fermenter/check_step/', 'FermenterView:check_step', (ctx) => {
    const taskCache = api.cache.get<Record<string, unknown>>('fermenter_task') || {}
    const ferms = Object.values(taskCache) as Row[]
    for (const ferm of ferms) {
      const id = Number(ferm.id)
      const step = ferm as Row
      const currentTemp = 20 // Placeholder for get_sensor_value

      if (currentTemp >= Number(step.temp)) {
        // high direction - temp reached
        const temp = Number(step.temp)
        stepRepo.update({ id: Number(step.id), state: 'A', direction: currentTemp >= Number(step.temp) ? 'C' : 'H' })
        api.emit('UPDATE_FERMENTER_TARGET_TEMP', { id, target_temp: temp })
      } else if (currentTemp <= Number(step.temp)) {
        // cold direction - temp reached
        const temp = Number(step.temp)
        stepRepo.update({ id: Number(step.id), state: 'A', direction: currentTemp >= Number(step.temp) ? 'C' : 'H' })
        api.emit('UPDATE_FERMENTER_TARGET_TEMP', { id, target_temp: temp })
      }
    }
    return noContent()
  })

  // get fermenter
  router.add('GET', '/api/fermenter/get_fermenter/<id>', 'FermenterView:get_fermenter', (ctx) => {
    const id = Number(ctx.params.id)
    const fermenter = api.cache.get<Record<string, Row>>('fermenter')?.[String(id)] ?? null
    return json(fermenter)
  })

  // target temp reached
  router.add('GET', '/api/fermenter/target_temp_reached/<id>/<step>', 'FermenterView:target_temp_reached', (ctx) => {
    const id = Number(ctx.params.id)
    const step = Number(ctx.params.step)
    const taskCache = api.cache.getOr<Record<string, unknown>>('fermenter_task', () => ({}))
    if (taskCache[String(id)]) {
      const fermenterStep = stepRepo.one(step)
      if (fermenterStep) {
        const timestamp = Date.now()
        stepRepo.updateTimer(step, timestamp)
        api.emit('UPDATE_FERMENTER_TARGET_TEMP', { id, target_temp: Number(fermenterStep.temp) })
      }
    }
    return noContent()
  })

  // Cache-Callback fuer /api/system/dump
  api.cache.set('fermenter', new CacheCallback(() => fermenterRepo.all()))
}

function resetFermenter(api: Api, stepRepo: FermenterStepRepository, id: number): void {
  stepRepo.resetAll(id)
  const cache = api.cache.get<Record<string, Row>>('fermenter')
  const fermenter = cache?.[String(id)]
  if (fermenter) {
    fermenter.steps = stepRepo.byFermenter(id)
  }
  const taskCache = api.cache.get<Record<string, unknown>>('fermenter_task')
  if (taskCache) delete taskCache[String(id)]
}