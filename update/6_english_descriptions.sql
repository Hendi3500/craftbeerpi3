-- Die Beschreibungen der Parameter auf Englisch umstellen.
--
-- Hintergrund
-- ----------
-- Die Oberflaeche zeigt neben jedem Parameter seinen Beschreibungstext
-- an ("System -> Parameter"). Die Beschreibungen der Telegram- und der
-- MQTT-Parameter waren auf Deutsch, alle anderen sind englisch. Damit
-- war die Liste gemischtsprachig.
--
-- Der Text steht in der Datenbank, nicht im Code: add_config_parameter
-- legt einen Parameter nur an, wenn er noch nicht existiert. Ein
-- vorhandener Parameter behaelt seinen alten Beschreibungstext - die
-- Aenderung im Code wirkt also erst bei einer frischen Installation.
-- Diese Migration holt die bestehenden Installationen nach.
--
-- Die UPDATEs sind idempotent: sie setzen den Text immer auf denselben
-- Wert, egal ob er schon der englische ist oder nicht. Sie aendern
-- weder Namen noch Werte noch Typen - nur die Beschreibung.

UPDATE config SET description = 'Telegram bot token (from @BotFather)' WHERE name = 'telegram_bot_token';
UPDATE config SET description = 'Telegram chat ID - separate several with a comma' WHERE name = 'telegram_chat_id';
UPDATE config SET description = 'Send a test message to Telegram when the backend starts' WHERE name = 'telegram_startup_message';

UPDATE config SET description = 'MQTT TLS CA certificate (path)' WHERE name = 'mqtt_ca_cert';
UPDATE config SET description = 'MQTT TLS client certificate (path)' WHERE name = 'mqtt_cert';
UPDATE config SET description = 'MQTT TLS client key (path)' WHERE name = 'mqtt_key';
