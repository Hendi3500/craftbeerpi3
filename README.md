# CraftBeerPi 3.0

Eine Brau- und Fermentationssteuerung für den Raspberry Pi, portiert auf
**Python 3 / Flask 3 / Socket.IO 5**.

Die Portierung ist in [MIGRATION.md](MIGRATION.md) dokumentiert — dort steht
für jede Position, was geändert wurde, warum, und wie es verifiziert wurde.

## Schnellstart

```bash
git clone https://github.com/Manuel83/craftbeerpi3
cd craftbeerpi3
sudo ./install.sh          # legt ein virtualenv an und installiert die Pakete
```

`install.sh` legt `.venv/` an und installiert die Pakete dorthin. Auf einem
Raspberry Pi wird zusätzlich `rpi-lgpio` installiert — das Paket braucht die
`lgpio`-C-Bibliothek und lässt sich nur dort bauen.

Danach starten:

```bash
.venv/bin/python run.py
```

Der Server lauscht auf **Port 5000** und bindet an `0.0.0.0`, ist also im
LAN erreichbar. Die Oberfläche liegt unter `/ui`, die REST-Schnittstelle
unter `/api/`.

### Port ändern

Der Port kommt aus der Konfiguration, nicht aus dem Code:

```sql
UPDATE config SET value = '8080' WHERE name = 'port';
```

Ohne diesen Eintrag gilt `5000`.

### Debug-Ausgaben

Das Log landet in `logs/app.log`. Normalerweise steht dort nur, was
wichtig ist (`INFO` und aufwärts). Zum Nachforschen lässt sich der
Level über eine Umgebungsvariable erhöhen:

```bash
CBPI_LOG_LEVEL=DEBUG .venv/bin/python run.py
```

Möglich sind `DEBUG`, `INFO`, `WARNING`, `ERROR` — alles, was Python
kennt. Ohne die Variable gilt `INFO`. Ein unbekannter Wert wird
ignoriert, damit ein Tippfehler nicht das Log abschaltet.

Achtung: auf `DEBUG` schreiben Flask, Werkzeug und Socket.IO jedes
einzelne mit. Das Log wächst dadurch schnell – für den Betrieb also
wieder auf `INFO` zurückgehen.

Flask-eigener Debug-Modus (der interaktive Fehler-Inspektor und der
automatische Reloader) ist davon getrennt und bleibt aus: der Reloader
startet den Server als Kindprozess, und der Neustart-Mechanismus des
Backends (`POST /api/restart`) ersetzt das Prozessbild per `execv` –
beides verträgt sich nicht mit einem Reloader.

### Server verwalten

`tools/serverctl.sh` startet und beendet den Server im Hintergrund, legt
die PID-Datei unter `logs/server.pid` ab und schreibt das Log nach
`logs/server.log`:

```bash
./tools/serverctl.sh start     # starten (im Hintergrund)
./tools/serverctl.sh stop      # beenden
./tools/serverctl.sh restart   # neu starten
./tools/serverctl.sh status    # Zustand anzeigen
```

Der Port wird aus der Konfiguration gelesen, muss also nirgends im
Skript gepflegt werden. Der Server läuft unter dem virtualenv
(`.venv/bin/python`) — mit dem System-Python startet er nicht.

**Der Stopp wird während eines Brauschritts verweigert.** Der PID-Regler,
der die Heizung steuert, läuft im Serverprozess; beendet man ihn, heizt
der Kessel weiter, ohne geregelt zu werden. Wer den Server trotzdem
beenden will, muss es ausdrücklich sagen:

```bash
./tools/serverctl.sh stop --force
```

Dasselbe gilt für `POST /api/restart` — der Endpunkt antwortet in dem
Fall mit HTTP 409.

### T3-Code-Aktion

Im Projekt liegt die Aktion `.opencode/commands/server.md`. Sie ist in
T3 Code als `/server` verfügbar und wird im Chat aufgerufen:

```text
/server start
/server stop
/server status
```

Die Aktion ruft `tools/serverctl.sh` auf. Kommt bei `stop` die
Meldung über den laufenden Brauschritt, fragt die Aktion nach, statt
selbst mit `--force` nachzusetzen.

## Voraussetzungen

| | |
|---|---|
| Python | 3.9 oder neuer (entwickelt und getestet mit 3.14) |
| Flask | 3.1.3 |
| Flask-SocketIO | 5.7.0, `async_mode="threading"` |
| Hardware | optional: 1-Wire für Temperatursensoren, GPIO für Relais |

Die vollständige Liste steht in [requirements.txt](requirements.txt).

## Aufbau

```
├── run.py                  # Einstiegspunkt des Servers
├── config/                 # Init-Skript, DB-Schema, Splash-Screen, Version
├── logs/                   # Laufzeit-Logs
├── modules/                # Anwendungscode
│   ├── actor/              # Aktor-API
│   ├── base_plugins/       # mitgelieferte Plugins (GPIO, 1-Wire, Hysterese, MQTT, …)
│   ├── core/               # Kern: Controller, Datenbank, Hardware-API
│   ├── kettle/             # Kesselsteuerung
│   ├── fermenter/          # Fermentationssteuerung
│   ├── plugins/            # nachinstallierbare Benutzer-Plugins
│   ├── recipe_import/      # BeerXML/Kleiner Brauhelfer Import
│   ├── sensors/            # Sensor-API
│   ├── steps/              # Brauschritte
│   ├── system/             # System-Endpunkte
│   └── ui/                 # Weboberfläche (Flask + Socket.IO)
├── tools/                  # Testwerkzeuge und Route-Baseline
├── update/                 # SQL-Migrationen
└── upload/                 # hochgeladene Rezepte/Dateien
```

### Kern vs. Plugins

`modules/base_plugins/` ist versionierter Teil des Projekts und lädt bei
jedem Start. `modules/plugins/` ist für nachinstallierbare Plugins gedacht
und wird vom Editor unter *Konfiguration → Plugin* verwaltet.

`modules/core/classy.py` ist ein eigener Ersatz für `flask_classy` 0.6.10
(2014, läuft unter Flask 3 nicht mehr). Er routet weiterhin nach
**Methodennamen** statt nach HTTP-Verben — nötig, weil `/api/step/` sonst
zwischen `getAll` (GET) und `/api/step/reset` (POST) kollidiert. Die
107 Routen bleiben dadurch unverändert.

## MQTT

MQTT ist **Kernbestandteil** (`modules/base_plugins/mqtt`) und braucht kein
Setup mehr außer dem Broker-Eintrag unter *Konfiguration → MQTT*:

| Feld | Bedeutung |
|---|---|
| `mqtt_server` | Hostname oder IP, Standard `localhost` |
| `mqtt_port` | Standard `1883` |
| `mqtt_username` / `mqtt_password` | leer lassen für anonymen Zugriff |
| `mqtt_tls` | Auswahlfeld `YES` / `NO` |
| `mqtt_ca_cert` / `mqtt_cert` / `mqtt_key` | optionale Pfade für TLS |

Die Parameter heißen klein wie die übrigen Parameter von CraftBeerPi 3
(`unit`, `brewery_name`, `setup`, `port`). Sie hießen früher
`MQTT_SERVER`, `MQTT_TLS` und so weiter; die vorhandene Konfiguration wird
beim Update automatisch übernommen.

Die Verbindung kommt automatisch zustande und wird bei einem Broker-Neustart
von selbst wieder aufgebaut; die Abos werden dabei erneut gesetzt. Es gibt
drei Bausteine:

- **MQTT_SENSOR** — Wert aus einem Topic lesen. „Payload Dictionary" legt
  den Pfad in verschachteltem JSON fest (`Sensor.Value`); leer lassen
  bedeutet Rohwert. Nur Skalare (Zahl, Text, Boolean) werden übernommen.
- **MQTTActor** — sendet `{"state": "on"}` / `{"state": "off"}`.
- **ESPEasyMQTT** — sendet die Rohwerte `1` / `0` nach ESPEasy-Konvention.

Details im [Plugin-README](modules/base_plugins/mqtt/README.md).

## Docker

Für PC und Mac liegt ein Container-Setup bei (Python 3, Image auf Basis von
`python:3.12-slim`):

```bash
docker compose up --build
```

Die Oberfläche ist danach unter <http://localhost:5000/ui/> erreichbar, die
REST-Schnittstelle unter <http://localhost:5000/api/>.

Das Verzeichnis wird in den Container gemountet — Datenbank (`craftbeerpi.db`)
und Logs (`logs/`) liegen damit auf dem Host und überleben ein
`docker compose down`. Der Port ist über die Umgebungsvariable `CBPI_PORT`
änderbar; sie hat im Container Vorrang vor dem Port aus der Datenbank:

```bash
CBPI_PORT=8080 docker compose up
```

GPIO ist im Container nicht erreichbar: Aktoren am Raspberry Pi werden
dort nicht geschaltet. Auf dem Pi läuft CraftBeerPi nach `install.sh` direkt
auf dem System, nicht im Container.

## Entwicklung und Prüfung

Unter `tools/` liegt die Test-Infrastruktur. Sie prüft nicht nur, ob die
Antwort stimmt, sondern auch, ob die **Routenliste** unverändert bleibt —
der wahrscheinlichste Fehler beim Umbau von `flask_classy` auf ein
Standard-`MethodView` ist das Wegfallen der Trailing-Slashes.

```bash
.venv/bin/python tools/snapshot_routes.py     # aktuelle Routen schreiben
.venv/bin/python tools/compare_routes.py      # gegen die Baseline prüfen
.venv/bin/python tools/test_api.py            # 32 REST-Aufrufe
.venv/bin/python tools/test_json.py           # 16 Serialisierungsprüfungen
.venv/bin/python tools/test_socket.py         # 21 Socket.IO-Prüfungen
.venv/bin/python tools/test_socket_e2e.py     #  9 Prüfungen mit echtem WebSocket
.venv/bin/python tools/sweep_endpoints.py     # alle GET-Routen, nur lesend
.venv/bin/python tools/test_gpio.py           # 34 GPIO-Prüfungen
.venv/bin/python tools/test_system.py         # 14 System-Endpunkte
.venv/bin/python tools/test_plugins.py        # 42 Plugin-Management
.venv/bin/python tools/test_migration.py      # 13 SQL-Migrationen
.venv/bin/python tools/test_kern_uebernahmen.py # 43 uebernommene Kern-Funktionen
.venv/bin/python tools/test_unbekannte_id.py    # 21 unbekannte Ids
```

Alle Skripte liefern bei Abweichung einen Exit-Code ungleich 0 und eignen
sich damit als Gate. `test_migration.py` arbeitet in einem eigenen
Verzeichnis und fasst die echte Datenbank nicht an.

> `sweep_endpoints.py` ruft **ausschließlich lesende** GET-Routen auf und
> lässt Endpunkte mit Seiteneffekt aus — insbesondere `/api/system/tags/<x>`,
> das ein echtes `git checkout` ausführt. Ein früherer, ungefilterter Sweep
> hat darüber versehentlich den Arbeitsstand im Repository überschrieben.

## Häufige Probleme

**`ERROR in __init__: BUZZER not working`**
Kein Buzzer angeschlossen oder kein GPIO verfügbar (z. B. im
Docker-Container). Der Server läuft weiter, nur der Piepton fehlt.

**`No module named 'RPi'`**
Kein Raspberry Pi. Die Hardware-Plugins werden dann übersprungen.

**Die Live-Anzeige im alten UI bleibt leer**
Der Socket spricht Engine.IO 4. Das alte `bundle.js` bringt einen
`socket.io-client` der Version 2 mit, der Engine.IO 3 spricht — der
Handshake wird mit 400 abgelehnt, und die alte Oberfläche hat keine
Live-Daten. Abhilfe: `modules/ui/static/socket.io.min.js` (Client
Version 4) wird vor dem Bundle geladen, und das Bundle benutzt ihn
statt des eigenen — eine Zeile im Bundle ist dafür angepasst
(`(window.io||i.default).connect(...)`). Wird das Bundle neu gebaut,
muss diese Anpassung wieder hinein. Die REST-Schnittstelle ist
davon nicht betroffen. Die neue Oberfläche bringt ihren Client
selbst mit und braucht nichts davon.

**Ein Endpunkt antwortet mit 500**
`logs/app.log` nennt den Endpunkt und den Traceback. Häufigste Ursache ist
ein Objekt im Cache, das der JSON-Provider nicht kennt — der Provider
liefert für unbekannte Typen `null`, wie der ComplexEncoder aus Flask 0.12.

**Die GPIO-Aktoren tun nichts**
`rpi-lgpio` fehlt oder lässt sich nicht installieren. Auf dem Pi:
`pip install rpi-lgpio`. Das Paket braucht die `lgpio`-C-Bibliothek und
lässt sich nur auf dem Pi bauen.

**`GET /api/system/tags/<name>` antwortet mit 409**
Der Endpunkt verweigert den Checkout in zwei Fällen:

- Der Arbeitsbaum hat uncommittete Änderungen — das `git reset --hard`
  dahinter würde sie verwerfen. Erst committen, dann erneut versuchen.
- Der Tag ist **älter als der aktuelle Stand**. Ein Checkout auf einen
  alten Tag entfernt die Commits zwischen dem Tag und dem aktuellen
  Stand aus dem Arbeitsbaum — auch dann, wenn alles committet ist. Das
  hat am 19.10.2026 den kompletten Python-3-Port vernichtet, obwohl der
  Arbeitsbaum sauber war. Erlaubt ist nur ein Tag, der den aktuellen
  HEAD enthält.

Vor dem Checkout wird der aktuelle Stand als Branch
`backup/pre-tag-checkout` gesichert, damit der Zustand wiederherstellbar
bleibt.

**`CRITICAL: We need to talk about your installation`**
Python 3.12 oder neuer auf einem System, in dem `rpi-lgpio` nicht
gebaut werden kann. Die GPIO-Aktoren und der Buzzer brauchen das Paket;
alles andere läuft ohne.
