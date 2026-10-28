/**
 * CraftBeerPi-Fassade - das, was Plugins und Module als `cbpi` kennen.
 *
 * In M0 sind nur die Teile implementiert, die Config und Notification
 * brauchen. Actor/Sensor/Kettle-Methoden folgen in M2. Die Signatur der
 * vorhandenen Methoden bleibt dabei stabil, damit Plugins spaeter nicht
 * zweimal angefasst werden muessen.
 */
import { randomUUID } from 'node:crypto'
import { appendFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import type { Logger } from '../logger.ts'
import type { Row, Table } from '../db.ts'
import type { Cache } from './cache.ts'
import { EventBus } from './events.ts'

/** Der Socket ist reiner Push-Kanal in den Namespace /brew. */
export interface BrewSocket {
  emitToBrew(event: string, data: unknown): void
}

export interface Message {
  id: string | number
  type: string
  headline: string
  message: string
  timeout?: number | null
  timestamp?: number
  read?: boolean
  [key: string]: unknown
}

export interface ApiOptions {
  cache: Cache
  bus: EventBus
  socket: BrewSocket
  logger: Logger
  configTable: Table
  /** Verzeichnis fuer action.log (Default <root>/logs). */
  logsDir: string
}

export class Api {
  readonly cache: Cache
  readonly bus: EventBus
  private readonly socket: BrewSocket
  private readonly logger: Logger
  private readonly configTable: Table
  private readonly logsDir: string

  constructor(options: ApiOptions) {
    this.cache = options.cache
    this.bus = options.bus
    this.socket = options.socket
    this.logger = options.logger
    this.configTable = options.configTable
    this.logsDir = options.logsDir
  }

  /** Server -> Client, Namespace /brew. */
  emit(event: string, data: unknown): void {
    this.socket.emitToBrew(event, data)
  }

  /**
   * notify() wie im Kern: Beep (M4), Message bauen, ueber den Eventbus
   * schicken. Der Notification-Handler legt sie in den Cache und
   * emittiert NOTIFY.
   */
  notify(
    headline: string,
    message: string,
    type = 'success',
    timeout: number | null = 5000,
  ): Message {
    return this.emitMessage({
      id: randomUUID(),
      type,
      headline,
      message,
      timeout,
    })
  }

  /** Akzeptiert - wie emit_message - einen Text oder eine fertige Message. */
  emitMessage(message: string | Message): Message {
    const value: Message =
      typeof message === 'string'
        ? {
            id: randomUUID(),
            type: 'info',
            headline: 'CraftBeerPi',
            message,
            timeout: null,
          }
        : message

    if (value.timestamp === undefined || value.timestamp === null) {
      value.timestamp = Date.now()
    }

    this.bus.emit('MESSAGE', value)
    return value
  }

  emitEvent(name: string, payload?: unknown): void {
    this.bus.emit(name, payload)
  }

  messages(): Message[] {
    return this.cache.getOr<Message[]>('messages', () => [])
  }

  config(): Record<string, Row> {
    return this.cache.getOr<Record<string, Row>>('config', () => ({}))
  }

  configEntry(name: string): Row | null {
    const entry = this.config()[name]
    return entry ?? null
  }

  getConfigParameter<T = unknown>(key: string, fallback: T): T {
    const entry = this.config()[key]
    if (!entry) return fallback
    return entry.value as T
  }

  /**
   * Config-Parameter schreiben. Es wird - wie im Kern nach dem Fix -
   * das vollstaendige Objekt geschrieben, nicht nur name und value.
   */
  setConfigParameter(name: string, value: unknown): Row {
    const entry = this.configEntry(name)
    if (!entry) {
      throw new Error(`Unknown config parameter: ${name}`)
    }

    const updated = this.configTable.update({ ...entry, value })
    this.config()[name] = updated
    this.emit('UPDATE_CONFIG', updated)
    return updated
  }

  /** Inhalt von /api/system/dump. */
  dump(): Record<string, unknown> {
    return this.cache.snapshot()
  }

  log(level: 'debug' | 'info' | 'warning' | 'error', message: string): void {
    this.logger[level](message)
  }

  /**
   * cbpi.log_action: eine Zeile in logs/action.log. Bewusst ohne Logger,
   * weil /api/logs/actions genau diese Datei liest.
   */
  logAction(text: string): void {
    mkdirSync(this.logsDir, { recursive: true })
    appendFileSync(
      join(this.logsDir, 'action.log'),
      `${localTimestamp(new Date())},${text}\n`,
    )
  }
}

function localTimestamp(date: Date): string {
  const pad = (value: number): string => String(value).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}
