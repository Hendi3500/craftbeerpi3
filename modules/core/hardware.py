# -*- coding: utf-8 -*-

from modules.core.props import apply_property_defaults


class Base(object):
    __dirty = False

    @classmethod
    def init_global(cls):
        pass

    def get_config_parameter(self, key, default_value):
        return self.api.get_config_parameter(key, default_value)

    def sleep(self, seconds):
        self.api.socketio.sleep(seconds)

    def init(self):
        pass

    def stop(self):
        pass

    def update(self, **kwds):
        pass

    def __init__(self, *args, **kwds):
        for a in kwds:
            super(Base, self).__setattr__(a, kwds.get(a))
        self.api = kwds.get("api")
        self.id = kwds.get("id")
        self.value = None
        self.__dirty = False

        # Konfigurationsfelder, die die Konfiguration nicht liefert,
        # bekommen ihren Vorgabewert. Ein Sensor ohne Topic ist dann
        # wenigstens ein leerer Topic und kein Property-Objekt.
        # Siehe modules.core.props.apply_property_defaults.
        apply_property_defaults(self, kwds)

    def __setattr__(self, name, value):

        if name != "_Base__dirty":
            self.__dirty = True
            super(Base, self).__setattr__(name, value)
        else:
            super(Base, self).__setattr__(name, value)


class SensorBase(Base):

    last_value = 0

    def init(self):
        pass

    def stop(self):
        pass

    def data_received(self, data):
        self.last_value = data
        self.api.receive_sensor_value(self.id, data)

    def get_unit(self):
        if self.get_config_parameter("unit", "C") == "C":
            return "°C"
        else:
            return "°F"

    def get_value(self):

        return {"value": self.last_value, "unit": self.get_unit()}

class SensorActive(SensorBase):

    __running = False

    def is_running(self):

        return self.__running

    def init(self):
        self.__running = True

    def stop(self):
        self.__running = False

    def execute(self):
        pass


class SensorPassive(SensorBase):
    def init(self):
        pass

    def read(self):
        return 0


class ActorBase(Base):

    def state(self):
        return 1

    def set_power(self, power):
        pass

    def on(self, power=0):
        pass

    def off(self):
        pass
