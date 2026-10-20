#!/usr/bin/env python3

import os

from modules import socketio, app, cbpi

# Der Port kommt aus der Konfiguration (config-Tabelle in der
# Datenbank). Im Container hat die Datenbank aber nicht immer das
# letzte Wort: CBPI_PORT setzt den Port beim Start fest, ohne die
# Datenbank zu aendern. Das ist noetig, weil docker-compose das
# Port-Mapping an einem festen Wert festmacht - laeuft der Server
# auf einem anderen Port, ist das Mapping wertlos.
port = None

port_env = os.environ.get('CBPI_PORT')
if port_env:
    try:
        port = int(port_env)
    except ValueError:
        port = None

if port is None:
    try:
        port = int(cbpi.get_config_parameter('port', '5000'))
    except (ValueError, TypeError):
        port = 5000

# allow_unsafe_werkzeug: noetig, weil der Dienst ueber start-stop-daemon
# ohne TTY laeuft (config/craftbeerpiboot). Flask-SocketIO verlangt diese
# Freigabe sonst ausdruecklich und startet gar nicht. Werkzeug ist fuer den
# Raspberry-Pi-Betrieb ausreichend, allerdings langsamer als ein eigener
# Server. WebSocket-Transport setzt das Paket simple-websocket voraus
# (async_mode="threading" in modules/app_config.py).
socketio.run(
    app,
    host='0.0.0.0',
    port=port,
    allow_unsafe_werkzeug=True,
)
