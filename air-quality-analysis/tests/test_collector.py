
import math

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
