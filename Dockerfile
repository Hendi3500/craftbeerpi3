# Container-Image fuer CraftBeerPi 3.0
#
# Der Container startet das Backend (Flask + Socket.IO). Die Oberflaeche
# liegt unter /ui/, die REST-Schnittstelle unter /api/.
#
# Wichtig: Das Projekt laeuft seit der Portierung auf Python 3 (siehe
# MIGRATION.md). Vorher stand hier "FROM python:2" - das Image war damit
# unbrauchbar, requirements.txt laesst sich unter Python 2 nicht
# installieren.
FROM python:3.12-slim

# PYTHONUNBUFFERED: stdout ungepuffert, damit "docker logs" etwas zeigt.
# Der Logger des Projekts schreibt zusaetzlich nach ./logs/app.log.
# PYTHONDONTWRITEBYTECODE: keine .pyc-Dateien im Image.
# PIP_NO_CACHE_DIR: kein pip-Cache im Image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Zeitzone. Ohne das tzdata-Paket im Image ist die Variable TZ
# wirkungslos und Flask/dateutil rechnen in UTC. DEBIAN_FRONTEND
# unterdrueckt die Rueckfrage des Pakets nach der Zeitzone.
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

# Abhaengigkeiten zuerst. So bleibt dieser Layer im Cache, wenn sich
# nur der Code aendert.
#
# rpi-lgpio steht bewusst nicht in requirements.txt: das Paket laesst
# sich nur auf dem Raspberry Pi bauen. Im Container ist GPIO ohnehin
# nicht erreichbar - modules/core/gpio.py liefert dann einen Stub.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Verzeichnisse, in die die App zur Laufzeit schreibt:
#   logs/   - app.log, action.log, <sensor>_<id>.log
#   upload/ - Uploads aus dem Datei-Plugin
# Die Datenbank craftbeerpi.db legt die App beim Start selbst an
# (config/schema.sql, modules/__init__.py).
RUN mkdir -p logs upload

# Der Standardport. Mit CBPI_PORT laeuft der Server auf einem anderen
# Port - dann muss das Port-Mapping im compose mitziehen.
EXPOSE 5000

# Healthcheck auf die Oberflaeche. Ohne curl - deshalb der Umweg ueber
# urllib aus dem Interpreter, den das Image ohnehin hat.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,sys,urllib.request; port=os.environ.get('CBPI_PORT','5000'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+port+'/ui/', timeout=4).status == 200 else 1)"

CMD ["python", "run.py"]
