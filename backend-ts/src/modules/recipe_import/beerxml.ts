/**
 * /api/beerxml - BeerXML Rezept-Import.
 *
 * Gegenstueck zu modules/recipe_import/beerxml.py. Stubs fuer den
 * Moment - die volle XML-Parsing-Logik braucht Node-Abhaengigkeiten
 * (xml2js, fast-xml-parser) und Datei-Upload-Handling (multer).
 * Die Endpunkte sind registriert, damit die Baseline vollstaendig ist.
 */
import type { Api } from '../../core/api.ts'
import type { Router } from '../../http/router.ts'
import { json, noContent } from '../../http/respond.ts'

export function registerBeerXmlRoutes(router: Router, api: Api): void {
  // GET /api/beerxml/ - Liste der Rezepte im hochgeladenen BeerXML
  router.add('GET', '/api/beerxml/', 'BeerXMLImport:get', () => {
    api.log('info', 'GET /api/beerxml/ - BeerXML list requested (stub)')
    return json([])
  })

  // POST /api/beerxml/upload - Datei hochladen
  router.add('POST', '/api/beerxml/upload', 'BeerXMLImport:upload_file', async () => {
    api.log('info', 'POST /api/beerxml/upload - BeerXML upload requested (stub)')
    api.notify('Upload Successful', 'The Beer XML file was uploaded successfully')
    return noContent()
  })

  // GET /api/beerxml/allowed_file/<filename> - Datei erlaubt?
  router.add('GET', '/api/beerxml/allowed_file/<filename>', 'BeerXMLImport:allowed_file', (ctx) => {
    const filename = ctx.params.filename ?? ''
    const allowed = filename.endsWith('.xml')
    return json(allowed)
  })

  // POST /api/beerxml/<int:id> - Rezept laden
  router.add('POST', '/api/beerxml/<int:id>', 'BeerXMLImport:load', async (ctx) => {
    const id = Number(ctx.params.id)
    api.log('info', `POST /api/beerxml/${id} - BeerXML load requested (stub)`)
    api.notify('Recipe loaded successfully', '')
    return noContent()
  })

  // GET /api/beerxml/getRecipeName/<id>
  router.add('GET', '/api/beerxml/getRecipeName/<id>', 'BeerXMLImport:getRecipeName', (ctx) => {
    const id = ctx.params.id ?? ''
    api.log('info', `GET /api/beerxml/getRecipeName/${id} (stub)`)
    return json({ name: `Recipe ${id}` })
  })

  // GET /api/beerxml/getBoilTime/<id>
  router.add('GET', '/api/beerxml/getBoilTime/<id>', 'BeerXMLImport:getBoilTime', (ctx) => {
    const id = ctx.params.id ?? ''
    api.log('info', `GET /api/beerxml/getBoilTime/${id} (stub)`)
    return json({ boil_time: 60 })
  })

  // GET /api/beerxml/getBoilAlerts/<id>
  router.add('GET', '/api/beerxml/getBoilAlerts/<id>', 'BeerXMLImport:getBoilAlerts', (ctx) => {
    const id = ctx.params.id ?? ''
    api.log('info', `GET /api/beerxml/getBoilAlerts/${id} (stub)`)
    return json({ alerts: [15, 30, 45] })
  })

  // GET /api/beerxml/getSteps/<id>
  router.add('GET', '/api/beerxml/getSteps/<id>', 'BeerXMLImport:getSteps', (ctx) => {
    const id = ctx.params.id ?? ''
    api.log('info', `GET /api/beerxml/getSteps/${id} (stub)`)
    return json([
      { name: 'Mash', temp: 65, timer: 60 },
      { name: 'Boil', temp: 100, timer: 60 },
    ])
  })
}