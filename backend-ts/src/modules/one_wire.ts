/**
 * /api/one_wire - One-Wire Temperatur-Sensoren (Test/Stub).
 *
 * Gegenstueck zu modules/base_plugins/one_wire/__init__.py.
 * Einfacher Endpunkt zum Setzen der Test-Temperatur.
 */
import type { Api } from '../core/api.ts'
import type { Router } from '../http/router.ts'
import { json, noContent } from '../http/respond.ts'

export function registerOneWireRoutes(router: Router, api: Api): void {
  // GET /api/one_wire/<int:t> - Temperatur setzen (Test)
  router.add('GET', '/api/one_wire/<int:t>', 'one_wire.set_temp', (ctx) => {
    const t = Number(ctx.params.t)
    api.log('info', `1-Wire set_temp: ${t}°C (stub)`)
    return noContent()
  })
}