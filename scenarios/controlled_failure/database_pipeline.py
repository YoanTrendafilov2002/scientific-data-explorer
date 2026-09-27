"""Controlled defect: an obsolete rounded Celsius-to-Kelvin offset."""
from __future__ import annotations

import sqlite3


KELVIN_OFFSET = 273.00  # DEFECT: scientifically correct offset is exactly 273.15.


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE raw_observations (
            observation_id INTEGER PRIMARY KEY,
            observed_at TEXT NOT NULL,
            station_id TEXT NOT NULL,
            variable_id TEXT NOT NULL,
            raw_value REAL NOT NULL,
            raw_unit TEXT NOT NULL,
            qc_flag TEXT NOT NULL
        );
        CREATE TABLE calibrations (
            station_id TEXT NOT NULL,
            variable_id TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            scale REAL NOT NULL,
            offset REAL NOT NULL,
            PRIMARY KEY (station_id, variable_id, valid_from)
        );
        CREATE TABLE daily_temperature_products (
            day TEXT NOT NULL,
            station_id TEXT NOT NULL,
            variable_id TEXT NOT NULL,
            valid_observation_count INTEGER NOT NULL,
            daily_mean_temperature_k REAL NOT NULL,
            PRIMARY KEY (day, station_id, variable_id)
        );
        """
    )


def build_daily_temperature_product(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM daily_temperature_products")
    connection.execute(
        """
        INSERT INTO daily_temperature_products
        WITH calibrated AS (
            SELECT date(o.observed_at) AS day, o.station_id, o.variable_id,
                   o.qc_flag, (o.raw_value * c.scale) + c.offset AS calibrated_temperature_c
            FROM raw_observations AS o
            JOIN calibrations AS c
              ON c.station_id = o.station_id
             AND c.variable_id = o.variable_id
             AND c.valid_from = (
                 SELECT MAX(c2.valid_from) FROM calibrations AS c2
                 WHERE c2.station_id = o.station_id
                   AND c2.variable_id = o.variable_id
                   AND c2.valid_from <= o.observed_at
             )
            WHERE o.variable_id = 'air_temperature' AND o.raw_unit = 'degC'
        ),
        valid_kelvin AS (
            SELECT day, station_id, variable_id,
                   calibrated_temperature_c + ? AS temperature_k
            FROM calibrated WHERE qc_flag = 'GOOD'
        )
        SELECT day, station_id, variable_id, COUNT(*), AVG(temperature_k)
        FROM valid_kelvin GROUP BY day, station_id, variable_id
        """,
        (KELVIN_OFFSET,),
    )
    connection.commit()


def fetch_products(connection: sqlite3.Connection) -> list[dict[str, object]]:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """SELECT day, station_id, variable_id, valid_observation_count,
                  daily_mean_temperature_k
           FROM daily_temperature_products
           ORDER BY day, station_id, variable_id"""
    ).fetchall()
    return [dict(row) for row in rows]

