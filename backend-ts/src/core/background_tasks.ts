/**
 * Registriert die Hintergrundtasks, wie @cbpi.backgroundtask im Python-Backend.
 *
 * Python definiert:
 *   @cbpi.backgroundtask(key="read_target_temps", interval=5)
 *   def read_target_temps(api): ...
 *
 * Hier werden die gleichen Tasks registriert, aber mit den TS-Modulen.
 * Die Tasks brauchen den Api-Objekt für Cache-Zugriff und Event-Emission.
 */
import type { Api } from './api.ts'
import type { BackgroundTaskManager } from './background.ts'

/**
 * Liest die Soll-Temperaturen der Kessel in die Logdatei.
 * Gegenstueck zu modules/kettle/__init__.py: read_target_temps()
 */
function readTargetTemps(api: Api): void {
  const kettleCache = api.cache.get<Record<string, Record<string, unknown>>>('kettle')
  if (!kettleCache) return

  for (const [key, kettle] of Object.entries(kettleCache)) {
    const targetTemp = (kettle as Record<string, unknown>).target_temp
    if (targetTemp !== undefined && targetTemp !== null) {
      api.logAction(`Kettle ${key} target_temp: ${targetTemp}`)
    }
  }
}

/**
 * Liest die Soll-Temperaturen der Fermenter in die Logdatei.
 * Gegenstueck zu modules/fermenter/__init__.py: read_target_temps()
 */
function readTargetTempsFermenter(api: Api): void {
  const fermenterCache = api.cache.get<Record<string, Record<string, unknown>>>('fermenter')
  if (!fermenterCache) return

  for (const [key, fermenter] of Object.entries(fermenterCache)) {
    const targetTemp = (fermenter as Record<string, unknown>).target_temp
    if (targetTemp !== undefined && targetTemp !== null) {
      api.logAction(`Fermenter ${key} target_temp: ${targetTemp}`)
    }
  }
}

/**
 * Liest passive Sensoren aus.
 * Gegenstueck zu modules/sensors/__init__.py: read_passive_sensor()
 * Dieser Task laeuft alle 5 Sekunden und liest Sensoren mit mode="P".
 */
async function readPassiveSensors(api: Api): Promise<void> {
  const sensors = api.cache.get<Record<string, Record<string, unknown>>>('sensors')
  if (!sensors) return

  for (const [, sensor] of Object.entries(sensors)) {
    const mode = sensor.mode ?? (sensor as Record<string, unknown>).mode ?? 'P'
    if (mode === 'P') {
      // Passive sensor - read() ist eine No-op ohne Plugin-Instanz (M5)
      const instance = (sensor as Record<string, unknown>).instance
      if (instance && typeof (instance as Record<string, unknown>).read === 'function') {
        try {
          const readFn = (instance as { read?: () => unknown }).read
          if (readFn) readFn()
        } catch {
          // Ignore read errors
        }
      }
    }
  }
}

/**
 * Ausfuehrung des Gaer-Schritts.
 * Gegenstueck zu modules/fermenter/__init__.py: execute_fermentation_step()
 * Dieser Task laeuft im Hintergrund und fuehrt aktive Gaer-Schritte aus.
 * Ohne step_types-Register (M5) ist execute() ein No-op.
 */
async function executeFermentationStep(api: Api): Promise<void> {
  const taskCache = api.cache.get<Record<string, Record<string, unknown>>>('fermenter_task')
  if (!taskCache) return

  for (const [fermenterId, step] of Object.entries(taskCache)) {
    const currentTemp = 20 // Placeholder - Sensoren weren't initialisiert

    const stepData = step as Record<string, unknown>
    const direction = String(stepData.direction ?? '')

    if (direction === 'H') {
      if (currentTemp >= Number(stepData.temp)) {
        // Zieltemperatur erreicht - Schritt beenden
        const temp = Number(stepData.temp)
        api.emit('UPDATE_FERMENTER_TARGET_TEMP', {
          id: Number(fermenterId),
          target_temp: temp,
        })
      }
    } else if (direction === 'C') {
      if (currentTemp <= Number(stepData.temp)) {
        const temp = Number(stepData.temp)
        api.emit('UPDATE_FERMENTER_TARGET_TEMP', {
          id: Number(fermenterId),
          target_temp: temp,
        })
      }
    }
  }
}

/**
 * Ruft den aktiven Schritt auf und fuehrt ihn aus.
 * Gegenstueck zu modules/steps/__init__.py: execute_step backgroundtask
 * Laeuft alle 0.1 Sekunden wie im Python-Original.
 */
async function executeStep(api: Api): Promise<void> {
  const activeStep = api.cache.get<Record<string, unknown>>('active_step')
  if (!activeStep) return

  try {
    // Execute call ist ein No-op ohne step_types-Register (M5)
    // Falls step types bereit stehen, koennte man hier anrufen:
    // activeStep.instance?.execute?.()

    // Dirty flag check - in TS implementieren wir das nicht exakt wie Python
    // da Row keine _dirty Eigenschaft hat

    // Auto-advance (n == True)
    const stepN = activeStep.n
    if (stepN === true || stepN === 'true') {
      activeStep.n = false
      // Start the next step - call fermenter start_fermentation
      // Dies wird durch die Endpoints im Fermenter-Modul gehandhabt
    }
  } catch {
    // Ignore errors in background task
  }
}

/**
 * Registriert alle Hintergrundtasks.
 * Die Tasks, die im Python so definiert sind:
 * - read_target_temps (kettle.py)
 * - read_target_temps_fermenter (fermenter.py)
 * - read_passive_sensor (sensors/__init__.py)
 * - execute_fermentation_step (fermenter.py)
 * - step_task (steps/__init__.py)
 */
export function registerBackgroundTasks(
  manager: BackgroundTaskManager,
  api: Api,
): void {
  // Kessel-Soll-Temperaturen in Logdatei schreiben (every 5s)
  manager.register('read_target_temps', readTargetTemps, 5)

  // Fermenter-Soll-Temperaturen in Logdatei schreiben (every 5s)
  manager.register('read_target_temps_fermenter', readTargetTempsFermenter, 5)

  // Passive Sensoren auslesen (every 5s)
  manager.register('read_passive_sensor', readPassiveSensors, 5)

  // Brauschritt-Ausfuehrung (every 0.1s)
  manager.register('step_task', executeStep, 0.1)

  // Gaer-Schritt-Temperatur-Updates (every 1s)
  manager.register('fermentation_task', executeFermentationStep, 1)

  api.log('info', 'Background tasks registered: read_target_temps, read_target_temps_fermenter, read_passive_sensor, step_task, fermentation_task')
}