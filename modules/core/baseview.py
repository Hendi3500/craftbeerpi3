from flask import request, json
from modules.core.classy import route, FlaskView
from modules import cbpi


class BaseView(FlaskView):

    as_array = False
    cache_key = None
    api = cbpi

    @route('/<int:id>', methods=["GET"])
    def getOne(self, id):

        if self.api.cache.get(self.cache_key) is not None:
            return json.dumps(self.api.cache.get(self.cache_key).get(id))
        else:
            return json.dumps(self.model.get_one(id))

    @route('/', methods=["GET"])
    def getAll(self):
        if self.api.cache.get(self.cache_key) is not None:
            return json.dumps(self.api.cache.get(self.cache_key))
        else:
            return json.dumps(self.model.get_all())

    def _pre_post_callback(self, data):
        pass


    def _post_post_callback(self, m):
        pass

    @route('/', methods=["POST"])
    def post(self):
        data = request.json
        self._pre_post_callback(data)
        m = self.model.insert(**data)
        if self.api.cache.get(self.cache_key) is not None:
            self.api.cache.get(self.cache_key)[m.id] = m

        self._post_post_callback(m)

        return json.dumps(m)

    def _pre_put_callback(self, m):
        pass

    def _post_put_callback(self, m):
        pass


    def _get_entry(self, id):
        """
        Den Eintrag mit der Id aus dem Cache holen, oder None.

        Fehlt er im Cache, wird die Datenbank gefragt. Ein Client kann
        eine Id schicken, die es nicht (mehr) gibt - etwa, weil sein
        Zustand aelter ist als der des Backends. Das war kein
        theoretischer Fall: die Oberflaeche hat einen Fermenter geloescht,
        der im Backend schon weg war, und bekam einen 500er mit
        KeyError statt einer sauberen Antwort.

        Liegt die Zeile in der Datenbank, aber nicht im Cache, wird sie
        nachgetragen - der Cache ist dann der aeltere Teil.
        """
        cache = self.api.cache.get(self.cache_key)

        if cache is None:
            return None

        entry = cache.get(id)

        if entry is None:
            entry = self.model.get_one(id)
            if entry is not None:
                cache[id] = entry

        return entry

    @route('/<int:id>', methods=["PUT"])
    def put(self, id):
        data = request.json
        data["id"] = id
        try:
            del data["instance"]
        except:
            pass
        if self.api.cache.get(self.cache_key) is not None:
            entry = self._get_entry(id)
            if entry is None:
                return ('Not found', 404)
            self._pre_put_callback(entry)
            entry.__dict__.update(**data)
            m = self.model.update(**entry.__dict__)
            self._post_put_callback(entry)
            return json.dumps(entry)
        else:
            m = self.model.update(**data)

            self._post_put_callback(m)
            return json.dumps(m)


    def _pre_delete_callback(self, m):
        pass

    def _post_delete_callback(self, id):
        """
        Nach dem Loeschen des Eintrags.

        Der Hook existiert, wurde aber nie aufgerufen: in delete() stand
        statt des Aufrufs eine lokale Funktion mit demselben Namen, die
        nie gelaufen ist. Views, die beim Loeschen noch etwas aufraeumen
        wollen (der Fermenter loescht seine Steps mit), brauchen ihn.
        """
        pass

    @route('/<int:id>', methods=["DELETE"])
    def delete(self, id):
        if self.api.cache.get(self.cache_key) is not None:
            entry = self._get_entry(id)
            if entry is None:
                # Unbekannte Id: 404 statt eines 500ers mit KeyError.
                # Ein Client mit veraltetem Zustand loescht sonst Objekte,
                # die es nicht mehr gibt, und der Server beantwortet das
                # mit einem Stacktrace.
                return ('Not found', 404)
            self._pre_delete_callback(entry)
            del self.api.cache.get(self.cache_key)[id]
        m = self.model.delete(id)
        self._post_delete_callback(id)
        return ('',204)

    @classmethod
    def post_init_callback(cls, obj):
        pass

    @classmethod
    def init_cache(cls):
        with cls.api.app.app_context():

            if cls.model.__as_array__ is True:
                cls.api.cache[cls.cache_key] = []

                for value in cls.model.get_all():
                    cls.post_init_callback(value)
                    cls.api.cache[cls.cache_key].append(value)
            else:
                cls.api.cache[cls.cache_key] = {}
                for key, value  in cls.model.get_all().items():
                    cls.post_init_callback(value)
                    cls.api.cache[cls.cache_key][key] = value