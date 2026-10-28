/**
 * Base-Plugin: fermenter_hysteresis
 *
 * Analog zu modules/base_plugins/fermenter_hysteresis/__init__.py.
 * Hysteresis-Fermenter-Controller (on/off basierend auf Temperaturdifferenz).
 */
import type { PluginInstance } from '../../../plugins/contract.ts'

export default {
  kind: 'fermentation_controller',
  name: 'Hysteresis',
  module: 'modules.base_plugins.fermenter_hysteresis',
  properties: [
    {
      name: 'heater_offset_min',
      label: 'Heater Offset ON',
      type: 'number',
      configurable: true,
      default_value: 0,
      description: 'Offset when heater turns on (heater + offset <= target_temp)',
    },
    {
      name: 'heater_offset_max',
      label: 'Heater Offset OFF',
      type: 'number',
      configurable: true,
      default_value: 0,
      description: 'Offset when heater turns off (heater + offset >= target_temp)',
    },
    {
      name: 'cooler_offset_min',
      label: 'Cooler Offset ON',
      type: 'number',
      configurable: true,
      default_value: 0,
      description: 'Offset when cooler turns on (temp >= target + offset)',
    },
    {
      name: 'cooler_offset_max',
      label: 'Cooler Offset OFF',
      type: 'number',
      configurable: true,
      default_value: 0,
      description: 'Offset when cooler turns off',
    },
  ],
  actions: [],
  create(): PluginInstance {
    let running = false
    let currentTargetTemp: number | null = null
    let currentTemp: number | null = null

    return {
      init(): void {
        running = true
      },
      async run(): Promise<void> {
        while (running) {
          // Simulate reading temp and target
          const target = currentTargetTemp
          const temp = currentTemp

          if (temp === null || target === null) {
            await new Promise((resolve) => setTimeout(resolve, 1000))
            continue
          }

          const offsetMin = 0 as number // heater_offset_min
          const offsetMax = 0 as number // heater_offset_max
          const coolerMin = 0 as number // cooler_offset_min
          const coolerMax = 0 as number // cooler_offset_max

          // Heater logic
          if (temp + offsetMin <= target) {
            // heater_on
          }
          if (temp + offsetMax >= target) {
            // heater_off
          }

          // Cooler logic
          if (temp >= target + coolerMin) {
            // cooler_on
          }
          if (temp <= target + coolerMax) {
            // cooler_off
          }

          await new Promise((resolve) => setTimeout(resolve, 1000))
        }
      },
      async stop(): Promise<void> {
        running = false
      },
      set_target_temp(temp: number, fermenterId: number): void {
        currentTargetTemp = temp
      },
      get_temp(fermenterId: number): Promise<number | null> {
        return Promise.resolve(currentTemp)
      },
      get_target_temp(): Promise<number | null> {
        return Promise.resolve(currentTargetTemp)
      },
      heater_on(power?: unknown): void {},
      heater_off(): void {},
      cooler_on(): void {},
      cooler_off(): void {},
      is_running(): boolean {
        return running
      },
      async sleep(ms: number): Promise<void> {
        await new Promise((resolve) => setTimeout(resolve, ms))
      },
    } as PluginInstance
  },
} as const