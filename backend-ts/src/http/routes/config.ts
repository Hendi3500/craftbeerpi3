/**
 * /api/config - Referenzmodul fuer den Port.
 *
 * Gegenstueck zu modules/config/__init__.py. Die Sonderfaelle sind
 * Absicht und stehen so in der Baseline:
 *   GET    /api/config/         Liste (Cache, nach Name)
 *   PUT    /api/config/<name>   nur value aendern
 *   GET    /api/config/<id>     400 NOT SUPPORTED
 *   DELETE /api/config/<id>     400 NOT SUPPORTED
 *   POST   /api/config/         400 NOT SUPPORTED
 */
import type { Api } from '../../core/api.ts'
import type { Row, Table } from '../../db.ts'
import { HttpError, type Router } from '../router.ts'
import { error, json } from '../respond.ts'

export function initConfigCache(api: Api, table: Table): void {
  const rows = table.all() as Record<string, Row>
  const cache: Record<string, Row> = {}
  for (const row of Object.values(rows)) {
    cache[String(row.name)] = row
  }
  api.cache.set('config', cache)
}

export function registerConfigRoutes(
  router: Router,
  api: Api,
  table: Table,
): void {
  router
    .add('GET', '/api/config/', 'ConfigView:getAll', () => json(api.config()))
    .add('POST', '/api/config/', 'ConfigView:post', () =>
      error('NOT SUPPORTED', 400),
    )
    .add('GET', '/api/config/<id>', 'ConfigView:getOne', () =>
      error('NOT SUPPORTED', 400),
    )
    .add('DELETE', '/api/config/<id>', 'ConfigView:delete', () =>
      error('NOT SUPPORTED', 400),
    )
    .add('PUT', '/api/config/<name>', 'ConfigView:put', async (ctx) => {
      const name = ctx.params.name ?? ''
      if (!api.configEntry(name)) {
        // Der Kern laeuft hier in einen KeyError und antwortet 500. Ein
        // unbekannter Name ist aber ein Client-Fehler (D-8).
        throw new HttpError(400, `Unknown config parameter: ${name}`)
      }

      const body = await ctx.json<Record<string, unknown>>()
      if (!Object.hasOwn(body, 'value')) {
        throw new HttpError(400, 'Bad Request: value missing')
      }

      return json(api.setConfigParameter(name, body.value))
    })
}
