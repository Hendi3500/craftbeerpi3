/**
 * Base-Plugin: OneWire
 *
 * Passiver OneWire Temperatursensor (1-Wire).
 * Gegenstueck zu modules/base_plugins/one_wire/__init__.py.
 * Implementiert echte 1-Wire Sensor-Scan und Temperaturmessung wie im Python-Backend.
 */
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import type { PluginApi, PluginInstance } from '../../../plugins/contract.ts'

/** Einfache OneWire Sensor-Scan: gleiche Logik wie modules/base_plugins/one_wire/__init__.py */
function getAvailableSensors(): string[] {
  try {
    const dir = '/sys/bus/w1/devices'
    if (!existsSync(dir)) return []

    const files = readdirSync(dir)
    const result: string[] = []

    for (const dirname of files) {
      if (dirname.startsWith('28') || dirname.startsWith('10')) {
        result.push(dirname)
      }
    }

    return result
  } catch {
    return []
  }
}

/** Liest die Temperatur aus einem OneWire Sensor */
function readSensorTemperature(sensorName: string): number | null {
  try {
    const file = join('/sys/bus/w1/devices', sensorName, 'w1_slave')
    const content = readFileSync(file, 'utf8')

    const lines = content.split('\n')
    const firstLine = lines[0]

    if (firstLine?.includes('YES')) {
      const tempStr = firstLine.split('=')[1]
      if (tempStr) {
        const temp = Number(tempStr) / 1000
        return isNaN(temp) ? null : temp
      }
    }

    return null
  } catch {
    return null
  }
}

export default {
  kind: 'sensor',
  name: 'OneWire',
  module: 'modules.base_plugins.one_wire',
  properties: [
    {
      name: 'sensor_name',
      label: 'Sensor',
      type: 'select',
      configurable: true,
      options: [],  // Wird vom Host ausgefüllt
      description: 'The OneWire sensor address.',
    },
    {
      name: 'offset',
      label: 'Offset',
      type: 'number',
      configurable: true,
      default_value: 0,
      description: 'Offset which is added to the received sensor data.',
    },
    {
      name: 'unit',
      label: 'Unit',
      type: 'select',
      configurable: true,
      options: ['C', 'F'],
      default_value: 'C',
      description: 'Temperature unit.',
    },
  ],
  create(api: PluginApi, config: Record<string, unknown>): PluginInstance {
    const instance: PluginInstance = {
      async init() {
        // Optional: w1-gpio und w1-therm module laden (wie in Python init_global)
        // Für Node.js müssen wir auf Systemebene zugreifen, was nicht sicher ist
      },
      async stop() {
        // Cleanup wenn nötig
      },
      getValue(): unknown {
        // Implementiere echte OneWire Sensor-Lesung
        const sensorName = config.sensor_name as string | undefined
        const offset = Number(config.offset ?? 0)
        const unit = config.unit as string ?? 'C'

        let temp = config.temp as number | undefined

        // Wenn kein direkter temp-Wert konfiguriert ist, versuche Hardware zu lesen
        if (temp === undefined || sensorName) {
          let hardwareTemp: number | null = null

          if (sensorName) {
            hardwareTemp = readSensorTemperature(sensorName)
          } else {
            // Scan für verfügbare Sensoren
            const available = getAvailableSensors()
            const firstSensor = available[0]
            if (firstSensor) {
              // Verwende den ersten verfügbaren Sensor
              hardwareTemp = readSensorTemperature(firstSensor)
            }
          }

          if (hardwareTemp !== null) {
            temp = hardwareTemp + offset
          }
        }

        // Konvertiere Einheiten
        if (temp !== undefined) {
          if (unit === 'F') {
            temp = temp * 9 / 5 + 32
          }
        }

        return temp
      },
    } as PluginInstance

    return instance
  },
} as const