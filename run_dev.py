#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entwicklungsmodus: den Server starten und bei jeder Aenderung neu starten.

    ./run_dev.py

Der Server laeuft als Kindprozess im Vordergrund, seine Ausgaben stehen
im Terminal. Wird eine Quelldatei geaendert, beendet sich der Server
und startet neu - mit dem Code, der gerade auf der Platte liegt.
Beenden mit Strg+C.

Warum Python und nicht ein Shell-Skript
---------------------------------------
Ein Shell-Skript fuer diesen Zweck stolpert ueber die Signale: bash
fuehrt einen Trap erst aus, wenn der laufende Vordergrundbefehl
fertig ist, und der Waechter wartet endlos auf eine Aenderung. Man
muss den Waechter deshalb in den Hintergrund schieben und mit "wait"
warten - und "wait" ist wiederum die Stelle, an der ein beendeter
Kindprozess zum Zombie wird. In Python ist das eine Zeile:
``KeyboardInterrupt`` und ``Popen.terminate()``.

Zusaetzlich ist der Waechter (tools/watch_changes.py) ohnehin Python.
Die Sprachmixerei aus zwei Skripten waere nur eine weitere Fehlerquelle.

Was beobachtet wird
--------------------
Alle .py-, .sql-, .html- und .yaml-Dateien unter modules/ und update/
sowie run.py und config/schema.sql. Der Waechter sitzt in
tools/watch_changes.py - dort steht auch, was bewusst nicht
beobachtet wird (__pycache__, logs/, das gebaute Frontend-Bundle, die
Datenbank).

Optionen
---------
``--port PORT``     Der Port, auf dem der Server laeuft. Ohne die Option
                    gilt der Port aus der Datenbank (wie beim normalen
                    Start). Praktisch, wenn neben dem laufenden Server
                    entwickelt wird::

                        ./run_dev.py --port 5000

                    Alternativ ueber die Umgebung: ``CBPI_PORT=5000``.

``--log-level LVL`` Das Log-Level. Vorgabe: DEBUG - im Entwicklungsmodus
                    sollen die Detailzeilen kommen, die im Betrieb
                    nur storen. Mit ``--log-level INFO`` (oder
                    ``CBPI_LOG_LEVEL=INFO``) wird es leiser.

``--no-restart``    Den Server starten und nichts beobachten - praktisch
                    fuer den Fall, dass man nur schnell etwas ausprobieren
                    will.

``--crash-guard N`` Nach N schnellen Abstuerzen (Start bis Absturz
                    unter 10 Sekunden) aufgeben, statt ewig neu zu
                    starten. Vorgabe: 3.

Datenbank
---------
Der Entwicklungsserver benutzt dieselbe Datenbank wie der laufende
Server (craftbeerpi.db). Zwei Dinge sind damit nicht getrennt:

- Der Port. Laeuft der normale Server, belegt er den Port aus der
  Datenbank - dann startet der Entwicklungsserver nicht. Mit
  ``--port`` laeuft er auf einem anderen Port, die Datenbank bleibt
  aber dieselbe.
- Die Migrationen. Sie laufen beim Start und werden in der Datenbank
  vermerkt. Wer den Entwicklungsserver startet, wendet also offene
  Migrationen an - auch auf den Daten der laufenden Instanz.
"""

import argparse
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import watch_changes  # noqa: E402  (Pfad oben gesetzt)


# --- Signalbehandlung ------------------------------------------------------

def _interrupt(signum, frame):
    """
    Strg+C (und SIGTERM) abfangen.

    Der Handler wird ausdruecklich gesetzt, statt sich auf den
    Standard zu verlassen: startet das Skript als Hintergrund-Job einer
    Shell ohne Job-Control, erbt der Prozess "SIGINT ignorieren" - und
    dann beendet Strg+C nichts. Der eigene Handler hebt das auf.
    """
    raise KeyboardInterrupt


def install_signal_handlers():
    signal.signal(signal.SIGINT, _interrupt)
    signal.signal(signal.SIGTERM, _interrupt)


# --- Ausgabe ---------------------------------------------------------------

def say(text=""):
    print(text, flush=True)


def info(text):
    print("  %s" % text, flush=True)


def error(text):
    print("FEHLER: %s" % text, file=sys.stderr, flush=True)


# --- Python ----------------------------------------------------------------

def interpreter():
    """
    Der Interpreter, mit dem der Server laeuft.

    Im virtualenv, weil das System-Python unter Bookworm weder Flask
    noch flask-socketio in der passenden Fassung hat. Ohne virtualenv
    laeuft der Server gar nicht erst.
    """
    venv = os.path.join(ROOT, ".venv", "bin", "python")
    if os.path.isfile(venv):
        return venv
    return sys.executable


# --- Port ------------------------------------------------------------------

def port_from_db():
    """Der Port aus der Datenbank - oder None, wenn keiner steht."""
    db_path = os.path.join(ROOT, "craftbeerpi.db")
    if not os.path.isfile(db_path):
        return None
    try:
        db = sqlite3.connect(db_path)
        row = db.execute("SELECT value FROM config WHERE name='port'").fetchone()
        db.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        return int(str(row[0]).strip())
    except (TypeError, ValueError):
        return None


def port_free(port):
    """
    Ist der Port noch frei?

    Binden ist die richtige Probe: ein Server, der da lauscht, laesst
    sich nicht binden. Ein Verbindungsversuch wuerde auch bei einem
    Socket im Status TIME_WAIT scheitern - der Port ist dann aber
    trotzdem benutzbar.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


# --- Server ----------------------------------------------------------------

class Server(object):
    """Der Server als Kindprozess."""

    def __init__(self, python, port, log_level):
        self.python = python
        self.port = port
        self.log_level = log_level
        self.process = None
        self.started_at = 0.0

    def start(self):
        env = os.environ.copy()
        env["CBPI_PORT"] = str(self.port)
        env["CBPI_LOG_LEVEL"] = self.log_level
        # Das Log geht in den Bildschirm, nicht in logs/app.log. So
        # steht alles nebeneinander - und das Logfile des laufenden
        # Servers bleibt unberuehrt.
        env["CBPI_LOG_STDOUT"] = "1"

        self.process = subprocess.Popen(
            [self.python, os.path.join(ROOT, "run.py")],
            cwd=ROOT,
            env=env,
        )
        self.started_at = time.time()
        info("Server laeuft (PID %d)" % self.process.pid)

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def stop(self):
        """Den Server beenden - und warten, bis er wirklich weg ist."""
        if self.process is None:
            return

        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                info("Nach 10s noch aktiv - SIGKILL.")
                self.process.kill()
                self.process.wait()
        else:
            # Der Prozess ist schon tot - nur noch die Ausgabe holen,
            # damit kein "Zombie" zurueckbleibt.
            self.process.wait()
        self.process = None

    def runtime(self):
        return time.time() - self.started_at


# --- Ablauf ----------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Server starten und bei jeder Aenderung neu starten.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--port", type=int, default=None,
                        help="Port des Servers (Vorgabe: der Port aus "
                             "der Datenbank).")
    parser.add_argument("--log-level", default=None,
                        help="Log-Level: DEBUG, INFO, WARNING, ERROR. "
                             "Vorgabe: DEBUG")
    parser.add_argument("--no-restart", action="store_true",
                        help="Nicht beobachten - nur starten.")
    parser.add_argument("--crash-guard", type=int, default=3,
                        help="Nach wie vielen schnellen Abstuerzen "
                             "aufgeben (Vorgabe: 3).")
    return parser.parse_args()


def main():
    args = parse_args()

    install_signal_handlers()

    python = interpreter()
    port = args.port or port_from_db() or 5000
    log_level = (args.log_level or os.environ.get("CBPI_LOG_LEVEL")
                 or "DEBUG").upper()

    say("CraftBeerPi im Entwicklungsmodus")
    info("Projekt: %s" % ROOT)
    info("Port:    %d" % port)
    info("Python:  %s" % python)
    info("Log:     logs/app.log")
    info("Ende:    Strg+C")
    say()

    if not port_free(port):
        error("Der Port %d ist bereits belegt." % port)
        info("Auf dem Port laeuft schon ein CraftBeerPi.")
        info("Ein anderer Port geht mit --port:")
        info("")
        info("    ./run_dev.py --port 5000")
        return 1

    server = Server(python, port, log_level)
    server.start()

    if args.no_restart:
        # Kein Beobachten - der Server laeuft einfach weiter, bis der
        # Nutzer ihn beendet.
        try:
            while True:
                time.sleep(0.5)
                if server.process.poll() is not None:
                    say("Der Server wurde beendet (Exit %s)."
                        % server.process.returncode)
                    return server.process.returncode or 0
        except KeyboardInterrupt:
            say()
            say("Beende ...")
            server.stop()
            return 0

    crashes = 0

    try:
        while True:
            try:
                changed = watch_changes.wait_for_change(interval=0.5,
                                                        settle=0.6,
                                                        pid=server.process.pid)
            except KeyboardInterrupt:
                break

            if changed is None:
                # Der Server ist gestorben.
                code = server.process.poll()
                say()
                if server.runtime() < 10:
                    crashes += 1
                    say("Der Server ist nach %.1fs abgestuerzt (Exit %s)."
                        % (server.runtime(), code))
                    if crashes >= args.crash_guard:
                        error("Er ist %d-mal hintereinander schnell "
                              "abgestuerzt - ich gebe auf." % crashes)
                        say("Die letzten Zeilen aus logs/app.log:")
                        try:
                            with open(os.path.join(ROOT, "logs", "app.log")) as f:
                                tail = f.readlines()[-20:]
                            for line in tail:
                                info("  %s" % line.rstrip())
                        except OSError:
                            pass
                        return 1
                else:
                    say("Der Server wurde beendet (Exit %s) - er startet "
                        "gleich wieder." % code)
                    crashes = 0

                server.stop()
                server.start()
                continue

            # Eine Aenderung - der Server wird neu gestartet.
            say()
            say("Aenderung erkannt:")
            for path in sorted(changed):
                info("  %s" % os.path.relpath(path, ROOT))
            say("Der Server wird neu gestartet.")

            server.stop()
            server.start()

    except KeyboardInterrupt:
        pass

    say()
    say("Beende ...")
    server.stop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
