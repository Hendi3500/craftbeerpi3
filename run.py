#!/usr/bin/env python3

from modules import socketio, app, cbpi

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
