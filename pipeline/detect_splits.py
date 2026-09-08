#!/usr/bin/env python3
"""Find years whose building stopped existing, and re-propose them.

    python3 detect_splits.py                       # dry run — prints, writes nothing
    python3 detect_splits.py --write orphans.sql   # emit the queue INSERTs
    python3 detect_splits.py --local               # queue them in queue.json instead

The problem, in one line: a year in suggestions.json is keyed by an OSM id, so
it survives exactly as long as that id does — and editing the map upstream is
what ends it.

Deleting a building is caught already: fetch_buildings.py writes it to
orphans.json as `not_in_osm`. **Splitting one is not caught by anything.**
Splitting keeps the original id on one piece and mints new ids for the rest, so
the parent never orphans, the new pieces are simply buildings with no year, and
nothing in any output changes. The data does not go wrong; it goes quiet.

So this compares two consecutive builds geometrically rather than by id:

    successors(parent) := new buildings whose centroid falls inside the
                          parent's OLD footprint

    0            deleted or out of scope — orphans.json already says so
    1, same id   untouched
    1, new id    redrawn
    2 or more    SPLIT — the interesting case

Every successor that has no year of its own gets one `orphan` row proposing the
parent's year, and a human decides. Nothing is written to suggestions.json here:
this only fills the review queue, and apply_queue.py is still the only thing
that merges — including re-checking that the field is *still* empty, which is
what stops a re-homed year landing on a piece somebody has since researched.

Why review rather than auto-apply
---------------------------------
Three fragments of one building rarely share one year: a wing added in 1968 to a
1935 block is exactly the kind of thing a split records. Inheritance is a good
guess and a bad fact, so it is proposed and never asserted — and the review card
lets the year be edited per piece before approving (docs §7).

Only the YEAR is inherited. See docs/submission-schema.md §6: a split is
precisely when names and addresses diverge.
"""
import argparse
import hashlib
import json
import os
import sys
import time

import submission

import paths
from paths import rel

SUGGESTIONS_FILE = paths.SUGGESTIONS
PROVENANCE_FILE = paths.PROVENANCE
QUEUE_FILE = paths.QUEUE

# A successor is a FRAGMENT, so it cannot be meaningfully larger than what it
# came out of. The slack absorbs the redraw case, where a building is retraced
# slightly bigger than the sloppy original that prompted the edit.
MAX_SUCCESSOR_RATIO = 1.05

# ~100m at Yerevan's latitude. Only ever an index bucket: correctness comes from
# the point-in-polygon test, this just decides how many of them get run.
CELL = 0.001

# Where an inherited year says it came from. Not a real submitter, and shaped so
# it can never collide with one: submitter_hash is 16 hex chars everywhere else,
# so a run of bad inheritance comes out as a set with
# `apply_queue.py --revert-submitter split-detector`.
DETECTOR_HASH = 'split-detector'


def rings(geometry):
    """Every outer ring of a Polygon or MultiPolygon, as coordinate lists."""
    if geometry['type'] == 'Polygon':
        return [geometry['coordinates'][0]]
    return [poly[0] for poly in geometry['coordinates']]


def centroid(ring):
    """Mean vertex, matching fetch_buildings.centroid — same point, same rounding.

    Deliberately the vertex mean rather than the area centroid: the two differ
    by metres on a building footprint, and using a different definition here
    than the one the rest of the project uses would put a successor on the wrong
    side of its own edge in exactly the ambiguous cases that matter.
    """
    return (round(sum(c[0] for c in ring) / len(ring), 6),
            round(sum(c[1] for c in ring) / len(ring), 6))


def area(ring):
    """Shoelace, in square degrees. Only ever compared against another ring at
    the same latitude, so the missing cos(lat) factor cancels and no projection
    is needed."""
    total = 0.0
    for i in range(len(ring) - 1):
        total += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(total) / 2


def contains(ring, lon, lat):
    """Ray cast. Small rings and a bbox prefilter upstream, so the plain loop is
    fine — fetch_buildings.py's bucketed Ring exists for 1,083-edge boundaries."""
    inside = False
    n = len(ring)
    for i in range(n - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if (y1 > lat) != (y2 > lat):
            if lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def load_features(path):
    if not os.path.exists(path):
        sys.exit(f'{path} does not exist — build it first (see build_public.sh)')
    with open(path, encoding='utf-8') as f:
        return json.load(f)['features']


def has_year(props):
    return any(props.get(k) is not None
               for k in ('year_built', 'year_est', 'year_min', 'year_max'))


def year_entry(entry):
    """The year half of a suggestions.json entry — the only half that travels."""
    return {k: v for k, v in entry.items() if k in submission.YEAR_FIELDS}


def build_index(features):
    """{cell: [(osm_id, lon, lat, props)]} over new-build centroids."""
    index = {}
    for f in features:
        ring = rings(f['geometry'])[0]
        lon, lat = centroid(ring)
        index.setdefault((int(lon / CELL), int(lat / CELL)), []).append(
            (str(f['properties']['id']), lon, lat, f['properties'], area(ring)))
    return index


def successors(index, ring):
    """New buildings whose centroid falls inside this old footprint."""
    lons = [c[0] for c in ring]
    lats = [c[1] for c in ring]
    parent_area = area(ring)
    out = []
    for cx in range(int(min(lons) / CELL), int(max(lons) / CELL) + 1):
        for cy in range(int(min(lats) / CELL), int(max(lats) / CELL) + 1):
            for osm_id, lon, lat, props, child_area in index.get((cx, cy), ()):
                if child_area > parent_area * MAX_SUCCESSOR_RATIO:
                    continue
                if contains(ring, lon, lat):
                    out.append((osm_id, lon, lat, props))
    return out


def changed_ids(old_features, new_features):
    """Ids that are new, or whose footprint moved, between two builds.

    THE gate on what may inherit, and it replaced two narrower ones that each
    got a real case wrong.

    Requiring a successor to be a brand-new id missed the building somebody
    RESHAPED rather than drew — an edit that can hand a dated footprint away
    just as completely. Requiring the parent to have shrunk missed the pieces
    that appear when a parent is barely touched at all; two of the four
    successors in the first live run were invisible for exactly that reason.

    Dropping both and asking only "was this touched?" is at once wider — a
    modified building counts, not just a created one — and much narrower, since
    a building standing inside a dated outline in BOTH builds, unedited, is a
    neighbour and stops being proposed. On the first live diff that was the
    difference between 48 candidates and 4.

    Derived from the two builds rather than taken from a diff file, so this
    stays usable with any pair of builds and needs no Overpass.
    """
    def ring_key(f):
        # rounded so a re-export that perturbs the last decimal is not an edit
        return tuple((round(x, 7), round(y, 7)) for x, y in rings(f['geometry'])[0])

    before = {str(f['properties']['id']): ring_key(f) for f in old_features}
    return {osm_id for osm_id, shape in
            ((str(f['properties']['id']), ring_key(f)) for f in new_features)
            if before.get(osm_id) != shape}


def find_heirs(old_features, new_features, suggestions):
    """The successors that should inherit a year, as (parent_id, child) tuples.

    Split out of main() so it can be tested against synthetic geometry: the case
    this exists for — a building becoming three — is precisely the one that
    cannot be reproduced by running the real pipeline twice.

    Deliberately generous. A successor that turns out to be somebody else's
    building costs a reviewer one click; a successor that is never proposed
    loses a researched year silently and permanently, which is the whole thing
    this exists to prevent. When the two are hard to tell apart — and they often
    are, since splitting a building and correcting an outline that covered two
    buildings are the same edit mechanically — it proposes and lets a person
    decide.
    """
    touched = changed_ids(old_features, new_features)
    new_ids = {str(f['properties']['id']) for f in new_features}
    index = build_index(new_features)

    # Only years THIS project owns are re-homed. A year that came from an OSM
    # tag reappears on whichever pieces carry the tag, and guessing on its behalf
    # would be this script arguing with the map it is reading.
    parents = [f for f in old_features
               if str(f['properties']['id']) in suggestions
               and year_entry(suggestions[str(f['properties']['id'])])]

    found = []
    for parent in parents:
        pid = str(parent['properties']['id'])
        entry = year_entry(suggestions[pid])
        ring = rings(parent['geometry'])[0]
        kids = successors(index, ring)
        if not kids:
            continue                       # deleted or out of scope — orphans.json says so
        # `has_year` is the one exclusion kept, and it is not a judgement: a
        # successor that already carries a year has a CLOSED field, so
        # apply_queue.py would refuse the row anyway. Queueing it would only
        # spend review time on work that cannot land.
        heirs = [k for k in kids
                 if k[0] != pid and k[0] in touched and not has_year(k[3])]
        if not heirs:
            continue                       # untouched, or every piece already dated
        split = pid in new_ids or len(kids) > 1
        for osm_id, lon, lat, _props in heirs:
            found.append((pid, entry, osm_id, lon, lat, split))
    return found


def submission_id(parent, child, entry):
    """Deterministic, so re-running before review collides on the primary key
    instead of queueing the same claim twice."""
    seed = f'{parent}|{child}|{json.dumps(entry, sort_keys=True)}'
    return hashlib.sha256(seed.encode()).hexdigest()[:12]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--old', default='build/buildings.geojson',
                    help='the build the live tiles were cut from (default: %(default)s)')
    ap.add_argument('--new', default='buildings.geojson',
                    help='the build made from the refreshed PBF (default: %(default)s)')
    ap.add_argument('--write', metavar='PATH',
                    help='write the queue INSERTs here, for wrangler d1 execute --file')
    ap.add_argument('--local', action='store_true',
                    help=f'queue into {rel(QUEUE_FILE)} instead, for the offline loop')
    args = ap.parse_args()

    old_features = load_features(args.old)
    new_features = load_features(args.new)
    suggestions = json.load(open(SUGGESTIONS_FILE, encoding='utf-8'))

    # The parent's evidence is the inherited year's evidence, and it lives in
    # provenance.json rather than in the entry: suggestions.json holds values,
    # not where they came from. Absent for the maintainer's own research, which
    # was never a submission — 'local' is the honest answer there.
    provenance = (json.load(open(PROVENANCE_FILE, encoding='utf-8'))
                  if os.path.exists(PROVENANCE_FILE) else {})

    def parent_source(osm_id):
        for rec in reversed(provenance.get(osm_id) or ()):
            if rec.get('source_kind'):
                return rec['source_kind']
        return 'local'

    rows, splits, redraws = [], set(), set()
    for pid, entry, osm_id, lon, lat, is_split in find_heirs(
            old_features, new_features, suggestions):
        (splits if is_split else redraws).add(pid)
        record = {
            'id': osm_id, 'lng': lon, 'lat': lat,
            'kind': 'orphan',
            'before': {'year': None},
            'after': entry,
            'source_kind': parent_source(pid),
            'source_note': f'inherited from building {pid}, split or redrawn in OSM',
            'derived_from': pid,
        }
        # Validated by the authority, with the maintainer-only kind allowed.
        # A detector that can write rows the merge would refuse is a detector
        # that fills the queue with work nobody can finish.
        try:
            normalised = submission.validate_submission(record, kinds=submission.KINDS)
        except submission.SubmissionError as err:
            print(f'  ⚠ skipped {osm_id} (from {pid}): {err}')
            continue
        rows.append((submission_id(pid, osm_id, entry), normalised))

    # Dated buildings whose OWN footprint moved. Nothing to propose — the year is
    # already on them and the field is closed — but a reshaped building is one
    # whose year may no longer describe what is now drawn, and that deserves a
    # look rather than silence. Printed, never queued: an orphan over a filled
    # field is a correction, which is a person's call and a different flow.
    touched = changed_ids(old_features, new_features)
    reshaped = sorted(
        pid for pid in (str(f['properties']['id']) for f in old_features)
        if pid in suggestions and year_entry(suggestions[pid]) and pid in touched)
    if reshaped:
        print(f'{len(reshaped)} dated building(s) were themselves reshaped — '
              f'check the year still fits:')
        for pid in reshaped:
            print(f"  ~ building {pid:>12}  {year_entry(suggestions[pid])}")
        print()

    if not rows:
        print('No orphaned years — every dated building still has its id.')
        return 0

    print(f'{len(rows)} inherited year(s) from {len(splits)} split(s) '
          f'and {len(redraws)} redraw(s):\n')
    for sid, r in rows:
        print(f"  {sid}  building {r['id']:>12}  ← {r['derived_from']:>12}  {r['entry']}")

    if args.local:
        queue = json.load(open(QUEUE_FILE, encoding='utf-8')) if os.path.exists(QUEUE_FILE) else {}
        added = 0
        for sid, r in rows:
            if sid in queue:               # already queued; idempotent by construction
                continue
            queue[sid] = {**r, 'status': 'pending', 'submitted_at': int(time.time()),
                          'submitter_hash': DETECTOR_HASH}
            added += 1
        os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
        with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(queue, f, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"\n✓ {added} queued in {rel(QUEUE_FILE)} — review at /review.html")
        return 0

    if not args.write:
        print('\nDry run — nothing written. Re-run with --write PATH or --local.')
        return 0

    def sql(value):
        if value is None:
            return 'NULL'
        return "'" + str(value).replace("'", "''") + "'"

    now = int(time.time())
    with open(args.write, 'w', encoding='utf-8') as f:
        for sid, r in rows:
            # OR IGNORE, with a deterministic id, is the whole idempotency story:
            # running this twice before review is a no-op rather than a duplicate.
            f.write(
                'INSERT OR IGNORE INTO submissions (submission_id, osm_id, lng, lat, kind, '
                'entry, before_json, source_kind, source_url, source_note, submitter_hash, '
                'derived_from, status, submitted_at) VALUES ('
                f"{sql(sid)}, {sql(r['id'])}, {r['lng']}, {r['lat']}, {sql(r['kind'])}, "
                f"{sql(json.dumps(r['entry'], sort_keys=True))}, "
                f"{sql(json.dumps(r['before'], sort_keys=True))}, "
                f"{sql(r['source_kind'])}, {sql(r['source_url'])}, {sql(r['source_note'])}, "
                f"{sql(DETECTOR_HASH)}, {sql(r['derived_from'])}, 'pending', {now});\n")

    db = os.environ.get('D1_DATABASE', '<your-d1-database>')
    print(f'\n✓ {args.write} written. Queue them with:\n')
    print(f'    npx wrangler d1 execute {db} --remote --file={args.write}\n')
    print('  Then review at /review.html on your deployed site.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
