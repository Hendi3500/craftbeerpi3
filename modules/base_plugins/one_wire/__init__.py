# -*- coding: utf-8 -*-
import os
from subprocess import Popen, PIPE, call

from modules import cbpi, app
from modules.core.hardware import SensorPassive
import json
import os, re, threading, time
from flask import Blueprint, render_template, request
from modules.core.props import Property

blueprint = Blueprint('one_wire', __name__)

temp = 22

def getSensors():
    try:
        arr = []
        for dirname in os.listdir('/sys/bus/w1/devices'):
            if (dirname.startswith("28") or dirname.startswith("10")):
                cbpi.app.logger.info("Device %s Found (Family: 28/10, Thermometer on GPIO4 (w1))" % dirname)
                arr.append(dirname)
        return arr
    except:
        return []




class myThread (threading.Thread):

    value = 0


    def __init__(self, sensor_name):
        threading.Thread.__init__(self)
        self.value = 0
        self.sensor_name = sensor_name
        self.runnig = True
        # Daemon-Thread: sonst laeuft der Prozess beim Beenden nicht
        # sauber weg, weil der Thread noch in der Schleife haengt.
        self.daemon = True

    def shutdown(self):
        pass

    def stop(self):
        self.runnig = False

    def run(self):

        while self.runnig:
            try:
                app.logger.info("READ TEMP")
                ## Test Mode
                if self.sensor_name is None:
                    return
                with open('/sys/bus/w1/devices/w1_bus_master1/%s/w1_slave' % self.sensor_name, 'r') as content_file:
                    content = content_file.read()
                    if (content.split('\n')[0].split(' ')[11] == "YES"):
                        temp = float(content.split("=")[-1]) / 1000  # temp in Celcius
                        self.value = temp
            except Exception as e:
                # Kein blankes except: ein Sensor, der nicht gelesen werden
                # kann, ist ein Fehlerfall und kein Grund, alles zu
                # verschlucken. Der Log ist bei jedem Zyklus laut, deshalb
                # wird der Fehler nur einmal gemeldet.
                if not getattr(self, "_gemeldet", False):
                    self._gemeldet = True
                    app.logger.error("1-Wire: Sensor %s nicht lesbar: %s"
                                     % (self.sensor_name, e))

            # time.sleep() statt socketio.sleep(): dieser Thread ist ein
            # reiner OS-Thread, kein Socket.IO-Backgroundtask.
            time.sleep(4)



@cbpi.sensor
class ONE_WIRE_SENSOR(SensorPassive):

    sensor_name = Property.Select("Sensor", getSensors(), description="The OneWire sensor address.")
    offset = Property.Number("Offset", True, 0, description="Offset which is added to the received sensor data. Positive and negative values are both allowed.")

    def init(self):

        self.t = myThread(self.sensor_name)

        def shudown():
            shudown.cb.shutdown()
        shudown.cb = self.t

        self.t.start()

    def stop(self):
        try:
            self.t.stop()
        except:
            pass

    def read(self):
        if self.get_config_parameter("unit", "C") == "C":
            self.data_received(round(self.t.value + self.offset_value(), 2))
        else:
            self.data_received(round(9.0 / 5.0 * self.t.value + 32 + self.offset_value(), 2))

    @cbpi.try_catch(0)
    def offset_value(self):
        # Fehlt "offset" in der Konfiguration, ist self.offset die
        # Property-Instanz aus der Klassendefinition und keine Zahl.
        # float() darauf wirft TypeError, und der try_catch lieferte
        # stillschweigend 0 - der eingestellte Offset wurde also
        # ignoriert und der Log lief alle fuenf Sekunden voll.
        #
        # Der Wert kann auch ein String sein (aus einem Formular), deshalb
        # wird nicht auf den Typ geprueft, sondern der Parse-Versuch als
        # Kriterium genommen.
        wert = self.offset
        try:
            return float(wert)
        except (TypeError, ValueError):
            return 0.0
            
    @classmethod
    def init_global(self):
        try:
            call(["modprobe", "w1-gpio"])
            call(["modprobe", "w1-therm"])
        except Exception as e:
            pass


@blueprint.route('/<int:t>', methods=['GET'])
def set_temp(t):
    global temp
    temp = t
    return ('', 204)


@cbpi.initalizer()
def init(cbpi):

    cbpi.app.register_blueprint(blueprint, url_prefix='/api/one_wire')
