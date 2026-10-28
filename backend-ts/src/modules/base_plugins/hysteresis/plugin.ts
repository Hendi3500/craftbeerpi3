/**
 * Base-Plugin: Hysteresis
 *
 * Sensor with hysteresis logic (similar to Python: from modules.base_plugins.hysteresis)
 */
import type { PluginApi, PluginInstance } from '../../../plugins/contract.ts'

export default {
  kind: 'sensor',
  name: 'Hysteresis',
  module: 'modules.base_plugins.hysteresis',
  properties: [
    {
      name: 'temp',
      label: 'Temperature',
      type: 'number',
      configurable: true,
      default_value: 20,
      description: 'Base temperature for hysteresis',
    },
    {
      name: 'delta',
      label: 'Delta',
      type: 'number',
      configurable: true,
      default_value: 5,
      description: 'Hysteresis band width',
    },
  ],
  create(api: PluginApi, config: Record<string, unknown>): PluginInstance {
    let current = Number(config.temp ?? 20)

    const instance: PluginInstance = {
      get_value(): unknown {
        // Simple hysteresis: current + random within delta
        const delta = Number(config.delta ?? 5)
        return current + (Math.random() * 2 - 1) * delta
      },
    } as PluginInstance

    return instance
  },
} as const