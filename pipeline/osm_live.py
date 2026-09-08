#!/usr/bin/env python3
"""Patch the last build up to live OSM, without waiting for Geofabrik.

    python3 osm_live.py                        # what changed since the PBF was cut
    python3 osm_live.py --write build/live.geojson

Geofabrik cuts `armenia-latest.osm.pbf` **once a day**, around 20:21 UTC, and
publishes it some hours after that. Verified from the replication headers rather
than assumed: sequence 3032 → 3035 spans three days, one per day. So an edit made
this afternoon cannot reach a PBF build today, and `fetch_buildings.py` makes
that worse by only downloading when the file is ABSENT — a cached extract sits
there forever until somebody deletes it.

That is fine for rendering and useless for the loop this project actually needs:
split a building, see the pieces come back for review. Overpass is minutely
fresh (`timestamp_osm_base` was 21 minutes old when this was written), so the
gap is closed from the other end — the build stays PBF-derived, and only what
has changed since the cut is fetched live and patched over the top.

Why an augmented diff rather than a plain query
-----------------------------------------------
`[adiff:"<since>"]` returns an ACTION per object — create, modify, delete — and
for a modify it returns BOTH `<old>` and `<new>` geometry. That matters more
than it sounds:

  * deletions are visible at all. A plain `(changed:"…")` query returns what
    exists now, so a building deleted since the cut is simply absent from the
    answer and indistinguishable from one that never changed.
  * a split's parent arrives with the footprint it had BEFORE the split, which
    is exactly what detect_splits.py needs to find the pieces — no second build
    to diff against.

Only `way` is handled. Multipolygon buildings are relations and are left to the
PBF path: assembling one correctly means resolving member ways and inner rings,
which pyosmium already does properly and this does not attempt badly.
"""
import argparse
import json
import os
import sys
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import paths

OVERPASS = 'https://overpass-api.de/api/interpreter'
YEREVAN_RELATION = 364087
PBF_FILE = paths.PBF
PREV_BUILD = paths.BUILDINGS

# Same list fetch_buildings.py reads, in the same order — a year on a patched
# feature has to mean what a year on a built one means, or the additive rule
# starts answering differently depending on which path a building arrived by.
YEAR_TAGS = ('start_date', 'year_of_construction', 'construction_date', 'opening_date')

QUERY = '''[adiff:"{since}"][out:xml][timeout:180];
rel({relation});map_to_area->.city;
way["building"](area.city);
out meta geom;
'''


def pbf_timestamp(path):
    """The replication moment the local extract was cut at — the point live OSM
    has to be asked about, and the reason this is not a fixed lookback window."""
    try:
        import osmium
    except ImportError:
        sys.exit('pyosmium is needed to read the PBF replication header')
    if not os.path.exists(path):
        sys.exit(f'{path} does not exist — nothing to patch onto')
    stamp = osmium.io.Reader(path).header().get('osmosis_replication_timestamp')
    if not stamp:
        sys.exit(f'{path} carries no replication timestamp; re-download it from Geofabrik')
    return stamp


def ssl_context():
    """A context that actually has root certificates.

    A python.org build on macOS ships without them unless its bundled
    `Install Certificates.command` has been run, and urllib then fails every
    https request with CERTIFICATE_VERIFY_FAILED. requests works on this machine
    only because it quietly uses certifi, so this does the same explicitly
    rather than leaving the script broken on the interpreter that is on PATH.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch(since, relation=YEREVAN_RELATION, url=OVERPASS):
    body = urllib.parse.urlencode(
        {'data': QUERY.format(since=since, relation=relation)}).encode()
    req = urllib.request.Request(url, data=body, headers={
        'User-Agent': 'UrbanLayers/1.0 (+https://urbanlayers.xyz)'})
    with urllib.request.urlopen(req, timeout=200, context=ssl_context()) as res:
        return res.read()


def ring_of(way):
    """[[lon, lat], …] closed, from an Overpass `geom` way."""
    pts = [[float(n.get('lon')), float(n.get('lat'))] for n in way.findall('nd')]
    if len(pts) < 3:
        return None
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def tags_of(el):
    return {t.get('k'): t.get('v') for t in el.findall('tag')}


def year_of(tags):
    """The OSM year, if the tags carry one — the only source a way created since
    the cut can have. A suggestion cannot exist for an id nobody has seen yet."""
    for key in YEAR_TAGS:
        raw = (tags.get(key) or '').strip()
        if len(raw) >= 4 and raw[:4].isdigit():
            return int(raw[:4])
    return None


def feature(way, tags):
    ring = ring_of(way)
    if ring is None:
        return None
    year = year_of(tags)
    props = {'id': int(way.get('id'))}
    if year is not None:
        props['year_built'] = year
    if tags.get('name'):
        props['name'] = tags['name']
    return {'type': 'Feature', 'properties': props,
            'geometry': {'type': 'Polygon', 'coordinates': [ring]}}


def parse_adiff(xml_bytes):
    """(created, modified, deleted, old_shapes) from an augmented diff.

    `old_shapes` is the pre-edit footprint of every modified way, keyed by id —
    the half a plain query cannot give you, and the half a split is found by.
    """
    root = ET.fromstring(xml_bytes)
    created, modified, deleted, old_shapes = {}, {}, set(), {}

    for action in root.iter('action'):
        kind = action.get('type')
        if kind == 'delete':
            # <old> holds the last version that existed; <new> is a tombstone
            for holder in action.findall('old'):
                for way in holder.findall('way'):
                    deleted.add(int(way.get('id')))
            continue

        new_holder = action.find('new') or action
        for way in new_holder.findall('way'):
            f = feature(way, tags_of(way))
            if f is None:
                continue
            (created if kind == 'create' else modified)[int(way.get('id'))] = f

        for holder in action.findall('old'):
            for way in holder.findall('way'):
                ring = ring_of(way)
                if ring:
                    old_shapes[int(way.get('id'))] = {
                        'type': 'Feature',
                        'properties': {'id': int(way.get('id'))},
                        'geometry': {'type': 'Polygon', 'coordinates': [ring]}}
    return created, modified, deleted, old_shapes


def patch(features, created, modified, deleted):
    """The previous build, brought up to live OSM.

    Properties on a patched feature are deliberately thin: an id, an OSM year if
    the tags carry one, a name. Everything else fetch_buildings.py computes —
    era inference, the suggestions merge — is left to the
    next real build. This file exists to answer "what is the CURRENT set of
    footprints", which is the only question split detection asks.
    """
    out = []
    for f in features:
        osm_id = int(f['properties']['id'])
        if osm_id in deleted:
            continue
        if osm_id in modified:
            # keep the properties the build computed, take the new geometry
            merged = dict(f)
            merged['geometry'] = modified[osm_id]['geometry']
            out.append(merged)
            continue
        out.append(f)
    seen = {int(f['properties']['id']) for f in out}
    out.extend(f for osm_id, f in created.items() if osm_id not in seen)
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pbf', default=PBF_FILE)
    ap.add_argument('--prev', default=PREV_BUILD,
                    help='the build to patch (default: %(default)s)')
    ap.add_argument('--write', metavar='PATH',
                    help='write the patched, current feature set here')
    ap.add_argument('--old-shapes', metavar='PATH',
                    help="write modified ways' PRE-edit footprints here, for "
                         "detect_splits.py --old")
    ap.add_argument('--since', help='override the PBF replication timestamp')
    ap.add_argument('--cache', metavar='PATH', help='reuse a saved adiff response')
    args = ap.parse_args()

    since = args.since or pbf_timestamp(args.pbf)
    print(f'PBF was cut at {since}')

    if args.cache and os.path.exists(args.cache):
        xml_bytes = open(args.cache, 'rb').read()
        print(f'  using cached {args.cache}')
    else:
        print('  asking Overpass what changed since…')
        xml_bytes = fetch(since)
        if args.cache:
            open(args.cache, 'wb').write(xml_bytes)

    created, modified, deleted, old_shapes = parse_adiff(xml_bytes)
    print(f'\n{len(created)} created, {len(modified)} modified, '
          f'{len(deleted)} deleted since the cut')

    if not (created or modified or deleted):
        print('Nothing has changed — the PBF build is already current.')
        return 0

    for osm_id, f in sorted(created.items()):
        print(f"  + way {osm_id:>12}  new")
    for osm_id in sorted(modified):
        print(f"  ~ way {osm_id:>12}  geometry changed")
    for osm_id in sorted(deleted):
        print(f"  - way {osm_id:>12}  deleted")

    if not args.write:
        print('\nDry run — nothing written. Re-run with --write PATH.')
        return 0

    with open(args.prev, encoding='utf-8') as f:
        features = json.load(f)['features']
    patched = patch(features, created, modified, deleted)
    with open(args.write, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': patched}, f)
    print(f'\n✓ {args.write}: {len(features):,} → {len(patched):,} features, current to live OSM')

    if args.old_shapes:
        # A split's parent is a MODIFY, and its old footprint is the outline the
        # new pieces have to be found inside. Handing it to detect_splits.py as
        # the "old" side is what makes this work with no second build.
        base = {int(f['properties']['id']): f for f in features}
        shapes = [{**base.get(i, s), 'geometry': s['geometry']}
                  for i, s in sorted(old_shapes.items())]
        with open(args.old_shapes, 'w', encoding='utf-8') as f:
            json.dump({'type': 'FeatureCollection', 'features': shapes}, f)
        print(f'✓ {args.old_shapes}: {len(shapes)} pre-edit footprint(s)')

    return 0


if __name__ == '__main__':
    sys.exit(main())
