
-- Air Quality Analysis: neue Datenbankstruktur
-- In der neuen Datenbank ausführen.

CREATE TABLE IF NOT EXISTS devices (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_uid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    location TEXT,
    firmware_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS sensors (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id BIGINT NOT NULL REFERENCES devices(id),
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    serial_number TEXT,
    location TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS measurement_types (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    description TEXT,
    min_plausible DOUBLE PRECISION,
    max_plausible DOUBLE PRECISION,
    CHECK (
        min_plausible IS NULL
        OR max_plausible IS NULL
        OR min_plausible <= max_plausible
    )
);

CREATE TABLE IF NOT EXISTS measurements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id BIGINT NOT NULL REFERENCES sensors(id),
    measurement_type_id BIGINT NOT NULL
        REFERENCES measurement_types(id),
    measured_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    value DOUBLE PRECISION NOT NULL,
    source_message_id TEXT,
    CHECK (value > '-Infinity'::DOUBLE PRECISION
           AND value < 'Infinity'::DOUBLE PRECISION),
    UNIQUE (sensor_id, measurement_type_id, measured_at)
);

CREATE INDEX IF NOT EXISTS idx_measurements_time
    ON measurements (measured_at DESC);

CREATE INDEX IF NOT EXISTS idx_measurements_sensor_time
    ON measurements (sensor_id, measured_at DESC);

CREATE TABLE IF NOT EXISTS measurement_aggregates (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id BIGINT NOT NULL REFERENCES sensors(id),
    measurement_type_id BIGINT NOT NULL
        REFERENCES measurement_types(id),
    bucket_start TIMESTAMPTZ NOT NULL,
    average_value DOUBLE PRECISION,
    min_value DOUBLE PRECISION,
    max_value DOUBLE PRECISION,
    last_value DOUBLE PRECISION,
    sample_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE (sensor_id, measurement_type_id, bucket_start),
    CHECK (sample_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_aggregates_time
    ON measurement_aggregates (bucket_start DESC);

CREATE TABLE IF NOT EXISTS rejected_measurements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id BIGINT REFERENCES sensors(id),
    raw_record JSONB NOT NULL,
    rejection_reason TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_message_id TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS device_status (
    device_id BIGINT PRIMARY KEY REFERENCES devices(id),
    last_seen TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'unknown',
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
