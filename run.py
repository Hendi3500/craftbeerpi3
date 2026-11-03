#!/usr/bin/env python3

import os

from modules import socketio, app, cbpi

# Der Port kommt aus CBPI_PORT, sonst 5000. Der fruehere Parameter "port"
# in der config-Tabelle ist entfernt (update/7_remove_port_config.sql):
# docker-compose bindet das Port-Mapping an CBPI_PORT, ein anderer Wert
# in der Datenbank haette das Mapping unbrauchbar gemacht.
port = 5000

port_env = os.environ.get('CBPI_PORT')
if port_env:
    try:
        port = int(port_env)
    except ValueError:
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
