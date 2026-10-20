# -*- coding: utf-8 -*-
"""
Telegram-Push fuer CraftBeerPi 3.0.

Leitet jede Meldung des Brauers an einen Telegram-Chat weiter.

Vorlage
-------
https://github.com/ShintoTuna/cbpi-telegram (Nikita Shatunov), ueber die
offizielle Plugin-Liste als ``TelegramPushNotifications`` gefuehrt.

Was an der Vorlage geaendert wurde und warum
---------------------------------------------
1. **Python 2.** Die Vorlage importiert ``thread`` - in Python 3 gibt es
   das Modul nicht mehr, der Import schlaegt fehl und das Plugin wird
   gar nicht geladen. Der Import war ohnehin unbenutzt.
2. **Die Konfiguration wurde nur beim Start gelesen.** Die Vorlage las
   Token und Chat-ID einmal in ``init()`` und benutzte sie danach aus
   den globalen Variablen. Eine Aenderung in der Oberflaeche wurde erst
   nach einem Neustart wirksam - das Readme raeumt das auch ein ("may
   require a system reboot"). Jetzt werden die Werte bei jeder Nachricht
   gelesen; die Oberflaeche schreibt sie direkt in den Config-Cache,
   eine Aenderung wirkt sofort.
3. **Die Parameter wurden mit einem nackten ``except`` angelegt.**
   ``add_config_parameter`` wirft, wenn der Parameter schon existiert -
   das war der Normalfall, nicht die Ausnahme. Jeder Start holte damit
   eine Fehlermeldung auf dem Bildschirm, die nichts zu sagen hatte.
   Jetzt wird der Cache geprueft (wie im Restart-Plugin), und ein
   wirklich unerwarteter Fehler wird geloggt.
4. **Der Text wurde nicht escaped.** Die Vorlage schickte die Meldung
   als HTML, ohne die Sonderzeichen zu maskieren. Ein ``<``, ``>`` oder
   ``&`` in der Meldung - bei einer Temperatur zum Beispiel "Heater
   < 50 %" - laesst Telegram die Nachricht mit "can't parse entities"
   ablehnen. Die Meldung kommt dann nie an. Der Text wird jetzt
   escaped, die Formatierung (fett/kursiv) bleibt.
5. **Kein Timeout, keine Fehlerbehandlung.** ``requests.get()`` ohne
   Timeout haengt, wenn Telegram nicht antwortet, und wirft bei einem
   Netzwerkfehler eine Exception mitten in der Ereignisbehandlung. Die
   Anfrage hat jetzt ein Timeout, und Fehler werden geloggt statt
   geworfen - eine kaputte Telegram-Anbindung darf den Brauvorgang
   nicht mitnehmen.
6. **Der Bot-Token stand in der URL, die protokolliert wurde.** Bei
   einem Netzwerkfehler steht die vollstaendige URL in der
   Ausnahmetext - der Token landet damit im Log. Im Log steht jetzt
   nur der Fehlertyp, und jeder Text wird gegen den Token geprueft.
7. **Mehrere Empfaenger.** Die Chat-ID darf kommasepariert angegeben
   werden, dann bekommen mehrere Geraete (Handy, Tablet,Partnerin)
   dieselben Meldungen. Eine einzelne ID funktioniert wie vorher.
8. **Laengenbegrenzung.** Telegram nimmt hoechstens 4096 Zeichen pro
   Nachricht an; ein längerer Text wird abgeschnitten.
9. **"Too Many Requests".** Telegram antwortet bei vielen Meldungen
   kurzzeitig mit 429. Das Plugin wartet dann die von Telegram
   genannte Zeit und versucht es ein zweites Mal.
10. **Eine Startnachricht.** Nach dem Start bekommt der Chat eine
    kurze Meldung. Damit sieht der Brauer sofort, ob die Anbindung
    funktioniert - vorher musste er auf die erste Meldung des
    Brauvorgangs warten, um es zu erfahren. Abschaltbar ueber den
    Parameter ``telegram_startup_message``.
11. **Jede Meldung piepte am Handy.** Jede Meldung kam als Push an -
    das Handy hat bei jedem Zwischenstand geklingelt, auch bei den
    kurzen Meldungen, die nach fuenf Sekunden wieder verschwinden.
    Der Ton gehoert aber nur zu den Meldungen, die keinen Ablauf-
    Timer haben: die bleiben liegen, bis sie weggeklickt werden, und
    die muss der Brauer auch auf dem Handy bemerken. Die Telegram-
    API kann das - ``sendMessage`` kennt den Schalter
    ``disable_notification`` ("Sends the message silently. Users will
    receive a notification with no sound."). Meldungen mit Timer
    werden damit stumm geschickt, die ohne Timer mit Ton.

Einrichtung
-----------
1. Bei Telegram ``@BotFather`` suchen, ``/newbot`` schicken und den
   Anweisungen folgen. Der Bot-Token steht in der Antwort.
2. Den eigenen Bot in Telegram oeffnen und ``/start`` schicken (der Bot
   muss eine Nachricht vom Chat bekommen, sonst kennt er die Chat-ID
   nicht).
3. Die Chat-ID ermitteln: ``https://api.telegram.org/bot<token>/getUpdates``
   im Browser oeffnen. In der Antwort steht unter ``message.from.id`` die
   Chat-ID. Alternative: die Nachricht aus dem Chat an den Bot schicken
   und in ``getUpdates`` nach ``chat.id`` schauen.
4. In CraftBeerPi unter *System -> Parameter* eintragen:

   * ``telegram_bot_token``  - der Token von BotFather
   * ``telegram_chat_id``    - die Chat-ID, mehrere kommasepariert

5. Backend neu starten. Die Startnachricht kommt an.
"""

import html
import logging
import time

import requests

from modules import cbpi


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

# Die Telegram-API. Der Token gehoert in die URL - so ist es von
# Telegram vorgegeben.
API = "https://api.telegram.org"

# Die Config-Parameter, die das Plugin in den Einstellungen anlegt.
PARAM_TOKEN = "telegram_bot_token"
PARAM_CHAT = "telegram_chat_id"
PARAM_STARTUP = "telegram_startup_message"

# Telegram nimmt hoechstens 4096 Zeichen pro Nachricht an.
MAX_LAENGE = 4096

# Timeout fuer die Anfrage. Ohne Timeout haengt der Request, wenn
# Telegram nicht antwortet - und der Thread der Ereignisbehandlung
# laeuft dann ewig.
TIMEOUT = 10

# Hoechstes Warten, wenn Telegram "Too Many Requests" sagt.
MAX_WARTEZEIT = 15

logger = logging.getLogger(__name__)


def _log(level, text):
    """
    In das Applikations-Log schreiben.

    Das Plugin-Log ist nach dem Start nicht mehr im Log zu sehen
    (es laeuft vor ``logging.basicConfig``), deshalb wird der Logger
    des Backends benutzt - mit dem Fallback auf das Modul-Log, falls
    es den noch nicht gibt.
    """
    try:
        cbpi.app.logger.log(logging.ERROR if level == "error" else logging.INFO, text)
    except Exception:
        logger.log(logging.ERROR if level == "error" else logging.INFO, text)


def _ohne_token(text, token):
    """
    Den Bot-Token aus einem Text entfernen.

    Der Token steht in der URL, und die URL landet in der
    Ausnahmetext von ``requests`` ("Max retries exceeded with url:
    /bot12345:ABC/sendMessage"). Ohne diese Maskierung steht das
    Bot-Passwort im Log.
    """
    if not token:
        return text
    return str(text).replace(token, "***")


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

def _parameter_anlegen():
    """
    Die Config-Parameter anlegen, falls sie noch nicht da sind.

    ``add_config_parameter`` wirft, wenn der Parameter schon existiert -
    das war der Normalfall und nicht die Ausnahme (die Vorlage fing das
    mit einem nackten ``except`` ab und meldete dann "Unable to update
    database"). Geprueft wird deshalb der Cache: der enthaelt genau
    die Parameter, die es wirklich gibt.

    Der Cache ist zu diesem Zeitpunkt gefuellt - das Config-Modul
    laeuft mit order 0, dieses Plugin mit order 9000.
    """
    vorhanden = cbpi.cache.get("config") or {}

    for name, wert, typ, beschreibung in (
        (PARAM_TOKEN, "", "text",
         "Telegram Bot Token (von @BotFather)"),
        (PARAM_CHAT, "", "text",
         "Telegram Chat ID - mehrere durch Komma trennen"),
        (PARAM_STARTUP, "NO", "yesno",
         "Beim Start des Backends eine Testnachricht an Telegram schicken"),
    ):
        if name in vorhanden:
            continue
        try:
            cbpi.add_config_parameter(name, wert, typ, beschreibung)
        except Exception as e:
            _log("error", "Telegram: Parameter %s konnte nicht angelegt werden: %s"
                 % (name, e))


def _einstellungen():
    """
    Token und Chat-IDs aus der Konfiguration lesen.

    Bewusst bei jeder Nachricht und nicht nur beim Start: die
    Oberflaeche schreibt die Parameter direkt in den Config-Cache,
    und der Brauer erwartet, dass eine Aenderung sofort wirkt. Die
    Vorlage las die Werte einmal und brauchte dafuer einen Neustart.

    :return: (Token, Liste der Chat-IDs)
    """
    token = (cbpi.get_config_parameter(PARAM_TOKEN, "") or "").strip()

    roh = (cbpi.get_config_parameter(PARAM_CHAT, "") or "").strip()
    chats = [teil.strip() for teil in roh.split(",") if teil.strip()]

    return token, chats


# ---------------------------------------------------------------------------
# Nachricht senden
# ---------------------------------------------------------------------------

def _formatiere(message):
    """
    Die Meldung in Telegram-Markdown uebertragen.

    Telegram kennt nur ein kleines Set an Tags; alles andere wird als
    Text behandelt. Deshalb wird der Text escaped - sonst lehnt
    Telegram die Nachricht ab, sobald sie ein ``<``, ``>`` oder ``&``
    enthaelt ("can't parse entities"), und die Meldung kommt nie an.
    """
    headline = str(message.get("headline") or "").strip()
    text = str(message.get("message") or "").strip()

    if headline and text:
        return "<b>%s</b>\n<i>%s</i>" % (html.escape(headline), html.escape(text))
    if headline:
        return "<b>%s</b>" % html.escape(headline)
    return html.escape(text)


def _mit_ton(message):
    """
    Entscheidet, ob die Meldung am Handy klingeln darf.

    Der Kern gibt jeder Meldung einen ``timeout`` mit:

    * ``None`` - die Meldung bleibt liegen, bis sie weggeklickt wird.
      Sie ist wichtig genug, um den Brauer auch auf dem Handy zu
      wecken: Ton an.
    * eine Zahl (in der Regel 5000) - die Meldung verschwindet nach
      ein paar Sekunden wieder. Sie ist ein Zwischenstand, kein
      Ereignis: kein Ton.

    Deshalb piept das Handy nur bei den Meldungen ohne Ablauf-Timer.
    """
    if not isinstance(message, dict):
        # Kein Dict, kein Timeout - lieber mit Ton. Eine Meldung ohne
        # Angabe ist eher eine bleibende.
        return True

    return message.get("timeout") is None


def _wartezeit(antwort):
    """
    Die Wartezeit aus einer 429-Antwort von Telegram holen.

    Telegram antwortet mit ``{"ok": false, "error_code": 429,
    "parameters": {"retry_after": 12}}``. Fehlt das Feld, wird ein
    kleiner Wert genommen.
    """
    try:
        daten = antwort.json()
        return int(daten.get("parameters", {}).get("retry_after", 5))
    except Exception:
        return 5


def _sende(token, chat, text, mit_ton=True):
    """
    Eine Nachricht an einen Chat schicken.

    :param mit_ton: True heisst, die Nachricht darf am Handy klingeln.
        False heisst: stumm - der Push kommt ohne Ton. Das ist der
        Schalter ``disable_notification`` der Telegram-API.

    :return: True, wenn Telegram die Nachricht angenommen hat.
    """
    url = "%s/bot%s/sendMessage" % (API, token)
    daten = {
        "chat_id": chat,
        "text": text[:MAX_LAENGE],
        "parse_mode": "HTML",
        # Telegram erwartet hier "true"/"false" als Text. Ein Python-
        # True wuerde als "True" in der Anfrage landen und von Telegram
        # nicht als boolescher Wert erkannt.
        "disable_notification": "false" if mit_ton else "true",
    }

    for versuch in range(2):
        try:
            antwort = requests.post(url, data=daten, timeout=TIMEOUT)
        except requests.RequestException as e:
            # Nur der Typ des Fehlers - der Text von requests enthaelt
            # die vollstaendige URL und damit den Bot-Token.
            _log("error", "Telegram: Anfrage fehlgeschlagen (%s)" % type(e).__name__)
            return False
        except Exception as e:
            _log("error", "Telegram: unerwarteter Fehler: %s" % type(e).__name__)
            return False

        if antwort.status_code == 429:
            # Telegram ist voll (zu viele Nachrichten in der Zeit).
            # Kurz warten und einmal versuchen.
            if versuch == 0:
                wartezeit = min(_wartezeit(antwort), MAX_WARTEZEIT)
                _log("info", "Telegram: zu viele Nachrichten - warte %ss" % wartezeit)
                time.sleep(wartezeit)
                continue
            return False

        if antwort.status_code != 200:
            _log("error", "Telegram: HTTP %s - %s"
                 % (antwort.status_code, _ohne_token(antwort.text[:200], token)))
            return False

        return True

    return False


def _sende_an_alle(token, chats, text, mit_ton=True):
    """
    Eine Nachricht an alle Empfaenger schicken.

    Fehler werden geloggt, nicht gemeldet: eine Meldung des Plugins
    waere selbst eine Meldung, die weitergeleitet wird - und der
    Kreislauf waere nicht zu Ende.
    """
    for chat in chats:
        if not _sende(token, chat, text, mit_ton=mit_ton):
            _log("error", "Telegram: Nachricht an Chat %s nicht zugestellt" % chat)


# ---------------------------------------------------------------------------
# Anbindung an den Kern
# ---------------------------------------------------------------------------

@cbpi.event("MESSAGE", async_=True)
def message_event(message):
    """
    Jede Meldung des Brauers an Telegram weitergeben.

    Das Event laeuft als Hintergrundtask - ein blockierender HTTP-Aufruf
    wuerde sonst den Aufrufer festhalten.
    """
    try:
        token, chats = _einstellungen()
    except Exception as e:
        _log("error", "Telegram: Konfiguration nicht lesbar: %s" % type(e).__name__)
        return

    if not token or not chats:
        # Ohne Token oder ohne Chat-ID gibt es niemanden, dem man etwas
        # schicken koennte. Das ist kein Fehler, sondern eine noch
        # nicht fertige Einrichtung - der Start meldet es.
        return

    try:
        text = _formatiere(message)
    except Exception as e:
        _log("error", "Telegram: Meldung nicht formatierbar: %s" % type(e).__name__)
        return

    # Nur die Meldungen ohne Ablauf-Timer duerfen am Handy klingeln.
    _sende_an_alle(token, chats, text, mit_ton=_mit_ton(message))


@cbpi.initalizer(order=9000)
def init(cbpi):
    """
    Das Plugin beim Start einrichten.

    Order 9000: die Config-Parameter sind zu diesem Zeitpunkt angelegt
    (das Config-Modul laeuft mit order 0), und die Meldungen des
    Notification-Moduls laufen bereits.
    """
    _parameter_anlegen()

    token, chats = _einstellungen()

    if not token:
        cbpi.notify("Telegram",
                    "Kein Bot-Token gesetzt - es werden keine Nachrichten "
                    "an Telegram geschickt. Token und Chat-ID unter "
                    "System -> Parameter eintragen.",
                    type="warning", timeout=None)
        return

    if not chats:
        cbpi.notify("Telegram",
                    "Keine Chat-ID gesetzt - es werden keine Nachrichten "
                    "an Telegram geschickt. Token und Chat-ID unter "
                    "System -> Parameter eintragen.",
                    type="warning", timeout=None)
        return

    _log("info", "Telegram: Plugin bereit (%d Empfaenger)" % len(chats))

    if (cbpi.get_config_parameter(PARAM_STARTUP, "YES") or "YES") == "YES":
        # Die Startnachricht geht in den Hintergrund: eine Telegram, die
        # nicht antwortet, darf den Start des Backends nicht aufhalten.
        cbpi.socketio.start_background_task(
            target=_startnachricht,
            token=token,
            chats=chats,
        )


def _startnachricht(token, chats):
    """
    Die Testnachricht nach dem Start schicken.

    Sie beantwortet die Frage "funktioniert die Anbindung?" ohne
    Warten auf die erste Meldung des Brauvorgangs.

    Die Nachricht klingelt am Handy - sie hat keinen Ablauf-Timer und
    der Brauer hat sie sich ausdruecklich gewuenscht (Parameter
    ``telegram_startup_message``). Wer sie nicht hoeren will, stellt
    den Parameter auf ``NO``.
    """
    text = ("<b>Telegram-Anbindung aktiv</b>\n"
            "<i>CraftBeerPi laeuft. Ab jetzt kommen alle Meldungen hier.</i>")
    _sende_an_alle(token, chats, text, mit_ton=True)
