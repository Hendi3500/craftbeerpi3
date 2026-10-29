/**
 * Plugin-Initialisierung nach createAll().
 *
 * Diese Funktionen durchlaufen die Cache-Einträge und setzen die
 * plugin-Instanz in jedem Eintrag. Sie entsprechen dem, was Python's
 * @cbpi.initalizer Order=1000 / Order=1 tut.
 */
import type { Api } from './api.ts'
import type { Cache } from './cache.ts'
import type { ManifestPluginHost } from '../plugins/host.ts'
import type { Row } from '../db.ts'

/**
 * Initialisiere Actor-Instanzen aus dem Cache.
 * Geht jede actor-Eintrag im Cache durch und setze .instance, .state, .power.
 */
function initActorInstances(api: Api, pluginHost: ManifestPluginHost): void {
  const actors = api.cache.get<Record<string, Row>>('actors')
  if (!actors || Array.isArray(actors)) return

  const actorTypes = api.cache.get<Record<string, Row>>('actor_types')
  if (!actorTypes || Array.isArray(actorTypes)) return

  for (const [id, actor] of Object.entries(actors) as [string, Row][]) {
    const typeEntry = actorTypes[String(actor.type)]
    if (!typeEntry) continue

    const typeName = String(typeEntry.name)
    const instance = pluginHost.create('actor', typeName, api, {
      ...(actor.config ?? {}),
      api,
      id: Number(id),
      name: String(actor.name),
    })

    if (!instance) continue

    // Instanz in den Cache-Eintrag setzen
    actor.instance = instance

    // Runtime-Zustand setzen (entspricht Python init_actor)
    actor.state = 0
    actor.power = 100

    if (typeof instance.init === 'function') {
      void instance.init()
    }
  }
}

/**
 * Initialisiere Sensor-Instanzen aus dem Cache.
 * Geht jede sensor-Eintrag im Cache durch und setze .instance, .mode.
 */
function initSensorInstances(api: Api, pluginHost: ManifestPluginHost): void {
  const sensors = api.cache.get<Record<string, Row>>('sensors')
  if (!sensors || Array.isArray(sensors)) return

  const sensorTypes = api.cache.get<Record<string, Row>>('sensor_types')
  if (!sensorTypes || Array.isArray(sensorTypes)) return

  for (const [id, sensor] of Object.entries(sensors) as [string, Row][]) {
    const typeEntry = sensorTypes[String(sensor.type)]
    if (!typeEntry) continue

    const typeName = String(typeEntry.name)
    const instance = pluginHost.create('sensor', typeName, api, {
      ...(sensor.config ?? {}),
      api,
      id: Number(id),
      name: String(sensor.name),
    })

    if (!instance) continue

    // Instanz in den Cache-Eintrag setzen
    sensor.instance = instance

    // Modus setzen (Standard: passiv)
    sensor.mode = 'P'

    if (typeof instance.init === 'function') {
      void instance.init()
    }
  }
}

/**
 * Initialisiere Kettle-Controller-Instanzen aus dem Cache.
 * Nutzt die logik-Konfiguration, um den passenden Controller zu erstellen.
 */
function initKettleControllers(api: Api, pluginHost: ManifestPluginHost): void {
  const kettles = api.cache.get<Record<string, Row>>('kettle')
  if (!kettles || Array.isArray(kettles)) return

  const controllerTypes = api.cache.get<Record<string, Row>>('controller_types')
  if (!controllerTypes || Array.isArray(controllerTypes)) return

  for (const [id, kettle] of Object.entries(kettles) as [string, Row][]) {
    const logic = String(kettle.logic ?? '')
    if (!logic) continue

    const typeEntry = controllerTypes[logic]
    if (!typeEntry) continue

    const typeName = String(typeEntry.name)
    const instance = pluginHost.create('controller', typeName, api, {
      ...(kettle.config ?? {}),
      api,
      kettle_id: Number(id),
      heater: String(kettle.heater ?? ''),
      sensor: String(kettle.sensor ?? ''),
    })

    if (!instance) continue

    // Instanz an den Kessel-Eintrag anhängen
    kettle.instance = instance

    // Controller initialisieren (falls vorhanden)
    if (typeof instance.init === 'function') {
      void instance.init()
    }
  }
}

/**
 * Initialisiere Fermenter-Controller-Instanzen aus dem Cache.
 */
function initFermenterControllers(api: Api, pluginHost: ManifestPluginHost): void {
  const fermenters = api.cache.get<Record<string, Row>>('fermenter')
  if (!fermenters || Array.isArray(fermenters)) return

  // Fermenter-Controller-Typen aus dem Cache holen
  const controllerTypes = api.cache.get<Record<string, Row>>('controller_types')
  const fermentationControllerTypes = api.cache.get<Record<string, Row>>('fermentation_controller_types')

  for (const [id, fermenter] of Object.entries(fermenters) as [string, Row][]) {
    const logic = String(fermenter.logic ?? '')
    if (!logic) continue

    // Zuerst nach fermentation_controller_types suchen
    let typeEntry: Row | undefined = fermentationControllerTypes
      ? fermentationControllerTypes[logic]
      : undefined

    // Falls nicht gefunden, nach controller_types suchen
    if (!typeEntry) {
      typeEntry = controllerTypes ? controllerTypes[logic] : undefined
    }

    if (!typeEntry) continue

    const typeName = String(typeEntry.name)
    const instance = pluginHost.create('fermentation_controller', typeName, api, {
      ...(fermenter.config ?? {}),
      api,
      fermenter_id: Number(id),
      heater: String(fermenter.heater ?? ''),
      sensor: String(fermenter.sensor ?? ''),
    })

    if (!instance) continue

    // Instanz an den Fermenter-Eintrag anhängen
    fermenter.instance = instance

    // Controller initialisieren (falls vorhanden)
    if (typeof instance.init === 'function') {
      void instance.init()
    }
  }
}

/**
 * Initialisiere alle Plugin-Instanzen nach dem Laden der Plugins.
 *
 * Aufruf-Reihenfolge in app.ts:
 *   plugins.createAll(api, cache)
 *   initPluginInstances(api, plugins)
 */
export function initPluginInstances(api: Api, pluginHost: ManifestPluginHost): void {
  initActorInstances(api, pluginHost)
  initSensorInstances(api, pluginHost)
  initKettleControllers(api, pluginHost)
  initFermenterControllers(api, pluginHost)

  api.log('info', 'Plugin instances initialized from cache')
}