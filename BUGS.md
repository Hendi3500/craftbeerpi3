# Bekannte Fehler

Befunde aus dem Code-Audit vom 22.10.2026. Jeder Eintrag nennt die Stelle,
den Fehlerfall (Eingabe/Zustand → falsches Ergebnis) und eine
Fix-Richtung.

Die Befunde sind nach Schweregrad sortiert. **Rot** = Sicherheit oder
Datenverlust, **Gelb** = stiller Fehler im Betrieb, **Blau** = Robustheit
und Best Practices.

Die Testsuite (18 Skripte unter `tools/`) ist grün — die Fehler unten liegen
ausserhalb der getesteten Pfade. Wer einen Eintrag behebt, sollte ihn mit
einem Test absichern.

---

## Rot — Sicherheit und Datenverlust

### B-01 `GET /api/system/endpoints` zerstört die HEAD-Semantik der ganzen App

**Stelle:** `modules/system/endpoints.py:285-289`

```python
for rule in self.api.app.url_map.iter_rules():
    r = rule
    endpoints[rule.rule] = {}
    if "HEAD" in r.methods: r.methods.remove("HEAD")
    if "OPTIONS" in r.methods: r.methods.remove("OPTIONS")
```

`r = rule` ist ein Alias, keine Kopie. `r.methods.remove("HEAD")` mutiert
das Rule-Objekt der Flask-App selbst.

**Fehlerfall:** `HEAD /api/kettle/` liefert **200**. Ein einziger Aufruf von
`GET /api/system/endpoints` entfernt HEAD und OPTIONS aus **allen** Routen
der Anwendung — danach liefert derselbe Request **405**. Betroffen sind
alle Routen, nicht nur die im Endpoint-Dump.

**Verifiziert:** Test-Client, `HEAD /api/kettle/` 200 → 405 nach einem
einzigen `GET /api/system/endpoints`.

**Fix-Richtung:** Die Methodenliste kopieren statt mutieren:
`methods = [m for m in rule.methods if m not in ("HEAD", "OPTIONS")]`.

---

### B-02 Mutierende Endpunkte sind als GET registriert

**Stelle:** `modules/core/classy.py:154-163` (Registrierung ohne `methods=`
→ nur GET) in Verbindung mit den betroffenen View-Methoden.

Betroffene Routen (bestätigt in der URL-Map der laufenden App):

| Route | Wirkung |
|---|---|
| `GET /api/system/doShutdown/` | fährt den Rechner herunter |
| `GET /api/system/doReboot/` | startet den Rechner neu |
| `GET /api/step/stop_step/` | bricht den laufenden Brauschritt ab, setzt die Kesseltemperatur auf 0 |
| `GET /api/actor/toggleTimeJob/<id>/<t>` | schaltet einen Aktor (potenziell die Heizung) an, blockiert den Request-Thread für `t` Sekunden |
| `GET /api/fermenter/target_temp_reached/<id>/<step>` | setzt den Timer eines Schritts |
| `GET /api/fermenter/check_step/` | triggert die Zustandsmaschine der Gärung |

**Fehlerfall:** Ein Link, ein Prefetch oder ein Crawler genügt. `doShutdown`
und `doReboot` haben zusätzlich **keine Authentifizierung** — der Server
bindet an `0.0.0.0`, das Netz ist also der einzige Schutz.

Hinweis: `doShutdown` und `doReboot` haben bereits die POST-Varianten
`/api/system/shutdown` und `/api/system/reboot`. Die GET-Varianten sind
derselbe Code unter einem zweiten Namen.

**Fix-Richtung:** Die Dekoratoren `@route(...)` explizit auf die gewünschte
Methode setzen und die GET-Pendants aus der automatischen Registrierung
nehmen (z. B. mit einem Unterstrich-Präfix, das `classy.py` überspringt).

---

### B-03 Rezept-Import löscht den Brauplan vor dem Fehler-Handler

**Stelle:**
- `modules/recipe_import/beerxml.py:63-64`
- `modules/recipe_import/kbh.py:69-70`
- `modules/recipe_import/restapi.py:35-36`

```python
Step.delete_all()
StepView().reset()

try:
    ...
```

**Fehlerfall:** Ein fehlerhaftes XML, ein fehlendes `BOIL_TIME`, ein
DB-Fehler — alles innerhalb des `try` nach dem Löschen. Der `except`-Zweig
meldet „Failed to load Recipe", aber der **bisherige Brauplan ist bereits
gelöscht**. Der Brauer verliert seine Steps und bekommt eine Fehlermeldung
statt eines Brauplans. Kein Rollback, keine Transaktion.

**Fix-Richtung:** Löschen und Anlegen in eine Transaktion, oder die neuen
Steps zuerst in eine Liste sammeln und erst nach erfolgreichem Import
schreiben.

---

### B-04 Fehlgeschlagene SQL-Migrationen werden dauerhaft übersprungen

**Stelle:** `modules/core/db_mirgrate.py:78`, `:113`, `:146`

Der Fortschritt wird über `SELECT max(version) FROM schema_info` bestimmt.
`schema_info` bekommt **pro erfolgreicher Datei** eine Zeile.

**Fehlerfall:** Datei 1 erfolgreich, Datei 2 schlägt fehl, Datei 3
erfolgreich → `max(version) = 3`. Beim nächsten Start gilt `3 >= 2`, also
wird Datei 2 **nie wieder** ausgeführt. Die Datenbank bleibt halb migriert,
und der Fehler taucht nicht mehr auf.

**Verifiziert:** nachgebaut — `max(version)=3` lässt Datei 2 dauerhaft
überspringen.

Der Kommentar in `db_mirgrate.py:159-162` beschreibt einen Mechanismus,
den es nicht gibt: `current_version` wird zwar lokal korrekt nicht
fortgeschrieben, der *durable* Stand ist aber `max(version)` über alle je
gelungenen Dateien.

**Nicht getestet:** `tools/test_migration.py:151` legt die kaputte Datei
immer als **höchste** Version an — genau die Konstellation, in der der
Fehler sichtbar bleibt.

**Fix-Richtung:** Fortschritt über die *Menge* der angewandten Versionen
(`SELECT version FROM schema_info`), nicht über `max()`. Zusätzlich nach
einem Fehler die Schleife abbrechen statt mit der nächsten Datei
weiterzumachen.

---

### B-05 `install.sh` entfernt eine versionierte Datei aus dem Repository

**Stelle:** `install.sh:70`

```bash
sudo mv ./config/splash.png /usr/share/plymouth/themes/pix/splash.png
```

`mv` **entfernt** die Datei aus dem Arbeitsbaum. `config/splash.png` ist
versioniert (2 MB).

**Fehlerfall:** Nach dem ersten Installlauf zeigt `git status` eine
Löschung, und ein zweiter Installlauf schlägt fehl, weil die Quelle nicht
mehr da ist.

**Fix-Richtung:** `cp` statt `mv`. Zusätzlich braucht das Skript
`set -euo pipefail` (siehe B-11) und ein `cd` ins Skriptverzeichnis
(siehe B-12).

---

## Gelb — stille Fehler im Betrieb

### B-06 `StepBase.get_kettle_temp()` / `get_target_temp()` liefern immer `None`

**Stelle:** `modules/core/step.py:33-37` und `:40-44`

```python
def get_kettle_temp(self, id=None):
    id = int(id)          # <-- int(None) wirft TypeError
    if id is None:        # <-- nicht mehr erreichbar
        id = self.kettle_id
```

`int(id)` steht **vor** der None-Prüfung. `int(None)` wirft `TypeError`, der
von `@cbpi.try_catch(None)` geschluckt wird → Rückgabe `None`. Der
`self.kettle_id`-Fallback ist toter Code.

**Verifiziert:** `get_target_temp()` → `None`, `get_kettle_temp()` → `None`.

Die korrekte Reihenfolge steht in `modules/core/controller.py:114-121`
(`KettleController.get_target_temp`).

**Fix-Richtung:** Die None-Prüfung vor das `int()`.

---

### B-07 `ActorBase.state()` gibt konstant `1` zurück

**Stelle:** `modules/core/hardware.py:103-104`

```python
def state(self):
    return 1
```

Der echte Zustand liegt im Cache-Eintrag (`actor.state`, `core.py`).
`modules/app_config.py:96` serialisiert Aktor-Instanzen über `o.state()`.

**Fehlerfall:** Jeder Aktor wird im Cache-Dump (`/api/system/dump`) und im
Socket-Push als **„an"** gemeldet — auch wenn er aus ist.

**Verifiziert:** `json.dumps(actor_instance)` → `1`, während
`cache["actors"][3].state` → `0`.

**Fix-Richtung:** Die Methode gegen den Cache-Eintrag auswerten lassen
oder den Cache-Zustand statt der Methode serialisieren.

---

### B-08 `DBModel.update()` überschreibt nicht übergebene Spalten mit NULL

**Stelle:** `modules/core/db.py:117-134`

Die UPDATE-Liste wird aus `cls.__fields__` gebaut, die Werte kommen aus
`kwargs.get(f)` — fehlende Keys werden zu `None` → NULL. Zudem fehlt jede
`rowcount`-Prüfung.

**Fehlerfall (verifiziert):**

```python
Config.update(name="unit", value="C")
# vorher : ('unit', 'C', 'select', 'Temperature Unit')
# nachher: ('unit', 'C', None,    None)
```

Typ und Beschreibung des Parameters sind gelöscht. Nach dem nächsten Start
rendert die UI den Parameter als Textfeld statt als Auswahlfeld.

**Teilweise abgefangen:** `CraftBeerPi.set_config_parameter()`
(`modules/core/core.py:249`) übergibt bewusst das vollständige Dict — der
Docstring dort beschreibt genau diesen Fehler. Die Methode selbst bleibt
die Falle für jeden anderen Aufrufer.

**Fix-Richtung:** In `update()` nur die tatsächlich übergebenen Felder
schreiben und `rowcount` prüfen.

---

### B-09 `GET /api/system/endpoints` — toter Code in `modules/system/endpoints.py`

Siehe B-01. Zusätzlich war in der Route ein Debug-Block
(`print(f)` über alle View-Funktionen, `pprint.pprint` zweimal) — der
wurde im Zuge der Bereinigung entfernt.

---

### B-10 Neun Endpunkte antworten mit HTTP 500 statt 404/400

**Stelle und Fehlerfall (alle per Test-Client verifiziert):**

| Aufruf | Fehler |
|---|---|
| `PUT /api/config/unknown` | `KeyError` — unbekannter Config-Name |
| `PUT /api/config/unit` (ohne `value` im Body) | `KeyError` |
| `POST /api/fermenter/999/targettemp/50` | `KeyError` — unbekannte Id |
| `POST /api/kettle/999/targettemp/50` | `KeyError` — unbekannte Id |
| `POST /api/step/sort` (Body ≠ Liste) | `IndexError` |
| `POST /api/actor/999/toggle` | `AttributeError` |
| `POST /api/sensor/999/action/x` | `AttributeError` |
| `POST /api/step/action/x` | `KeyError` |
| `POST /api/recipe/import/v1/` (ohne `steps`) | 500 |

**Kontext:** Genau diese Fehlerklasse hat `modules/core/baseview.py:53-79`
(`_get_entry`) für Sensor, Actor und Kettle bereits behoben — die
404-Antwort samt Test in `tools/test_unbekannte_id.py`. **Config, Fermenter,
Kettle, Steps und Recipe fehlen in dieser Liste.** Die `ConfigView.put`
überschreibt `BaseView.put` und übernimmt dessen `_get_entry`-Guard nicht.

**Fix-Richtung:** Den `_get_entry`-Guard auch in den abweichenden Views
verwenden und die View-Liste in `tools/test_unbekannte_id.py` erweitern.

---

### B-11 `install.sh` läuft ohne Fehlerprüfung

**Stelle:** `install.sh:1` — `#!/bin/bash`, aber kein `set -euo pipefail`.

Folgen, jeweils mit Zeile:

- `:35` `apt-get -y update; apt-get -y upgrade;` — zwei Kommandos mit `;`.
  Ein Fehlschlag des Updates läuft in den Install, ein Fehlschlag des
  Upgrades wird übergangen.
- `:46-53` `apt-get install` und `pip install` — ein Fehlschlag (z. B.
  Netzwerk) fuehrt trotzdem zur Erfolgsmeldung in `:75`
  („Installtion Finished").
- `:65-66` `echo ... >> "/boot/config.txt"` — schreibt bei jedem Lauf ein
  **zweites Mal** das `dtoverlay=w1-gpio,gpiopin=4,pullup=on` (keine
  Pruefung auf Vorhandensein) → doppelte Overlays ab dem zweiten Install.
- `:172-175` `exit` ohne Argument nach der Root-Pruefung — `whiptail`
  liefert 0, das Skript meldet also **Erfolg**, obwohl nichts installiert
  wurde.
- `:72` `sed "s@#DIR#@${PWD}@g"` — `${PWD}` unquotiert; ein Pfad mit `@`,
  `&` oder Leerzeichen bricht die Ersetzung.

**Fix-Richtung:** `set -euo pipefail` am Kopf, Fehlerpruefung nach jedem
Paket-Schritt, `exit 1` statt `exit`, `cp` statt `mv` (B-05).

---

### B-12 `install.sh` wechselt nicht ins Skriptverzeichnis

**Stelle:** `install.sh:49`, `:53`, `:70`, `:72`, `:91`, `:124`, `:133`

Das Skript nutzt durchgaengig relative Pfade. `sudo /pfad/install.sh` aus
einem beliebigen Verzeichnis legt `.venv` im falschen Ordner an, findet
`config/craftbeerpiboot` nicht und fuehrt `git reset --hard` im **falschen
Repository** aus.

**Fix-Richtung:** Wie in `tools/serverctl.sh:49-51`:
```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT" || exit 1
```

---

### B-13 Die Gärungs-Automatik bricht still ab

**Stelle:** `modules/fermenter/__init__.py:559-580`

`check_step()` iteriert über `cbpi.cache["fermenter_task"].items()` und ruft
in der Schleife `self.start_fermentation(key)` (`:576`). Das loescht in
`start_fermentation` den Key `del cbpi.cache["fermenter_task"][id]` (`:383`)
und setzt ihn neu.

**Fehlerfall (verifiziert in Python 3.14):** Mutation eines Dicts waehrend
der Iteration → `RuntimeError: dictionary changed size during iteration`.
Der Fehler wird vom `except Exception: pass` (`:579-580`) **nicht** gefangen,
weil er vom Iterator beim naechsten `next()` geworfen wird. Er propagiert
bis in den Job-Wrapper. Die uebrigen Fermenter in diesem Durchlauf werden
uebersprungen.

**Zweiter, stillerer Fehlerfall:** `cbpi.get_sensor_value()` gibt bei
Fehlern `None` zurueck (`modules/core/core.py:174-180`). `current_temp >=
value.temp` wirft dann `TypeError` → vom `except Exception: pass`
verschluckt. Ergebnis: der Schritt bekommt nie seinen Timer, die Gaerung
steht still — **ohne jede Meldung**.

**Fix-Richtung:** Ueber `list(cbpi.cache["fermenter_task"].items())`
iterieren, `None` von `get_sensor_value()` abfangen, und beide Faelle
loggen.

---

### B-14 Der Kessel-Automatik zeigt „Auto" ohne laufenden Controller

**Stelle:** `modules/kettle/__init__.py:51-63`

```python
kettle.state = not kettle.state
if kettle.logic is not None:
    ...
```

Das Flag wird auch dann umgeschaltet, wenn `kettle.logic is None` — es
wird **kein Controller gestartet**, das Flag steht trotzdem auf `True`.

**Fehlerfall:** Der Knopf zeigt „Auto", es laeuft nichts. Der
Fermenter hat genau diesen Fehler bereits behoben
(`modules/fermenter/__init__.py:455-510`, mit `_clear_running()` und
Notification) — der Kessel wurde nicht nachgezogen.

**Zweiter Fehlerfall:** `modules/kettle/__init__.py:59-61` startet den
Controller ohne `try/except`. Eine Exception im Controller killt den
Background-Thread **stillschweigend**, `kettle.state` bleibt `True` → der
gleiche Zustand wie oben.

**Fix-Richtung:** Das Fermenter-Muster uebernehmen.

---

### B-15 Die Donations-Notification ist nicht wegklickbar

**Stelle:** `modules/notification/__init__.py:63` vs. `:33`

Die Spendens-Meldung bekommt `id = len(cbpi.cache["messages"])` — einen
**int**. Alle anderen Nachrichten bekommen von `cbpi.notify()` eine **UUID
als String** (`modules/core/core.py:229`). `dismiss` vergleicht
`m.get("id") == id`, wobei `id` aus der URL immer ein String ist.

**Fehlerfall (verifiziert):** `DELETE /api/notification/0` → 204, die
Message bleibt aber im Cache. Die int-ID kann nie matchen.

**Fix-Richtung:** Die ID als String vergeben, wie alle anderen Messages.

---

### B-16 `messageEvent` wirft `KeyError`, wenn eine Message kein `timeout` hat

**Stelle:** `modules/notification/__init__.py:52`

```python
if message["timeout"] is None:
```

`emit_message()` garantiert bei Dicts nur den `"timestamp"`, nicht
`"timeout"` (`modules/core/core.py:474-476`).

**Fehlerfall (verifiziert):** `messageEvent({"id":"x", ...})` ohne
`"timeout"` → `KeyError: 'timeout'`. Der Handler laeuft `async_=True`, die
Exception landet im Hintergrund-Task — die Notification geht verloren, ohne
Logeintrag.

**Fix-Richtung:** `message.get("timeout")` verwenden.

---

### B-17 Ein Schritt mit unbekanntem Typ gilt als aktiv, obwohl nichts laeuft

**Stelle:** `modules/steps/__init__.py:152-166` und `:180-185`

`init_step()` gibt bei unbekanntem `step.type` frueh zurueck (`:155-157`).
`start()` setzt den Schritt danach trotzdem auf `'A'` und schreibt das in
die DB (`:182-185`).

**Fehlerfall:** Der Schritt gilt als aktiv, es laeuft keine Instanz,
`cbpi.cache["active_step"]` bleibt `None` → die Brauphase haengt bei diesem
Schritt.

**Fix-Richtung:** `start()` darf keinen Schritt aktivieren, dessen Typ
nicht aufloesbar ist.

---

### B-18 `checkout_tag` funktioniert nur einmal

**Stelle:** `modules/system/endpoints.py:199`

```python
repo.create_head('backup/pre-tag-checkout', branch.commit)
```

Der Branchname ist **fest**. Beim zweiten Tag-Checkout existiert der Branch
bereits → `GitCommandError` → `return ('Could not create backup branch', 500)`.

**Fehlerfall:** Der Endpunkt funktioniert nach dem ersten erfolgreichen
Checkout nicht mehr — und der Backup-Zweig, der den Zustand
wiederherstellbar machen sollte, verhindert genau den zweiten Vorgang.

**Fix-Richtung:** Einen eindeutigen Branchnamen verwenden (z. B. mit dem
Tag-Namen oder einem Zeitstempel).

---

### B-19 `install.sh` findet auf aktuellen Systemen keine IP-Adresse

**Stelle:** `install.sh:111`

```bash
ipaddr=`ifconfig wlan0 2>/dev/null|awk '/inet addr:/ {print $2}'|sed 's/addr://'`
```

Zwei Probleme: `ifconfig` (net-tools) ist auf Raspberry Pi OS Bookworm
**nicht vorinstalliert**, und das Muster `inet addr:` stammt aus net-tools
1.x — moderne Ausgabe lautet `inet 192.168.1.42`, der Treffer ist leer.

**Fehlerfall:** `install.sh:112` zeigt `http://:5000` an. Nebenbei ist die
Portangabe fest auf 5000 verdrahtet, obwohl der Port laut README aus der
DB kommt.

**Fix-Richtung:** `hostname -I` oder `ip -4 addr show wlan0`.

---

### B-20 `stats` blockiert den Start und sendet unverschlüsselt nach außen

**Stelle:** `modules/stats/__init__.py:33`

```python
r = requests.post('http://statistics.craftbeerpi.com', json=info)
```

**Fehlerfall 1 (Start):** Der Aufruf laeuft im Initializer
(`order=9999`) **ohne Timeout**. Ein haengender Server blockiert den
kompletten Start der Anwendung unbegrenzt.

**Fehlerfall 2 (Datenschutz):** Unverschluesseltes HTTP fuer die
Uebertragung der Geraete-Seriennummer, bei jedem Start, ohne Opt-in und
ohne Konfigurationsmoeglichkeit.

**Fehlerfall 3:** `getserial()` (`:5-14`) oeffnet `/proc/cpuinfo` nicht mit
`with` — tritt in der Schleife eine Exception auf, bleibt das Handle offen.

**Fix-Richtung:** Timeout setzen, HTTPS verwenden, das Senden abschaltbar
machen, `with` benutzen.

---

### B-21 Fehlerbehandlung maskiert den eigentlichen Fehler

**Stelle:** `modules/core/core.py:145-148` (Sensor) und `:48-55` (Actor)

```python
try:
    value = self.cache.get("sensors").get(int(id))
    ...
except Exception as e:
    self.notify("Actor Error", "Failed to setup actor %s. ..." % value.name, ...)
```

`value` wird erst in der try-Zeile gebunden. Bei unbekannter ID ist `value`
`None` → `AttributeError: 'NoneType' object has no attribute 'name'`.

**Fehlerfall (verifiziert):** `cbpi.init_sensor(9999)` →
`AttributeError`, `cbpi.init_actor(9999)` → `AttributeError`. Der eigentliche
Fehler (unbekannte ID) ist nicht mehr erkennbar.

**Fix-Richtung:** Den `value`-Zugriff aus dem except-Zweig herausziehen
oder den Fall separat behandeln.

---

### B-22 `switch_actor_on/off` und `actor_power` prüfen die Id nicht

**Stelle:** `modules/core/core.py:58`, `:71`, `:77`

`self.cache.get("actors").get(id)` ohne `None`-Prüfung.

**Fehlerfall (verifiziert):** `switch_actor_on("1")` → `AttributeError:
'NoneType' object has no attribute 'state'`. Inkonsistent zu `init_actor`,
das `int(id)` verwendet.

---

### B-23 Der Dev-Modus zeigt die falsche Logdatei

**Stelle:** `run_dev.py:196` (Log geht auf stdout), `:267` (Ausgabe sagt
`logs/app.log`), `:320-325` (Crash-Guard liest `logs/app.log`).

**Fehlerfall:** Die Crash-Diagnose zeigt die Zeilen des **produktiven**
Servers, nicht die des abgestuerzten Entwicklungsprozesses — fremde,
irrefuehrende Zeilen.

**Fix-Richtung:** Im Dev-Modus den Prozess-Output puffern oder den Hinweis
auf „Ausgabe im Terminal" umstellen.

---

### B-24 Aenderungen waehrend des Neustarts werden verschluckt

**Stelle:** `tools/watch_changes.py:161`, `run_dev.py:303`

`wait_for_change()` erzeugt bei **jedem** Aufruf ein neues
`baseline = snapshot()`.

**Fehlerfall:** Datei X geaendert → Neustart (1-3 s). Waehrend dieser Zeit
wird Datei Y gespeichert. Der naechste `wait_for_change()`-Aufruf baut das
`baseline` **inklusive Y** → Y wird nie als Aenderung gemeldet. Der Server
laeuft mit veraltetem Code, bis die *naechste* Aenderung kommt.

**Fix-Richtung:** Das `baseline` in `run_dev.py` halten und dem Watcher
uebergeben.

---

### B-25 Der „rein lesende" Sweep fuehrt einen `git fetch` aus

**Stelle:** `tools/sweep_endpoints.py:4-5` (Beschreibung) vs. der
Ausschlussliste `:23-32`

`/api/system/check_update` fehlt in der Ausschlussliste — und das ist ein
GET **mit Schreibwirkung** (`modules/system/endpoints.py:246-253`:
`o.fetch()`).

**Fehlerfall:** Der Sweep schreibt `.git/refs/remotes/origin/*`. Der
Arbeitsbaum ist danach nicht mehr unberuehrt — genau die Eigenschaft, die
`MIGRATION.md:55-57` („Ein Sweep ueber HTTP-Endpunkte ist ein Eingriff,
keine Analyse.") als Lektion festhaelt.

**Fix-Richtung:** `/api/system/check_update` in die Ausschlussliste.

---

## Blau — Robustheit und Best Practices

### B-26 `rpi.lgpio` ist kein `RPi.GPIO`-Ersatz, wird aber als verfügbar gemeldet

**Stelle:** `modules/core/gpio.py:161-166`, `:180`

`rpi.lgpio` ist die **native** API (`lgpio_set_function`, …), nicht die
`RPi.GPIO`-API (`setmode`/`setup`/`output`). Die Plugins in
`modules/base_plugins/` rufen aber genau diese auf. `GPIO_AVAILABLE = not
isinstance(GPIO, GPIOStub)` meldet trotzdem „verfügbar".

**Fehlerfall:** Die Plugins bekommen ein Objekt ohne `GPIO.setup` →
`AttributeError` in einem Hintergrund-Thread statt der klaren
Stub-Meldung.

**Fix-Richtung:** Stufe 2 entfernen oder als „native API, nicht
kompatibel" markieren.

### B-27 Migrationen und Datenbank liegen relativ zum Arbeitsverzeichnis

**Stelle:** `modules/core/db_mirgrate.py:51`, `:53`, `:82`,
`modules/core/db.py:14`

Alle Pfade sind relativ zum CWD. `python /pfad/run.py` aus `$HOME` →
Migrationen laufen **kommentarlos nicht** (`_sort_files()` gibt eine leere
Liste zurueck), die Datenbank wird als `~/craftbeerpi.db` **neu angelegt**
(leer, ohne Schema).

**Fix-Richtung:** Pfade aus `os.path.dirname(...)` ableiten — so macht es
`modules/restart/__init__.py:161` bereits.

### B-28 `DBModel.update()` ohne Primärschlüssel ist ein stiller No-Op

**Stelle:** `modules/core/db.py:131-133`

`WHERE 'id' = ?` mit `kwargs.get(pk)` — fehlt der Primaerschluessel, ist
der Wert `None` → `WHERE id = NULL` → 0 Zeilen geaendert, `commit()` ohne
Fehler. Ebenso fehlt jede `rowcount`-Pruefung (`delete` `:74`, `insert`
`:112`).

### B-29 `get_sensor_value()` verschluckt jeden Fehler ohne Log

**Stelle:** `modules/core/core.py:174-180`

Jeder Fehler → `None`, **ohne jegliches Log**. Ein defekter Sensor ist damit
von „kein Messwert" nicht unterscheidbar. Alle Verbraucher
(`controller.py:36`, `step.py:28`) rechnen mit `None` weiter.

### B-30 Ungepruefte Methodenausfuehrung per HTTP

**Stelle:** `modules/sensors/__init__.py:15-19`,
`modules/actor/__init__.py:63-67`, `modules/steps/__init__.py:86-89`

`...instance.__getattribute__(method)()` — **beliebige** Methode des
Plugin-Objekts per HTTP aufrufbar, keine Whitelist. `active_step` ist
`None` → `AttributeError` → 500 (verifiziert).

### B-31 `Property.Number` verliert die `unit`-Angabe

**Stelle:** `modules/core/props.py:82`

Der Parameter `unit` wird nie gespeichert (kein `self.unit`).

### B-32 `apply_property_defaults` kann Entwickler-Werte ueberschreiben

**Stelle:** `modules/core/props.py:43-44`

Der MRO-Scan findet ein Property-Attribut auch dann, wenn eine Unterklasse
es durch einen einfachen Wert ersetzt hat. `name in instance.__dict__` ist
dann `False` → `apply_property_defaults` ueberschreibt den Klassenwert mit
dem Default (oft `None`).

### B-33 `get_by_state` mit einem String-Argument laeuft in einen sqlite-Fehler

**Stelle:** `modules/fermenter/__init__.py:70`,
`modules/steps/__init__.py:24-31`

`cur.execute(sql, state)` mit `state` als String → sqlite3 interpretiert
ihn als Zeichenkette, nicht als Tupel.

**Fehlerfall (verifiziert):** `'Active'` →
`sqlite3.ProgrammingError: Incorrect number of bindings supplied … 6
supplied`. In `fermenter` ist die Methode toter Code, in `steps` wird sie
mit `'A'` (ein Zeichen) aufgerufen und funktioniert daher zufaellig.

Zusaetzlich: der Parameter `order` in `modules/steps/__init__.py:24` wird
nie benutzt.

### B-34 `init_kettle()` ist vollstaendig defekt (toter Code)

**Stelle:** `modules/core/core.py:520-527`

`value["state"] = False` wirft `TypeError: 'Kettle' object does not support
item assignment` auf einem DBModel-Objekt. Der except-Zweig meldet daraufhin
faelschlich „Kettle Setup Failed". Die Methode hat keine Aufrufer.

### B-35 `classy.py`: `decorators` wird nie angewandt, `orig_route_base` nie gesetzt

**Stelle:** `modules/core/classy.py:48`, `:165-167`

`decorators = []` — das flask_classy-Feld wird nie benutzt. Eine View, die
`decorators = [...]` setzt, verliert sie **stillschweigend**. `orig_route_base`
wird nirgends gesetzt, der Ruecksetz-Mechanismus ist toter Code.

### B-36 `classy.py`: geerbte `@cbpi.action`-Methoden fehlen in der UI

**Stelle:** `modules/core/core.py:331-334`, `:411-414`

Actions werden nur aus `cls.__dict__` gesammelt, **nicht** aus geerbten
Klassen.

### B-37 `classy.py`: Regelaufbau doppelt implementiert

**Stelle:** `modules/core/classy.py:52-90` vs. `:143-163`

`build_rule` zweimal, `trailing_slash`-Logik zweimal, `add_url_rule` zweimal
— ~40 Zeilen mit 4 Call-Sites derselben Logik.

### B-38 `db_mirgrate.py`: `OperationalError` wird als „frische Installation" fehlinterpretiert

**Stelle:** `modules/core/db_mirgrate.py:149-154`

Jede `OperationalError` (z. B. „database is locked" bei parallelem Start)
setzt `current_version = None` → **alle** Migrationen laufen erneut. Der
`except Exception`-Zweig (`:152-154`) ebenso.

### B-39 `db_mirgrate.py`: naives Splitten an `;`

**Stelle:** `modules/core/db_mirgrate.py:84`

`sqlCommands = d.split(";")` — ein Semikolon **innerhalb eines
String-Literals** oder in einem `CREATE TRIGGER ... BEGIN ...; ... END;`
zerlegt das Statement → `sqlite3.ProgrammingError`. Heute harmlos (die 6
SQL-Dateien enthalten keine Trigger), aber eine latente Falle.

### B-40 `step.py`: der Schluessel `kettleid` wird nie uebergeben

**Stelle:** `modules/core/step.py:125`

`self.kettle_id = kwds.get("kettleid")` — der Schluessel wird nirgends
uebergeben (`modules/steps/__init__.py` uebergibt `cfg` aus `step.config`,
dort heisst der Kessel `"kettle"`). `kettle_id` ist daher immer `None`;
`set_target_temp(temp)` ohne explizite ID emittiert `SET_TARGET_TEMP` mit
`id=None`.

### B-41 `step.py`: `__setattr__` hat zwei identische Zweige

**Stelle:** `modules/core/step.py:148-154`

Der `managed_fields`-Check hat keinerlei Wirkung — ein toter Zweig, der
`is_dirty()` suggeriert, aber nichts bewirkt. Ebenso in
`modules/core/hardware.py:42-48`.

### B-42 `controller.py`: `get_sensor_value` nutzt das globale `cbpi`

**Stelle:** `modules/core/controller.py:36`

Waehrend `ActorController` (`:12`, `:19`, `:25`) `self.api` benutzt, greift
`SensorController` auf das Modul-Globale zu. Bei einem Controller, der nicht
mit dem globalen Singleton erzeugt wurde, liefert der Sensorwert den Wert
eines **fremden** Systems. Aehnlich in `modules/core/step.py:28` und `:37`.

### B-43 `KettleController` und `FermenterController` sind ~40 Zeilen Duplikat

**Stelle:** `modules/core/controller.py:84-123` vs. `:125-176`

`heater_on`/`heater_off`/`get_temp`/`get_target_temp` fast identisch
(nur `kettle` vs. `fermenter`).

### B-44 `core.py`: ~60 Zeilen duplizierte Property-Introspection

**Stelle:** `modules/core/core.py:290-337` vs. `:380-416`

`__parseProps` und `step` — einziger Unterschied ist `Property` vs.
`StepProperty`.

### B-45 `props.py`: `StepProperty` ist ein zeichengleiches Duplikat

**Stelle:** `modules/core/props.py:119-137` vs. `:97-116`

`Actor`, `Sensor`, `Kettle` sind zeichengleich mit `Property` — obwohl
`StepProperty` bereits von `Property` erbt. Zusaetzlich bricht die
Vererbung `StepProperty.Actor(PropertyType)` statt `StepProperty.Actor(Property.Actor)`
die Typ-Hierarchie: `isinstance(x, Property.Actor)` ist fuer einen
`StepProperty.Actor` `False`.

### B-46 Vier Kopien derselben Erklärung zur Property-Vorgabe

**Stelle:** `modules/core/props.py:6-39`, `modules/core/step.py:132-141`,
`modules/core/controller.py:72-77`, `modules/core/hardware.py:36-39`

Derselbe Text in vier Dateien.

### B-47 Der `sendStats`-Parameter shadowiert das globale `cbpi`

**Stelle:** `modules/stats/__init__.py:18`

`def sendStats(cbpi)` — der Parameter shadowiert das globale `cbpi`.

### B-48 `modules/app_config.py`: fehlendes `logs/` bricht den App-Import ab

**Stelle:** `modules/app_config.py:50`

`logging.basicConfig(filename='./logs/app.log', ...)` — existiert `./logs`
nicht, wirft der **Import** der App `FileNotFoundError`.

**Verifiziert:** `FileNotFoundError: [Errno 2] No such file or directory:
'/tmp/logtest/logs/app.log'`.

Der `Dockerfile:46` legt das Verzeichnis an, `install.sh` **nicht** → bei
manueller Installation startet der Server nicht.

### B-49 `SECRET_KEY` ist hart kodiert

**Stelle:** `modules/app_config.py:54`

`app.config['SECRET_KEY'] = 'craftbeerpi'` — kein Override per
Umgebungsvariable. Das Muster existiert im Projekt bereits (`CBPI_LOG_LEVEL`,
`CBPI_PORT`).

Geringe Prioritaet: es gibt keine Sessions im Projekt, und der Server
bindet ohnehin ohne Authentifizierung an `0.0.0.0`.

### B-50 `/api/system/dump` legt den kompletten Cache offen

**Stelle:** `modules/system/endpoints.py:268-270`

`json.dumps(cbpi.cache)` unauthentifiziert — inklusive aller Config-Werte
(Broker, Zugangsdaten) und des `mqtt`-Caches.

### B-51 Der Plugin-Store ist eine Remote-Code-Execution-Kette

**Stelle:** `modules/addon/endpoints.py:210`, `:237`

`plugins.yaml` wird von GitHub ungeprueft uebernommen, ihr `repo_url` wird
geklont (`Repo.clone_from`). Der geklonte Code wird beim naechsten Start
importiert und ausgefuehrt (`loadPlugins`, `:283`).

Zusaetzlich schreibt `saveFile` (`:157-158`) beliebigen Request-Body als
ausfuehrbaren Python-Code in `modules/plugins/<name>/__init__.py` — ohne
Authentifizierung kann jeder im LAN Code einschleusen.

### B-52 `sweep_endpoints.py` enthaelt tote Ausschluesse

**Stelle:** `tools/sweep_endpoints.py:26-27`

`/api/system/doReboot` und `/api/system/doShutdown` — die realen Routen
heißen `/api/system/reboot` und `/api/system/shutdown` (die ohnehin POST
sind). Altlast aus der flask_classy-Zeit.

### B-53 `requirements.txt`: ungepinnte Abhaengigkeiten, eine ungenutzte

**Stelle:** `requirements.txt:15-18`, `:22`, `:26`

`python-dateutil>=2.9`, `PyYAML>=6.0`, `requests>=2.32`, `GitPython>=3.1`,
`simple-websocket>=1.1`, `paho-mqtt>=2.1` stehen als offene Bereiche. Kein
Lockfile, keine Hashes → `Dockerfile:37` baut bei jedem Mal ein anderes
Image.

**`python-dateutil` wird nirgends importiert** (grep ueber `modules/` ergibt
keinen Treffer) — weder eine Abhaengigkeit von Flask noch von GitPython.

### B-54 Ungenutzte Imports und Variablen

**Stelle:** 81 ungenutzte Imports (per `pyflakes` verifiziert), verteilt auf:

| Datei | Anzahl |
|---|---|
| `modules/recipe_import/restapi.py` | 10 (in 62 Zeilen) |
| `modules/recipe_import/beerxml.py` | 6 |
| `modules/recipe_import/kbh.py` | 5 |
| `modules/core/core.py` | 7 |
| `modules/base_plugins/one_wire/__init__.py` | 6 |
| `modules/system/endpoints.py` | 3 |
| `modules/app_config.py` | 3 |
| `modules/__init__.py` | 6 |
| `tools/*` | 11 (siehe unten) |

Dazu ungenutzte lokale Variablen: `core.py:94`, `:483`, `:576`,
`baseview.py:131`, `step.py:54`, `kettle/__init__.py:61`,
`fermenter/__init__.py:366`, `:510`, `:579`, `:589`,
`stats/__init__.py:33`, `:35`, `logs/endpoints.py:77`,
`system/endpoints.py:264`, `:275`, `:276`,
`recipe_import/beerxml.py:42`, `restapi.py:53`,
`modules/buzzer/__init__.py:43`, `base_plugins/one_wire/__init__.py:129`.

In `tools/`: `sweep_endpoints.py:14` (`json`), `test_api.py:21` (`io`),
`test_json.py:22` (`io`), `test_socket.py:20` (`io`),
`test_fermenter_auto.py:29` (`time`), `test_step_reset.py:29` (`time`),
`test_telegram_plugin.py:25` (`types`), `test_plugins.py:43` (`cbpi`),
`test_unbekannte_id.py:42` (`cbpi`), `test_system.py:161` (`pwm`).

### B-55 Blankes `except:` an 15 Stellen

**Stelle:** `modules/core/baseview.py:87`, `modules/core/core.py:187`, `:193`,
`:501`, `modules/base_plugins/one_wire/__init__.py:24`, `:98`,
`modules/logs/endpoints.py:33`, `:68`, `modules/stats/__init__.py:12`,
`modules/kettle/__init__.py:32`, `modules/system/endpoints.py:234`,
`modules/fermenter/__init__.py:130`

Ein blankes `except:` faengt auch `KeyboardInterrupt` und `SystemExit`.

### B-56 `try_catch` loggt ohne Traceback

**Stelle:** `modules/core/core.py:499-503`

Der `except:` faengt alles und loggt nur den Funktionsnamen — die
Fehlerursache geht verloren. Ausserdem nutzen die Dekoratoren
(`event`, `initalizer`, `backgroundtask`, `try_catch`) kein
`functools.wraps` → `__name__` und `__doc__` gehen am dekorierten Objekt
verloren.

### B-57 `getOne` antwortet bei unbekannter Id mit 200 und `null`

**Stelle:** `modules/core/baseview.py:12-18`

`put()` und `delete()` liefern bei derselben Lage `404` — inkonsistente
API-Semantik.

### B-58 `getUnit` interpretiert alles ausser „C" als Fahrenheit

**Stelle:** `modules/core/hardware.py:67-71`

Ein Tippfehler in der Config (`"c"`, `"°C"`, `"K"`) ergibt still °F.

### B-59 `clean_cache` setzt `cache["init"]` auf ein Dict

**Stelle:** `modules/core/core.py:284-288`

Je nach Flag `[]` oder `{}` — fuer `cache["init"]` (eine Liste von Dicts)
waere `{}` falsch. Wird nirgends aufgerufen.

### B-60 `cache` und `eventbus` sind Klassenattribute

**Stelle:** `modules/core/core.py:198`, `:215`

Veränderbarer Zustand, der ueber alle `CraftBeerPi`-Exemplare geteilt wird.
`run_init()` (`:520`) sortiert `cache["init"]` **in-place**. Das ist die
Wurzel von B-13: der Cache wird gleichzeitig aus Request-Threads und aus
Background-Tasks ohne Lock beschrieben.

### B-61 `emit_event` iteriert waehrend ein Thread anhaengt

**Stelle:** `modules/core/core.py:478-483`

`self.eventbus.get(name, [])` — ein anderer Thread kann in dieselbe Liste
appen (z. B. Plugin-Nachladen). CPython toleriert das, aber ein Event kann
uebersprungen werden.

### B-62 `init_actors` setzt `api` am Plugin-*Typ* statt am Exemplar

**Stelle:** `modules/core/core.py:29-33`

`value.get("class").api = self` — ein Klassenattribut am Plugin-Typ
(global). Alle Exemplare eines Typs teilen sich so `api`.

### B-63 `sensor_instances` wird nie befuellt

**Stelle:** `modules/core/core.py:128-129`, `:204`

Der Block `if id in self.cache.get("sensor_instances")` ist toter Code — die
vorgesehene Funktion (alten Sensor stoppen) greift nie.

### B-64 `save_to_file` oeffnet die Logdatei pro Messwert neu

**Stelle:** `modules/core/core.py:154-160`

`open`/`write`/`close` bei 0,1-s-Sensor-Takt, ohne Absicherung, ob `./logs`
existiert → `FileNotFoundError` in einem Callback-Pfad.

### B-65 `config/version.yaml` wird von keinem Werkzeug gelesen

**Stelle:** `config/version.yaml` — gelesen wird es nur in
`modules/system/endpoints.py:293` (und dort nicht sinnvoll: der Inhalt
landet in `y`, das danach nicht mehr benutzt wird).

### B-66 `config/version.yaml` und die `endpoints`-Route sind faktisch kaputt

**Stelle:** `modules/system/endpoints.py:272-298`

Die Route erzeugt eine Swagger-2.0-Beschreibung, laesst `paths` aber leer
(die Methoden werden entfernt statt dokumentiert) und liefert dann ein
leeres Ergebnis. `pprint.pprint` wurde bereinigt, der Rest bleibt.

### B-67 `modules/ui/endpoints.py`: `template_folder='templates'` ohne Verzeichnis

**Stelle:** `modules/ui/endpoints.py:5`

Das Verzeichnis existiert nicht und wird nicht genutzt — im Zuge der
Bereinigung entfernt.

### B-68 Die `.cjs`-Werkzeuge haengen an einem fremden absoluten Pfad

**Stelle:** `tools/shot_alt_ui.cjs:11-15`, `tools/test_alt_ui.cjs:18-22`

```js
const WebSocket = require(
  path.join(
    "/home/lope/cbpi3UIng/node_modules/.pnpm/ws@8.21.3/node_modules/ws"
  )
)
```

Beide Skripte haengen an einem absoluten Pfad in einem **anderen, nicht zu
diesem Projekt gehoerenden Repository** und an einer exakten
pnpm-Store-Version. Auf jeder anderen Maschine schlagen sie mit
`MODULE_NOT_FOUND` fehl. Beide Dateien sind versioniert.

### B-69 `tools/snapshot_routes.py` baut einen eigenen GPIO-Stub

**Stelle:** `tools/snapshot_routes.py:24-63`

`modules/core/gpio.py:66-141` liefert bereits genau das (mit besserer
Fehlermeldung). Zusaetzlich ist der `git`-Stub `:65-72` toter Code —
`GitPython>=3.1` steht in `requirements.txt` und ist damit immer
installiert.

### B-70 `docker-compose.yml`: die `user:`-Empfehlung funktioniert so nicht

**Stelle:** `docker-compose.yml:50-56`

`${UID:-1000}` ist in Docker Compose **nicht** als Shell-Variable
verfuegbar — `UID` ist eine Bash-Shell-Variable, keine exportierte
Umgebungsvariable. Der Vorschlag funktioniert in der Regel nicht.

Ausserdem mountet `.:/usr/src/app` den Image-Inhalt (inklusive des in
`Dockerfile:46` angelegten `logs/`- und `upload/`-Verzeichnisses) und legt
DB/Logs als **root-eigene** Dateien auf dem Host ab.

### B-71 `Dockerfile` laeuft als root

**Stelle:** `Dockerfile:65`

Kein `USER` im Image. `docker-compose.yml:52-56` kommentiert das, aber
das Image selbst bleibt root. Besser: `USER` im Dockerfile setzen und im
Compose nur fuer den GPIO-Fall ueberschreiben.

### B-72 `Dockerfile`: Healthcheck ist unsauber

**Stelle:** `Dockerfile:63`

`urllib.request.urlopen(...)` wirft bei !=200 eine `HTTPError`; die
`sys.exit(0 if … == 200 else 1)`-Logik ist damit toter Code, weil der
Fehler vorher durchschlaegt. Funktional harmlos (Exit != 0 ⇒ unhealthy),
aber unsauber.

### B-73 `install.sh` nutzt `sudo` in einem Skript, das ohnehin als root laeuft

**Stelle:** `install.sh:70`, `:81`, `:91`, `:103`, `:110`, `:116`, `:142`,
`:152`, `:160-162`

Neun Stellen. Redundant und bricht auf Systemen ohne `sudo` (schlanke
Images). Konsistent waere: alle Kommandos ohne `sudo` ausfuehren, da Root
ohnehin vorausgesetzt ist.

### B-74 `install.sh`: `pip` und `wheel` werden ungepinnt gehoben

**Stelle:** `install.sh:52`

`pip install --upgrade pip wheel` — auf die jeweils neueste Version, ohne
Hash- oder Versionspins. `requirements.txt` pinnt dagegen die Kernpakete
exakt. Zwei Installationen derselben Requirements-Datei koennen
unterschiedliche `pip`-/`setuptools`-Staende haben.

### B-75 `tools/serverctl.sh`: „Server laeuft nicht" trotz laufendem Server

**Stelle:** `tools/serverctl.sh:167-172`

`ss -ltnpH` zeigt Prozessinformationen **nur fuer eigene Sockets** (bzw.
fuer root). Laeuft der Server unter einem anderen Benutzer oder als root
(`config/craftbeerpiboot:29` `DAEMON_USER=root`), liefert `ss` kein
`pid=` → `port_pid` ist leer.

**Fehlerfall:** `do_status` (`:317-340`) meldet „CraftBeerPi laeuft nicht",
und `do_start` (`:200-208`) ueberspringt die Portpruefung → ein **zweiter
Server** wird gestartet, der mit „Address already in use" stirbt.

### B-76 Die Brauschritt-Pruefung ist doppelt implementiert

**Stelle:** `tools/serverctl.sh:106-123` und `modules/restart/__init__.py:173-182`

Zwei Implementierungen derselben Regel. Aendert der Kern den
Zustandsmarker, wird eine stillschweigend falsch.

### B-77 `tools/shot_alt_ui.cjs` und `tools/test_alt_ui.cjs` sind dupliziert

**Stelle:** beide Dateien — dieselben ~60 Zeilen Helfer (`httpJson`,
Chrome-Spawn, DevTools-`send`/`wartende`-Map).

### B-78 `tools/serverctl.sh` ruft inline-Python per Heredoc auf

**Stelle:** `tools/serverctl.sh:79-98` und `:106-123`

Zweimal dasselbe Muster (DB-Zugriff + Fehlerbehandlung), zweimal
`import sqlite3` inline.

### B-79 `run_dev.py`: Portpruefung und Start sind nicht atomar

**Stelle:** `run_dev.py:271-277` und `:280`

Zwischen Pruefung und Start liegt ein Fenster; der Server kann den Port
trotzdem nicht binden.

Nebenbei: `run_dev.py:122-133` faellt auf `sys.executable` zurueck, obwohl
der Docstring `:127-129` sagt „Ohne virtualenv laeuft der Server gar nicht
erst" — der Nutzer bekommt dann einen `ImportError` statt einer klaren
Meldung.

### B-80 `run.py`: `port = None` ist redundant

**Stelle:** `run.py:13`

Wird initialisiert und dann in beiden Zweigen ueberschrieben.

### B-81 `modules/restart/__init__.py`: doppelte Initializer-Order

**Stelle:** `modules/restart/__init__.py:524` (`order=3000`), `:540` und
`:560` (beide `order=1`)

Drei Initialisizer, davon zwei mit derselben Order. Die Reihenfolge
zwischen ihnen haengt an der Registrierungsreihenfolge, nicht an der
Order-Angabe. Der Kommentar `:565-568` („damit es genau einmal da ist")
beschreibt eine Eigenschaft, die die Order nicht garantiert.

### B-82 Tippfehler in Namen, die zur API gehoeren

**Stelle:** `modules/core/db.py:20` — `__priamry_key__` (statt
`__primary_key__`)

Funktional harmlos, weil alle Modelle konsistent denselben Namen benutzen.
Wer von aussen ein Modell schreibt, muss den Tippfehler mitmachen. Umbenennen
waere ein Breaking Change fuer externe Plugins → mindestens als TODO
markieren.

Ebenfalls: `modules/steps/__init__.py:187` `get_manged_fields_as_array`
(„manged"), `modules/core/props.py:20` `__priamry_key__` in `Config`
(`modules/config/__init__.py:12`), `modules/core/db_mirgrate.py` (Dateiname
„mirgrate"), `modules/addon/endpoints.py:201`/`:204` „REALOD OF PLUGIN %s"
und `:138` „Name arlready in use" (in benutzersichtbaren Meldungen),
`modules/core/classy.py:10` „importanteste" (bereits korrigiert),
`modules/base_plugins/brew_steps/__init__.py` „set target tep".

---

## Anhang: Was bei diesem Audit bereits behoben wurde

Im Zuge der Bereinigung wurden diese Punkte bereits erledigt. Die
Zeilennummern in diesem Abschnitt beziehen sich auf den Stand **vor** der
Bereinigung — sie sind historisch und nicht zum Nachschlagen gedacht.

- doppelte Eintraege und Kommentarbloecke in `.gitignore` (zweimal
  `logs/server.pid`, zweimal `*.pyc`)
- alle veralteten Zeilenverweise in Kommentaren (`core.py`, `flask_classy.py`,
  `base_server.py`) — Zeilennummern in Kommentaren erodieren
- der falsche Satz „Python 2 code, like the core it runs next to" in
  `modules/plugins/AdvancedPIDAutoTune/__init__.py`
- das Python-2-Restkommentar in `modules/buzzer/__init__.py`
- Debug-`print`s im Produktivpfad (`core.py`, `controller.py`, `hardware.py`,
  `step.py`, `system/endpoints.py` inkl. `pprint.pprint`)
- der tote Dekorator `actor2` mit vier `print`s (`modules/core/core.py`)
- der doppelte `"init"`-Schluessel im `cache`-Dict (`modules/core/core.py`)
- falsche Docstrings „reads all passive sensors in interval of 1 second"
  (`interval=5`) in `fermenter`, `kettle`, `sensors`
- falsche Kommentare „READ KBH DATABASE" in `beerxml.py` und `restapi.py`
- Markdown-Ueberschriften (`### add rest step`) in Python-Dateien
- leere `:return:`-Reste und Kommentare, die nur die Zeile darunter
  beschreiben
- der auskommentierte Decorator in `modules/addon/endpoints.py`
- `import pprint` doppelt in `modules/__init__.py`
- `modules/ui/endpoints.py`: `template_folder` ohne Verzeichnis, 10
  Leerzeilen am Ende
- `tools/watch_changes.py`: die im Kommentar beschriebene Ausschlussregel
  fuer `modules/ui/src/` ist jetzt implementiert, `logs/` und `upload/` aus
  den toten `SKIP_DIRS` entfernt
- `README.md`: die Fehlermeldung `CRITICAL: We need to talk about your
  installation` existiert im Projekt nicht — der Abschnitt beschreibt jetzt
  die tatsaechliche GPIO-Meldung; `.yml` und `--crash-guard` ergaenzt;
  die Liste der Testwerkzeuge vervollstaendigt
- `MIGRATION.md`: die Widersprueche „Position 1-4" vs. „1-7",
  „107 Routen" vs. 110, die veralteten Testzahlen und die
  veralteten Zeilenverweise
- `requirements.txt`: die Behauptung „Pins auf aktuelle Stands" stimmte nicht
