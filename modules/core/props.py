class PropertyType(object):
    pass


def apply_property_defaults(instance, provided=None):
    """
    Property-Attribute eines Plugins durch echte Werte ersetzen.

    Ein Plugin deklariert seine Konfigurationsfelder als Klassenattribut:

        heater_offset_min = Property.Number("Heater Offset ON", True, 0)

    Der Wert kommt aus der Konfiguration des Kessels bzw. Fermenters.
    Steht dort keiner - die Oberflaeche hat das Feld nicht mitgeschickt,
    weil sie beim Anlegen des Objekts noch gar keine Logik gewaehlt hatte
    -, dann blieb bisher das Property-Objekt selbst als Attribut stehen.
    Der Controller rechnet damit:

        float(self.heater_offset_min)
        -> TypeError: float() argument must be a string or a real
           number, not 'Number'

    Der Controller stirbt damit in der ersten Sekunde, der Automatik-
    Knopf springt auf Handbetrieb zurueck, und im Log steht nur dieser
    eine kryptische TypeError.

    Deshalb bekommt jedes Property-Attribut, fuer das die Konfiguration
    keinen Wert liefert, seinen Vorgabewert - genau den, den auch die
    Oberflaeche beim Anlegen des Objekts eintragen wuerde.

    ``Select`` hat keinen eigenen Vorgabewert. Dort wird der erste
    Eintrag der Liste genommen: das ist der Wert, den die Oberflaeche
    im Auswahlfeld anzeigt, wenn die Konfiguration den Eintrag nicht
    enthaelt. So verhaelt sich der Controller genauso wie das, was der
    Brauer auf dem Bildschirm sieht.

    Werte, die die Konfiguration liefert, bleiben unveraendert - sie
    stehen bereits als Instanzattribut im ``__dict__``.
    """
    if provided is None:
        provided = {}

    for klasse in type(instance).__mro__:
        for name, wert in vars(klasse).items():
            if not isinstance(wert, PropertyType):
                continue
            if name in instance.__dict__:
                # Die Konfiguration hat den Wert geliefert - der steht
                # bereits als Instanzattribut drin und bleibt unangetastet.
                continue

            if name in provided:
                try:
                    setattr(instance, name, provided[name])
                except Exception:
                    pass
                continue

            vorgabe = getattr(wert, "default_value", None)

            if vorgabe is None and isinstance(wert, Property.Select) \
                    and getattr(wert, "options", None):
                vorgabe = wert.options[0]

            try:
                setattr(instance, name, vorgabe)
            except Exception:
                # Ein Attribut, das sich nicht setzen laesst, darf den
                # Start des Controllers nicht verhindern.
                pass


class Property(object):
    class Select(PropertyType):
        def __init__(self, label, options, description=""):
            PropertyType.__init__(self)
            self.label = label
            self.options = options
            self.description = description

    class Number(PropertyType):
        def __init__(self, label, configurable=False, default_value=None, unit="", description=""):
            PropertyType.__init__(self)
            self.label = label
            self.configurable = configurable
            self.default_value = default_value
            self.description = description

    class Text(PropertyType):
        def __init__(self, label, configurable=False, default_value="", description=""):
            PropertyType.__init__(self)
            self.label = label
            self.configurable = configurable
            self.default_value = default_value
            self.description = description

    class Actor(PropertyType):
        def __init__(self, label, description=""):
            PropertyType.__init__(self)
            self.label = label
            self.configurable = True
            self.description = description

    class Sensor(PropertyType):
        def __init__(self, label, description=""):
            PropertyType.__init__(self)
            self.label = label
            self.configurable = True
            self.description = description

    class Kettle(PropertyType):
        def __init__(self, label, description=""):
            PropertyType.__init__(self)
            self.label = label
            self.configurable = True
            self.description = description


class StepProperty(Property):
    class Actor(PropertyType):
        def __init__(self, label, description=""):
            PropertyType.__init__(self)
            self.label = label
            self.configurable = True
            self.description = description
    class Sensor(PropertyType):
        def __init__(self, label, description=""):
            PropertyType.__init__(self)
            self.label = label
            self.configurable = True
            self.description = description
    class Kettle(PropertyType):
        def __init__(self, label, description=""):
            PropertyType.__init__(self)
            self.label = label
            self.configurable = True
            self.description = description
