CREATE INDEX IF NOT EXISTS idx_osm_road_ways_geom
ON road_prod.osm_road_ways
USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_road_guide_signs_geom
ON road_prod.road_guide_signs
USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_traffic_signals_geom
ON road_prod.traffic_signals
USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_crosswalks_geom
ON road_prod.crosswalks
USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_protection_zones_geom
ON road_prod.protection_zones
USING GIST (geom);
