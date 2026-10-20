#!/bin/bash
#
# Server-Verwaltung fuer CraftBeerPi: start, stop, restart, status.
#
# Wird von der T3-Code-Aktion /server aufgerufen und kann auch direkt
# in einem Terminal benutzt werden:
#
#     ./tools/serverctl.sh start
#     ./tools/serverctl.sh stop
#     ./tools/serverctl.sh restart
#     ./tools/serverctl.sh status
#
# WICHTIG - der Stopp und der Brauvorgang
# ----------------------------------------
# Ein laufender Brauschritt wird vom Kern ueber einen Zustand "A"
# in der Tabelle "step" markiert. Waehrend ein Schritt laeuft,
# reguliert ein Controller die Heizung - und der Controller ist ein
# Prozess. Beendet man ihn, hoert die Heizung auf, geregelt zu werden.
# Ein Kessel, der auf 100 Grad steht, heizt dann weiter.
#
# Deshalb verweigert "stop" den Stopp waehrend eines Brauschritts und
# sagt, warum. Wer es trotzdem will, muss es ausdruecklich sagen:
#
#     ./tools/serverctl.sh stop --force
#
# Der gleiche Schutz steckt auch im Backend selbst: POST /api/restart
# antwortet in dem Fall mit HTTP 409 (modules/restart/__init__.py).
#
# Wie der Server gestartet wird
# -----------------------------
# Der Server laeuft unter dem Python aus dem virtualenv
# (.venv/bin/python). Das ist wichtig: das System-Python hat unter
# Bookworm weder Flask noch flask-socketio in der passenden Fassung.
# Ohne virtualenv laeuft der Server gar nicht erst.
#
# Das Init-Skript (/etc/init.d/craftbeerpiboot) wird NICHT benutzt -
# es laeuft als root, setzt ein PID-File unter /var/run voraus und
# existiert nur auf dem Raspberry Pi. Dieses Skript laeuft als der
# Benutzer, der das Repository besitzt, und legt seine Datei unter
# logs/. So kann es auch auf einem Entwicklerrechner benutzt werden.
#
# Es laeuft unter dem Init-Skript UND diesem Skript? Dann gibt es
# zwei Server. "status" sagt das, "start" verweigert es.

set -u

# --- Pfade -----------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT" || exit 1

PIDFILE="$ROOT/logs/server.pid"
LOGFILE="$ROOT/logs/server.log"
DBFILE="$ROOT/craftbeerpi.db"
RUNSCRIPT="$ROOT/run.py"

# --- Ausgabe ---------------------------------------------------------------

say()  { printf '%s\n' "$*"; }
info() { printf '  %s\n' "$*"; }
err()  { printf 'FEHLER: %s\n' "$*" >&2; }

# --- Python ----------------------------------------------------------------

if [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    err "Kein Python gefunden. 'install.sh' laufen lassen."
    exit 1
fi

# --- Port aus der Konfiguration -------------------------------------------
# Der Port kommt aus der Datenbank, nicht aus dem Code. Wird er
# geaendert, muss das hier nicht angepasst werden.

read_port() {
    local port=""
    if [ -f "$DBFILE" ]; then
        port="$("$PYTHON" - "$DBFILE" <<'PYEOF' 2>/dev/null
import sqlite3, sys
try:
    db = sqlite3.connect(sys.argv[1])
    row = db.execute("SELECT value FROM config WHERE name='port'").fetchone()
    print(row[0] if row else "")
except Exception:
    print("")
PYEOF
)"
    fi
    # Leer oder unbrauchbar -> der Vorgabewert aus run.py
    case "$port" in
        ''|*[!0-9]*) port=5000 ;;
    esac
    printf '%s' "$port"
}

PORT="$(read_port)"

# --- Brauschritt pruefen ---------------------------------------------------
# "A" = aktiv. Genau diesen Zustand setzt StepView.start(), und genau
# diesen Wert sucht auch der Kern in modules/restart/__init__.py.

brauschritt_aktiv() {
    [ -f "$DBFILE" ] || return 1
    local anzahl
    anzahl="$("$PYTHON" - "$DBFILE" <<'PYEOF' 2>/dev/null
import sqlite3, sys
try:
    db = sqlite3.connect(sys.argv[1])
    row = db.execute("SELECT COUNT(*) FROM step WHERE state='A'").fetchone()
    print(row[0] if row else 0)
except Exception:
    print(0)
PYEOF
)"
    case "$anzahl" in
        ''|*[!0-9]*) anzahl=0 ;;
    esac
    [ "$anzahl" -gt 0 ]
}

# --- PID / Prozess ---------------------------------------------------------

pid_from_file() {
    [ -f "$PIDFILE" ] || return 1
    local pid
    pid="$(cat "$PIDFILE" 2>/dev/null)"
    case "$pid" in
        ''|*[!0-9]*) return 1 ;;
    esac
    kill -0 "$pid" 2>/dev/null || return 1
    printf '%s' "$pid"
}

# Der Prozess laeuft noch, ist aber nicht ueber die PID-Datei zu finden
# (etwa weil die Datei geloescht wurde). Dann hilft nur die Suche nach
# dem Aufruf.
#
# Wichtig: das Muster "[p]ython" statt "python". "pgrep -f" sucht in
# der vollstaendigen Kommandozeile - und die Kommandozeile von pgrep
# selbst enthaelt das Muster. Ohne die Klammer findet pgrep also sich
# selbst und meldet immer eine leere PID, die dann als "laeuft" gilt.

pid_from_process() {
    pgrep -f "[p]ython.*${RUNSCRIPT}" 2>/dev/null | head -1
}

running_pid() {
    local pid
    pid="$(pid_from_file)" && [ -n "$pid" ] && { printf '%s' "$pid"; return 0; }
    pid="$(pid_from_process)" && [ -n "$pid" ] && { printf '%s' "$pid"; return 0; }
    return 1
}

# --- Befehle ---------------------------------------------------------------

do_start() {
    local pid
    if pid="$(running_pid)"; then
        err "Der Server laeuft bereits (PID $pid)."
        info "Port: $PORT"
        info "Mit './tools/serverctl.sh stop' beenden, dann erneut starten."
        return 1
    fi

    if [ ! -f "$RUNSCRIPT" ]; then
        err "run.py nicht gefunden ($RUNSCRIPT)."
        return 1
    fi

    mkdir -p "$ROOT/logs" || return 1

    say "CraftBeerPi wird gestartet (Port $PORT) ..."

    # setsid loest den Prozess vom Terminal - er ueberlebt das Ende
    # des Aufrufs. nohup ignoriert SIGHUP. Die Ausgabe geht in eine
    # eigene Logdatei, damit sie beim naechsten Start nicht
    # ueberschrieben wird.
    setsid nohup "$PYTHON" "$RUNSCRIPT" >>"$LOGFILE" 2>&1 &
    local new_pid=$!
    echo "$new_pid" >"$PIDFILE"

    # Warten, bis der Port wirklich lauscht. Der Import von "modules"
    # dauert je nach Hardware ein paar Sekunden.
    local waited=0
    local max_wait=40
    while [ "$waited" -lt "$max_wait" ]; do
        if ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q .; then
            say "Server laeuft (PID $new_pid, Port $PORT)."
            info "Log: $LOGFILE"
            return 0
        fi
        # Frueher abbrechen, wenn der Prozess schon wieder weg ist.
        if ! kill -0 "$new_pid" 2>/dev/null; then
            err "Der Server ist beim Starten gestorben. Letzte Zeilen aus $LOGFILE:"
            tail -n 15 "$LOGFILE" 2>/dev/null | sed 's/^/    /'
            rm -f "$PIDFILE"
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done

    err "Der Server antwortet nach ${max_wait}s nicht auf Port $PORT."
    info "Der Prozess laeuft (PID $new_pid). Log: $LOGFILE"
    return 1
}

do_stop() {
    local force="${1:-}"
    local pid

    if ! pid="$(running_pid)"; then
        say "Der Server laeuft nicht."
        rm -f "$PIDFILE"
        return 0
    fi

    # Der Schutz gegen den Datenverlust im Brauvorgang.
    if [ "$force" != "--force" ] && brauschritt_aktiv; then
        err "Es laeuft ein Brauschritt - der Server wird NICHT beendet."
        info "Der Controller, der die Heizung regulaert, laeuft im Server."
        info "Nach dem Beenden heizt der Kessel weiter, ohne geregelt zu werden."
        info ""
        info "Wenn das so gewuenscht ist, ausdruecklich bestaetigen:"
        info "    ./tools/serverctl.sh stop --force"
        return 1
    fi

    say "Server wird beendet (PID $pid) ..."

    # SIGTERM zuerst: der Python-Prozess raeumt damit auf. Die
    # Socket.IO-Verbindungen werden geschlossen, die Logdatei wird
    # geflusht.
    kill -TERM "$pid" 2>/dev/null

    local waited=0
    while [ "$waited" -lt 15 ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PIDFILE"
            say "Server beendet."
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done

    # Nach 15s noch da: SIGKILL. Der Server haengt dann meist an
    # einem blockierten Socket.
    info "Nach 15s noch aktiv - SIGKILL."
    kill -KILL "$pid" 2>/dev/null
    sleep 1
    rm -f "$PIDFILE"

    if kill -0 "$pid" 2>/dev/null; then
        err "Der Server laesst sich nicht beenden (PID $pid)."
        return 1
    fi

    say "Server beendet."
    return 0
}

do_status() {
    local pid
    if pid="$(running_pid)"; then
        say "CraftBeerPi laeuft (PID $pid)."
        info "Port: $PORT"
        if ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q .; then
            info "Der Port $PORT lauscht."
        else
            info "Der Port $PORT lauscht NOCH NICHT - der Server startet noch."
        fi
    else
        say "CraftBeerPi laeuft nicht."
        info "Port: $PORT"
    fi

    if brauschritt_aktiv; then
        say ""
        say "Es laeuft ein Brauschritt. Ein Stopp wuerde die Heizung"
        say "unreguliert weiterlaufen lassen."
    fi

    if [ -f "$LOGFILE" ]; then
        info "Log: $LOGFILE"
    fi
    return 0
}

do_restart() {
    # Nur das erste Argument ist das "--force"-Flag. "set -u" ist aktiv,
    # deshalb muss der Default explizit gesetzt werden - ein leeres
    # Argument ist etwas anderes als ein nicht gesetztes.
    local force="${1:-}"
    do_stop "$force" || return 1
    say ""
    do_start
}

# --- Aufruf ----------------------------------------------------------------

BEFEHL="${1:-status}"
shift 2>/dev/null || true

case "$BEFEHL" in
    start)
        do_start
        ;;
    stop)
        do_stop "$@"
        ;;
    restart)
        do_restart "$@"
        ;;
    status)
        do_status
        ;;
    *)
        err "Unbekannter Befehl: $BEFEHL"
        say ""
        say "Erlaubt sind: start, stop, restart, status"
        exit 2
        ;;
esac
