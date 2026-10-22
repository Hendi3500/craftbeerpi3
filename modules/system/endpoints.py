import yaml
from flask import json, url_for, Response
from modules.core.classy import FlaskView, route
from git import Repo, Git

from modules.app_config import cbpi

import pprint
import time


class SystemView(FlaskView):
    """
    System-Endpunkte. Erbt bewusst nicht von BaseView - der braucht ein
    Modell, das es hier nicht gibt. ``api`` wird trotzdem gesetzt, damit
    die Hintergrundtasks ueber cbpi.socketio laufen.
    """

    api = cbpi

    def _schedule_power_action(self, command):
        """
        Neustart bzw. Herunterfahren einplanen.

        Wichtig: das passiert als Hintergrundtask, **nachdem** die Antwort
        raus ist. Vorher lief der Befehl im Request-Thread: die Antwort
        wurde 5 Sekunden lang blockiert und kam gar nicht mehr an, weil der
        Rechner vorher schon runterfuhr. Der Browser sah einen Timeout
        statt der Bestaetigung.

        ``call`` bekommt eine Liste, kein String: mit einem String sucht
        subprocess auf POSIX einProgramm namens "halt" im PATH und
        scheitert - "halt" ist ein systemctl-Unterbefehl, kein Programm.
        """
        def execute():
            time.sleep(5)
            from subprocess import call
            try:
                call([command])
            except Exception as e:
                self.api.app.logger.error("%s failed: %s" % (command, e))

        self.api.socketio.start_background_task(target=execute)

    def doShutdown(self):
        self._schedule_power_action("halt")

    @route('/shutdown', methods=['POST'])
    def shutdown(self):
        """
        Shutdown hook
        :return: HTTP 204
        """
        self.doShutdown()

        return ('', 204)

    def doReboot(self):
        self._schedule_power_action("reboot")

    @route('/reboot', methods=['POST'])
    def reboot(self):
        """
        Reboot hook
        :return: HTTP 204
        """
        self.doReboot()

        return ('', 204)

    @route('/tags/<name>', methods=['GET'])
    def checkout_tag(self, name):
        """
        Auf einen Git-Tag auswechseln.

        Wichtig: dieser Endpunkt war zweimal die Ursache fuer einen
        Datenverlust. Er resetet den Arbeitsbaum mit "git reset --hard"
        und checkoutet danach - das verwirft **alle** uncommitteten
        Aenderungen und stellt den Code auf den Stand des Tags zurueck.
        Ein GET darf aber keine Seiteneffekte haben, und ein versehent-
        liches Aufrufen (Browser-Prefetch, Link im Chat, Crawler) hat so
        schon zweimal den kompletten Port vernichtet (19.10.2026).

        Deshalb gilt jetzt:
          1. Der Tag-Name wird gegen die tatsaechlich vorhandenen Tags
             geprueft. Freier Text kann nichts ausloesen.
          2. Ist der Arbeitsbaum schmutzig (uncommittete Aenderungen),
             wird der Checkout **verweigert** und mit HTTP 409 gemeldet.
          3. **Der Ziel-Tag muss den aktuellen Stand enthalten.**
             Genau daran scheitert der Angriff: Ein Checkout auf einen
             aelteren Tag (z.B. "3.0" von 2019) entfernt den Port aus
             dem Arbeitsbaum, obwohl der Arbeitsbaum sauber ist und der
             Port committet ist. Schritt 2 allein hat das nicht
             verhindert - er schuetzt nur uncommittete Aenderungen.
             Ein Checkout ist deshalb nur erlaubt, wenn der Tag-Commit
             den aktuellen HEAD **enthaelt** (`git merge-base --is-ancestor
             HEAD <tag>`). Ein aelterer Tag verliert immer Commits aus
             dem Arbeitsbaum und wird mit HTTP 409 abgelehnt.
          4. Vor dem Checkout wird der aktuelle HEAD als Branch
             "backup/pre-tag-checkout" gesichert. Der Zustand vor dem
             Checkout ist damit immer wiederherstellbar.

        Das Frontend ruft den Endpunkt weiterhin per GET auf, deshalb
        bleibt das Verb unveraendert.
        """
        repo = Repo('./')

        # 0. Erst die Tags holen, dann pruefen.
        #
        # Die Reihenfolge war vorher umgekehrt: die Tag-Liste wurde
        # gelesen, und der Fetch passierte erst spaeter, direkt vor dem
        # Checkout. Ein Tag, der nur auf dem Remote existierte und
        # noch nicht lokal geholt war, stand deshalb nicht in der
        # Liste - der Endpunkt antwortete mit HTTP 404 "Unknown tag",
        # obwohl der Tag sehr wohl existierte. Und der Fetch, der ihn
        # geholt haette, kam eine halbe Funktion zu spaet.
        #
        # Der Fetch laeuft jetzt vor der Pruefung. Schlaegt er fehl
        # (kein Remote, kein Netz), laeuft die Pruefung mit den lokal
        # bekannten Tags weiter - ein lokaler Tag ist damit weiterhin
        # auswählbar, und ein Remote-Tag ist nach dem naechsten
        # erfolgreichen Fetch auch verfuegbar.
        try:
            o = repo.remotes.origin
            o.fetch()
        except Exception as e:
            cbpi.app.logger.warning(
                "Tags could not be updated (%s) - only the locally known "
                "tags are offered" % e)

        # 1. Nur existierende Tags zulassen
        try:
            tags = [t.name for t in repo.tags]
        except Exception as e:
            cbpi.app.logger.error("Tags not readable: %s" % e)
            return ('Tags not readable', 500)

        if name not in tags:
            cbpi.app.logger.warning("Checkout rejected: unknown tag '%s'" % name)
            return ('Unknown tag %s' % name, 404)

        # 2. Nicht ueber uncommittete Aenderungen hinwegkommen
        try:
            dirty = repo.is_dirty(untracked_files=False)
        except Exception as e:
            cbpi.app.logger.error("Working tree not checkable: %s" % e)
            return ('Working tree not checkable', 500)

        if dirty:
            cbpi.app.logger.warning(
                "Checkout of '%s' denied: the working tree has "
                "uncommitted changes", name)
            cbpi.notify("Checkout denied",
                        "There are uncommitted changes in the working directory. "
                        "Please commit or reset first.",
                        type="danger", timeout=None)
            return ('Working tree is dirty - commit or stash first', 409)

        # 3. Der Ziel-Tag muss den aktuellen Stand enthalten.
        #    Ein aelterer Tag (z.B. "3.0" von 2019) verliert immer
        #    Commits aus dem Arbeitsbaum - unabhaengig davon, ob der
        #    Arbeitsbaum sauber ist. Genau das hat den Port zerstoert.
        try:
            branch = repo.active_branch
        except Exception:
            branch = None

        if branch is None:
            # Detached HEAD: der Zustand laesst sich keinem Branch zuordnen,
            # ein Checkout koennte ihn ins Nichts zerlegen.
            cbpi.app.logger.warning(
                "Checkout of '%s' denied: HEAD is detached" % name)
            return ('HEAD is detached - refusing to check out a tag', 409)

        try:
            # True, wenn HEAD ein Vorfahr des Tags ist - der Tag enthaelt
            # den aktuellen Stand also und der Checkout verliert nichts.
            contains_current_state = repo.is_ancestor(branch.commit, repo.commit(name))
        except Exception as e:
            cbpi.app.logger.error("Tag history not checkable: %s" % e)
            return ('Tag history not checkable', 500)

        if not contains_current_state:
            cbpi.app.logger.warning(
                "Checkout of '%s' denied: the tag does not contain the current "
                "state of '%s'" % (name, branch.name))
            cbpi.notify("Checkout denied",
                        "The tag '%s' is older than the current state of "
                        "'%s'. A checkout there would remove the commits "
                        "between the tag and the current state from the "
                        "working tree."
                        % (name, branch.name),
                        type="danger", timeout=None)
            return ('Tag %s is older than %s - refusing' % (name, branch.name), 409)

        # 4. Sicherung des aktuellen Stands, bevor der Arbeitsbaum
        #    umgestellt wird. Danach ist der Zustand wiederherstellbar.
        try:
            repo.create_head('backup/pre-tag-checkout', branch.commit)
            cbpi.app.logger.info(
                "Backup for tag checkout created: backup/pre-tag-checkout -> %s"
                % branch.commit.hexsha[:8])
        except Exception as e:
            cbpi.app.logger.error("Backup branch could not be created: %s" % e)
            return ('Could not create backup branch', 500)

        try:
            repo.git.reset('--hard')
            # Der Fetch passiert oben, vor der Tag-Pruefung - hier noch
            # einmal zu holen wuerde nur Zeit kosten.
            g = Git('./')
            g.checkout(name)
        except Exception as e:
            cbpi.app.logger.error("Checkout of '%s' failed: %s" % (name, e))
            cbpi.notify("Checkout failed", str(e), type="danger", timeout=None)
            return ('Checkout failed: %s' % e, 500)

        cbpi.notify("Checkout successful", "Please restart the system")
        return ('', 204)

    @route('/git/status', methods=['GET'])
    def git_status(self):
        repo = Repo('./')
        o = repo.remotes.origin
        o.fetch()
        # Tags
        tags = []
        for t in repo.tags:
            tags.append({"name": t.name, "commit": str(t.commit), "date": t.commit.committed_date,
                         "committer": t.commit.committer.name, "message": t.commit.message})
        try:
            branch_name = repo.active_branch.name
            # test1
        except:
            branch_name = None

        changes = []
        commits_behind = repo.iter_commits('master..origin/master')

        for c in list(commits_behind):
            changes.append({"committer": c.committer.name, "message": c.message})

        return json.dumps({"tags": tags, "headcommit": str(repo.head.commit), "branchname": branch_name,
                           "master": {"changes": changes}})

    @route('/check_update', methods=['GET'])
    def check_update(self):

        repo = Repo('./')
        o = repo.remotes.origin
        o.fetch()
        changes = []
        commits_behind = repo.iter_commits('master..origin/master')

        for c in list(commits_behind):
            changes.append({"committer": c.committer.name, "message": c.message})

        return json.dumps(changes)

    @route('/git/pull', methods=['POST'])
    def update(self):
        repo = Repo('./')
        o = repo.remotes.origin
        info = o.pull()
        cbpi.notify("Pull successful", "The lasted updated was downloaded. Please restart the system")
        return ('', 204)

    @route('/dump', methods=['GET'])
    def dump(self):
        return json.dumps(cbpi.cache)

    @route('/endpoints', methods=['GET'])
    def endpoints(self):
        endpoints = {}
        re =  {
            "swagger": "2.0",
            "host": "",
            "info": {
                "description":"",
                "version": "",
                "title": "CraftBeerPi"
            },
            "schemes": ["http"],
            "paths": endpoints}
        for rule in self.api.app.url_map.iter_rules():
            r = rule
            endpoints[rule.rule] = {}
            if "HEAD" in r.methods: r.methods.remove("HEAD")
            if "OPTIONS" in r.methods: r.methods.remove("OPTIONS")
            for m in rule.methods:
                endpoints[rule.rule][m] = dict(summary="", description="", consumes=["application/json"],produces=["application/json"])

        with open("config/version.yaml", 'r') as stream:

            y = yaml.safe_load(stream)
        return Response(yaml.dump(re), mimetype='text/yaml')



@cbpi.initalizer()
def init(cbpi):

    SystemView.api = cbpi
    SystemView.register(cbpi.app, route_base='/api/system')
