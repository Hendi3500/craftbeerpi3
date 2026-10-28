/**
 * Umgebung, an derselben Stelle wie im Python-Backend.
 *
 * CBPI_PORT, CBPI_LOG_LEVEL und CBPI_LOG_STDOUT haben dort dieselbe
 * Bedeutung (siehe modules/app_config.py und run.py). Zusaetzlich:
 *
 *   CBPI_ROOT   Wurzel des Projekts (config/, update/, logs/, modules/)
 *   CBPI_DB     Pfad zur SQLite-Datei (Default: <root>/craftbeerpi.db)
 */
import { resolve } from 'node:path'

export function rootDir(): string {
  const fromEnv = process.env.CBPI_ROOT?.trim()
  if (fromEnv) return resolve(fromEnv)
  // src/env.ts -> backend-ts -> Projektwurzel
  return resolve(import.meta.dirname, '../..')
}

export function dbFile(root: string): string {
  const fromEnv = process.env.CBPI_DB?.trim()
  return fromEnv ? resolve(fromEnv) : resolve(root, 'craftbeerpi.db')
}

/** Port aus der Umgebung, oder null wenn nicht gesetzt/ungueltig. */
export function parsePort(raw: string | undefined): number | null {
  const value = raw?.trim()
  if (!value) return null
  const port = Number(value)
  return Number.isInteger(port) && port > 0 && port < 65536 ? port : null
}

export function logLevel(): string {
  return (process.env.CBPI_LOG_LEVEL ?? 'INFO').trim().toUpperCase()
}

export function logToStdout(): boolean {
  const value = (process.env.CBPI_LOG_STDOUT ?? '').trim().toLowerCase()
  return value === '1' || value === 'true' || value === 'yes' || value === 'on'
}
