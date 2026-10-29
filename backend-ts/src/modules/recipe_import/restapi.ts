/**
 * /api/recipe/import/v1 - REST Rezept-Import.
 *
 * Gegenstueck zu modules/recipe_import/restapi.py. Einfacher Stub,
 * der ein Rezept aus einem JSON-Body in Steps konvertiert.
 */
import type { Api } from '../../core/api.ts'
import type { Router } from '../../http/router.ts'
import { json, noContent } from '../../http/respond.ts'

export function registerRestImportRoutes(router: Router, api: Api): void {
  // POST /api/recipe/import/v1/ - Rezept per REST laden
  router.add('POST', '/api/recipe/import/v1/', 'RESTImport:load', async (ctx) => {
    try {
      const data = await ctx.json<Record<string, unknown>>()
      const name = String(data.name ?? 'No Name')

      api.notify('Recipe loaded successfully', name)
      return noContent()
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      api.notify('Failed to load Recipe', message, 'danger')
      return json({ message }, 500)
    }
  })
}