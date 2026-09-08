import argparse
import requests
import hashlib
import json
import re
import sys
import os
import csv
import osmium

import osm_source
import paths
from paths import rel

PBF_URL = "https://download.geofabrik.de/asia/armenia-latest.osm.pbf"
PBF_FILE = paths.PBF
SUGGESTIONS_FILE = paths.SUGGESTIONS
PROVENANCE_FILE = paths.PROVENANCE

# A coarse prefilter, NOT the crop. The real crop is Yerevan's administrative
# boundary, applied after the parse (see the clip below) — this box only exists
# to throw away most of Armenia cheaply before the expensive test runs.
#
# It must be a strict superset of that boundary or it would clip the city itself,
# which the old hand-drawn box actually did: at max_lat 40.23 and min_lon 44.38
# it cut real Yerevan off in the north and west, while running down to 40.05 in
# the south — ~1.8km past the city, into Ararat province. The boundary spans
# lat 40.0659–40.2418, lon 44.3621–44.6218; this is that, padded.
YEREVAN = dict(min_lat=40.055, max_lat=40.252, min_lon=44.352, max_lon=44.632)

# The city itself: relation 364087, "Երևան", admin_level 4 (Yerevan is a
# marz-equivalent). Matched on tags as well as id, so a renumbering upstream
# can't silently take the crop back to being that bounding box.
YEREVAN_RELATION = 364087

parser = argparse.ArgumentParser(description="Fetch Yerevan buildings and tag them with construction years.")
parser.add_argument('--no-infer', action='store_true',
                     help="skip inferred_buildings.json (khrushchevka/brezhnevka estimates); "
                          "only use known OSM tags and manual suggestions")
parser.add_argument('--source', choices=('overpass', 'pbf'), default='overpass',
                    help="where the buildings come from. 'overpass' (default) is "
                         "LIVE OSM, current to the minute. 'pbf' is Geofabrik's "
                         "daily extract, which is cut once a day around 20:21 UTC "
                         "and published hours after that — so an edit made today "
                         "cannot appear in a pbf build today, however often you "
                         "rebuild. Kept as a fallback for when Overpass is "
                         "unreachable, and for rebuilding an old state offline.")
parser.add_argument('--no-refresh', action='store_true',
                    help='reuse the cached Overpass response instead of asking '
                         'for newer data. This is what makes a build reproducible '
                         '— same cache, same output, no network — and Overpass is '
                         'a shared service that should not be asked twice for data '
                         'that has not changed.')
parser.add_argument('--out-dir', default=str(paths.BUILD), metavar='DIR',
                     help=f"where to write buildings.geojson, stats.json and needs_data.csv "
                          f"(default: {paths.rel(paths.BUILD)}). The editor and the public "
                          f"build read the same dataset from there; pass a different directory "
                          f"to build a variant without clobbering it.")
args = parser.parse_args()

os.makedirs(args.out_dir, exist_ok=True)


def out_path(name):
    return os.path.join(args.out_dir, name)


def load_suggestions():
    """Accepted years and details, keyed by OSM id. Written only by
    apply_queue.py, from a row somebody approved in the review queue.

    One entry holds everything a person can correct about a building:
    {"year": int, "approx": bool, "name": str, "addr_street": str,
    "addr_number": str}, or {"year_min": int, "year_max": int, ...} when the
    year was given as a span instead. Every field is optional — an entry may
    carry only a year, only an address, or both — and a field that isn't there
    falls back to the OSM tag. A bare int is still accepted as a year, from the
    older suggested_years.json format."""
    if not os.path.exists(SUGGESTIONS_FILE):
        return {}
    with open(SUGGESTIONS_FILE, encoding='utf-8') as f:
        return json.load(f)


# The keys that spell out a year. Must match YEAR_KEYS in apply_queue.py — a
# provenance record lists the fields its submission wrote, and this is how we
# ask whether the year is one of them.
YEAR_FIELDS = {'year', 'year_min', 'year_max'}


def load_community_years():
    """OSM ids whose YEAR came from an accepted public submission.

    suggestions.json cannot answer this. It is one flat file of manual edits and
    says nothing about who made them — the ~700 entries in it today are the
    maintainer's own research, and a visitor's approved suggestion lands in the
    same shape beside them. provenance.json is the record that tells them apart:
    apply_queue.py writes one entry there per submission it merges, and removes
    it again on --revert, so it stays exactly the set of accepted contributions.

    Only ids come back. provenance.json also holds submitter_hash and
    source_kind, and nothing this script writes — geojson, tiles, stats, the CSV
    — may carry either: buildings.geojson is a Derived Database under ODbL and
    share-alike would publish a submitter fingerprint downstream forever
    (docs/submission-schema.md §4).

    Address-only contributions are deliberately not counted. The stats panel is
    a breakdown of buildings by how their YEAR is known, and its rows have to
    sum to the total; a submission that added a street name changed no year and
    belongs in no row of it.
    """
    if not os.path.exists(PROVENANCE_FILE):
        return set()                      # nothing applied yet — a real state, not an error
    with open(PROVENANCE_FILE, encoding='utf-8') as f:
        provenance = json.load(f)
    # An orphan is this project's OWN year, re-homed onto the footprints an OSM
    # split left behind (docs/submission-schema.md §6). It travels through the
    # same queue and lands in the same file as a public suggestion, so without
    # this it would be counted as one — and "Community Contributions" is the one
    # number on the map that is supposed to mean people.
    return {
        osm_id for osm_id, records in provenance.items()
        if any(YEAR_FIELDS.intersection(rec.get('fields') or ())
               and rec.get('kind') != 'orphan'
               for rec in records)
    }


def suggestion_for(suggestions, osm_id):
    """Return (year, approx, year_min, year_max) for a suggestion entry.

    A suggestion carries at most one year shape: a point year — with approx
    saying which of the two point shapes it is, though nothing writes a new
    approx any more — or a span, of which either bound may be absent ("after
    1958"). All four are None when there is no entry, or when the entry only
    corrects name/address."""
    entry = suggestions.get(str(osm_id))
    if entry is None:
        return None, None, None, None
    if not isinstance(entry, dict):
        return entry, False, None, None      # legacy suggested_years.json bare int
    return (entry.get('year'), bool(entry.get('approx')),
            entry.get('year_min'), entry.get('year_max'))


# ── Year extraction ───────────────────────────────────────────────────────────

YEAR_TAGS = ('start_date', 'year_of_construction', 'construction_date', 'opening_date')


def parse_year(tags):
    """Return (year: int, source: str) from any known year tag, else (None, None).
    Armenia has structures far older than the Soviet era, so this accepts any
    1-4 digit AD year (BCE dates, e.g. OSM's "-0782" format, aren't handled).

    A full date like "10.09.2018" has a day/month component that also looks
    like a short number, so a 4-digit year is always preferred when one is
    present; a 1-3 digit fallback only kicks in when there's no 4-digit
    candidate at all (genuinely old buildings, e.g. "301")."""
    for key in YEAR_TAGS:
        val = tags.get(key)
        if not val:
            continue
        val = val.strip()
        m = re.search(r'\b(\d{4})\b', val) or re.search(r'\b(\d{1,3})\b', val)
        if m:
            y = int(m.group(1))
            if 1 <= y <= 2030:
                return y, key
    return None, None


# ── Era classification (Khrushchevka / Brezhnevka) ──────────────────────────
#
# Era estimates come from a separate, standalone classifier that fits two
# models on hand-labeled buildings and publishes an era only where both agree
# at >= 0.90 and a khrushchevka has exactly 5 floors. It lives in exp/research/,
# which is local to a maintainer's machine and not in this repository — what
# ships is its output, inferred_buildings.json, which is tracked and which this
# script only reads. It never runs classification logic itself, so a bad model
# tweak there cannot silently corrupt anything here without a review step in
# between, and a clone with no classifier still builds the same map.
#
# It replaced a hand-written rule that wrote era_classifications.json. Neither
# is part of the build any more; all that survives is the entry shape they
# agreed on, which is what era_span's fallback is about.

INFERRED_BUILDINGS_FILE = paths.INFERRED

def era_span(era):
    """Return (year_min, year_max) for one inferred_buildings entry.

    The classifier writes the programme's real span as year_min/year_max.
    The +/- 5 fallback is for an older file that only carries the midpoint —
    an archived classification still loads rather than silently losing its
    years."""
    if era.get('year_min') is not None and era.get('year_max') is not None:
        return era['year_min'], era['year_max']
    mid = era['year_approx']
    return mid - 5, mid + 5


def load_era_classifications():
    """Model-backed Khrushchevka/Brezhnevka calls from the era classifier,
    keyed by OSM id: {"era": "khrushchevka"|"brezhnevka",
    "year_min": int, "year_max": int, ...} — see era_span for the fallback
    when only the older "year_approx" midpoint is present."""
    if not os.path.exists(INFERRED_BUILDINGS_FILE):
        return {}
    with open(INFERRED_BUILDINGS_FILE, encoding='utf-8') as f:
        return json.load(f)


# ── Geometry helpers ────────────────────────────────────────────────────────
#
# building/leisure=stadium footprints come back from osmium as Areas, which
# may be assembled from a single closed way OR a multipolygon relation (used
# for buildings with a courtyard hole, or several disjoint parts — e.g. the
# government complex, big museum/stadium complexes). Areas expose outer/inner
# rings rather than a flat node list, so we build proper Polygon/MultiPolygon
# GeoJSON (with holes) instead of assuming a single simple ring.

def in_yerevan(lats, lons):
    return not (min(lats) > YEREVAN['max_lat'] or max(lats) < YEREVAN['min_lat'] or
                min(lons) > YEREVAN['max_lon'] or max(lons) < YEREVAN['min_lon'])


def centroid(geometry):
    pts = geometry['coordinates'][0] if geometry['type'] == 'Polygon' else geometry['coordinates'][0][0]
    lons = [c[0] for c in pts]
    lats = [c[1] for c in pts]
    return round(sum(lats) / len(lats), 6), round(sum(lons) / len(lons), 6)


# ── Clipping to the city ────────────────────────────────────────────────────
#
# Yerevan is not a rectangle. Its boundary is 1,188 points across two disjoint
# parts — the city, plus a narrow strip running west towards the airport — and
# any box drawn around it takes in ~30k buildings belonging to Ararat, Armavir
# and Kotayk. So the crop is the boundary polygon itself, tested against each
# building's centroid.
#
# The obvious ray cast walks all 1,083 edges of the main ring for every one of
# ~106k buildings: 115M iterations of pure Python, well over a minute. But a ray
# only ever crosses edges spanning the point's own latitude, so edges are indexed
# into latitude buckets once and each point then tests a couple of dozen instead
# of a thousand. That keeps this dependency-free — no numpy, no shapely, nothing
# the build machine might not have.

LAT_BUCKETS = 256


class Ring:
    """One closed ring, with a latitude index for fast point-in-ring tests."""

    def __init__(self, coords):
        if coords[0] != coords[-1]:
            coords = coords + [coords[0]]
        self.x = [c[0] for c in coords]
        self.y = [c[1] for c in coords]
        self.min_lon, self.max_lon = min(self.x), max(self.x)
        self.min_lat, self.max_lat = min(self.y), max(self.y)
        self.scale = LAT_BUCKETS / ((self.max_lat - self.min_lat) or 1e-9)
        self.buckets = [[] for _ in range(LAT_BUCKETS)]
        for i in range(len(coords) - 1):
            lo, hi = sorted((self.y[i], self.y[i + 1]))
            for b in range(self._bucket(lo), self._bucket(hi) + 1):
                self.buckets[b].append(i)

    def _bucket(self, lat):
        b = int((lat - self.min_lat) * self.scale)
        return 0 if b < 0 else min(b, LAT_BUCKETS - 1)

    def contains(self, lon, lat):
        if not (self.min_lat <= lat <= self.max_lat
                and self.min_lon <= lon <= self.max_lon):
            return False
        x, y, inside = self.x, self.y, False
        for i in self.buckets[self._bucket(lat)]:
            y1, y2 = y[i], y[i + 1]
            if (y1 > lat) != (y2 > lat):
                if lon < (x[i + 1] - x[i]) * (lat - y1) / (y2 - y1) + x[i]:
                    inside = not inside
        return inside


def boundary_rings(area):
    """[[outer, *holes], ...] as Rings, from the boundary relation's Area."""
    parts = []
    for outer in area.outer_rings():
        rings = [Ring([[n.lon, n.lat] for n in outer])]
        rings += [Ring([[n.lon, n.lat] for n in inner])
                  for inner in area.inner_rings(outer)]
        parts.append(rings)
    return parts


def inside_boundary(parts, lon, lat):
    return any(p[0].contains(lon, lat)
               and not any(h.contains(lon, lat) for h in p[1:])
               for p in parts)


def is_yerevan_boundary(obj, tags):
    if obj.from_way():                       # the boundary is a relation
        return False
    if obj.orig_id() == YEREVAN_RELATION:
        return True
    return (tags.get('boundary') == 'administrative'
            and tags.get('admin_level') == '4'
            and tags.get('name') in ('Երևան', 'Yerevan'))


def ring_coords(ring):
    coords = [[n.lon, n.lat] for n in ring]
    if len(coords) < 3:
        return None
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def area_geometry(area):
    """Build a GeoJSON Polygon/MultiPolygon (with holes) from an osmium Area, or None."""
    def polygon_for(outer):
        oc = ring_coords(outer)
        if oc is None:
            return None
        rings = [oc]
        for inner in area.inner_rings(outer):
            ic = ring_coords(inner)
            if ic:
                rings.append(ic)
        return rings

    outers = list(area.outer_rings())
    if not outers:
        return None
    if len(outers) == 1:
        rings = polygon_for(outers[0])
        return {"type": "Polygon", "coordinates": rings} if rings else None

    polys = [p for p in (polygon_for(o) for o in outers) if p]
    return {"type": "MultiPolygon", "coordinates": polys} if polys else None


def geometry_bbox_points(geometry):
    """Flatten every [lon, lat] point out of a Polygon/MultiPolygon, for a bbox check."""
    rings = geometry['coordinates'] if geometry['type'] == 'Polygon' \
        else [r for poly in geometry['coordinates'] for r in poly]
    return [pt for ring in rings for pt in ring]


# A building's year comes in exactly one of these shapes, and which one it is
# is what the map has to show — never a single number standing in for all of
# them:
#
#   exact   year_built            an OSM tag, or someone who typed a year.
#                                 "1965".
#   range   year_min / year_max   a span where no single year is known. Either
#                                 an era call from the classifier — the building
#                                 is in a construction programme, so the span
#                                 that programme ran for is the whole of what is
#                                 known — or a suggestion, where ONE of the two
#                                 bounds may be absent: "after 1958" and "before
#                                 1972" are the shapes the form writes now, and
#                                 the missing bound is the claim, not a gap.
#                                 "1957–1968", "after 1958".
#   approx  year_est              LEGACY, still rendered, no longer written:
#                                 someone who ticked an "approx" box the form no
#                                 longer has, or an era known only by midpoint.
#                                 "~1965".
#
# The shapes are mutually exclusive: whichever fields a feature carries, the
# other shapes' fields are absent. Nothing downstream has to guess which kind of
# number it is holding, and nothing has to invent a midpoint to store.

def classify_year(tags, suggestions, era_classifications, osm_id, use_inference):
    """Return (year, year_est, year_min, year_max, confidence, year_tag)."""
    year, year_tag = parse_year(tags)
    sug_year, sug_approx, sug_min, sug_max = suggestion_for(suggestions, osm_id)

    if sug_min is not None or sug_max is not None:
        # someone who typed a bound rather than a year: "after 1958", or an
        # older submission's closed span. Identical in shape to an era call and
        # rendered the same way, but it outranks one — a person looked at this
        # building, the classifier didn't. An absent bound stays absent: it is
        # what makes the span open at that end.
        return None, None, sug_min, sug_max, 'suggested', 'suggested'
    if sug_year is not None:
        if sug_approx:
            # deliberately NOT widened into a +/- 5 range. A person picking
            # "approx" is saying "about 1965", not "somewhere in 1960-1970" —
            # and the form has a range shape for saying the latter, so widening
            # this one would put words in their mouth.
            return None, sug_year, None, None, 'suggested', 'suggested'
        return sug_year, None, None, None, 'suggested', 'suggested'
    if year is not None:
        return year, None, None, None, 'known', year_tag
    if use_inference:
        era = era_classifications.get(str(osm_id))
        if era:
            year_min, year_max = era_span(era)
            return (None, None, year_min, year_max,
                    'medium', f"era:{era['era']}")
    return None, None, None, None, None, None


YEREVAN_METRO_OPERATOR = 'Կարեն Դեմիրճյանի անվան Երևանի մետրոպոլիտեն'


def is_relevant_area(tags):
    """Buildings plus a handful of non-building=* categories worth showing:
    stadiums, landmark attractions (the Cascade), towers (the TV tower), and
    Yerevan Metro platforms. railway=platform is also used all over Armenia's
    intercity rail network, so it's scoped to the metro's operator/subway=yes
    to avoid pulling in every train station platform in the country."""
    if 'building' in tags:
        return True
    if tags.get('leisure') == 'stadium':
        return True
    if tags.get('tourism') == 'attraction':
        return True
    if tags.get('man_made') == 'tower':
        return True
    return False


# ── Download ──────────────────────────────────────────────────────────────────
#
# Only on the --source pbf path. Note the `exists` check: the extract is fetched
# once and then NEVER refreshed, so a cached copy sits at whatever day it was
# downloaded until somebody deletes it. That silent staleness — five days of it,
# when this was written — is a large part of why the default is now live OSM.
# Refresh it with `pyosmium-up-to-date armenia.osm.pbf`, which is incremental and
# stamps the new replication timestamp into the header.

if args.source != 'pbf':
    pass
elif os.path.exists(PBF_FILE):
    print(f"Using cached {rel(PBF_FILE)}")
else:
    print("Downloading Armenia PBF from Geofabrik (~50 MB)…")
    with requests.get(PBF_URL, stream=True, timeout=300, allow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get('Content-Length', 0))
        done = 0
        with open(PBF_FILE, 'wb') as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {100 * done // total}%  {done // 1024 // 1024} MB", end='', flush=True)
    print(f"\nSaved {rel(PBF_FILE)}")

# ── Parse ─────────────────────────────────────────────────────────────────────

suggestions = load_suggestions()
community_years = load_community_years()
era_classifications = load_era_classifications()
print(f"Era classification: {'off' if args.no_infer else 'on'}")
if suggestions:
    with_year = sum(1 for e in suggestions.values()
                    if not isinstance(e, dict) or e.get('year') is not None)
    with_info = sum(1 for e in suggestions.values()
                    if isinstance(e, dict) and any(k in e for k in ('name', 'addr_street', 'addr_number')))
    print(f"Loaded {len(suggestions):,} manual edits from {rel(SUGGESTIONS_FILE)}"
          f"  ({with_year:,} with a year, {with_info:,} with name/address)")
if community_years:
    print(f"  of which {len(community_years):,} year(s) came from accepted public "
          f"submissions ({rel(PROVENANCE_FILE)})")
if era_classifications:
    print(f"Loaded {len(era_classifications):,} era classifications from {rel(INFERRED_BUILDINGS_FILE)}")

features = []
yerevan_parts = None
osm_base = None


def pbf_areas():
    """Areas out of the Geofabrik extract, plus the city boundary on the way past.

    The boundary rides along in the pass that is happening anyway — no extra
    sweep of the PBF, no cached boundary file to go stale. It can arrive at any
    point in the stream, before or after the buildings it decides the fate of,
    which is why the clip runs once the whole list is in hand.
    """
    global yerevan_parts
    for obj in osmium.FileProcessor(PBF_FILE).with_areas():
        if not obj.is_area():
            continue
        if yerevan_parts is None and is_yerevan_boundary(obj, obj.tags):
            yerevan_parts = boundary_rings(obj)
            continue
        geometry = area_geometry(obj)
        if geometry is None:
            continue
        pts = geometry_bbox_points(geometry)
        if not in_yerevan([p[1] for p in pts], [p[0] for p in pts]):
            continue
        yield obj, geometry


def overpass_areas():
    """Areas out of live OSM.

    No boundary handling and no bbox prefilter, because `map_to_area` did the
    clip server-side — which is why `yerevan_parts` stays None on this path and
    the clip below is skipped. The city outline is the query, not a 1,188-point
    ring index walked once per building.
    """
    global osm_base
    data = osm_source.fetch(refresh=not args.no_refresh)
    osm_base = osm_source.base_timestamp(data)
    print(f"Live OSM via Overpass — current to {osm_base}")
    for area in osm_source.iter_areas(data):
        yield area, area.geometry


if args.source == 'overpass':
    print("Fetching Yerevan buildings, stadiums, and landmarks from live OSM…")
    stream = overpass_areas()
else:
    print("Parsing Yerevan buildings, stadiums, and landmarks from PBF…")
    stream = pbf_areas()

for obj, geometry in stream:
    tags = obj.tags

    if not is_relevant_area(tags):
        continue

    osm_id = obj.orig_id()
    year, year_est, year_min, year_max, confidence, year_tag = classify_year(
        tags, suggestions, era_classifications, osm_id, not args.no_infer)

    # manual name/address edits only override the fields they actually set —
    # a field left out of the entry still falls back to the OSM tag. Legacy bare-int
    # entries carry a year and nothing else, hence the isinstance guard.
    info = suggestions.get(str(osm_id)) or {}
    if not isinstance(info, dict):
        info = {}

    # address priority: manual edit > OSM tag
    addr_street = info.get('addr_street') or tags.get('addr:street')
    addr_number = info.get('addr_number') or tags.get('addr:housenumber')

    features.append({
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "id": osm_id,
            "osm_type": 'way' if obj.from_way() else 'relation',
            # exactly one of these shapes is populated — see classify_year
            "year_built": year,      # exact: OSM tag, or a suggested year
            "year_est": year_est,    # approx: a legacy "about 19xx"
            "year_min": year_min,    # range: an era programme's span, or a
            "year_max": year_max,    #        suggested bound — either may be
                                     #        absent, which is what makes the
                                     #        span open at that end
            "confidence": confidence,  # 'known' | 'suggested' | 'medium' | 'low' | null
            "year_tag": year_tag,
            # True only when this building's year came from an accepted public
            # submission, so the front end can count the Community row while
            # holding every feature in memory, the same way it counts the rest.
            # Not dropped from the web build: it is set on a few hundred
            # features at most and null keys are stripped below, so it costs
            # nothing on the ~103k buildings that don't have it. It says a year
            # was contributed, never by whom — see load_community_years.
            "community": True if str(osm_id) in community_years else None,
            "building": tags.get('building') or tags.get('leisure') or tags.get('tourism')
                        or tags.get('man_made') or tags.get('railway'),
            "name": info.get('name', tags.get('name') or tags.get('name:en') or tags.get('name:hy')),
            "levels": tags.get('building:levels'),
            "material": tags.get('building:material'),
            "addr_street": addr_street,
            "addr_number": addr_number,
        }
    })

# ── Clip to Yerevan ───────────────────────────────────────────────────────────
#
# Everything below this point — the counters, stats.json's bounds, the tiles, the
# needs_data report — sees only what's left, so this has to happen before any of
# it. A building is in or out by its centroid: one straddling the line belongs to
# whichever side its middle is on, which is the only answer that doesn't depend
# on how the footprint happens to be drawn.

# Captured before the clip so an orphaned suggestion can be told apart from one
# that merely fell outside the city — see the integrity check below.
parsed_ids = {str(f['properties']['id']) for f in features}

if args.source == 'overpass':
    # Already clipped, by `map_to_area` in the query itself. Running the ring
    # test again would cost a minute to confirm what the server guaranteed —
    # and would DISAGREE at the edges, because Overpass clips by intersection
    # with the boundary area while this clips by centroid. Two answers to one
    # question is worse than either.
    #
    # The cost is that `parsed_ids` and the kept set are now identical, so the
    # orphan report below cannot separate "outside the city" from "gone from
    # OSM" and calls everything not_in_osm. The distinction only ever mattered
    # for suggestions sitting just over the line; a --source pbf run still
    # reports it exactly.
    print(f"\nInside the Yerevan boundary (clipped by Overpass): {len(features):,}")
else:
    if yerevan_parts is None:
        # Falling through would silently republish Ararat, Armavir and Kotayk as
        # Yerevan, which is the exact bug the boundary crop exists to fix. Better
        # to stop than to ship a map that quietly claims another province.
        sys.exit(f"Yerevan boundary (relation {YEREVAN_RELATION}) not found in {rel(PBF_FILE)}.\n"
                 "Nothing else can be trusted to be inside the city, so this is fatal.\n"
                 "If the relation was renumbered upstream, update YEREVAN_RELATION.")

    def in_city(feature):
        lat, lon = centroid(feature['geometry'])   # centroid returns lat, lon
        return inside_boundary(yerevan_parts, lon, lat)

    before = len(features)
    features = [f for f in features if in_city(f)]
    print(f"\nClipped to the Yerevan boundary: {before:,} → {len(features):,} "
          f"({before - len(features):,} dropped as outside the city)")

# ── Suggestion integrity ─────────────────────────────────────────────────────
#
# suggestions.json is keyed by OSM id and every lookup above is a plain .get(),
# so a key matching no building is indistinguishable from a building with no
# suggestion. Hand-researched years can therefore detach and never be missed:
# the run prints "Loaded 725 manual edits" whether 725 matched or 300 did.
#
# It has already happened. One entry orphaned when the coarse bbox crop became
# the boundary clip above, taking a confirmed year out of the map with nothing
# in any output saying so.
#
# The two causes need telling apart, because the remedies are opposites:
#
#   outside_boundary  parsed fine, then dropped by the clip — the building is
#                     real and the entry is simply out of scope now. Harmless,
#                     unless the scope moves again and you wanted it back.
#   not_in_osm        never reached the parse at all: deleted upstream, redrawn
#                     under a new id, or split into several. The year in
#                     suggestions.json is now the ONLY copy that exists.
ORPHANS_FILE = paths.ORPHANS_NAME

kept_ids = {str(f['properties']['id']) for f in features}
orphans = {
    osm_id: {'reason': 'outside_boundary' if osm_id in parsed_ids else 'not_in_osm',
             'entry': entry}
    for osm_id, entry in suggestions.items()
    if osm_id not in kept_ids
}

with open(out_path(ORPHANS_FILE), 'w', encoding='utf-8') as f:
    json.dump(orphans, f, ensure_ascii=False, indent=2, sort_keys=True)

if orphans:
    # a bare int is a legacy suggested_years.json entry, which is a year and
    # nothing else — hence the isinstance guard rather than a plain .get()
    def carries_year(entry):
        if not isinstance(entry, dict):
            return True
        return any(entry.get(k) is not None for k in ('year', 'year_min', 'year_max'))

    lost = sum(1 for o in orphans.values() if carries_year(o['entry']))
    outside = sum(1 for o in orphans.values() if o['reason'] == 'outside_boundary')
    print(f"\n⚠ {len(orphans):,} manual edit(s) in {rel(SUGGESTIONS_FILE)} match no building"
          f" — {lost:,} of them carry a year")
    print(f"    {outside:,} outside the city boundary, "
          f"{len(orphans) - outside:,} gone from OSM")
    print(f"    → {rel(out_path(ORPHANS_FILE))}")
else:
    print(f"\nAll {len(suggestions):,} manual edits matched a building.")

# Way ids and relation ids are separate namespaces upstream, so nothing prevents
# a way 123 and a relation 123 both existing. suggestions.json keys on the bare
# number, so the two would share one entry, and promoteId/setFeatureState would
# address an id that matches two features (hovering one highlights both). There
# are none today; this exists so the day one appears is loud rather than subtle.
if len(kept_ids) != len(features):
    seen, collisions = set(), set()
    for f in features:
        osm_id = str(f['properties']['id'])
        if osm_id in seen:
            collisions.add(osm_id)
        seen.add(osm_id)
    print(f"\n⚠ {len(collisions):,} OSM id(s) belong to more than one building: "
          f"{', '.join(sorted(collisions)[:5])}"
          f"{' …' if len(collisions) > 5 else ''}")
    print("    suggestions.json cannot address these separately — key the entry "
          "'way/<id>' or 'relation/<id>' to fix.")

# ── Stats ─────────────────────────────────────────────────────────────────────

total = len(features)
known = sum(1 for f in features if f['properties']['confidence'] == 'known')
suggested = sum(1 for f in features if f['properties']['confidence'] == 'suggested')
inferred = sum(1 for f in features if f['properties']['confidence'] in ('medium', 'low'))
unknown = total - known - suggested - inferred

# A strict subset of `suggested`: a public submission can only ever write a year
# into a building that had none, so its year always ends up in that bucket and
# never in `known`. The front end subtracts it back out of the Confirmed row,
# which is why it has to be counted the same way here rather than straight off
# provenance.json — an accepted contribution whose building was later deleted
# from OSM is in the file but not on the map, and must not inflate a row that
# has to add up.
community = sum(1 for f in features
                if f['properties']['confidence'] == 'suggested'
                and f['properties']['community'])

print(f"\nBuildings: {total:,}")
print(f"  Known year (OSM tag) : {known:,}  ({100 * known // total}%)")
print(f"  Suggested (manual)   : {suggested:,}  ({100 * suggested // total}%)")
print(f"    ├ maintainer       : {suggested - community:,}")
print(f"    └ public, accepted : {community:,}")
print(f"  Inferred era         : {inferred:,}  ({100 * inferred // total}%)")
print(f"  No data              : {unknown:,}  ({100 * unknown // total}%)")

# The slider has to span every year any building could be, so a ranged building
# contributes both of its bounds, not a midpoint that would leave the ends of
# its era unreachable.
all_years = [y for f in features for y in (
    f['properties']['year_built'], f['properties']['year_est'],
    f['properties']['year_min'], f['properties']['year_max']) if y]
if all_years:
    print(f"\nYear/era range: {min(all_years)} – {max(all_years)}")

# ── Write ─────────────────────────────────────────────────────────────────────
#
# buildings.geojson is fetched by the browser on every page load, so it's
# trimmed to only what the map actually renders: confidence is
# dropped since it's fully derivable client-side from year_built/year_est/
# year_min/year_tag; levels/material are popup-only "why inferred" detail that
# isn't worth their weight across ~100k mostly-no-data features.
# needs_data.csv below still gets the full fields.
#
# year_min/year_max used to be dropped here too, back when they were a
# synthetic +/- 5 around a midpoint the front end already had — carrying them
# bought nothing. Now they ARE the era shape (there is no midpoint to fall back
# on), so they ship. Measured cost of adding them: +32KB gzipped on a 17MB
# tileset, +0 bytes on the median tile, because only ~2.5k of 106k features
# carry a range and MVT stores their handful of distinct values once per layer.
# The number to watch is coverage, not the field count: giving every building a
# range costs ~3MB gzipped, and at that point encode the era as one small code
# and expand it client-side instead.
#
# null-valued keys are dropped too — MapLibre's ['get', ...] expression and
# every front-end check already treat a missing key the same as an explicit
# null, and ~95% of buildings have no year data at all, so most features are
# mostly nulls.

WEB_DROP_KEYS = {'confidence', 'levels', 'material'}

web_features = [
    {
        **f,
        "properties": {
            k: v for k, v in f['properties'].items()
            if k not in WEB_DROP_KEYS and v is not None
        }
    }
    for f in features
]
geojson = {"type": "FeatureCollection", "features": web_features}
geojson_text = json.dumps(geojson, ensure_ascii=False, separators=(',', ':'))
with open(out_path('buildings.geojson'), 'w', encoding='utf-8') as f:
    f.write(geojson_text)

# The build id the front end stamps onto every tile URL (?v=…), so a browser
# holding yesterday's tiles fetches today's the moment the data changes. Without
# it an approved suggestion stays invisible to the contributor for as long as
# their cached tile lives — which is the whole bug this exists to fix; see the
# tile source in map.js and the /tiles/* header in build_public.sh.
#
# Derived from the CONTENT, not the clock, and that is the point: a rebuild that
# changes nothing keeps the same id, so nobody re-downloads 29MB of identical
# tiles. It hashes buildings.geojson because that file is the tiles' only input —
# same GeoJSON, same tiles. (The one thing it cannot see is a change to
# tippecanoe's flags; if those ever change, bump this by hashing them in too.)
BUILD_ID = hashlib.sha1(geojson_text.encode('utf-8')).hexdigest()[:10]

print(f"\nDone → {rel(out_path('buildings.geojson'))} ({os.path.getsize(out_path('buildings.geojson')) / 1024 / 1024:.1f} MB)")

# ── Stats sidecar ─────────────────────────────────────────────────────────────
#
# The tiled build (buildings.pmtiles, see BUILD.md) only ever has the features
# currently on screen in memory, so the front end can't count categories or find
# the year range by walking the data the way the GeoJSON build does. Both numbers
# are known here, at build time, so they're written out as a ~200-byte sidecar the
# page fetches alongside the tiles.

STATS_FILE = paths.STATS_NAME
# Bounds of the actual data. The front end hands these to MapLibre so it never
# requests tiles outside the built area: tippecanoe only generates tiles where
# features exist, and a missing tile on Cloudflare Pages comes back as 200 +
# index.html rather than a 404, which MapLibre then fails to parse.
all_pts = [pt for f in features for pt in geometry_bbox_points(f['geometry'])]
bounds = [
    min(p[0] for p in all_pts), min(p[1] for p in all_pts),
    max(p[0] for p in all_pts), max(p[1] for p in all_pts),
] if all_pts else None

# ── The year index ──────────────────────────────────────────────────────────
#
# The counters used to be a snapshot of the whole city, because that is all the
# client could know: on the vector-tile path only the tiles on screen exist, so
# nothing can be counted there. That made the numbers static while the year
# slider moved, which reads as a bug.
#
# Counting what IS on screen would be worse — it would change as you pan, and
# "how many khrushchevkas are in Yerevan" is not a question about your viewport.
#
# So the answer is computed here instead, where the whole dataset is in hand,
# and shipped as an index the client can sum for any range. Only 3.7% of
# buildings carry a year at all, and they collapse to ~250 distinct
# (lo, hi, bucket) triples — most of an era programme shares one span — so this
# costs about 9KB and makes the counters exact for the whole city at any
# handle position, not merely plausible.
#
# Buckets mirror deriveConfidence() in map.js exactly, and the split of
# `suggested` is what keeps Community from being double-counted:
#
#   0  known       an OSM date tag
#   1  suggested, not from an accepted public submission
#   2  suggested, from one            ← the Community row
#   3  inferred    an era estimate
#
# so Confirmed = 0 + 1, Community = 2, Inferred = 3 — the same arithmetic
# updateStats() already did, now answerable per range.
year_buckets = {}
for f in features:
    p = f['properties']
    lo, hi = p.get('year_min'), p.get('year_max')
    if lo is None and hi is None:
        y = p.get('year_built') if p.get('year_built') is not None else p.get('year_est')
        if y is None:
            continue
        lo = hi = y
    else:
        lo = lo if lo is not None else hi
        hi = hi if hi is not None else lo

    if p.get('year_tag') == 'suggested':
        bucket = 2 if p.get('community') else 1
    elif p.get('year_built') is not None:
        bucket = 0
    else:
        bucket = 3
    year_buckets[(lo, hi, bucket)] = year_buckets.get((lo, hi, bucket), 0) + 1

year_index = sorted([lo, hi, b, n] for (lo, hi, b), n in year_buckets.items())

stats = {
    'total': total,
    'bounds': bounds,
    # cache-busting stamp for the tile URLs — see BUILD_ID above
    'build': BUILD_ID,
    'known': known,
    'suggested': suggested,
    # a subset of 'suggested', not a fourth bucket — see the count above
    'community': community,
    'inferred': inferred,
    'unknown': unknown,
    'min_year': min(all_years) if all_years else None,
    'max_year': max(all_years) if all_years else None,
    # [lo, hi, bucket, count] per distinct triple — see above
    'year_index': year_index,
}
with open(out_path(STATS_FILE), 'w', encoding='utf-8') as f:
    json.dump(stats, f, indent=2)

print(f"Stats   → {rel(out_path(STATS_FILE))}  (year range {stats['min_year']}–{stats['max_year']}, build {BUILD_ID})")
print(f"          year index: {len(year_index)} spans covering "
      f"{sum(r[3] for r in year_index):,} dated buildings")
if bounds:
    print(f"          bounds {bounds[0]:.4f},{bounds[1]:.4f} → {bounds[2]:.4f},{bounds[3]:.4f}")


# ── Incomplete data report ────────────────────────────────────────────────────

REPORT_FILE = paths.REPORT_NAME
FIELDS = [
    'status', 'osm_id', 'address', 'name',
    'levels', 'material', 'building_type',
    'year_est', 'year_range', 'confidence',
    'lat', 'lon', 'osm_url'
]

rows = []
for f in features:
    p = f['properties']
    if p['confidence'] in ('known', 'suggested'):
        continue

    lat, lon = centroid(f['geometry'])
    addr = ' '.join(filter(None, [p.get('addr_street'), p.get('addr_number')]))
    # an open bound reads as the claim it is, the same way the popup renders it
    lo, hi = p.get('year_min'), p.get('year_max')
    year_range = (f'{lo}–{hi}' if lo and hi
                  else f'after {lo}' if lo
                  else f'before {hi}' if hi
                  else '')

    rows.append({
        'status': 'inferred' if p['confidence'] in ('medium', 'low') else 'unknown',
        'osm_id': p['id'],
        'address': addr,
        'name': p.get('name') or '',
        'levels': p.get('levels') or '',
        'material': p.get('material') or '',
        'building_type': p.get('building') or '',
        'year_est': p.get('year_est') or '',
        'year_range': year_range,
        'confidence': p.get('confidence') or 'none',
        'lat': lat,
        'lon': lon,
        'osm_url': f"https://www.openstreetmap.org/{p.get('osm_type', 'way')}/{p['id']}",
    })

# sort: unknown first, then inferred; within each group, addressed buildings first
rows.sort(key=lambda r: (
    0 if r['status'] == 'unknown' else 1,
    0 if r['address'] else 1
))

with open(out_path(REPORT_FILE), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(rows)

unknown_with_addr = sum(1 for r in rows if r['status'] == 'unknown' and r['address'])
inferred_with_addr = sum(1 for r in rows if r['status'] == 'inferred' and r['address'])
print(f"Report  → {rel(out_path(REPORT_FILE))}  ({len(rows):,} rows)")
print(f"  unknown  : {sum(1 for r in rows if r['status'] == 'unknown'):,}"
      f"  ({unknown_with_addr:,} have address)")
print(f"  inferred : {sum(1 for r in rows if r['status'] == 'inferred'):,}"
      f"  ({inferred_with_addr:,} have address)")
