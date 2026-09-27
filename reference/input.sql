INSERT INTO calibrations (station_id, variable_id, valid_from, scale, offset) VALUES
('STATION_A', 'air_temperature', '2026-01-01T00:00:00Z', 1.002, -0.12),
('STATION_B', 'air_temperature', '2026-01-01T00:00:00Z', 0.998, 0.08);

INSERT INTO raw_observations
(observation_id, observed_at, station_id, variable_id, raw_value, raw_unit, qc_flag) VALUES
(1, '2026-09-25T00:00:00Z', 'STATION_A', 'air_temperature', 20.0, 'degC', 'GOOD'),
(2, '2026-09-25T06:00:00Z', 'STATION_A', 'air_temperature', 22.0, 'degC', 'GOOD'),
(3, '2026-09-25T12:00:00Z', 'STATION_A', 'air_temperature', 99.0, 'degC', 'BAD'),
(4, '2026-09-25T18:00:00Z', 'STATION_A', 'air_temperature', 18.0, 'degC', 'GOOD'),
(5, '2026-09-25T00:00:00Z', 'STATION_B', 'air_temperature', 15.0, 'degC', 'GOOD'),
(6, '2026-09-25T12:00:00Z', 'STATION_B', 'air_temperature', 17.0, 'degC', 'SUSPECT'),
(7, '2026-09-25T18:00:00Z', 'STATION_B', 'air_temperature', 19.0, 'degC', 'GOOD'),
(8, '2026-09-26T00:00:00Z', 'STATION_A', 'air_temperature', 21.0, 'degC', 'GOOD'),
(9, '2026-09-26T12:00:00Z', 'STATION_A', 'air_temperature', 23.0, 'degC', 'GOOD');

