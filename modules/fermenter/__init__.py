import time
from flask import request
from modules.core.classy import route

from modules import DBModel, cbpi, get_db
from modules.core.baseview import BaseView


class Fermenter(DBModel):
    __fields__ = ["name", "brewname", "sensor", "sensor2", "sensor3", "heater", "cooler",  "logic",  "config",  "target_temp"]
    __table_name__ = "fermenter"
    __json_fields__ = ["config"]

class FermenterStep(DBModel):
    __fields__ = ["name", "days", "hours", "minutes", "temp", "direction", "order", "state", "start", "end", "timer_start", "fermenter_id"]
    __table_name__ = "fermenter_step"

    @classmethod
    def get_by_fermenter_id(cls, id):
        cur = get_db().cursor()
        cur.execute("SELECT * FROM %s WHERE fermenter_id = ?" % cls.__table_name__,(id,))
        result = []
        for r in cur.fetchall():
            result.append(cls(r))
        return result

    @classmethod
    def get_max_order(cls,id):
        cur = get_db().cursor()
        cur.execute("SELECT max(fermenter_step.'order') as 'order' FROM %s WHERE fermenter_id = ?" % cls.__table_name__, (id,))
        r = cur.fetchone()
        return r.get("order")

    @classmethod
    def update_state(cls, id, state):
        cur = get_db().cursor()
        cur.execute("UPDATE %s SET state = ? WHERE id =?" % cls.__table_name__, (state, id))
        get_db().commit()

    @classmethod
    def update_timer(cls, id, timer):
        cur = get_db().cursor()
        cur.execute("UPDATE %s SET timer_start = ? WHERE id =?" % cls.__table_name__, (timer, id))
        get_db().commit()

    @classmethod
    def get_by_state(cls, state):
        cur = get_db().cursor()
        cur.execute("SELECT * FROM %s WHERE state = ?" % cls.__table_name__, state)
        r = cur.fetchone()
        if r is not None:
            return cls(r)
        else:
            return None

    @classmethod
    def reset_all_steps(cls,id):
        cur = get_db().cursor()
        cur.execute("UPDATE %s SET state = 'I', start = NULL, end = NULL, timer_start = NULL WHERE fermenter_id = ?" % cls.__table_name__, (id,))
        get_db().commit()

class FermenterView(BaseView):
    model = Fermenter
    cache_key = "fermenter"


    def _post_post_callback(self, m):
        m.state = False
        m.steps = []

    def _pre_put_callback(self, m):
        m.state = False
        try:
            m.instance.stop()
        except:
            pass

    def _post_put_callback(self, m):
        m.state = False
        self.reset(int(m.id))

    @route('/<int:id>/targettemp/<temp>', methods=['POST'])
    def postTargetTemp(self, id, temp):
        if temp is None or not temp:
            return ('', 500)
        id = int(id)
        temp = float(temp)
        cbpi.cache.get(self.cache_key)[id].target_temp = float(temp)
        self.model.update(**self.api.cache.get(self.cache_key)[id].__dict__)
        cbpi.emit("UPDATE_FERMENTER_TARGET_TEMP", {"id": id, "target_temp": temp})
        return ('', 204)

    @route('/<int:id>/brewname', methods=['POST'])
    def postBrewName(self, id):
        data = request.json
        brewname = data.get("brewname")
        cbpi.cache.get(self.cache_key)[id].brewname = brewname
        self.model.update(**self.api.cache.get(self.cache_key)[id].__dict__)
        cbpi.emit("UPDATE_FERMENTER_BREWNAME", {"id": id, "brewname": brewname})
        return ('', 204)

    @classmethod
    def post_init_callback(cls, obj):
        obj.steps = FermenterStep.get_by_fermenter_id(obj.id)
        obj.state = False

    @route('/<int:id>/step', methods=['POST'])
    def postStep(self, id):
        data = request.json
        order_max = FermenterStep.get_max_order(id)
        order = order_max + 1 if order_max is not None else 1
        data["order"] = order
        data["days"] = 0 if data["days"] == "" else data["days"]
        data["hours"] = 0 if data["hours"] == "" else data["hours"]
        data["minutes"] = 0 if data["minutes"] == "" else data["minutes"]
        data["temp"] = 0 if data["temp"] == "" else data["temp"]
        data["state"] = "I"
        data["name"] = "NO NAME" if data["name"] == "" else data["name"]
        f = FermenterStep.insert(**data)

        cbpi.cache.get(self.cache_key)[id].steps.append(f)

        cbpi.emit("UPDATE_FERMENTER", cbpi.cache.get(self.cache_key)[id])

        return ('', 204)

    @route('/<int:id>/step/<int:stepid>', methods=["PUT"])
    def putStep(self, id, stepid):
        data = request.json
        # Select modal

        data["id"] = stepid
        data["fermenter_id"] = id

        data["days"] = 0 if data["days"] == "" else data["days"]
        data["hours"] = 0 if data["hours"] == "" else data["hours"]
        data["minutes"] = 0 if data["minutes"] == "" else data["minutes"]

        for s in cbpi.cache.get(self.cache_key)[id].steps:
            if s.id == stepid:
                s.__dict__.update(**data)

                FermenterStep.update(**s.__dict__)
                break
        cbpi.emit("UPDATE_FERMENTER", cbpi.cache.get(self.cache_key)[id])
        return ('', 204)

    @route('/<int:id>/step/<int:stepid>', methods=["DELETE"])
    def deleteStep(self, id, stepid):

        for idx, s in enumerate(cbpi.cache.get(self.cache_key)[id].steps):
            if s.id == stepid:
                del cbpi.cache.get(self.cache_key)[id].steps[idx]
                FermenterStep.delete(s.id)
                break
        cbpi.emit("UPDATE_FERMENTER", cbpi.cache.get(self.cache_key)[id])
        return ('', 204)

    @route('/<int:id>/start', methods=['POST'])
    def start_fermentation(self, id):
        active = None
        for idx, s in enumerate(cbpi.cache.get(self.cache_key)[id].steps):
            if s.state == 'A':
                active = s
                break

        inactive = None
        for idx, s in enumerate(cbpi.cache.get(self.cache_key)[id].steps):
            if s.state == 'I':
                inactive = s
                break

        if active is not None:

            active.state = 'D'
            active.end = time.time()
            FermenterStep.update(**active.__dict__)

            del cbpi.cache["fermenter_task"][id]

        if inactive is not None:
            fermenter = self.get_fermenter(inactive.fermenter_id)
            current_temp = cbpi.get_sensor_value(int(fermenter.sensor))

            inactive.state = 'A'
            inactive.start = time.time()
            inactive.direction = "C" if current_temp >= inactive.temp else "H"
            FermenterStep.update(**inactive.__dict__)

            self.postTargetTemp(id, inactive.temp)

            cbpi.cache["fermenter_task"][id] = inactive

        cbpi.emit("UPDATE_FERMENTER", cbpi.cache.get(self.cache_key)[id])
        return ('', 204)

    @route('/<int:id>/reset', methods=["POST"])
    def reset(self, id):
        FermenterStep.reset_all_steps(id)

        cbpi.cache[self.cache_key][id].steps = FermenterStep.get_by_fermenter_id(id)

        if id in cbpi.cache["fermenter_task"]:
            del cbpi.cache["fermenter_task"][id]

        cbpi.emit("UPDATE_FERMENTER", cbpi.cache.get(self.cache_key)[id])
        return ('', 204)

    @route('/<int:id>/automatic', methods=['POST'])
    def toggle(self, id):
        """
        Automatik- und Handbetrieb umschalten.

        Das State-Flag wird hier nur noch von dem cleared, der auch
        gestoppt hat. Vorher wurde es an drei Stellen umgeschaltet:
        einmal hier nach dem Start, einmal hier nach dem Stop und nochmal
        im Background-Task, wenn der Controller endet. Genau das
        Zurueckkehren loest aber das Stoppen aus - von Automatik auf
        Handbetrieb gewechselt wurde damit:

            1. toggle() -> instance.stop(), state = False (Handbetrieb)
            2. run() kehrt zurueck -> state = True (wieder Automatik)
            3. erst der naechste Druck blieb auf Handbetrieb - ein zweiter
               Stop auf einen bereits toten Controller.

        Der Button stand also gruen, waehrend gar kein Controller mehr lief.
        """
        fermenter = cbpi.cache.get(self.cache_key).get(id)
        if fermenter is None:
            return ('', 404)

        try:
            if getattr(fermenter, "state", False):
                self._stop_fermenter(fermenter)
            else:
                self._start_fermenter(fermenter)
        except Exception as e:
            cbpi.app.logger.error("Switching the fermenter %s failed: %s: %s"
                                   % (id, type(e).__name__, e))
            cbpi.notify("Switching the fermenter failed",
                        "Please check the configuration of %s" % fermenter.name,
                        type="danger", timeout=None)
            # Nie ein Flag stehen lassen fuer einen Controller, der nicht
            # laeuft.
            fermenter.state = False
            return ('', 500)

        return ('', 204)

    def _start_fermenter(self, fermenter):
        """
        Controller aufbauen, auf Automatik stellen und starten.

        Ohne konfigurierten Controller bleibt der Fermenter auf Handbetrieb:
        der Kern hat das Flag auch ohne "logic" gesetzt - der Button waere
        gruen, ohne dass etwas laeuft.
        """
        logic = getattr(fermenter, "logic", None)

        if logic is None:
            cbpi.app.logger.info(
                "Fermenter %s has no controller - stays in manual mode"
                % getattr(fermenter, "name", "?"))
            return

        controller = cbpi.get_fermentation_controller(logic)

        if controller is None:
            cbpi.notify("Fermenter Controller not found",
                        "Please check the logic configuration of %s" % fermenter.name,
                        type="danger", timeout=None)
            return

        cfg = fermenter.config.copy()
        cfg.update(
            dict(api=cbpi, fermenter_id=fermenter.id, heater=fermenter.heater, sensor=fermenter.sensor))
        instance = controller.get("class")(**cfg)
        instance.init()
        fermenter.instance = instance

        # Vor dem Start des Tasks, nicht danach: ein Controller, der
        # sofort endet oder eine Exception wirft, wuerde sonst das gerade
        # gesetzte Flag wieder loeschen.
        fermenter.state = True
        cbpi.emit("UPDATE_FERMENTER", fermenter)

        def run(instance):
            try:
                instance.run()
            except Exception as e:
                cbpi.app.logger.error("The controller of fermenter %s failed: %s: %s"
                                       % (getattr(fermenter, "id", "?"), type(e).__name__, e))
                # Der Brauer sieht im Log nichts. Ohne Meldung auf dem
                # Bildschirm bleibt der Knopf auf Handbetrieb und es sieht
                # aus, als waere der Knopf kaputt.
                try:
                    cbpi.notify("Fermenter controller stopped",
                                "The controller of %s exited with an error: %s"
                                % (getattr(fermenter, "name", "?"), e),
                                type="danger", timeout=None)
                except Exception:
                    pass
            finally:
                self._clear_running(fermenter)

        t = cbpi.socketio.start_background_task(target=run, instance=instance)

    def _stop_fermenter(self, fermenter):
        """
        Controller stoppen und im Handbetrieb lassen.

        Das Flag wird hier und nirgends sonst geloescht, damit das
        Zurueckkehren des Controllers es nicht wieder auf Automatik stellt.
        """
        instance = getattr(fermenter, "instance", None)

        if instance is not None:
            instance.stop()

        fermenter.instance = None
        fermenter.state = False
        cbpi.emit("UPDATE_FERMENTER", fermenter)

    def _clear_running(self, fermenter):
        """
        Zurueck auf Handbetrieb, wenn der Controller von sich aus endet.

        Nur wenn das Flag noch gesetzt ist: beim manuellen Stop hat
        _stop_fermenter() es bereits geloescht, der Schritt entfaellt dann.
        """
        if not getattr(fermenter, "state", False):
            return

        fermenter.state = False
        cbpi.emit("UPDATE_FERMENTER", fermenter)

    def get_fermenter(self, id):
        return cbpi.cache["fermenter"].get(id)

    def target_temp_reached(self,id, step):
        timestamp = time.time()

        days = step.days * 24 * 60 * 60
        hours = step.hours * 60 * 60
        minutes = step.minutes * 60
        target_time = days + hours + minutes + timestamp

        FermenterStep.update_timer(step.id, target_time)

        step.timer_start = target_time

        cbpi.emit("UPDATE_FERMENTER", cbpi.cache.get(self.cache_key)[id])

    def check_step(self):
        for key, value in cbpi.cache["fermenter_task"].items():

            try:
                fermenter = self.get_fermenter(key)
                current_temp = current_temp = cbpi.get_sensor_value(int(fermenter.sensor))

                if value.timer_start is None:

                    if value.direction == "H" :

                        if current_temp >= value.temp:
                            self.target_temp_reached(key,value)
                    else:
                        if current_temp <= value.temp:
                            self.target_temp_reached(key, value)
                else:
                    if time.time() >= value.timer_start:
                        self.start_fermentation(key)
                    else:
                        pass
            except Exception as e:
                pass


@cbpi.backgroundtask(key="read_target_temps_fermenter", interval=5)
def read_target_temps(api):
    """
    background process that reads all passive sensors in interval of 1 second
    :return: None
    """
    result = {}
    for key, value in cbpi.cache.get("fermenter").items():
        cbpi.save_to_file(key, value.target_temp, prefix="fermenter")


instance = FermenterView()

@cbpi.backgroundtask(key="fermentation_task", interval=1)
def execute_fermentation_step(api):
    with cbpi.app.app_context():
        instance.check_step()


def init_active_steps():
    '''
    active_steps = FermenterStep.query.filter_by(state='A')
    for a in active_steps:
        db.session.expunge(a)
        cbpi.cache["fermenter_task"][a.fermenter_id] = a
    '''

@cbpi.initalizer(order=1)
def init(cbpi):

    FermenterView.register(cbpi.app, route_base='/api/fermenter')
    FermenterView.init_cache()
