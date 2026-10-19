"""
Ersatz fuer flask_classy 0.6.10, das seit 2014 nicht mehr gepflegt wird und
unter Flask 3 nicht laedt.

flask_classy registriert Routen ueber Methodennamen statt ueber HTTP-Verben
und haengt beim Bauen der Regel die Argumente der Methode als URL-Parameter
an (build_rule, flask_classy.py:217-246). Beides wird hier nachgebildet, damit
die 107 Routen unveraendert bleiben - siehe MIGRATION.md.

Der importanteste Unterschied zu einem Standard-MethodView: dispatchiert wird
nach dem Routennamen, nicht nach dem HTTP-Verb. Bei /api/step/ wuerde ein
Standard-MethodView die POST-Route fuer getAll sonst mit der Action-Route
kollidieren lassen.
"""

from flask import request, json
from flask.views import MethodView


class route(object):
    """Dekorator wie flask_classy.route: haengt die Regel an die Funktion."""

    def __init__(self, rule, **options):
        self.rule = rule
        self.options = options

    def __call__(self, f):
        if not hasattr(f, "_rule_cache") or f._rule_cache is None:
            f._rule_cache = {f.__name__: [(self.rule, self.options)]}
        elif f.__name__ not in f._rule_cache:
            f._rule_cache[f.__name__] = [(self.rule, self.options)]
        else:
            f._rule_cache[f.__name__].append((self.rule, self.options))
        return f


class FlaskView(MethodView):
    """
    MethodView mit flask_classy-kompatiblem Routing.

    Unterklassen registrieren sich wie bisher ueber
    ``MyView.register(app, route_base='/api/thing')``.
    """

    route_base = None
    route_prefix = None
    trailing_slash = True
    decorators = []

    # -- URL-Aufbau (flask_classy.build_rule nachgebildet) ---------------

    @classmethod
    def get_route_base(cls):
        route_base = cls.route_base
        if route_base is not None:
            return route_base.strip("/")
        name = cls.__name__
        if name.endswith("View"):
            name = name[:-4]
        return name.lower().strip("/")

    @classmethod
    def build_rule(cls, rule, method=None):
        """
        Baut die URL: route_prefix + route_base + rule, danach die Argumente
        der Methode als URL-Parameter (flask_classy.py:229-246).

        Das ist der Grund fuer /api/step/init_step/<step> - die Regel lautet
        nur "/init_step", das Argument step wird angehaengt.
        """
        parts = []
        if cls.route_prefix:
            parts.append(cls.route_prefix)
        route_base = cls.get_route_base()
        if route_base:
            parts.append(route_base)
        parts.append(rule)

        if method is not None:
            import inspect

            ignored = ["self"] + getattr(cls, "base_args", [])
            for arg in inspect.getfullargspec(method).args:
                if arg not in ignored:
                    parts.append("<%s>" % arg)

        result = "/%s" % "/".join(parts)
        while "//" in result:
            result = result.replace("//", "/")
        return result

    # -- Registrierung ---------------------------------------------------

    @classmethod
    def register(cls, app, route_base=None, subdomain=None, route_prefix=None,
                 trailing_slash=None):
        if route_base:
            cls.route_base = route_base
        if route_prefix:
            cls.route_prefix = route_prefix
        if trailing_slash is not None:
            cls.trailing_slash = trailing_slash

        special_methods = {"get", "put", "patch", "post", "delete", "index"}

        for name, value in inspect_getmembers(cls):
            if name.startswith(("_", "before_", "after_")):
                continue
            # MethodView-Methoden geerbt aus flask.views: gehoeren nicht
            # zur Routen-Deklaration des Projekts
            if name in ("dispatch_request", "methods", "provide_automatic_options"):
                continue

            rule_cache = getattr(value, "_rule_cache", None)

            if rule_cache and name in rule_cache:
                cached = rule_cache[name]
                for idx, (rule_str, options) in enumerate(cached):
                    methods = options.get("methods", ["GET"])
                    # Mehrfach dekorierte Methode: flask_classy vergibt
                    # fuer jede Regel einen eigenen Endpunkt (Zeile 115-118)
                    if options.get("endpoint"):
                        endpoint = options["endpoint"]
                    elif len(cached) == 1:
                        endpoint = "%s:%s" % (cls.__name__, name)
                    else:
                        endpoint = "%s:%s_%d" % (cls.__name__, name, idx)
                    app.add_url_rule(
                        # build_rule ohne method: bei explizitem @route werden
                        # Argumente nicht angehaengt (flask_classy.py:106)
                        cls.build_rule(rule_str),
                        endpoint,
                        cls.as_proxy(name),
                        methods=methods,
                        subdomain=subdomain,
                    )

            elif name in special_methods:
                if name in ("get", "index"):
                    methods = ["GET"]
                else:
                    methods = [name.upper()]
                rule_str = cls.build_rule("/")
                if not cls.trailing_slash:
                    rule_str = rule_str.rstrip("/")
                app.add_url_rule(
                    rule_str,
                    "%s:%s" % (cls.__name__, name),
                    cls.as_proxy(name),
                    methods=methods,
                    subdomain=subdomain,
                )

            else:
                route_str = "/%s/" % name
                if not cls.trailing_slash:
                    route_str = route_str.rstrip("/")
                app.add_url_rule(
                    cls.build_rule(route_str, value),
                    "%s:%s" % (cls.__name__, name),
                    cls.as_proxy(name),
                    subdomain=subdomain,
                )

        if hasattr(cls, "orig_route_base"):
            cls.route_base = cls.orig_route_base
            del cls.orig_route_base

    @classmethod
    def as_proxy(cls, name):
        """Erzeugt die View-Funktion fuer eine Methode (make_proxy_method)."""
        return _BoundProxy(cls, name)


class _BoundProxy(object):
    """
    Bindet den Aufruf an eine View-Instanz.

    flask_classy erzeugt die Instanz einmalig bei register() (Zeile 174) und
    ruft bei jedem Request dieselbe Instanz auf. Das Verhalten bleibt erhalten,
    damit der von BaseView genutzte Zustand stabil bleibt.
    """

    def __init__(self, cls, name):
        self._cls = cls
        self._name = name
        self._instance = None
        self.__name__ = "%s:%s" % (cls.__name__, name)
        self.__doc__ = getattr(getattr(cls, name, None), "__doc__", None)

    def _get_view(self):
        if self._instance is None:
            self._instance = self._cls()
        return self._instance

    def __call__(self, *args, **kwargs):
        return getattr(self._get_view(), self._name)(*args, **kwargs)


def inspect_getmembers(cls):
    import inspect

    return inspect.getmembers(cls, predicate=inspect.isfunction)