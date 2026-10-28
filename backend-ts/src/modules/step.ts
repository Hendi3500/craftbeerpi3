/**
 * /api/step - erste echte Domain-Ressource.
 *
 * Steps brauchen keine Hardware und keine Plugins fuer CRUD, Sortieren
 * und Zuruecksetzen. Genau deshalb ist dieses Modul der Beweis fuer die
 * BaseView-Maschinerie (M1).
 *
 * Was noch fehlt, ist die Ausfuehrung: start/next setzen den Zustand wie
 * im Original, aber ohne step_types gibt es keine Instanz. Der Kern
 * verhaelt sich in diesem Fall genauso (init_step kehrt frueh zurueck).
 */
import type { Api } from '../core/api.ts'
import { CacheCallback } from '../json.ts'
import { Table } from '../db.ts'
import type { Db, Row } from '../db.ts'
import { registerBaseView } from '../http/baseview.ts'
import type { Router } from '../http/router.ts'
import { noContent } from '../http/respond.ts'

export class StepRepository {
  readonly table: Table
  private readonly db: Db

  constructor(db: Db) {
    this.db = db
    this.table = new Table(db, {
      name: 'step',
      fields: ['name', 'type', 'stepstate', 'state', 'start', 'end', 'order', 'config'],
      jsonFields: ['config', 'stepstate'],
      orderBy: 'order',
      asArray: true,
    })
  }

  all(): Row[] {
    return this.table.all() as Row[]
  }

  byState(state: string): Row | null {
    return this.all().find((row) => row.state === state) ?? null
  }

  maxOrder(): number | null {
    let max: number | null = null
    for (const row of this.all()) {
      const value = Number(row.order)
      if (!Number.isFinite(value)) continue
      if (max === null || value > max) max = value
    }
    return max
  }

  resetAll(): void {
    this.db.conn
      .prepare(
        'UPDATE "step" SET state = ?, stepstate = NULL, start = NULL, end = NULL',
      )
      .run('I')
  }

  updateState(id: string | number, state: string): void {
    this.db.conn.prepare('UPDATE "step" SET state = ? WHERE id = ?').run(state, id)
  }

  updateStepState(id: string | number, state: unknown): void {
    this.db.conn
      .prepare('UPDATE "step" SET stepstate = ? WHERE id = ?')
      .run(JSON.stringify(state), id)
  }

  setOrders(pairs: [number, number][]): void {
    const statement = this.db.conn.prepare(
      'UPDATE "step" SET "order" = ? WHERE id = ?',
    )
    const apply = this.db.conn.transaction(() => {
      for (const [id, order] of pairs) statement.run(order, id)
    })
    apply()
  }

  deleteAll(): void {
    this.db.conn.prepare('DELETE FROM "step"').run()
  }

  update(id: string | number, patch: Row): Row {
    return this.table.update({ id, ...patch })
  }
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000)
}

function stopStep(api: Api): void {
  const step = api.cache.get<Row | null>('active_step')
  api.cache.set('active_step', null)

  if (step) {
    // finish() gehoert der Plugin-Instanz. Ohne step_types gibt es keine.
    const kettle = step.kettleid ?? step.kettle
    if (kettle !== undefined && kettle !== null) {
      api.emitEvent('SET_TARGET_TEMP', { id: Number(kettle), temp: 0 })
    }
  }
}

function startStep(api: Api, repository: StepRepository) {
  const active = repository.byState('A')
  const inactive = repository.byState('I')

  if (active) {
    repository.updateState(active.id as number, 'D')
    repository.update(active.id as number, { end: nowSeconds() })
    stopStep(api)
  }

  if (inactive) {
    // init_step() im Original: protokolliert zuerst, prueft dann den
    // registrierten step_type und kehrt ohne Instanz zurueck (M5).
    api.logAction(`Start Step ${String(inactive.name)}`)
    api.log(
      'debug',
      `Step type "${String(inactive.type)}" is not registered yet (M5) - state is set without an instance`,
    )
    repository.update(inactive.id as number, {
      state: 'A',
      stepstate: inactive.config,
      start: nowSeconds(),
    })
  } else {
    api.logAction('Brewing Finished')
    api.notify('Brewing Finished', 'You are done!', 'success', null)
  }

  api.emit('UPDATE_ALL_STEPS', repository.all())
  return noContent()
}

export function registerStepModule(
  router: Router,
  api: Api,
  repository: StepRepository,
): void {
  registerBaseView(router, {
    base: '/api/step',
    endpoint: 'StepView',
    table: repository.table,
    api,
    // StepView hat im Original cache_key = None: CRUD geht direkt gegen
    // die Datenbank, "steps" ist nur ein Callback fuer den Dump.
    cacheKey: null,
    prePost: (data) => {
      const max = repository.maxOrder()
      data.order = max === null ? 1 : max + 1
      data.state = 'I'
    },
  })

  router
    .add('DELETE', '/api/step/', 'StepView:deleteAll', () => {
      repository.deleteAll()
      api.emit('UPDATE_ALL_STEPS', repository.all())
      return noContent()
    })
    .add('POST', '/api/step/sort', 'StepView:sort_steps', async (ctx) => {
      const pairs = await ctx.json<[number, number][]>()
      repository.setOrders(pairs)
      api.emit('UPDATE_ALL_STEPS', repository.all())
      return noContent()
    })
    .add('POST', '/api/step/reset', 'StepView:reset', () => {
      repository.resetAll()
      stopStep(api)
      api.emit('UPDATE_ALL_STEPS', repository.all())
      return noContent()
    })
    .add('POST', '/api/step/reset/current', 'StepView:resetCurrentStep', () => {
      // Ohne aktiven Schritt gibt es nichts zurueckzusetzen.
      return noContent()
    })
    .add('POST', '/api/step/action/<method>', 'StepView:action', (ctx) => {
      api.log(
        'warning',
        `Step action "${ctx.params.method ?? ''}" ignored - no active step instance (M5)`,
      )
      return noContent()
    })
    .add('POST', '/api/step/start', 'StepView:start_0', () =>
      startStep(api, repository),
    )
    .add('POST', '/api/step/next', 'StepView:start_1', () =>
      startStep(api, repository),
    )
    .add(
      'GET',
      '/api/step/init_step/<step>',
      'StepView:init_step',
      (ctx) => {
        // Im Original ist das eine Methode, die per classy als GET-Route
        // mit einem String aufgerufen wird und dann scheitert. Hier wird
        // sie sauber zu einem No-op (D-9).
        api.log(
          'debug',
          `init_step("${ctx.params.step ?? ''}") ignored - no step types registered (M5)`,
        )
        return noContent()
      },
    )
    .add('GET', '/api/step/stop_step/', 'StepView:stop_step', () => {
      stopStep(api)
      return noContent()
    })

  // /api/system/dump fuehrt den Callback aus und zeigt den aktuellen
  // Datenbankstand - wie add_cache_callback("steps", get_all) im Original.
  api.cache.set('steps', new CacheCallback(() => repository.all()))
}
