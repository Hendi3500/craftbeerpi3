/**
 * /api/logs - Gegenstueck zu modules/logs/endpoints.py.
 *
 * Die Logs liegen unter <root>/logs. Python arbeitet mit "./logs" relativ
 * zum Projektverzeichnis; hier wird der Root explizit uebergeben, damit
 * das Verhalten nicht vom Arbeitsverzeichnis des Prozesses abhaengt.
 *
 * Formate (unveraendert):
 *   action.log        CSV: "YYYY-MM-DD HH:MM:SS,Text"
 *   <type>_<id>.log   CSV: "YYYY-MM-DD HH:MM:SS,Wert"
 *
 * Zeitstempel werden wie datetime.strptime(...) - datetime(1970,1,1)
 * berechnet: die Wanduhrzeit wird als UTC interpretiert, nicht in die
 * lokale Zeitzone umgerechnet.
 */
import {
  existsSync,
  readFileSync,
  readdirSync,
  unlinkSync,
} from 'node:fs'
import { join } from 'node:path'
import type { Api } from '../core/api.ts'
import type { Row } from '../db.ts'
import { HttpError, type Router } from '../http/router.ts'
import { error, HttpResponse, json } from '../http/respond.ts'

const LOG_NAME = /^([A-Za-z0-9-_])+\.log$/
const TIMESTAMP = /^(\d{4})-(\d{1,2})-(\d{1,2}) (\d{1,2}):(\d{1,2}):(\d{1,2})$/

export function isLogName(name: string): boolean {
  return LOG_NAME.test(name)
}

/** Ein CSV-Feld; akzeptiert Quotes wie der Python-csv-Reader. */
function parseCsvLine(line: string): string[] {
  const fields: string[] = []
  let current = ''
  let quoted = false
  let index = 0

  while (index < line.length) {
    const char = line[index]
    if (quoted) {
      if (char === '"') {
        if (line[index + 1] === '"') {
          current += '"'
          index += 2
          continue
        }
        quoted = false
        index += 1
        continue
      }
      current += char
      index += 1
      continue
    }

    if (char === '"' && current === '') {
      quoted = true
      index += 1
      continue
    }
    if (char === ',') {
      fields.push(current)
      current = ''
      index += 1
      continue
    }
    current += char
    index += 1
  }

  fields.push(current)
  return fields
}

/** "YYYY-MM-DD HH:MM:SS" wie strptime, Ergebnis in Millisekunden. */
export function timestampToMillis(value: string): number | null {
  const match = TIMESTAMP.exec(value)
  if (!match) return null

  const [year, month, day, hour, minute, second] = match
    .slice(1)
    .map((part) => Number(part))
  if (
    year === undefined ||
    month === undefined ||
    day === undefined ||
    hour === undefined ||
    minute === undefined ||
    second === undefined
  ) {
    return null
  }

  const millis = Date.UTC(year, month - 1, day, hour, minute, second)
  // strptime lehnt unmoegliche Daten ab (z. B. 31.02.); Date.UTC rollt
  // sie still weiter. Der Vergleich faengt genau diese Faelle ab.
  const check = new Date(millis)
  if (
    check.getUTCFullYear() !== year ||
    check.getUTCMonth() !== month - 1 ||
    check.getUTCDate() !== day ||
    check.getUTCHours() !== hour ||
    check.getUTCMinutes() !== minute ||
    check.getUTCSeconds() !== second
  ) {
    return null
  }
  return millis
}

/** Liest "<type>_<id>.log" und liefert [[ms, wert], ...]. */
export function readLogAsJson(
  dir: string,
  type: string,
  id: string | number,
): [number, number][] {
  const file = join(dir, `${type}_${id}.log`)
  if (!existsSync(file)) return []

  const result: [number, number][] = []
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    if (line === '') continue
    const fields = parseCsvLine(line)
    const millis = timestampToMillis(fields[0] ?? '')
    const value = Number.parseFloat(fields[1] ?? '')
    if (millis === null || !Number.isFinite(value)) continue
    result.push([millis, value])
  }
  return result
}

export function readActions(dir: string): [number, string][] {
  const file = join(dir, 'action.log')
  if (!existsSync(file)) return []

  const result: [number, string][] = []
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    if (line === '') continue
    const fields = parseCsvLine(line)
    const millis = timestampToMillis(fields[0] ?? '')
    if (millis === null) continue
    result.push([millis, fields[1] ?? ''])
  }
  return result
}

/** Controller-Typ aus dem Cache, wie cbpi.get_controller(). */
export function controllerFor(api: Api, key: string, name: unknown): Row | null {
  const types = api.cache.get<Record<string, Row>>(key) ?? {}
  return types[String(name)] ?? null
}

function cachedRow(
  api: Api,
  key: string,
  id: string,
): Row | null {
  const entries = api.cache.get<Record<string, Row>>(key) ?? {}
  return entries[id] ?? entries[String(Number(id))] ?? null
}

function notFound(message: string): HttpError {
  return new HttpError(404, message)
}

function chartData(
  dir: string,
  entry: Row,
): { name: unknown; data: [number, number][] } {
  return {
    name: entry.name,
    data: readLogAsJson(dir, String(entry.data_type), String(entry.data_id)),
  }
}

export function registerLogModule(
  router: Router,
  api: Api,
  dir: string,
): void {
  router
    .add('GET', '/api/logs/', 'LogView:get_all_logfiles', () => {
      if (!existsSync(dir)) return json([])
      return json(
        readdirSync(dir).filter((name) => name.endsWith('.log')),
      )
    })
    .add('GET', '/api/logs/actions', 'LogView:actions', () =>
      json(readActions(dir)),
    )
    .add('GET', '/api/logs/check_filename/<name>', 'LogView:check_filename', (ctx) =>
      json(isLogName(ctx.params.name ?? '')),
    )
    .add('GET', '/api/logs/read_log_as_json/<type>/<id>', 'LogView:read_log_as_json', (ctx) =>
      json(
        readLogAsJson(dir, ctx.params.type ?? '', ctx.params.id ?? ''),
      ),
    )
    .add(
      'GET',
      '/api/logs/convert_chart_data_to_json/<chart_data>',
      'LogView:convert_chart_data_to_json',
      (ctx) => {
        // Im Original wird der Pfadparameter wie ein dict benutzt und
        // scheitert immer mit TypeError (500). Das ist kein sinnvoller
        // Endpunkt; hier wird daraus ein klarer Client-Fehler (D-11).
        throw new HttpError(
          400,
          `chart_data must be an object, got ${ctx.params.chart_data ?? ''}`,
        )
      },
    )
    .add('GET', '/api/logs/download/<file>', 'LogView:download', (ctx) => {
      const name = ctx.params.file ?? ''
      if (!isLogName(name)) return error('File Not Found', 404)

      const file = join(dir, name)
      if (!existsSync(file)) return error('File Not Found', 404)

      const data = readFileSync(file)
      return new HttpResponse(200, data, {
        'Content-Type': 'application/octet-stream',
        'Content-Disposition': `attachment; filename=${name}`,
        'Content-Length': String(data.length),
        'Cache-Control':
          'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0',
        Pragma: 'no-cache',
        Expires: '-1',
        'Last-Modified': new Date().toUTCString(),
      })
    })
    .add('DELETE', '/api/logs/<file>', 'LogView:clearlog', (ctx) => {
      const name = ctx.params.file ?? ''
      if (!isLogName(name)) return error('File Not Found', 404)

      const file = join(dir, name)
      if (existsSync(file)) {
        unlinkSync(file)
        api.notify('Log deleted successfully', '')
      } else {
        api.notify('Failed to delete log', '', 'danger')
      }
      return new HttpResponse(204, '')
    })
    .add('POST', '/api/logs/<t>/<int:id>', 'LogView:get_logs_as_json', (ctx) => {
      const type = ctx.params.t ?? ''
      const id = ctx.params.id ?? ''

      if (type === 's') {
        const sensor = cachedRow(api, 'sensors', id)
        if (!sensor) throw notFound(`Sensor ${id} not found`)
        return json([
          { name: sensor.name, data: readLogAsJson(dir, 'sensor', id) },
        ])
      }

      if (type === 'k') {
        const kettle = cachedRow(api, 'kettle', id)
        if (!kettle) throw notFound(`Kettle ${id} not found`)
        const controller = controllerFor(api, 'controller_types', kettle.logic)
        if (!controller) throw notFound(`No controller for kettle ${id}`)
        const chart = (controller.class as { chart?: (entry: Row) => Row[] })
          ?.chart
        if (typeof chart !== 'function') {
          throw new HttpError(
            500,
            `Controller ${String(kettle.logic)} cannot chart yet (M5)`,
          )
        }
        return json(chart(kettle).map((entry) => chartData(dir, entry)))
      }

      if (type === 'f') {
        const fermenter = cachedRow(api, 'fermenter', id)
        if (!fermenter) throw notFound(`Fermenter ${id} not found`)
        const controller = controllerFor(
          api,
          'fermentation_controller_types',
          fermenter.logic,
        )
        if (!controller) {
          throw notFound(`No controller for fermenter ${id}`)
        }
        const chart = (controller.class as { chart?: (entry: Row) => Row[] })
          ?.chart
        if (typeof chart !== 'function') {
          throw new HttpError(
            500,
            `Controller ${String(fermenter.logic)} cannot chart yet (M5)`,
          )
        }
        return json(chart(fermenter).map((entry) => chartData(dir, entry)))
      }

      return json([])
    })
}
