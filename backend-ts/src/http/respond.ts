/**
 * Antworttypen. Die Handler geben entweder eine HttpResponse zurueck
 * oder einen Wert, der als JSON serialisiert wird.
 */
import { stringify } from '../json.ts'

export class HttpResponse {
  readonly status: number
  readonly body: string | Buffer
  readonly headers: Record<string, string>

  constructor(
    status: number,
    body: string | Buffer = '',
    headers: Record<string, string> = {},
  ) {
    this.status = status
    this.body = body
    this.headers = headers
  }
}

export function noContent(): HttpResponse {
  return new HttpResponse(204, '')
}

export function text(value: string, status = 200): HttpResponse {
  return new HttpResponse(status, value, {
    'Content-Type': 'text/html; charset=utf-8',
  })
}

/** JSON-Antwort. Abweichung D-1: application/json statt text/html. */
export function json(value: unknown, status = 200): HttpResponse {
  return new HttpResponse(status, stringify(value), {
    'Content-Type': 'application/json',
  })
}

export function error(message: string, status: number): HttpResponse {
  return text(message, status)
}

export function redirect(location: string, status = 302): HttpResponse {
  return new HttpResponse(status, '', { Location: location })
}
