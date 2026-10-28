/**
 * Base-Plugin: DummyTempSensor
 *
 * Analog zu modules/base_plugins/dummy_temp/__init__.py.
 * Im P2-System (Manifest) ist ein Plugin eine ESM-Datei mit
 * einem Manifest (default oder benannt). Hier exportiert der Loader das
 * Manifest, und die Laufzeit erzeugt eine Instanz der DummyTempSensor-Klasse.
 *
 * Die Plugin-Klasse selbst ist ein einfacher Sensor, der sich in einem
 * Hintergrundprozess nach einem konfigurierbaren Intervall selbst liest.
 */
import type { PluginApi, PluginInstance } from '../../../plugins/contract.ts'

export default {
  kind: 'sensor',
  name: 'DummyTempSensor',
  module: 'modules.base_plugins.dummy_temp',
  properties: [
    {
      name: 'temp',
      label: 'Temperature',
      type: 'number',
      configurable: true,
      description: 'Dummy Temperature as decimal value',
      default_value: 5,
    },
  ],
  actions: [
    {
      method: 'my_action',
      label: 'My Custom Action',
    },
  ],
  create(api: PluginApi, config: Record<string, unknown>): PluginInstance {
    let lastValue = Number(config.temp ?? 5)
    let running = false

    const instance: PluginInstance = {
      async init() {
        running = true
        while (running) {
          lastValue = Number(config.temp ?? 5) + Math.random() * 2 - 1
          await new Promise((resolve) => setTimeout(resolve, 5000))
        }
      },
      async stop() {
        running = false
      },
      get_value(): unknown {
        return lastValue
      },
      my_action(): void {
        console.log('HELLO WORLD')
      },
    } as PluginInstance

    return instance
  },
} as const