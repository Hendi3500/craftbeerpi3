# -*- coding: utf-8 -*-
"""
AdvancedPIDAutoTune - finds the AdvancedPID settings for your kettle.

WHY THIS PLUGIN EXISTS:

The AdvancedPID controller (CascadeControl plugin) ships with P=10, I=2.0,
D=1.0. Those numbers are a starting point for a small, fast kettle and they
are wrong by two orders of magnitude for a 38 litre mash tun with a 3.6 kW
induction plate - not a little wrong, structurally wrong:

    integrator_max = (output_max - output_min) / ki = 100 / 2.0 = 50

The integrator grows by at most `integrator_error_max` (hard coded 1.0) per
second, so after 50 seconds of error it holds 50, and `i_action = ki * 50`
alone is the full 100 % output. The integral term pins the heater on and the
proportional term stops mattering. The defaults are a 50 second time bomb on
a big kettle and nobody notices until the mash overshoots by five degrees.

Tuning by hand is worse. The brewmaster has a duty cycle and a temperature
curve and no way to tell them apart: "badly tuned", "element too small" and
"probe in the wrong place" look exactly the same from the temperature alone.

This plugin identifies the kettle instead. It drives the heater with a relay
(Ziegler-Nichols ultimate gain), which makes the temperature oscillate around
the setpoint, and watches how big that oscillation gets and how long it takes.
Two numbers fall out - Ku (the proportional gain at which the loop starts to
oscillate on its own) and Pu (the period of that oscillation).

HOW IT WORKS:

Relay feedback, the classic closed-loop autotune. The output is a square wave
around the setpoint: full output until the kettle passes setpoint + noiseband,
zero until it drops below setpoint - noiseband, repeat. Two things come out of
the resulting temperature swing:

    Pu = 4 * theta          theta = dead time of the plant
    Ku = 4 * d / (pi * A)   A = half of the peak-to-peak swing

HOW THE ANSWER IS TURNED INTO SETTINGS:

The raw Ziegler-Nichols gains are not what you want to run. ZN deliberately
overshoots - it buys response time with stability, which is the wrong trade for
a mash that is held at one temperature for an hour. So the interesting part of
this plugin is that it does not stop at Ku and Pu.

A second, independent measurement is taken while the kettle oscillates: the
mean output over the last ten minutes. That mean is the duty cycle the element
has to hold just to stay at the setpoint, and it is a direct measurement of
how much the kettle loses to the room:

    UA = mean_output / 100 * heater_power / (setpoint - room_temperature)

From UA the plant is fully determined, because the thermal capacity of the
water is known:

    C  = volume * 4186 J/K          (water; the steel adds a few percent)
    tau = C / UA                     open loop time constant
    Kdc = UA / (heater_power / 100)  DC gain in degrees per percent output

and from there the lambda tuning that this plugin actually recommends:

    kp = (C / lambda - UA) / (heater_power / 100)
    ki = kp / lambda

which is the IMC/lambda tuning of a first order plant with the loop slowed
down to `lambda` seconds. `lambda` is a property, default 600 s: that is about
ten minutes from "setpoint changed" to "settled", which for a 38 litre kettle
feels immediate and never oscillates.

The remaining AdvancedPID settings are derived rather than guessed:

- `integrator_initial` is set to the measured mean output divided by ki, so the
  controller starts already holding the setpoint instead of climbing there
  from zero over the first ten minutes.
- `kd` is limited by the sensor resolution. AdvancedPID differentiates the raw
  error with no filter, so a DS18B20 at 0.0625 degrees produces derivative
  noise of resolution/sample_time, and kd is capped such that that noise stays
  below 1 % of output. On a large kettle the cap wins and kd comes out at 0.
- `update_interval` is Pu/20, clamped to 5..30 s. The lower bound is not a
  tuning choice: the core polls passive sensors every 5 s
  (modules/sensors/__init__.py, backgroundtask "read_passive_sensor"), so a
  faster PID loop re-reads the same stale value on every second iteration and
  feeds the derivative term zero.
- `maxoutput` is 100 % - during the run the element needs full authority, and
  afterwards there is no reason to cap it.

NOTES:
- The actor MUST be GPIOPWM. AdvancedPID and this plugin both drive the heater
  through actor_power() -> instance.set_power(), and for GPIOSimple and
  RelayBoard set_power() is inherited from ActorBase and does nothing. Worse,
  heater_on(0.0) in the start path energises those actors regardless of the
  power argument, because their on() ignores it. The preflight check below
  refuses to run rather than heating at 100 % while pretending to tune.
- `output step %` must equal `max. output %`. The relay in this implementation
  accumulates (`output += outputstep`), it is not the fixed-amplitude relay of
  the Arduino library it is derived from. With a step below the maximum the
  output ramps up instead of switching, and Ku = 4*d/(pi*A) is computed from the
  wrong relay amplitude. Any other value is corrected and warned about.
- The heater is switched off in a finally block. The upstream plugin calls
  atune.run() inside the while condition, so an exception from its own logging
  leaves the element running with nothing regulating it.
- Every log write is guarded. The upstream plugin logs to ./logs/autotune.log
  from inside its run loop; if that directory is missing the plugin dies with
  the heater on.
- The result is written to ./logs/advancedpid-autotune.txt and pushed to the
  notification bell, so the numbers survive the end of the run.
- Relay feedback only sees the plant around the ultimate frequency. It cannot
  separate DC gain from time constant on its own - that is what the mean
  output is for. If the mean output is 0 the kettle never actually settled
  during the oscillation (output was clamped at the minimum) and the lambda
  tuning is skipped in favour of the classic rules.
- Degrees Celsius only. The relay, the 0.5 degree noise band and the water
  heat capacity are all metric; a backend running on Fahrenheit is warned and
  the run is refused rather than answered in the wrong scale.
- Python 2 code, like the core it runs next to.
"""

import logging
import math
import os
import time
from collections import deque, namedtuple

from modules import cbpi
from modules.core.controller import KettleController
from modules.core.hardware import ActorBase
from modules.core.props import Property

logger = logging.getLogger(__name__)

## Where the full result ends up. Relative to the backend root, same as the
## upstream plugin's autotune.log.
TRACE_LOG = "./logs/autotune.log"
REPORT_FILE = "./logs/advancedpid-autotune.txt"

## CBP polls passive sensors on this interval (modules/sensors/__init__.py).
## A PID loop faster than this re-reads the same value and computes a
## derivative of zero on every second iteration.
SENSOR_POLL_INTERVAL = 5.0

## Specific heat of water, J/(kg K) - 4.186 kJ/(kg K).
WATER_HEAT_CAPACITY = 4186.0

## Fraction of the output the derivative term is allowed to produce from
## sensor quantisation noise alone. 1 % is below the resolution of the kettle
## temperature display and above the visible jitter of the heater.
DERIVATIVE_NOISE_BUDGET = 0.01

## Closed-loop time constant bounds for update_interval, seconds.
MIN_UPDATE_INTERVAL = SENSOR_POLL_INTERVAL
MAX_UPDATE_INTERVAL = 20.0

## Samples of output history kept for the mean output measurement, seconds.
## The window actually used is chosen after the run and has to cover at
## least two full oscillation cycles; on a large kettle that is far more
## than the 600 s a fixed window would give.
OUTPUT_HISTORY = 7200.0

## Peak-to-peak amplitude deviation below which the oscillation counts as
## converged (same criterion as the Arduino library this is derived from).
PEAK_AMPLITUDE_TOLERANCE = 0.05

## Hard stop: ten full cycles.
MAX_PEAKS = 20

kp_description = (
    "The proportional term, also known as kp, is the action of PID in response "
    "to each unit of error. kp dictates the aggressiveness of action. \nThe "
    "units of kp are output / process variable (e.g. % / °C)"
)
ki_description = (
    "The integral term, also known as ki, is the action of the PID in response "
    "to cumulative error in the system. ki is used primarily to reduce steady "
    "state error, but also factors into aggressivness of action. \nThe units "
    "of ki are output/(process variable • time) (e.g. % / (°C • seconds))"
)
kd_description = (
    "The derivative term, also known as kd, is the action of the PID in "
    "response to the rate of change of the error. kd is used primarily to "
    "reduce overshoot. \nThe units are of output / process variable / time "
    "(e.g. % / °C / seconds)"
)
outstep_description = (
    "Default: 100. Sets the output when stepping up/down. Must be equal to "
    "'max. output %' - the relay in this plugin accumulates, so a step below "
    "the maximum ramps the output up instead of switching it, and the "
    "calculated Ku would be from the wrong relay amplitude."
)
maxoutput_description = (
    "Default: 100. Sets the max power output. The element needs its full "
    "authority during the run - a capped run identifies a part of the power "
    "stage, not the kettle."
)
lookback_description = (
    "Default: 60. How far back to look for min/max temps when deciding "
    "whether the newest reading is a peak. Must be at least three times the "
    "sample time."
)
noiseband_description = (
    "Default: 0.5. Hysteresis of the relay in degrees. Should be at least "
    "twice the sensor resolution, and the resulting oscillation must be "
    "clearly larger than it - if the amplitude in the log sits at this "
    "value, the tuner is counting sensor noise."
)
sampletime_description = (
    "Default: 5. Seconds between readings. Do not go below 5: the core polls "
    "passive sensors every 5 s, and a faster loop re-reads the same stale "
    "value every second iteration."
)
lambda_description = (
    "Default: 600. The closed-loop time constant the result is tuned for: "
    "roughly this many seconds from a changed setpoint to settled. Larger is "
    "gentler and never oscillates, smaller reacts faster and hunts."
)
power_description = (
    "Default: 3600. Real electrical power of the element at 100 % output, in "
    "watts. Not the nameplate rating if it is below it."
)
volume_description = (
    "Default: 38. Content of the kettle in litres at the setpoint. Sets the "
    "thermal capacity the tuning is calculated for. The steel is not counted; "
    "it is a few percent of the water and ignoring it errs on the safe side."
)
room_description = (
    "Default: 20. Ambient temperature in degrees. The mean output of the run "
    "only converts to a heat loss UA if the difference to the setpoint is "
    "known."
)
resolution_description = (
    "Default: 0.0625. Resolution of the kettle sensor in degrees (0.0625 for "
    "a 12 bit DS18B20, 0.0078125 for 16 bit). Caps the derivative term so that "
    "sensor noise cannot move the heater."
)


@cbpi.controller
class AdvancedPIDAutoTune(KettleController):

    a_outstep = Property.Number("output step %", True, 100, description=outstep_description)
    b_maxoutput = Property.Number("max. output %", True, 100, description=maxoutput_description)
    c_lookback = Property.Number("lookback seconds", True, 60, description=lookback_description)
    d_noiseband = Property.Number("noise band (°C)", True, 0.5, description=noiseband_description)
    e_sample_time = Property.Number("sample time (s)", True, 5, description=sampletime_description)
    f_lambda = Property.Number("target loop time constant (s)", True, 600, description=lambda_description)
    g_heater_power = Property.Number("heater power at 100 % (W)", True, 3600, description=power_description)
    h_kettle_volume = Property.Number("kettle volume (L)", True, 38, description=volume_description)
    i_room_temperature = Property.Number("room temperature (°C)", True, 20, description=room_description)
    j_sensor_resolution = Property.Number("sensor resolution (°C)", True, 0.0625, description=resolution_description)

    def stop(self):
        if self.is_running():
            self.notify(
                "AutoTune interrupted",
                "AutoTune was interrupted and was not able to finish. The "
                "heater has been switched off.",
                type="danger",
                timeout=None,
            )
        super(KettleController, self).stop()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _trace(self, text):
        """
        Append one line to the run trace.

        Guarded, because this is called from inside the control loop and a
        missing ./logs directory must not take the heater down with it.
        """
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        line = "%s,%s" % (stamp, text)
        logger.info("AdvancedPIDAutoTune: %s" % text)
        try:
            directory = os.path.dirname(TRACE_LOG)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            with open(TRACE_LOG, "a") as handle:
                handle.write(line + "\n")
        except Exception as e:
            logger.warning("AdvancedPIDAutoTune: trace not written (%s)" % e)

    def _cleanup(self):
        """Element off, whatever happened."""
        try:
            self.actor_power(0)
        except Exception as e:
            logger.debug("AdvancedPIDAutoTune: actor_power(0) failed (%s)" % e)
        self.heater_off()

    def _auto_off(self):
        self._cleanup()
        kettle = cbpi.cache.get("kettle")[self.kettle_id]
        kettle.state = False
        cbpi.emit("UPDATE_KETTLE", kettle)

    def _fail(self, message):
        self._trace("failed: %s" % message)
        self._cleanup()
        self.notify("AutoTune failed", message, type="danger", timeout=None)

    def _is_pwm_actor(self):
        """
        Does the kettle's heater actor implement set_power()?

        ActorBase.set_power() is a no-op; only GPIOPWM overrides it. Without
        it nothing this plugin or AdvancedPID does reaches the element, and
        heater_on(0.0) in the start path switches a plain relay on anyway.
        """
        try:
            kettle = cbpi.cache.get("kettle")[self.kettle_id]
            heater_id = int(kettle.heater)
            instance = cbpi.cache.get("actors")[heater_id].instance
        except Exception as e:
            self._trace("heater not readable (%s)" % e)
            return False
        return getattr(type(instance), "set_power", None) is not ActorBase.set_power

    def _unit_is_celsius(self):
        try:
            return str(cbpi.get_config_parameter("unit", "C")) == "C"
        except Exception:
            # Config cache is not populated yet - assume the CBP default
            # rather than blocking the run.
            return True

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def run(self):

        if not self._unit_is_celsius():
            self._fail(
                "This plugin calculates in degrees Celsius (relay band, water "
                "heat capacity). Switch the backend to °C before tuning."
            )
            return

        if not self._is_pwm_actor():
            self._fail(
                "The heater actor of this kettle does not implement "
                "set_power() - it has to be a GPIOPWM actor. With GPIOSimple "
                "or RelayBoard nothing this plugin computes reaches the "
                "element."
            )
            return

        outstep = float(self.a_outstep)
        maxoutput = min(float(self.b_maxoutput), 100.0)
        lookback = float(self.c_lookback)
        noiseband = float(self.d_noiseband)
        sample_time = float(self.e_sample_time)
        lambda_s = float(self.f_lambda)
        heater_power = float(self.g_heater_power)
        volume = float(self.h_kettle_volume)
        room_temp = float(self.i_room_temperature)
        resolution = float(self.j_sensor_resolution)

        if outstep < 1.0:
            self._fail("Output step % must be at least 1")
            return
        if sample_time < 1.0:
            self._fail("Sample time must be at least 1 s")
            return
        if lookback < sample_time * 3:
            self._fail(
                "Lookback (%s s) must be at least three times the sample time "
                "(%s s) - otherwise no peak can be recognised."
                % (lookback, sample_time)
            )
            return
        if maxoutput <= 0.0:
            self._fail("Max. output % must be positive")
            return
        if noiseband <= 0.0:
            self._fail("Noise band must be positive")
            return
        if lambda_s <= 0.0:
            self._fail("Target loop time constant must be positive")
            return
        if heater_power <= 0.0:
            self._fail("Heater power must be positive")
            return
        if volume <= 0.0:
            self._fail("Kettle volume must be positive")
            return

        if abs(outstep - maxoutput) > 1e-6:
            self._trace(
                "output step %s does not match max output %s - corrected to %s. "
                "A step below the maximum ramps the output instead of "
                "switching it and Ku would be from the wrong relay amplitude."
                % (outstep, maxoutput, maxoutput)
            )
            self.notify(
                "AutoTune corrected",
                "Output step was %s %% but max. output is %s %%. The relay "
                "only switches correctly with equal values, so the step was "
                "set to %s %% for this run."
                % (outstep, maxoutput, maxoutput),
                type="warning",
            )
            outstep = maxoutput

        setpoint = self.get_target_temp()

        if setpoint is None or setpoint <= 0:
            self._fail(
                "This kettle has no target temperature. Set one before "
                "running the autotune - the run needs a setpoint to oscillate "
                "around."
            )
            return

        try:
            tuner = RelayAutoTuner(
                setpoint,
                outstep,
                sample_time,
                lookback,
                0.0,
                maxoutput,
                noiseband,
            )
        except Exception as e:
            self._fail(str(e))
            return

        self.notify(
            "AutoTune running",
            "Tuning towards %s degrees. Expect the heater to switch between "
            "0 %% and %s %% for a while - leave this alone until it finishes. "
            "Details in %s." % (setpoint, maxoutput, TRACE_LOG),
            type="info",
            timeout=None,
        )
        self._trace(
            "start: setpoint=%s outstep=%s maxoutput=%s lookback=%s "
            "noiseband=%s sample=%s lambda=%s power=%s volume=%s room=%s"
            % (
                setpoint, outstep, maxoutput, lookback, noiseband,
                sample_time, lambda_s, heater_power, volume, room_temp,
            )
        )

        result = None
        try:
            # heater_on(0.0) is not cosmetic: for GPIOPWM it is what creates
            # the PWM handle that every later set_power() writes to.
            self.heater_on(0.0)

            applied = None
            while self.is_running():
                current = self.get_temp()

                if current is None:
                    self._fail(
                        "This kettle's sensor returned no reading. The autotune "
                        "cannot identify a kettle it cannot measure - check "
                        "the sensor first."
                    )
                    return

                if tuner.update(current):
                    break

                output = tuner.output

                # Only on change. actor_power() emits SWITCH_ACTOR to every
                # connected client on every call, and the relay holds each
                # output for a whole cycle - re-sending it is pure noise.
                if output != applied:
                    self.actor_power(output)
                    applied = output

                self._trace(
                    "output=%s%% input=%s peaks=%s amplitude=%s"
                    % (output, round(current, 2), tuner.peak_count,
                       round(tuner.induced_amplitude, 3))
                )
                self.sleep(sample_time)

            result = self._result(
                tuner, setpoint, room_temp, heater_power, volume,
                lambda_s, sample_time, resolution, maxoutput, noiseband,
            )

        except Exception as e:
            logger.exception("AdvancedPIDAutoTune: run aborted")
            self._fail("AutoTune aborted: %s" % e)
            return

        finally:
            self._cleanup()

        self._report(result)

        # The kettle is handed back on manual. run() is over, the heater is
        # off and the controller is finished with its job - leaving the kettle
        # showing "automatic" over a controller that drives nothing is the
        # one state where the UI lies about what is regulating the kettle.
        # The brewer enters the values and switches automatic back on.
        self._auto_off()

    # ------------------------------------------------------------------
    # result
    # ------------------------------------------------------------------

    def _result(self, tuner, setpoint, room_temp, heater_power, volume,
                lambda_s, sample_time, resolution, maxoutput, noiseband):
        """
        Turn Ku, Pu and the measured mean output into a full set of
        AdvancedPID settings.
        """
        # The window has to cover at least two whole cycles: a window that
        # ends mid-cycle is biased by wherever in the cycle it happens to
        # stop, and on a large kettle one cycle is 12 minutes or more.
        window = OUTPUT_HISTORY
        if tuner.pu > 0:
            window = max(600.0, 2.0 * tuner.pu)
        mean_output = tuner.mean_output(min(window, OUTPUT_HISTORY))
        delta_t = setpoint - room_temp

        result = {
            "state": tuner.state,
            "setpoint": setpoint,
            "room_temp": room_temp,
            "delta_t": delta_t,
            "amplitude": tuner.induced_amplitude,
            "peak_count": tuner.peak_count,
            "slope": tuner.peak_slope_per_min(),
            "mean_output": mean_output,
            "mean_window": min(window, OUTPUT_HISTORY),
            "mean_reliable": False,
            "ku": 0.0,
            "pu": 0.0,
            "ua": 0.0,
            "tau": 0.0,
            "kdc": 0.0,
            "capacity": 0.0,
            "notes": [],
        }

        if tuner.state != RelayAutoTuner.STATE_SUCCEEDED:
            if tuner.state == RelayAutoTuner.STATE_FAILED:
                result["notes"].append(
                    "The oscillation did not settle within %s half periods. "
                    "Usually the noise band is smaller than the sensor noise, "
                    "or the sample time is too fast for the sensor. Try noise "
                    "band 1.0 and sample time 10 s."
                    % MAX_PEAKS
                )
            else:
                result["notes"].append(
                    "The run ended in state '%s' without a converged "
                    "oscillation, so there are no gains. This should not "
                    "happen - report the run log." % tuner.state
                )
            return result

        result["ku"] = tuner.ku
        result["pu"] = tuner.pu
        result["capacity"] = volume * WATER_HEAT_CAPACITY

        # Mean output <-> heat loss. Independent of the relay: while the
        # kettle oscillates around the setpoint, the mean output is exactly
        # what the element has to put in to cover the losses.
        watts_per_percent = heater_power / 100.0
        if mean_output > 0.5 and delta_t > 0.0:
            result["ua"] = (mean_output / 100.0 * heater_power) / delta_t
            result["tau"] = result["capacity"] / result["ua"]
            result["kdc"] = watts_per_percent / result["ua"]
            result["mean_reliable"] = True

            if 2.0 * tuner.pu > OUTPUT_HISTORY:
                result["notes"].append(
                    "The oscillation period is %s s, so two full cycles are "
                    "%s s - more than the %s s of output history that was "
                    "kept. The mean output is therefore not unbiased and the "
                    "P value derived from it is rough. The classic rule "
                    "below is the safer number here."
                    % (round(tuner.pu, 1), round(2 * tuner.pu, 1),
                       round(OUTPUT_HISTORY, 1))
                )
                result["mean_reliable"] = False

        classic = classic_gains(tuner.ku, tuner.pu, "brewing")

        if result["mean_reliable"] and result["tau"] > lambda_s:
            kp = (result["capacity"] / lambda_s - result["ua"]) / watts_per_percent
            ki = kp / lambda_s
            integrator_initial = mean_output / ki if ki > 0 else 0.0
            max_integrator = abs((maxoutput - 0.0) / ki) if ki > 0 else 0.0
            if abs(integrator_initial) > max_integrator:
                integrator_initial = max_integrator
            method = "lambda"
        else:
            if not result["mean_reliable"]:
                result["notes"].append(
                    "The heater was never off during the run (mean output "
                    "%s %% of %s %%), so no loss figure could be measured and "
                    "the lambda tuning was skipped. The kettle needs to reach "
                    "its target and then fall below it again - check that the "
                    "setpoint is reachable and the sensor is not stuck."
                    % (round(mean_output, 1), maxoutput)
                )
            elif result["tau"] <= lambda_s:
                result["notes"].append(
                    "The open loop time constant of the kettle (%s s) is not "
                    "longer than the requested %s s, so a loop of that speed "
                    "cannot be built - the classic rule below is used "
                    "instead. Lower the target loop time constant or accept "
                    "the fast one."
                    % (round(result["tau"], 1), lambda_s)
                )
            kp = classic.Kp
            ki = classic.Ki
            integrator_initial = 0.0
            method = "classic"

        # Derivative, limited by what the sensor can resolve. AdvancedPID
        # differentiates the raw error without a filter.
        #
        # Td comes from the target loop time constant, not from Pu: Pu = 4*theta
        # only holds for a relay symmetric about the setpoint, and on a large
        # kettle the mean output is a few percent rather than 50 % - the OFF
        # leg takes minutes and stretches the period several fold, while the
        # dead time it is derived from is unchanged. lambda is the number
        # that means what it says.
        td = min(15.0, lambda_s / 40.0)
        noise_limit = (
            DERIVATIVE_NOISE_BUDGET * sample_time / resolution
            if resolution > 0 else float("inf")
        )
        kd = min(kp * td, noise_limit)
        noise_capped = kd < kp * td

        # Likewise from lambda: 30 samples per closed loop time constant is
        # plenty to resolve the correction, and never faster than the sensor
        # poll or every second iteration reads a stale value.
        update_interval = min(max(lambda_s / 30.0, MIN_UPDATE_INTERVAL),
                              MAX_UPDATE_INTERVAL)

        result.update({
            "method": method,
            "kp": kp,
            "ki": ki,
            "kd": kd,
            "ti": (kp / ki) if ki > 0 else 0.0,
            "td": (kd / kp) if kp > 0 else 0.0,
            "td_intended": td,
            "noise_capped": noise_capped,
            "sensor_resolution": resolution,
            "sample_time": sample_time,
            "integrator_initial": integrator_initial,
            "update_interval": update_interval,
            "maxoutput": 100.0,
            "notification_timeout": 10000.0,
            "classic": classic,
            "ziegler_nichols": classic_gains(tuner.ku, tuner.pu,
                                             "ziegler-nichols"),
        })

        if 2.0 * tuner.induced_amplitude < 3.0 * noiseband:
            result["notes"].append(
                "The oscillation was only %s degrees peak-to-peak against a "
                "relay band of %s degrees, so the peaks barely clear the "
                "switching band. Ku and Pu are then no more trustworthy than the "
                "sensor noise - but the recommended P value does not "
                "depend on them, it was computed from the measured heat "
                "loss."
                % (round(2 * tuner.induced_amplitude, 2),
                   round(2 * noiseband, 2))
            )

        return result

    def _report(self, result):
        """Push the result to the notification bell, the trace and a file."""

        kettle = cbpi.cache.get("kettle")[self.kettle_id]
        name = getattr(kettle, "name", self.kettle_id)

        if result["state"] == RelayAutoTuner.STATE_SUCCEEDED:
            text = format_report(name, result)
            self._trace(text.replace("\n", " | "))
            self._write_report(text)

            for note in result["notes"]:
                self.notify("AutoTune note", note, type="warning", timeout=None)

            self.notify(
                "AdvancedPID values",
                "kp %s | ki %s | kd %s   (ti %s s, td %s s, %s tuning)"
                % (round(result["kp"], 2), round(result["ki"], 4),
                   round(result["kd"], 1), round(result["ti"], 1),
                   round(result["td"], 1), result["method"]),
                type="success",
                timeout=None,
            )
            self.notify(
                "AdvancedPID other settings",
                "maxoutput %s %% | integrator initial %s | update interval %s s "
                "| notification %s ms"
                % (round(result["maxoutput"]),
                   round(result["integrator_initial"]),
                   round(result["update_interval"], 1),
                   round(result["notification_timeout"])),
                type="success",
                timeout=None,
            )
            self.notify(
                "AutoTune complete",
                "Kettle '%s' tuned at %s degrees. Auto mode is off - enter "
                "the values above, switch the controller back on and let it "
                "settle. Full report in %s."
                % (name, result["setpoint"], REPORT_FILE),
                type="success",
                timeout=None,
            )
        else:
            self._trace("autotune did not succeed")
            self.notify(
                "AutoTune failed",
                "No usable result for kettle '%s'. See the notes above and "
                "%s." % (name, TRACE_LOG),
                type="danger",
                timeout=None,
            )

    def _write_report(self, text):
        try:
            directory = os.path.dirname(REPORT_FILE)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            with open(REPORT_FILE, "w") as handle:
                handle.write(text)
        except Exception as e:
            logger.warning("AdvancedPIDAutoTune: report not written (%s)" % e)


PIDParams = namedtuple("PIDParams", ["Kp", "Ki", "Kd"])


## Classic Ziegler-Nichols style rules, from the Arduino PID AutoTune library
## this is derived from. Divisors are [P, I, D]: kp = Ku/P, Ti = Pu/I,
## Td = Pu/D. "brewing" is the detuned one, the only rule with a realistic
## chance of holding a temperature for an hour without hunting.
TUNING_RULES = {
    "ziegler-nichols": (34, 40, 160),
    "tyreus-luyben": (44, 9, 126),
    "ciancone-marlin": (66, 88, 162),
    "pessen-integral": (28, 50, 133),
    "some-overshoot": (60, 40, 60),
    "no-overshoot": (100, 40, 60),
    "brewing": (2.5, 3, 3600),
}


def classic_gains(ku, pu, rule="brewing"):
    """
    The classic rule set, in the parameterisation AdvancedPID uses:

        kp = Ku / P
        ki = kp / Ti   with Ti = Pu / I      (so ki = kp * I / Pu)
        kd = kp * Td   with Td = Pu / D
    """
    p_div, i_div, d_div = TUNING_RULES[rule]
    kp = ku / p_div
    ki = kp * i_div / pu if pu > 0 else 0.0
    kd = kp * pu / d_div
    return PIDParams(kp, ki, kd)


class RelayAutoTuner(object):
    """
    Relay feedback autotune.

    Same construction as the Arduino PID AutoTune library, with the output
    as an accumulating ramp (upstream CBP port) rather than a fixed-amplitude
    relay. The ramp only coincides with a relay while output step == max
    output, which the controller enforces before it gets here.
    """

    STATE_OFF = "off"
    STATE_STEP_UP = "relay step up"
    STATE_STEP_DOWN = "relay step down"
    STATE_SUCCEEDED = "succeeded"
    STATE_FAILED = "failed"

    def __init__(self, setpoint, outputstep=10, sampleTimeSec=5,
                 lookbackSec=60, outputMin=float("-inf"),
                 outputMax=float("inf"), noiseband=0.5, getTimeMs=None):
        if setpoint is None:
            raise ValueError("Kettle setpoint must be specified")
        if outputstep < 1:
            raise ValueError("Output step % must be greater or equal to 1")
        if sampleTimeSec < 1:
            raise ValueError("Sample time must be greater or equal to 1")
        if lookbackSec < sampleTimeSec * 3:
            raise ValueError(
                "Lookback must be at least three times the sample time"
            )
        if noiseband <= 0:
            raise ValueError("Noise band must be positive")
        if outputMin >= outputMax:
            raise ValueError("Min output % must be less than max output %")

        self._inputs = deque(maxlen=int(round(lookbackSec / sampleTimeSec)))
        self._outputHistory = deque(
            maxlen=max(4, int(round(OUTPUT_HISTORY / sampleTimeSec)))
        )
        self._sampleTime = sampleTimeSec * 1000.0
        self._setpoint = setpoint
        self._outputstep = outputstep
        self._noiseband = noiseband
        self._outputMin = outputMin
        self._outputMax = outputMax
        self._getTimeMs = getTimeMs or self._currentTimeMs

        self._state = self.STATE_OFF
        self._peakTimestamps = deque(maxlen=5)
        self._peaks = deque(maxlen=5)

        self._output = 0.0
        self._lastRunTimestamp = 0.0
        self._peakType = 0
        self._peakCount = 0
        self._inducedAmplitude = 0.0
        self.ku = 0.0
        self.pu = 0.0

    @property
    def state(self):
        return self._state

    @property
    def output(self):
        return self._output

    @property
    def peak_count(self):
        return self._peakCount

    @property
    def induced_amplitude(self):
        return self._inducedAmplitude

    def peak_slope_per_min(self):
        """
        Observed temperature change per minute between the last two peaks.

        Not the physical heating rate. Every leg the kettle spends flat at the
        start and the end while the heater output is already switched or
        already cut - the dead time - so the real gradient is this divided by
        (dt - 2*theta). With theta unknown here, this stays an observed rate
        and is reported as such, for spotting a kettle that does not move.

        The +1 on the timestamp index is not a fudge. _initTuner seeds
        _peakTimestamps with the start time so that Pu can be read off two
        intervals further down the deque, and that seed never gets a matching
        entry in _peaks. Peak n therefore lives at index n in _peaks and
        n + 1 in _peakTimestamps until the seed is pushed out of the deque by
        the sixth inflection.
        """
        if len(self._peaks) < 2:
            return 0.0
        if len(self._peakTimestamps) == len(self._peaks) + 1:
            stamps = list(self._peakTimestamps)[1:]
        else:
            stamps = list(self._peakTimestamps)
        if len(stamps) < 2:
            return 0.0
        minutes = (stamps[-1] - stamps[-2]) / 60000.0
        if minutes <= 0:
            return 0.0
        return (self._peaks[-1] - self._peaks[-2]) / minutes

    def mean_output(self, windowSec):
        """
        Mean output over the last windowSec seconds.

        Only samples from after the first peak are recorded: before the
        relay has caught the setpoint the output is at the maximum and the
        kettle is still climbing, and averaging that in would overestimate
        the heat loss badly.
        """
        now = self._getTimeMs()

        if not self._outputHistory:
            return 0.0

        cutoff = now - windowSec * 1000.0
        total = 0.0
        count = 0
        for stamp, output in self._outputHistory:
            if stamp >= cutoff:
                total += output
                count += 1

        # Plain arithmetic, not time weighted: the readings arrive at a fixed
        # sample interval, so every one of them stands for the same slice of
        # time. Weighting by age would give the oldest sample - the one that
        # may be half a cycle out of phase - the largest share.
        return total / count if count else 0.0
    def update(self, inputValue):
        """Feed one reading. Returns True when the run is over."""
        now = self._getTimeMs()

        if self._state in (self.STATE_OFF, self.STATE_SUCCEEDED,
                           self.STATE_FAILED):
            self._initTuner(now)
        elif (now - self._lastRunTimestamp) < self._sampleTime:
            return False

        self._lastRunTimestamp = now

        if (self._state == self.STATE_STEP_UP
                and inputValue > self._setpoint + self._noiseband):
            self._state = self.STATE_STEP_DOWN
        elif (self._state == self.STATE_STEP_DOWN
                and inputValue < self._setpoint - self._noiseband):
            self._state = self.STATE_STEP_UP

        if self._state == self.STATE_STEP_UP:
            self._output += self._outputstep
        elif self._state == self.STATE_STEP_DOWN:
            self._output -= self._outputstep

        self._output = min(self._output, self._outputMax)
        self._output = max(self._output, self._outputMin)

        isMax = True
        isMin = True
        for value in self._inputs:
            isMax = isMax and (inputValue > value)
            isMin = isMin and (inputValue < value)

        self._inputs.append(inputValue)

        if self._peakCount >= 1:
            self._outputHistory.append((now, self._output))

        if len(self._inputs) < self._inputs.maxlen:
            return False

        inflection = False
        if isMax:
            if self._peakType == -1:
                inflection = True
            self._peakType = 1
        elif isMin:
            if self._peakType == 1:
                inflection = True
            self._peakType = -1

        if inflection:
            self._peakCount += 1
            self._peaks.append(inputValue)
            self._peakTimestamps.append(now)

        # Amplitude has settled when the last peaks no longer grow.
        if inflection and self._peakCount > 4:
            # Die Amplitude wird **neu berechnet**, nicht auf dem
            # bisherigen Wert aufaddiert.
            #
            # Vorher stand hier kein Reset, der Wert wurde also ueber
            # die Auswertungen hinweg akkumuliert. Gemessen in einer
            # Kesselsimulation: Auswertung 1 ergab 0,3539 (korrekt),
            # Auswertung 2 dann 0,4034 statt der frisch berechneten
            # 0,3444 - ein Plus von 17 % auf den gemeldeten Ku.
            #
            # Das ist kein Verhalten der Arduino-Vorlage: dort ist die
            # Amplitude eine lokale Variable, die bei jeder Auswertung
            # neu gefuellt wird, und der direkte Vorfahre
            # (cbpi4-PID_AutoTune) setzt die Amplitude vor der
            # Auswertung ausdruecklich auf 0.
            #
            # Der Effekt war doppelt: die gemeldete Amplitude war zu
            # gross, und das Konvergenzkriterium (deviation) wurde
            # gegen einen zu grossen Wert geprueft - der Tuner meldete
            # das "Settled" also frueher und zu Unrecht.
            self._inducedAmplitude = 0.0
            absMax = self._peaks[-2]
            absMin = self._peaks[-2]
            for i in range(0, len(self._peaks) - 2):
                self._inducedAmplitude += abs(self._peaks[i] - self._peaks[i + 1])
                absMax = max(self._peaks[i], absMax)
                absMin = min(self._peaks[i], absMin)

            self._inducedAmplitude /= 6.0

            if self._inducedAmplitude > 0:
                deviation = (
                    (0.5 * (absMax - absMin) - self._inducedAmplitude)
                    / self._inducedAmplitude
                )
                if deviation < PEAK_AMPLITUDE_TOLERANCE:
                    self._state = self.STATE_SUCCEEDED

        if self._peakCount >= MAX_PEAKS:
            self._output = 0.0
            self._state = self.STATE_FAILED
            return True

        if self._state == self.STATE_SUCCEEDED:
            self._output = 0.0
            self.ku = 4.0 * self._outputstep / (self._inducedAmplitude * math.pi)

            period1 = self._peakTimestamps[3] - self._peakTimestamps[1]
            period2 = self._peakTimestamps[4] - self._peakTimestamps[2]
            self.pu = 0.5 * (period1 + period2) / 1000.0
            return True

        return False

    def _currentTimeMs(self):
        return time.time() * 1000.0

    def _initTuner(self, now):
        self._peakType = 0
        self._peakCount = 0
        self._output = 0.0
        self._inducedAmplitude = 0.0
        self.ku = 0.0
        self.pu = 0.0
        self._inputs.clear()
        self._peaks.clear()
        self._peakTimestamps.clear()
        self._outputHistory.clear()
        self._peakTimestamps.append(now)
        self._state = self.STATE_STEP_UP


def format_report(name, result):
    """The report that lands in the notification bell and the report file."""

    lines = []
    add = lines.append

    add("AdvancedPIDAutoTune - result for kettle '%s'" % name)
    add("=" * 62)
    add("")
    add("Run")
    add("  setpoint            %s degC" % result["setpoint"])
    add("  room temperature    %s degC" % result["room_temp"])
    add("  measured            %s degrees above room" % round(result["delta_t"], 2))
    add("  oscillation         %s degC peak-to-peak"
        % round(2 * result["amplitude"], 3))
    add("  peaks counted       %s" % result["peak_count"])

    if result["state"] != RelayAutoTuner.STATE_SUCCEEDED:
        add("")
        add("The run did not settle into a steady oscillation, so there are")
        add("no gains. See the notes in the notification bell.")
        add("")
        for note in result["notes"]:
            add("  - %s" % note)
        return "\n".join(lines)

    add("")
    add("Identified plant")
    add("  Ku (ultimate gain)  %s %%/degC" % round(result["ku"], 2))
    add("  Pu (period)         %s s" % round(result["pu"], 1))
    add("  observed rate        %s degC/min between peaks"
        % round(abs(result["slope"]), 3))
    add("  mean output         %s %% over the last %s s"
        % (round(result["mean_output"], 1), round(result["mean_window"])))

    if result["mean_reliable"]:
        add("  heat loss UA        %s W/K" % round(result["ua"], 2))
        add("  thermal capacity    %s J/K (water only)"
            % round(result["capacity"]))
        add("  open loop tau       %s s" % round(result["tau"], 1))
        add("  DC gain             %s degC per %% output"
            % round(result["kdc"], 3))
    else:
        add("  heat loss UA        not measured")

    add("")
    add("AdvancedPID - recommended")
    add("  tuning method       %s" % result["method"])
    add("  a_kp                %s" % round(result["kp"], 2))
    add("  b_ki                %s" % round(result["ki"], 4))
    add("  c_kd                %s" % round(result["kd"], 1))
    add("  (Ti = %s s)" % round(result["ti"], 1))
    if result["noise_capped"]:
        add("  Td capped          %s s instead of %s s - AdvancedPID"
            % (round(result["td"], 1), round(result["td_intended"], 1)))
        add("  differentiates the raw error without a filter, so a %s degC"
            % result["sensor_resolution"])
        add("  sensor at %s s sampling would swing the heater further than"
            % round(result["sample_time"], 1))
        add("  the %s %% noise budget allows. D has little to do on a"
            % round(DERIVATIVE_NOISE_BUDGET * 100))
        add("  kettle this size anyway - the dead time is short next to")
        add("  the time constant.")
    add("")
    add("AdvancedPID - remaining settings")
    add("  d_maxoutput         %s %%" % round(result["maxoutput"]))
    add("  e_integrator_init   %s" % round(result["integrator_initial"]))
    add("  f_update_interval   %s s" % round(result["update_interval"], 1))
    add("  g_notification_ms   %s" % round(result["notification_timeout"]))

    add("")
    add("Cross check - classic rules on the same Ku / Pu")
    add("  ziegler-nichols     kp %s  ki %s  kd %s"
        % (round(result["ziegler_nichols"].Kp, 2),
           round(result["ziegler_nichols"].Ki, 4),
           round(result["ziegler_nichols"].Kd, 1)))
    add("  brewing             kp %s  ki %s  kd %s"
        % (round(result["classic"].Kp, 2),
           round(result["classic"].Ki, 4),
           round(result["classic"].Kd, 1)))

    if result["notes"]:
        add("")
        add("Notes")
        for note in result["notes"]:
            add("  - %s" % note)

    add("")
    add("Enter the values by hand afterwards - this plugin does not write")
    add("them into the kettle config, so an interrupted run cannot leave a")
    add("half tuned controller behind.")

    return "\n".join(lines)