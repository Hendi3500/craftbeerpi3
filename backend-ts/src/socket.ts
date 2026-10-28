/**
 * socket.io - Namespace /brew, reiner Server->Client-Push.
 *
 * Der Namespace /brew muss ohne registrierten Handler erreichbar sein;
 * der Client verbindet sich nur zum Empfangen. CORS ist offen, weil das
 * Backend ausschliesslich im LAN gebunden ist und ein Reverse Proxy den
 * Host-Header umschreibt.
 */
import type { Server as HttpServer } from 'node:http'
import { Server } from 'socket.io'

export function createSocket(http: HttpServer): Server {
  const io = new Server(http, {
    cors: { origin: '*', methods: ['GET', 'POST'] },
    // Das Frontend bringt seinen Client selbst mit. Python hat die Datei
    // ebenfalls separat ausgeliefert (modules/ui/static/socket.io.min.js).
    serveClient: false,
  })

  io.of('/brew')
  return io
}
