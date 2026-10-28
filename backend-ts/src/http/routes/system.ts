/**
 * /api/system - in M0 die zwei lesenden Endpunkte.
 *
 * dump und endpoints sind die ersten Ziele der Fixture-Pruefung, weil
 * sie den kompletten Cache bzw. die komplette Routentabelle abbilden.
 * Genau dort faellt jede Paritaetsabweichung sofort auf.
 *
 * endpoints: das YAML wird sortiert erzeugt (wie PyYAML mit
 * sort_keys=True). Fuer den Fixture-Vergleich wird trotzdem geparst
 * verglichen, nicht byteweise.
 */
import { stringify as yamlStringify } from 'yaml'
import type { Api } from '../../core/api.ts'
import type { Router } from '../router.ts'
import { HttpResponse, json } from '../respond.ts'

export function registerSystemRoutes(router: Router, api: Api): void {
  router
    .add('GET', '/api/system/dump', 'SystemView:dump', () => json(api.dump()))
    .add('GET', '/api/system/endpoints', 'SystemView:endpoints', () => {
      const paths: Record<string, Record<string, unknown>> = {}

      for (const { rule, methods } of router.rules()) {
        const entry: Record<string, unknown> = {}
        for (const method of methods) {
          entry[method] = {
            summary: '',
            description: '',
            consumes: ['application/json'],
            produces: ['application/json'],
          }
        }
        paths[rule] = entry
      }

      const document = {
        swagger: '2.0',
        host: '',
        info: { description: '', version: '', title: 'CraftBeerPi' },
        schemes: ['http'],
        paths,
      }

      return new HttpResponse(200, yamlStringify(document, { sortMapEntries: true }), {
        'Content-Type': 'text/yaml; charset=utf-8',
      })
    })
}
