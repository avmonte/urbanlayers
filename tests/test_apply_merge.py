#!/usr/bin/env python3
"""Claims combine instead of overwriting — run: python3 test_apply_merge.py

A photograph never proves a construction year; it proves a bound. Two photos are
two claims, and together they say more than either alone. This is that rule.

The bug it exists to prevent is subtle and was live: a second claim REPLACED the
first, so a building known to be "after 1936" that gained a "before 1942" ended
up showing only "before 1942". More evidence produced a worse answer.
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
from apply_queue import merge_years, write_entry, year_interval, describe

failures = []


def check(label, current, claim, want):
    """want: the resulting entry, or 'CONFLICT'."""
    merged, conflict = merge_years(current, claim)
    got = 'CONFLICT' if conflict else merged
    ok = got == want
    lo, hi = year_interval(claim)
    print(f"{'✓' if ok else '✗ FAIL'} {label:34} + {describe(lo, hi):14} → "
          f"{'CONFLICT' if conflict else describe(*year_interval(merged)) if merged else '—'}")
    if not ok:
        failures.append(f'{label}: expected {want}, got {got}')


# ── bounds intersect: this is the whole point ───────────────────────────────
check('nothing known',        {},                   {'year_max': 1948}, {'year_max': 1948})
check('after + before',       {'year_min': 1936},   {'year_max': 1942},
      {'year_min': 1936, 'year_max': 1942})
check('before + after',       {'year_max': 1948},   {'year_min': 1944},
      {'year_min': 1944, 'year_max': 1948})
check('the later "after" wins',  {'year_min': 1936}, {'year_min': 1944}, {'year_min': 1944})
check('the earlier "before" wins', {'year_max': 1948}, {'year_max': 1942}, {'year_max': 1942})
check('a span is tightened',  {'year_min': 1944, 'year_max': 1972}, {'year_max': 1948},
      {'year_min': 1944, 'year_max': 1948})
# bounds that meet are an exact year, the same collapse parse_year_shape makes
check('bounds that meet',     {'year_min': 1948},   {'year_max': 1948},
      {'year': 1948, 'approx': False})
check('exact year inside',    {'year_min': 1944, 'year_max': 1948},
      {'year': 1946, 'approx': False}, {'year': 1946, 'approx': False})

# ── irreconcilable: one of the sources is wrong, and a person decides ───────
check('before earlier than after', {'year_min': 1944}, {'year_max': 1942}, 'CONFLICT')
check('exact year outside a span', {'year_min': 1944, 'year_max': 1948},
      {'year': 1953, 'approx': False}, 'CONFLICT')
check('two exact years disagree',  {'year': 1953, 'approx': False},
      {'year': 1948, 'approx': False}, 'CONFLICT')

# a legacy approx year is a guess at a point, not a bound on one: it constrains
# nothing, so real evidence replaces it rather than arguing with it
check('legacy ~year yields',  {'year': 1965, 'approx': True}, {'year_max': 1942},
      {'year_max': 1942})

# ── write_entry: the fold reaches suggestions.json, and text is untouched ───
print()
suggestions = {'42': {'year_min': 1936, 'name': 'Old name'}}
replaced, conflict = write_entry(suggestions, '42', {'year_max': 1942})
ok = suggestions['42'] == {'year_min': 1936, 'year_max': 1942, 'name': 'Old name'} and not conflict
print(f"{'✓' if ok else '✗ FAIL'} write_entry folds and keeps other fields → {suggestions['42']}")
if not ok:
    failures.append('write_entry did not fold correctly')
# and what it replaced is what revert puts back
ok = replaced == {'year_min': 1936}
print(f"{'✓' if ok else '✗ FAIL'} records what it replaced, for revert → {replaced}")
if not ok:
    failures.append('write_entry did not record the replaced value')

suggestions = {'42': {'year_min': 1944}}
replaced, conflict = write_entry(suggestions, '42', {'year_max': 1942})
ok = conflict and suggestions['42'] == {'year_min': 1944}
print(f"{'✓' if ok else '✗ FAIL'} a conflict writes NOTHING → {suggestions['42']}")
if not ok:
    failures.append('write_entry wrote despite a conflict')

# ── overwrite_conflicts: the newer claim wins ────────────────────────────────
#
# The CLI default. A conflict here is not two strangers disagreeing, it is one
# researcher having found something better, so it resolves forward instead of
# waiting to be arbitrated on every build.
suggestions = {'42': {'year_min': 1944, 'name': 'Kept'}}
replaced, conflict = write_entry(suggestions, '42', {'year_max': 1942},
                                 overwrite_conflicts=True)
ok = not conflict and suggestions['42'] == {'year_max': 1942, 'name': 'Kept'}
print(f"{'✓' if ok else '✗ FAIL'} overwrite: the newer claim wins → {suggestions['42']}")
if not ok:
    failures.append('overwrite_conflicts did not take the new claim')

# The whole point of overwriting is that the old bound is DISBELIEVED, so it
# must not survive by being folded into the answer.
ok = 'year_min' not in suggestions['42']
print(f"{'✓' if ok else '✗ FAIL'} overwrite does not fold the rejected bound back in")
if not ok:
    failures.append('overwrite_conflicts intersected instead of replacing')

# and it stays revertible — that is what makes overwriting safe rather than lossy
ok = replaced == {'year_min': 1944}
print(f"{'✓' if ok else '✗ FAIL'} overwrite records what it replaced → {replaced}")
if not ok:
    failures.append('overwrite_conflicts did not record the replaced value')

print()
if failures:
    for f in failures:
        print(f'  {f}')
    sys.exit(1)
print('claims combine')
