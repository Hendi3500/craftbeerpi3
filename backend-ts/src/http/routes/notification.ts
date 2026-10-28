/**
 * /api/notification - Nachrichten-Cache und Wegklicken.
 *
 * Der MESSAGE-Handler liegt in src/index.ts, weil er beim Boot
 * registriert wird. Hier stehen nur die beiden Routen.
 */
import type { Api } from '../../core/api.ts'
import type { Router } from '../router.ts'
import { json, noContent } from '../respond.ts'

export function registerNotificationRoutes(router: Router, api: Api): void {
  router
    .add('GET', '/api/notification/', 'NotificationView:getMessages', () =>
      json(api.messages()),
    )
    .add(
      'DELETE',
      '/api/notification/<id>',
      'NotificationView:dismiss',
      (ctx) => {
        const list = api.messages()
        const id = ctx.params.id ?? ''
        const index = list.findIndex((message) => String(message.id) === id)
        if (index >= 0) list.splice(index, 1)

        // Auch ohne Treffer: ein Client, der eine bereits geloeschte
        // Nachricht wegklickt, muss trotzdem Bescheid bekommen.
        api.emit('NOTIFY_DISMISS', id)
        return noContent()
      },
    )
}
