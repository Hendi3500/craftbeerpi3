/**
 * Background Task System - replacement für @cbpi.backgroundtask
 *
 * Im Python-Backend definiert man Hintergrundtasks mit:
 *   @cbpi.backgroundtask(key="task_name", interval=5)
 *   def my_task(api):
 *       ...
 *
 * Wichtig: Socket.IO start_background_task führt den Task in einem
 * separaten Thread aus. In Node.js gibt es nur das Event-Loop,
 * also brauchen wir setInterval für periodische Tasks.
 */
import type { Api } from './api.ts'

export interface BackgroundTask {
  key: string
  callback: (api: Api) => void | Promise<void>
  interval: number
  intervalId?: NodeJS.Timeout
  running: boolean
  lastRun?: number
}

export class BackgroundTaskManager {
  private readonly tasks = new Map<string, BackgroundTask>()
  private readonly api: Api

  constructor(api: Api) {
    this.api = api
  }

  /**
   * Registriert einen Hintergrundtask.
   * Der Task startet nicht automatisch - muss mit start() aufgerufen werden.
   */
  register(key: string, callback: (api: Api) => void | Promise<void>, interval: number): void {
    if (this.tasks.has(key)) {
      this.api.log('warning', `Background task '${key}' already registered, overwriting`)
    }

    this.tasks.set(key, {
      key,
      callback,
      interval,
      running: false,
    })
  }

  /**
   * Startet einen Hintergrundtask.
   */
  start(key: string): boolean {
    const task = this.tasks.get(key)
    if (!task) {
      this.api.log('warning', `Background task '${key}' not registered`)
      return false
    }

    if (task.running) {
      this.api.log('warning', `Background task '${key}' already running`)
      return false
    }

    task.running = true
    task.lastRun = Date.now()

    const runTask = async () => {
      try {
        await task.callback(this.api)
        task.lastRun = Date.now()
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        this.api.log('error', `Background task '${key}' failed: ${message}`)
      }
    }

    // Erster Durchlauf sofort
    runTask()

    // Periodischer Durchlauf
    task.intervalId = setInterval(runTask, task.interval * 1000)

    this.api.log('info', `Background task '${key}' started (interval: ${task.interval}s)`)
    return true
  }

  /**
   * Stoppt einen Hintergrundtask.
   */
  stop(key: string): boolean {
    const task = this.tasks.get(key)
    if (!task) {
      this.api.log('warning', `Background task '${key}' not found`)
      return false
    }

    if (!task.running) {
      return false
    }

    if (task.intervalId) {
      clearInterval(task.intervalId)
      task.intervalId = undefined
    }

    task.running = false
    this.api.log('info', `Background task '${key}' stopped`)
    return true
  }

  /**
   * Startet alle registrierten Tasks.
   */
  startAll(): void {
    for (const [key] of this.tasks) {
      this.start(key)
    }
  }

  /**
   * Stoppt alle laufenden Tasks.
   */
  stopAll(): void {
    for (const task of this.tasks.values()) {
      if (task.running && task.intervalId) {
        clearInterval(task.intervalId)
        task.running = false
      }
    }
  }

  /**
   * Liefert den Status aller Tasks.
   */
  status(): Record<string, { running: boolean; interval: number; lastRun?: number }> {
    const result: Record<string, { running: boolean; interval: number; lastRun?: number }> = {}
    for (const task of this.tasks.values()) {
      result[task.key] = {
        running: task.running,
        interval: task.interval,
        lastRun: task.lastRun,
      }
    }
    return result
  }
}

/**
 * Decorator-ähnliche Funktion zum Registrieren von Tasks.
 * Verwendung:
 *   backgroundTask('taskName', 5)((api) => { ... })
 */
export function backgroundTask(
  key: string,
  interval: number,
): (callback: (api: Api) => void | Promise<void>) => void {
  return (callback: (api: Api) => void | Promise<void>) => {
    // Diese Funktion muss mit dem Task-Manager verbunden werden
    // Für Tests kann man sie separat registrieren
    const taskManager = getGlobalTaskManager()
    if (taskManager) {
      taskManager.register(key, callback, interval)
    }
  }
}

// Globale Referenz für den Dekorator
let globalTaskManager: BackgroundTaskManager | undefined

export function setGlobalTaskManager(manager: BackgroundTaskManager): void {
  globalTaskManager = manager
}

export function getGlobalTaskManager(): BackgroundTaskManager | undefined {
  return globalTaskManager
}