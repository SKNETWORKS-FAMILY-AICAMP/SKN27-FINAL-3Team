CREATE TABLE IF NOT EXISTS road_prod.osm_road_ways (
    id BIGSERIAL PRIMARY KEY,
    osm_way_id BIGINT,
    road_name TEXT,
    road_ref TEXT,
    highway_type TEXT,
    lane_count INTEGER,
    oneway TEXT,
    junction_type TEXT,
    destination TEXT,
    destination_ref TEXT,
    maxspeed TEXT,
    bridge TEXT,
    tunnel TEXT,
    layer TEXT,
    geom geometry(LineString, 4326),
    osm_updated_at TIMESTAMPTZ,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_tags JSONB
);

CREATE TABLE IF NOT EXISTS road_prod.road_guide_signs (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT,
    road_name TEXT,
    road_address TEXT,
    parcel_address TEXT,
    sign_type TEXT,
    direction_text TEXT,
    route_number TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geom geometry(Point, 4326),
    source_reference_date DATE,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_json JSONB
);

CREATE TABLE IF NOT EXISTS road_prod.traffic_signals (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT,
    road_name TEXT,
    road_address TEXT,
    parcel_address TEXT,
    signal_type TEXT,
    control_type TEXT,
    flashing_operation TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geom geometry(Point, 4326),
    source_reference_date DATE,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_json JSONB
);

CREATE TABLE IF NOT EXISTS road_prod.crosswalks (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT,
    road_name TEXT,
    road_address TEXT,
    parcel_address TEXT,
    crosswalk_type TEXT,
    pedestrian_signal TEXT,
    traffic_island TEXT,
    raised_crosswalk TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geom geometry(Point, 4326),
    source_reference_date DATE,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_json JSONB
);

CREATE TABLE IF NOT EXISTS road_prod.protection_zones (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT,
    zone_type TEXT,
    facility_name TEXT,
    road_address TEXT,
    parcel_address TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geom geometry(Geometry, 4326),
    source_reference_date DATE,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_json JSONB
);
