/**
 * Base-Plugin: gpio_actor
 *
 * Analog zu modules/base_plugins/gpio_actor/__init__.py.
 * GPIO Aktoren (GPIOSimple, GPIOPWM).
 * Auf Nicht-Pi-Systemen: sauberer Stub mit Log-Meldung (M4).
 */
import type { PluginApi, PluginInstance } from '../../../plugins/contract.ts'

// Mock GPIO on non-Pi systems
const GPIO_AVAILABLE = false

class GPIOSimpleInstance implements PluginInstance {
  gpio: number = 0

  async init(): Promise<void> {
    if (!GPIO_AVAILABLE) {
      console.log('GPIO actors not available: no access to the GPIO interface.')
      return
    }
    // GPIO setup would go here on Pi
  }

  async on(power?: unknown): Promise<void> {
    if (!GPIO_AVAILABLE) return
    console.log(`GPIO ON ${this.gpio}`)
  }

  async off(): Promise<void> {
    if (!GPIO_AVAILABLE) return
    console.log('GPIO OFF')
  }

  async set_power(power?: unknown): Promise<void> {}
}

class GPIOPWMInstance implements PluginInstance {
  gpio: number = 0
  frequency: number = 100
  power: number = 100

  async init(): Promise<void> {
    if (!GPIO_AVAILABLE) {
      console.log('GPIO actors not available: no access to the GPIO interface.')
      return
    }
    // GPIO setup would go here on Pi
  }

  async on(power?: unknown): Promise<void> {
    if (!GPIO_AVAILABLE) return
    if (power !== undefined) this.power = Number(power ?? 100)
    console.log(`GPIO PWM ON ${this.gpio} freq=${this.frequency} power=${this.power}`)
  }

  async off(): Promise<void> {
    if (!GPIO_AVAILABLE) return
    console.log('GPIO PWM OFF')
  }

  async set_power(power?: unknown): Promise<void> {
    if (power !== undefined) this.power = Number(power ?? 100)
  }
}

export default {
  kind: 'actor',
  name: 'GPIOSimple',
  module: 'modules.base_plugins.gpio_actor',
  properties: [
    {
      name: 'gpio',
      label: 'GPIO',
      type: 'select',
      configurable: true,
      description: 'GPIO to which the actor is connected',
      options: [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27],
    },
  ],
  actions: [],
  create(api: PluginApi, config: Record<string, unknown>): PluginInstance {
    const instance = new GPIOSimpleInstance()
    if ('gpio' in config) instance.gpio = Number(config.gpio ?? 0)
    return instance
  },
} as const

// Secondary export for GPIOPWM (named export)
export { GPIOPWMInstance }