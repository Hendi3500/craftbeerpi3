-- Repair: Config-Parameter hatten ihren Typ verloren.
--
-- CraftBeerPi.set_config_parameter() hat Config.update() nur name und
-- value uebergeben. update() schreibt aber alle Spalten der config-
-- Tabelle, und was nicht uebergeben wird, kommt als NULL herein. Im
-- Cache blieb das verborgen - dort wurde nur name/value aktualisiert -
-- in der Datenbank nicht. Nach dem naechsten Start war der Parameter
-- ohne Typ wieder da, und die UI rendert ihn als Textfeld statt als
-- Auswahl- oder Zahlenfeld.
--
-- Betroffen sind alle Parameter, die zur Laufzeit gesetzt werden:
--   brew_name    - set_config_parameter() beim Rezeptimport
--   brewery_name - set_config_parameter() aus der Konfiguration
--
-- Die UPDATE-statements sind auf "type IS NULL" Bedingt: ein Parameter,
-- der noch seinen Typ hat, wird nicht angefasst.
UPDATE config SET type = 'text', description = 'Brew Name', options = NULL WHERE name = 'brew_name' AND type IS NULL;
UPDATE config SET type = 'text', description = 'Your brewery name', options = NULL WHERE name = 'brewery_name' AND type IS NULL;
UPDATE config SET type = 'text', description = 'Plugins changed since the last backend restart, JSON. Internal, do not edit.', options = NULL WHERE name = 'plugins_changed' AND type IS NULL;
UPDATE config SET type = 'text', description = 'When the running backend was started (epoch seconds, float). Internal, do not edit.', options = NULL WHERE name = 'backend_started_at' AND type IS NULL;
