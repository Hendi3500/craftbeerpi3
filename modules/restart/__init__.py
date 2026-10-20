# -*- coding: utf-8 -*-
"""
Neustart des Backends ueber die API.

Wofuer
------
Der Kern kann sich nicht selbst neu starten. ``CraftBeerPi`` hat kein
``shutdown()``, kein ``restart()`` und kein ``reload()``, kein Event und
keine Socket-Message dafuer. Das einzige "Restart" im Kern ist ein Text,
der den Brauer auffordert, es selbst zu tun ("Plugin %s updated
successfully. Please restart the system"). Der Ablauf "Plugin speichern ->
wirksam machen" ist damit: deployen, Neustart von Hand, hoffen.

Dieses Modul liefert den Neustart als API:

==========================  ==========================================
``POST /api/restart``       202 - Neustart ist eingplant
``GET  /api/restart``       Status
==========================  ==========================================

Wie der Neustart passiert
--------------------------
Das Backend fuehrt sich selbst wieder aus:

.. code-block:: python

    os.execv(sys.executable, [sys.executable, "<backend>/run.py"])

``execv`` ersetzt das Prozess-Image und **behaelt die PID**. Genau darum
geht es: Das Backend wird vom SysV-Skript ``/etc/init.d/craftbeerpiboot``
ueber ``start-stop-daemon --make-pidfile`` gestartet - die PID-Datei
bleibt also korrekt, und ``start-stop-daemon`` bemerkt ueberhaupt
nichts. Kein ``sudo``, kein Signal, keine Abhaengigkeit vom Init-Skript:
der Neustart funktioniert genauso, ob die Anlage das Init-Skript,
systemd oder gar nichts verwendet.

Das erneute ``run.py`` fuehrt die komplette Boot-Kette noch einmal aus,
denn der Import des ``modules``-Pakets *ist* der Boot
(``modules/__init__.py``): ``init_db()`` -> ``initPlugins()`` ->
``cbpi.run_init()`` -> ``cbpi.run_background_processes()``. Das ist genau
die Abfolge, die ein Service-Neustart macht - inklusive Neu-Import aller
Plugins, sodass Runtime-Patches wieder greifen.

Sicherheitsnetze
----------------
- **``sys.executable``, nicht "python".** Unter einem virtualenv koennen
  beide verschieden sein - und ``sys.executable`` ist der Interpreter, der
  ``run.py`` gerade wirklich ausfuehrt. Ist er leer, wird der Neustart
  verweigert statt geraten.
- **``run.py`` wird aus dem ``modules``-Paket abgeleitet**, nicht aus dem
  aktuellen Verzeichnis: der Neustart haengt damit nicht daran, dass das
  Skript mit ``--chdir`` im Backend-Verzeichnis gestartet wurde.
- **Ein laufender Braustep blockiert den Neustart** (409), ausser der
  Aufrufer sagt ``{"force": true}``. Ein Neustart stoppt den
  Step-Controller - von da an reguliert nichts mehr die Heizung, und ein
  auf 100 °C stehender Kessel heizt weiter. "Aktiv" ist ein Step im
  Zustand "A" (so setzt ihn ``StepView.start()``).
- **Ein zweiter Request waehrend des Countdowns** bekommt 409 mit dem
  aktuellen Status. Ohne diese Sperre gaebe es zwei Countdowns, und das
  erste ``execv`` naehme den Prozess einfach zu frueh weg.
- **Findet das Backend sich nicht selbst**, antwortet es mit 500 und
  startet nichts neu - besser ein lautes Scheitern als ein 202, hinter
  dem nichts passiert. Derselbe Fehler im Background-Thread raeumt die
  Sperre auf und meldet eine persistente Notification.
- **``delay`` im Body** ueberschreibt die Wartezeit (Default 3 s). 0 oder
  kleiner wird ignoriert - 0 wuerde die Antwort selbst killen, ein
  negatives ist ein Tippfehler und kein Wunsch nach Geschwindigkeit.
- **Vor dem ``execv`` wird das Log geleert** (die Handler werden
  geflusht, nicht geschlossen - ein ``logging.shutdown()`` wuerde einem
  ``execv``, das fehlschlaegt, auch noch die Fehlermeldung wegnehmen).
  Die Zeile, die den Neustart erklaert, steht damit in der alten wie in
  der neuen Logdatei.

Fuer die Clients faellt jede socket.io-Verbindung weg und kommt einzeln
wieder; die UI laedt danach wie ueblich ``GET /api/system/dump``. Wer
vorher etwas anzeigen will, bekommt vorher das Socket-Event
``RESTART_SCHEDULED`` mit dem Status.

Wann ueberhaupt ein Neustart ansteht
-------------------------------------
Der Knopf ist nicht "falls gebraucht" da, sondern **nur wenn sich ein
Plugin geaendert hat** - und das weiss jeder Client, auch der, der nicht
gespeichert hat. Dafuer gibt es zwei Config-Parameter:

===========================  =========================================
``plugins_changed``          JSON-Liste offener Aenderungen
``backend_started_at``       Epoch-Sekunden des Starts des Backends
===========================  =========================================
"""

import json
import logging
import os
import sys
import time

from flask import Blueprint, json as flask_json, request

from modules import cbpi
from modules.steps import Step

import modules as modules_package


logger = logging.getLogger(__name__)

blueprint = Blueprint('backend_restart', __name__)

# Sekunden zwischen der Antwort und dem Neustart. Lang genug, damit die
# Antwort das Gerät verlaesst und die Socket-Clients die Ansage sehen,
# kurz genug, damit der Brauer nicht denkt, der Knopf habe nichts getan.
RESTART_DELAY = 3

# An die Clients kurz vor dem Neustart, damit die UI statt nur dem
# Wegfallen der Verbindung ein "restarting"-Overlay zeigen kann.
SCHEDULE_EVENT = "RESTART_SCHEDULED"

# {"at": <epoch>, "delay": <sekunden>} waehrend ein Neustart unterwegs ist,
# None sonst. Sperrt gegen einen zweiten Request: der wuerde einen zweiten
# Countdown starten, und das erste execv wuerde den Prozess einfach zu
# frueh wegnehmen.
_pending = None

# Config-Parameter mit den Plugin-Aenderungen, die noch einen Neustart
# wollen - als JSON-Liste. Ein Parameter statt Speicher, damit auch die
# Clients, die nicht geaendert haben, davon erfahren.
CONFIG_CHANGED = "plugins_changed"

# Config-Parameter mit der Epoch dieses Backend-Starts. Eine Aenderung,
# die aelter ist, ist laengst angewendet und darf keinen Neustart mehr
# vorschlagen.
CONFIG_STARTED = "backend_started_at"

# Obergrenze fuer die Liste. Die Liste wächst nur durch Aenderungen ohne
# Neustart - das ist schon eine Situation, die jemand bemerken sollte;
# ohne Obergrenze wuerde sie in einer lang laufenden Installation zu einer
# Logdatei.
CHANGES_LIMIT = 20

# Die Editor-Endpunkte, die ein Plugin auf der Platte aendern, mit dem
# Verb, das festgehalten wird. Alles andere ist ein Lesen und aendert
# nichts.
CHANGE_ENDPOINTS = {
    "addon.saveFile": "saved",
    "addon.createPlugin": "created",
    "addon.deletePlugin": "deleted",
    "addon.download_addon": "installed",
    "addon.update_addon": "updated",
}


def _run_script():
    """
    Absoluter Pfad von run.py, abgeleitet aus der Lage des modules-Pakets.

    <backend>/modules/__init__.py -> <backend>/run.py. Aus dem Paket
    abgeleitet und nicht aus ``os.getcwd()``, damit es egal ist, ob der
    Prozess mit ``--chdir`` im Backend-Verzeichnis gestartet wurde. None,
    wenn es die Datei dort nicht gibt.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(modules_package.__file__)))
    candidate = os.path.join(root, "run.py")

    if os.path.isfile(candidate):
        return candidate

    # Letzte Moeglichkeit: das Arbeitsverzeichnis, in das das Init-Skript
    # ohnehin chdir't.
    fallback = os.path.join(os.getcwd(), "run.py")
    return fallback if os.path.isfile(fallback) else None


def _is_brewing():
    """
    True, waehrend ein Brauschritt laeuft.

    Ein Step im Zustand "A" ist der aktive - StepView.start() setzt ihn
    und setzt den vorherigen Step zurueck. None heisst: kein Step laeuft,
    also reguliert nichts unter einem Controller gerade die Heizung.
    """
    with cbpi.app.app_context():
        return Step.get_by_state("A") is not None


def _status():
    """
    Der Zustand eines wartenden Neustarts - fuer GET und fuer die
    Konfliktantworten.

    Die Sekunden werden ab dem Moment heruntergezaehlt, in dem der
    Request angenommen wurde, damit der Client denselben Countdown sieht,
    der ihm zugesagt wurde, und nicht einen Wert, der springt, wenn er
    zweimal fragt.
    """
    if _pending is None:
        return {"pending": False, "seconds": 0, "delay": RESTART_DELAY}

    remaining = _pending["delay"] - (time.time() - _pending["at"])
    return {
        "pending": True,
        "seconds": int(round(remaining)) if remaining > 0 else 0,
        "delay": _pending["delay"],
    }


def _sockets_unererbbar_machen():
    """
    Die Sockets dieses Prozesses unererbbar machen.

    Warum das noetig ist
    -------------------
    Der Werkzeug-Server setzt seinen Listening-Socket absichtlich auf
    "inheritable" (werkzeug/serving.py: ``srv.socket.set_inheritable(True)``).
    Er soll damit an einen Reloader-Kindprozess weitergegeben werden
    koennen.

    Beim ``execv`` erbt das neue Prozessbild diesen Socket deshalb
    auch - und startet mit einem Port, der bereits gebunden ist. Der
    zweite Bind des neuen Servers schlaegt mit "Address already in use"
    fehl, das Backend beendet sich und das Ergebnis ist: **kein
    Prozess, kein Port, keine Oberflaeche**. Der Neustart-Knopf hat das
    Backend damit abgeschossen, statt es neu zu starten - und wer es
    nicht bemerkte, hat ein totes System vor sich.

    Deshalb werden die Sockets vor dem Wechsel des Prozessbildes
    unererbbar gemacht. Der Kernel schliesst sie dann beim execv, und
    der neue Prozess bindet den Port von Grund auf.

    :return: Die Anzahl der umgestellten Deskriptoren.
    """
    geaendert = 0

    try:
        pfad = "/proc/self/fd"
        for name in os.listdir(pfad):
            try:
                fd = int(name)
                if not os.readlink(os.path.join(pfad, name)).startswith("socket:"):
                    continue
                if not os.get_inheritable(fd):
                    continue
                os.set_inheritable(fd, False)
                geaendert += 1
            except (OSError, ValueError):
                # Der Deskriptor kann zwischen dem Listing und dem
                # Zugriff verschwunden sein - dann ist er aber auch
                # nicht mehr zu erben.
                continue
    except Exception as e:
        logger.warning("BackendRestart: Sockets konnten nicht unererbbar "
                       "gemacht werden: %s" % e)

    return geaendert


def _execute(delay):
    """
    Warten, dann dieses Prozess-Image durch ein frisches Backend ersetzen.

    Laeuft in einem Hintergrund-Thread. Nichts hier darf eine Exception
    werfen - ein Fehler muss die Sperre raeumen und jemandem Bescheid
    geben, weil die Alternative ein Backend waere, das 202 antwortet und
    sich dann nie neu startet.
    """
    global _pending

    try:
        run_script = _run_script()

        # socketio.sleep ist der Sleep des Async-Modells. Im Modus
        # "threading" ist das time.sleep - es haelt den Hub beim Warten
        # nicht am Laufen, aber es blockiert auch nicht den Server.
        cbpi.socketio.sleep(delay)

        if run_script is None or not os.path.isfile(run_script):
            raise RuntimeError("run.py not found")

        interpreter = sys.executable

        if not interpreter:
            raise RuntimeError("sys.executable is empty")

        # Die gepufferten Logzeilen raus, bevor das Image ersetzt wird, damit
        # das Log sie behält. Flush, nicht shutdown: execv schlaegt laut fehl,
        # und ein toter Logger wuerde die Fehlermeldung auch noch wegnehmen.
        logger.info("BackendRestart: exec %s %s" % (interpreter, run_script))

        # Der Neustart wendet alles an, was auf der Platte liegt - auch ein
        # Plugin, das waehrend der Wartezeit gespeichert wurde. Die Liste der
        # offenen Aenderungen geht deshalb mit diesem Prozess. Schlaegt das
        # Leeren fehl, bleibt die Liste stehen und die UI bietet einen
        # Neustart an, der nichts mehr zu tun hat: falsch, aber harmlos.
        _clear_changes()

        for handler in logging.root.handlers[:]:
            try:
                handler.flush()
            except Exception:
                pass

        # Der Listening-Socket darf nicht in das neue Prozessbild
        # geerbt werden - sonst kann der neue Server den Port nicht
        # binden und das Backend steht nicht mehr. Siehe
        # _sockets_unererbbar_machen().
        anzahl = _sockets_unererbbar_machen()
        logger.info("BackendRestart: %d Socket(s) unererbbar gemacht" % anzahl)

        # Ab hier kehrt nichts zurueck. Die PID bleibt gleich, damit die
        # PID-Datei des Init-Skripts gueltig bleibt.
        os.execv(interpreter, [interpreter, run_script])
    except Exception as e:
        _pending = None
        logger.error("BackendRestart: Neustart fehlgeschlagen (%s)" % e)
        cbpi.notify(
            "Backend",
            "Restart failed: %s" % e,
            type="error",
            timeout=None,
        )


def _ensure_parameters():
    """
    Sicherstellen, dass beide Parameter existieren.

    ``set_config_parameter`` wirft einen KeyError fuer einen Namen, den
    der Config-Cache nicht kennt, und ein erneutes Anlegen wuerde eine
    doppelte Zeile einfuegen - deshalb wird der Cache geprueft, das ist
    ueber Neustarts hinweg idempotent.
    """
    for name, description in (
        (CONFIG_CHANGED, "Plugins changed since the last backend restart, JSON. Internal, do not edit."),
        (CONFIG_STARTED, "When the running backend was started (epoch seconds, float). Internal, do not edit."),
    ):
        config = cbpi.cache.get("config")

        if config is None:
            return False

        if name in config:
            continue

        cbpi.add_config_parameter(name, "[]" if name == CONFIG_CHANGED else "0", "text", description)

    return True


def _read_changes():
    """
    Die aufgezeichneten Aenderungen, neueste zuerst. Wirft nie - die Liste
    ist nur ein Hinweis.
    """
    raw = cbpi.get_config_parameter(CONFIG_CHANGED, "[]")

    try:
        entries = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("BackendRestart: %s ist nicht lesbar, fange neu an" % CONFIG_CHANGED)
        return []

    if not isinstance(entries, list):
        return []

    return [e for e in entries if isinstance(e, dict) and e.get("name")]


def _write_changes(changes):
    cbpi.set_config_parameter(CONFIG_CHANGED, json.dumps(changes))


def _record_change(name):
    """
    Merken, dass ein Plugin geaendert wurde.

    Aufgerufen aus einem after_request-Hook, also muss es scheitern
    duerfen: die beobachtete Anfrage war bereits erfolgreich, und aus
    einem gespeicherten Plugin einen 500 zu machen wuerde dem Brauer
    weder das Plugin noch den Hinweis lassen.
    """
    try:
        if not _ensure_parameters():
            return

        now = time.time()
        # Ein zweimal gespeichertes Plugin behaelt die neuere Zeit - die ist
        # die, gegen die der Vergleich mit dem Backend-Start laeuft.
        entries = [e for e in _read_changes() if e.get("name") != name]
        entries.append({"name": name, "at": now, "action": CHANGE_ENDPOINTS.get(request.endpoint, "changed")})
        entries.sort(key=lambda e: e.get("at", 0))
        _write_changes(entries[-CHANGES_LIMIT:])

        logger.info("BackendRestart: Plugin %s geaendert, ein Neustart ist faellig" % name)
    except Exception as e:
        logger.error("BackendRestart: Aenderung von %s konnte nicht notiert werden (%s)" % (name, e))


def _clear_changes():
    """
    Die aufgezeichneten Aenderungen vergessen - der Neustart wendet sie alle
    an.

    Hier, in dem Prozess, der geht, und nicht im neuen: die Liste bedeutet
    "geaendert seit dem Start des laufenden Backends", und nach dem execv
    ist das neue Backend das, wogegen alles andere verglichen wird.
    """
    try:
        _write_changes([])
    except Exception as e:
        # Nicht fatal: die Liste bleibt stehen, und die UI bietet einen
        # Neustart an, der nichts mehr zu tun hat - falsch, aber harmlos.
        logger.error("BackendRestart: Aenderungsliste konnte nicht geleert werden (%s)" % e)


def _note_change(response):
    """
    after_request-Hook: die Editor-Aufrufe vermerken, die ein Plugin auf der
    Platte aendern.

    Die Anfrage zu beobachten statt die View-Funktionen zu umschliessen ist
    der einzige Weg hinein: ``@blueprint.route`` uebergibt die Funktion an
    das Blueprint, waehrend ``modules/addon/endpoints.py`` importiert wird -
    ein spaeteres Zuschreiben des Modulattributs wuerde von der
    registrierten Route nie erreicht.

    Der Statuscode wird geprueft, damit ein abgelehntes Speichern - ein
    vergebener Name, ein fehlendes Verzeichnis - keine Aenderung behauptet,
    die nicht passiert ist.
    """
    if response.status_code >= 400 or request.endpoint not in CHANGE_ENDPOINTS:
        return response

    name = (request.view_args or {}).get("name")

    if name:
        _record_change(name)

    return response


@blueprint.route('/restart', methods=['GET'])
def status():
    """
    GET /api/restart - ist ein Neustart unterwegs, und wann kommt er?

    Der Client kann hier nachfragen, muss aber nicht: das Socket-Event
    unten traegt dieselbe Information.
    """
    result = _status()
    result["available"] = True
    return flask_json.dumps(result)


@blueprint.route('/restart', methods=['POST'])
def restart():
    """
    POST /api/restart - erst antworten, dann kurz darauf neu starten.

    Body (optionales JSON): ``{"force": true}``, um auch bei laufendem
    Brauschritt neu zu starten, ``{"delay": 5}`` fuer einen anderen
    Countdown als der Standard von 3 s.

    202  der Neustart ist eingeplant
    409  einer ist schon unterwegs, oder ein Brauschritt laeuft und force
         wurde nicht angegeben (der Body sagt dann, welcher der beiden
         Faelle es war)
    500  das Backend konnte sich nicht finden - es wurde nichts neu
         gestartet
    """
    global _pending

    if _pending is not None:
        return flask_json.dumps(_status()), 409

    body = request.get_json(silent=True) or {}

    if not isinstance(body, dict):
        body = {}

    delay = body.get("delay", RESTART_DELAY)

    try:
        delay = int(delay)
    except (TypeError, ValueError):
        delay = RESTART_DELAY

    # Null wuerde die Antwort selbst killen, und ein negatives ist ein
    # Tippfehler und kein Wunsch nach Geschwindigkeit.
    if delay < 1:
        delay = RESTART_DELAY

    if _is_brewing() and not body.get("force"):
        return flask_json.dumps({
            "pending": False,
            "brewing": True,
            "message": "A brew step is running. Restarting would stop the "
                       "controller without turning off the heater. Retry with "
                       "force=true if that is what you want.",
        }), 409

    if _run_script() is None or not sys.executable:
        # Nichts, wohin neu zu starten. Lieber jetzt laut scheitern als ein
        # stilles No-Op hinter einem 202.
        logger.error("BackendRestart: run.py oder Interpreter nicht gefunden")
        return flask_json.dumps({
            "pending": False,
            "message": "BackendRestart cannot find run.py. Not restarting.",
        }), 500

    _pending = {"at": time.time(), "delay": delay}

    logger.info("BackendRestart: Neustart in %ss eingeplant" % delay)
    cbpi.notify(
        "Backend",
        "CraftBeerPi is restarting, back in a few seconds",
        type="info",
    )
    cbpi.emit(SCHEDULE_EVENT, _status())

    cbpi.socketio.start_background_task(target=_execute, delay=delay)

    return flask_json.dumps(_status()), 202


@cbpi.initalizer(order=3000)
def init(cbpi):
    """
    Das Blueprint registrieren.

    Ein plain Blueprint statt einer flask_classy-View: es gibt hier nichts
    zu ueberschreiben und kein Model zu binden. order=3000 legt die
    Registrierung hinter alle Views des Kerns (der letzte steht auf 2000),
    damit ein Client, der /api/restart erreicht, auch ein vollstaendiges
    Backend erreicht - es gibt kein Fenster, in dem sich ein halb
    initialisiertes Backend neu starten wuerde.
    """
    cbpi.app.register_blueprint(blueprint, url_prefix='/api')
    logger.info("BackendRestart: POST /api/restart ist verfuegbar")


@cbpi.initalizer(order=1)
def init_parameters(cbpi):
    """
    Die Config-Parameter anlegen und den Start dieses Backends festhalten.

    order=1 hinter dem Initializer des Config-Moduls (order=0), das ist
    der, der den Cache fuellt, in dem beide Parameter liegen. Der Stempel
    ist das, was eine Aenderung von vor einem Reboot aufhoeren laesst,
    keinen Neustart mehr vorzuschlagen.
    """
    try:
        if not _ensure_parameters():
            logger.warning("BackendRestart: Config-Cache nicht bereit, keine Aenderungserfassung")
            return

        cbpi.set_config_parameter(CONFIG_STARTED, repr(time.time()))
    except Exception as e:
        logger.error("BackendRestart: Aenderungserfassung nicht eingerichtet (%s)" % e)


@cbpi.initalizer(order=1)
def init_tracking(cbpi):
    """
    Die Editor-Endpunkte beobachten, die ein Plugin auf der Platte aendern.

    Aus einem Initializer registriert und nicht beim Import, damit es
    genau einmal da ist und nachdem das App-Objekt existiert.
    """
    cbpi.app.after_request(_note_change)
    logger.info("BackendRestart: Plugin-Aenderungen werden erfasst")
