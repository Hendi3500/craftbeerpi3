/**
 * Kanonisches JSON, wie es das Python-Backend erzeugt.
 *
 * Flask 3 serialisiert mit DefaultJSONProvider und dessen Vorgaben
 * sort_keys=True und ensure_ascii=True. Zusaetzlich benutzt Python
 * json.dumps die Standard-Separatoren ", " und ": " - also mit
 * Leerzeichen. Das ist fuer den Fixture-Vergleich entscheidend: zwei
 * inhaltlich gleiche Antworten sind sonst nicht byte-gleich.
 *
 * Der Encoder bildet ausserdem den ComplexJSONProvider nach
 * (modules/app_config.py):
 *
 *   CacheCallback  -> ausfuehren (add_cache_callback)
 *   Map            -> Objekt (unser Cache ist eine Map)
 *   Klasse/Funktion-> { name, module }
 *   __json__/toJSON -> Ergebnis
 *   unbekannter Typ-> null (wie ComplexEncoder aus Flask 0.12)
 *
 * Der letzte Punkt ist kein Versehen: im Cache liegen zur Laufzeit
 * Controller- und Schritt-Instanzen. Ohne den null-Zweig waeren
 * /api/kettle/ und /api/system/dump 500er.
 */
export class CacheCallback {
  private readonly callback: () => unknown

  constructor(callback: () => unknown) {
    this.callback = callback
  }

  call(): unknown {
    return this.callback()
  }
}

export interface JsonDiagnostics {
  unknown?: (typeName: string) => void
}

let diagnostics: JsonDiagnostics = {}

export function setJsonDiagnostics(next: JsonDiagnostics): void {
  diagnostics = next
}

const UNSAFE = /[\u0080-\uffff]/g

function quote(value: string): string {
  return JSON.stringify(value).replace(UNSAFE, (char) => {
    return '\\u' + char.charCodeAt(0).toString(16).padStart(4, '0')
  })
}

function isPlainObject(value: object): boolean {
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function encode(value: unknown, seen: WeakSet<object>): string {
  if (value === null || value === undefined) return 'null'

  switch (typeof value) {
    case 'number':
      return Number.isFinite(value) ? JSON.stringify(value) : 'null'
    case 'bigint':
      // Python-Integer sind beliebig gross; roh ausgeben statt zu runden.
      return value.toString()
    case 'boolean':
      return value ? 'true' : 'false'
    case 'string':
      return quote(value)
    case 'function':
      return encode(
        {
          name: value.name,
          module: (value as { __module__?: unknown }).__module__ ?? null,
        },
        seen,
      )
    case 'object':
      break
    default:
      return 'null'
  }

  const object = value as object
  if (seen.has(object)) return 'null'
  seen.add(object)

  try {
    if (object instanceof CacheCallback) {
      return encode(object.call(), seen)
    }

    if (object instanceof Map) {
      const mapped: Record<string, unknown> = {}
      for (const [key, entry] of object) mapped[String(key)] = entry
      return encode(mapped, seen)
    }

    if (Array.isArray(object)) {
      return '[' + object.map((entry) => encode(entry, seen)).join(', ') + ']'
    }

    if (isPlainObject(object)) {
      const source = object as Record<string, unknown>
      return (
        '{' +
        Object.keys(source)
          .sort()
          .map((key) => quote(key) + ': ' + encode(source[key], seen))
          .join(', ') +
        '}'
      )
    }

    const custom = object as {
      __json__?: () => unknown
      toJSON?: () => unknown
      constructor?: { name?: string }
    }
    if (typeof custom.__json__ === 'function') {
      return encode(custom.__json__(), seen)
    }
    if (typeof custom.toJSON === 'function') {
      return encode(custom.toJSON(), seen)
    }

    diagnostics.unknown?.(custom.constructor?.name ?? 'Object')
    return 'null'
  } finally {
    seen.delete(object)
  }
}

/** Nur fuer Tests und Sonderfaelle; stringify() ist der Normalfall. */
export function canonicalize(value: unknown): unknown {
  if (value === undefined) return null
  if (value === null) return null
  if (Array.isArray(value)) return value.map(canonicalize)
  if (typeof value === 'object') {
    const source = value as Record<string, unknown>
    const result: Record<string, unknown> = {}
    for (const key of Object.keys(source).sort()) {
      result[key] = canonicalize(source[key])
    }
    return result
  }
  return value
}

export function stringify(value: unknown): string {
  return encode(value, new WeakSet<object>())
}
