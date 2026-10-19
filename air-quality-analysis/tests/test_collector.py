
import json
import sqlite3

import collector
from datetime import datetime

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
