/**
 * /api/buzzer - Buzzer-Kontrolle für Benachrichtigungen.
 *
 * Gegenstueck zu modules/buzzer/__init__.py. Der Buzzer wird ueber GPIO
 * gesteuert. Ohne GPIO-Zugriff ist dies ein No-op.
 */
import { writeFileSync, existsSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import type { Api } from '../core/api.ts'

const SOUND = ['H', 0.1, 'L', 0.1, 'H', 0.1, 'L', 0.1, 'H', 0.1, 'L']

interface BuzzerConfig {
  gpio?: number
  beepLevel?: 'HIGH' | 'LOW'
}

/**
 * Buzzer-Klasse - gleiche Logik wie Python modules/buzzer/__init__.py
 */
export class Buzzer {
  private gpio: number | null = null
  private beepLevel: 'HIGH' | 'LOW'
  private active: boolean = false

  constructor(config: BuzzerConfig, api: Api) {
    this.beepLevel = config.beepLevel ?? 'HIGH'
    const gpioPin = config.gpio ?? 22

    try {
      // In Node.js kann man GPIO nicht einfach über /sys/class/gpio kontrollieren
      // oder über ein npm-Paket wie 'onoff'. Fuer Tests/Stubs:
      // - GPIO-Pin wird geschrieben nach /sys/class/gpio/export
      // - Wert wird geschrieben nach /sys/class/gpio/gpio{num}/value
      this.gpio = gpioPin
      this.active = this.initGpio(gpioPin, api)
      api.log('info', `Buzzer initialized on GPIO${gpioPin}`)
    } catch (error) {
      api.log('warning', `Buzzer initialization failed: ${String(error)}`)
      this.gpio = null
    }
  }

  private initGpio(gpioPin: number, api: Api): boolean {
    try {
      // Export GPIO
      writeFileSync('/sys/class/gpio/export', String(gpioPin))
      // Set direction to out
      mkdirSync(join('/sys/class/gpio', `gpio${gpioPin}`), { recursive: true })
      writeFileSync(join('/sys/class/gpio', `gpio${gpioPin}`, 'direction'), 'out')
      return true
    } catch (error) {
      api.log('warning', `GPIO ${gpioPin} not accessible: ${String(error)}`)
      return false
    }
  }

  private writeGpio(value: number | string): void {
    if (this.gpio === null) return
    try {
      writeFileSync(join('/sys/class/gpio', `gpio${this.gpio}`, 'value'), String(value))
    } catch {
      // GPIO nicht verfuegbar
    }
  }

  /**
   * Spiele einen kurzen Klickton ab.
   * Echo to Python: Buzzer.beep()
   */
  async beep(): Promise<void> {
    if (!this.active) {
      // Buzzer nicht initialisiert - nichts zu tun
      return
    }

    const play = async (sound: (string | number)[]): Promise<void> => {
      for (const item of sound) {
        if (typeof item === 'string') {
          if (item === 'H' && this.beepLevel === 'HIGH') {
            this.writeGpio(1)
          } else if (item === 'H' && this.beepLevel !== 'HIGH') {
            this.writeGpio(0)
          } else if (item === 'L' && this.beepLevel === 'HIGH') {
            this.writeGpio(0)
          } else {
            this.writeGpio(1)
          }
          // Kurze Verzoegerung fuer HIGH/LOW-Trennung
          await new Promise((resolve) => setTimeout(resolve, 10))
        } else {
          // number = delay in seconds
          await new Promise((resolve) => setTimeout(resolve, item * 1000))
        }
      }
    }

    // Async Thread in Python - hier einfach async ausfuehren
    void play(SOUND)
  }

  /**
   * Stoppt den Buzzer (setzt Pin auf Low).
   */
  async stop(): Promise<void> {
    if (this.gpio !== null && this.active) {
      this.writeGpio(0)
      this.active = false
    }
  }
}

/** Buzzer-Instanz (wird von initPlugins gesetzt) */
let buzzer: Buzzer | null = null

/**
 * Initialisiert den Buzzer. Wird vom App-Boot augerufen.
 * Echo to Python: modules/buzzer/__init__.py init()
 */
export function initBuzzer(api: Api): void {
  const gpio = api.getConfigParameter('buzzer', 22)
  const beepLevel = api.getConfigParameter('buzzer_beep_level', 'HIGH')

  buzzer = new Buzzer({ gpio, beepLevel }, api)

  // Erster Beep beim Start (wie Python: cbpi.beep())
  void buzzer.beep()

  api.notify('Buzzer', `Buzzer initialized, GPIO${gpio}`)
}

/**
 * Liefert die globale Buzzer-Instanz.
 */
export function getBuzzer(): Buzzer | null {
  return buzzer
}