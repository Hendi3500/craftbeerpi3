/**
 * /api/editor - Editor für Plugins und Konfiguration.
 *
 * Gegenstueck zu modules/addon/endpoints.py.
 * Ermöglicht das Verwalten von Plugins und Konfigurationsparameter via REST API.
 *
 * Endpoint-Namen entsprechen dem Python-Blueprint "addon":
 *   addon.getPlugins, addon.deletePlugin, addon.getFile,
 *   addon.saveFile, addon.createPlugin, addon.download_addon,
 *   addon.reload_plugin, addon.update_addon, addon.plugins
 */
import type { Api } from '../../core/api.ts'
import type { RequestContext } from '../../http/router.ts'
import { Router } from '../../http/router.ts'
import { json, noContent } from '../../http/respond.ts'

export interface EditorDependencies {
  api: Api
}

/**
 * Registriere das Editor-Modul am Router.
 */
export function registerEditorModule(
  router: Router,
  deps: EditorDependencies,
): void {
  const api = deps.api

  // GET /api/editor/ - Liste aller Plugins
  router.add('GET', '/api/editor/', 'addon.getPlugins', async (ctx: RequestContext) => {
    const PLUGIN_DIR = './modules/plugins'
    try {
      const fs = require('node:fs')
      const files = fs.readdirSync(PLUGIN_DIR).filter(
        (f: string) =>
          !f.endsWith('.DS_Store') &&
          !f.endsWith('.py') &&
          !f.endsWith('.pyc'),
      )
      const result = files.filter((filename: string) => {
        try {
          const path = require('node:path').join(PLUGIN_DIR, filename)
          return true
        } catch {
          return false
        }
      })
      return json(result)
    } catch {
      return json([], 500)
    }
  })

  // GET /api/editor/<name> - Plugin-Code
  router.add('GET', '/api/editor/<name>', 'addon.getFile', async (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    // Stub: gib leeren Code zurueck
    return json('')
  })

  // PUT /api/editor/<name> - Plugin anlegen
  router.add('PUT', '/api/editor/<name>', 'addon.createPlugin', async (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    // Stub: lege Verzeichnis an
    return noContent()
  })

  // POST /api/editor/<name> - Plugin-Code speichern
  router.add('POST', '/api/editor/<name>', 'addon.saveFile', async (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    // Stub: speichere Datei
    return noContent()
  })

  // DELETE /api/editor/<name> - Plugin loeschen
  router.add('DELETE', '/api/editor/<name>', 'addon.deletePlugin', async (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    // Stub: loesche Verzeichnis
    return noContent()
  })

  // POST /api/editor/<name>/reload/ - Plugin neu laden
  router.add('POST', '/api/editor/<name>/reload/', 'addon.reload_plugin', async (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    // Stub: lade Plugin neu
    return noContent()
  })

  // POST /api/editor/<name>/download - Plugin downloaden
  router.add('POST', '/api/editor/<name>/download', 'addon.download_addon', async (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    // Stub: download via Git
    return noContent()
  })

  // POST /api/editor/<name>/update - Plugin updaten
  router.add('POST', '/api/editor/<name>/update', 'addon.update_addon', async (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    // Stub: updte via Git
    return noContent()
  })

  // GET /api/editor/list - Offizielle Plugin-Liste
  router.add('GET', '/api/editor/list', 'addon.plugins', async (ctx: RequestContext) => {
    // Stub: gib leeres Object zurueck
    return json({})
  })
}