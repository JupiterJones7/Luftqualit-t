
import os

import pandas as pd
import psycopg
from dotenv import load_dotenv

load_dotenv()

# Metadaten-Spalten, die nicht zu den Messgrössen gehören.
IDENTIFIER_COLUMNS = [
    "timestamp",
    "sensor_id",
    "sensor_name",
    "sensor_model",
]


def load_data_from_database():
    """Lädt alle verfügbaren Messgrössen aus PostgreSQL."""

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL fehlt. Bitte die .env-Datei prüfen."
        )

    query = """
        SELECT
            m.measured_at AS timestamp,
            s.id AS sensor_id,
            s.name AS sensor_name,
            s.model AS sensor_model,
            mt.code AS measurement_code,
            mt.unit AS measurement_unit,
            m.value
        FROM measurements AS m
        JOIN sensors AS s
            ON s.id = m.sensor_id
        JOIN measurement_types AS mt
            ON mt.id = m.measurement_type_id
        ORDER BY
            m.measured_at,
            s.id,
            mt.code;
    """

    with psycopg.connect(database_url) as connection:
        df = pd.read_sql_query(query, connection)

    # Einheitliches Ergebnis auch dann zurückgeben,
    # wenn noch keine Messwerte vorhanden sind.
    if df.empty:
        return pd.DataFrame(columns=IDENTIFIER_COLUMNS)

    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Jede Messgrösse wird zu einer eigenen Spalte.
    # Unterschiedliche Sensoren bleiben getrennt.
    measurements = df.pivot(
        index=[
            "timestamp",
            "sensor_id",
            "sensor_name",
            "sensor_model",
        ],
        columns="measurement_code",
        values="value",
    ).reset_index()

    measurements.columns.name = None

    print(
        f"{len(measurements)} Zeitpunkte/Sensor-Kombinationen "
        "aus PostgreSQL geladen."
    )

    print(
        f"{len(measurements.columns) - len(IDENTIFIER_COLUMNS)} "
        "verschiedene Messgrössen-Spalten verfügbar."
    )

    return measurements
