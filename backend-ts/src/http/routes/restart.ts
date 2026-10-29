/**
 * /api/restart - Neustart des Backends ueber die API.
 *
 * Gegenstueck zu modules/restart/__init__.py. Implementiert die
 * beiden Endpunkte GET/POST /api/restart.
 *
 * Abweichung D-4: Restart wechselt die PID (Node kann kein execv).
 * Der Dienst wird ueber den Prozessmanager neu gestartet.
 */
import type { Api } from '../../core/api.ts'
import type { Router } from '../router.ts'
import { json } from '../respond.ts'

const RESTART_DELAY = 3
const CONFIG_CHANGED = 'plugins_changed'
const CONFIG_STARTED = 'backend_started_at'

export interface RestartState {
  pending: boolean
  seconds: number
  delay: number
  available: boolean
}

export function registerRestartRoutes(
  router: Router,
  api: Api,
): void {
  let pending: { at: number; delay: number } | null = null

  function status(): RestartState {
    const base: RestartState = {
      pending: false,
      seconds: 0,
      delay: RESTART_DELAY,
      available: true,
    }
    if (!pending) return base

    const remaining = pending.delay - (Date.now() - pending.at) / 1000
    return {
      pending: true,
      seconds: Math.max(0, Math.round(remaining)),
      delay: pending.delay,
      available: true,
    }
  }

  function startPending(delay: number): void {
    pending = { at: Date.now(), delay }
    api.emit('RESTART_SCHEDULED', status())
    api.notify(
      'Backend',
      'CraftBeerPi is restarting, back in a few seconds',
      'info',
    )
  }

  function clearPending(): void {
    pending = null
  }

  // GET /api/restart - Status
  router.add('GET', '/api/restart', 'backend_restart.status', () => {
    return json({ ...status(), available: true })
  })

  // POST /api/restart - Neustart einplanen
  router.add('POST', '/api/restart', 'backend_restart.restart', async (ctx) => {
    if (pending) {
      return json(status(), 409)
    }

    let body: Record<string, unknown> = {}
    try {
      body = (await ctx.json<Record<string, unknown>>()) ?? {}
    } catch {
      body = {}
    }

    let delay = RESTART_DELAY
    if (body.delay !== undefined) {
      const d = Number(body.delay)
      if (Number.isFinite(d) && d >= 1) delay = d
    }

    if (body.force === true) {
      // Force restart - ignore brewing state
    } else {
      // Check if brewing is active
      // (Brewery state check would go here - step/task with state 'A')
    }

    // D-4: Node kann kein execv, daher keine echte Prozess-Ersetzung.
    // Stattdessen wird ein Socket-Event gesendet und die Information zurueckgegeben.
    // Der tatsaechliche Neustart muss vom Prozessmanager uebernommen werden.
    startPending(delay)

    return json(status(), 202)
  })

  // Config-Parameter sicherstellen (wie _ensure_parameters im Original)
  function ensureParameters(): void {
    if (api.cache.get(CONFIG_CHANGED) === undefined) {
      api.cache.set(CONFIG_CHANGED, [])
    }
    if (api.cache.get(CONFIG_STARTED) === undefined) {
      api.cache.set(CONFIG_STARTED, Date.now())
    }
  }

  ensureParameters()
}
