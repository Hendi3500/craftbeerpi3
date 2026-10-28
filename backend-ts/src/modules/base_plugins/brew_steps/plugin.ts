/**
 * Base-Plugin: BrewSteps
 *
 * Steps: MashStep, MashInStep (from Python modules/base_plugins/brew_steps).
 * Die Plugin-Klasse selbst ist ein einfacher Schritt, der ein Ziel-Temperatur-
 * Event sendet, Timer startet usw. Für jetzt nur als Platzhalter.
 */
import type { PluginInstance } from '../../../plugins/contract.ts'

// TypeScript-Klasse für MashStep
export class MashStep implements PluginInstance {
  kind = 'step'
  name = 'MashStep'
  module = 'modules.base_plugins.brew_steps'
  properties: Array<{ name: string, label: string, type: 'number' | 'kettle' | 'text', configurable: boolean, description?: string, default_value?: unknown, options?: unknown[] }> = []
  actions: Array<{ method: string, label: string }> = []

  // Properties
  temp: number = 0
  kettle: number = 0
  timer: number = 0

  async init(): Promise<void> {
    // Set target temp on kettle (same kettle_id)
    // In real implementation would call cbpi.emit("SET_TARGET_TEMP", {id, temp})
  }

  async start(): Promise<void> {
    // Start timer if timer not finished
    // Would implement: if is_timer_finished() is null, start_timer
  }

  reset(): void {
    // Reset timer and set target temp
  }

  finish(): void {
    // Finish step
  }

  execute(): void {
    // Execute step loop (check temp, timer)
  }

  // Helper methods from Python Step
  async set_target_temp(temp: number, kettle: number): Promise<void> {
    // API call to set kettle target temperature
    // In full implementation would emit SET_TARGET_TEMP
    this.temp = temp
    this.kettle = kettle
  }

  async get_kettle_temp(kettle: number): Promise<number | null> {
    // Get current kettle temperature
    // Placeholder
    return null
  }

  async is_timer_finished(): Promise<boolean | null> {
    // Check if timer finished
    // Placeholder
    return null
  }

  async start_timer(seconds: number): Promise<void> {
    // Start timer
    this.timer = seconds
  }

  async stop_timer(): Promise<void> {
    // Stop timer
    this.timer = 0
  }

  async notify(headline: string, message: string, timeout?: number | null): Promise<void> {
    // Notification (simplify for now)
    console.log(`NOTIFY: ${headline} - ${message}`)
  }

  async next(): Promise<void> {
    // Move to next step
  }

  async actor_power(id: number, power: number): Promise<void> {
    // Call actor power (placeholder)
  }

  async get_sensor_value(id: number): Promise<number | null> {
    // Get sensor value (placeholder)
    return null
  }
}

// TypeScript-Klasse für MashInStep
export class MashInStep implements PluginInstance {
  kind = 'step'
  name = 'MashInStep'
  module = 'modules.base_plugins.brew_steps'
  properties: Array<{ name: string, label: string, type: 'number' | 'kettle' | 'text', configurable: boolean, description?: string, default_value?: unknown, options?: unknown[] }> = []
  actions: Array<{ method: string, label: string }> = []

  s: boolean = false

  async init(): Promise<void> {
    this.s = false
    // Set target temp
  }

  async change_power(): Promise<void> {
    // Custom action: change power
    await this.actor_power(1, 50)
  }

  async actor_power(id: number, power: number): Promise<void> { return void 0 }
  async get_sensor_value(id: number): Promise<number | null> { return null }
  async set_target_temp(temp: number, kettle: number): Promise<void> {}
  async get_kettle_temp(kettle: number): Promise<number | null> { return null }
  async is_timer_finished(): Promise<boolean | null> { return null }
  async start_timer(seconds: number): Promise<void> {}
  async stop_timer(): Promise<void> {}
  async notify(headline: string, message: string, timeout?: number | null): Promise<void> {}
  async next(): Promise<void> {}
  async start(): Promise<void> {}
  async reset(): Promise<void> {}
  async finish(): Promise<void> {}
  async execute(): Promise<void> {}
}

// Default export: manifest for MashStep (most common step)
export default {
  kind: 'step',
  name: 'MashStep',
  module: 'modules.base_plugins.brew_steps',
  properties: [
    {
      name: 'temp',
      label: 'Temperature',
      type: 'number',
      configurable: true,
      description: 'Target Temperature of Mash Step',
    },
    {
      name:
      'kettle',
      label: 'Kettle',
      type: 'kettle',
      configurable: false,
      description: 'Kettle in which the mashing takes place',
    },
    {
      name: 'timer',
      label: 'Timer in Minutes',
      type: 'number',
      configurable: true,
      description: 'Timer is started when the target temperature is reached',
    },
  ],
  actions: [
    {
      method: 'start',
      label: 'Start Timer Now',
    },
  ],
  create(api: unknown, config: Record<string, unknown>): PluginInstance {
    const instance = new MashStep()
    // Set properties from config
    if ('temp' in config && typeof config.temp === 'number') instance.temp = config.temp
    if ('kettle' in config && typeof config.kettle === 'number') instance.kettle = config.kettle
    if ('timer' in config && typeof config.timer === 'number') instance.timer = config.timer
    return instance
  },
} as const