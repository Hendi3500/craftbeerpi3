/**
 * Statische Dateien fuer /ui und /static.
 *
 * Die Python-Seite liefert /ui/ aus modules/ui/static (das alte Bundle)
 * und /static/ aus modules/static. Beide Pfade stehen in der
 * Route-Baseline und muessen erhalten bleiben, auch wenn die neue
 * Oberflaeche separat laeuft.
 */
import { existsSync, readFileSync, statSync } from 'node:fs'
import { extname, resolve, sep } from 'node:path'
import { HttpResponse, text } from './respond.ts'

const TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.map': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.txt': 'text/plain; charset=utf-8',
}

export function serveFile(baseDir: string, relativePath: string): HttpResponse {
  const base = resolve(baseDir)
  const target = resolve(base, relativePath.replace(/^\/+/, ''))

  // Pfadausbruch verhindern. resolve() normalisiert "..", deshalb reicht
  // der Prefix-Vergleich.
  if (target !== base && !target.startsWith(base + sep)) {
    return text('Not Found', 404)
  }

  if (!existsSync(target) || !statSync(target).isFile()) {
    return text('Not Found', 404)
  }

  const type = TYPES[extname(target).toLowerCase()] ?? 'application/octet-stream'
  return new HttpResponse(200, readFileSync(target), { 'Content-Type': type })
}
