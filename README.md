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
| `MQTT_SERVER` | Hostname oder IP, Standard `localhost` |
| `MQTT_PORT` | Standard `1883` |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | leer lassen für anonymen Zugriff |
| `MQTT_TLS` | `true` schaltet TLS ein |
| `MQTT_CA_CERT` / `MQTT_CERT` / `MQTT_KEY` | optionale Pfade für TLS |

Die Verbindung kommt automatisch zustande und wird bei einem Broker-Neustart
von selbst wieder aufgebaut; die Abos werden dabei erneut gesetzt. Es gibt
drei Bausteine:

- **MQTT_SENSOR** — Wert aus einem Topic lesen. „Payload Dictionary" legt
  den Pfad in verschachteltem JSON fest (`Sensor.Value`); leer lassen
  bedeutet Rohwert. Nur Skalare (Zahl, Text, Boolean) werden übernommen.
- **MQTTActor** — sendet `{"state": "on"}` / `{"state": "off"}`.
- **ESPEasyMQTT** — sendet die Rohwerte `1` / `0` nach ESPEasy-Konvention.

Details im [Plugin-README](modules/base_plugins/mqtt/README.md).

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
Der Socket spricht Engine.IO 4, das alte `bundle.js` spricht Engine.IO 3
und wird abgelehnt. Die REST-Schnittstelle ist davon nicht betroffen. Eine
neue Oberfläche mit aktuellem `socket.io-client` ist der saubere Weg.

**Ein Endpunkt antwortet mit 500**
`logs/app.log` nennt den Endpunkt und den Traceback. Häufigste Ursache ist
ein Objekt im Cache, das der JSON-Provider nicht kennt — der Provider
liefert für unbekannte Typen `null`, wie der ComplexEncoder aus Flask 0.12.

**Die GPIO-Aktoren tun nichts**
`rpi-lgpio` fehlt oder lässt sich nicht installieren. Auf dem Pi:
`pip install rpi-lgpio`. Das Paket braucht die `lgpio`-C-Bibliothek und
lässt sich nur auf dem Pi bauen.

**`GET /api/system/tags/<name>` antwortet mit 409**
Der Endpunkt verweigert den Checkout, solange der Arbeitsbaum
uncommittete Änderungen hat — das `git reset --hard` dahinter hätte sie
verworfen. Erst committen, dann erneut versuchen.

**`CRITICAL: We need to talk about your installation`**
Python 3.12 oder neuer auf einem System, in dem `rpi-lgpio` nicht
gebaut werden kann. Die GPIO-Aktoren und der Buzzer brauchen das Paket;
alles andere läuft ohne.
