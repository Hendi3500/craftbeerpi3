/**
 * cbpi.cache - prozessweiter Zustand.
 *
 * Im Python-Backend ein Klassen-Dict, hier eine Map mit denselben
 * Schluesseln. Wichtig: /api/system/dump gibt den kompletten Inhalt aus,
 * deshalb ist die Schluesselmenge Teil des Vertrags (siehe CACHE_SEED in
 * src/index.ts).
 */
export type CacheShape = Record<string, unknown>

export class Cache {
  private readonly store = new Map<string, unknown>()

  constructor(seed: CacheShape = {}) {
    for (const [key, value] of Object.entries(seed)) {
      this.store.set(key, value)
    }
  }

  get<T = unknown>(key: string): T | undefined {
    return this.store.get(key) as T | undefined
  }

  /** Wie get(), legt aber bei fehlendem Schluessel den Vorgabewert an. */
  getOr<T>(key: string, create: () => T): T {
    const existing = this.store.get(key)
    if (existing !== undefined) return existing as T
    const created = create()
    this.store.set(key, created)
    return created
  }

  set<T>(key: string, value: T): T {
    this.store.set(key, value)
    return value
  }

  has(key: string): boolean {
    return this.store.has(key)
  }

  delete(key: string): boolean {
    return this.store.delete(key)
  }

  snapshot(): CacheShape {
    return Object.fromEntries(this.store)
  }
}
