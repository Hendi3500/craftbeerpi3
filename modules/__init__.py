import json
import pprint
import sys, os
from flask import Flask, render_template, redirect
from flask_socketio import SocketIO, emit

import logging
# Define the WSGI application object

from modules.app_config import *

from modules.core.db import get_db


@app.route('/')
def index():
    return redirect('ui')


# Define the database object which is imported
# by modules and controllers


import modules.steps
import modules.config
import modules.logs
import modules.sensors
import modules.actor
import modules.notification
import modules.fermenter
from modules.addon.endpoints import initPlugins
import modules.ui
import modules.system
import modules.buzzer
import modules.stats
import modules.kettle
import modules.recipe_import
import modules.core.db_mirgrate
import modules.restart

from modules.app_config import cbpi
# Build the database:
# This will create the database file using SQLAlchemy


def init_db():
    with app.app_context():
        db = get_db()

        try:
            with app.open_resource('../config/schema.sql', mode='r') as f:
                db.cursor().executescript(f.read())

            db.commit()
        except Exception as e:
            # Das Schema ist die Grundlage fuer alles Weitere. Ein Fehler
            # hier darf nicht stillschweigend verschwinden - dann laeuft
            # der Server mit einer unbrauchbaren Datenbank weiter.
            app.logger.error("Schema konnte nicht angelegt werden: %s: %s"
                             % (type(e).__name__, e))

init_db()
initPlugins()
cbpi.run_init()

cbpi.run_background_processes()



app.logger.info("##########################################")
app.logger.info("### STARTUP COMPLETE")
app.logger.info("##########################################")