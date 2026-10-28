/**
 * Eventbus - Gegenstueck zu cbpi.event() / cbpi.emit_event().
 *
 * Im Python-Backend werden Handler mit Namen registriert und mit
 * Keyword-Argumenten aufgerufen. Hier bekommt jeder Handler ein
 * Payload-Objekt; das ist der einzige Unterschied und bleibt lokal.
 */
export type Listener = (payload: unknown) => void

export class EventBus {
  private readonly listeners = new Map<string, Listener[]>()

  on(name: string, listener: Listener): () => void {
    const list = this.listeners.get(name) ?? []
    list.push(listener)
    this.listeners.set(name, list)
    return () => {
      const current = this.listeners.get(name)
      if (!current) return
      const index = current.indexOf(listener)
      if (index >= 0) current.splice(index, 1)
    }
  }

  emit(name: string, payload?: unknown): void {
    const list = this.listeners.get(name)
    if (!list) return
    // Kopie: ein Handler darf sich waehrend der Zustellung abmelden.
    for (const listener of [...list]) {
      listener(payload)
    }
  }

  names(): string[] {
    return [...this.listeners.keys()]
  }
}
