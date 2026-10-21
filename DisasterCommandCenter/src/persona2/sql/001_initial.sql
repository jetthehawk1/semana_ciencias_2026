CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.simulations (
    run_id TEXT PRIMARY KEY CHECK (length(trim(run_id)) > 0),
    schema_version TEXT NOT NULL CHECK (schema_version = '1.0'),
    dataset_kind TEXT NOT NULL CHECK (dataset_kind = 'synthetic_simulation'),
    manifest JSONB NOT NULL,
    package_hash TEXT NOT NULL CHECK (length(package_hash) = 64),
    sampling_interval INTEGER NOT NULL CHECK (sampling_interval > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS {schema}.sensors (
    run_id TEXT NOT NULL REFERENCES {schema}.simulations(run_id),
    sensor_id TEXT NOT NULL CHECK (length(trim(sensor_id)) > 0),
    x INTEGER NOT NULL CHECK (x >= 0 AND x < 160),
    y INTEGER NOT NULL CHECK (y >= 0 AND y < 100),
    building_id TEXT,
    PRIMARY KEY (run_id, sensor_id)
);
CREATE TABLE IF NOT EXISTS {schema}.readings (
    run_id TEXT NOT NULL,
    turn INTEGER NOT NULL CHECK (turn >= 0),
    sensor_id TEXT NOT NULL,
    temperature_c DOUBLE PRECISION NOT NULL CHECK (temperature_c BETWEEN -50 AND 500),
    smoke_index DOUBLE PRECISION NOT NULL CHECK (smoke_index BETWEEN 0 AND 1),
    alarm BOOLEAN NOT NULL,
    fire_within_2_cells BOOLEAN NOT NULL,
    PRIMARY KEY (run_id, turn, sensor_id),
    FOREIGN KEY (run_id, sensor_id) REFERENCES {schema}.sensors(run_id, sensor_id)
);
CREATE TABLE IF NOT EXISTS {schema}.events (
    run_id TEXT NOT NULL,
    turn INTEGER NOT NULL,
    sensor_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind = 'sensor_alarm'),
    details JSONB NOT NULL,
    PRIMARY KEY (run_id, turn, sensor_id, kind),
    FOREIGN KEY (run_id, turn, sensor_id) REFERENCES {schema}.readings(run_id, turn, sensor_id)
);
CREATE TABLE IF NOT EXISTS {schema}.models (
    model_id TEXT PRIMARY KEY CHECK (length(trim(model_id)) > 0),
    metadata JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS {schema}.predictions (
    run_id TEXT NOT NULL,
    turn INTEGER NOT NULL,
    sensor_id TEXT NOT NULL,
    model_id TEXT NOT NULL REFERENCES {schema}.models(model_id),
    predicted_fire_within_2_cells BOOLEAN NOT NULL,
    PRIMARY KEY (run_id, turn, sensor_id, model_id),
    FOREIGN KEY (run_id, turn, sensor_id) REFERENCES {schema}.readings(run_id, turn, sensor_id)
);
CREATE TABLE IF NOT EXISTS {schema}.reports (
    report_id TEXT PRIMARY KEY CHECK (length(report_id) = 64),
    run_id TEXT NOT NULL REFERENCES {schema}.simulations(run_id),
    kind TEXT NOT NULL CHECK (kind IN ('eda', 'baseline', 'comparison', 'integration')),
    report JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
