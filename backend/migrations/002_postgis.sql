-- Applied only on PostgreSQL with ENABLE_POSTGIS=true.
-- Adds geography columns (kept in sync from lat/lon by triggers) and GiST indexes
-- for fast "nearby stops" and spatial reporting queries.

CREATE EXTENSION IF NOT EXISTS postgis;

ALTER TABLE stops ADD COLUMN geom geography(Point, 4326);
ALTER TABLE gps_locations ADD COLUMN geom geography(Point, 4326);
ALTER TABLE buses ADD COLUMN last_geom geography(Point, 4326);
ALTER TABLE routes ADD COLUMN shape geography(LineString, 4326);

CREATE OR REPLACE FUNCTION speedo_sync_point() RETURNS trigger AS $$
BEGIN
    NEW.geom := ST_SetSRID(ST_MakePoint(NEW.lon, NEW.lat), 4326)::geography;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION speedo_sync_bus_point() RETURNS trigger AS $$
BEGIN
    IF NEW.last_lat IS NOT NULL AND NEW.last_lon IS NOT NULL THEN
        NEW.last_geom := ST_SetSRID(ST_MakePoint(NEW.last_lon, NEW.last_lat), 4326)::geography;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION speedo_sync_route_shape() RETURNS trigger AS $$
DECLARE pts geometry[];
BEGIN
    SELECT array_agg(ST_SetSRID(ST_MakePoint((p->>1)::float8, (p->>0)::float8), 4326) ORDER BY ord)
      INTO pts
      FROM jsonb_array_elements(NEW.shape_json::jsonb) WITH ORDINALITY AS t(p, ord);
    IF array_length(pts, 1) >= 2 THEN
        NEW.shape := ST_MakeLine(pts)::geography;
    ELSE
        NEW.shape := NULL;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_stops_geom BEFORE INSERT OR UPDATE OF lat, lon ON stops
    FOR EACH ROW EXECUTE FUNCTION speedo_sync_point();
CREATE TRIGGER trg_gps_geom BEFORE INSERT ON gps_locations
    FOR EACH ROW EXECUTE FUNCTION speedo_sync_point();
CREATE TRIGGER trg_bus_geom BEFORE INSERT OR UPDATE OF last_lat, last_lon ON buses
    FOR EACH ROW EXECUTE FUNCTION speedo_sync_bus_point();
CREATE TRIGGER trg_route_shape BEFORE INSERT OR UPDATE OF shape_json ON routes
    FOR EACH ROW EXECUTE FUNCTION speedo_sync_route_shape();

UPDATE stops SET lat = lat;
UPDATE routes SET shape_json = shape_json;

CREATE INDEX ix_stops_geom ON stops USING GIST (geom);
CREATE INDEX ix_gps_geom ON gps_locations USING GIST (geom);
CREATE INDEX ix_buses_geom ON buses USING GIST (last_geom);
CREATE INDEX ix_routes_shape ON routes USING GIST (shape);
