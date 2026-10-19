
import json
import os
import random
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
QUEUE_FILE = BASE_DIR / "data" / "collector_queue.sqlite3"

DATABASE_URL = os.getenv("DATABASE_URL")
SENSOR_NAME = "Raumluftstation 1"

INTERVAL_SECONDS = 60
LIMITS = {
    "CO2": (0, 10000),
    "temperature": (-20, 60),
    "humidity": (0, 100),
}


def generate_measurements():
    """Erzeugt vorläufig simulierte Messwerte."""
    return {
        "CO2": round(random.uniform(450, 1200), 1),
        "temperature": round(random.uniform(19, 26), 1),
        "humidity": round(random.uniform(30, 65), 1),
    }


def validate_measurements(values):
    errors = []

    for name, (minimum, maximum) in LIMITS.items():
        if name not in values:
            errors.append(f"Messwert fehlt: {name}")
            continue

        value = values[name]

        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            errors.append(f"Messwert ist keine Zahl: {name}")
            continue

        if not minimum <= value <= maximum:
            errors.append(
                f"{name} ausserhalb des Prüfbereichs "
                f"({minimum} bis {maximum})"
            )

    return errors


def init_queue():
    """Erstellt die lokale Warteschlange, falls sie fehlt."""
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(QUEUE_FILE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                values_json TEXT NOT NULL,
                errors_json TEXT NOT NULL
            )
            """
        )


def enqueue_measurement(timestamp, values, errors):
    """Speichert einen Messzyklus dauerhaft auf dem Computer."""
    with sqlite3.connect(QUEUE_FILE) as connection:
        connection.execute(
            """
            INSERT INTO pending_measurements
                (timestamp, values_json, errors_json)
            VALUES (?, ?, ?)
            """,
            (
                timestamp.isoformat(),
                json.dumps(values, allow_nan=False),
                json.dumps(errors),
            ),
        )


def get_database_config(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM sensors
            WHERE name = %s
            ORDER BY id
            LIMIT 1
            """,
            (SENSOR_NAME,),
        )
        sensor = cursor.fetchone()

        if sensor is None:
            raise ValueError(f"Sensor nicht gefunden: {SENSOR_NAME}")

        cursor.execute("SELECT id, name FROM measurement_types")

        type_ids = {
            name: type_id
            for type_id, name in cursor.fetchall()
        }

    if not set(LIMITS).issubset(type_ids):
        raise ValueError("Benötigte Messwerttypen fehlen.")

    return sensor[0], type_ids


def save_rejected(connection, sensor_id, timestamp, values, errors):
    """Dokumentiert einen ungültigen Messzyklus in PostgreSQL."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO rejected_measurements
                (sensor_id, raw_record, rejection_reason,
                 source_file, source_row)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_file, source_row)
            DO NOTHING
            """,
            (
                sensor_id,
                Jsonb({
                    "timestamp": timestamp,
                    "values": values,
                }),
                "; ".join(errors),
                f"collector:{timestamp}",
                1,
            ),
        )


def save_valid(connection, sensor_id, type_ids, values, timestamp):
    """Speichert die Messwerte innerhalb einer Transaktion."""
    with connection.cursor() as cursor:
        for name, value in values.items():
            cursor.execute(
                """
                INSERT INTO measurements
                    (sensor_id, measurement_type_id, measured_at, value)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT
                    (sensor_id, measurement_type_id, measured_at)
                DO NOTHING
                """,
                (
                    sensor_id,
                    type_ids[name],
                    datetime.fromisoformat(timestamp),
                    value,
                ),
            )


def deliver_pending():
    """Überträgt wartende Messzyklen und löscht sie erst danach."""
    while True:
        with sqlite3.connect(QUEUE_FILE) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT id, timestamp, values_json, errors_json
                FROM pending_measurements
                ORDER BY id
                LIMIT 1
                """
            ).fetchone()

        if row is None:
            return

        values = json.loads(row["values_json"])
        errors = json.loads(row["errors_json"])

        # Ein fehlgeschlagener Upload lässt den Eintrag lokal bestehen.
        try:
            with psycopg.connect(
                DATABASE_URL,
                connect_timeout=5,
            ) as connection:
                sensor_id, type_ids = get_database_config(connection)

                if errors:
                    save_rejected(
                        connection,
                        sensor_id,
                        row["timestamp"],
                        values,
                        errors,
                    )
                else:
                    save_valid(
                        connection,
                        sensor_id,
                        type_ids,
                        values,
                        row["timestamp"],
                    )

        except (psycopg.OperationalError, psycopg.InterfaceError):
            print(
                "Datenbank nicht erreichbar. "
                "Messwerte bleiben in der lokalen Warteschlange."
            )
            return

        # Erst nach erfolgreichem Datenbank-Commit entfernen.
        with sqlite3.connect(QUEUE_FILE) as connection:
            connection.execute(
                "DELETE FROM pending_measurements WHERE id = ?",
                (row["id"],),
            )

        print(f"Messzyklus {row['id']} erfolgreich übertragen.")


def main():
    init_queue()

    print("Datenerfassung gestartet.")
    print(f"Lokale Warteschlange: {QUEUE_FILE}")
    print("Beenden mit Ctrl+C.")

    while True:
        timestamp = datetime.now(timezone.utc)
        values = generate_measurements()
        errors = validate_measurements(values)

        # Immer zuerst lokal sichern.
        enqueue_measurement(timestamp, values, errors)

        if errors:
            print(f"Ungültige Messwerte: {'; '.join(errors)}")
        else:
            print(
                f"Erfasst: CO2 {values['CO2']} ppm | "
                f"Temperatur {values['temperature']} °C | "
                f"Luftfeuchtigkeit {values['humidity']} %"
            )

        # Ältere Einträge werden zuerst übertragen.
        try:
            deliver_pending()
        except (psycopg.Error, ValueError) as error:
            print(f"Übertragung vorerst nicht möglich: {error}")

        with sqlite3.connect(QUEUE_FILE) as connection:
            pending = connection.execute(
                "SELECT COUNT(*) FROM pending_measurements"
            ).fetchone()[0]

        if pending:
            print(f"Noch nicht übertragen: {pending} Messzyklen.")

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    if not DATABASE_URL:
        print(
            "Warnung: DATABASE_URL fehlt. "
            "Messwerte werden lokal gesammelt, bis die Verbindung "
            "konfiguriert ist."
        )

    try:
        main()
    except KeyboardInterrupt:
        print("\nDatenerfassung beendet.")
