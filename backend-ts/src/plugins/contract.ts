/**
 * Plugin-Vertrag.
 *
 * Die Laufzeit ist noch nicht entschieden (P1 Decorator, P2 Manifest,
 * P3 Worker, P4 Python-Bridge - siehe REWRITE-TS.md Abschnitt 9).
 * Der Vertrag ist trotzdem fix: alles, was ein Plugin liefert, steht
 * hier. Die vier Varianten unterscheiden sich nur darin, wie ein
 * PluginManifest entsteht und geladen wird.
 *
 * Entscheidend ist die Form von PropertyDescriptor: sie speist
 * /api/system/dump und die Konfigurationsdialoge. Sie entspricht 1:1
 * dem, was __parseProps im Python-Kern in den Cache schreibt.
 */
import type { Api } from '../core/api.ts'

export type PluginKind =
  | 'actor'
  | 'sensor'
  | 'controller'
  | 'fermentation_controller'
  | 'step'

export type PropertyType =
  | 'number'
  | 'text'
  | 'select'
  | 'actor'
  | 'sensor'
  | 'kettle'

export interface PropertyDescriptor {
  name: string
  label: string
  type: PropertyType
  configurable: boolean
  description?: string
  default_value?: unknown
  options?: unknown[]
}

export interface ActionDescriptor {
  method: string
  label: string
}

export type PluginApi = Api

export interface PluginInstance {
  init?(): void | Promise<void>
  stop?(): void | Promise<void>
  execute?(): void | Promise<void>
  /** Actor */
  on?(power?: unknown): void | Promise<void>
  off?(): void | Promise<void>
  set_power?(power?: unknown): void | Promise<void>
  /** Sensor */
  get_value?(): unknown
  /** Sensor: passive Sensoren werden vom Hintergrundtask gelesen. */
  read?(): unknown
  /** Controller: blockierende Regelschleife, laeuft bis stop(). */
  run?(): void | Promise<void>
  is_running?(): boolean
  /** Controller: Kessel-/Fermenter-Helfer (siehe plugins/controller.ts). */
  heater_on?(power?: number): void | Promise<void>
  heater_off?(): void | Promise<void>
  get_temp?(): number | null
  get_target_temp?(): number | null
  actor_on?(power?: number, id?: number): void | Promise<void>
  actor_off?(id?: number): void | Promise<void>
  actor_power?(power: number, id?: number): void | Promise<void>
  get_sensor_value?(id?: number): number | null
}

export interface PluginManifest {
  kind: PluginKind
  /** Klassenname im Cache, z. B. "Hysteresis". */
  name: string
  /**
   * Python-Modulname fuer den Cache-Dump, z. B.
   * "modules.base_plugins.dummy_temp". Default: Pfad des Plugins.
   */
  module?: string
  properties: PropertyDescriptor[]
  actions?: ActionDescriptor[]
  create(api: PluginApi, config: Record<string, unknown>): PluginInstance
}

export interface DiscoveredPlugin {
  scope: 'base' | 'user'
  name: string
  directory: string
}

export interface PluginHost {
  discover(): DiscoveredPlugin[]
  loadAll(): Promise<void>
  get(kind: PluginKind, name: string): PluginManifest | undefined
  list(): PluginManifest[]
  reload(name: string): Promise<void>
  /**
   * Erzeugt eine Plugin-Instanz aus einem Manifest und speichert sie im Cache.
   * Der config-Parameter überschreibt die Standardkonfiguration aus dem Manifest.
   */
  create(kind: PluginKind, name: string, api: Api, config?: Record<string, unknown>): PluginInstance | undefined
}
