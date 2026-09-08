#!/usr/bin/env python3
"""A building becoming three — run: python3 test_split_detect.py

This is the case the whole detector exists for and the one case the real
pipeline cannot produce on demand: it needs two builds whose OSM ids differ,
which means an actual edit in OSM and a Geofabrik refresh. So the geometry is
synthetic — squares, tiled by hand — and the assertions are about which
successors inherit and, more importantly, which do NOT.

The negatives are the point. Every false positive here writes a confident year
onto somebody else's building.
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
from detect_splits import find_heirs

failures = []


def square(osm_id, x0, y0, x1, y1, **props):
    return {
        'type': 'Feature',
        'properties': {'id': osm_id, **props},
        'geometry': {'type': 'Polygon', 'coordinates': [[
            [x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]},
    }


def check(label, old, new, suggestions, want_ids):
    got = sorted(h[2] for h in find_heirs(old, new, suggestions))
    ok = got == sorted(want_ids)
    print(f"{'✓' if ok else '✗'} {label}\n    inherit → {got or 'nothing'}")
    if not ok:
        failures.append(f'{label}: got {got}, wanted {sorted(want_ids)}')


YEAR = {'1000': {'year': 1965, 'approx': False}}

# The parent, one square from (0,0) to (0.003, 0.001).
PARENT = square('1000', 0, 0, 0.003, 0.001)

# ── the case it exists for ───────────────────────────────────────────────────
# Split into three: the original id keeps the left third, two new ids take the
# rest. This is what iD and JOSM actually do.
check('split into three — the two new pieces inherit',
      [PARENT],
      [square('1000', 0, 0, 0.001, 0.001),
       square('2001', 0.001, 0, 0.002, 0.001),
       square('2002', 0.002, 0, 0.003, 0.001)],
      YEAR, ['2001', '2002'])

# Redrawn: the parent was deleted and retraced under a new id. One successor,
# and it must still inherit — this is the same loss wearing a different shape.
check('redrawn under a new id — the successor inherits',
      [PARENT],
      [square('3001', 0, 0, 0.003, 0.001)],
      YEAR, ['3001'])

# ── the negatives ────────────────────────────────────────────────────────────
# A big dated building with small buildings standing inside its outline in BOTH
# builds. They are neighbours in a courtyard, not fragments. The first version
# of the detector proposed eleven heirs on exactly this shape.
neighbours = [square('900', 0.0005, 0.0002, 0.0008, 0.0005),
              square('901', 0.0015, 0.0002, 0.0018, 0.0005)]
check('untouched neighbours inside the parent — nothing inherits',
      [PARENT] + neighbours,
      [PARENT] + neighbours,
      YEAR, [])

# Somebody draws a NEW building inside the parent's outline without touching the
# parent. This DOES inherit, and the expectation was deliberately reversed: the
# earlier rule wanted the parent to have shrunk first, and that hid two of the
# four successors in the first live run. Splitting a building and drawing a
# piece beside a barely-touched one are not distinguishable from the outside,
# and the cost of being wrong runs one way — a wrong proposal is one click, a
# missing one is a researched year gone silently.
check('new building inside an untouched parent — inherits, and should',
      [PARENT],
      [PARENT, square('4001', 0.0005, 0.0002, 0.0008, 0.0005)],
      YEAR, ['4001'])

# A successor that EXISTED BEFORE and was reshaped counts too — an edit can hand
# a dated footprint away by moving a building's outline just as completely as by
# drawing a new one.
check('a neighbour that was reshaped — inherits',
      [PARENT, square('4002', 0.0005, 0.0002, 0.0008, 0.0005)],
      [PARENT, square('4002', 0.0005, 0.0002, 0.0009, 0.0006)],
      YEAR, ['4002'])

# A split where the new piece was ALREADY dated in OSM. The additive rule says
# a filled field is closed, so proposing over it would be a correction — and
# apply_queue.py would refuse it anyway. Better never to queue the work.
check('successor already has a year — nothing inherits',
      [PARENT],
      [square('1000', 0, 0, 0.0015, 0.001),
       square('5001', 0.0015, 0, 0.003, 0.001, year_built=1970)],
      YEAR, [])

# The parent vanished with nothing put in its place. That is a deletion, and
# orphans.json already reports it; inventing a successor would be worse than
# saying nothing.
check('parent deleted, nothing replaces it — nothing inherits',
      [PARENT], [], YEAR, [])

# A building with no year of ours has nothing to bequeath.
check('parent carries no suggested year — nothing inherits',
      [PARENT],
      [square('1000', 0, 0, 0.001, 0.001),
       square('6001', 0.001, 0, 0.003, 0.001)],
      {}, [])

print()
if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('splits are found, neighbours are left alone')
