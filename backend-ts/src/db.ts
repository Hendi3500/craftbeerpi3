/**
 * SQLite-Zugriff und der DBModel-Ersatz.
 *
 * Bewusst nah an modules/core/db.py: eine Verbindung, synchron, rohe
 * Queries, JSON-Felder als Text. Das haelt die bestehende
 * craftbeerpi.db kompatibel und macht Migrationen nachvollziehbar.
 *
 * Abweichung D-2: update() schreibt nur die uebergebenen Spalten. Das
 * Python-Original schrieb alle Felder und setzte nicht uebergebene auf
 * NULL (BUGS.md B-08). BaseView.put() uebergibt ohnehin das vollstaendige
 * Objekt, das Verhalten der Endpunkte bleibt also gleich.
 */
import Database from 'better-sqlite3'
import { existsSync, mkdirSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'

export type Row = Record<string, unknown>

export interface TableMeta {
  /** Tabellenname in der Datenbank. */
  name: string
  /** Spalten ohne Primaerschluessel. */
  fields: string[]
  /** Default "id". */
  primaryKey?: string
  /** Spalten, die JSON als Text enthalten. */
  jsonFields?: string[]
  /** Spalte fuer ORDER BY. */
  orderBy?: string
  /** true: get_all() liefert eine Liste statt einer Map. */
  asArray?: boolean
}

interface ResolvedMeta extends Required<Omit<TableMeta, 'orderBy'>> {
  orderBy?: string
}

export class Db {
  readonly conn: Database.Database

  constructor(file: string) {
    mkdirSync(dirname(file), { recursive: true })
    this.conn = new Database(file)
  }

  close(): void {
    this.conn.close()
  }

  /** config/schema.sql ausfuehren. Idempotent (CREATE IF NOT EXISTS). */
  initSchema(root: string): void {
    const file = join(root, 'config', 'schema.sql')
    if (!existsSync(file)) return
    this.conn.exec(readFileSync(file, 'utf8'))
  }

  /**
   * update/*.sql der Reihe nach anwenden, Version in schema_info.
   *
   * Anders als das Python-Original wird ein Fehler nicht verschluckt
   * (BUGS.md B-04): eine halb angewendete Migration ist schlimmer als
   * ein Start, der laut scheitert.
   */
  migrate(root: string): { applied: number[]; current: number | null } {
    const dir = join(root, 'update')
    if (!existsSync(dir)) return { applied: [], current: null }

    let current: number | null = null
    try {
      const row = this.conn
        .prepare('SELECT max(version) AS m FROM schema_info')
        .get() as { m: number | null } | undefined
      current = row?.m ?? null
    } catch {
      current = null
    }

    const files = readdirSync(dir)
      .filter((name) => name.endsWith('.sql'))
      .map((name) => {
        const index = name.indexOf('_')
        const version = index > 0 ? Number(name.slice(0, index)) : Number.NaN
        return { name, version }
      })
      .filter((entry) => Number.isInteger(entry.version))
      .sort((a, b) => a.version - b.version || a.name.localeCompare(b.name))

    const applied: number[] = []
    for (const entry of files) {
      if (current !== null && current >= entry.version) continue
      const sql = readFileSync(join(dir, entry.name), 'utf8')
      const apply = this.conn.transaction(() => {
        this.conn.exec(sql)
        this.conn
          .prepare('INSERT INTO schema_info (version, filename) VALUES (?, ?)')
          .run(entry.version, entry.name)
      })
      apply()
      current = entry.version
      applied.push(entry.version)
    }

    return { applied, current }
  }
}

export class Table {
  private readonly db: Db
  private readonly meta: ResolvedMeta

  constructor(db: Db, meta: TableMeta) {
    this.db = db
    this.meta = {
      name: meta.name,
      fields: meta.fields,
      primaryKey: meta.primaryKey ?? 'id',
      jsonFields: meta.jsonFields ?? [],
      asArray: meta.asArray ?? false,
      orderBy: meta.orderBy,
    }
  }

  private get jsonFields(): string[] {
    return this.meta.jsonFields
  }

  get primaryKey(): string {
    return this.meta.primaryKey
  }

  get name(): string {
    return this.meta.name
  }

  get isArray(): boolean {
    return this.meta.asArray
  }

  private quote(identifier: string): string {
    return '"' + identifier.replace(/"/g, '""') + '"'
  }

  private hydrate(row: Row): Row {
    // Wie DBModel.__init__: nur Primaerschluessel und deklarierte Felder
    // uebernehmen. Spalten, die in der Tabelle stehen, aber nicht im
    // Modell (z. B. kettle.height), wuerden sonst im JSON auftauchen und
    // die Antwort gegenueber Python veraendern.
    const result: Row = {}
    const primary = this.meta.primaryKey
    if (primary in row) result[primary] = row[primary]

    for (const field of this.meta.fields) {
      const value = row[field]
      if (value === undefined) {
        result[field] = null
      } else if (this.jsonFields.includes(field) && typeof value === 'string') {
        try {
          result[field] = JSON.parse(value)
        } catch {
          // Ungueltiges JSON bleibt als Text stehen - wie bisher.
          result[field] = value
        }
      } else {
        result[field] = value
      }
    }

    return result
  }

  private encode(field: string, value: unknown): unknown {
    if (value === undefined || value === null) return null
    if (this.jsonFields.includes(field)) {
      return typeof value === 'string' ? value : JSON.stringify(value)
    }
    return value
  }

  all(): Row[] | Record<string, Row> {
    const order = this.meta.orderBy
      ? ` ORDER BY ${this.quote(this.meta.orderBy)}`
      : ''
    const sql = `SELECT * FROM ${this.quote(this.meta.name)}${order}`
    const rows = (this.db.conn.prepare(sql).all() as Row[]).map((row) =>
      this.hydrate(row),
    )

    if (this.meta.asArray) return rows

    const result: Record<string, Row> = {}
    for (const row of rows) result[String(row[this.meta.primaryKey])] = row
    return result
  }

  one(id: string | number): Row | null {
    const sql = `SELECT * FROM ${this.quote(this.meta.name)} WHERE ${this.quote(
      this.meta.primaryKey,
    )} = ?`
    const row = this.db.conn.prepare(sql).get(id) as Row | undefined
    return row ? this.hydrate(row) : null
  }

  insert(data: Row): Row {
    const columns: string[] = []
    const values: unknown[] = []

    const primary = data[this.meta.primaryKey]
    if (primary !== undefined && primary !== null) {
      columns.push(this.meta.primaryKey)
      values.push(primary)
    }

    for (const field of this.meta.fields) {
      columns.push(field)
      values.push(this.encode(field, data[field]))
    }

    const sql =
      `INSERT INTO ${this.quote(this.meta.name)} ` +
      `(${columns.map((column) => this.quote(column)).join(', ')}) ` +
      `VALUES (${columns.map(() => '?').join(', ')})`

    const info = this.db.conn.prepare(sql).run(...values)
    const id = primary ?? info.lastInsertRowid
    const inserted = this.one(id as string | number)
    if (!inserted) {
      throw new Error(`Insert into ${this.meta.name} returned no row`)
    }
    return inserted
  }

  update(data: Row): Row {
    const id = data[this.meta.primaryKey]
    if (id === undefined || id === null) {
      throw new Error(
        `update() on ${this.meta.name} without primary key ${this.meta.primaryKey}`,
      )
    }

    const columns = this.meta.fields.filter((field) =>
      Object.hasOwn(data, field),
    )
    if (columns.length === 0) {
      const row = this.one(id as string | number)
      if (!row) throw new Error(`Row ${String(id)} not found in ${this.meta.name}`)
      return row
    }

    const sql =
      `UPDATE ${this.quote(this.meta.name)} SET ` +
      columns.map((column) => `${this.quote(column)} = ?`).join(', ') +
      ` WHERE ${this.quote(this.meta.primaryKey)} = ?`

    this.db.conn
      .prepare(sql)
      .run(...columns.map((column) => this.encode(column, data[column])), id)

    const updated = this.one(id as string | number)
    if (!updated) throw new Error(`Row ${String(id)} not found in ${this.meta.name}`)
    return updated
  }

  delete(id: string | number): void {
    const sql = `DELETE FROM ${this.quote(this.meta.name)} WHERE ${this.quote(
      this.meta.primaryKey,
    )} = ?`
    this.db.conn.prepare(sql).run(id)
  }
}
