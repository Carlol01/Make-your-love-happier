-- Schema sintetico (nomi non ufficiali) usato dai test per costruire il database.
CREATE TABLE menstruation_period_record_table (row_id INTEGER PRIMARY KEY, start_time INTEGER, end_time INTEGER, start_zone_offset INTEGER, end_zone_offset INTEGER);
CREATE TABLE menstruation_flow_record_table (row_id INTEGER PRIMARY KEY, time INTEGER, flow INTEGER, zone_offset INTEGER);
CREATE TABLE steps_record_table (row_id INTEGER PRIMARY KEY, start_time INTEGER, count INTEGER);
