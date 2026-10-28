/**
 * Base-Plugin: OneWire
 *
 * Passiver OneWire Temperatursensor (1-Wire).
 * Siehe modules/base_plugins/one_wire/__init__.py.
 */
import type { PluginApi, PluginInstance } from '../../../plugins/contract.ts'

export default {
  kind: 'sensor',
  name: 'OneWire',
  module: 'modules.base_plugins.one_wire',
  properties: [
    {
      name: 'temp',
      label: 'Temperature',
      type: 'number',
      configurable: true,
      default_value: 22,
      description: 'OneWire temperature sensor value',
    },
  ],
  create(api: PluginApi, config: Record<string, unknown>): PluginInstance {
    const instance: PluginInstance = {
      async init() {
        // In einer echten Installation würde hier 1-Wire Bus initialisiert
        // Für jetzt nur Mock-Daten laden
      },
      async stop() {
        // Aufräumen falls nötig
      },
      get_value(): unknown {
        // Mock: einfache Sinus-ähnliche Schwankung
        const base = Number(config.temp ?? 22)
        const phase = (Date.now() / 10000) % (2 * Math.PI)
        return base + Math.sin(phase) * 0.5
      },
    } as PluginInstance

    return instance
  },
} as const