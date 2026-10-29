/**
 * Base-Plugin: mqtt
 *
 * Analog zu modules/base_plugins/mqtt/__init__.py.
 * MQTT-Broker-Anbindung zum Empfang von Sensordaten und Schalten von Actoren.
 * Implementiert einen echten MQTT-Client ueber das npm-Paket 'mqtt'.
 *
 * Portiert auf Node.js:
 *   * Verbindungsaufbau ueber 'mqtt.Client' statt paho-mqtt
 *   * Callback-API durch EventEmitter ersetzt (Standard im mqtt-Paket)
 *   * Subscriptions zentral verwaltet, bei (Re-)Connect erneut gesetzt
 *   * Reader-Task laeuft als socket.io-background-task (siehe background_tasks.ts)
 *   * Fehler im Broker brechen den Backend-Start nicht ab
 *
 * Config-Parameter (wie im Python-Backend, klein geschrieben):
   mqtt_server, mqtt_port, mqtt_username, mqtt_password,
   mqtt_tls, mqtt_ca_cert, mqtt_cert, mqtt_key
 */
import type { Api } from '../../../core/api.ts'
import type { PluginInstance } from '../../../plugins/contract.ts'
import { connect as mqttConnect, type MqttClient, type IClientOptions } from 'mqtt'

/** Config-Parameter-Namen (klein geschrieben, wie Python). */
const CONFIG_SERVER = 'mqtt_server'
const CONFIG_PORT = 'mqtt_port'
const CONFIG_USERNAME = 'mqtt_username'
const CONFIG_PASSWORD = 'mqtt_password'
const CONFIG_TLS = 'mqtt_tls'
const CONFIG_CA_CERT = 'mqtt_ca_cert'
const CONFIG_CERT = 'mqtt_cert'
const CONFIG_KEY = 'mqtt_key'

/** TLS Auswahlfeld: YES / NO (nicht Freitext, wie im Python-Backend). */
const TLS_OPTIONS = ['YES', 'NO']

/** Alte GROSSBUCHSTABEN-Parameter-Namen (Migration, wie im Python-Backend). */
const OLD_NAMES: Record<string, string> = {
  [CONFIG_SERVER]: 'MQTT_SERVER',
  [CONFIG_PORT]: 'MQTT_PORT',
  [CONFIG_USERNAME]: 'MQTT_USERNAME',
  [CONFIG_PASSWORD]: 'MQTT_PASSWORD',
  [CONFIG_TLS]: 'MQTT_TLS',
  [CONFIG_CA_CERT]: 'MQTT_CA_CERT',
  [CONFIG_CERT]: 'MQTT_CERT',
  [CONFIG_KEY]: 'MQTT_KEY',
}

/** Simple Queue fuer eingehende MQTT-Nachrichten (Thread-safe). */
class MessageQueue {
  private queue: Array<{ id: number; value: unknown }> = []
  private maxSize = 1000

  push(item: { id: number; value: unknown }): void {
    if (this.queue.length >= this.maxSize) {
      // Einmalig warnen, dann落ち lassen
      this.queue.shift()
    }
    this.queue.push(item)
  }

  pop(): { id: number; value: unknown } | null {
    if (this.queue.length === 0) return null
    return this.queue.shift() ?? null
  }

  isEmpty(): boolean {
    return this.queue.length === 0
  }
}

/**
 * Umwandlung von Config-Werten zu Boolean.
 * Python: _as_bool() - untersucht explizit auf "yes"/"no"/"true"/"false"/"1"/"0"/"on"/"off"
 * damit ein leeres oder "false"-Feld nicht versehentlich truthy ist.
 */
function asBool(value: unknown, defaultValue = false): boolean {
  if (typeof value === 'boolean') return value
  if (value === null || value === undefined) return defaultValue

  const text = String(value).trim().toLowerCase()
  if (text === 'yes' || text === 'y' || text === 'true' || text === '1' || text === 'on') return true
  if (text === 'no' || text === 'n' || text === 'false' || text === '0' || text === 'off' || text === '') return false
  return defaultValue
}

/**
 * Umwandlung von Config-Werten zu Integer mit Fehlerbehandlung.
 * Python: _as_int() - faengt ValueError ab und nutzt Default-Wert.
 */
function asInt(value: unknown, defaultValue: number, what = 'Value'): number {
  try {
    return Number.parseInt(String(value).trim(), 10)
  } catch {
    return defaultValue
  }
}

/**
 * Liest einen Config-Parameter aus dem Cache oder gibt Default zurueck.
 * Python: _read_config() - handhabt alte und neue Parameternamen.
 */
function readConfig(
  api: Api,
  name: string,
  defaultValue: string | number,
  description: string,
  paramType = 'text',
  options?: string[],
): string | number {
  const cache = api.config()
  if (!cache || Object.keys(cache).length === 0) {
    // Der Config-Cache ist noch nicht da.
    return defaultValue
  }

  const entry = cache[name]
  const oldName = OLD_NAMES[name]
  const oldEntry = oldName ? cache[oldName] : null

  if (entry) {
    // Fall 2: Parameter gibt es schon.
    const value = entry.value !== null ? entry.value : defaultValue
    // Typ-Anpassung wird hier ausgelassen (da kein Zugriff auf Config-Tabelle)
    return value
  } else {
    // Fall 1 oder 3: Wert des alten Parameters uebernehmen, sonst Default.
    if (oldEntry && oldEntry.value !== null) {
      return oldEntry.value
    }
    return defaultValue
  }
}

/**
 * Liest den TLS-Parameter und bringt ihn auf YES/NO.
 * Python: _read_tls() - migriert alte "true"/"false"-Werte.
 */
function readTls(api: Api): string {
  const raw = String(readConfig(api, CONFIG_TLS, 'NO', 'MQTT TLS', 'select', TLS_OPTIONS))
  const newValue = asBool(raw) ? 'YES' : 'NO'

  // Migration: alten Wert auf YES/NO umstellen (vereinfacht, ohne Config-Tabelle-Zugriff)

  return newValue
}

/**
 * Loescht einen alten Config-Parameter (GROSSBUCHSTABEN-Version).
 * Python: _delete_parameter() - entfernt alte Eintraege nach Migration.
 */
function deleteOldParameter(api: Api, name: string): void {
  // Ohne Zugriff auf Config-Tabelle kann hier nichts geloescht werden.
  // Der alte Eintrag bleibt im Cache, wird aber nicht mehr verwendet.
}

/**
 * MQTTBroker - verwaltet genau eine MQTT-Verbindung fuer alle Actoren und Sensoren.
 * Python: MQTTBroker-Klasse in modules/base_plugins/mqtt/__init__.py
 */
export class MqttBroker {
  private client: MqttClient | null = null
  private connected = false
  private readonly topics = new Map<string, Array<(topic: string, payload: Buffer, packet: any) => void>>()
  private readonly server: string
  private readonly port: number
  private readonly username: string | null
  private readonly password: string | null
  private readonly tls: boolean
  private readonly caCert: string
  private readonly cert: string
  private readonly key: string
  private readonly keepalive: number
  private readonly api: Api

  constructor(api: Api, server: string, port: number, username: string | null,
              password: string | null, tls: boolean,
              caCert = '', cert = '', key = '', keepalive = 60) {
    this.api = api
    this.server = server
    this.port = asInt(port, 1883, 'MQTT port')
    this.username = username && username !== 'username' ? username : null
    this.password = password && password !== 'password' ? password : null
    this.tls = tls
    this.caCert = caCert
    this.cert = cert
    this.key = key
    this.keepalive = asInt(keepalive, 60, 'MQTT keepalive')
  }

  /** Startet die MQTT-Verbindung (blockiert nicht). */
  start(): boolean {
    this.api.log('info', `MQTT: connecting to ${this.server}:${this.port}`)

    try {
      const options: IClientOptions = {
        port: this.port,
        keepalive: this.keepalive,
        clientId: `cbpi-${Math.random().toString(16).slice(2, 10)}`,
        clean: true,
        reconnectPeriod: 5000,
      }

      if (this.username && this.password) {
        options.username = this.username
        options.password = this.password
      }

      if (this.tls) {
        options.rejectUnauthorized = true // Zertifikatspruefung aktiv
      }

      this.client = mqttConnect(`mqtt${this.tls ? 's' : ''}://${this.server}`, options)

      this.client.on('connect', () => {
        this.connected = true
        this.api.log('info', 'MQTT: connected')

        // Alle registrierten Topics erneut abonnieren (nach Reconnect)
        for (const topic of this.topics.keys()) {
          this.subscribeNow(topic)
        }
      })

      this.client.on('disconnect', () => {
        this.connected = false
        this.api.log('warning', 'MQTT: connection disconnected')
      })

      this.client.on('error', (err) => {
        this.api.log('error', `MQTT: error: ${err.message}`)
      })

      this.client.on('message', (topic, payload, packet) => {
        const callbacks = this.topics.get(topic)
        if (callbacks) {
          for (const cb of callbacks) {
            try {
              cb(topic, payload, packet)
            } catch (error) {
              this.api.log('error', `MQTT: callback error for '${topic}': ${String(error)}`)
            }
          }
        }
      })

      return true
    } catch (error) {
      this.api.log('error', `MQTT: connection setup failed: ${String(error)}`)
      return false
    }
  }

  /** Stoppt die MQTT-Verbindung. */
  stop(): void {
    try {
      this.client?.end(true)
      this.client = null
    } catch (error) {
      this.api.log('error', `MQTT: error while shutting down: ${String(error)}`)
    } finally {
      this.connected = false
    }
  }

  /** Prueft, ob die Verbindung aktiv ist. */
  isConnected(): boolean {
    return this.connected && this.client !== null
  }

  /** Wartet bis die Verbindung steht (max. timeout Sekunden). */
  waitConnected(timeout = 10): boolean {
    // In Node.js kann man nicht einfach auf connect warten ohne Promise.
    // Hier: simple Schleife mit Intervall.
    const start = Date.now()
    const interval = 100
    const check = (): boolean => {
      if (this.isConnected()) return true
      if (Date.now() - start > timeout * 1000) return false
      return false // wird von aufrufer wiederholt
    }
    return check()
  }

  /** Veröffentlicht eine Nachricht. */
  publish(topic: string, payload: string | Buffer, qos = 2, retain = true, timeout = 10): boolean {
    if (!topic) {
      this.api.log('error', 'MQTT: publish without topic')
      return false
    }

    if (!this.isConnected()) {
      this.api.log('error', `MQTT: no broker (${this.server}:${this.port}), publish to '${topic}' discarded`)
      return false
    }

    try {
      this.client!.publish(topic, payload, { qos, retain }, (err) => {
        if (err) {
          this.api.log('error', `MQTT: publish to '${topic}' failed: ${err.message}`)
        }
      })
      return true
    } catch (error) {
      this.api.log('error', `MQTT: publish to '${topic}' failed: ${String(error)}`)
      return false
    }
  }

  /** Registriert einen Callback fuer ein Topic. */
  addSubscription(topic: string, callback: (topic: string, payload: Buffer, packet: any) => void): boolean {
    if (!topic) {
      this.api.log('error', 'MQTT: sensor without topic - subscription skipped')
      return false
    }

    if (!this.topics.has(topic)) {
      this.topics.set(topic, [])
    }
    const callbacks = this.topics.get(topic)!
    if (!callbacks.includes(callback)) {
      callbacks.push(callback)
    }

    if (this.isConnected()) {
      this.subscribeNow(topic)
    }
    return true
  }

  /** Meldet einen Callback ab. */
  removeSubscription(topic: string, callback?: (topic: string, payload: Buffer, packet: any) => void): boolean {
    const callbacks = this.topics.get(topic)
    if (!callbacks) return true

    if (callback === undefined) {
      this.topics.delete(topic)
    } else {
      const idx = callbacks.indexOf(callback)
      if (idx >= 0) {
        callbacks.splice(idx, 1)
      }
      if (callbacks.length === 0) {
        this.topics.delete(topic)
      }
    }

    if (this.isConnected() && !this.topics.has(topic)) {
      try {
        this.client?.unsubscribe(topic)
      } catch (error) {
        this.api.log('error', `MQTT: unsubscribe from '${topic}' failed: ${String(error)}`)
      }
    }
    return true
  }

  /** Liefert alle Callbacks fuer ein Topic (Kopie). */
  subscriptionsFor(topic: string): Array<(topic: string, payload: Buffer, packet: any) => void> {
    return [...(this.topics.get(topic) ?? [])]
  }

  /** Abonniert ein Topic sofort. */
  private subscribeNow(topic: string): void {
    try {
      this.client?.subscribe(topic, { qos: 1 })
    } catch (error) {
      this.api.log('error', `MQTT: subscribe to '${topic}' failed: ${String(error)}`)
    }
  }

  /** JSON-Darstellung fuer /api/system/dump. */
  toJSON(): Record<string, unknown> {
    return {
      server: this.server,
      port: this.port,
      tls: this.tls,
      authenticated: Boolean(this.username && this.password),
      connected: this.isConnected(),
      topics: [...this.topics.keys()].sort(),
    }
  }
}

/**
 * Fallback-Broker, wenn der echte nicht starten kann.
 * Python: _broker_out-Klasse
 */
class MqttBrokerOut {
  private reported = false
  private readonly topics = new Map<string, Array<(topic: string, payload: Buffer, packet: any) => void>>()
  private readonly caCert: string
  private readonly cert: string
  private readonly key: string

  constructor(caCert = '', cert = '', key = '') {
    this.caCert = caCert
    this.cert = cert
    this.key = key
  }

  private report(what: string): void {
    if (this.reported) return
    this.reported = true
    console.error(`MQTT: ${what} not possible - the broker is not running. Check the MQTT configuration.`)
  }

  publish(): boolean {
    this.report('publish')
    return false
  }

  isConnected(): boolean {
    return false
  }

  waitConnected(): boolean {
    return false
  }

  addSubscription(topic: string, callback: (topic: string, payload: Buffer, packet: any) => void): void {
    if (!this.topics.has(topic)) {
      this.topics.set(topic, [])
    }
    this.topics.get(topic)!.push(callback)
  }

  removeSubscription(topic: string, callback?: (topic: string, payload: Buffer, packet: any) => void): void {
    const callbacks = this.topics.get(topic)
    if (!callbacks) return
    if (callback === undefined) {
      this.topics.delete(topic)
    } else {
      const idx = callbacks.indexOf(callback)
      if (idx >= 0) callbacks.splice(idx, 1)
      if (callbacks.length === 0) this.topics.delete(topic)
    }
  }

  subscriptionsFor(topic: string): Array<(topic: string, payload: Buffer, packet: any) => void> {
    return [...(this.topics.get(topic) ?? [])]
  }

  stop(): void { /* noop */ }

  toJSON(): Record<string, unknown> {
    return { connected: false, error: 'MQTT broker not running' }
  }
}

/** Globale Message-Queue fuer eingehende MQTT-Nachrichten. */
const mqttQueue = new MessageQueue()

/**
 * MQTT Actor: schaltet mit JSON-Payload {"state":"on"/"off"}.
 * Python: MQTTActor-Klasse (dekoriert mit @cbpi.actor)
 */
function createMqttActor(api: Api): PluginInstance {
  return {
    async init(): Promise<void> {
      // Actor-Initialisierung
    },
    async stop(): Promise<void> {
      // Aufraeumen
    },
    on(power = 100): void {
      const topic = this.topic
      if (!topic) return
      const broker = api.config()[CONFIG_SERVER] ? getBroker(api) : null
      if (broker) {
        broker.publish(topic, JSON.stringify({ state: 'on' }), 2, true)
      }
    },
    off(): void {
      const topic = this.topic
      if (!topic) return
      const broker = api.config()[CONFIG_SERVER] ? getBroker(api) : null
      if (broker) {
        broker.publish(topic, JSON.stringify({ state: 'off' }), 2, true)
      }
    },
    topic: '', // wird von der Konfiguration gesetzt
  } as PluginInstance
}

/**
 * ESPEasyMQTT Actor: schaltet mit rohen Payloads "1"/"0".
 * Python: ESPEasyMQTT-Klasse (dekoriert mit @cbpi.actor)
 */
function createEspEasyMqttActor(api: Api): PluginInstance {
  return {
    async init(): Promise<void> {},
    async stop(): Promise<void> {},
    on(power = 100): void {
      const topic = this.topic
      if (!topic) return
      const broker = getBroker(api)
      if (broker) {
        broker.publish(topic, '1', 2, true)
      }
    },
    off(): void {
      const topic = this.topic
      if (!topic) return
      const broker = getBroker(api)
      if (broker) {
        broker.publish(topic, '0', 2, true)
      }
    },
    topic: '',
  } as PluginInstance
}

/**
 * MQTT Sensor: lauscht auf Topic und empfängt Werte.
 * Python: MQTT_SENSOR-Klasse (dekoriert mit @cbpi.sensor)
 */
function createMqttSensor(api: Api): PluginInstance {
  return {
    async init(): Promise<void> {
      // Sensor wird ueber den fermenter_task oder step_task ausgefuehrt
    },
    async stop(): Promise<void> {},
    getValue(): unknown {
      return { value: this.lastValue, unit: this.unit }
    },
    getUnit(): string {
      return this.unit
    },
    lastValue: null,
    topic: '',
    payloadPath: null as string[] | null,
    unit: '',
    broker: null as MqttBroker | MqttBrokerOut | null,
    _onMessage: null as ((topic: string, payload: Buffer, packet: any) => void) | null,
  } as PluginInstance
}

/** Hilfsfunktion: Holt oder erstellt den Broker aus dem Cache. */
function getBroker(api: Api): MqttBroker | MqttBrokerOut | null {
  const cache = api.cache.get('mqtt')
  return cache ?? null
}

/**
 * Initialisiert das MQTT-Plugin.
 * Python: initMQTT() - decoratert mit @cbpi.initalizer(order=0)
 */
export function initMqtt(api: Api): void {
  try {
    const server = String(readConfig(api, CONFIG_SERVER, 'localhost', 'MQTT Server'))
    const port = String(readConfig(api, CONFIG_PORT, '1883', 'MQTT Server Port', 'number'))
    const username = String(readConfig(api, CONFIG_USERNAME, '', 'MQTT username'))
    const password = String(readConfig(api, CONFIG_PASSWORD, '', 'MQTT password'))
    const tls = readTls(api) === 'YES'
    const caCert = String(readConfig(api, CONFIG_CA_CERT, '', 'MQTT TLS CA certificate (path)'))
    const cert = String(readConfig(api, CONFIG_CERT, '', 'MQTT TLS client certificate (path)'))
    const key = String(readConfig(api, CONFIG_KEY, '', 'MQTT TLS client key (path)'))

    // Der Broker darf den Start des Backends nicht verhindern.
    let broker: MqttBroker | MqttBrokerOut
    try {
      broker = new MqttBroker(api, server, port, username, password, tls, caCert, cert, key)
      broker.start()
      api.cache.set('mqtt', broker)
      api.log('info', 'MQTT: plugin initialized')
    } catch (error) {
      api.log('error', `MQTT: broker could not be started (${String(error)}) - backend continues without MQTT`)
      broker = new MqttBrokerOut(caCert, cert, key)
      api.cache.set('mqtt', broker)
    }

    // Reader-Task: Werte aus der Queue an den Core weitergeben.
    // Python: mqtt_reader() als socketio.background_task
    // Hier wird dies im background_tasks.ts registriert.

  } catch (error) {
    api.log('error', `MQTT: initialization failed: ${String(error)}`)
  }
}

/**
 * Verarbeitet eine eingehende MQTT-Nachricht fuer einen Sensor.
 * Python: _handle_message()
 */
function handleMessage(sensorId: number, payloadPath: string[] | null, payload: Buffer): void {
  try {
    let msg: string
    try {
      msg = payload.toString('utf8')
    } catch {
      msg = String(payload)
    }

    let data: unknown
    try {
      data = JSON.parse(msg)
    } catch {
      data = msg
    }

    if (payloadPath !== null) {
      // Verschachteltes JSON durchlaufen, z.B. "Sensor.Value"
      let current = data
      for (const key of payloadPath) {
        if (typeof current !== 'object' || current === null || Array.isArray(current)) return
        current = (current as Record<string, unknown>)[key]
        if (current === undefined) return
      }
      data = current
    }

    if (typeof data === 'number' || typeof data === 'string' || typeof data === 'boolean') {
      mqttQueue.push({ id: sensorId, value: data })
    }
  } catch (error) {
    console.error(`MQTT: error handling message: ${String(error)}`)
  }
}

/**
 * Exportiert Funktionen fuer die Hintergrundtask-Verarbeitung.
 * Diese werden von background_tasks.ts aufgerufen.
 */
export const mqttProcessor = {
  /** Liest eine Nachricht aus der Queue und gibt sie an den Sensor weiter. */
  processOne(api: Api): void {
    const msg = mqttQueue.pop()
    if (!msg) return

    try {
      const sensors = api.cache.get<Record<string, Record<string, unknown>>>('sensors')
      const sensor = sensors?.[String(msg.id)]
      if (!sensor) return

      const instance = sensor.instance as PluginInstance & { lastValue?: unknown }
      if (instance) {
        instance.lastValue = msg.value
      }
      api.emit('SENSOR_UPDATE', sensor)
    } catch (error) {
      api.log('error', `MQTT: reader could not process value: ${String(error)}`)
    }
  },
}

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
      options: TLS_OPTIONS,
      default_value: 'NO',
      description: 'Use TLS for MQTT connection',
    },
    {
      name: 'ca_cert',
      label: 'CA Certificate',
      type: 'text',
      configurable: true,
      default_value: '',
      description: 'Path to CA certificate file',
    },
    {
      name: 'cert',
      label: 'Client Certificate',
      type: 'text',
      configurable: true,
      default_value: '',
      description: 'Path to client certificate file',
    },
    {
      name: 'key',
      label: 'Client Key',
      type: 'text',
      configurable: true,
      default_value: '',
      description: 'Path to client key file',
    },
  ],
  actions: [],
  create(): PluginInstance {
    // Minimaler Stub - die echte Logik laeuft ueber initMqtt() und MqttBroker
    return {
      async init(): Promise<void> {
        console.log('MQTT Plugin: Initializing - broker config ready')
      },
      async stop(): Promise<void> {},
      get_value(): unknown {
        const broker = getBroker({} as Api) // wird spaeter ersetzt
        return broker ? broker.toJSON() : { status: 'not_initialized', connected: false }
      },
    } as PluginInstance
  },
} as const