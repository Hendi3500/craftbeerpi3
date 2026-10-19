CREATE TABLE IF NOT EXISTS kettle
(
    id INTEGER PRIMARY KEY NOT NULL,
    name VARCHAR(80),
    sensor VARCHAR(80),
    heater VARCHAR(10),
    automatic VARCHAR(255),
    logic VARCHAR(50),
    config VARCHAR(1000),
    agitator VARCHAR(10),
    target_temp INTEGER,
    height INTEGER,
    diameter INTEGER
);

CREATE TABLE IF NOT EXISTS step
(
    id INTEGER PRIMARY KEY NOT NULL,
    "order" INTEGER,
    name VARCHAR(80),
    type VARCHAR(100),
    stepstate VARCHAR(255),
    state VARCHAR(1),
    start INTEGER,
    end INTEGER,
    config VARCHAR(255),
    kettleid INTEGER
);

CREATE TABLE IF NOT EXISTS sensor
(
    id INTEGER PRIMARY KEY NOT NULL,
    type VARCHAR(100),
    name VARCHAR(80),
    config VARCHAR(500),
    hide BOOLEAN
);

CREATE TABLE IF NOT EXISTS fermenter_step
(
    id INTEGER PRIMARY KEY NOT NULL,
    name VARCHAR(80),
    hours INTEGER,
    minutes INTEGER,
    days INTEGER,
    temp INTEGER,
    direction VARCHAR(1),
    "order" INTEGER,
    state VARCHAR(1),
    start INTEGER,
    timer_start INTEGER,
    end INTEGER,
    fermenter_id INTEGER,
    FOREIGN KEY (fermenter_id) REFERENCES fermenter (id)
);

CREATE TABLE IF NOT EXISTS fermenter
(
    id INTEGER PRIMARY KEY NOT NULL,
    name VARCHAR(80),
    brewname VARCHAR(80),
    sensor VARCHAR(80),
    sensor2 VARCHAR(80),
    sensor3 VARCHAR(80),
    heater VARCHAR(10),
    logic VARCHAR(50),
    config VARCHAR(1000),
    cooler VARCHAR(10),
    target_temp INTEGER
);

CREATE TABLE IF NOT EXISTS config
(
    name VARCHAR(50) PRIMARY KEY NOT NULL,
    value VARCHAR(255),
    type VARCHAR(50),
    description VARCHAR(255),
    options VARCHAR(255)
);


INSERT OR IGNORE INTO config VALUES ('kettle_cols', 4, 'select', 'Adjust the width of a kettle widget on the brewing dashboard', '[1,2,3, 4, 5, 6, 7, 8, 9, 10, 11, 12]');
INSERT OR IGNORE INTO config VALUES ('actor_cols', 4, 'select', 'Adjust the width of a actor widget on the brewing dashboard', '[1,2,3, 4, 5, 6, 7, 8, 9, 10, 11, 12]');
INSERT OR IGNORE INTO config VALUES ('sensor_cols', 4, 'select', 'Adjust the width of a sensor widget on the brewing dashboard', '[1,2,3, 4, 5, 6, 7, 8, 9, 10, 11, 12]');
INSERT OR IGNORE INTO config VALUES ('unit', 'C', 'select', 'Temperature Unit', '["C","F"]');
INSERT OR IGNORE INTO config VALUES ('brewery_name', 'My Home Brewery', 'text', 'Your brewery name', NULL );
INSERT OR IGNORE INTO config VALUES ('buzzer', 16, 'select', 'Buzzer GPIO', '[16,17,18,19,20,21,22,23]');
INSERT OR IGNORE INTO config VALUES ('buzzer_beep_level', 'HIGH', 'select', 'Buzzer Logic Beep Level', '["HIGH", "LOW"]');
INSERT OR IGNORE INTO config VALUES ('setup', 'YES', 'select', 'Show the Setup dialog', '["YES","NO"]');
INSERT OR IGNORE INTO config VALUES ('brew_name', '', 'text', 'Brew Name', NULL);
INSERT OR IGNORE INTO config VALUES ('donation_notification', 'YES', 'select', 'Disable Donation Notification', '["YES","NO"]');
-- Meereshöhe der Brauanlage in Metern. Der Siedepunkt sinkt um rund
-- 1 °C je 285 m:  T_Siede = 100 - Höhe/285.  Auf 400 m sind das 98,6 °C -
-- ein Schritt mit 100 °C erreicht sein Ziel dann nie, der Step läuft in
-- den Timeout und der Brauvorgang steht.  Die Korrektur selbst macht die
-- UI (Rezeptimport, Rezept-Library, Step-Dialog).  Typ "number", damit
-- /parameter ein Zahlenfeld statt eines Textfelds rendert.
INSERT OR IGNORE INTO config VALUES ('altitude', 0, 'number', 'Altitude above sea level in meters (boiling point = 100 - altitude/285)', NULL);
-- ID des geladenen Rezepts. Die UI leitet sie aus dem Dokument ab und
-- schreibt sie hierher; das Backend haelt sie nur fuer die Anzeige
-- neben dem Braunamen bereit.
INSERT OR IGNORE INTO config VALUES ('brew_recipe_uuid', '', 'text', 'UUID of the loaded brew recipe', NULL);
-- Plugin-Aenderungen, die noch einen Neustart wollen: JSON-Liste
-- [{"name": ..., "at": ..., "action": ...}]. Der Neustart selbst leert die
-- Liste, bevor er das Prozess-Image ersetzt.
INSERT OR IGNORE INTO config VALUES ('plugins_changed', '[]', 'text', 'Plugins changed since the last backend restart, JSON. Internal, do not edit.', NULL);
-- Epoch-Sekunden (float) des Starts des laufenden Backends. Damit weiss
-- die UI, ob eine Aenderung von vor einem Neustart schon angewendet ist.
INSERT OR IGNORE INTO config VALUES ('backend_started_at', '0', 'text', 'When the running backend was started (epoch seconds, float). Internal, do not edit.', NULL);


CREATE TABLE IF NOT EXISTS actor
(
    id INTEGER PRIMARY KEY NOT NULL,
    name VARCHAR(50),
    type VARCHAR(100),
    config VARCHAR(500),
    hide BOOLEAN
);
