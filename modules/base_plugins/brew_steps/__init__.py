# -*- coding: utf-8 -*-
import time


from modules.core.props import Property, StepProperty
from modules.core.step import StepBase
from modules import cbpi



@cbpi.step
class MashStep(StepBase):
    '''
    Just put the decorator @cbpi.step on top of a method
    '''
    # Properties
    temp = Property.Number("Temperature", configurable=True, description="Target Temperature of Mash Step")
    kettle = StepProperty.Kettle("Kettle", description="Kettle in which the mashing takes place")
    timer = Property.Number("Timer in Minutes", configurable=True, description="Timer is started when the target temperature is reached")

    def init(self):
        '''
        Initialize Step. This method is called once at the beginning of the step
        :return:
        '''
        # set target tep
        self.set_target_temp(self.temp, self.kettle)

    @cbpi.action("Start Timer Now")
    def start(self):
        '''
        Custom Action which can be execute form the brewing dashboard.
        All method with decorator @cbpi.action("YOUR CUSTOM NAME") will be available in the user interface
        :return:
        '''
        if self.is_timer_finished() is None:
            self.start_timer(int(self.timer) * 60)

    def reset(self):
        self.stop_timer()
        self.set_target_temp(self.temp, self.kettle)

    def finish(self):
        self.set_target_temp(0, self.kettle)

    def execute(self):
        '''
        This method is execute in an interval
        :return:
        '''

        # Check if Target Temp is reached
        if self.get_kettle_temp(self.kettle) >= float(self.temp):
            # Check if Timer is Running
            if self.is_timer_finished() is None:
                self.start_timer(int(self.timer) * 60)

        # Check if timer finished and go to next step
        if self.is_timer_finished() == True:
            self.notify("Mash Step Completed!", "Starting the next step", timeout=None)
            self.next()


@cbpi.step
class MashInStep(StepBase):
    '''
    Just put the decorator @cbpi.step on top of a method
    '''
    # Properties
    temp = Property.Number("Temperature", configurable=True,  description="Target Temperature of Mash Step")
    kettle = StepProperty.Kettle("Kettle", description="Kettle in which the mashing takes place")
    s = False

    @cbpi.action("Change Power")
    def change_power(self):
        self.actor_power(1, 50)

    def init(self):
        '''
        Initialize Step. This method is called once at the beginning of the step
        :return:
        '''
        # set target tep
        self.s = False
        self.set_target_temp(self.temp, self.kettle)

    def finish(self):
        '''
        Der Schritt ist vorbei - die Zieltemperatur des Kessels gehoert
        zurueckgesetzt.

        Ohne das bleibt die Temperatur des Schritts im Kessel stehen und
        der Kessel heizt weiter, obwohl der Schritt nicht mehr laeuft.
        MashStep und BoilStep machen es genauso.
        '''
        self.set_target_temp(0, self.kettle)



    def execute(self):
        '''
        This method is execute in an interval
        :return:
        '''

        # Check if Target Temp is reached
        if self.get_kettle_temp(self.kettle) >= float(self.temp) and self.s is False:
            self.s = True
            self.notify("Step Temp Reached!", "Please press the next button to continue", timeout=None)



@cbpi.step
class ChilStep(StepBase):

    timer = Property.Number("Timer in Minutes", configurable=True, default_value=0, description="Timer is started immediately")

    @cbpi.action("Start Timer")
    def start(self):
        if self.is_timer_finished() is None:
            self.start_timer(int(self.timer) * 60)

    def reset(self):
        self.stop_timer()


    def finish(self):
        pass

    def execute(self):
        if self.is_timer_finished() is None:
            self.start_timer(int(self.timer) * 60)

        if self.is_timer_finished() == True:
            self.next()

@cbpi.step
class PumpStep(StepBase):

    pump = StepProperty.Actor("Pump", description="Pump actor gets toggled")
    timer = Property.Number("Timer in Minutes", configurable=True, default_value=0, description="Timer is started immediately")

    @cbpi.action("Start Timer")
    def start(self):
        if self.is_timer_finished() is None:
            self.start_timer(int(self.timer) * 60)

    def reset(self):
        self.stop_timer()


    def finish(self):
        self.actor_off(int(self.pump))

    def init(self):
        self.actor_on(int(self.pump))

    def execute(self):
        if self.is_timer_finished() is None:
            self.start_timer(int(self.timer) * 60)

        if self.is_timer_finished() == True:
            self.next()

@cbpi.step
class BoilStep(StepBase):
    '''
    Just put the decorator @cbpi.step on top of a method
    '''
    # Properties
    temp = Property.Number("Temperature", configurable=True, default_value=100, description="Target temperature for boiling")
    kettle = StepProperty.Kettle("Kettle", description="Kettle in which the boiling step takes place")
    timer = Property.Number("Timer in Minutes", configurable=True, default_value=90, description="Timer is started when target temperature is reached")
    hop_1 = Property.Number("Hop 1 Addition", configurable=True, description="First hop alert")
    hop_1_added = Property.Number("",default_value=None)
    hop_2 = Property.Number("Hop 2 Addition", configurable=True, description="Second Hop alert")
    hop_2_added = Property.Number("", default_value=None)
    hop_3 = Property.Number("Hop 3 Addition", configurable=True)
    hop_3_added = Property.Number("", default_value=None, description="Third Hop alert")
    hop_4 = Property.Number("Hop 4 Addition", configurable=True)
    hop_4_added = Property.Number("", default_value=None, description="Fourth Hop alert")
    hop_5 = Property.Number("Hop 5 Addition", configurable=True)
    hop_5_added = Property.Number("", default_value=None, description="Fives Hop alert")
    hop_5_name = Property.Text("Hop 5 Name", configurable=True, default_value="")

    # Hop-Namen: der Alert sagt damit "Please add Magnum" statt
    # "Please add Hop 1". Der Name kommt aus dem Rezept-Import oder wird
    # im Step-Dialog eingetragen. Er ist Config, kein State - er uebersteht
    # deshalb einen Reset und einen Neustart.
    hop_1_name = Property.Text("Hop 1 Name", configurable=True, default_value="", description="Name of the first hop, e.g. Magnum")
    hop_2_name = Property.Text("Hop 2 Name", configurable=True, default_value="", description="Name of the second hop")
    hop_3_name = Property.Text("Hop 3 Name", configurable=True, default_value="")
    hop_4_name = Property.Text("Hop 4 Name", configurable=True, default_value="")

    def init(self):
        '''
        Initialize Step. This method is called once at the beginning of the step
        :return:
        '''
        # set target tep
        self.set_target_temp(self.temp, self.kettle)




    @cbpi.action("Start Timer Now")
    def start(self):
        '''
        Custom Action which can be execute form the brewing dashboard.
        All method with decorator @cbpi.action("YOUR CUSTOM NAME") will be available in the user interface
        :return:
        '''
        if self.is_timer_finished() is None:
            self.start_timer(int(self.timer) * 60)

    def reset(self):
        self.stop_timer()
        self.set_target_temp(self.temp, self.kettle)
        # Die Hop-Flags zuruecksetzen. Sie sind managed fields und werden
        # im stepstate gespeichert; reset() hat sie vorher nicht
        # zurueckgesetzt. Folge: nach "Reset Step" bleibt die Step-Instanz
        # mit allen hop_X_added = True am Leben, check_hop_timer() haelt
        # jeden Hop fuer "schon zugegeben" und es feuert kein Hop-Alarm
        # mehr fuer den Rest des Suds.
        #
        # resetCurrentStep() laesst die Instanz am Leben, deshalb muessen
        # die Flags auf der Instanz zurueckgesetzt werden - das dirty flag
        # sorgt dafuer, dass der Kern sie wieder ins stepstate schreibt.
        # Die Hop-Namen sind Config, kein State, die bleiben wie sie sind.
        for number in range(1, 6):
            self.__setattr__("hop_%s_added" % number, None)

    def finish(self):
        self.set_target_temp(0, self.kettle)


    def hop_label(self, number):
        """
        Wie der Hop im Alert heisst: sein Name, wenn einer konfiguriert ist,
        sonst die Slot-Nummer. Der Name kommt aus dem Rezept-Import oder
        wird im Step-Dialog eingetragen - er kann fehlen, leer oder
        Leerzeichen sein, und eine Zahl im Feld ist ueberhaupt kein Name,
        sondern ein verirrter Config-Wert.
        :return:
        """
        name = self.__getattribute__("hop_%s_name" % number)

        if not isinstance(name, str):
            return "Hop %s" % number

        name = name.strip()

        if not name:
            return "Hop %s" % number

        # Eine reine Zahl ist kein Name, sondern ein verirrter Config-Wert.
        # Die Recipe-Import-Version hat eine Zahl im Feld mit dem echten
        # Namen des Hops belegt - der steht dann in der Zahl und geht
        # verloren, wenn der Name nicht uebernommen wird. Deshalb faellt
        # auch "42" auf die Slot-Nummer zurueck.
        try:
            float(name)
        except ValueError:
            return name

        return "Hop %s" % number

    def check_hop_timer(self, number, value):

        if value is None:
            # Fuer diesen Hop ist nichts eingetragen. Ein Rezept hat
            # seltener fuenf Hop-Slots als fuenf Hopgaben.
            #
            # Vorher ist der Schritt hier gestorben: int(None) wirft
            # TypeError, und der Fehler reisst die ganze execute()-Runde
            # mit - die Hop-Meldungen der slots nach diesem kamen nicht
            # mehr und der Schritt lief nie fertig.
            return

        if self.__getattribute__("hop_%s_added" % number) is not True and time.time() > (
            self.timer_end - (int(self.timer) * 60 - int(value) * 60)):
            self.__setattr__("hop_%s_added" % number, True)
            self.notify("Hop Alert", "Please add %s" % self.hop_label(number), timeout=None)

    def execute(self):
        '''
        This method is execute in an interval
        :return:
        '''
        # Check if Target Temp is reached
        if self.get_kettle_temp(self.kettle) >= float(self.temp):
            # Check if Timer is Running
            if self.is_timer_finished() is None:
                self.start_timer(int(self.timer) * 60)
            else:
                self.check_hop_timer(1, self.hop_1)
                self.check_hop_timer(2, self.hop_2)
                self.check_hop_timer(3, self.hop_3)
                self.check_hop_timer(4, self.hop_4)
                self.check_hop_timer(5, self.hop_5)
        # Check if timer finished and go to next step
        if self.is_timer_finished() == True:
            self.notify("Boil Step Completed!", "Starting the next step", timeout=None)
            self.next()
