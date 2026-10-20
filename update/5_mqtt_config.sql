-- MQTT-Konfiguration: die Parameter auf kleingeschriebene Namen umstellen
-- und TLS von einem Textfeld in ein Auswahlfeld (YES/NO) ueberfuehren.
--
-- Hintergrund
-- ----------
-- Die MQTT-Parameter hiessen bisher MQTT_SERVER, MQTT_PORT, MQTT_TLS
-- und so weiter. Alle anderen Parameter in CraftBeerPi 3 sind klein
-- geschrieben: unit, brewery_name, setup, port, altitude. Die
-- GROSSBUCHSTABEN fielen auf und machten die Oberflaeche uneinheitlich.
--
-- Die Parameter werden hier umbenannt, damit die vorhandene
-- Konfiguration erhalten bleibt. Ohne diese Migration laeuft der
-- Plugin nach dem Update mit den Vorgabewerten - der Broker waere
-- nicht mehr erreichbar, bis der Brauer alles von Hand eingetragen hat.
--
-- TLS wird dabei zum Auswahlfeld: "true"/"false" wird zu "YES"/"NO".
-- Als Textfeld war jedes nicht-leere Zeichenfeld truthy - ein
-- eingetragenes "false" haette TLS eingeschaltet gelassen, und der
-- Broker waere gar nicht erreichbar.
--
-- Die UPDATEs ueberschreiben nichts, was schon existiert: existiert
-- der neue Name bereits, gewinnt er, und der alte Eintrag bleibt
-- liegen. Das Plugin entfernt ihn beim Start (siehe _parameter_loeschen
-- in modules/base_plugins/mqtt/__init__.py).

UPDATE config SET name = 'mqtt_server' WHERE name = 'MQTT_SERVER' AND NOT EXISTS (SELECT 1 FROM config WHERE name = 'mqtt_server');
UPDATE config SET name = 'mqtt_port' WHERE name = 'MQTT_PORT' AND NOT EXISTS (SELECT 1 FROM config WHERE name = 'mqtt_port');
UPDATE config SET name = 'mqtt_username' WHERE name = 'MQTT_USERNAME' AND NOT EXISTS (SELECT 1 FROM config WHERE name = 'mqtt_username');
UPDATE config SET name = 'mqtt_password' WHERE name = 'MQTT_PASSWORD' AND NOT EXISTS (SELECT 1 FROM config WHERE name = 'mqtt_password');
UPDATE config SET name = 'mqtt_tls' WHERE name = 'MQTT_TLS' AND NOT EXISTS (SELECT 1 FROM config WHERE name = 'mqtt_tls');
UPDATE config SET name = 'mqtt_ca_cert' WHERE name = 'MQTT_CA_CERT' AND NOT EXISTS (SELECT 1 FROM config WHERE name = 'mqtt_ca_cert');
UPDATE config SET name = 'mqtt_cert' WHERE name = 'MQTT_CERT' AND NOT EXISTS (SELECT 1 FROM config WHERE name = 'mqtt_cert');
UPDATE config SET name = 'mqtt_key' WHERE name = 'MQTT_KEY' AND NOT EXISTS (SELECT 1 FROM config WHERE name = 'mqtt_key');

-- TLS: Freitext in ein Auswahlfeld ueberfuehren.
UPDATE config SET value = 'YES' WHERE name = 'mqtt_tls' AND lower(trim(value)) IN ('true', '1', 'yes', 'on', 'y');
UPDATE config SET value = 'NO' WHERE name = 'mqtt_tls' AND lower(trim(value)) IN ('false', '0', 'no', 'off', 'n', '');
UPDATE config SET type = 'select', options = '["YES", "NO"]' WHERE name = 'mqtt_tls';

-- Der Port ist eine Zahl - wie der Port des Webservers.
UPDATE config SET type = 'number' WHERE name = 'mqtt_port';

-- Die uebrigen Parameter bleiben Textfelder.
UPDATE config SET type = 'text' WHERE name IN ('mqtt_server', 'mqtt_username', 'mqtt_password', 'mqtt_ca_cert', 'mqtt_cert', 'mqtt_key');
