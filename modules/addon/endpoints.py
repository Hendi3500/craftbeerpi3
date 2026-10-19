import json

import re
import sys
from flask import Blueprint, request, send_from_directory
from importlib import import_module, reload as reload_module
from modules import socketio, cbpi


from git import Repo
import os
import requests
import yaml
import shutil

blueprint = Blueprint('addon', __name__)


modules = {}

PLUGIN_DIR = "./modules/plugins"

# Ein Plugin-Name darf nur aus Buchstaben, Ziffern, _, - und . bestehen und
# muss mit einem Buchstaben oder einer Ziffer beginnen.
#
# Warum: die Routen "/api/editor/<name>" nehmen den Namen ungeprueft aus
# dem Pfad. Ohne diese Pruefung laesst sich mit einem Name wie
# "../../logs" jedes Verzeichnis loeschen (deletePlugin macht ein
# shutil.rmtree) oder in beliebige Verzeichnisse schreiben. Der Server
# bindet an 0.0.0.0, ist also im LAN erreichbar.
NAME_MUSTER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# Obergrenze fuer den Namen. Das Dateisystem erlaubt 255 Bytes pro
# Eintrag, ein zu langer Name wuerde erst beim Anlegen mit ENAMETOOLONG
# scheitern.
NAME_MAX_LAENGE = 100


def _plugin_pfad(name):
    """
    Sicheren Pfad fuer ein Plugin liefern.

    Gibt None zurueck, wenn der Name ungueltig ist oder aus dem
    Plugin-Verzeichnis herausfuehren wuerde.
    """
    if not name or not isinstance(name, str) or not NAME_MUSTER.match(name):
        return None
    if len(name) > NAME_MAX_LAENGE:
        return None
    basis = os.path.abspath(PLUGIN_DIR)
    pfad = os.path.abspath(os.path.join(basis, name))
    try:
        if os.path.commonpath([basis, pfad]) != basis:
            return None
    except ValueError:
        # Verschiedene Laufwerke oder Wurzeln - auf Windows ein
        # Sonderfall, auf Linux nicht moeglich.
        return None
    return pfad


def _ist_plugin_verzeichnis(pfad):
    """
    True, wenn ein Eintrag in modules/plugins bzw. modules/base_plugins ein
    echtes Plugin ist.

    ``__pycache__`` ist selbst ein Verzeichnis und damit vom Datei-Filter
    nicht erreichbar - es erschien deshalb in /api/editor/ als installiertes
    Plugin und liess sich als Namespace-Paket sogar ohne Fehler importieren.
    Klammer-Pfade und Punkt-Verzeichnisse sind aus demselben Grund keine
    Plugins.
    """
    name = os.path.basename(pfad.rstrip("/"))
    if name.startswith(".") or name.startswith("_"):
        return False
    return os.path.isdir(pfad)

def merge(source, destination):
    """
    Helper method to merge two dicts
    :param source:
    :param destination:
    :return:
    """
    for key, value in source.items():
        if isinstance(value, dict):
               # get node or create one
            node = destination.setdefault(key, {})
            merge(value, node)
        else:
            destination[key] = value

    return destination

@blueprint.route('/', methods=['GET'])
def getPlugins():
    """
    Endpoint for all plugins
    :return:
    """
    result = []
    for filename in os.listdir(PLUGIN_DIR):
        if filename.endswith(".DS_Store") or filename.endswith(".py") or filename.endswith(".pyc"):
            continue
        if not _ist_plugin_verzeichnis(os.path.join(PLUGIN_DIR, filename)):
            continue
        result.append(filename)

    return json.dumps(result)

@blueprint.route('/<name>', methods=['GET'])
def getFile(name):
    """
    Returns plugin code
    :param name: plugin name
    :return: the plugin code from __init__.py
    """
    return send_from_directory(_plugin_pfad(name) or PLUGIN_DIR, "__init__.py")

@blueprint.route('/<name>', methods=['PUT'])
def createPlugin(name):

    """
    Create a new plugin file
    :param name: the plugin name
    :return: empty http response 204
    """
    pfad = _plugin_pfad(name)
    if pfad is None:
        return ('Invalid plugin name', 400)
    if not os.path.exists(pfad):
        os.makedirs(pfad)
        with open(os.path.join(pfad, "__init__.py"), "wb") as fo:
            fo.write(b"")
        cbpi.emit_message("PLUGIN %s CREATED" % (name))
        return ('', 204)
    else:
        cbpi.emit_message("Failed to create plugin %s. Name arlready in use" % (name))
        return ('', 500)




@blueprint.route('/<name>', methods=['POST'])
def saveFile(name):

    """
    save plugin code. code is provides via http body
    :param name: the plugin name
    :return: empty http reponse
    """
    pfad = _plugin_pfad(name)
    if pfad is None:
        return ('Invalid plugin name', 400)
    if not os.path.isdir(pfad):
        return ('Dir Not found', 500)
    with open(os.path.join(pfad, "__init__.py"), "wb") as fo:
        fo.write(request.get_data())
    cbpi.emit_message("PLUGIN %s SAVED" % (name))

    return ('', 204)

@blueprint.route('/<name>', methods=['DELETE'])
def deletePlugin(name):

    """
    Delete plugin
    :param name: plugin name
    :return: HTTP 204 if ok - HTTP 500 if plugin not exists
    """
    pfad = _plugin_pfad(name)
    if pfad is None:
        return ('Invalid plugin name', 400)
    if os.path.isdir(pfad) is False:
        return ('Dir Not found', 500)
    shutil.rmtree(pfad)
    cbpi.notify("Plugin deleted", "Plugin %s deleted successfully" % name)
    return ('', 204)

@blueprint.route('/<name>/reload/', methods=['POST'])
def reload_plugin(name):
    """
    Hot-Reload eines Plugins.

    Vorher standen hier drei Fehler nebeneinander, die den Endpunkt
    komplett unbrauchbar machten:
      - ``cache`` war nie definiert (NameError)
      - ``reload`` ist in Python 3 kein Builtin mehr (NameError)
      - ``e.message`` gibt es seit Python 3.0 nicht mehr (AttributeError)

    Das Modul-Register ist das lokale ``modules``-Dictionary, in das
    loadCorePlugins() und loadPlugins() schreiben.
    """
    if _plugin_pfad(name) is None:
        return ('Invalid plugin name', 400)
    try:
        if name in modules:
            reload_module(modules[name])
        else:
            modules[name] = import_module("modules.plugins.%s" % (name))
        cbpi.emit_message("REALOD OF PLUGIN %s SUCCESSFUL" % (name))
        return ('', 204)
    except Exception as e:
        cbpi.emit_message("REALOD OF PLUGIN %s FAILED" % (name))
        return json.dumps("%s: %s" % (type(e).__name__, e)), 500


@blueprint.route('/list', methods=['GET'])
def plugins():
    """
    Read the central plugin yaml to get a list of all official plugins
    :return:
    """
    response = requests.get("https://raw.githubusercontent.com/Manuel83/craftbeerpi-plugins/master/plugins.yaml")
    cbpi.cache["plugins"] = merge(yaml.safe_load(response.text), cbpi.cache["plugins"])
    for key, value in  cbpi.cache["plugins"].items():
        value["installed"] = os.path.isdir("./modules/plugins/%s/" % (key))

    return json.dumps(cbpi.cache["plugins"])


@blueprint.route('/<name>/download', methods=['POST'])
def download_addon(name):

    pfad = _plugin_pfad(name)
    if pfad is None:
        return ('Invalid plugin name', 400)

    plugin = cbpi.cache["plugins"].get(name)
    # Die None-Pruefung muss VOR dem Zugriff stehen. Vorher stand
    # plugin["loading"] = True darueber, ein unbekannter Name lief also
    # in einen TypeError und nicht in die 404.
    if plugin is None:
        return ('', 404)
    plugin["loading"] = True
    try:
        Repo.clone_from(plugin.get("repo_url"), pfad)
        cbpi.notify("Download successful", "Plugin %s downloaded successfully" % name)
    except Exception as e:
        cbpi.notify("Download failed", str(e), type="danger", timeout=None)
        return ('', 500)
    finally:
        plugin["loading"] = False

    return ('', 204)

@blueprint.route('/<name>/update', methods=['POST'])
def update_addon(name):
    pfad = _plugin_pfad(name)
    if pfad is None:
        return ('Invalid plugin name', 400)
    if not os.path.isdir(pfad):
        return ('Dir Not found', 500)
    try:
        repo = Repo(pfad)
        o = repo.remotes.origin
        o.pull()
    except Exception as e:
        cbpi.notify("Update failed", str(e), type="danger", timeout=None)
        return ('', 500)
    cbpi.notify("Plugin Updated", "Plugin %s updated successfully. Please restart the system" % name)
    return ('', 204)


def loadCorePlugins():
    for filename in os.listdir("./modules/base_plugins"):

        if _ist_plugin_verzeichnis("./modules/base_plugins/" + filename) is False:
            continue
        try:
            modules[filename] = import_module("modules.base_plugins.%s" % (filename))
        except Exception as e:


            cbpi.notify("Failed to load plugin %s " % filename, str(e), type="danger", timeout=None)
            cbpi.app.logger.error(e)

def loadPlugins():
    for filename in os.listdir(PLUGIN_DIR):
        if _ist_plugin_verzeichnis(os.path.join(PLUGIN_DIR, filename)) is False:
            continue
        try:
            modules[filename] = import_module("modules.plugins.%s" % (filename))
        except Exception as e:
            cbpi.notify("Failed to load plugin %s " % filename, str(e), type="danger", timeout=None)
            cbpi.app.logger.error(e)

#@cbpi.initalizer(order=1)
def initPlugins():
    loadCorePlugins()
    loadPlugins()

@cbpi.initalizer(order=2)
def init(cbpi):

    cbpi.app.register_blueprint(blueprint, url_prefix='/api/editor')
