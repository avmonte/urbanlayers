#!/usr/bin/env python3
"""The two queue shapes must normalise to the same record — run: python3 test_queue_shapes.py

load_queue() in apply_queue.py takes either what server.py writes locally
({submission_id: record}) or a `wrangler d1 execute --json` export (flat SQL
columns, JSON strings). Its own docstring says the point is that "the local loop
stays a true rehearsal of the production one instead of a similar-looking thing
that diverges at the step that matters".

It diverged. Phase 3 added `kind`, the D1 branch dropped it, and every report
approved in production came back looking like a suggestion — so the additive
check rejected it for touching a field that already had a value, which is the
one thing a report is for. Locally it worked, because the local shape carries
the key already. This test is that bug, kept.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
from apply_queue import load_queue, check_applicable

failures = []

REPORT = {
    'id': '532973771', 'lng': 44.5, 'lat': 40.18, 'kind': 'report',
    'entry': {'year_max': 1930},
    'before': {'year': {'year_built': 1932}, 'name': None},
    'source_kind': 'document', 'source_note': 'x', 'submitter_hash': 'h',
    'status': 'approved', 'submitted_at': 1,
}
D1_ROW = {
    'submission_id': 'abc123', 'osm_id': 532973771, 'lng': 44.5, 'lat': 40.18,
    'kind': 'report', 'entry': json.dumps(REPORT['entry']),
    'before_json': json.dumps(REPORT['before']), 'source_kind': 'document',
    'source_note': 'x', 'submitter_hash': 'h', 'status': 'approved', 'submitted_at': 1,
}
D1_EXPORT = [{'results': [D1_ROW]}]


def written(obj):
    fd, path = tempfile.mkstemp(suffix='.json')
    with os.fdopen(fd, 'w') as f:
        json.dump(obj, f)
    return path


local_path = written({'abc123': REPORT})
d1_path = written(D1_EXPORT)
try:
    local, local_from_d1 = load_queue(local_path)
    d1, d1_from_d1 = load_queue(d1_path)
finally:
    os.remove(local_path)
    os.remove(d1_path)

for label, got, want in [('local export flag', local_from_d1, False),
                         ('d1 export flag', d1_from_d1, True)]:
    ok = got == want
    print(f"{'✓' if ok else '✗ FAIL'} {label:22} → {got}")
    if not ok:
        failures.append(label)

for key in ('id', 'kind', 'entry', 'before', 'status'):
    a, b = local['abc123'].get(key), d1['abc123'].get(key)
    ok = a == b
    print(f"{'✓' if ok else '✗ FAIL'} same {key:18} local={a!r} d1={b!r}")
    if not ok:
        failures.append(f'{key} differs between queue shapes')

# and the consequence the bug actually had: which branch the merge takes
print()
built = {'532973771': {'year_built': 1932, 'name': None}}
for label, queue in (('local', local), ('d1', d1)):
    reasons = check_applicable(built, '532973771', queue['abc123'])
    ok = not reasons          # the value is still 1932, so the report applies
    print(f"{'✓' if ok else '✗ FAIL'} {label:5} report applies → {'yes' if ok else reasons}")
    if not ok:
        failures.append(f'{label}: report was not applicable')

print()
if failures:
    for f in failures:
        print(f'  {f}')
    sys.exit(1)
print('both queue shapes agree')
