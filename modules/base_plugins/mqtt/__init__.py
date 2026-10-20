# -*- coding: utf-8 -*-
"""
MQTT Plugin fuer CraftBeerPi 3.0

Verbindet sich mit einem MQTT-Broker, um Sensordaten zu empfangen und
Actoren zu schalten.

Portierung auf Python 3 / paho-mqtt 2.x
-----------------------------------------
Gegenueber der Python-2-Fassung (2018) geaendert:

* print-Statements und ``basestring`` entfernt.
* ``eventlet`` durch die Standardbibliothek ``queue`` ersetzt. Das Projekt
  laeuft mit ``async_mode="threading"``, eventlet ist nicht installiert und
  war auch nie eine Abhaengigkeit des Projekts.
* paho-mqtt 2.x: der Client verlangt ein explizites ``CallbackAPIVersion``.
  Fuer paho 1.x bleibt eine Fallback-Variante erhalten.
* Verbindungsaufbau ueber ``connect_async()`` + ``loop_start()`` statt eines
  eigenen Threads mit ``loop_forever()``. paho baut die Verbindung damit
  selbst auf und stellt sie nach einem Broker-Neustart automatisch wieder her.
* Der Client wird nicht mehr im Thread erzeugt. Vorher war er waehrend des
  Verbindungsaufbaus ``None``; Actoren, die in diesem Fenster schalteten,
  bekamen einen ``AttributeError``.
* Abos werden zentral registriert und bei jedem (Re-)Connect erneut gesetzt.
  Vorher wurde in ``MQTT_SENSOR.init()`` blind abonniert - ohne Verbindung
  blieb das Topic dauerhaft stumm.
* Der ``except:`` ohne Typ im Reader-Thread ist weg. Er hat jeden Fehler
  geschluckt, auch fehlende Sensor-IDs, die dann dauerhaft Daten im Queue
  blockiert haben.

Die Topics und die Sensorkonfiguration im Broker aendern sich durch den Port
nicht, bestehende Konfigurationen bleiben gueltig.
"""

import json
import queue
import threading

import paho.mqtt.client as mqtt

from modules import cbpi, ActorBase
from modules.core.hardware import SensorActive
from modules.core.props import Property


# Reader-Queue: die paho-Netzwerkthreads duerfen den Flask-/Socket.IO-Zustand
# nicht direkt anfassen. Deshalb legen die Callbacks hier nur Werte ab und der
# Reader-Thread (im socketio-Kontext gestartet) stoesst sie an den Core weiter.
q = queue.Queue()


def _as_bool(value, default=False):
    """
    Config-Wert als Boolean.

    Wichtig: die Konfigurationsfelder liefern Strings. ``if self.tls:`` waere
    bei "false" immer wahr, weil jeder nicht-leere String truthy ist - TLS
    waere also dauerhaft aktiv und der Broker wuerde nie erreichbar. Deshalb
    wird hier bewusst geparst statt auf Truthiness geprueft.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("true", "1", "yes", "on", "y")


def _as_int(value, default, what="Wert"):
    """
    Eine Zahl aus einer Konfigurationszeile.

    Die Werte kommen aus der Datenbank, also aus einem Textfeld - der
    Brauer tippt " 1883 " mit einem Leerzeichen ein, oder "abc". Ein
    int() darauf wirft ValueError, und der Fehler landete ungeschuetzt
    im Initialisierer: der Import von ``modules`` brach ab, CraftBeerPi
    startete gar nicht mehr - kein Webinterface, keine Brausteuerung.
    Ein Addon darf den Start der Kern-App nicht killen.

    Ein unbrauchbarer Wert wird gemeldet und durch den Vorgabewert
    ersetzt. Der Brauer sieht die Meldung im Log und kann die
    Konfiguration korrigieren, das Backend laeuft trotzdem.
    """
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        _log().error(
            "MQTT: %s ist keine Zahl (%r) - benutze %s stattdessen"
            % (what, value, default))
        return default


def _log():
    """In das Applikations-Log schreiben, mit Fallback auf das Modul-Log."""
    try:
        return cbpi.app.logger
    except Exception:
        import logging
        return logging.getLogger(__name__)


class MQTTBroker:
    """
    Verwaltet genau eine MQTT-Verbindung fuer alle Actoren und Sensoren.

    Thread-sicher. Alle oeffentlichen Methoden duerfen aus den Threads der
    Actoren und Sensoren aufgerufen werden.
    """

    def __init__(self, server, port, username, password, tls,
                 ca_cert="", cert="", key="", keepalive=60):
        self.server = server
        # Die Portzahl kann aus der Datenbank kommen, also aus einem
        # Textfeld. Ein "abc" oder " 1883" darf den Start nicht killen -
        # siehe die Fehlerbehandlung in initMQTT.
        self.port = _as_int(port, 1883, "MQTT Port")
        self.username = username
        self.password = password
        self.tls = _as_bool(tls)
        self.ca_cert = ca_cert
        self.cert = cert
        self.key = key
        self.keepalive = _as_int(keepalive, 60, "MQTT Keepalive")

        self._lock = threading.RLock()
        self._connected = threading.Event()
        # topic -> Liste der Callbacks. Ein Topic kann von mehreren Sensoren
        # genutzt werden; jeder Sensor registriert seinen eigenen Callback.
        self._topics = {}

        self._client = self._create_client()

    # ------------------------------------------------------------------
    # Client-Aufbau
    # ------------------------------------------------------------------
    def _create_client(self):
        """Client erzeugen und konfigurieren. Muss vor start() passieren."""
        if hasattr(mqtt, "CallbackAPIVersion"):
            # paho-mqtt 2.x
            self._api_v2 = True
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            # on_connect-Signatur V2: (client, userdata, flags, reason_code, properties)
            client.on_connect = self._on_connect_v2
            client.on_disconnect = self._on_disconnect_v2
        else:
            # paho-mqtt 1.x
            self._api_v2 = False
            client = mqtt.Client()
            client.on_connect = self._on_connect_v1
            client.on_disconnect = self._on_disconnect_v1

        # on_message ist in paho 1.x und 2.x gleich signiert:
        # (client, userdata, msg)
        client.on_message = self._dispatch

        # Die Sentinel-Werte "username"/"password" stammen aus der
        # Python-2-Fassung: das sind die Platzhalter, die der Konfigurations-
        # dialog anlegt, wenn noch keine Zugangsdaten eingetragen sind.
        # Leere Werte behandeln wir genauso, damit man die Felder auch
        # einfach leer lassen kann.
        if self.username and self.password \
                and self.username != "username" and self.password != "password":
            client.username_pw_set(self.username, self.password)

        if self.tls:
            client.tls_set(ca_certs=self.ca_cert or None,
                           certfile=self.cert or None,
                           keyfile=self.key or None)
            # Zertifikatspruefung bleibt aktiv - "insecure" wuerde TLS auf
            # eine reine Verschluesselung ohne Authentizitaet herabstufen.
            client.tls_insecure_set(False)

        return client

    def start(self):
        """
        Verbindung starten. Blockiert nicht.

        ``connect_async`` + ``loop_start`` laesst paho den Verbindungsaufbau
        und die Reconnects im Hintergrund erledigen. Die alte Fassung hat
        ``connect()`` in einem eigenen Thread aufgerufen und ist bei jedem
        Broker-Neustart dauerhaft gescheitert.
        """
        _log().info("MQTT: verbinde mit %s:%s" % (self.server, self.port))
        try:
            self._client.connect_async(self.server, self.port, self.keepalive)
            self._client.loop_start()
        except Exception as e:
            _log().error("MQTT: Verbindungsaufbau fehlgeschlagen: %s" % e)
            return False
        return True

    def stop(self):
        try:
            self._client.disconnect()
            self._client.loop_stop()
        except Exception as e:
            _log().error("MQTT: Fehler beim Beenden: %s" % e)
        finally:
            self._connected.clear()

    # ------------------------------------------------------------------
    # Verbindungs-Callbacks
    # ------------------------------------------------------------------
    @staticmethod
    def _rc_value(reason_code):
        """
        Return code als int.

        paho-mqtt 1.x liefert hier ein int. paho-mqtt 2.x liefert ein
        ReasonCode-Objekt, das zwar __eq__ gegen eine int implementiert, aber
        kein __int__ - ein int(...) darauf wirft TypeError. Genau das ist
        passiert, bevor dieser Helper existierte: die Ausnahme wurde mitten
        im Netzwerkthread geworfen und von paho verschluckt, die Verbindung
        sah danach nie nach verbunden aus.
        """
        if reason_code is None:
            return 1
        if hasattr(reason_code, "value"):
            return int(reason_code.value)
        try:
            return int(reason_code)
        except (TypeError, ValueError):
            return 1

    def _on_connect_v1(self, client, userdata, flags, rc):
        self._guard(self._handle_connect, self._rc_value(rc))

    def _on_connect_v2(self, client, userdata, flags, reason_code, properties=None):
        self._guard(self._handle_connect, self._rc_value(reason_code))

    def _on_disconnect_v1(self, client, userdata, rc):
        self._guard(self._handle_disconnect, self._rc_value(rc))

    def _on_disconnect_v2(self, client, userdata, disconnect_flags,
                          reason_code, properties=None):
        self._guard(self._handle_disconnect, self._rc_value(reason_code))

    def _guard(self, func, *args):
        """
        Laesst keine Ausnahme aus einem paho-Callback nach aussen.

        paho ruft diese Callbacks im Netzwerkthread auf und faengt dort
        auftretende Fehler nicht ab - ein Fehler wuerde den Thread beenden
        und die MQTT-Verbindung bliebe ohne jede Logzeile tot stehen.
        """
        try:
            func(*args)
        except Exception as e:
            _log().error("MQTT: Fehler in %s: %s" % (func.__name__, e))

    def _handle_connect(self, rc):
        if rc != 0:
            self._connected.clear()
            _log().error("MQTT: Verbindung abgelehnt (Code %s)" % rc)
            return

        # Snapshot und connected-Flag unter derselben Sperre setzen. Sonst
        # kann sich ein add_subscription dazwischenschieben und das Topic
        # sowohl hier als auch dort abonniert werden.
        with self._lock:
            topics = list(self._topics.keys())
            self._connected.set()

        _log().info("MQTT: verbunden, %d Topic(s) werden abonniert" % len(topics))

        # Alle registrierten Topics erneut abonnieren. Nach einem Reconnect
        # sind die Abos des Brokers verloren, das war ein stiller Datenverlust.
        for topic in topics:
            self._subscribe_now(topic)

    def _handle_disconnect(self, rc):
        self._connected.clear()
        if rc != 0:
            _log().warning("MQTT: Verbindung unterbrochen (Code %s), Reconnect läuft" % rc)

    def is_connected(self):
        return self._connected.is_set()

    def __json__(self):
        """
        Darstellung fuer /api/system/dump, das den kompletten cbpi.cache
        als JSON ausgibt. Der Endpunkt wird vom Frontend beim Start
        geladen - ohne diesen Hook wuerde jeder Request darauf mit 500
        fehlschlagen, sobald das Plugin den Broker im Cache ablegt.
        """
        return {
            "server": self.server,
            "port": self.port,
            "tls": self.tls,
            "authenticated": bool(self.username and self.password),
            "connected": self.is_connected(),
            "topics": sorted(self._topics.keys()),
        }

    def wait_connected(self, timeout=10):
        return self._connected.wait(timeout)

    # ------------------------------------------------------------------
    # Publish / Subscribe
    # ------------------------------------------------------------------
    def publish(self, topic, payload, qos=2, retain=True, timeout=10):
        """
        Nachricht senden. Gibt True zurueck, wenn der Broker sie angenommen
        hat. Blockiert hoechstens ``timeout`` Sekunden auf die Verbindung.
        """
        if not topic:
            _log().error("MQTT: publish ohne Topic - verwende die Actor-Konfiguration")
            return False

        if not self._connected.is_set():
            # Vorher: AttributeError, weil client noch None war.
            if not self.wait_connected(timeout):
                _log().error("MQTT: kein Broker (%s:%s), publish auf '%s' verworfen"
                             % (self.server, self.port, topic))
                return False

        try:
            info = self._client.publish(topic, payload, qos=qos, retain=retain)
        except Exception as e:
            _log().error("MQTT: publish auf '%s' fehlgeschlagen: %s" % (topic, e))
            return False

        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            _log().error("MQTT: publish auf '%s' nicht moeglich (rc=%s)"
                         % (topic, info.rc))
            return False
        return True

    def add_subscription(self, topic, callback):
        """
        Callback fuer ein Topic registrieren. Darf vor und nach dem
        Verbindungsaufbau aufgerufen werden.
        """
        if not topic:
            _log().error("MQTT: Sensor ohne Topic - Subscription uebersprungen")
            return False

        with self._lock:
            self._topics.setdefault(topic, [])
            if callback not in self._topics[topic]:
                self._topics[topic].append(callback)

        if self._connected.is_set():
            self._subscribe_now(topic)
        return True

    def remove_subscription(self, topic, callback=None):
        """
        Callback wieder abmelden. Ohne callback wird das Topic ganz
        abbestellt, sobald kein Sensor mehr darauf zeigt.
        """
        with self._lock:
            callbacks = self._topics.get(topic, [])
            if callback is None:
                self._topics.pop(topic, None)
            else:
                if callback in callbacks:
                    callbacks.remove(callback)
                if not callbacks:
                    self._topics.pop(topic, None)

        if self._connected.is_set() and topic not in self._topics:
            try:
                self._client.unsubscribe(topic)
            except Exception as e:
                _log().error("MQTT: unsubscribe von '%s' fehlgeschlagen: %s" % (topic, e))
        return True

    def _subscribe_now(self, topic):
        try:
            self._client.subscribe(topic, qos=1)
        except Exception as e:
            _log().error("MQTT: subscribe auf '%s' fehlgeschlagen: %s" % (topic, e))

    # ------------------------------------------------------------------
    # Weiterleitung an die Sensoren
    # ------------------------------------------------------------------
    def subscriptions_for(self, topic):
        """Callbacks, die auf diesem Topic lauschen (Kopie der Liste)."""
        with self._lock:
            return list(self._topics.get(topic, []))

    def _dispatch(self, client, userdata, msg):
        """
        Von paho aufgerufen, sobald eine Nachricht eintrifft. Verteilt sie an
        die Sensoren, die sich auf dieses Topic eingetragen haben.

        Bewusst hier und nicht im Initialisierer verdrahtet: ein Broker, der
        ohne on_message dasteht, schluckt Nachrichten sonst kommentarlos.
        Wir verteilen selbst statt paho's message_callback_add zu nutzen - das
        kann in paho 2.x keine Wildcard-Topics, und die Callbacks muessen ohnehin
        zentral verwaltet werden, damit sie sich beim Stop eines Sensors
        sauber abmelden lassen.
        """
        for callback in self.subscriptions_for(msg.topic):
            try:
                callback(client, userdata, msg)
            except Exception as e:
                _log().error("MQTT: Fehler im Callback fuer '%s': %s"
                             % (msg.topic, e))


@cbpi.actor
class MQTTActor(ActorBase):
    topic = Property.Text("Topic", configurable=True, default_value="",
                          description="MQTT TOPIC")

    def on(self, power=100):
        self.api.cache["mqtt"].publish(self.topic,
                                       payload=json.dumps({"state": "on"}),
                                       qos=2, retain=True)

    def off(self):
        self.api.cache["mqtt"].publish(self.topic,
                                       payload=json.dumps({"state": "off"}),
                                       qos=2, retain=True)


@cbpi.actor
class ESPEasyMQTT(ActorBase):
    """
    ESPEasy-kompatibler Actor: schaltet mit rohen Payloads 1/0 statt JSON.
    """
    topic = Property.Text("Topic", configurable=True, default_value="",
                          description="MQTT TOPIC")

    def on(self, power=100):
        self.api.cache["mqtt"].publish(self.topic, payload="1",
                                       qos=2, retain=True)

    def off(self):
        self.api.cache["mqtt"].publish(self.topic, payload="0",
                                       qos=2, retain=True)


@cbpi.sensor
class MQTT_SENSOR(SensorActive):
    a_topic = Property.Text("Topic", configurable=True, default_value="",
                            description="MQTT TOPIC")
    b_payload = Property.Text("Payload Dictionary", configurable=True, default_value="",
                              description="Wo der Wert im Payload steht, leer lassen fuer Rohwert")
    c_unit = Property.Text("Unit", configurable=True, default_value="",
                           description="Units to display")

    last_value = None

    def init(self):
        self.topic = self.a_topic
        if self.b_payload == "":
            self.payload_text = None
        else:
            self.payload_text = [p.strip() for p in self.b_payload.split(".") if p.strip()]
        self.unit = self.c_unit[0:3]
        self.broker = self.api.cache["mqtt"]

        SensorActive.init(self)

        # Der Callback haelt die Sensor-ID direkt fest. Die alte Fassung hatte
        # sie als Funktionsattribut gesetzt, was bei mehreren Sensoren mit
        # identischer on_message-Funktion zu Verwechslungen fuehrte.
        sensor_id = self.id
        payload_path = self.payload_text

        def on_message(client, userdata, msg):
            _handle_message(sensor_id, payload_path, msg.payload)

        self._on_message = on_message
        self.broker.add_subscription(self.topic, on_message)
        _log().info("MQTT: Sensor %s lauscht auf '%s' (Pfad: %s)"
                    % (self.name, self.topic, self.payload_text or "Rohwert"))

    def get_value(self):
        return {"value": self.last_value, "unit": self.unit}

    def get_unit(self):
        return self.unit

    def stop(self):
        try:
            self.api.cache["mqtt"].remove_subscription(self.topic, self._on_message)
        except Exception as e:
            _log().error("MQTT: Sensor %s konnte nicht abgemeldet werden: %s"
                         % (self.name, e))
        SensorActive.stop(self)

    def execute(self):
        '''
        Active sensor has to handle his own loop
        :return:
        '''
        self.sleep(5)


def _handle_message(sensor_id, payload_path, payload):
    """
    MQTT-Nachricht auswerten und den Wert in die Queue legen.

    Frueher: ``print e`` auf jedem Fehler - ein nicht parsebares Payload hat
    das Log flutet und die eigentliche Fehlermeldung war nicht zu sehen.
    """
    try:
        msg = payload.decode("utf-8", errors="replace")
    except AttributeError:
        msg = str(payload)

    try:
        data = json.loads(msg)
    except ValueError:
        data = msg

    if payload_path is not None:
        # Verschachteltes JSON durchlaufen, z. B. "Sensor.Value"
        for key in payload_path:
            if not isinstance(data, dict):
                return
            data = data.get(key, None)
            if data is None:
                return

    if isinstance(data, (int, float, str, bool)):
        try:
            q.put_nowait({"id": sensor_id, "value": data})
        except queue.Full:
            _log().warning("MQTT: Eingangsqueue voll, Wert fuer Sensor %s verworfen" % sensor_id)
    else:
        _log().debug("MQTT: Payload fuer Sensor %s ist kein skalarer Wert (%s)"
                     % (sensor_id, type(data).__name__))


class _BrokerAus(object):
    """
    Ersatz fuer den Broker, wenn er sich nicht starten laesst.

    Steht in ``cbpi.cache["mqtt"]``, damit die Actoren und Sensoren
    weiterhin etwas vorfinden, das sie benutzen koennen. Jede Methode
    meldet einmal, dass es nicht geht, und tut dann nichts.

    Ohne diesen Ersatz wuerde ein Actor beim Schalten einen KeyError
    werfen - der Fehler faellt dann in den Flask-Request-Thread bzw.
    in den Brauschritt-Thread und der Schaltvorgang bricht ab. So
    bleibt der Actor schaltbar (die Schaltung wird nur nicht
    uebertragen) und der Brauer bekommt eine Meldung.
    """

    def __init__(self, ca_cert="", cert="", key=""):
        self._gemeldet = False
        self._topics = {}
        self._lock = threading.RLock()
        self.ca_cert = ca_cert
        self.cert = cert
        self.key = key

    def _melde(self, was):
        if self._gemeldet:
            return
        self._gemeldet = True
        _log().error(
            "MQTT: %s nicht moeglich - der Broker laeuft nicht. Die "
            "MQTT-Konfiguration pruefen." % was)

    def publish(self, topic, payload, qos=2, retain=True, timeout=10):
        self._melde("publish")
        return False

    def is_connected(self):
        return False

    def wait_connected(self, timeout=10):
        return False

    def add_subscription(self, topic, callback):
        with self._lock:
            self._topics.setdefault(topic, []).append(callback)

    def remove_subscription(self, topic, callback=None):
        with self._lock:
            if callback is None:
                self._topics.pop(topic, None)
            elif topic in self._topics:
                if callback in self._topics[topic]:
                    self._topics[topic].remove(callback)

    def subscriptions_for(self, topic):
        with self._lock:
            return list(self._topics.get(topic, []))

    def stop(self):
        pass

    def __json__(self):
        return {"connected": False, "error": "MQTT broker not running"}


@cbpi.initalizer(order=0)
def initMQTT(cbpi_instance):
    """
    Der Parameter heisst historisch so, ist aber die CraftBeerPi-Instanz -
    die Initialisierer werden mit ``self`` der cbpi aufgerufen
    (siehe CraftBeerPi.run_init).
    """

    def config(name, default, description):
        value = cbpi_instance.get_config_parameter(name, None)
        if value is None:
            cbpi_instance.add_config_parameter(name, default, "text", description)
            return default
        return value

    server = config("MQTT_SERVER", "localhost", "MQTT Server")
    port = config("MQTT_PORT", "1883", "MQTT Server Port")
    username = config("MQTT_USERNAME", "", "MQTT username")
    password = config("MQTT_PASSWORD", "", "MQTT password")
    tls = config("MQTT_TLS", "false", "MQTT TLS")
    ca_cert = config("MQTT_CA_CERT", "", "MQTT TLS CA Zertifikat (Pfad)")
    cert = config("MQTT_CERT", "", "MQTT TLS Client Zertifikat (Pfad)")
    key = config("MQTT_KEY", "", "MQTT TLS Client Key (Pfad)")

    # Der Broker darf den Start des Backends nicht verhindern.
    #
    # Vorher stand hier kein try/except. Ein Tippfehler in der
    # Konfiguration - "MQTT_PORT" auf "abc", ein nicht existierender
    # Pfad fuer das TLS-Zertifikat - liess die Ausnahme bis nach oben
    # durch. run_init() (modules/core/core.py) ruft die Initialisierer
    # ohne Fehlerbehandlung auf, und run_init() laeuft beim Import von
    # ``modules``. Folge: der Import brach ab, CraftBeerPi startete gar
    # nicht mehr. Kein Webinterface, keine Brausteuerung, weil ein
    # optionaler MQTT-Broker falsch konfiguriert war.
    #
    # Ein Addon ist ein Zusatz zum Kern, nicht Teil davon. Wenn es nicht
    # laeuft, laeuft der Kern.
    try:
        broker = MQTTBroker(server, port, username, password, tls,
                            ca_cert=ca_cert, cert=cert, key=key)
        broker.start()
        cbpi_instance.cache["mqtt"] = broker
    except Exception as e:
        _log().error(
            "MQTT: Broker konnte nicht gestartet werden (%s: %s) - das "
            "Backend laeuft ohne MQTT weiter. Die Konfiguration der "
            "MQTT-Parameter pruefen."
            % (type(e).__name__, e))
        try:
            cbpi_instance.notify(
                "MQTT",
                "Der MQTT-Broker konnte nicht gestartet werden: %s. "
                "Das Backend laeuft ohne MQTT weiter." % e,
                type="danger",
                timeout=None,
            )
        except Exception:
            # Auch die Benachrichtigung darf den Start nicht verhindern.
            pass
        # Der Cache-Eintrag fehlt damit. Die Actoren und Sensoren
        # greifen darauf zu - sie bekommen einen Broker, der nichts
        # tut, statt einer staendigen Fehlermeldung beim Schalten.
        cbpi_instance.cache["mqtt"] = _BrokerAus(ca_cert, cert, key)

    def mqtt_reader(api):
        """
        Werte aus der Queue an den Core weitergeben. Laeuft als socketio-
        Background-Task, damit Flask/Socket.IO im richtigen Kontext laufen.
        """
        while True:
            try:
                m = q.get(timeout=0.1)
            except queue.Empty:
                continue
            except Exception:
                continue

            try:
                sensor_id = m.get("id")
                if sensor_id is None:
                    continue
                sensor = api.cache.get("sensors").get(sensor_id)
                if sensor is None:
                    _log().debug("MQTT: Sensor %s nicht (mehr) vorhanden, Wert verworfen"
                                 % sensor_id)
                    continue
                if sensor.instance is not None:
                    sensor.instance.last_value = m.get("value")
                api.receive_sensor_value(sensor_id, m.get("value"))
            except Exception as e:
                # Vorher: blankes except. Auch ein KeyError auf der
                # Sensor-Id blieb dadurch unentdeckt.
                _log().error("MQTT: Reader konnte Wert nicht verarbeiten: %s" % e)

    cbpi_instance.socketio.start_background_task(target=mqtt_reader, api=cbpi_instance)
    _log().info("MQTT: Plugin initialisiert")