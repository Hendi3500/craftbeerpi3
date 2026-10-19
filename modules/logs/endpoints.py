import datetime
import os
from flask import Blueprint, request, send_from_directory, json
from modules.core.classy import FlaskView, route
from modules import cbpi


class LogView(FlaskView):

    @route('/', methods=['GET'])
    def get_all_logfiles(self):
        result = []
        for filename in os.listdir("./logs"):
            if filename.endswith(".log"):
                result.append(filename)
        return json.dumps(result)

    @route('/actions')
    def actions(self):
        filename = "./logs/action.log"
        if os.path.isfile(filename) == False:
            return json.dumps([])
        import csv
        array = []
        # Textmodus: der CSV-Parser in Python 3 verlangt Strings. Im
        # Binaermodus liefert er Bytes und bricht mit
        # "_csv.Error: iterator should return strings, not bytes" ab.
        with open(filename, 'r', newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                try:
                    array.append([int((datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S") - datetime.datetime(1970, 1, 1)).total_seconds()) * 1000, row[1]])
                except:
                    pass
        return json.dumps(array)

    @route('/<file>', methods=["DELETE"])
    def clearlog(self, file):
        """
        Overload delete method to shutdown sensor before delete
        :param id: sensor id
        :return: HTTP 204
        """
        if not self.check_filename(file):
            return ('File Not Found', 404)

        filename = "./logs/%s" % file
        if os.path.isfile(filename) == True:
            os.remove(filename)
            cbpi.notify("log deleted succesfully", "")
        else:
            cbpi.notify("Failed to delete log", "", type="danger")
        return ('', 204)

    def read_log_as_json(self, type, id):
        filename = "./logs/%s_%s.log" % (type, id)
        if os.path.isfile(filename) == False:
            return []

        import csv
        array = []
        # Textmodus, siehe actions() - der CSV-Parser verlangt Strings.
        with open(filename, 'r', newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                try:
                    array.append([int((datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S") - datetime.datetime(1970, 1, 1)).total_seconds()) * 1000, float(row[1])])
                except:
                    pass
        return array

    def convert_chart_data_to_json(self, chart_data):
        return {"name": chart_data["name"], "data": self.read_log_as_json(chart_data["data_type"], chart_data["data_id"])}

    @route('/<t>/<int:id>', methods=["POST"])
    def get_logs_as_json(self, t, id):
        data = request.json
        result = []

        # Unbekannte Ids: Der Client kann eine Id schicken, die es nicht
        # (mehr) gibt - etwa weil sein Zustand aelter ist als der des
        # Backends. Ohne diese Pruefung gab es hier einen 500er mit
        # AttributeError ('NoneType' hat kein 'logic'/'name'), also
        # dieselbe Fehlerklasse, die modules/core/baseview.py inzwischen
        # mit 404 beantwortet.
        if t == "s":
            sensor = cbpi.cache.get("sensors").get(id)
            if sensor is None:
                return ('Sensor %s not found' % id, 404)
            result.append({"name": sensor.name, "data": self.read_log_as_json("sensor", id)})

        if t == "k":
            kettle = cbpi.cache.get("kettle").get(id)
            if kettle is None:
                return ('Kettle %s not found' % id, 404)
            # list(): map() liefert in Python 3 einen Iterator, den json.dumps
            # nicht serialisieren kann.
            controller = cbpi.get_controller(kettle.logic)
            if controller is None:
                return ('No controller for kettle %s' % id, 404)
            result = [self.convert_chart_data_to_json(x)
                      for x in controller.get("class").chart(kettle)]

        if t == "f":
            fermenter = cbpi.cache.get("fermenter").get(id)
            if fermenter is None:
                return ('Fermenter %s not found' % id, 404)
            controller = cbpi.get_fermentation_controller(fermenter.logic)
            if controller is None:
                return ('No controller for fermenter %s' % id, 404)
            result = [self.convert_chart_data_to_json(x)
                      for x in controller.get("class").chart(fermenter)]

        return json.dumps(result)

    @route('/download/<file>')
    @cbpi.nocache
    def download(self, file):
        if not self.check_filename(file):
            return ('File Not Found', 404)
        # download_name: attachment_filename wurde in Flask 2.2 entfernt.
        return send_from_directory('../logs', file, as_attachment=True, download_name=file)

    def check_filename(self, name):
        import re
        pattern = re.compile('^([A-Za-z0-9-_])+.log$')

        return True if pattern.match(name) else False

@cbpi.initalizer()
def init(app):
    """
    Initializer for the message module
    :param app: the flask app
    :return: None
    """
    LogView.register(cbpi.app, route_base='/api/logs')
