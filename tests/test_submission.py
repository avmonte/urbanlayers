#!/usr/bin/env python3
"""Tests for submission.py — run: python3 test_submission.py

No framework on purpose: the repo has no test dependency and this needs none.
Exits non-zero on failure, so CI can gate the merge path on it.

Every case here is a line in docs/submission-schema.md. If you change one, change
the other — the spec is the authority and this is what proves the code matches it.
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
from submission import (validate_submission, SubmissionError, is_open,
                        matches_observed, KINDS)

VALID = dict(id="524357988", lng=44.5, lat=40.18,
             before={"year": None}, after={"year": 1968, "approx": False},
             source_kind="online", source_url="https://www.hinyerevan.com/photos/10907")

failures = []


def check(name, patch, expect):
    """expect: a substring of the normalised entry, or 'REJECT'."""
    try:
        got = "OK " + str(validate_submission({**VALID, **patch})['entry'])
    except SubmissionError as e:
        got = f"REJECT({e.status}): {e}"
    ok = expect in got
    print(f"{'✓' if ok else '✗ FAIL'} {name:34} → {got}")
    if not ok:
        failures.append(f"{name}: expected {expect!r}, got {got!r}")


# ── the year shapes ──────────────────────────────────────────────────────────
check("valid exact",            {}, "OK")
# the two the form offers besides an exact year: one bound, one open end. The
# open end is stored as an ABSENT key, never a null — see docs §2.
check("after 1958",             {"after": {"year_min": 1958}}, "{'year_min': 1958}")
check("before 1972",            {"after": {"year_max": 1972}}, "{'year_max': 1972}")
# closed spans still validate — era inference writes them and older submissions
# carry them — but no form produces one any more
check("closed span",            {"after": {"year_min": 1958, "year_max": 1972}}, "year_min")
# approx renders where it already exists and is refused on the way in: silently
# storing it as exact would invent a precision the submitter did not claim
check("approx rejected",        {"after": {"year": 1965, "approx": True}}, "REJECT")
# a zero-width span reads as vaguer than what was meant, so it collapses
check("zero-width range→exact", {"after": {"year_min": 1965, "year_max": 1965}},
                                "{'year': 1965, 'approx': False}")
check("range backwards",        {"after": {"year_min": 1972, "year_max": 1958}}, "REJECT")
check("year AND bound",         {"after": {"year": 1960, "year_min": 1958}}, "REJECT")
check("year AND range",         {"after": {"year": 1960, "year_min": 1958, "year_max": 1972}}, "REJECT")
check("year out of range",      {"after": {"year": 3000}}, "REJECT")
# bool is an int subclass in Python — True must not slip through as year 1
check("bool as year",           {"after": {"year": True}}, "REJECT")

# ── field handling ───────────────────────────────────────────────────────────
check("empty after",            {"after": {}}, "REJECT")
check("blank name dropped",     {"after": {"year": 1968, "name": "   "}}, "{'year': 1968")
check("name too long",          {"after": {"year": 1968, "name": "x" * 201}}, "REJECT")
check("unknown key dropped",    {"after": {"year": 1968, "evil": "x"}}, "{'year': 1968")

# ── the additive rule ────────────────────────────────────────────────────────
# a non-null `before` means the client offered an input for a field that already
# had a value — a broken or hostile client, not a user error
check("before already filled",  {"before": {"year": 1965}}, "REJECT")

# ── evidence ─────────────────────────────────────────────────────────────────
# The kind says what the evidence IS; the floor says what it must arrive with.
# A plaque reaches us as a link to a photo of it (and, once uploads exist, as a
# photo taken on the spot) — the kind is not a claim about the attachment.
check("bad source_kind",        {"source_kind": "vibes"}, "REJECT")
check("missing source_kind",    {"source_kind": None}, "REJECT")
check("retired kind refused",   {"source_kind": "document"}, "REJECT")
# a plaque asks for nothing: the claim names a physical thing on a specific
# building, which is the most checkable evidence in the system
check("plaque needs nothing",   {"source_kind": "plaque", "source_url": None}, "OK")
check("online needs a link",    {"source_kind": "online", "source_url": None}, "REJECT")
check("local needs a note",     {"source_kind": "local", "source_url": None}, "REJECT")
check("local with a note",      {"source_kind": "local", "source_url": None,
                                 "source_note": "I grew up here"}, "OK")
# a link is not evidence of local knowledge — the note is what carries it
check("local, link but no note", {"source_kind": "local"}, "REJECT")
check("report: plaque alone",   {"kind": "report", "source_kind": "plaque", "source_url": None,
                                 "before": {"year": {"year_built": 1965}},
                                 "after": {"year": 1985}}, "OK")
check("note too long",          {"source_note": "x" * 501}, "REJECT")

# ── the link, checked by shape and never by whether it answers ───────────────
# Wikipedia 403s a bare automated HEAD that a browser gets 200 for, so
# reachability is recorded for the reviewer and never used to refuse anything.
check("http refused",           {"source_url": "http://example.com/x"}, "REJECT")
check("javascript: refused",    {"source_url": "javascript:alert(1)"}, "REJECT")
# an IP literal is never a citation, and is the shape an SSRF probe takes
check("ip literal refused",     {"source_url": "https://169.254.169.254/meta-data"}, "REJECT")
check("localhost refused",      {"source_url": "https://localhost/admin"}, "REJECT")
check(".local refused",         {"source_url": "https://printer.local/x"}, "REJECT")
# user@host reads as one site and goes to another
check("userinfo refused",       {"source_url": "https://hinyerevan.com@evil.example.com/x"}, "REJECT")
check("whitespace refused",     {"source_url": "https://example .com/x"}, "REJECT")
check("link over cap",          {"source_url": "https://a.example.com/" + "x" * 479}, "REJECT")

# ── request shape ────────────────────────────────────────────────────────────
check("non-numeric id",         {"id": "../etc"}, "REJECT")
check("missing coords",         {"lng": None}, "REJECT")

# ── phase 3: reports ─────────────────────────────────────────────────────────
# A report disputes what is displayed. `before` names the disputed fields and
# carries the values the reporter saw; `after` may propose replacements for some,
# all or none of them — a disputed field with no proposed value is a flag.
REPORT = dict(kind="report", source_url="https://www.hinyerevan.com/photos/10907")
check("report: correct a year",  {**REPORT, "before": {"year": {"year_built": 1965}},
                                  "after": {"year": 1985}}, "{'year': 1985")
check("report: flag only",       {**REPORT, "before": {"year": {"year_built": 1965}},
                                  "after": {}}, "OK {}")
check("report: correct + flag",  {**REPORT, "before": {"year": {"year_built": 1965},
                                                       "name": "Wrong name"},
                                  "after": {"year": 1985}}, "{'year': 1985")
# Phase 3 required a note on EVERY report, on the grounds that a reviewer is
# deciding between two claims. The evidence floor replaced that: a link to the
# page showing the right year IS that evidence, and demanding prose beside it
# was friction without a purpose. What must never happen is a report arriving
# with nothing attached at all.
check("report: link is enough",  {**REPORT, "before": {"year": {"year_built": 1965}},
                                  "after": {"year": 1985}, "source_note": ""}, "OK")
check("report: nothing attached", {**REPORT, "before": {"year": {"year_built": 1965}},
                                   "after": {"year": 1985}, "source_kind": "local",
                                   "source_url": None, "source_note": ""}, "REJECT")
check("report: must name a field", {**REPORT, "before": {}, "after": {"year": 1985}}, "REJECT")
check("report: only disputed",   {**REPORT, "before": {"year": {"year_built": 1965}},
                                  "after": {"year": 1985, "name": "X"}}, "REJECT")
check("report: field must exist", {**REPORT, "before": {"levels": 3}, "after": {}}, "REJECT")
check("unknown kind",            {"kind": "vandalism"}, "REJECT")

# ── staleness: is the report still about what the map shows? ─────────────────
# The phase 3 mirror of is_open. A value changed between submit and merge means
# the report describes a version of the data that no longer exists.
print()
for props, observed, want in [
    # the year is still exactly what was reported
    ({'year_built': 1965}, {'year': {'year_built': 1965}}, True),
    # somebody corrected it first
    ({'year_built': 1985}, {'year': {'year_built': 1965}}, False),
    # same number, different shape: "~1965" is not the claim "1965"
    ({'year_est': 1965}, {'year': {'year_built': 1965}}, True is False),
    # an era span, reported as it stands
    ({'year_min': 1958, 'year_max': 1972}, {'year': {'year_min': 1958, 'year_max': 1972}}, True),
    # the span was narrowed after the report
    ({'year_min': 1960, 'year_max': 1970}, {'year': {'year_min': 1958, 'year_max': 1972}}, False),
    # reporting a missing fact that is still missing
    ({}, {'year': {}}, True),
    # ...that somebody has since filled in
    ({'year_built': 1965}, {'year': {}}, False),
    # text fields compare directly
    ({'name': 'Cascade'}, {'name': 'Cascade'}, True),
    ({'name': 'Cascade'}, {'name': 'Casacde'}, False),
    ({}, {'name': None}, True),
]:
    reasons = matches_observed(props, observed)
    got = not reasons
    ok = got == want
    print(f"{'✓' if ok else '✗ FAIL'} still applies {str(observed):52} vs {str(props):40} → {got}")
    if not ok:
        failures.append(f'matches_observed({props}, {observed}): expected {want}, got {got}')

# ── openness: inference closes a field exactly like a confirmed year ─────────
print()
for props, field, want in [
    ({}, 'year', True),
    ({'year_built': 1965}, 'year', False),
    ({'year_est': 1965}, 'year', False),
    ({'year_min': 1958, 'year_max': 1972}, 'year', False),
    # an open bound closes the year exactly as a closed span does — what the map
    # displays is a claim, whichever end of it is known
    ({'year_min': 1958}, 'year', False),
    ({'year_max': 1972}, 'year', False),
    ({'name': 'X'}, 'year', True),
    ({'name': 'X'}, 'name', False),
    ({'year_built': 1965}, 'name', True),
]:
    got = is_open(props, field)
    ok = got == want
    print(f"{'✓' if ok else '✗ FAIL'} is_open {str(props):42} {field:6} → {got}")
    if not ok:
        failures.append(f"is_open({props}, {field}): expected {want}, got {got}")

# ── phase 4: orphans (docs §6) ───────────────────────────────────────────────
#
# The maintainer-only kind. Everything here goes through the same validator the
# wire uses, with KINDS passed explicitly — which is itself the test that the
# default stays closed.
ORPHAN = dict(id="2001", lng=44.5, lat=40.18, kind="orphan",
              before={"year": None}, after={"year": 1965, "approx": False},
              source_kind="online", source_url="https://www.hinyerevan.com/photos/1",
              derived_from="1000")


def orphan(name, patch, expect):
    try:
        r = validate_submission({**ORPHAN, **patch}, kinds=KINDS)
        got = f"OK {r['entry']} from {r['derived_from']}"
    except SubmissionError as e:
        got = f"REJECT({e.status}): {e}"
    ok = expect in got
    print(f"{'✓' if ok else '✗ FAIL'} orphan {name:33} → {got}")
    if not ok:
        failures.append(f"orphan {name}: expected {expect!r}, got {got!r}")


print()
orphan("inherits a year",        {}, "OK {'year': 1965, 'approx': False} from 1000")
orphan("inherits a bound",       {"after": {"year_max": 1972}}, "OK {'year_max': 1972}")
# The rule most worth holding: a split is exactly when names and addresses stop
# being shared, so neither ever travels.
orphan("cannot inherit a name",  {"after": {"year": 1965, "name": "School 76"}},
       "REJECT(400): an orphan can only inherit a year, not: name")
orphan("cannot inherit a street",
       {"after": {"year": 1965, "addr_street": "Abovyan"}},
       "REJECT(400): an orphan can only inherit a year, not: addr_street")
orphan("needs a parent",         {"derived_from": None}, "REJECT(400): derived_from")
orphan("parent must be an id",   {"derived_from": "../etc"}, "REJECT(400): derived_from")
orphan("cannot inherit itself",  {"derived_from": "2001"},
       "REJECT(400): an orphan cannot inherit from itself")
orphan("needs something to give", {"after": {}}, "REJECT(400)")
# The successor is a fresh id with an empty year, so the additive rule applies
# to an orphan exactly as it does to a suggestion.
orphan("before must be empty",   {"before": {"year": 1930}},
       "REJECT(400): these fields already have a value")
# A parent may predate the §2 source_kind split; its evidence still counts.
orphan("legacy parent evidence", {"source_kind": "document"}, "OK")
# The evidence floor is waived — the parent id is the provenance, and the
# parent's own note has very likely been purged by now (§4 Retention).
orphan("no note needed",         {"source_kind": "local", "source_url": None,
                                  "source_note": ""}, "OK")
# And the wire stays shut, which is the whole reason `kinds` defaults closed.
try:
    validate_submission(ORPHAN)
    failures.append("orphan reached validate_submission's default kinds")
    print("✗ FAIL orphan refused off the wire")
except SubmissionError as e:
    print(f"✓ orphan refused off the wire            → REJECT({e.status}): {e}")

print()
if failures:
    print(f"{len(failures)} failure(s):")
    for f in failures:
        print(f"  {f}")
    sys.exit(1)
print("all passed")
