-- Speedo Live core schema (PostgreSQL; converted automatically for SQLite in development).
-- Coordinates are stored as lat/lon DOUBLE PRECISION here; 002_postgis adds geography
-- columns + GiST indexes when PostGIS is available.

CREATE TABLE users (
    id              BIGSERIAL PRIMARY KEY,
    email           VARCHAR(255) UNIQUE,
    phone           VARCHAR(20) UNIQUE,
    name            VARCHAR(120) NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    role            VARCHAR(16) NOT NULL DEFAULT 'passenger' CHECK (role IN ('passenger','driver','admin')),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL,
    last_login_at   TIMESTAMPTZ,
    CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

CREATE TABLE administrators (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    title       VARCHAR(80),
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE routes (
    id             BIGSERIAL PRIMARY KEY,
    code           VARCHAR(32) NOT NULL UNIQUE,
    name           VARCHAR(160) NOT NULL,
    description    TEXT,
    color          VARCHAR(9) NOT NULL DEFAULT '#1D4ED8',
    status         VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','inactive')),
    is_demo        BOOLEAN NOT NULL DEFAULT FALSE,
    verified       BOOLEAN NOT NULL DEFAULT FALSE,
    source         VARCHAR(255),
    shape_json     TEXT NOT NULL DEFAULT '[]',   -- JSON [[lat,lon],...] outbound geometry
    length_m       DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_speed_kmh  DOUBLE PRECISION NOT NULL DEFAULT 18,
    created_at     TIMESTAMPTZ NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE stops (
    id          BIGSERIAL PRIMARY KEY,
    code        VARCHAR(32) NOT NULL UNIQUE,
    name        VARCHAR(160) NOT NULL,
    name_ur     VARCHAR(160),
    lat         DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon         DOUBLE PRECISION NOT NULL CHECK (lon BETWEEN -180 AND 180),
    is_demo     BOOLEAN NOT NULL DEFAULT FALSE,
    status      VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active','closed')),
    created_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_stops_latlon ON stops (lat, lon);

CREATE TABLE route_stops (
    id          BIGSERIAL PRIMARY KEY,
    route_id    BIGINT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    stop_id     BIGINT NOT NULL REFERENCES stops(id) ON DELETE RESTRICT,
    seq         INTEGER NOT NULL,
    chainage_m  DOUBLE PRECISION NOT NULL DEFAULT 0,  -- distance along route from first stop
    dwell_s     INTEGER NOT NULL DEFAULT 20,
    UNIQUE (route_id, seq),
    UNIQUE (route_id, stop_id)
);
CREATE INDEX ix_route_stops_stop ON route_stops (stop_id);

CREATE TABLE drivers (
    id                   BIGSERIAL PRIMARY KEY,
    user_id              BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    employee_code        VARCHAR(32) NOT NULL UNIQUE,
    license_no           VARCHAR(40),
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    is_demo              BOOLEAN NOT NULL DEFAULT FALSE,
    location_consent_at  TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL
);

CREATE TABLE buses (
    id              BIGSERIAL PRIMARY KEY,
    bus_number      VARCHAR(32) NOT NULL UNIQUE,
    registration_no VARCHAR(32),
    capacity        INTEGER,
    route_id        BIGINT REFERENCES routes(id) ON DELETE SET NULL,
    driver_id       BIGINT UNIQUE REFERENCES drivers(id) ON DELETE SET NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive','maintenance')),
    is_demo         BOOLEAN NOT NULL DEFAULT FALSE,
    gps_device_id   VARCHAR(64) UNIQUE,
    last_lat        DOUBLE PRECISION,
    last_lon        DOUBLE PRECISION,
    last_speed_mps  DOUBLE PRECISION,
    last_heading    DOUBLE PRECISION,
    last_accuracy_m DOUBLE PRECISION,
    last_chainage_m DOUBLE PRECISION,
    last_gps_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_buses_route ON buses (route_id);

CREATE TABLE trips (
    id              BIGSERIAL PRIMARY KEY,
    bus_id          BIGINT NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
    driver_id       BIGINT REFERENCES drivers(id) ON DELETE SET NULL,
    route_id        BIGINT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    direction       VARCHAR(10) NOT NULL DEFAULT 'outbound' CHECK (direction IN ('outbound','inbound')),
    status          VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','interrupted')),
    source          VARCHAR(16) NOT NULL DEFAULT 'driver' CHECK (source IN ('driver','simulator','provider')),
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    last_gps_at     TIMESTAMPTZ,
    gps_points      INTEGER NOT NULL DEFAULT 0,
    gps_gap_s       DOUBLE PRECISION NOT NULL DEFAULT 0,   -- total seconds without fresh GPS
    offline_events  INTEGER NOT NULL DEFAULT 0,
    max_delay_min   DOUBLE PRECISION NOT NULL DEFAULT 0,
    distance_m      DOUBLE PRECISION NOT NULL DEFAULT 0,
    end_reason      VARCHAR(40)
);
CREATE INDEX ix_trips_bus_status ON trips (bus_id, status);
CREATE INDEX ix_trips_started ON trips (started_at);

CREATE TABLE gps_locations (
    id              BIGSERIAL PRIMARY KEY,
    trip_id         BIGINT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    bus_id          BIGINT NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
    lat             DOUBLE PRECISION NOT NULL,
    lon             DOUBLE PRECISION NOT NULL,
    speed_mps       DOUBLE PRECISION,
    heading         DOUBLE PRECISION,
    accuracy_m      DOUBLE PRECISION,
    chainage_m      DOUBLE PRECISION,
    low_accuracy    BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at     TIMESTAMPTZ NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_gps_trip_time ON gps_locations (trip_id, recorded_at);
CREATE INDEX ix_gps_bus_time ON gps_locations (bus_id, recorded_at);
CREATE INDEX ix_gps_recorded ON gps_locations (recorded_at);

-- Historical average speeds per route/direction/hour, used by the ETA engine.
CREATE TABLE segment_speeds (
    id              BIGSERIAL PRIMARY KEY,
    route_id        BIGINT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    direction       VARCHAR(10) NOT NULL,
    hour            INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
    samples         INTEGER NOT NULL DEFAULT 0,
    avg_speed_mps   DOUBLE PRECISION NOT NULL DEFAULT 0,
    UNIQUE (route_id, direction, hour)
);

CREATE TABLE schedules (
    id               BIGSERIAL PRIMARY KEY,
    route_id         BIGINT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    days             VARCHAR(40) NOT NULL DEFAULT 'MON,TUE,WED,THU,FRI,SAT,SUN',
    first_departure  VARCHAR(5) NOT NULL,   -- HH:MM Asia/Karachi
    last_departure   VARCHAR(5) NOT NULL,
    headway_min      INTEGER NOT NULL CHECK (headway_min > 0),
    valid_from       DATE,
    valid_to         DATE,
    notes            VARCHAR(255),
    is_demo          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_schedules_route ON schedules (route_id);

CREATE TABLE service_alerts (
    id          BIGSERIAL PRIMARY KEY,
    title       VARCHAR(160) NOT NULL,
    body        TEXT,
    severity    VARCHAR(16) NOT NULL DEFAULT 'info' CHECK (severity IN ('info','delay','disruption','suspension','schedule_change')),
    route_id    BIGINT REFERENCES routes(id) ON DELETE CASCADE,
    stop_id     BIGINT REFERENCES stops(id) ON DELETE CASCADE,
    starts_at   TIMESTAMPTZ NOT NULL,
    ends_at     TIMESTAMPTZ,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_by  BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_alerts_active ON service_alerts (is_active, starts_at);

CREATE TABLE notifications (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        VARCHAR(24) NOT NULL,   -- approaching | arriving | delay | disruption | schedule_change | info
    title       VARCHAR(160) NOT NULL,
    body        TEXT,
    data_json   TEXT,
    dedupe_key  VARCHAR(120),
    pushed      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL,
    read_at     TIMESTAMPTZ,
    UNIQUE (user_id, dedupe_key)
);
CREATE INDEX ix_notifications_user ON notifications (user_id, created_at);

CREATE TABLE notification_prefs (
    user_id             BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    approaching         BOOLEAN NOT NULL DEFAULT TRUE,
    approaching_lead_min INTEGER NOT NULL DEFAULT 5,
    delays              BOOLEAN NOT NULL DEFAULT TRUE,
    disruptions         BOOLEAN NOT NULL DEFAULT TRUE,
    schedule_changes    BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE device_tokens (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token       VARCHAR(512) NOT NULL UNIQUE,
    platform    VARCHAR(16) NOT NULL DEFAULT 'android',
    created_at  TIMESTAMPTZ NOT NULL
);

-- "Tell me when the bus approaches this stop" requests.
CREATE TABLE stop_watches (
    id                     BIGSERIAL PRIMARY KEY,
    user_id                BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    route_id               BIGINT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    stop_id                BIGINT NOT NULL REFERENCES stops(id) ON DELETE CASCADE,
    bus_id                 BIGINT REFERENCES buses(id) ON DELETE CASCADE,
    lead_min               INTEGER NOT NULL DEFAULT 5,
    created_at             TIMESTAMPTZ NOT NULL,
    expires_at             TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_watches_expires ON stop_watches (expires_at);

CREATE TABLE favorite_routes (
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    route_id    BIGINT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, route_id)
);

CREATE TABLE favorite_stops (
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stop_id     BIGINT NOT NULL REFERENCES stops(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, stop_id)
);

CREATE TABLE journey_history (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    origin_label  VARCHAR(160) NOT NULL,
    dest_label    VARCHAR(160) NOT NULL,
    route_codes   VARCHAR(120),
    created_at    TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_history_user ON journey_history (user_id, created_at);

-- Anonymous route-usage counter for reports (no personal data).
CREATE TABLE route_usage (
    id          BIGSERIAL PRIMARY KEY,
    route_id    BIGINT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    event       VARCHAR(16) NOT NULL,   -- planned | tracked | viewed
    created_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_route_usage ON route_usage (route_id, created_at);
