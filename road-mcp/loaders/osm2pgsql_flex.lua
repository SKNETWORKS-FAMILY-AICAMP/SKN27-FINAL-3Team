local road_ways = osm2pgsql.define_way_table('osm_road_ways', {
    { column = 'osm_way_id', type = 'bigint' },
    { column = 'road_name', type = 'text' },
    { column = 'road_ref', type = 'text' },
    { column = 'highway_type', type = 'text' },
    { column = 'lane_count', type = 'int' },
    { column = 'oneway', type = 'text' },
    { column = 'junction_type', type = 'text' },
    { column = 'destination', type = 'text' },
    { column = 'destination_ref', type = 'text' },
    { column = 'maxspeed', type = 'text' },
    { column = 'bridge', type = 'text' },
    { column = 'tunnel', type = 'text' },
    { column = 'layer', type = 'text' },
    { column = 'raw_tags', type = 'jsonb' },
    { column = 'geom', type = 'linestring', projection = 4326 },
})

function osm2pgsql.process_way(object)
    local highway = object.tags.highway
    if not highway then
        return
    end

    road_ways:insert({
        osm_way_id = object.id,
        road_name = object.tags.name,
        road_ref = object.tags.ref,
        highway_type = highway,
        lane_count = tonumber(object.tags.lanes),
        oneway = object.tags.oneway,
        junction_type = object.tags.junction,
        destination = object.tags.destination,
        destination_ref = object.tags['destination:ref'],
        maxspeed = object.tags.maxspeed,
        bridge = object.tags.bridge,
        tunnel = object.tags.tunnel,
        layer = object.tags.layer,
        raw_tags = object.tags,
        geom = object:as_linestring(),
    })
end
