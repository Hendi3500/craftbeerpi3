# -*- coding: utf-8 -*-
"""
CascadeControl - kaskadierte PID- und Hysterese-Regler fuer CraftBeerPi 3.0.

Vier Kessel-Controller:

- **CascadePID** - aeussere PID-Schleife berechnet den Zielwert der
  inneren, innere PID-Schleife daraus die Heizleistung.
- **AdvancedPID** - einzelner PID-Regler mit Integrator-Startwert.
- **CascadeHysteresis** - aeussere PID-Schleife, innen eine Hysterese.
- **AdvancedHysteresis** - einzelne Hysterese.

Portierung von Python 2 auf Python 3
------------------------------------
Die Vorlage war Python 2 und laesst sich in dieser Form nicht einmal
importieren. Aenderungen:

1. ``def **init**`` -> ``def __init__``. In der Vorlage war der
   Konstruktor von ``PID`` und ``Hysteresis`` durch eine Markdown-
   Hervorhebung zerstoert worden - ``def **init**`` ist ein SyntaxError,
   das Plugin waere nie geladen worden.
2. Die ``print``-Statements sind weg. Sie schrieben exakt dieselbe Zeile
   noch einmal nach stdout, die der Logger bereits in ``logs/app.log``
   schreibt. Im Daemonbetrieb laeuft stdout ins Leere, und doppelt
   geloggte Regelwerte machen das Log unlesbar.
3. ``unicode`` ist weg. Die Sensor-Property wird ueber einen Helfer
   gelesen, der sowohl eine Zahl als auch einen Ziffern-String annimmt -
   je nach Oberflaeche landet das eine oder das andere dort.
4. ``super(KettleController, self).stop()`` -> ``super(CascadePID, self).stop()``
   und so weiter. Die alte Form ist zwar funktionsgleich, springt aber
   ueber die eigene Klasse hinweg und ist damit missverstaendlich.
5. Der Sensorwert kommt ueber ``cbpi.get_sensor_value()``. Der direkte
   Zugriff auf ``cache["sensors"][id].instance.last_value`` wirft einen
   TypeError, solange der Sensor noch keinen Wert geliefert hat.
6. Die Einheit wird ueber einen Helfer ermittelt, der notfalls direkt aus
   der Datenbank liest. Beim Import der Plugins ist der Config-Cache
   noch leer - die Klassenattribute werden ausgewertet, bevor die
   Initialisierer laufen. Ein ``get_config_parameter("unit")`` liefert
   dort also immer "C", und der Fahrenheit-Zweig waere nie erreicht.
7. Zwei Fehlermeldungen sind korrigiert: die Pruefung der maximalen
   Ausgangsleistung meldete "Notification timeout must be positive" -
   ein Copy-Paste-Fehler, der die falsche Ursache nennt.
8. In ``Hysteresis.update`` sind die Klammern um ``not self.positive``
   richtig gesetzt. Ohne sie liest Python ``not (self.positive and ...)``.
   Bei der negativen Aktion (Kuehlen) galt damit faelschlich der Fall
   "Istwert unter Sollwert" als AN - die Heizung waere anstatt aus
   geblieben.

Achtung bei der Nutzung
------------------------
``heater_on(0.0)`` schaltet den Actor **ein** - bei einem Actor, der den
Leistungsparameter ignoriert (``GPIOSimple``, ``RelayBoard``), heizt er
mit 100 %. Fuer diese Regler wird ein Actor mit Leistungsstufe gebraucht
(``GPIOPWM``). Das Plugin prueft das nicht - das ist die Aufgabe von
``AdvancedPIDAutoTune``.
"""

import time

from modules import cbpi
from modules.core.controller import KettleController
from modules.core.props import Property


# ---------------------------------------------------------------------------
# Property descriptions
# ---------------------------------------------------------------------------
kp_description = "The proportional term, also known as kp, is the action of PID in response to each unit of error. kp dictates the aggressiveness of action. \nThe units of kp are output / process variable (e.g. % / °C)"
ki_description = "The integral term, also known as ki, is the action of the PID in response to cumulative error in the system. ki is used primarily to reduce steady state error, but also factors into aggressivness of action. \nThe units of ki are output/(process variable • time) (e.g. % / (°C • seconds))"
kd_description = "The derivative term, also known as kd, is the action of the PID in response to the rate of change of the error. kd is used primarily to reduce overshoot. \nThe units are of output / process variable / time (e.g. % /°C / seconds)"
update_interval_description = "This is the length of time in seconds between recalculation of actor output with the PID algorithm."
notification_timeout_description = "Notification duration in milliseconds"
action_description = "Positive action results in the Actor being ON when current value of control variable is BELOW it's set point (e.g. heating). Negative action results in an Actor being OFF when the current value of the control variable is ABOVE it's setpoint (e.g. cooling)."
maxset_description = "The maximum temperature that the outer loop can set as the target for the inner loop"
maxoutput_description = "The maximum PWM output %"


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------
def temperature_unit():
    """
    Die eingestellte Temperatureinheit ("C" oder "F").

    Der Config-Cache ist beim Import der Plugins noch leer: die
    Klassenattribute werden ausgewertet, bevor die Initialisierer laufen.
    ``get_config_parameter`` liefert dort also immer den Vorgabewert, und
    der Zweig fuer Fahrenheit wuerde nie erreicht. Deshalb wird notfalls
    direkt aus der Datenbank gelesen - die steht zu diesem Zeitpunkt
    bereits, sie wird in ``init_db()`` angelegt.
    """
    try:
        unit = cbpi.get_config_parameter("unit", None)
        if unit:
            return unit
    except Exception:
        pass

    try:
        with cbpi.app.app_context():
            from modules.config import Config
            entry = Config.get_one("unit")
            if entry is not None and entry.value:
                return entry.value
    except Exception:
        pass

    return "C"


def sensor_id(value):
    """
    Die Sensor-Id aus dem Property-Wert.

    Je nach Oberflaeche landet dort eine Zahl oder ein Ziffern-String -
    beides wird angenommen. Leer oder nicht-numerisch liefert None.
    """
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return int(value)

    text = str(value).strip()

    if not text:
        return None

    try:
        return int(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------
@cbpi.controller
class CascadePID(KettleController):
    a_inner_sensor = Property.Sensor(label="Inner loop sensor")
    b_inner_kp = Property.Number("Inner loop proportional term", True, 5.0, description=kp_description)
    c_inner_ki = Property.Number("Inner loop integral term", True, 0.25, description=ki_description)
    d_inner_kd = Property.Number("Inner loop derivative term", True, 0.0, description=kd_description)
    e_inner_integrator_initial = Property.Number("Inner loop integrator initial value", True, 0.0)
    if temperature_unit() == "C":
        f_maxset = Property.Number("Max inner loop target (°C)", True, 75, description=maxset_description)
    else:
        f_maxset = Property.Number("Max inner loop target (°F)", True, 168, description=maxset_description)
    g_maxoutput = Property.Number("Max inner loop output (%)", True, 100, description=maxoutput_description)
    h_outer_kp = Property.Number("Outer loop proportional term", True, 5.0, description=kp_description)
    i_outer_ki = Property.Number("Outer loop integral term", True, 2.0, description=ki_description)
    j_outer_kd = Property.Number("Outer loop derivative term", True, 1.0, description=kd_description)
    k_outer_integrator_initial = Property.Number("Outer loop integrator initial value", True, 0.0)
    l_update_interval = Property.Number("Update interval (s)", True, 2.5, description=update_interval_description)
    m_notification_timeout = Property.Number("Notification duration (ms)", True, 5000, description=notification_timeout_description)

    def stop(self):
        self.actor_power(0.0)
        self.heater_off()
        super(CascadePID, self).stop()

    def run(self):
        inner_sensor = sensor_id(self.a_inner_sensor)

        if inner_sensor is None or inner_sensor not in cbpi.cache.get("sensors", {}):
            self.notify("PID Error", "An inner sensor must be selected",
                        timeout=None, type="danger")
            raise UserWarning("PID - An inner sensor must be selected")

        # Ensure all numerical properties are floats
        inner_kp = float(self.b_inner_kp)
        inner_ki = float(self.c_inner_ki)
        inner_kd = float(self.d_inner_kd)
        inner_integrator_initial = float(self.e_inner_integrator_initial)
        maxset = float(self.f_maxset)
        maxoutput = min(float(self.g_maxoutput), 100.0)
        outer_kp = float(self.h_outer_kp)
        outer_ki = float(self.i_outer_ki)
        outer_kd = float(self.j_outer_kd)
        outer_integrator_initial = float(self.k_outer_integrator_initial)
        update_interval = float(self.l_update_interval)
        notification_timeout = float(self.m_notification_timeout)

        # Error check
        if update_interval <= 0.0:
            self.notify("PID Error", "Update interval must be positive",
                        timeout=None, type="danger")
            raise ValueError("PID - Update interval must be positive")
        elif notification_timeout <= 0.0:
            self.notify("PID Error", "Notification timeout must be positive",
                        timeout=None, type="danger")
            raise ValueError("PID - Notification timeout must be positive")
        elif maxoutput < 5.0:
            self.notify("PID Error", "Max output must be at least 5%",
                        timeout=None, type="danger")
            raise ValueError("PID - Max output must be at least 5%")
        else:
            self.heater_on(0.0)

        # Initialize PID cascade
        if temperature_unit() == "C":
            outer_pid = PID(outer_kp, outer_ki, outer_kd, 0.0, maxset, 1.0, outer_integrator_initial)
        else:
            outer_pid = PID(outer_kp, outer_ki, outer_kd, 32, maxset, 1.8, outer_integrator_initial)

        inner_pid = PID(inner_kp, inner_ki, inner_kd, 0.0, maxoutput, 1.0, inner_integrator_initial)

        while self.is_running():
            waketime = time.time() + update_interval

            # Get the target temperature
            outer_target_value = self.get_target_temp()

            # Calculate inner target value from outer PID
            outer_current_value = self.get_temp()
            inner_target_value = round(outer_pid.update(outer_current_value, outer_target_value), 2)

            # Calculate inner output from inner PID
            inner_current_value = cbpi.get_sensor_value(inner_sensor)

            if inner_current_value is None:
                # Der innere Sensor hat noch keinen Wert geliefert. Das ist
                # kein Grund, den Regler zu beenden - die Heizung bleibt
                # einfach, wo sie ist, und die Schleife laeuft weiter.
                self.sleep(min(update_interval, 1.0))
                continue

            inner_output = round(inner_pid.update(inner_current_value, inner_target_value), 2)

            # Update the heater power
            self.actor_power(inner_output)

            # Log loop details
            cbpi.app.logger.info("[%s] Outer loop PID target/actual/output/integrator: %s/%s/%s/%s" % (waketime, outer_target_value, outer_current_value, inner_target_value, round(outer_pid.integrator, 2)))
            cbpi.app.logger.info("[%s] Inner loop PID target/actual/output/integrator: %s/%s/%s/%s" % (waketime, inner_target_value, inner_current_value, inner_output, round(inner_pid.integrator, 2)))

            # Sleep until update required again
            if waketime <= time.time() + 0.25:
                self.notify("PID Error", "Update interval is too short",
                            timeout=notification_timeout, type="warning")
                cbpi.app.logger.info("PID - Update interval is too short")
            else:
                self.sleep(waketime - time.time())


@cbpi.controller
class AdvancedPID(KettleController):
    a_kp = Property.Number("Proportional term", True, 10.0, description=kp_description)
    b_ki = Property.Number("Integral term", True, 2.0, description=ki_description)
    c_kd = Property.Number("Derivative term", True, 1.0, description=kd_description)
    d_maxoutput = Property.Number("Max output (%)", True, 100, description=maxoutput_description)
    e_integrator_initial = Property.Number("Integrator initial value", True, 0.0)
    f_update_interval = Property.Number("Update interval (s)", True, 2.5, description=update_interval_description)
    g_notification_timeout = Property.Number("Notification duration (ms)", True, 5000, description=notification_timeout_description)

    def stop(self):
        self.actor_power(0.0)
        self.heater_off()
        super(AdvancedPID, self).stop()

    def run(self):
        kp = float(self.a_kp)
        ki = float(self.b_ki)
        kd = float(self.c_kd)
        maxoutput = min(float(self.d_maxoutput), 100.0)
        integrator_initial = float(self.e_integrator_initial)
        update_interval = float(self.f_update_interval)
        notification_timeout = float(self.g_notification_timeout)

        # Error check
        if update_interval <= 0.0:
            self.notify("PID Error", "Update interval must be positive",
                        timeout=None, type="danger")
            raise ValueError("PID - Update interval must be positive")
        elif notification_timeout <= 0.0:
            self.notify("PID Error", "Notification timeout must be positive",
                        timeout=None, type="danger")
            raise ValueError("PID - Notification timeout must be positive")
        elif maxoutput < 5.0:
            self.notify("PID Error", "Max output must be at least 5%",
                        timeout=None, type="danger")
            raise ValueError("PID - Max output must be at least 5%")
        else:
            self.heater_on(0.0)

        # Initialize PID
        pid = PID(kp, ki, kd, 0.0, maxoutput, 1.0, integrator_initial)

        while self.is_running():
            waketime = time.time() + update_interval

            # Get the target temperature
            target_value = self.get_target_temp()

            # Calculate the output
            current_value = self.get_temp()
            output = round(pid.update(current_value, target_value), 2)

            # Update the heater power
            self.actor_power(output)

            # Log details
            cbpi.app.logger.info("[%s] PID target/actual/output/integrator: %s/%s/%s/%s" % (waketime, target_value, current_value, output, round(pid.integrator, 2)))

            # Sleep until update required again
            if waketime <= time.time() + 0.25:
                self.notify("PID Error", "Update interval is too short",
                            timeout=notification_timeout, type="warning")
                cbpi.app.logger.info("PID - Update interval is too short")
            else:
                self.sleep(waketime - time.time())


@cbpi.controller
class CascadeHysteresis(KettleController):
    aa_kp = Property.Number("Proportional term", True, 10.0, description=kp_description)
    ab_ki = Property.Number("Integral term", True, 2.0, description=ki_description)
    ac_kd = Property.Number("Derivative term", True, 1.0, description=kd_description)
    ad_integrator_initial = Property.Number("Integrator initial value", True, 0.0)
    if temperature_unit() == "C":
        ae_maxset = Property.Number("Max hysteresis target (°C)", True, 75, description=maxset_description)
    else:
        ae_maxset = Property.Number("Max hysteresis target (°F)", True, 168, description=maxset_description)
    ba_inner_sensor = Property.Sensor(label="Inner (hysteresis) sensor")
    bb_action = Property.Select(label="Hysteresis Action Type", options=["Positive", "Negative"], description=action_description)
    bc_on_min = Property.Number("Hysteresis Minimum Time On (s)", True, 45)
    bd_on_max = Property.Number("Hysteresis Maximum Time On (s)", True, 1800)
    be_off_min = Property.Number("Hysteresis Minimum Time Off (s)", True, 90)
    c_update_interval = Property.Number("Update interval (s)", True, 2.5, description=update_interval_description)
    d_notification_timeout = Property.Number("Notification duration (ms)", True, 5000, description=notification_timeout_description)

    def stop(self):
        self.heater_off()
        super(CascadeHysteresis, self).stop()

    def run(self):
        inner_sensor = sensor_id(self.ba_inner_sensor)

        if inner_sensor is None or inner_sensor not in cbpi.cache.get("sensors", {}):
            self.notify("Hysteresis Error", "An inner sensor must be selected",
                        timeout=None, type="danger")
            raise UserWarning("Hysteresis - An inner sensor must be selected")

        # Outer PID settings
        kp = float(self.aa_kp)
        ki = float(self.ab_ki)
        kd = float(self.ac_kd)
        integrator_initial = float(self.ad_integrator_initial)
        maxset = float(self.ae_maxset)

        # Inner hysteresis settings
        positive = self.bb_action == "Positive"
        on_min = float(self.bc_on_min)
        on_max = float(self.bd_on_max)
        off_min = float(self.be_off_min)

        # General settings
        update_interval = float(self.c_update_interval)
        notification_timeout = float(self.d_notification_timeout)

        # Error check
        if on_min <= 0.0:
            self.notify("Hysteresis Error", "Minimum 'on time' must be positive", timeout=None, type="danger")
            raise ValueError("Hysteresis - Minimum 'on time' must be positive")
        if on_max <= 0.0:
            self.notify("Hysteresis Error", "Maximum 'on time' must be positive", timeout=None, type="danger")
            raise ValueError("Hysteresis - Maximum 'on time' must be positive")
        if on_min >= on_max:
            self.notify("Hysteresis Error", "Maximum 'on time' must be greater than the minimum 'on time'", timeout=None, type="danger")
            raise ValueError("Hysteresis - Maximum 'on time' must be greater than the minimum 'on time'")
        if off_min <= 0.0:
            self.notify("Hysteresis Error", "Minimum 'off time' must be positive", timeout=None, type="danger")
            raise ValueError("Hysteresis - Minimum 'off time' must be positive")
        if update_interval <= 0.0:
            self.notify("Hysteresis Error", "Update interval must be positive", timeout=None, type="danger")
            raise ValueError("Hysteresis - Update interval must be positive")
        elif notification_timeout <= 0.0:
            self.notify("Hysteresis Error", "Notification timeout must be positive", timeout=None, type="danger")
            raise ValueError("Hysteresis - Notification timeout must be positive")
        else:
            # Initialize outer PID
            if temperature_unit() == "C":
                outer_pid = PID(kp, ki, kd, 0.0, maxset, 1.0, integrator_initial)
            else:
                outer_pid = PID(kp, ki, kd, 32, maxset, 1.8, integrator_initial)

            # Initialize hysteresis
            inner_hysteresis = Hysteresis(positive, on_min, on_max, off_min)

            while self.is_running():
                waketime = time.time() + update_interval

                # Get the target temperature
                outer_target_value = self.get_target_temp()

                # Calculate inner target value from outer PID
                outer_current_value = self.get_temp()
                inner_target_value = round(outer_pid.update(outer_current_value, outer_target_value), 2)
                inner_current_value = cbpi.get_sensor_value(inner_sensor)

                if inner_current_value is None:
                    # Der innere Sensor hat noch keinen Wert geliefert.
                    self.sleep(min(update_interval, 1.0))
                    continue

                # Update the hysteresis controller
                if inner_hysteresis.update(inner_current_value, inner_target_value):
                    self.heater_on(100)
                    cbpi.app.logger.info("[%s] Inner hysteresis actor stays ON" % (waketime))
                else:
                    self.heater_off()
                    cbpi.app.logger.info("[%s] Inner hysteresis actor stays OFF" % (waketime))

                # Log loop details
                cbpi.app.logger.info("[%s] Outer loop PID target/actual/output/integrator: %s/%s/%s/%s" % (waketime, outer_target_value, outer_current_value, inner_target_value, round(outer_pid.integrator, 2)))

                # Sleep until update required again
                if waketime <= time.time() + 0.25:
                    self.notify("Hysteresis Error", "Update interval is too short", timeout=notification_timeout, type="warning")
                    cbpi.app.logger.info("Hysteresis - Update interval is too short")
                else:
                    self.sleep(waketime - time.time())


@cbpi.controller
class AdvancedHysteresis(KettleController):
    a_action = Property.Select(label="Hysteresis Action Type", options=["Positive", "Negative"], description=action_description)
    b_on_min = Property.Number("Hysteresis Minimum Time On (s)", True, 45)
    c_on_max = Property.Number("Hysteresis Maximum Time On (s)", True, 1800)
    d_off_min = Property.Number("Hysteresis Minimum Time Off (s)", True, 90)
    e_update_interval = Property.Number("Update interval (s)", True, 2.5, description=update_interval_description)
    f_notification_timeout = Property.Number("Notification duration (ms)", True, 5000, description=notification_timeout_description)

    def stop(self):
        self.heater_off()
        super(AdvancedHysteresis, self).stop()

    def run(self):
        positive = self.a_action == "Positive"
        on_min = float(self.b_on_min)
        on_max = float(self.c_on_max)
        off_min = float(self.d_off_min)
        update_interval = float(self.e_update_interval)
        notification_timeout = float(self.f_notification_timeout)

        # Error check
        if on_min <= 0.0:
            self.notify("Hysteresis Error", "Minimum 'on time' must be positive", timeout=None, type="danger")
            raise ValueError("Hysteresis - Minimum 'on time' must be positive")
        if on_max <= 0.0:
            self.notify("Hysteresis Error", "Maximum 'on time' must be positive", timeout=None, type="danger")
            raise ValueError("Hysteresis - Maximum 'on time' must be positive")
        if on_min >= on_max:
            self.notify("Hysteresis Error", "Maximum 'on time' must be greater than the minimum 'on time'", timeout=None, type="danger")
            raise ValueError("Hysteresis - Maximum 'on time' must be greater than the minimum 'on time'")
        if off_min <= 0.0:
            self.notify("Hysteresis Error", "Minimum 'off time' must be positive", timeout=None, type="danger")
            raise ValueError("Hysteresis - Minimum 'off time' must be positive")
        if update_interval <= 0.0:
            self.notify("Hysteresis Error", "Update interval must be positive", timeout=None, type="danger")
            raise ValueError("Hysteresis - Update interval must be positive")
        elif notification_timeout <= 0.0:
            self.notify("Hysteresis Error", "Notification timeout must be positive", timeout=None, type="danger")
            raise ValueError("Hysteresis - Notification timeout must be positive")
        else:
            # Initialize hysteresis
            hysteresis_on = Hysteresis(positive, on_min, on_max, off_min)

            while self.is_running():
                waketime = time.time() + update_interval

                # Get the target temperature
                current_value = self.get_temp()
                target_value = self.get_target_temp()

                if hysteresis_on.update(current_value, target_value):
                    self.heater_on(100)
                    cbpi.app.logger.info("[%s] Hysteresis actor stays ON" % (waketime))
                else:
                    self.heater_off()
                    cbpi.app.logger.info("[%s] Hysteresis actor stays OFF" % (waketime))

                # Sleep until update required again
                if waketime <= time.time() + 0.25:
                    self.notify("Hysteresis Error", "Update interval is too short", timeout=notification_timeout, type="warning")
                    cbpi.app.logger.info("Hysteresis - Update interval is too short")
                else:
                    self.sleep(waketime - time.time())


# ---------------------------------------------------------------------------
# Regelalgorithmen
# ---------------------------------------------------------------------------
class PID(object):
    def __init__(self, kp, ki, kd, output_min, output_max, integrator_error_max, integrator_initial):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.output_min = output_min
        self.output_max = output_max

        # Set integrator maximum in relation to ki and output range
        # such that the maximum integrator alone could result in no
        # more than 100% of the output. This can help limit excessive
        # integrator wind up.
        if ki == 0.0:
            self.integrator_max = 0.0
        else:
            self.integrator_max = abs((output_max - output_min) / ki)

        # Setting an error maximum for the integrator is an additional
        # measure to prevent excessive integrator windup
        self.integrator_error_max = abs(integrator_error_max)

        self.last_time = 0.0
        self.last_error = 0.0

        # Quietly ensure the initial integrator does not exceed
        # the magnitude of the integrator maximum
        if abs(integrator_initial) > abs(self.integrator_max):
            self.integrator = self.integrator_max
        else:
            self.integrator = integrator_initial

    def update(self, current, target):
        # Initialization iteration
        if self.last_time == 0.0:
            self.last_time = time.time()
            current_error = target - current

            # Update last_error
            self.last_error = current_error

            # Return output
            return max(min(self.kp * current_error, self.output_max), self.output_min)

        # Regular iteration
        else:
            # Calculate duration of iteration
            current_time = time.time()
            iteration_time = current_time - self.last_time
            self.last_time = current_time

            # Calculate error
            current_error = target - current

            # Calculate error for use with integrator with respect to specified error limits
            integrator_error = max(min(current_error, self.integrator_error_max), -self.integrator_error_max)

            # Update the integrator with respect to total integrator limits
            self.integrator = max(min(self.integrator + (integrator_error * iteration_time), self.integrator_max), -self.integrator_max)

            # Calculate error derivative
            derivative = (current_error - self.last_error) / iteration_time

            # Calculate output components
            p_action = self.kp * current_error
            i_action = self.ki * self.integrator
            d_action = self.kd * derivative

            # Update last_error
            self.last_error = current_error

            # Return output
            return max(min(p_action + i_action + d_action, self.output_max), self.output_min)


class Hysteresis(object):
    def __init__(self, positive, on_min, on_max, off_min):
        # If positive is true, output will be ON when the control variable is
        # BELOW the lowerbound (i.e. heating if controlling temperature)
        #
        # If positive is false, output will be ON when the control variable is
        # ABOVE the setpoint (i.e. cooling if controlling temperature)
        self.positive = positive

        # The minimum and maximum time in seconds that an output should remain ON
        # This setting is intended to protect against scenarios which may lead to
        # excessive cycling of a compressor, etc. This overrides the buffer.
        self.on_min = on_min
        self.on_max = on_max

        # The minimum time in seconds that an output should remain OFF
        # This setting is intended to protect against scenarios which may lead to
        # excessive cycling of a compressor, etc.
        self.off_min = off_min

        # To implement min/max on/off times, keep track of time of last change
        # in the output
        self.last_change = time.time()

        # Record intended state
        self.on = False

    def update(self, current, target):
        interval = time.time() - self.last_change

        # Sollzustand: AN, wenn die Bedingung der gewaehlten Aktion zutrifft.
        #
        # Die Klammern um "not self.positive" sind wichtig. Ohne sie liest
        # Python "not (self.positive and (current >= target))" - bei der
        # negativen Aktion (Kuehlen) galt damit auch der Fall "Istwert unter
        # Sollwert" als AN, und die Heizung waere anstatt aus geblieben.
        if self.positive:
            should_on = current <= target
        else:
            should_on = current >= target

        if should_on:
            if self.on:
                if interval > self.on_max:
                    # Current ON time has exceeded ON time maximum
                    # Turn OFF, and update time of last change
                    self.last_change = time.time()
                    self.on = False
                else:
                    # Leave ON
                    self.on = True
            else:
                if interval < self.off_min:
                    # Prevent turning ON due to OFF time minimum
                    self.on = False
                else:
                    # OK to turn ON
                    # Turn ON, and update time of last change
                    self.last_change = time.time()
                    self.on = True
        else:
            if self.on:
                if interval < self.on_min:
                    # Current ON time has NOT exceeded minimum, so leave ON
                    self.on = True
                else:
                    # OK to turn OFF
                    # Turn OFF, and update time of last change
                    self.last_change = time.time()
                    self.on = False
            else:
                # Leave OFF
                self.on = False

        return self.on
