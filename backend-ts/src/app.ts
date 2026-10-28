/**
 * Aufbau der Anwendung, ohne zu lauschen.
 *
 * Getrennt von index.ts, damit Tests denselben Bootpfad benutzen wie der
 * Server. Ein Test, der die Verdrahtung nachbaut, prueft die Verdrahtung
 * nicht.
 */
import { createServer, type Server as HttpServer } from 'node:http'
import { join } from 'node:path'
import type { Server as SocketServer } from 'socket.io'
import { Api, type Message } from './core/api.ts'
import { Cache } from './core/cache.ts'
import { EventBus } from './core/events.ts'
import { Db, Table } from './db.ts'
import { dbFile, rootDir } from './env.ts'
import { Router } from './http/router.ts'
import { initConfigCache } from './http/routes/config.ts'
import { registerRoutes } from './http/routes/index.ts'
import { setJsonDiagnostics } from './json.ts'
import { createLogger, type Logger } from './logger.ts'
import { ManifestPluginHost } from './plugins/host.ts'
import type { PluginManifest } from './plugins/contract.ts'
import { createSocket } from './socket.ts'

/**
 * Schluessel von cbpi.cache. /api/system/dump gibt sie aus, deshalb ist
 * die Menge Teil des Vertrags. Die leeren Container entsprechen dem
 * Stand nach dem Python-Boot (BaseView.init_cache legt sie an).
 */
const CACHE_SEED = {
  config: {},
  actor_types: {},
  sensor_types: {},
  sensors: {},
  sensor_instances: {},
  init: [],
  background: [],
  step_types: {},
  controller_types: {},
  messages: [],
  plugins: {},
  fermentation_controller_types: {},
  fermenter_task: {},
  actors: {},
  kettle: {},
  fermenter: {},
  steps: [],
}

export interface AppOptions {
  root?: string
  database?: string
  logger?: Logger
  /** Default <root>/logs; Tests zeigen damit auf ein temporaeres Verzeichnis. */
  logsDir?: string
  /** Programmatisch registrierte Plugins (Tests, Core-Plugins). */
  plugins?: PluginManifest[]
}

export interface App {
  root: string
  db: Db
  api: Api
  router: Router
  io: SocketServer
  httpServer: HttpServer
  plugins: ManifestPluginHost
  close(): Promise<void>
}

export async function createApp(options: AppOptions = {}): Promise<App> {
  const root = options.root ?? rootDir()
  const logger =
    options.logger ??
    createLogger({ level: 'INFO', toStdout: false, file: join(root, 'logs', 'app.log') })

  const db = new Db(options.database ?? dbFile(root))
  db.initSchema(root)
  const migration = db.migrate(root)
  if (migration.applied.length > 0) {
    logger.info(`APPLIED DB FILES: ${migration.applied.join(', ')}`)
  }

  const configTable = new Table(db, {
    name: 'config',
    fields: ['type', 'value', 'description', 'options'],
    primaryKey: 'name',
    jsonFields: ['options'],
  })

  const logsDir = options.logsDir ?? join(root, 'logs')
  const cache = new Cache(CACHE_SEED)
  const bus = new EventBus()
  const httpServer = createServer()

  const api = new Api({
    cache,
    bus,
    socket: {
      emitToBrew: (event, data) => {
        io.of('/brew').emit(event, data)
      },
    },
    logger,
    configTable,
    logsDir,
  })

  const io = createSocket(httpServer)

  // Socket.IO Event-Wiring: bus Events -> /brew Namespace
  bus.on('SENSOR_UPDATE', (payload: unknown) => io.of('/brew').emit('SENSOR_UPDATE', payload))
  bus.on('SWITCH_ACTOR', (actor: unknown) => io.of('/brew').emit('SWITCH_ACTOR', actor))
  bus.on('UPDATE_KETTLE', (kettleIdOrData: unknown) => {
    const id = typeof kettleIdOrData === 'number'
      ? kettleIdOrData
      : (kettleIdOrData as Record<string, unknown>).id
    const kettle = api.cache.get('kettle') as Record<string, unknown> | undefined
    io.of('/brew').emit('UPDATE_KETTLE', kettle?.[String(id)] ?? { id })
  })
  bus.on('UPDATE_KETTLE_TARGET_TEMP', (data: unknown) => io.of('/brew').emit('UPDATE_KETTLE_TARGET_TEMP', data))
  bus.on('UPDATE_FERMENTER', (fermenter: unknown) => {
    const cacheFermenter = api.cache.get<Record<string, unknown>>('fermenter')
    let fermenterId: number | unknown = fermenter
    if (typeof fermenter === 'object' && fermenter !== null && 'id' in fermenter) {
      fermenterId = (fermenter as Record<string, unknown>).id ?? fermenter
    }
    io.of('/brew').emit('UPDATE_FERMENTER', cacheFermenter?.[String(fermenterId)] ?? fermenter)
  })
  bus.on('UPDATE_FERMENTER_TARGET_TEMP', (data: unknown) => io.of('/brew').emit('UPDATE_FERMENTER_TARGET_TEMP', data))
  bus.on('UPDATE_FERMENTER_BREWNAME', (data: unknown) => io.of('/brew').emit('UPDATE_FERMENTER_BREWNAME', data))
  bus.on('UPDATE_ALL_STEPS', (steps: unknown) => io.of('/brew').emit('UPDATE_ALL_STEPS', steps))
  bus.on('UPDATE_CONFIG', (config: unknown) => io.of('/brew').emit('UPDATE_CONFIG', config))
  bus.on('NOTIFY', (message: unknown) => io.of('/brew').emit('NOTIFY', message))
  bus.on('NOTIFY_DISMISS', (id: unknown) => io.of('/brew').emit('NOTIFY_DISMISS', { id }))
  bus.on('RESTART_SCHEDULED', (data: unknown) => io.of('/brew').emit('RESTART_SCHEDULED', data))

  const router = new Router(logger)
  const plugins = new ManifestPluginHost(root, logger)

  registerRoutes(router, api, {
    root,
    configTable,
    db,
    logsDir,
    pluginHost: plugins,
  })
  initConfigCache(api, configTable)

  for (const manifest of options.plugins ?? []) plugins.register(manifest)
  await plugins.loadAll()
  plugins.populate(cache)
  plugins.createAll(api, cache)

  setJsonDiagnostics({
    unknown: (typeName) => {
      logger.debug(`JSON: unknown type ${typeName} becomes null`)
    },
  })

  // MESSAGE -> Cache (nur persistente) und NOTIFY an die Clients.
  bus.on('MESSAGE', (payload) => {
    const message = payload as Message
    if (message.timeout === undefined || message.timeout === null) {
      api.messages().push(message)
    }
    api.emit('NOTIFY', message)
  })

  // Wie modules/notification/__init__.py: einmalige Spenden-Notification.
  if (api.getConfigParameter('donation_notification', 'YES') === 'YES') {
    api.messages().push({
      id: api.messages().length,
      type: 'info',
      headline: 'Support CraftBeerPi with your donation',
      message: 'You will find the PayPay Donation button in the system menu',
      read: false,
    } as Message)
  }

  httpServer.on('request', (req, res) => {
    void router.handle(req, res)
  })

  return {
    root,
    db,
    api,
    router,
    io,
    httpServer,
    plugins,
    close: () =>
      new Promise<void>((resolve) => {
        io.close()
        if (!httpServer.listening) {
          db.close()
          resolve()
          return
        }
        httpServer.close(() => {
          db.close()
          resolve()
        })
      }),
  }
}
