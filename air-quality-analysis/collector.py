
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
INTERVAL_SECONDS = 60
OFFLINE_AFTER_MINUTES = 3

# Vorläufige Prüfbereiche.
# Vor dem Anschluss echter Sensoren anhand der Dokumentation prüfen.
LIMITS = {
    "pm1_mass": (0, 1000),
    "pm25_mass": (0, 1000),
    "pm4_mass": (0, 1000),
    "pm10_mass": (0, 1000),
    "pm05_number": (0, None),
    "pm1_number": (0, None),
    "pm25_number": (0, None),
    "pm4_number": (0, None),
    "pm10_number": (0, None),
    "co2": (0, 10000),
    "formaldehyde": (0, 10),
    "temperature": (-20, 60),
    "humidity": (0, 100),
    "voc_index": (0, 500),
    "nox_index": (0, 500),
}


def generate_measurements(model):
    """Erzeugt künstliche Messwerte zum Testen."""

    values = {
        "pm1_mass": round(random.uniform(2, 15), 2),
        "pm25_mass": round(random.uniform(4, 25), 2),
        "pm4_mass": round(random.uniform(5, 30), 2),
        "pm10_mass": round(random.uniform(6, 40), 2),
        "pm05_number": round(random.uniform(1, 30), 2),
        "pm1_number": round(random.uniform(1, 25), 2),
        "pm25_number": round(random.uniform(1, 20), 2),
        "pm4_number": round(random.uniform(1, 15), 2),
        "pm10_number": round(random.uniform(1, 10), 2),
        "co2": round(random.uniform(450, 1200), 1),
        "temperature": round(random.uniform(19, 26), 1),
        "humidity": round(random.uniform(30, 65), 1),
        "voc_index": round(random.uniform(50, 150), 1),
        "nox_index": round(random.uniform(1, 100), 1),
    }

    if model == "SEN69C":
        values["formaldehyde"] = round(
            random.uniform(0.001, 0.03), 4
        )

    return values


def validate_measurements(values):
    """Prüft Messwerte auf Zahlen und plausible Grenzbereiche."""

    errors = []

    for code, value in values.items():
        if code not in LIMITS:
            errors.append(f"Unbekannte Messgrösse: {code}")
            continue

        minimum, maximum = LIMITS[code]

        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            errors.append(f"Messwert ist keine Zahl: {code}")
            continue

        if not (
            minimum <= value
            and (maximum is None or value <= maximum)
        ):
            errors.append(f"{code} ausserhalb des Prüfbereichs")

    return errors


def init_queue():
    """Erstellt oder erweitert die lokale SQLite-Warteschlange."""

    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(QUEUE_FILE) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS pending_measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                values_json TEXT NOT NULL,
                errors_json TEXT NOT NULL,
                sensor_model TEXT NOT NULL DEFAULT 'SEN66'
            )
        """)

        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(pending_measurements)"
            ).fetchall()
        }

        if "sensor_model" not in columns:
            connection.execute("""
                ALTER TABLE pending_measurements
                ADD COLUMN sensor_model TEXT NOT NULL DEFAULT 'SEN66'
            """)


def enqueue_measurement(timestamp, model, values, errors):
    """Speichert einen Messzyklus lokal."""

    with sqlite3.connect(QUEUE_FILE) as connection:
        connection.execute("""
            INSERT INTO pending_measurements (
                timestamp,
                values_json,
                errors_json,
                sensor_model
            )
            VALUES (?, ?, ?, ?)
        """, (
            timestamp.isoformat(),
            json.dumps(values, allow_nan=False),
            json.dumps(errors),
            model,
        ))


def get_database_config(connection, model):
    """Liest Sensor-ID, Geräte-ID und Messgrössen-IDs."""

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT s.id, s.device_id
            FROM sensors AS s
            JOIN devices AS d ON d.id = s.device_id
            WHERE s.model = %s
              AND s.active = TRUE
              AND d.active = TRUE
            ORDER BY s.id
            LIMIT 1
        """, (model,))

        sensor = cursor.fetchone()

        if sensor is None:
            raise ValueError(
                f"Kein aktiver Sensor mit Modell {model} gefunden."
            )

        sensor_id, device_id = sensor

        cursor.execute("""
            SELECT code, id
            FROM measurement_types
        """)

        type_ids = {
            code: type_id
            for code, type_id in cursor.fetchall()
        }

    return sensor_id, device_id, type_ids


def update_device_status(
    connection,
    device_id,
    status,
    last_seen,
    last_error=None,
):
    """Aktualisiert den Gerätestatus und den letzten Messzeitpunkt."""

    now = datetime.now(timezone.utc)

    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO device_status (
                device_id,
                last_seen,
                status,
                last_error,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (device_id)
            DO UPDATE SET
                last_seen = CASE
                    WHEN EXCLUDED.last_seen IS NULL
                        THEN device_status.last_seen
                    WHEN device_status.last_seen IS NULL
                        THEN EXCLUDED.last_seen
                    ELSE GREATEST(
                        device_status.last_seen,
                        EXCLUDED.last_seen
                    )
                END,
                status = EXCLUDED.status,
                last_error = EXCLUDED.last_error,
                updated_at = EXCLUDED.updated_at
        """, (
            device_id,
            last_seen,
            status,
            last_error,
            now,
        ))


def save_rejected(
    connection,
    sensor_id,
    timestamp,
    model,
    values,
    errors,
):
    """Protokolliert einen ungültigen Messzyklus."""

    source_id = f"collector:{model}:{timestamp}"

    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO rejected_measurements (
                sensor_id,
                raw_record,
                rejection_reason,
                source_message_id
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_message_id) DO NOTHING
        """, (
            sensor_id,
            Jsonb({
                "timestamp": timestamp,
                "sensor_model": model,
                "values": values,
            }),
            "; ".join(errors),
            source_id,
        ))


def save_valid(
    connection,
    sensor_id,
    type_ids,
    values,
    timestamp,
    model,
):
    """Speichert gültige Messwerte in PostgreSQL."""

    measured_at = datetime.fromisoformat(timestamp)

    with connection.cursor() as cursor:
        for code, value in values.items():
            if code not in type_ids:
                raise ValueError(
                    f"Messgrösse fehlt in measurement_types: {code}"
                )

            cursor.execute("""
                INSERT INTO measurements (
                    sensor_id,
                    measurement_type_id,
                    measured_at,
                    value,
                    source_message_id
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (
                    sensor_id,
                    measurement_type_id,
                    measured_at
                ) DO NOTHING
            """, (
                sensor_id,
                type_ids[code],
                measured_at,
                value,
                f"collector:{model}:{timestamp}:{code}",
            ))


def deliver_pending():
    """Überträgt wartende Messzyklen und löscht sie erst nach Commit."""

    if not DATABASE_URL:
        print(
            "DATABASE_URL fehlt. "
            "Warteschlange bleibt lokal."
        )
        return

    while True:
        with sqlite3.connect(QUEUE_FILE) as connection:
            connection.row_factory = sqlite3.Row

            row = connection.execute("""
                SELECT
                    id,
                    timestamp,
                    values_json,
                    errors_json,
                    sensor_model
                FROM pending_measurements
                ORDER BY id
                LIMIT 1
            """).fetchone()

        if row is None:
            return

        values = json.loads(row["values_json"])
        errors = json.loads(row["errors_json"])
        model = row["sensor_model"]
        measured_at = datetime.fromisoformat(row["timestamp"])

        try:
            with psycopg.connect(
                DATABASE_URL,
                connect_timeout=5,
            ) as connection:

                sensor_id, device_id, type_ids = (
                    get_database_config(connection, model)
                )

                if errors:
                    save_rejected(
                        connection,
                        sensor_id,
                        row["timestamp"],
                        model,
                        values,
                        errors,
                    )

                    # Ungültige Daten aktualisieren nicht last_seen.
                    # Sonst könnte ein fehlerhafter Zyklus das Gerät
                    # fälschlicherweise als online erscheinen lassen.
                    update_device_status(
                        connection,
                        device_id,
                        "warning",
                        None,
                        "; ".join(errors),
                    )
                else:
                    save_valid(
                        connection,
                        sensor_id,
                        type_ids,
                        values,
                        row["timestamp"],
                        model,
                    )

                    update_device_status(
                        connection,
                        device_id,
                        "online",
                        measured_at,
                        None,
                    )

        except (psycopg.Error, ValueError) as error:
            print(f"Übertragung fehlgeschlagen: {error}")
            print("Eintrag bleibt in der lokalen Warteschlange.")
            return

        # Erst nach erfolgreichem Commit aus der lokalen Queue löschen.
        with sqlite3.connect(QUEUE_FILE) as connection:
            connection.execute(
                "DELETE FROM pending_measurements WHERE id = ?",
                (row["id"],),
            )

        print(f"{model}: Messzyklus {row['id']} übertragen.")


def mark_stale_devices_offline():
    """Markiert Geräte mit veralteten Messzeitpunkten als offline."""

    if not DATABASE_URL:
        return

    try:
        with psycopg.connect(
            DATABASE_URL,
            connect_timeout=5,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE device_status
                    SET
                        status = 'offline',
                        last_error = 'Keine aktuellen Messdaten',
                        updated_at = NOW()
                    WHERE
                        (
                            last_seen IS NULL
                            OR last_seen < NOW()
                                - (%s * INTERVAL '1 minute')
                        )
                        AND status <> 'offline'
                """, (OFFLINE_AFTER_MINUTES,))

                if cursor.rowcount:
                    print(
                        f"{cursor.rowcount} Gerät(e) als offline markiert."
                    )

    except psycopg.Error as error:
        print(
            f"Offline-Prüfung momentan nicht möglich: {error}"
        )


def main():
    """Startet die simulierte Datenerfassung."""

    init_queue()

    print("Simulierter Collector gestartet.")
    print(f"Lokale Warteschlange: {QUEUE_FILE}")
    print(
        "Offline-Grenze: "
        f"{OFFLINE_AFTER_MINUTES} Minuten ohne neue Messdaten."
    )
    print("Beenden mit Ctrl+C.")

    while True:
        timestamp = datetime.now(timezone.utc)

        for model in ("SEN66", "SEN69C"):
            values = generate_measurements(model)
            errors = validate_measurements(values)

            enqueue_measurement(
                timestamp,
                model,
                values,
                errors,
            )

            if errors:
                print(f"{model}: {'; '.join(errors)}")
            else:
                print(
                    f"{model}: CO2 {values['co2']} ppm, "
                    f"Temperatur {values['temperature']} °C, "
                    f"Feuchtigkeit {values['humidity']} %"
                )

        try:
            deliver_pending()
        except (psycopg.Error, ValueError) as error:
            print(
                f"Übertragung vorerst nicht möglich: {error}"
            )

        # Offline-Prüfung auch dann versuchen, wenn keine Queue
        # übertragen werden konnte.
        mark_stale_devices_offline()

        with sqlite3.connect(QUEUE_FILE) as connection:
            pending = connection.execute(
                "SELECT COUNT(*) FROM pending_measurements"
            ).fetchone()[0]

        if pending:
            print(
                f"Noch nicht übertragen: {pending} Messzyklen."
            )

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDatenerfassung beendet.")
