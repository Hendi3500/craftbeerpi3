/**
 * Logging mit demselben Format wie das Python-Backend:
 *
 *   2026-10-28 10:00:00,123 - INFO - message
 *
 * Standardziel ist logs/app.log, mit CBPI_LOG_STDOUT=1 die Konsole.
 * Geschrieben wird synchron: das Volumen ist klein, und ein Logeintrag,
 * der beim Absturz noch im Puffer steht, ist genau der, den man braucht.
 */
import { appendFileSync, mkdirSync } from 'node:fs'
import { dirname } from 'node:path'

export type Level = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'

const ORDER: Record<Level, number> = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40 }

export interface Logger {
  debug(message: string): void
  info(message: string): void
  warning(message: string): void
  error(message: string): void
}

function timestamp(): string {
  const d = new Date()
  const pad = (n: number, width = 2) => String(n).padStart(width, '0')
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())},` +
    pad(d.getMilliseconds(), 3)
  )
}

export function createLogger(options: {
  level: string
  toStdout: boolean
  file: string
}): Logger {
  const configured = (options.level as Level) in ORDER ? (options.level as Level) : 'INFO'
  const threshold = ORDER[configured]

  if (!options.toStdout) {
    mkdirSync(dirname(options.file), { recursive: true })
  }

  const write = (level: Level, message: string) => {
    if (ORDER[level] < threshold) return
    const line = `${timestamp()} - ${level} - ${message}\n`
    if (options.toStdout) {
      process.stdout.write(line)
    } else {
      appendFileSync(options.file, line)
    }
  }

  return {
    debug: (m) => write('DEBUG', m),
    info: (m) => write('INFO', m),
    warning: (m) => write('WARNING', m),
    error: (m) => write('ERROR', m),
  }
}
