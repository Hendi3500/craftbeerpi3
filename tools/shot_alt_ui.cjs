/*
 * Screenshot der alten Oberflaeche (modules/ui) - damit man sieht, ob
 * die Live-Werte (Temperaturen, Aktuatoren) ankommen.
 *
 * Aufruf:  node tools/shot_alt_ui.cjs [url] [ziel.png]
 */
const { spawn } = require("node:child_process")
const fs = require("node:fs")
const http = require("node:http")
const path = require("node:path")
const WebSocket = require(
  path.join(
    "/home/lope/cbpi3UIng/node_modules/.pnpm/ws@8.21.3/node_modules/ws"
  )
)

const URL = process.argv[2] || "http://127.0.0.1:5000/ui/"
const ZIEL = process.argv[3] || "/tmp/opencode/alt-ui.png"
const PORT = 9334
const warte = (ms) => new Promise((r) => setTimeout(r, ms))

function httpJson(pfad) {
  return new Promise((resolve, reject) => {
    http
      .get({ host: "127.0.0.1", port: PORT, path: pfad }, (res) => {
        let daten = ""
        res.on("data", (d) => (daten += d))
        res.on("end", () => {
          try {
            resolve(JSON.parse(daten))
          } catch (e) {
            reject(e)
          }
        })
      })
      .on("error", reject)
  })
}

async function main() {
  const chrome = spawn(
    "google-chrome",
    [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--disable-dev-shm-usage",
      "--window-size=1280,1000",
      `--remote-debugging-port=${PORT}`,
      "about:blank",
    ],
    { stdio: "ignore" }
  )

  try {
    let ziel = null
    for (let i = 0; i < 40 && !ziel; i++) {
      await warte(500)
      try {
        const liste = await httpJson("/json/list")
        ziel = liste.find((t) => t.type === "page")
      } catch (e) {
        /* noch nicht bereit */
      }
    }
    if (!ziel) throw new Error("Chrome antwortet nicht")

    const ws = new WebSocket(ziel.webSocketDebuggerUrl, {
      maxPayload: 64 * 1024 * 1024,
    })
    let id = 0
    const wartende = new Map()
    const send = (methode, params = {}) =>
      new Promise((resolve) => {
        const msgId = ++id
        wartende.set(msgId, resolve)
        ws.send(JSON.stringify({ id: msgId, method: methode, params }))
      })
    ws.on("message", (rohdaten) => {
      const n = JSON.parse(rohdaten.toString())
      if (n.id && wartende.has(n.id)) {
        wartende.get(n.id)(n.result)
        wartende.delete(n.id)
      }
    })
    await new Promise((resolve) => ws.on("open", resolve))

    await send("Page.enable")
    await send("Emulation.setDeviceMetricsOverride", {
      width: 1280,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    })
    await send("Page.navigate", { url: URL })
    await warte(12000)

    const bild = await send("Page.captureScreenshot", { format: "png" })
    fs.writeFileSync(ZIEL, Buffer.from(bild.data, "base64"))
    console.log("geschrieben:", ZIEL)
    ws.close()
  } finally {
    chrome.kill()
  }
}

main().catch((e) => {
  console.log("FEHLER:", e.message)
  process.exit(1)
})
