/**
 * Einstiegspunkt - Gegenstueck zu run.py.
 *
 * Der Aufbau selbst liegt in app.ts, damit Tests denselben Bootpfad
 * benutzen.
 */
import { join } from 'node:path'
import { createApp } from './app.ts'
import type { Api } from './core/api.ts'
import { logLevel, logToStdout, parsePort, rootDir } from './env.ts'
import { createLogger } from './logger.ts'

function resolvePort(api: Api): number {
  const fromEnv = parsePort(process.env.CBPI_PORT)
  if (fromEnv !== null) return fromEnv

  const fromConfig = Number(api.getConfigParameter('port', 5000))
  return Number.isInteger(fromConfig) && fromConfig > 0 ? fromConfig : 5000
}

async function main(): Promise<void> {
  const root = rootDir()
  const logger = createLogger({
    level: logLevel(),
    toStdout: logToStdout(),
    file: join(root, 'logs', 'app.log'),
  })

  const app = await createApp({ root, logger })

  const port = resolvePort(app.api)

  app.httpServer.listen(port, '0.0.0.0', () => {
    logger.info('##########################################')
    logger.info(`### STARTUP COMPLETE (TS, ${app.router.size} routes)`)
    logger.info('##########################################')
    logger.info(`Listening on 0.0.0.0:${port}`)
  })

  const shutdown = (signal: string) => {
    logger.info(`${signal} received, shutting down`)
    void app.close().then(() => process.exit(0))
  }

  process.on('SIGINT', () => shutdown('SIGINT'))
  process.on('SIGTERM', () => shutdown('SIGTERM'))
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.stack ?? error.message : String(error)
  process.stderr.write(`Startup failed: ${message}\n`)
  process.exit(1)
})
