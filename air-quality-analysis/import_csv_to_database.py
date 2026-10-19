
import os
from pathlib import Path

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

from main import load_data, clean_data, OUTPUT_DIR

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "data" / "measurements.csv"


def make_json_safe(record):
    """Wandelt Pandas-Werte in JSON-kompatible Python-Werte um."""
    result = {}

    for key, value in record.items():
        if pd.isna(value):
            result[key] = None
        elif isinstance(value, pd.Timestamp):
            result[key] = value.isoformat()
        else:
            result[key] = value.item() if hasattr(value, "item") else value

    return result


def import_csv_to_database():
    # 1. CSV einlesen und Datenqualität prüfen
    raw_df = load_data(CSV_FILE)
    clean_df = clean_data(raw_df)

    # 2. Bericht mit fehlerhaften Zeilen laden
    rejected_file = OUTPUT_DIR / "rejected_measurements.csv"

    if rejected_file.exists():
        rejected_df = pd.read_csv(rejected_file)
    else:
        rejected_df = pd.DataFrame()

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL fehlt. Bitte die .env-Datei prüfen."
        )

    inserted = 0
    skipped = 0
    rejected_inserted = 0
    rejected_skipped = 0

    # 3. Mit PostgreSQL verbinden
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:

            # Sensor suchen
            cursor.execute(
                """
                SELECT id
                FROM sensors
                WHERE name = %s
                ORDER BY id
                LIMIT 1
                """,
                ("Raumluftstation 1",),
            )

            sensor = cursor.fetchone()

            if sensor is None:
                raise ValueError(
                    "Sensor 'Raumluftstation 1' wurde nicht gefunden."
                )

            sensor_id = sensor[0]

            # Messwerttypen laden
            cursor.execute(
                "SELECT id, name FROM measurement_types"
            )

            type_ids = {
                name: type_id
                for type_id, name in cursor.fetchall()
            }

            columns = {
                "co2_ppm": "CO2",
                "temperature_c": "temperature",
                "humidity_pct": "humidity",
            }

            if not set(columns.values()).issubset(type_ids):
                raise ValueError(
                    "Benötigte Messwerttypen fehlen in der Datenbank."
                )

            # 4. Gültige Messwerte importieren
            for _, row in clean_df.iterrows():
                for column, type_name in columns.items():
                    cursor.execute(
                        """
                        INSERT INTO measurements
                            (sensor_id, measurement_type_id,
                             measured_at, value)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT
                            (sensor_id, measurement_type_id, measured_at)
                        DO NOTHING
                        RETURNING id
                        """,
                        (
                            sensor_id,
                            type_ids[type_name],
                            row["timestamp"].to_pydatetime(),
                            float(row[column]),
                        ),
                    )

                    if cursor.fetchone() is None:
                        skipped += 1
                    else:
                        inserted += 1

            # 5. Fehlerhafte Zeilen in PostgreSQL speichern
            for _, row in rejected_df.iterrows():
                source_row = int(row["source_row"])
                raw_record = make_json_safe(row.to_dict())
                reason = str(row["error_reason"])

                cursor.execute(
                    """
                    INSERT INTO rejected_measurements
                        (sensor_id, raw_record, rejection_reason,
                         source_file, source_row)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_file, source_row)
                    DO NOTHING
                    RETURNING id
                    """,
                    (
                        sensor_id,
                        Jsonb(raw_record),
                        reason,
                        CSV_FILE.name,
                        source_row,
                    ),
                )

                if cursor.fetchone() is None:
                    rejected_skipped += 1
                else:
                    rejected_inserted += 1

    # Die Transaktion wird beim Verlassen des with-Blocks bestätigt.
    print("\n--- Import abgeschlossen ---")
    print(f"Gültige Zeitpunkte: {len(clean_df)}")
    print(f"Neue gültige Messwerte: {inserted}")
    print(f"Bereits vorhandene Messwerte übersprungen: {skipped}")
    print(f"Neue fehlerhafte Datensätze: {rejected_inserted}")
    print(
        "Bereits vorhandene Fehlerdatensätze übersprungen:",
        rejected_skipped,
    )


if __name__ == "__main__":
    import_csv_to_database()
