# MQTT Plugin for CraftBeerPi 3.0

This plugins allows to connect to an MQTT Message broker to receive sensor data and invoke actors.

Requires **paho-mqtt 2.x** and Python 3. Tested with paho-mqtt 2.1.0 on Python 3.14.

Since it lives in `modules/base_plugins/mqtt` it is part of the CraftBeerPi
core and loads on every start. The dependency `paho-mqtt` is listed in
`requirements.txt`.


## Installation

### Install missing python lib
After installation please install the python MQTT lib

```pip install paho-mqtt```

https://pypi.org/project/paho-mqtt/

### Install MQTT message broker

Second step is to install an MQTT message broker on your Raspberry Pi.
An open source message broker is mosquitto (https://mosquitto.org/)

```
sudo apt-get update
sudo apt-get install mosquitto

# Furhter commands to control mosquitto service
sudo service mosquitto status
sudo service mosquitto stop
sudo service mosquitto start
```

Leave username and password empty to connect anonymously.

# MQTT Test Client 
A nice MQTT test client is mqtt.fx http://www.mqttfx.org/


# Plugin config

## Broker connection

- `MQTT_SERVER` - hostname or IP of the broker, default `localhost`
- `MQTT_PORT` - default `1883`
- `MQTT_USERNAME` / `MQTT_PASSWORD` - leave empty for anonymous access
- `MQTT_TLS` - `true` enables TLS
- `MQTT_CA_CERT`, `MQTT_CERT`, `MQTT_KEY` - optional paths for TLS. With
  `MQTT_TLS` enabled and no paths given, the system trust store is used.
  Certificate verification stays active - there is deliberately no "insecure"
  switch.

The connection is established in the background and reconnects automatically.
All topic subscriptions are restored after a reconnect, so a restarted broker
does not require a restart of CraftBeerPi.

## Actors

- **MQTTActor** - publishes `{"state": "on"}` / `{"state": "off"}` as JSON.
  This is the payload most home automation systems expect.
- **ESPEasyMQTT** - publishes the raw values `1` and `0`, following the ESPEasy
  convention for GPIO switches.

Both publish with `qos=2` and `retain=true`.

## MQTT Sensor

- Enter the message topic
- If the data in the payload is in a dictionary, specify the path in "Payload Dictionary" with '.' separators. EG
  - msg = `{ "Name":"MySensor", "Sensor": {"Value": 32 , "Type" : "1-wire"}}`
  - "Payload Dictionary" = `Sensor.Value`
- If your data is raw (e.g. `mosquitto_pub -d -t temperature -m 32`), leave
  "Payload Dictionary" blank
- Enter preferred unit up to 3 chars

Only scalar values are accepted - a number, a string or a boolean. If the
configured path points at a nested object, the message is ignored and a
debug entry is written to `logs/app.log`.

Wildcard topics such as `cbpi/#` are not supported per sensor. Use one sensor
per topic.

## Logging

All messages go to `logs/app.log` with the prefix `MQTT:`. If the broker is
unreachable, this shows up as

```
MQTT: kein Broker (localhost:1883), publish auf 'topic' verworfen
```

Checking that file is the quickest way to confirm whether the broker is
reachable from the Pi.