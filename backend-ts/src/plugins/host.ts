/**
 * P2-Manifest-Laufzeit.
 *
 * Ein Plugin ist eine ESM-Datei (`plugin.ts`, `plugin.js` oder `plugin.mjs`)
 * in einem Plugin-Verzeichnis. Sie exportiert ein Manifest (default oder
 * benannt `manifest`):
 *
 *   export default {
 *     kind: 'sensor',
 *     name: 'DummyTempSensor',
 *     module: 'modules.base_plugins.dummy_temp',
 *     properties: [
 *       { name: 'temp', label: 'Temperature', type: 'number',
 *         configurable: true, default_value: 20 },
 *     ],
 *     create(api, config) {
 *       return { getValue: () => Number(config.temp ?? 20) }
 *     },
 *   }
 *
 * Kein Build-Schritt: Node fuehrt TypeScript ueber Type-Stripping aus.
 * Deshalb gibt es keine Dekoratoren - P2 ist die Variante, die ohne
 * Compiler auskommt (Entscheidung siehe REWRITE-TS.md Abschnitt 9).
 *
 * Der Cache bekommt pro Typ einen Eintrag in der Form des Python-Kerns:
 *
 *   { name, class, properties, actions }
 *
 * `class` ist im Original die Plugin-Klasse und wird im Dump zu
 * {name, module}. Hier steht dafuer eine Markerfunktion mit denselben
 * Feldern, damit /api/system/dump unveraendert bleibt.
 */
import { existsSync, readdirSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { basename, join, relative } from 'node:path'
import type { Api } from '../core/api.ts'
import type { Cache } from '../core/cache.ts'
import type { Logger } from '../logger.ts'
import type {
  DiscoveredPlugin,
  PluginHost,
  PluginInstance,
  PluginKind,
  PluginManifest,
  PropertyDescriptor,
} from './contract.ts'
import type { Row } from '../db.ts'

const FILES = ['plugin.ts', 'plugin.js', 'plugin.mjs']

export const TYPE_CACHE: Record<PluginKind, string> = {
  actor: 'actor_types',
  sensor: 'sensor_types',
  controller: 'controller_types',
  fermentation_controller: 'fermentation_controller_types',
  step: 'step_types',
}

const KINDS = new Set(Object.keys(TYPE_CACHE))

function isPluginDirectory(path: string): boolean {
  if (!existsSync(path)) return false
  const name = basename(path)
  return !name.startsWith('.') && !name.startsWith('_')
}

function marker(manifest: PluginManifest): () => void {
  const fn = function pluginClass(): void {}
  Object.defineProperty(fn, 'name', { value: manifest.name })
  Object.defineProperty(fn, '__module__', {
    value: manifest.module ?? manifest.name,
  })
  return fn
}

/** Property in der Form, die __parseProps in den Cache schreibt. */
function propertyEntry(property: PropertyDescriptor): Record<string, unknown> {
  const base: Record<string, unknown> = {
    name: property.name,
    label: property.label,
    type: property.type,
    configurable: property.configurable,
    description: property.description ?? null,
  }

  // Select hat im Original keinen default_value, die uebrigen Typen schon.
  if (property.type !== 'select') {
    base.default_value = property.default_value ?? null
  }
  if (property.type === 'select') {
    base.options = property.options ?? []
  }
  return base
}

export function typeEntry(manifest: PluginManifest): Record<string, unknown> {
  return {
    name: manifest.name,
    class: marker(manifest),
    properties: manifest.properties.map(propertyEntry),
    actions: (manifest.actions ?? []).map((action) => ({
      method: action.method,
      label: action.label,
    })),
  }
}

function validate(manifest: unknown, source: string): PluginManifest {
  if (typeof manifest !== 'object' || manifest === null) {
    throw new Error(`${source}: manifest is not an object`)
  }

  const candidate = manifest as Partial<PluginManifest>
  if (!candidate.kind || !KINDS.has(candidate.kind)) {
    throw new Error(`${source}: unknown plugin kind ${String(candidate.kind)}`)
  }
  if (typeof candidate.name !== 'string' || candidate.name === '') {
    throw new Error(`${source}: manifest.name is missing`)
  }
  if (!Array.isArray(candidate.properties)) {
    throw new Error(`${source}: manifest.properties must be an array`)
  }
  if (typeof candidate.create !== 'function') {
    throw new Error(`${source}: manifest.create must be a function`)
  }

  return candidate as PluginManifest
}

export class ManifestPluginHost implements PluginHost {
  private readonly discovered: DiscoveredPlugin[]
  private readonly loaded = new Map<string, PluginManifest>()
  private readonly files = new Map<string, string>()
  private readonly root: string
  private readonly logger: Logger

  constructor(root: string, logger: Logger) {
    this.root = root
    this.logger = logger
    // Die TypeScript-Plugins liegen unter backend-ts/src/modules. `root` ist
    // die Projektwurzel (config/, update/, logs/, craftbeerpi.db); die
    // Python-Plugins unter <root>/modules sind fuer diese Laufzeit irrelevant.
    const modules = join(root, 'backend-ts', 'src', 'modules')
    this.discovered = [
      ...this.scan('base', join(modules, 'base_plugins')),
      ...this.scan('user', join(modules, 'plugins')),
    ]
  }

  private scan(scope: 'base' | 'user', dir: string): DiscoveredPlugin[] {
    if (!existsSync(dir)) return []
    try {
      return readdirSync(dir)
        .map((name) => join(dir, name))
        .filter((path) => isPluginDirectory(path))
        .map((path) => ({ scope, name: basename(path), directory: path }))
    } catch (error) {
      this.logger.warning(
        `Plugin directory ${dir} not readable: ${
          error instanceof Error ? error.message : String(error)
        }`,
      )
      return []
    }
  }

  discover(): DiscoveredPlugin[] {
    return [...this.discovered]
  }

  private key(kind: PluginKind, name: string): string {
    return `${kind}:${name}`
  }

  /** Programmatisch registrieren (Tests, spaeter auch Core-Plugins). */
  register(manifest: PluginManifest): void {
    const checked = validate(manifest, 'manifest')
    this.loaded.set(this.key(checked.kind, checked.name), checked)
  }

  private moduleName(directory: string): string {
    // Python-Modulname fuer /api/system/dump: "modules.base_plugins.x".
    const src = join(this.root, 'backend-ts', 'src')
    return relative(src, directory)
      .split(/[\\/]/)
      .join('.')
  }

  private async importPlugin(entry: DiscoveredPlugin): Promise<void> {
    const file = FILES.map((name) => join(entry.directory, name)).find((path) =>
      existsSync(path),
    )
    if (!file) {
      this.logger.debug(
        `Plugin ${entry.scope}/${entry.name} has no plugin.ts/js - skipped`,
      )
      return
    }

    const url = pathToFileURL(file)
    // Cache-Busting fuer reload(); ohne Query liefert Node das alte Modul.
    if (this.files.has(entry.name)) url.searchParams.set('v', String(Date.now()))

    const module = (await import(url.href)) as {
      default?: unknown
      manifest?: unknown
    }
    // Eine Datei darf mehrere Klassen desselben Python-Moduls exportieren
    // (z. B. GPIOSimple und GPIOPWM). Dann ist der Default ein Array.
    const raw = module.manifest ?? module.default
    const manifests = Array.isArray(raw) ? raw : [raw]
    this.files.set(entry.name, file)
    for (const candidate of manifests) {
      const manifest = validate(candidate, `plugin ${entry.scope}/${entry.name}`)
      if (manifest.module === undefined) {
        manifest.module = this.moduleName(entry.directory)
      }
      this.register(manifest)
    }
  }

  async loadAll(): Promise<void> {
    for (const entry of this.discovered) {
      try {
        await this.importPlugin(entry)
      } catch (error) {
        // Ein defektes Plugin darf nicht den ganzen Start verhindern;
        // Python wuerde hier mit einem Traceback abbrechen. Der Fehler
        // wird laut protokolliert, das Plugin bleibt ungeladen.
        this.logger.error(
          `Plugin ${entry.scope}/${entry.name} not loaded: ${
            error instanceof Error ? error.message : String(error)
          }`,
        )
      }
    }

    const kinds = new Set([...this.loaded.values()].map((entry) => entry.kind))
    this.logger.info(
      `Plugins loaded: ${this.loaded.size} (${[...kinds].sort().join(', ') || 'none'})`,
    )
  }

  /** Typ-Caches fuellen, wie __parseProps im Python-Kern. */
  populate(cache: Cache): void {
    for (const key of Object.values(TYPE_CACHE)) cache.set(key, {})

    for (const manifest of this.loaded.values()) {
      const key = TYPE_CACHE[manifest.kind]
      const types = cache.getOr<Record<string, unknown>>(key, () => ({}))
      types[manifest.name] = typeEntry(manifest)
    }
  }

  get(kind: PluginKind, name: string): PluginManifest | undefined {
    return this.loaded.get(this.key(kind, name))
  }

  list(): PluginManifest[] {
    return [...this.loaded.values()]
  }

  create(kind: PluginKind, name: string, api: Api, config?: Record<string, unknown>): PluginInstance | undefined {
    const manifest = this.get(kind, name)
    if (!manifest) {
      this.logger.warning(`Plugin manifest not found: ${kind}:${name}`)
      return undefined
    }
    try {
      return manifest.create(api, config ?? {})
    } catch (error) {
      this.logger.error(`Failed to create plugin ${kind}:${name}: ${error instanceof Error ? error.message : String(error)}`)
      return undefined
    }
  }

  /**
   * Create all plugin instances from loaded manifests.
   * This method expects the API instance to be passed because manifests require it.
   */
  /**
   * Create all plugin instances from loaded manifests.
   * This method creates instances and stores them in the API cache.
   * The instances are stored per-kind and are available via
   * cbpi.cache["actors"], cbpi.cache["sensors"], etc.
   *
   * Note: This overwrites any existing DB-row-only entries in the cache
   * with plugin-instantiated objects that have the same structure plus
   * an .instance field and runtime state.
   */
  createAll(api: Api, cache: Cache): void {
    for (const manifest of this.loaded.values()) {
      const kind = manifest.kind
      const name = manifest.name

      try {
        const instance = manifest.create(api, {})
        if (instance === undefined) continue

        const key = TYPE_CACHE[kind]
        if (!key) {
          this.logger.debug(`No cache key for plugin kind: ${kind}`)
          continue
        }

        const typeCache = cache.getOr<Record<string, unknown>>(key, () => ({}))

        // For actors and sensors, also store the instance in each DB entry
        if (kind === 'actor' || kind === 'sensor') {
          // Get existing entries of this type from the cache
          const existingEntries = cache.get<Record<string, Row>>(key) || {}
          const instanceEntry: Record<string, unknown> = {
            name,
            class: marker(manifest),
            properties: manifest.properties.map(propertyEntry),
            actions: (manifest.actions ?? []).map((action) => ({
              method: action.method,
              label: action.label,
            })),
            instance,
          }

          // If there are DB entries of this type, enhance them with instance data
          if (existingEntries && typeof existingEntries !== 'function') {
            for (const [entryId, entry] of Object.entries(existingEntries)) {
              if (entry && typeof entry === 'object') {
                // Merge instance data into the entry
                const enhancedEntry = { ...entry, instance }
                typeCache[entryId] = enhancedEntry
              }
            }
          }

          // Also set a global entry for the kind
          typeCache['global'] = {
            name,
            class: marker(manifest),
            properties: manifest.properties.map(propertyEntry),
            actions: (manifest.actions ?? []).map((action) => ({
              method: action.method,
              label: action.label,
            })),
            instance,
          }
        } else {
          // For controllers and other kinds, store globally
          typeCache['global'] = {
            name,
            class: marker(manifest),
            properties: manifest.properties.map(propertyEntry),
            actions: (manifest.actions ?? []).map((action) => ({
              method: action.method,
              label: action.label,
            })),
            instance,
          }
        }

        typeCache[name] = {
          name,
          class: marker(manifest),
          properties: manifest.properties.map(propertyEntry),
          actions: (manifest.actions ?? []).map((action) => ({
            method: action.method,
            label: action.label,
          })),
        }
        cache.set(key, typeCache)

        this.logger.debug(`Plugin ${kind}:${name} instantiated successfully`)
      } catch (error) {
        this.logger.error(
          `Plugin ${kind}:${name} failed to create: ${
            error instanceof Error ? error.message : String(error)
          }`,
        )
      }
    }
  }

  async reload(name: string): Promise<void> {
    const file = this.files.get(name)
    if (!file) {
      throw new Error(`Plugin ${name} was not loaded from a file`)
    }

    const entry = this.discovered.find((candidate) => candidate.name === name)
    if (!entry) throw new Error(`Plugin ${name} is not discovered`)

    await this.importPlugin(entry)
  }
}