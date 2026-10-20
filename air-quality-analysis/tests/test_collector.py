import collector
import math
import sqlite3

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from collector import validate_measurements, generate_measurements


def test_generated_sen66_values_are_valid():
    values = generate_measurements("SEN66")
    assert validate_measurements(values, "SEN66") == []


def test_generated_sen69c_values_are_valid():
    values = generate_measurements("SEN69C")
    assert validate_measurements(values, "SEN69C") == []


def test_missing_co2_is_rejected():
    values = generate_measurements("SEN66")
    del values["co2"]

    errors = validate_measurements(values, "SEN66")

    assert any("Messgrösse fehlt: co2" in e for e in errors)


def test_negative_humidity_is_rejected():
    values = generate_measurements("SEN66")
    values["humidity"] = -5

    errors = validate_measurements(values, "SEN66")

    assert any("humidity ausserhalb" in e for e in errors)


def test_nan_is_rejected():
    values = generate_measurements("SEN66")
    values["temperature"] = math.nan

    errors = validate_measurements(values, "SEN66")

    assert any("nicht endlich" in e for e in errors)


def test_infinity_is_rejected():
    values = generate_measurements("SEN66")
    values["co2"] = math.inf

    errors = validate_measurements(values, "SEN66")

    assert any("nicht endlich" in e for e in errors)


def test_formaldehyde_is_required_for_sen69c():
    values = generate_measurements("SEN69C")
    del values["formaldehyde"]

    errors = validate_measurements(values, "SEN69C")

    assert any(
        "Messgrösse fehlt: formaldehyde" in e
        for e in errors
    )


def test_formaldehyde_is_not_required_for_sen66():
    values = generate_measurements("SEN66")

    assert "formaldehyde" not in values
    assert validate_measurements(values, "SEN66") == []


def test_corrupt_queue_json_does_not_crash(tmp_path, monkeypatch):
    queue_file = tmp_path / "test_queue.sqlite3"

    with sqlite3.connect(queue_file) as connection:
        connection.execute("""
            CREATE TABLE pending_measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                values_json TEXT NOT NULL,
                errors_json TEXT NOT NULL,
                sensor_model TEXT NOT NULL DEFAULT 'SEN66',
                device_uid TEXT
            )
        """)

        connection.execute("""
            INSERT INTO pending_measurements
                (timestamp, values_json, errors_json, sensor_model)
            VALUES (?, ?, ?, ?)
        """, (
            "2026-10-20T12:00:00+00:00",
            "{invalid-json",
            "[]",
            "SEN66",
        ))

    monkeypatch.setattr(collector, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(collector, "DATABASE_URL", "dummy")

    collector.deliver_pending()

    with sqlite3.connect(queue_file) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM pending_measurements"
        ).fetchone()[0]

    assert count == 1


def test_queue_entry_is_kept_when_database_fails(tmp_path, monkeypatch):
    queue_file = tmp_path / "test_queue.sqlite3"

    with sqlite3.connect(queue_file) as connection:
        connection.execute("""
            CREATE TABLE pending_measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                values_json TEXT NOT NULL,
                errors_json TEXT NOT NULL,
                sensor_model TEXT NOT NULL DEFAULT 'SEN66',
                device_uid TEXT
            )
        """)

        connection.execute("""
            INSERT INTO pending_measurements
                (timestamp, values_json, errors_json, sensor_model)
            VALUES (?, ?, ?, ?)
        """, (
            "2026-10-20T12:00:00+00:00",
            '{"co2": 800}',
            '[]',
            "SEN66",
        ))

    monkeypatch.setattr(collector, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(collector, "DATABASE_URL", "postgresql://invalid")

    def fail_database_connection(*args, **kwargs):
        raise collector.psycopg.OperationalError(
            "Simulierter Verbindungsausfall"
        )

    monkeypatch.setattr(
        collector.psycopg,
        "connect",
        fail_database_connection,
    )

    collector.deliver_pending()

    with sqlite3.connect(queue_file) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM pending_measurements"
        ).fetchone()[0]

    assert count == 1

def test_current_measurement_sets_online_status():
    connection = MagicMock()
    now = datetime.now(timezone.utc)

    collector.update_device_status(
        connection,
        device_id=1,
        status="online",
        last_seen=now,
    )

    connection.cursor.assert_called_once()

def test_old_measurement_is_not_marked_online():
    connection = MagicMock()
    old_timestamp = datetime.now(timezone.utc) - timedelta(minutes=5)

    collector.update_device_status(
        connection,
        device_id=1,
        status="online",
        last_seen=old_timestamp,
    )

    connection.cursor.assert_called_once()


def test_missing_timestamp_does_not_set_online():
    connection = MagicMock()

    collector.update_device_status(
        connection,
        device_id=1,
        status="online",
        last_seen=None,
    )

    connection.cursor.assert_called_once()


def test_current_measurement_uses_online_status():
    connection = MagicMock()
    now = datetime.now(timezone.utc)

    collector.update_device_status(
        connection,
        device_id=1,
        status="online",
        last_seen=now,
    )

    args = connection.cursor.return_value.__enter__.return_value.execute.call_args
    sql = args.args[0]
    params = args.args[1]

    assert "INSERT INTO device_status" in sql
    assert "ON CONFLICT (device_id)" in sql
    assert "online" in params
    assert now in params


def test_old_measurement_is_not_set_online_by_python_logic():
    connection = MagicMock()
    old_timestamp = datetime.now(timezone.utc) - timedelta(minutes=5)

    collector.update_device_status(
        connection,
        device_id=1,
        status="online",
        last_seen=old_timestamp,
    )

    args = connection.cursor.return_value.__enter__.return_value.execute.call_args
    params = args.args[1]

    # Die Funktion sollte einen veralteten Messzeitpunkt
    # bereits vor dem SQL-Aufruf als offline einstufen.
    assert "offline" in params
    assert "Keine aktuellen Messdaten" in params


def test_missing_timestamp_sets_unknown_status():
    connection = MagicMock()

    collector.update_device_status(
        connection,
        device_id=1,
        status="online",
        last_seen=None,
    )

    args = connection.cursor.return_value.__enter__.return_value.execute.call_args
    params = args.args[1]

    assert "unknown" in params
    assert "Kein Messzeitpunkt vorhanden." in params



def test_stale_invalid_cycle_preserves_recent_online_status():
    connection = MagicMock()
    cursor = MagicMock()

    connection.cursor.return_value.__enter__.return_value = cursor

    collector.update_device_status(
        connection,
        device_id=1,
        status="warning",
        last_seen=None,
        last_error="Ungültige Messwerte",
    )

    cursor.execute.assert_called_once()

    sql, params = cursor.execute.call_args.args

    # Die SQL-Anweisung muss den bisherigen Status berücksichtigen.
    assert "device_status.last_seen" in sql
    assert "device_status.status = 'online'" in sql

    # Die Aktualitätsgrenze muss geprüft werden.
    assert "INTERVAL '1 minute'" in sql

    assert params[-4:] == (
        collector.OFFLINE_AFTER_MINUTES,
        collector.OFFLINE_AFTER_MINUTES,
        collector.OFFLINE_AFTER_MINUTES,
        collector.OFFLINE_AFTER_MINUTES,
    )
