
import json
import sys, os
import types
from flask import Flask, render_template, redirect, json, g
from flask.json.provider import DefaultJSONProvider


from flask_socketio import SocketIO, emit

import logging



from modules.core.core import CraftBeerPi, ActorBase, SensorBase
from modules.core.db import DBModel

app = Flask(__name__)

FORMAT = '%(asctime)-15s - %(levelname)s - %(message)s'

logging.basicConfig(filename='./logs/app.log',level=logging.INFO, format=FORMAT)
app.config['SECRET_KEY'] = 'craftbeerpi'
app.config['UPLOAD_FOLDER'] = './upload'


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


class ComplexJSONProvider(DefaultJSONProvider):
    """
    Ersetzt den in Flask 2.2 entfernten app.json_encoder.

    Flask 2.2 hat app.json_encoder entfernt, der Ersatz ist ein Provider
    (DefaultJSONProvider). Die Reihenfolge der Pruefungen entspricht dem
    ComplexEncoder aus Flask 0.12, das Verhalten an zwei Stellen nicht:

    - Unbekannte Typen liefern jetzt einen Klartext-Fehler mit Typnamen
      statt stillschweigend None. Das Original hat bei jedem unbekannten
      Typ Daten verworfen, ohne es zu melden - 36 Felder im Cache-Dump
      waren davon betroffen (Plugin-Klassen in *_types, Background-Tasks
      und Initializer als Funktionen). Siehe die Vergleiche in MIGRATION.md.
      Diese Felder werden einzeln benannt. Fuer alle *weiteren* unbekannten
      Typen gilt weiter der alte None-Zweig: die Aufzaehlung beschreibt nur
      den statischen Cache-Inhalt, die zur Laufzeit entstehenden Instanzen
      (Hysteresis in Kettle.instance, ChilStep in active_step) gab es beim
      Portieren noch nicht, sonst wuerden /api/kettle/ und /api/system/dump
      beim ersten Benutzen eines Kessels mit HTTP 500 antworten.
    - Sortierung und ensure_ascii uebernimmt der DefaultProvider
      (sort_keys=True), wie vorher flask.json.dumps.
    """

    @staticmethod
    def default(o):
        if isinstance(o, DBModel):
            return o.__dict__

        if isinstance(o, ActorBase):
            return o.state()

        if isinstance(o, SensorBase):
            return o.get_value()

        # Cache-Callbacks werden als ausfuehrbare Methode markiert
        # (CraftBeerPi.add_cache_callback, core.py:231)
        if hasattr(o, "callback"):
            return o()

        # Klassen statt Instanzen: cbpi.cache haelt in *_types die Plugin-
        # Klassen selbst (core.py:34, core.py:272). Sie erscheinen im
        # Cache-Dump /api/system/dump, den das Frontend beim Start laedt.
        # Der ComplexEncoder aus Flask 0.12 gab fuer alles Unbekannte
        # stillschweigend None zurueck - davon haengt dieser Endpunkt ab.
        if isinstance(o, type):
            return {"name": o.__name__, "module": o.__module__}

        # Funktionen im Cache sind Background-Tasks (core.py:469) und
        # Cache-Callbacks (core.py:231). Callables werden ausgefuehrt, wenn
        # sie als callback markiert sind, sonst nur benannt - die
        # Dekorator-Wrapper in core.py:474 wuerden beim Aufruf in den
        # Cache schreiben.
        if isinstance(o, types.FunctionType):
            return {"name": o.__name__, "module": o.__module__}

        if isinstance(o, (types.MethodType, types.BuiltinFunctionType)):
            return {"name": getattr(o, "__name__", str(o))}

        # Opt-in-Hook fuer Objekte, die im Cache liegen und dort nicht
        # serialisierbar sind. /api/system/dump macht json.dumps auf den
        # gesamten Cache und wird vom Frontend beim Start geladen - ohne
        # diese Ausnahme wird der Endpunkt zu einem 500er, sobald ein Plugin
        # eine eigene Verbindung im Cache ablegt (MQTTPlugin).
        to_json = getattr(o, "__json__", None)
        if callable(to_json):
            return to_json()

        # Alles Uebrige: ComplexEncoder aus Flask 0.12 gab hier im else-Zweig
        # "return None" zurueck, ohne Meldung (MIGRATION.md, "Was der alte
        # Encoder verschluckt hat"). Die Aufzaehlung oben deckt nur den
        # statischen Cache-Inhalt ab - die Laufzeit-Objekte entstehen erst
        # spaeter, wenn ein Kessel einen Actor bekommt (Hysteresis-Instanz in
        # Kettle.instance) oder ein Schritt laeuft (ChilStep in active_step).
        # Ohne diesen Zweig liefern /api/kettle/ und /api/system/dump dann
        # HTTP 500, sobald ein Kessel benutzt wird.
        app.logger.debug("JSON: unbekannter Typ %s wird zu null",
                         type(o).__name__)
        return None


app.json = ComplexJSONProvider(app)

# async_mode fest auf threading. eventlet ist deprecated und nur noch im
# Bugfix-Modus; ohne diese Angabe wuerde flask-socketio selbst ein
# async-Modell waehlen. Der Server empfaengt keine Socket-Events - der
# Socket ist reiner Server->Client-Push (core.py:219-220) - es gibt also
# keinen Bedarf fuer kooperative Nebenlaeufigkeit zwischen I/O-Warten.
#
# Der Namespace /brew muss hier ausdruecklich benannt werden: python-socketio
# 5.x prueft bei jedem Connect gegen eine Whitelist (server.py:519-523) und
# lehnt sonst mit "Unable to connect" ab. /brew hat im Projekt keinen Handler,
# weil der Socket reiner Server->Client-Push ist - ohne diese Angabe kann
# sich kein Client verbinden und es kommen keine Live-Daten mehr an.
#
# Wichtig: die Liste ERSETZT den Default ['/'] (base_server.py:65), nicht
# erweitert ihn. '/' bleibt deshalb enthalten.
#
# json=json ist Pflicht: flask-socketio erkennt das flask.json-Modul und
# ersetzt es durch einen FlaskSafeJSON-Wrapper, der den App-Kontext erzwingt
# (flask_socketio/__init__.py:216-233). Genau daran haengt der komplette
# Live-Datenstrom - faellt der Parameter weg, faellt jede Temperaturmeldung.
#
# cors_allowed_origins="*" ist noetig, weil python-engineio sonst nur einen
# Origin akzeptiert, der zum Host passt, den der Server sieht (Default None =
# Same-Origin). Jeder Reverse Proxy vor dem Backend (z. B. der Nitro-Server der
# cbpi3-ui, der den Host-Header auf 192.168.x.x:5000 umschreibt) laesst dann
# jeden Request mit dem Socket.IO-Handshake mit "Not an accepted origin." (400)
# ablehnen und der Browser verbindet sich nie. Das Backend selbst bindet nur
# an 0.0.0.0 im lokalen Netz, deshalb ist das hier unkritisch.
#
# allow_upgrades=False ist Pflicht, solange der Werkzeug-Entwicklungsserver
# laeuft: der kann den WebSocket-Upgrade nicht bedienen, der Engine.IO-Server
# antwortet darauf mit 400. Der Client versucht es trotzdem - socket.io-client
# 4 beendet die Verbindung nach dem fehlgeschlagenen Upgrade und verbindet
# sich *nicht* wieder, weil der Manager skipReconnect gesetzt hat. Die
# Oberflaeche haengt dann dauerhaft ohne Live-Daten da: keine Temperaturen,
# kein Aktualisieren nach einem Schritt-Reset, und der Knopf "Auto" am
# Fermenter sieht tot aus. Der Handshake sagt mit "upgrades": [] gleich die
# Wahrheit - der Client bleibt auf Polling, das der Server kann.
socketio = SocketIO(
    app,
    json=json,
    logging=False,
    async_mode="threading",
    namespaces=["/", "/brew"],
    cors_allowed_origins="*",
    allow_upgrades=False,
)
cbpi   = CraftBeerPi(app, socketio)

app.logger.info("##########################################")
app.logger.info("### NEW STARTUP Version 3.0")
app.logger.info("##########################################")
