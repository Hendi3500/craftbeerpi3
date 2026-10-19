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

    def _schedule_power_action(self, befehl):
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
        def ausfuehren():
            time.sleep(5)
            from subprocess import call
            try:
                call([befehl])
            except Exception as e:
                self.api.app.logger.error("%s fehlgeschlagen: %s" % (befehl, e))

        self.api.socketio.start_background_task(target=ausfuehren)

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

        # 1. Nur existierende Tags zulassen
        try:
            tags = [t.name for t in repo.tags]
        except Exception as e:
            cbpi.app.logger.error("Tags nicht lesbar: %s" % e)
            return ('Tags nicht lesbar', 500)

        if name not in tags:
            cbpi.app.logger.warning("Checkout abgelehnt: unbekannter Tag '%s'" % name)
            return ('Unknown tag %s' % name, 404)

        # 2. Nicht ueber uncommittete Aenderungen hinwegkommen
        try:
            schmutzig = repo.is_dirty(untracked_files=False)
        except Exception as e:
            cbpi.app.logger.error("Arbeitsbaum nicht prüfbar: %s" % e)
            return ('Arbeitsbaum nicht prüfbar', 500)

        if schmutzig:
            cbpi.app.logger.warning(
                "Checkout von '%s' verweigert: der Arbeitsbaum hat "
                "uncommittete Änderungen", name)
            cbpi.notify("Checkout verweigert",
                        "Es gibt uncommittete Änderungen im Arbeitsverzeichnis. "
                        "Bitte zuerst committen oder zurücksetzen.",
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
                "Checkout von '%s' verweigert: HEAD ist losgeloest" % name)
            return ('HEAD is detached - refusing to check out a tag', 409)

        try:
            # True, wenn HEAD ein Vorfahr des Tags ist - der Tag enthaelt
            # den aktuellen Stand also und der Checkout verliert nichts.
            enthaelt_aktuellen_stand = repo.is_ancestor(branch.commit, repo.commit(name))
        except Exception as e:
            cbpi.app.logger.error("Tag-Historie nicht prüfbar: %s" % e)
            return ('Tag history not checkable', 500)

        if not enthaelt_aktuellen_stand:
            cbpi.app.logger.warning(
                "Checkout von '%s' verweigert: der Tag enthaelt den aktuellen "
                "Stand von '%s' nicht" % (name, branch.name))
            cbpi.notify("Checkout verweigert",
                        "Der Tag '%s' ist älter als der aktuelle Stand von "
                        "'%s'. Ein Checkout dorthin würde die Commits "
                        "zwischen dem Tag und dem aktuellen Stand aus dem "
                        "Arbeitsbaum entfernen."
                        % (name, branch.name),
                        type="danger", timeout=None)
            return ('Tag %s is older than %s - refusing' % (name, branch.name), 409)

        # 4. Sicherung des aktuellen Stands, bevor der Arbeitsbaum
        #    umgestellt wird. Danach ist der Zustand wiederherstellbar.
        try:
            repo.create_head('backup/pre-tag-checkout', branch.commit)
            cbpi.app.logger.info(
                "Sicherung fuer Tag-Checkout angelegt: backup/pre-tag-checkout -> %s"
                % branch.commit.hexsha[:8])
        except Exception as e:
            cbpi.app.logger.error("Sicherungs-Branch nicht anlegbar: %s" % e)
            return ('Could not create backup branch', 500)

        try:
            repo.git.reset('--hard')
            o = repo.remotes.origin
            o.fetch()
            g = Git('./')
            g.checkout(name)
        except Exception as e:
            cbpi.app.logger.error("Checkout von '%s' fehlgeschlagen: %s" % (name, e))
            cbpi.notify("Checkout fehlgeschlagen", str(e), type="danger", timeout=None)
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
        import urllib
        output = []
        vf = self.api.app.view_functions

        for f in self.api.app.view_functions:
            print(f)
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
        pprint.pprint(y)
        pprint.pprint(re)
        return Response(yaml.dump(re), mimetype='text/yaml')



@cbpi.initalizer()
def init(cbpi):

    SystemView.api = cbpi
    SystemView.register(cbpi.app, route_base='/api/system')
