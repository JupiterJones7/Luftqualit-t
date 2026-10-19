
import json
import sqlite3

import collector
from datetime import datetime
import psycopg

def test_valid_measurements_are_accepted():
    values = {
        "CO2": 650.0,
        "temperature": 22.4,
        "humidity": 48.0,
    }

    assert collector.validate_measurements(values) == []


def test_co2_outside_range_is_rejected():
    values = {
        "CO2": 15000,
        "temperature": 22.4,
        "humidity": 48.0,
    }

    errors = collector.validate_measurements(values)

    assert any("CO2" in error for error in errors)


def test_missing_measurement_is_rejected():
    values = {
        "CO2": 650.0,
        "temperature": 22.4,
    }

    errors = collector.validate_measurements(values)

    assert any("humidity" in error for error in errors)


def test_invalid_temperature_is_rejected():
    values = {
        "CO2": 650.0,
        "temperature": -30,
        "humidity": 48.0,
    }

    errors = collector.validate_measurements(values)

    assert any("temperature" in error for error in errors)


def test_queue_persists_measurement(tmp_path, monkeypatch):
    queue_file = tmp_path / "test_queue.sqlite3"
    monkeypatch.setattr(collector, "QUEUE_FILE", queue_file)

    collector.init_queue()

    timestamp = datetime.fromisoformat("2026-10-19T10:00:00+00:00")
    values = {
        "CO2": 650.0,
        "temperature": 22.4,
        "humidity": 48.0,
    }

    collector.enqueue_measurement(timestamp, values, [])

    with sqlite3.connect(queue_file) as connection:
        row = connection.execute(
            """
            SELECT timestamp, values_json, errors_json
            FROM pending_measurements
            """
        ).fetchone()

    assert row is not None
    assert row[0] == timestamp.isoformat()
    assert json.loads(row[1]) == values
    assert json.loads(row[2]) == []


def test_queue_can_be_initialized_twice(tmp_path, monkeypatch):
    queue_file = tmp_path / "test_queue.sqlite3"
    monkeypatch.setattr(collector, "QUEUE_FILE", queue_file)

    collector.init_queue()
    collector.init_queue()

    assert queue_file.exists()


def test_database_failure_keeps_measurement_in_queue(
    tmp_path, monkeypatch
):
    queue_file = tmp_path / "test_queue.sqlite3"
    monkeypatch.setattr(collector, "QUEUE_FILE", queue_file)

    collector.init_queue()

    timestamp = datetime.fromisoformat(
        "2026-10-19T10:00:00+00:00"
    )
    values = {
        "CO2": 650.0,
        "temperature": 22.4,
        "humidity": 48.0,
    }

    collector.enqueue_measurement(timestamp, values, [])

    def database_unavailable(*args, **kwargs):
        raise psycopg.OperationalError("Database unavailable")

    monkeypatch.setattr(
        collector.psycopg, "connect", database_unavailable
    )

    collector.deliver_pending()

    with sqlite3.connect(queue_file) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM pending_measurements"
        ).fetchone()[0]

    assert count == 1


def test_queued_measurement_is_delivered_after_reconnection(
    tmp_path, monkeypatch
):
    queue_file = tmp_path / "test_queue.sqlite3"
    monkeypatch.setattr(collector, "QUEUE_FILE", queue_file)

    collector.init_queue()

    timestamp = datetime.fromisoformat(
        "2026-10-19T10:00:00+00:00"
    )
    values = {
        "CO2": 650.0,
        "temperature": 22.4,
        "humidity": 48.0,
    }

    collector.enqueue_measurement(timestamp, values, [])

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    delivered = []

    monkeypatch.setattr(
        collector.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(),
    )

    monkeypatch.setattr(
        collector,
        "get_database_config",
        lambda connection: (
            1,
            {"CO2": 1, "temperature": 2, "humidity": 3},
        ),
    )

    monkeypatch.setattr(
        collector,
        "save_valid",
        lambda connection, sensor_id, type_ids, values, timestamp:
            delivered.append(values.copy()),
    )

    collector.deliver_pending()

    assert len(delivered) == 1
    assert delivered[0] == values

    with sqlite3.connect(queue_file) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM pending_measurements"
        ).fetchone()[0]

    assert count == 0
