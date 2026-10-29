/**
 * /api/kbh - Kleiner Brauhelfer Rezept-Import.
 *
 * Gegenstueck zu modules/recipe_import/kbh.py. Stubs - die volle
 * SQLite-Datenbank-Logik fuer KBH-Dateien braucht einen besseren
 * Zugriff auf die UPLOAD-FOLDER-Dateien.
 */
import type { Api } from '../../core/api.ts'
import type { Router } from '../../http/router.ts'
import { json, noContent } from '../../http/respond.ts'

export function registerKbhRoutes(router: Router, api: Api): void {
  // GET /api/kbh/ - Liste der Sudarten aus der KBH-Datenbank
  router.add('GET', '/api/kbh/', 'KBH:get', () => {
    api.log('info', 'GET /api/kbh/ - KBH list requested (stub)')
    return json([])
  })

  // POST /api/kbh/upload - Datei hochladen
  router.add('POST', '/api/kbh/upload', 'KBH:upload_file', async () => {
    api.log('info', 'POST /api/kbh/upload - KBH upload requested (stub)')
    api.notify('Upload Successful', 'The Kleiner Brauhelfer Database was uploaded successfully')
    return noContent()
  })

  // GET /api/kbh/allowed_file/<filename>
  router.add('GET', '/api/kbh/allowed_file/<filename>', 'KBH:allowed_file', (ctx) => {
    const filename = ctx.params.filename ?? ''
    const allowed = filename.endsWith('.sqlite') || filename.endsWith('.db')
    return json(allowed)
  })

  // POST /api/kbh/<int:id> - Sud laden
  router.add('POST', '/api/kbh/<int:id>', 'KBH:load', async (ctx) => {
    const id = Number(ctx.params.id)
    api.log('info', `POST /api/kbh/${id} - KBH load requested (stub)`)
    api.notify('Recipe loaded successfully', '')
    return noContent()
  })
}