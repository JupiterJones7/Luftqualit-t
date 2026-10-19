
import os

import pandas as pd
import psycopg
from dotenv import load_dotenv

load_dotenv()


def load_data_from_database():
    """Lädt CO2-, Temperatur- und Feuchtigkeitswerte aus PostgreSQL."""

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL fehlt. Bitte die .env-Datei prüfen."
        )

    query = """
        SELECT
            measured_at AS timestamp,
            MAX(value) FILTER (
                WHERE mt.name = 'CO2'
            ) AS co2_ppm,
            MAX(value) FILTER (
                WHERE mt.name = 'temperature'
            ) AS temperature_c,
            MAX(value) FILTER (
                WHERE mt.name = 'humidity'
            ) AS humidity_pct
        FROM measurements AS m
        JOIN measurement_types AS mt
            ON mt.id = m.measurement_type_id
        GROUP BY measured_at, sensor_id
        ORDER BY measured_at;
    """

    with psycopg.connect(database_url) as connection:
        df = pd.read_sql_query(query, connection)

    if df.empty:
        raise ValueError(
            "Die Datenbank enthält noch keine Messwerte."
        )

    df["timestamp"] = pd.to_datetime(df["timestamp"])

    print(f"{len(df)} Zeitpunkte aus PostgreSQL geladen.")

    return df
