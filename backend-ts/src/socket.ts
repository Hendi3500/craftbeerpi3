/**
 * socket.io - Namespace /brew, reiner Server->Client-Push.
 *
 * Der Namespace /brew muss ohne registrierten Handler erreichbar sein;
 * der Client verbindet sich nur zum Empfangen. CORS ist offen, weil das
 * Backend ausschliesslich im LAN gebunden ist und ein Reverse Proxy den
 * Host-Header umschreibt.
 *
 * Events (12 Events):
 *   SENSOR_UPDATE            <- Sensor wert
 *   SWITCH_ACTOR             <- Aktor ein/aus/macht
 *   UPDATE_KETTLE            <- Kessel status
 *   UPDATE_KETTLE_TARGET_TEMP <- Kesseltargettemp
 *   UPDATE_FERMENTER         <- Fermenter status
 *   UPDATE_FERMENTER_TARGET_TEMP <- Fermenter targettemp
 *   UPDATE_FERMENTER_BREWNAME <- Fermenter braunname
 *   UPDATE_ALL_STEPS         <- Schritte aktualisiert
 *   UPDATE_CONFIG            <- Config aktualisiert
 *   NOTIFY                   <- Persistente Notification
 *   NOTIFY_DISMISS           <- Notification loeschen
 *   RESTART_SCHEDULED        <- Neustart geplant
 */
import type { Server as HttpServer } from 'node:http'
import { Server } from 'socket.io'

export function createSocket(http: HttpServer): Server {
  const io = new Server(http, {
    cors: { origin: '*', methods: ['GET', 'POST'] },
    serveClient: false,
  })

  io.of('/brew')

  return io
}