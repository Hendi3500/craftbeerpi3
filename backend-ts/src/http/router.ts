/**
 * Flask-kompatibler Router.
 *
 * Warum kein Fastify/Express: die Routen des Projekts folgen
 * flask_classy, nicht REST. Entscheidend sind vier Eigenschaften, die
 * ein Standard-Router anders macht:
 *
 *   1. Trailing Slash: /api/step/ und /api/step sind verschieden. Eine
 *      Regel mit Slash leitet die Variante ohne Slash per 308 um,
 *      umgekehrt wird nicht umgeleitet.
 *   2. Konverter: <int:id> matcht \d+, nicht "irgendein Segment".
 *   3. Statische Regeln gewinnen gegen dynamische
 *      (/api/logs/actions vor /api/logs/<file>).
 *   4. Methoden werden pro Regel geprueft, nicht pro Pfad.
 *
 * Die Regelstrings werden woertlich aus tools/routes_baseline.json
 * uebernommen.
 */
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Logger } from '../logger.ts'
import { HttpResponse, json, noContent, redirect, text } from './respond.ts'

export type Method =
  | 'GET'
  | 'POST'
  | 'PUT'
  | 'DELETE'
  | 'PATCH'
  | 'HEAD'
  | 'OPTIONS'

export interface RequestContext {
  req: IncomingMessage
  res: ServerResponse
  method: string
  path: string
  query: URLSearchParams
  params: Record<string, string>
  /** Rohbody (fuer /api/editor/<name> POST). */
  body: () => Promise<Buffer>
  /** Geparster JSON-Body; wirft HttpError(400) bei ungueltigem JSON. */
  json: <T = unknown>() => Promise<T>
}

export type HandlerResult = HttpResponse | unknown
export type Handler = (
  ctx: RequestContext,
) => HandlerResult | Promise<HandlerResult>

export interface RouteSpec {
  method: Method
  rule: string
  endpoint: string
  handler: Handler
}

export class HttpError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'HttpError'
    this.status = status
  }
}

export type Match =
  | { kind: 'route'; spec: RouteSpec; params: Record<string, string> }
  | { kind: 'redirect'; location: string }
  | { kind: 'not-allowed'; allow: string[] }
  | { kind: 'options'; allow: string[] }
  | { kind: 'not-found' }

interface Compiled {
  spec: RouteSpec
  regex: RegExp
  keys: string[]
  dynamic: number
}

const CONVERTER = /^<(?:(int|float|path|string):)?([A-Za-z_][A-Za-z0-9_]*)>$/

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function compile(spec: RouteSpec): Compiled {
  if (!spec.rule.startsWith('/')) {
    throw new Error(`Route must start with "/": ${spec.rule}`)
  }

  const segments = spec.rule.split('/')
  const keys: string[] = []
  let pattern = '^'

  segments.forEach((segment, index) => {
    if (index === 0) return
    pattern += '/'
    if (segment === '') return

    const match = CONVERTER.exec(segment)
    if (!match) {
      pattern += escapeRegex(segment)
      return
    }

    const type = match[1] ?? 'string'
    keys.push(match[2] as string)
    if (type === 'int') pattern += '(\\d+)'
    else if (type === 'float') pattern += '(\\d+\\.\\d+)'
    else if (type === 'path') pattern += '([^/].*)'
    else pattern += '([^/]+)'
  })

  pattern += '$'
  return { spec, regex: new RegExp(pattern), keys, dynamic: keys.length }
}

export class Router {
  private readonly routes: Compiled[] = []
  private readonly logger: Logger

  constructor(logger: Logger) {
    this.logger = logger
  }

  add(
    method: Method,
    rule: string,
    endpoint: string,
    handler: Handler,
  ): this {
    const spec: RouteSpec = { method, rule, endpoint, handler }
    const compiled = compile(spec)

    if (
      this.routes.some(
        (route) =>
          route.spec.method === method && route.spec.rule === rule,
      )
    ) {
      throw new Error(`Duplicate route: ${method} ${rule}`)
    }

    this.routes.push(compiled)
    // Statische Regeln zuerst, dann laengere Regeln. Das entspricht der
    // Gewichtung von Werkzeug und loest /api/logs/actions gegen
    // /api/logs/<file>.
    this.routes.sort((a, b) => {
      if (a.dynamic !== b.dynamic) return a.dynamic - b.dynamic
      if (a.spec.rule.length !== b.spec.rule.length) {
        return b.spec.rule.length - a.spec.rule.length
      }
      return a.spec.rule.localeCompare(b.spec.rule)
    })

    return this
  }

  get size(): number {
    return this.routes.length
  }

  rules(): { rule: string; methods: Method[] }[] {
    const map = new Map<string, Set<Method>>()
    for (const route of this.routes) {
      const set = map.get(route.spec.rule) ?? new Set<Method>()
      set.add(route.spec.method)
      map.set(route.spec.rule, set)
    }
    return [...map.entries()].map(([rule, methods]) => ({
      rule,
      methods: [...methods].sort(),
    }))
  }

  /** Registrierte Routen mit Endpunktnamen - fuer den Baseline-Abgleich. */
  specs(): RouteSpec[] {
    return this.routes.map((route) => route.spec)
  }

  resolve(method: string, path: string): Match {
    const wanted = method.toUpperCase()
    const pathMatches: Compiled[] = []

    for (const route of this.routes) {
      const result = route.regex.exec(path)
      if (!result) continue
      pathMatches.push(route)

      const sameMethod = route.spec.method === wanted
      const headForGet = wanted === 'HEAD' && route.spec.method === 'GET'
      if (!sameMethod && !headForGet) continue

      const params: Record<string, string> = {}
      route.keys.forEach((key, index) => {
        const raw = result[index + 1] ?? ''
        try {
          params[key] = decodeURIComponent(raw)
        } catch {
          params[key] = raw
        }
      })
      return { kind: 'route', spec: route.spec, params }
    }

    if (pathMatches.length > 0) {
      const allow = [
        ...new Set(pathMatches.flatMap((route) => route.spec.method)),
      ]
      if (allow.includes('GET')) allow.push('HEAD')
      allow.push('OPTIONS')
      if (wanted === 'OPTIONS') {
        return { kind: 'options', allow: [...new Set(allow)].sort() }
      }
      return { kind: 'not-allowed', allow: [...new Set(allow)].sort() }
    }

    // Nur in eine Richtung: Regel mit Slash, Anfrage ohne Slash.
    if (path !== '/' && !path.endsWith('/')) {
      const candidate = path + '/'
      if (
        this.routes.some(
          (route) =>
            route.spec.rule.endsWith('/') && route.regex.test(candidate),
        )
      ) {
        return { kind: 'redirect', location: candidate }
      }
    }

    return { kind: 'not-found' }
  }

  async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    let url: URL
    try {
      url = new URL(req.url ?? '/', 'http://localhost')
    } catch {
      this.send(res, text('Bad Request', 400))
      return
    }

    const method = (req.method ?? 'GET').toUpperCase()
    const match = this.resolve(method, url.pathname)

    try {
      if (match.kind === 'not-found') {
        this.send(res, text('Not Found', 404))
        return
      }

      if (match.kind === 'redirect') {
        this.send(res, redirect(match.location + url.search, 308))
        return
      }

      if (match.kind === 'not-allowed' || match.kind === 'options') {
        if (match.kind === 'options') {
          this.send(
            res,
            new HttpResponse(200, '', { Allow: match.allow.join(', ') }),
          )
        } else {
          this.send(
            res,
            new HttpResponse(405, 'Method Not Allowed', {
              Allow: match.allow.join(', '),
            }),
          )
        }
        return
      }

      const ctx = this.createContext(req, res, method, url, match.params)
      const result = await match.spec.handler(ctx)
      const response =
        result instanceof HttpResponse
          ? result
          : result === undefined
            ? noContent()
            : json(result)

      if (method === 'HEAD') {
        this.send(
          res,
          new HttpResponse(response.status, '', response.headers),
        )
        return
      }

      this.send(res, response)
    } catch (error) {
      if (error instanceof HttpError) {
        this.send(res, text(error.message, error.status))
        return
      }
      const message = error instanceof Error ? error.message : String(error)
      this.logger.error(
        `Unhandled error for ${method} ${url.pathname}: ${message}`,
      )
      this.send(res, text('Internal Server Error', 500))
    }
  }

  private createContext(
    req: IncomingMessage,
    res: ServerResponse,
    method: string,
    url: URL,
    params: Record<string, string>,
  ): RequestContext {
    let bodyPromise: Promise<Buffer> | null = null
    let jsonPromise: Promise<unknown> | null = null

    const readBody = (): Promise<Buffer> => {
      bodyPromise ??= new Promise<Buffer>((resolve, reject) => {
        const chunks: Buffer[] = []
        req.on('data', (chunk: Buffer) => chunks.push(chunk))
        req.on('end', () => resolve(Buffer.concat(chunks)))
        req.on('error', reject)
      })
      return bodyPromise
    }

    return {
      req,
      res,
      method,
      path: url.pathname,
      query: url.searchParams,
      params,
      body: readBody,
      json: <T>() => {
        jsonPromise ??= readBody().then((raw) => {
          if (raw.length === 0) {
            throw new HttpError(400, 'Bad Request: empty JSON body')
          }
          try {
            return JSON.parse(raw.toString('utf8')) as unknown
          } catch {
            throw new HttpError(400, 'Bad Request: invalid JSON')
          }
        })
        return jsonPromise as Promise<T>
      },
    }
  }

  private send(res: ServerResponse, response: HttpResponse): void {
    res.statusCode = response.status
    for (const [name, value] of Object.entries(response.headers)) {
      res.setHeader(name, value)
    }
    if (response.status === 204 || response.status === 304) {
      res.end()
      return
    }
    res.end(response.body)
  }
}
