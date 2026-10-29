/**
 * Editor-Sicherheitsfunktionen - Gegenstueck zu modules/addon/endpoints.py.
 *
 * Der Python-Backend hat eine Reihe von Sicherheitspruefungen, die im
 * TS-Editor-Stub fehlen:
 *   - NAME_PATTERN: Plugin-Name validieren
 *   - NAME_MAX_LENGTH: Laenge pruefen
 *   - _plugin_path: Pfad-Traversal verhindern
 *   - _is_plugin_directory: Echte Plugin-Verzeichnisse identifizieren
 */
import { existsSync, statSync } from 'node:fs'
import { basename, join, resolve } from 'node:path'

/**
 * Ein Plugin-Name darf nur aus Buchstaben, Ziffern, _, - und . bestehen
 * und muss mit einem Buchstaben oder einer Ziffer beginnen.
 *
 * Warum: die Routen "/api/editor/<name>" nehmen den Namen ungeprueft aus
 * dem Pfad. Ohne diese Pruefung laesst sich mit einem Name wie
 * "../../logs" jedes Verzeichnis loeschen (deletePlugin macht ein
 * shutil.rmtree) oder in beliebige Verzeichnisse schreiben.
 */
export const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/

/** Obergrenze fuer den Namen. */
export const NAME_MAX_LENGTH = 100

/**
 * Sicheren Pfad fuer ein Plugin liefern.
 *
 * Gibt None zurueck, wenn der Name ungueltig ist oder aus dem
 * Plugin-Verzeichnis herausfuehren wuerde.
 */
export function pluginPath(name: string, baseDir: string): string | null {
  if (!name || typeof name !== 'string') return null
  if (!NAME_PATTERN.test(name)) return null
  if (name.length > NAME_MAX_LENGTH) return null

  const base = resolve(baseDir)
  const path = resolve(join(base, name))

  try {
    if (path !== base && !path.startsWith(base + '/')) return null
  } catch {
    return null
  }

  return path
}

/**
 * True, wenn ein Eintrag in modules/plugins bzw. modules/base_plugins ein
 * echtes Plugin ist.
 *
 * ``__pycache__`` ist selbst ein Verzeichnis und damit vom Datei-Filter
 * nicht erreichbar - es erschien deshalb in /api/editor/ als installiertes
 * Plugin.
 */
export function isPluginDirectory(path: string): boolean {
  const name = basename(path)
  if (name.startsWith('.') || name.startsWith('_')) return false
  try {
    return statSync(path).isDirectory()
  } catch {
    return false
  }
}

/**
 * Prueft, ob ein Name ein gueltiges Plugin-Verzeichnis ist.
 */
export function isValidPluginName(name: string): boolean {
  if (!NAME_PATTERN.test(name)) return false
  if (name.length > NAME_MAX_LENGTH) return false
  return true
}

/**
 * Merge-Helper: verschachtelte Dicts zusammenfuehren.
 * Gegenstueck zu modules/addon/endpoints.py: merge()
 */
export function merge(source: Record<string, unknown>, destination: Record<string, unknown>): Record<string, unknown> {
  for (const [key, value] of Object.entries(source)) {
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      const node = (destination[key] ?? {}) as Record<string, unknown>
      destination[key] = merge(value as Record<string, unknown>, node)
    } else {
      destination[key] = value
    }
  }
  return destination
}