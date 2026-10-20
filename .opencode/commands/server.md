---
description: CraftBeerPi-Server starten, stoppen, neu starten oder Status abfragen
---

# CraftBeerPi-Serververwaltung

Der Nutzer will den CraftBeerPi-Server **$ARGUMENTS**.

Fuehre genau einen Befehl aus - passend zu dem, was der Nutzer
verlangt hat. Der Aufruf lautet immer:

```
./tools/serverctl.sh <befehl>
```

Die Befehle und ihre Bedeutung:

| Befehl | Wirkung |
| --- | --- |
| `start` | Server starten (im Hintergrund, ueberlebt das Terminal) |
| `stop` | Server beenden - **verweigert** den Stopp, solange ein Brauschritt laeuft |
| `stop --force` | Server auch bei laufendem Brauschritt beenden |
| `restart` | Beenden und neu starten |
| `status` | Zustand anzeigen (laufend/gestoppt, Port, Brauschritt) |

## Wichtig: der Stopp waehrend eines Brauschritts

`stop` **ohne** `--force` verweigert den Stopp, wenn ein Brauschritt
laeuft, und sagt warum: Der PID-Regler, der die Heizung steuert, laeuft
im Serverprozess. Beendet man ihn, heizt der Kessel weiter, ohne
geregelt zu werden.

Wenn `stop` diese Meldung ausgibt, ist das ein **Hinweis, kein
Fehler**. Leite sie dem Nutzer weiter und frage nach, ob er den
Server trotzdem beenden will. Erst wenn er das ausdruecklich
bestätigt, fuehre `./tools/serverctl.sh stop --force` aus.

## Nach dem Befehl

Gib das Ergebnis knapp wieder. Was der Nutzer wissen muss:

- **Start**: laeuft der Server jetzt, auf welchem Port, wo liegt das Log.
- **Stopp**: ist er beendet, oder wurde er wegen eines Brauschritts
  verweigert (dann nachfragen, nicht selbst mit `--force` nachsetzen).
- **Status**: laeuft er, lauscht der Port, laeuft ein Brauschritt.

Ergaenze, wenn der Start fehlgeschlagen ist, die letzten Zeilen aus
`logs/server.log` - dort steht, warum.

## Hintergrund

Der Server laeuft im virtualenv (`.venv/bin/python`) und schreibt
sein Log nach `logs/server.log`. Die PID-Datei liegt unter
`logs/server.pid`.

Das Skript laeuft absichtlich **nicht** ueber
`/etc/init.d/craftbeerpiboot`: das setzt root und ein PID-File unter
`/var/run` voraus und existiert nur auf dem Raspberry Pi. So funktioniert
die Aktion auch auf einem Entwicklerrechner.
