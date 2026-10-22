#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wartet auf eine Aenderung an den Quelldateien und beendet sich dann.

Aufruf (siehe run_dev.py):

    .venv/bin/python tools/watch_changes.py [--pid PID]

Rueckgabewert:
    0  eine Aenderung wurde gefunden. Die geaenderten Dateien stehen
       auf stdout, eine je Zeile, mit Pfad relativ zum Projektwurzel-
       verzeichnis.
    3  der Prozess mit der PID aus --pid ist gestorben
    1  ein Fehler (falsche Parameter)

Warum in Python und nicht in der Shell
--------------------------------------
Die Shell kann Dateien nicht beobachten. Dazu braucht es inotify, und
das liefert nur ein Werkzeug mit: watchexec, entr oder inotifywait.
Die sind auf einem Raspberry Pi nicht vorinstalliert, und nur fuer
"Server bei Aenderung neu starten" noch ein Werkzeug nachinstallieren
zu muessen, ist zu viel. Der Waechter hier kommt ohne zusaetzliche
Abhaengigkeit aus: er vergleicht alle halbe Sekunde die Zeitstempel
der Dateien.

Der Nachteil gegenueber inotify: die Aenderung wird bis zu einer halben
Sekunde spaeter bemerkt. Das ist genau die Zeit, die ein Speichern
braucht - und es ist egal, denn der Server wird ohnehin erst neu
gestartet, wenn die Datei geschrieben ist.

Was beobachtet wird
--------------------
- alle .py-, .sql-, .html- und .yaml-Dateien unter modules/ und update/
- run.py und config/schema.sql

Was nicht beobachtet wird - und warum
--------------------------------------
- __pycache__ : das schreibt Python beim Import selbst. Ohne diese
  Ausnahme startet der Server endlos neu.
- logs/ und upload/ : Laufzeitverzeichnisse, kein Quelltext.
- modules/ui/static/ : das gebaute JavaScript-Bundle. Es wird
  ausgeliefert, nicht ausgewertet - ein Neustart bringt hier nichts.
- craftbeerpi.db : die Datenbank. Die schreibt die laufende Instanz
  selbst; jede Aenderung loese einen Neustart aus, der wieder in die
  Datenbank schreibt.
- modules/ui/src/ : die Quellen des Frontends. Die baut ein
  eigener Build-Schritt; das Ergebnis landet in modules/ui/static/.
"""

import argparse
import os
import sys
import time


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Verzeichnisse, die durchsucht werden.
WATCH_DIRS = ("modules", "update")

# Dateien, die beobachtet werden (Verzeichnisse gibt es dort nicht).
WATCH_FILES = ("run.py", "config/schema.sql")

# Nur diese Endungen zaehlen als Quelltext.
SUFFIXES = (".py", ".sql", ".html", ".yaml", ".yml")

# Verzeichnisse, die komplett ignoriert werden.
# logs/ und upload/ stehen hier nicht drin: sie liegen ausserhalb der
# beobachteten Wurzeln (WATCH_DIRS) und werden ohnehin nie betreten.
SKIP_DIRS = ("__pycache__", ".git", ".venv", "node_modules")

# Pfade (relativ zur Wurzel), die ignoriert werden.
# modules/ui/static/ ist das gebaute Bundle, modules/ui/src/ sind die
# Quellen des Frontends - beide werden ausgeliefert, nicht ausgewertet.
SKIP_PATHS = (os.path.join("modules", "ui", "static"),
              os.path.join("modules", "ui", "src"))


def _norm(path):
    return os.path.normpath(path)


def iter_files():
    """Alle beobachteten Dateien als absolute Pfade."""
    for base in WATCH_DIRS:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, base)):
            dirnames[:] = sorted(
                name for name in dirnames
                if name not in SKIP_DIRS
                and _norm(os.path.relpath(os.path.join(dirpath, name), ROOT)) not in SKIP_PATHS
            )
            for name in sorted(filenames):
                if name.endswith(SUFFIXES):
                    yield os.path.join(dirpath, name)

    for rel in WATCH_FILES:
        path = os.path.join(ROOT, rel)
        if os.path.isfile(path):
            yield path


def snapshot():
    """
    Der Zustand aller beobachteten Dateien.

    Als Schluessel dient der Pfad, als Wert der Zeitstempel und die
    Groesse. Beide zusammen: eine Datei, die in derselben Sekunde
    geschrieben wurde, sieht man an der Groesse, eine, die nur
    angefasst wurde, am Zeitstempel.
    """
    state = {}
    for path in iter_files():
        try:
            stat = os.stat(path)
        except OSError:
            # Die Datei wurde gerade geloescht - das ist eine Aenderung,
            # kein Fehler.
            continue
        state[path] = (stat.st_mtime_ns, stat.st_size)
    return state


def diff(before, after):
    """Die Pfade, die sich zwischen zwei Zuständen geändert haben."""
    changed = set()
    for path in before:
        if path not in after or after[path] != before[path]:
            changed.add(path)
    for path in after:
        if path not in before:
            changed.add(path)
    return changed


def pid_alive(pid):
    """
    Lebt der Prozess noch?

    Ein beendeter Prozess, dessen Eltern ihn noch nicht geerntet hat,
    ist ein Zombie - er steht noch in /proc, nimmt aber nichts mehr an.
    Für den Wächter ist er tot, sonst meldet er einen Absturz, den es
    nicht gibt.
    """
    try:
        with open("/proc/%d/stat" % pid, "r") as handle:
            data = handle.read()
    except OSError:
        return False

    # Der Prozessname steht in Klammern und kann selbst Klammern
    # enthalten ("(python) (worker)"). Deshalb von hinten schneiden:
    # hinter der letzten Klammer steht der Zustand.
    rest = data[data.rfind(")") + 1:].split()
    state = rest[0] if rest else ""
    return state != "Z"


def wait_for_change(interval=0.5, settle=0.6, pid=None):
    """
    Auf eine Aenderung warten.

    :return: Die Liste der geaenderten Pfade, oder None, wenn der
        Prozess mit der PID pid gestorben ist.
    """
    baseline = snapshot()

    while True:
        time.sleep(interval)

        if pid is not None and not pid_alive(pid):
            return None

        current = snapshot()
        if current == baseline:
            continue

        # Eine Aenderung ist da. Jetzt warten, bis die Dateien still
        # sind: ein Editor speichert in mehreren Schritten, und ein
        # "git checkout" fasst viele Dateien hintereinander an. Sonst
        # startet der Server mit einer halb geschriebenen Datei.
        changed = diff(baseline, current)
        last = current
        stable_since = time.time()

        while True:
            time.sleep(0.1)

            now = snapshot()
            if now != last:
                last = now
                changed = diff(baseline, now)
                stable_since = time.time()
                continue

            if time.time() - stable_since >= settle:
                return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, default=None,
                        help="PID des Servers. Beendet sich dieser, "
                             "endet auch der Wächter (Rueckgabewert 3).")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="Abstand zwischen zwei Vergleichen (Sekunden).")
    parser.add_argument("--settle", type=float, default=0.6,
                        help="Wie lange die Dateien still sein muessen, "
                             "bevor gemeldet wird (Sekunden).")
    args = parser.parse_args()

    changed = wait_for_change(interval=args.interval, settle=args.settle,
                              pid=args.pid)

    if changed is None:
        return 3

    for path in sorted(changed):
        print(os.path.relpath(path, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
