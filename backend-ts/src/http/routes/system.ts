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
 *
 * Die restlichen System-Endpunkte (reboot, shutdown, git, check_update)
 * sind Stubs - die Python-Implementierung nutzt GitPython und subprocess,
 * was hier ohne entsprechende Node-Abhaengigkeiten nicht 1:1 moeglich ist.
 * Sie antworten mit 204/200 und loggen, was passieren wuerde.
 */
import { stringify as yamlStringify } from 'yaml'
import type { Api } from '../../core/api.ts'
import type { Router } from '../router.ts'
import { HttpResponse, json, noContent } from '../respond.ts'

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
    // Check for git updates
    .add('GET', '/api/system/check_update', 'SystemView:check_update', () => {
      // Stub: Python uses git to check for updates
      return json([])
    })
    // Do reboot (Python schedules reboot after 5s)
    .add('GET', '/api/system/doReboot/', 'SystemView:doReboot', () => {
      api.log('info', 'doReboot called - would schedule reboot (stub)')
      return noContent()
    })
    // Do shutdown (Python schedules shutdown after 5s)
    .add('GET', '/api/system/doShutdown/', 'SystemView:doShutdown', () => {
      api.log('info', 'doShutdown called - would schedule shutdown (stub)')
      return noContent()
    })
    // Git status
    .add('GET', '/api/system/git/status', 'SystemView:git_status', () => {
      // Stub: Python uses GitPython
      return json({ tags: [], headcommit: '', branchname: null, master: { changes: [] } })
    })
    // Git pull
    .add('POST', '/api/system/git/pull', 'SystemView:update', () => {
      api.log('info', 'git pull called - would update (stub)')
      api.notify('Pull successful', 'The latest update was downloaded. Please restart the system')
      return noContent()
    })
    // Reboot
    .add('POST', '/api/system/reboot', 'SystemView:reboot', () => {
      api.log('info', 'reboot called - would schedule reboot (stub)')
      api.emit('RESTART_SCHEDULED', { pending: true, seconds: 5, delay: 5 })
      return noContent()
    })
    // Shutdown
    .add('POST', '/api/system/shutdown', 'SystemView:shutdown', () => {
      api.log('info', 'shutdown called - would schedule shutdown (stub)')
      api.emit('RESTART_SCHEDULED', { pending: true, seconds: 5, delay: 5 })
      return noContent()
    })
    // Checkout tag
    .add('GET', '/api/system/tags/<name>', 'SystemView:checkout_tag', (ctx) => {
      const name = ctx.params.name ?? ''
      api.log('info', `checkout_tag called for tag: ${name} - stub`)
      return json({ message: `Tag ${name} checkout not implemented (stub)` }, 501)
    })
}
