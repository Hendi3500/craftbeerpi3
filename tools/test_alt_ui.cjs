/*
 * Testet die alte CraftBeerPi-Oberflaeche (modules/ui/static/bundle.js)
 * im echten Browser: verbindet sie sich mit dem Backend und kommen
 * Live-Daten an?
 *
 * Der Test startet Chrome headless, laedt die Seite und schaut nach,
 * ob der Socket der Oberflaeche verbunden ist und ob Ereignisse
 * ankommen. Ueber das DevTools-Protokoll wird ein Skript VOR den
 * Skripten der Seite eingefuegt, das window.io.connect abfaengt - so
 * sieht der Test genau den Socket, den die Oberflaeche benutzt.
 *
 * Aufruf:  node tools/test_alt_ui.cjs [url]
 *          Exit 0 = die Oberflaeche hat Live-Daten.
 */
const { spawn } = require("node:child_process")
const http = require("node:http")
const path = require("node:path")
const WebSocket = require(
  path.join(
    "/home/lope/cbpi3UIng/node_modules/.pnpm/ws@8.21.3/node_modules/ws"
  )
)

const URL = process.argv[2] || "http://127.0.0.1:5000/ui/"
const PORT = 9333

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
      `--remote-debugging-port=${PORT}`,
      "about:blank",
    ],
    { stdio: "ignore" }
  )

  try {
    // Chrome braucht einen Moment, bis der Debugger lauscht.
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
    if (!ziel) throw new Error("Chrome antwortet nicht auf dem Debugger-Port")

    const ws = new WebSocket(ziel.webSocketDebuggerUrl, {
      maxPayload: 64 * 1024 * 1024,
    })

    let id = 0
    const wartende = new Map()
    const meldungen = []
    const send = (methode, params = {}) =>
      new Promise((resolve) => {
        const msgId = ++id
        wartende.set(msgId, resolve)
        ws.send(JSON.stringify({ id: msgId, method: methode, params }))
      })

    ws.on("message", (rohdaten) => {
      const nachricht = JSON.parse(rohdaten.toString())
      if (nachricht.id && wartende.has(nachricht.id)) {
        wartende.get(nachricht.id)(nachricht.result)
        wartende.delete(nachricht.id)
        return
      }
      // Fehler und Warnungen der Seite einsammeln.
      if (nachricht.method === "Runtime.consoleAPICalled") {
        const text = (nachricht.params.args || [])
          .map((a) => a.value ?? a.description ?? "")
          .join(" ")
        if (nachricht.params.type === "error" || nachricht.params.type === "warning") {
          meldungen.push(nachricht.params.type + ": " + text.slice(0, 200))
        }
      }
      if (nachricht.method === "Runtime.exceptionThrown") {
        const d = nachricht.params.exceptionDetails
        meldungen.push(
          "exception: " + (d.exception?.description || d.text || "").slice(0, 200)
        )
      }
    })

    await new Promise((resolve) => ws.on("open", resolve))

    // Skript VOR den Skripten der Seite: es faengt window.io.connect ab,
    // sobald der Client geladen ist, und legt den Socket der Oberflaeche
    // unter window.__testSocket ab.
    await send("Page.addScriptToEvaluateOnNewDocument", {
      source: `
        (function () {
          let original = null;
          Object.defineProperty(window, "io", {
            configurable: true,
            get() { return original; },
            set(wert) {
              if (wert && typeof wert.connect === "function") {
                const connect = wert.connect.bind(wert);
                wert.connect = function (...args) {
                  const s = connect(...args);
                  window.__testSocket = s;
                  window.__testEreignisse = [];
                  s.onAny(function (name) {
                    window.__testEreignisse.push(name);
                  });
                  return s;
                };
              }
              original = wert;
            },
          });
        })();
      `,
    })

    await send("Page.enable")
    await send("Runtime.enable")
    await send("Page.navigate", { url: URL })
    await warte(8000)

    const auswerten = async (ausdruck) => {
      const r = await send("Runtime.evaluate", {
        expression: ausdruck,
        returnByValue: true,
      })
      return r && r.result ? r.result.value : undefined
    }

    const verbunden = await auswerten(
      "window.__testSocket ? window.__testSocket.connected : 'kein Socket'"
    )
    const ereignisse = await auswerten(
      "window.__testEreignisse ? window.__testEreignisse.length : 0"
    )
    const namen = await auswerten(
      "window.__testEreignisse ? Array.from(new Set(window.__testEreignisse)).slice(0, 6).join(', ') : ''"
    )
    const clientVersion = await auswerten(
      "window.io && window.io.protocol ? window.io.protocol : 'unbekannt'"
    )
    const dom = await auswerten(
      "document.getElementById('root') ? document.getElementById('root').children.length : 0"
    )

    console.log("  Seite:              ", URL)
    console.log("  Socket.IO-Protokoll: ", clientVersion)
    console.log("  Oberflaeche gerendert (Kinder in #root):", dom)
    console.log("  Socket verbunden:   ", verbunden)
    console.log("  Ereignisse empfangen:", ereignisse, namen ? "(" + namen + ")" : "")
    console.log("  Konsolen-Fehler:     ", meldungen.length ? meldungen.join(" | ") : "keine")

    ws.close()
    return verbunden === true && ereignisse > 0
  } finally {
    chrome.kill()
  }
}

main()
  .then((ok) => {
    console.log(ok ? "  ERGEBNIS: die alte Oberflaeche hat Live-Daten" : "  ERGEBNIS: keine Live-Daten");
    process.exit(ok ? 0 : 1);
  })
  .catch((e) => {
    console.log("  FEHLER:", e.message);
    process.exit(1);
  });
