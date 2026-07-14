from typing import Any

from app.db import connect


def find_nearby_road_environment(latitude: float, longitude: float, radius_m: int = 80) -> dict[str, Any]:
    query = """
        SELECT
            osm_way_id,
            road_name,
            road_ref,
            highway_type,
            lane_count,
            oneway,
            ST_Distance(
                geom::geography,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
            ) AS distance_m
        FROM road_prod.osm_road_ways
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
            %s
        )
        ORDER BY distance_m ASC
        LIMIT 5
    """
    with connect() as conn:
        rows = conn.execute(query, (longitude, latitude, longitude, latitude, radius_m)).fetchall()
    return {"radius_m": radius_m, "road_candidates": [dict(row) for row in rows]}
