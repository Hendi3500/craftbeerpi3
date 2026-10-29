/**
 * Controller-Laufzeit - Gegenstueck zu modules/core/controller.py.
 *
 * Python-Controller sind blockierende Threads: `run()` laeuft, bis
 * `stop()` das Flag setzt. In Node gibt es keine Threads, deshalb ist
 * `run()` hier eine asynchrone Schleife. Kettle/Fermenter rufen sie mit
 * `void instance.run()` auf und `stop()` beendet sie ueber das Flag und
 * weckt ein laufendes `sleep()`.
 *
 * Die Helfer (heater_on, get_temp, get_target_temp, actor_power, ...)
 * arbeiten direkt auf dem Cache - genau wie die Python-Vorbilder. Damit
 * funktionieren die portierten Regler ohne Zugriff auf die Router-Module.
 */
import type { Api } from '../core/api.ts'
import type { Row } from '../db.ts'
import type { PluginInstance } from './contract.ts'

export interface ControllerConfig {
  api: Api
  heater?: unknown
  sensor?: unknown
  kettle_id?: unknown
  fermenter_id?: unknown
  cooler?: unknown
  [key: string]: unknown
}

type Map = Record<string, Row>

function cacheMap(api: Api, key: string): Map | null {
  const value = api.cache.get<Map>(key)
  if (!value || Array.isArray(value)) return null
  return value
}

function asNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export abstract class ControllerBase implements PluginInstance {
  protected readonly config: ControllerConfig
  readonly api: Api

  private running = false
  private wake: (() => void) | null = null

  constructor(config: ControllerConfig) {
    this.config = config
    this.api = config.api
  }

  /** Property-Wert mit Vorgabe (apply_property_defaults). */
  protected value(name: string, fallback: unknown): unknown {
    const value = this.config[name]
    return value === undefined || value === null || value === '' ? fallback : value
  }

  protected number(name: string, fallback: number): number {
    return asNumber(this.value(name, fallback)) ?? fallback
  }

  protected text(name: string, fallback = ''): string {
    const value = this.value(name, fallback)
    return value === undefined || value === null ? fallback : String(value)
  }

  is_running(): boolean {
    return this.running
  }

  /** Python setzt das Flag im Konstruktor-Pfad (init) bereits. */
  init(): void {
    this.running = true
  }

  stop(): void {
    this.running = false
    const wake = this.wake
    this.wake = null
    wake?.()
  }

  /** Unterbrechbares sleep; stop() weckt sofort. */
  async sleep(seconds: number): Promise<void> {
    if (!this.running) return
    const ms = Math.max(0, seconds * 1000)
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        this.wake = null
        resolve()
      }, ms)
      this.wake = () => {
        clearTimeout(timer)
        resolve()
      }
    })
  }

  notify(
    headline: string,
    message: string,
    type = 'success',
    timeout: number | null = 5000,
  ): void {
    this.api.notify(headline, message, type, timeout)
  }

  /**
   * Einstiegspunkt fuer Kettle/Fermenter. Setzt das Running-Flag selbst,
   * weil der Aufrufer `run()` ohne vorheriges `init()` startet.
   */
  async run(): Promise<void> {
    if (this.running) {
      await this.loop()
      return
    }
    this.running = true
    try {
      await this.loop()
    } catch (error) {
      this.api.log(
        'error',
        `Controller loop failed: ${error instanceof Error ? error.message : String(error)}`,
      )
    } finally {
      this.running = false
    }
  }

  /** Die eigentliche Regelschleife. */
  protected abstract loop(): Promise<void>

  // --- ActorController ----------------------------------------------------

  actor_on(power = 100, id?: number): void {
    const actorId = id ?? this.heaterId()
    if (actorId === null) return
    const actor = cacheMap(this.api, 'actors')?.[String(actorId)]
    if (!actor) {
      this.api.log('warning', `Controller: actor ${actorId} not in cache`)
      return
    }
    const instance = actor.instance as PluginInstance | undefined
    if (instance && typeof instance.on === 'function') void instance.on(power)
    actor.state = 1
    actor.power = power
    this.api.emit('SWITCH_ACTOR', actor)
  }

  actor_off(id?: number): void {
    const actorId = id ?? this.heaterId()
    if (actorId === null) return
    const actor = cacheMap(this.api, 'actors')?.[String(actorId)]
    if (!actor) {
      this.api.log('warning', `Controller: actor ${actorId} not in cache`)
      return
    }
    const instance = actor.instance as PluginInstance | undefined
    if (instance && typeof instance.off === 'function') void instance.off()
    actor.state = 0
    this.api.emit('SWITCH_ACTOR', actor)
  }

  actor_power(power: number, id?: number): void {
    const actorId = id ?? this.heaterId()
    if (actorId === null) return
    const actor = cacheMap(this.api, 'actors')?.[String(actorId)]
    if (!actor) {
      this.api.log('warning', `Controller: actor ${actorId} not in cache`)
      return
    }
    const instance = actor.instance as PluginInstance | undefined
    if (instance && typeof instance.set_power === 'function') void instance.set_power(power)
    actor.power = power
    this.api.emit('SWITCH_ACTOR', actor)
  }

  // --- SensorController ---------------------------------------------------

  /** Entspricht cbpi.get_sensor_value(id): letzter Wert aus dem Cache. */
  get_sensor_value(id?: number): number | null {
    const sensorId = id ?? this.sensorId()
    if (sensorId === null) return null
    const sensor = cacheMap(this.api, 'sensors')?.[String(sensorId)]
    if (!sensor) return null
    const direct = asNumber(sensor.last_value)
    if (direct !== null) return direct
    const instance = sensor.instance as PluginInstance | undefined
    if (instance && typeof instance.get_value === 'function') {
      const value = asNumber(instance.get_value())
      if (value !== null) {
        sensor.last_value = value
        return value
      }
    }
    return null
  }

  // --- Kessel/Fermenter ---------------------------------------------------

  protected kettleId(): number | null {
    return asNumber(this.config.kettle_id)
  }

  protected fermenterId(): number | null {
    return asNumber(this.config.fermenter_id)
  }

  private heaterId(): number | null {
    const kettle = cacheMap(this.api, 'kettle')?.[String(this.kettleId() ?? '')]
    if (kettle) {
      const heater = asNumber(kettle.heater)
      if (heater !== null) return heater
    }
    const fermenter = cacheMap(this.api, 'fermenter')?.[String(this.fermenterId() ?? '')]
    if (fermenter) {
      const heater = asNumber(fermenter.heater)
      if (heater !== null) return heater
    }
    return asNumber(this.config.heater)
  }

  private coolerId(): number | null {
    const fermenter = cacheMap(this.api, 'fermenter')?.[String(this.fermenterId() ?? '')]
    if (fermenter) {
      const cooler = asNumber(fermenter.cooler)
      if (cooler !== null) return cooler
    }
    return asNumber(this.config.cooler)
  }

  protected sensorId(): number | null {
    const kettle = cacheMap(this.api, 'kettle')?.[String(this.kettleId() ?? '')]
    if (kettle) {
      const sensor = asNumber(kettle.sensor)
      if (sensor !== null) return sensor
    }
    const fermenter = cacheMap(this.api, 'fermenter')?.[String(this.fermenterId() ?? '')]
    if (fermenter) {
      const sensor = asNumber(fermenter.sensor)
      if (sensor !== null) return sensor
    }
    return asNumber(this.config.sensor)
  }

  get_temp(): number | null {
    return this.get_sensor_value()
  }

  get_target_temp(): number | null {
    const kettle = cacheMap(this.api, 'kettle')?.[String(this.kettleId() ?? '')]
    if (kettle) return asNumber(kettle.target_temp)
    const fermenter = cacheMap(this.api, 'fermenter')?.[String(this.fermenterId() ?? '')]
    if (fermenter) return asNumber(fermenter.target_temp)
    return asNumber(this.config.target_temp)
  }

  heater_on(power = 100): void {
    this.actor_on(power, this.heaterId() ?? undefined)
  }

  heater_off(): void {
    this.actor_off(this.heaterId() ?? undefined)
  }

  cooler_on(power = 100): void {
    this.actor_on(power, this.coolerId() ?? undefined)
  }

  cooler_off(): void {
    this.actor_off(this.coolerId() ?? undefined)
  }
}

/** Controller fuer Kessel (modules.core.controller.KettleController). */
export abstract class KettleController extends ControllerBase {}

/** Controller fuer Gaerbehaelter (modules.core.controller.FermenterController). */
export abstract class FermenterController extends ControllerBase {}

/**
 * PID wie modules/plugins/CascadeControl/__init__.py: ein einfacher
 * idealer PID mit Begrenzung von Ausgang und Integrator.
 */
export class PID {
  readonly kp: number
  readonly ki: number
  readonly kd: number
  readonly output_min: number
  readonly output_max: number
  readonly integrator_max: number
  readonly integrator_error_max: number

  integrator: number
  last_time = 0
  last_error = 0

  constructor(
    kp: number,
    ki: number,
    kd: number,
    outputMin: number,
    outputMax: number,
    integratorErrorMax: number,
    integratorInitial: number,
    private readonly clock: () => number = () => Date.now() / 1000,
  ) {
    this.kp = kp
    this.ki = ki
    this.kd = kd
    this.output_min = outputMin
    this.output_max = outputMax
    this.integrator_max =
      ki === 0 ? 0 : Math.abs((outputMax - outputMin) / ki)
    this.integrator_error_max = Math.abs(integratorErrorMax)
    this.integrator =
      Math.abs(integratorInitial) > Math.abs(this.integrator_max)
        ? this.integrator_max
        : integratorInitial
  }

  update(current: number, target: number): number {
    const clamp = (value: number): number =>
      Math.max(Math.min(value, this.output_max), this.output_min)

    if (this.last_time === 0) {
      this.last_time = this.clock()
      const error = target - current
      this.last_error = error
      return clamp(this.kp * error)
    }

    const now = this.clock()
    const iteration = now - this.last_time
    this.last_time = now

    const error = target - current
    const integratorError = Math.max(
      Math.min(error, this.integrator_error_max),
      -this.integrator_error_max,
    )
    this.integrator = Math.max(
      Math.min(this.integrator + integratorError * iteration, this.integrator_max),
      -this.integrator_max,
    )
    const derivative = iteration === 0 ? 0 : (error - this.last_error) / iteration
    this.last_error = error

    return clamp(
      this.kp * error + this.ki * this.integrator + this.kd * derivative,
    )
  }
}

/** Hysterese mit minimalen An-/Auszeiten wie im CascadeControl-Plugin. */
export class Hysteresis {
  readonly positive: boolean
  readonly on_min: number
  readonly on_max: number
  readonly off_min: number

  last_change = Date.now() / 1000
  on = false

  constructor(
    positive: boolean,
    onMin: number,
    onMax: number,
    offMin: number,
    private readonly clock: () => number = () => Date.now() / 1000,
  ) {
    this.positive = positive
    this.on_min = onMin
    this.on_max = onMax
    this.off_min = offMin
  }

  update(current: number, target: number): boolean {
    const interval = this.clock() - this.last_change
    const shouldOn = this.positive ? current <= target : current >= target

    if (shouldOn) {
      if (this.on) {
        if (interval > this.on_max) {
          this.last_change = this.clock()
          this.on = false
        }
      } else if (interval < this.off_min) {
        this.on = false
      } else {
        this.last_change = this.clock()
        this.on = true
      }
    } else if (this.on) {
      if (interval < this.on_min) {
        this.on = true
      } else {
        this.last_change = this.clock()
        this.on = false
      }
    } else {
      this.on = false
    }

    return this.on
  }
}
