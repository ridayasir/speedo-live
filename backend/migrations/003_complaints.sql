-- Passenger complaints about a bus / its driver (filed with the bus number).
CREATE TABLE complaints (
    id                 BIGSERIAL PRIMARY KEY,
    ref_code           VARCHAR(16) NOT NULL UNIQUE,      -- given to the passenger to check status
    bus_id             BIGINT REFERENCES buses(id) ON DELETE SET NULL,
    bus_number         VARCHAR(32) NOT NULL,             -- as found at filing time (kept if the bus is deleted)
    route_id           BIGINT REFERENCES routes(id) ON DELETE SET NULL,
    driver_id          BIGINT REFERENCES drivers(id) ON DELETE SET NULL,   -- driver on that bus when the complaint was filed
    category           VARCHAR(24) NOT NULL CHECK (category IN ('rash_driving','rude_behaviour','harassment','overcharging',
                           'skipped_stop','phone_smoking','late','bus_condition','other')),
    description        TEXT NOT NULL,
    location           VARCHAR(160),
    incident_at        TIMESTAMPTZ NOT NULL,
    user_id            BIGINT REFERENCES users(id) ON DELETE SET NULL,
    contact_name       VARCHAR(120),
    contact_phone      VARCHAR(20),
    status             VARCHAR(16) NOT NULL DEFAULT 'new' CHECK (status IN ('new','in_review','resolved','rejected')),
    admin_note         TEXT,
    handled_by         BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL,
    updated_at         TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_complaints_status ON complaints (status, created_at);
CREATE INDEX ix_complaints_driver ON complaints (driver_id);
CREATE INDEX ix_complaints_bus ON complaints (bus_id);
CREATE INDEX ix_complaints_user ON complaints (user_id);
