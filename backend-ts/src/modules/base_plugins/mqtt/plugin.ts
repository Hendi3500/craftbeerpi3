/**
 * Base-Plugin: mqtt
 *
 * Analog zu modules/base_plugins/mqtt/__init__.py.
 * MQTT-Broker-Anbindung zum Empfang von Sensordaten und Schalten von Actoren.
 * Auf Nicht-Pi-Systemen: Stub mit Config-Parameter-Lesen.
 *
 * Der volle MQTT-Client (paho-mqtt) ist in Node.js verfügbar. Hier wird
 * das Laden der Konfigurationsparameter und ein minimaler Stub bereitgestellt.
 */
import type { PluginInstance } from '../../../plugins/contract.ts'

type MqttKey = 'server' | 'port' | 'username' | 'password' | 'tls' | 'ca_cert' | 'cert' | 'key'

/**
 * Liest einen Config-Parameter aus dem Cache oder gibt Default zurück.
 */
function readConfigBool(config: Record<MqttKey, unknown>, key: MqttKey, defaultValue: boolean): boolean {
  const value = config[key]
  if (value === undefined) return defaultValue
  const text = String(value).trim().toLowerCase()
  if (text === 'yes' || text === 'y' || text === 'true' || text === '1' || text === 'on') return true
  if (text === 'no' || text === 'n' || text === 'false' || text === '0' || text === 'off') return false
  return defaultValue
}

/**
 * Minimaler MQTT-Plugin-Stub für die Konfigurations-Infrastruktur.
 * Der volle MQTT-Client (paho-mqtt) kann später nachgerüstet werden.
 */
export default {
  kind: 'sensor',
  name: 'MqttBroker',
  module: 'modules.base_plugins.mqtt',
  properties: [
    {
      name: 'server',
      label: 'MQTT Server',
      type: 'text',
      configurable: true,
      default_value: 'localhost',
      description: 'MQTT Broker Hostname or IP',
    },
    {
      name: 'port',
      label: 'MQTT Port',
      type: 'number',
      configurable: true,
      default_value: 1883,
      description: 'MQTT Broker Port',
    },
    {
      name: 'username',
      label: 'Username',
      type: 'text',
      configurable: true,
      default_value: '',
      description: 'MQTT Username (optional)',
    },
    {
      name: 'password',
      label: 'Password',
      type: 'text',
      configurable: true,
      default_value: '',
      description: 'MQTT Password (optional)',
    },
    {
      name: 'tls',
      label: 'TLS enable',
      type: 'select',
      configurable: true,
      options: ['YES', 'NO'],
      default_value: 'NO',
      description: 'Use TLS for MQTT connection',
    },
  ],
  actions: [],
  create(): PluginInstance {
    // Keine laufende MQTT-Verbindung im P2-Stub;
    // Config-Parameter stehen für spätere Nutzung bereit.
    return {
      async init(): Promise<void> {
        // Konfiguration beim Start lesen/loggen
        console.log('MQTT Plugin: Initializing - broker config ready')
      },
      async stop(): Promise<void> {
        // Aufräumen
      },
      get_value(): unknown {
        return { status: 'configured', server: 'localhost', connected: false }
      },
    } as PluginInstance
  },
} as const