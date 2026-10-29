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
 *
 * Hinweis: Dies ist eine vereinfachte Implementierung als Stub.
 * Die vollständige Python-Funktionalität (Git, Datei-Upload, etc.)
 * würde zusätzliche Abhängigkeiten und TypeScript-Definitionen erfordern.
 */
import type { Api } from '../../core/api.ts'
import type { RequestContext } from '../../http/router.ts'
import { Router } from '../../http/router.ts'
import { json, noContent } from '../../http/respond.ts'

export function registerEditorModule(
  router: Router,
  deps: { api: Api },
): void {
  const api = deps.api

  // GET /api/editor/ - Liste aller Plugins
  router.add('GET', '/api/editor/', 'addon.getPlugins', () => {
    api.log('info', 'GET /api/editor/ - Editor list requested')
    return json([])
  })

  // GET /api/editor/<name> - Plugin-Code
  router.add('GET', '/api/editor/<name>', 'addon.getFile', (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    api.log('info', `GET /api/editor/${name} - Plugin file requested`)
    return json('')
  })

  // PUT /api/editor/<name> - Plugin anlegen
  router.add('PUT', '/api/editor/<name>', 'addon.createPlugin', (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    api.log('info', `PUT /api/editor/${name} - Create plugin requested`)
    api.emitMessage(`Plugin ${name} created`)
    return noContent()
  })

  // POST /api/editor/<name> - Plugin-Code speichern
  router.add('POST', '/api/editor/<name>', 'addon.saveFile', (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    api.log('info', `POST /api/editor/${name} - Save plugin requested`)
    return noContent()
  })

  // DELETE /api/editor/<name> - Plugin loeschen
  router.add('DELETE', '/api/editor/<name>', 'addon.deletePlugin', (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    api.log('info', `DELETE /api/editor/${name} - Delete plugin requested`)
    api.emitMessage(`Plugin ${name} deleted`)
    return noContent()
  })

  // POST /api/editor/<name>/reload/ - Plugin neu laden
  router.add('POST', '/api/editor/<name>/reload/', 'addon.reload_plugin', (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    api.log('info', `POST /api/editor/${name}/reload/ - Reload plugin requested`)
    return noContent()
  })

  // POST /api/editor/<name>/download - Plugin downloaden
  router.add('POST', '/api/editor/<name>/download', 'addon.download_addon', (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    api.log('info', `POST /api/editor/${name}/download - Download plugin requested`)
    return noContent()
  })

  // POST /api/editor/<name>/update - Plugin updaten
  router.add('POST', '/api/editor/<name>/update', 'addon.update_addon', (ctx: RequestContext) => {
    const name = ctx.params.name ?? ''
    api.log('info', `POST /api/editor/${name}/update - Update plugin requested`)
    return noContent()
  })

  // GET /api/editor/list - Offizielle Plugin-Liste
  router.add('GET', '/api/editor/list', 'addon.plugins', () => {
    api.log('info', 'GET /api/editor/list - Official plugins list requested')
    return json({})
  })
}