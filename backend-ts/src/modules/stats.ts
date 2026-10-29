/**
 * /api/stats - Statistiken-Sammlung und Telemetrie.
 *
 * Gegenstueck zu modules/stats/__init__.py. Sendet System-Informationen
 * an den CraftBeerPi-Statistik-Server.
 */
import type { Api } from '../core/api.ts'

interface SystemInfo {
  id: string
  version: string
  kettle: number
  hardware: number
  thermometer: string
  hardware_control: string
}

/**
 * Liest die CPU-Serial-Nummer (wie Python: /proc/cpuinfo lesen).
 */
function getCpuSerial(): string {
  const fs = require('node:fs') as typeof import('node:fs')
  try {
    const content = fs.readFileSync('/proc/cpuinfo', 'utf8')

    for (const line of content.split('\n')) {
      if (line.startsWith('Serial')) {
        // Serial-Zeile hat format: "Serial          : 0000000012345678"
        const match = line.match(/Serial\s+:\s+([0-9a-fA-F]+)/)
        if (match && match[1]) {
          return match[1].toLowerCase()
        }
      }
    }
  } catch {
    // Fehler beim Lesen - verwende Platzhalter
  }
  return '0000000000000000'
}

/**
 * Sendet Statistiken an den CraftBeerPi-Server.
 * Echo to Python: modules/stats/__init__.py sendStats()
 */
export async function sendStats(api: Api): Promise<void> {
  try {
    const serial = getCpuSerial()

    const info: SystemInfo = {
      id: serial,
      version: '3.0',
      kettle: api.dump().kettle ? Object.keys(api.dump().kettle as Record<string, unknown>).length : 0,
      hardware: api.dump().actors ? Object.keys(api.dump().actors as Record<string, unknown>).length : 0,
      thermometer: 'CBP3.0',
      hardware_control: 'CBP3.0',
    }

    // HTTP POST zu statistics.craftbeerpi.com
    const response = await fetch('http://statistics.craftbeerpi.com', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(info),
    })

    if (!response.ok) {
      api.log('warning', `Stats submission failed: ${response.status}`)
    }
  } catch (error) {
    // Fehler nicht protokollieren - Telemetrie darf nicht den Start blockieren
    api.log('debug', `Stats submission error: ${String(error)}`)
  }
}

/**
 * Registriert das Stats-Modul.
 * Wird während des Bootvorgangs aufgerufen (order=9999 in Python).
 */
export function initStatsModule(api: Api): void {
  // Stats werden beim Boot gesendet und laufen nicht als ständiger Hintergrundtask
  // Sie werden nur beim ersten Start gesendet
  setTimeout(() => {
    void sendStats(api)
  }, 2000) // 2 Sekunden warten bis andere Module bereit sind
}