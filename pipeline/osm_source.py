#!/usr/bin/env python3
"""Yerevan's buildings, straight from live OSM.

The PBF path this replaces was never slow — it was *stale*. Geofabrik cuts
`armenia-latest.osm.pbf` once a day around 20:21 UTC and publishes hours later,
so an edit made this afternoon could not reach a build today no matter how often
you rebuilt. For a project whose loop is "split a building, see the pieces come
back for review", a day of latency is the whole cost.

Overpass answers the same question about live data. Measured on the real city,
not assumed:

    76,315 ways + 263 multipolygon relations     10.3 s     56.7 MB
    timestamp_osm_base 17 minutes old at the time of writing

Two things get simpler on the way, which is unusual for a swap like this:

  * **the boundary clip disappears.** `map_to_area` runs it server-side, so the
    1,188-point ring index, the latitude bucketing and the per-building
    point-in-polygon test are all replaced by one line of query. The PBF needed
    them because a country extract has no idea where the city is.
  * **the download is the parse.** No pyosmium area assembly pass over 53 MB of
    a whole country to reach 76k buildings in one city.

What is NOT simpler is multipolygons. pyosmium assembled those for free; here
their rings arrive as unordered member ways that have to be stitched, which is
what `stitch_rings` is for. 263 of 76,578 areas — a third of a percent, and the
only real work in this file.

Reproducibility is the honest cost. A PBF is a file you can keep and rebuild
from a year later; an Overpass query is a moving target. So the raw response is
cached, and `timestamp_osm_base` is carried out as the provenance stamp that
`osmosis_replication_timestamp` used to be. Rebuilding from the cache reproduces
a build exactly; refreshing is an explicit act.
"""
import json
import os
import ssl
import time
import urllib.parse
import urllib.request

import paths

OVERPASS = 'https://overpass-api.de/api/interpreter'
YEREVAN_RELATION = 364087
CACHE_FILE = paths.OVERPASS_CACHE

# Everything is_relevant_area() would keep, asked for once rather than filtered
# out of a whole country. Kept deliberately loose — the tag filtering still
# happens downstream in one place, and a query that decides relevance too would
# be a second copy of that rule living somewhere nobody would think to look.
QUERY = '''[out:json][timeout:600];
rel({relation});map_to_area->.city;
(
  way["building"](area.city);
  rel["building"](area.city);
  way["leisure"="stadium"](area.city);
  rel["leisure"="stadium"](area.city);
  way["tourism"="attraction"](area.city);
  rel["tourism"="attraction"](area.city);
  way["man_made"="tower"](area.city);
);
out geom;
'''


def _ssl_context():
    """A context with root certificates.

    A python.org build on macOS ships without them unless its bundled
    `Install Certificates.command` has been run, and urllib then fails every
    https request with CERTIFICATE_VERIFY_FAILED. See osm_live.ssl_context.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch(cache=CACHE_FILE, refresh=True, relation=YEREVAN_RELATION, url=OVERPASS):
    """The raw Overpass response, from the network or the cache.

    `refresh=False` rebuilds from whatever is cached, which is what makes a
    build reproducible: same cache, same output, no network. Overpass is a
    shared public service and a 57 MB query is not free to it, so a rebuild that
    does not need newer data should not ask for any.
    """
    if not refresh and os.path.exists(cache):
        with open(cache, encoding='utf-8') as f:
            return json.load(f)

    body = urllib.parse.urlencode(
        {'data': QUERY.format(relation=relation)}).encode()
    req = urllib.request.Request(url, data=body, headers={
        'User-Agent': 'UrbanLayers/1.0 (+https://urbanlayers.xyz)'})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=900, context=_ssl_context()) as res:
            data = json.loads(res.read())
    except Exception as err:
        # Overpass being down or rate-limiting must not destroy the ability to
        # build. The cache is a worse answer than live data and an enormously
        # better one than no map, so it is used loudly rather than silently.
        if os.path.exists(cache):
            print(f'  ⚠ Overpass failed ({err}) — building from the cached copy')
            with open(cache, encoding='utf-8') as f:
                return json.load(f)
        raise
    print(f'  fetched in {time.time() - started:.1f}s')
    with open(cache, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return data


def base_timestamp(data):
    """When OSM's data was current, as Overpass reports it — the replacement for
    the PBF's osmosis_replication_timestamp, and the stamp a build is pinned to."""
    return (data.get('osm3s') or {}).get('timestamp_osm_base')


def _ring(points):
    """[[lon, lat], …] closed, from Overpass `geometry`. None if degenerate."""
    coords = [[p['lon'], p['lat']] for p in points if p]
    if len(coords) < 3:
        return None
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def stitch_rings(segments):
    """Unordered member ways → closed rings.

    A multipolygon's outer boundary is frequently several ways that only form a
    ring end to end, in no particular order and in either direction. pyosmium did
    this silently on the PBF path; Overpass hands over the pieces.

    Anything that will not close is dropped rather than guessed at: a building
    drawn as an unclosed boundary is broken upstream, and inventing the missing
    edge would put a wrong footprint on the map with no way to tell.
    """
    pending = [list(s) for s in segments if s and len(s) >= 2]
    rings = []
    while pending:
        chain = pending.pop(0)
        joined = True
        while chain[0] != chain[-1] and joined:
            joined = False
            for i, seg in enumerate(pending):
                if seg[0] == chain[-1]:
                    chain += seg[1:]
                elif seg[-1] == chain[-1]:
                    chain += seg[-2::-1]
                elif seg[-1] == chain[0]:
                    chain = seg[:-1] + chain
                elif seg[0] == chain[0]:
                    chain = seg[:0:-1] + chain
                else:
                    continue
                pending.pop(i)
                joined = True
                break
        if chain[0] == chain[-1] and len(chain) >= 4:
            rings.append(chain)
    return rings


def _relation_geometry(rel):
    """GeoJSON Polygon/MultiPolygon from a multipolygon relation, or None.

    Inner rings are matched to outers by containment rather than by order, since
    the members arrive in neither. One point-in-ring test per inner against each
    outer — there are 263 relations in the whole city, so the naive loop is the
    right one.
    """
    outers, inners = [], []
    for m in rel.get('members', []):
        if m.get('type') != 'way' or not m.get('geometry'):
            continue
        seg = [[p['lon'], p['lat']] for p in m['geometry']]
        (inners if m.get('role') == 'inner' else outers).append(seg)

    outer_rings = stitch_rings(outers)
    if not outer_rings:
        return None
    inner_rings = stitch_rings(inners)

    def contains(ring, lon, lat):
        inside = False
        for i in range(len(ring) - 1):
            x1, y1 = ring[i]
            x2, y2 = ring[i + 1]
            if (y1 > lat) != (y2 > lat):
                if lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                    inside = not inside
        return inside

    polys = []
    for outer in outer_rings:
        holes = [h for h in inner_rings if contains(outer, h[0][0], h[0][1])]
        polys.append([outer] + holes)

    if len(polys) == 1:
        return {'type': 'Polygon', 'coordinates': polys[0]}
    return {'type': 'MultiPolygon', 'coordinates': polys}


class Area:
    """One building, wearing the interface the PBF parse loop already speaks.

    `.tags`, `.orig_id()` and `.from_way()` are pyosmium's names on purpose: the
    loop in fetch_buildings.py that turns an area into a feature is good code
    that had nothing to do with where the area came from, and it is left alone.
    """

    __slots__ = ('tags', '_id', '_is_way', 'geometry')

    def __init__(self, tags, osm_id, is_way, geometry):
        self.tags = tags
        self._id = osm_id
        self._is_way = is_way
        self.geometry = geometry

    def orig_id(self):
        return self._id

    def from_way(self):
        return self._is_way


def iter_areas(data):
    """Every building in the response, as Area objects. Skips broken geometry."""
    skipped = 0
    for el in data.get('elements', []):
        tags = el.get('tags') or {}
        if el['type'] == 'way':
            ring = _ring(el.get('geometry') or [])
            geometry = {'type': 'Polygon', 'coordinates': [ring]} if ring else None
        elif el['type'] == 'relation':
            geometry = _relation_geometry(el)
        else:
            continue
        if geometry is None:
            skipped += 1
            continue
        yield Area(tags, el['id'], el['type'] == 'way', geometry)
    if skipped:
        print(f'  ⚠ {skipped} area(s) skipped — geometry that does not close')
