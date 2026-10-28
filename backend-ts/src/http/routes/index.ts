/**
 * Routen-Registry.
 *
 * Jeder Eintrag muss in tools/routes_baseline.json stehen
 * (test/routes.test.ts prueft das). Regeln werden woertlich uebernommen,
 * inklusive Trailing Slash und <int:...>-Konvertern.
 */
import { join } from 'node:path'
import type { Api } from '../../core/api.ts'
import type { Db, Table } from '../../db.ts'
import type { Router } from '../router.ts'
import { registerLogModule } from '../../modules/logs.ts'
import { StepRepository, registerStepModule } from '../../modules/step.ts'
import { ActorRepository, registerActorModule } from '../../modules/actor.ts'
import { SensorRepository, registerSensorModule } from '../../modules/sensor.ts'
import type { PluginInstance } from '../../plugins/contract.ts'
import { redirect } from '../respond.ts'
import { serveFile } from '../static.ts'
import { registerConfigRoutes } from './config.ts'
import { registerNotificationRoutes } from './notification.ts'
import { registerSystemRoutes } from './system.ts'

export interface RouteDependencies {
  root: string
  configTable: Table
  db: Db
  logsDir: string
  pluginHost: { create(kind: string, name: string, api: Api, config?: Record<string, unknown>): PluginInstance | undefined }
}

export function registerRoutes(
  router: Router,
  api: Api,
  dependencies: RouteDependencies,
): void {
  const uiStatic = join(dependencies.root, 'modules', 'ui', 'static')
  const appStatic = join(dependencies.root, 'modules', 'static')

  router
    .add('GET', '/', 'index', () => redirect('ui'))
    .add('GET', '/ui/', 'react.index', () =>
      serveFile(uiStatic, 'index.html'),
    )
    .add('GET', '/ui/static/<path:filename>', 'react.static', (ctx) =>
      serveFile(uiStatic, ctx.params.filename ?? ''),
    )
    .add('GET', '/static/<path:filename>', 'static', (ctx) =>
      serveFile(appStatic, ctx.params.filename ?? ''),
    )

  registerConfigRoutes(router, api, dependencies.configTable)
  registerNotificationRoutes(router, api)
  registerSystemRoutes(router, api)
  registerLogModule(router, api, dependencies.logsDir)

  const stepRepository = new StepRepository(dependencies.db)
  registerStepModule(router, api, stepRepository)

  registerActorModule(
    router,
    api,
    dependencies.pluginHost,
    new ActorRepository(dependencies.db),
  )
  registerSensorModule(
    router,
    api,
    dependencies.pluginHost,
    new SensorRepository(dependencies.db),
  )
}
