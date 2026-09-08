#!/usr/bin/env python3
"""Proves submission.py and functions/api/_shared.js agree — run: python3 test_parity.py

The same rules exist in Python (the merge gate) and JS (the edge). Two
implementations of one spec drift, and the drift is invisible until a
submission is accepted at the edge and rejected at the merge — or worse, the
other way round. This runs identical cases through both and diffs the answers.

Needs node on PATH. Skips (exit 0) without it, so it never blocks a machine
that only runs the Python side.
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
import paths
from submission import validate_submission, validate_review_edit, SubmissionError

VALID = dict(id="524357988", lng=44.5136, lat=40.1872, before={"year": None},
             after={"year": 1968, "approx": False},
             source_kind="online", source_url="https://www.hinyerevan.com/photos/10907",
             source_note="")

CASES = [
    ("exact",                  {}),
    ("approx",                 {"after": {"year": 1965, "approx": True}}),
    ("approx false",           {"after": {"year": 1965, "approx": False}}),
    ("range",                  {"after": {"year_min": 1958, "year_max": 1972}}),
    ("zero-width range",       {"after": {"year_min": 1965, "year_max": 1965}}),
    ("range backwards",        {"after": {"year_min": 1972, "year_max": 1958}}),
    ("after only",             {"after": {"year_min": 1958}}),
    ("before only",            {"after": {"year_max": 1972}}),
    ("open bound + name",      {"after": {"year_max": 1972, "name": "Block 4"}}),
    ("year and bound",         {"after": {"year": 1960, "year_min": 1958}}),
    ("year and range",         {"after": {"year": 1960, "year_min": 1958, "year_max": 1972}}),
    ("year too big",           {"after": {"year": 3000}}),
    ("year zero",              {"after": {"year": 0}}),
    ("bool as year",           {"after": {"year": True}}),
    ("float year",             {"after": {"year": 1968.5}}),
    ("string year",            {"after": {"year": "1968"}}),
    ("empty after",            {"after": {}}),
    ("blank name",             {"after": {"year": 1968, "name": "   "}}),
    ("name at cap",            {"after": {"year": 1968, "name": "x" * 200}}),
    ("name over cap",          {"after": {"year": 1968, "name": "x" * 201}}),
    ("number over cap",        {"after": {"year": 1968, "addr_number": "x" * 21}}),
    ("non-string name",        {"after": {"year": 1968, "name": 42}}),
    ("unknown key",            {"after": {"year": 1968, "evil": "x"}}),
    ("address only",           {"after": {"addr_street": "Abovyan", "addr_number": "12"}}),
    ("before filled",          {"before": {"year": 1965}}),
    ("before blank string",    {"before": {"year": ""}}),
    ("bad source_kind",        {"source_kind": "vibes"}),
    ("no source_kind",         {"source_kind": None}),
    ("other, no note",         {"source_kind": "other", "source_note": ""}),
    ("other, with note",       {"source_kind": "other", "source_note": "grandmother"}),
    ("note at cap",            {"source_note": "x" * 500}),
    ("note over cap",          {"source_note": "x" * 501}),
    ("id not numeric",         {"id": "../etc"}),
    ("id empty",               {"id": ""}),
    ("no lng",                 {"lng": None}),
    ("lng as string",          {"lng": "44.5"}),

    # ── phase 3: reports ────────────────────────────────────────────────────
    # `before` stops being all-nulls and becomes the disputed fields with the
    # values the reporter saw, so the two validators now have a second shape to
    # agree on — including which year property was set, which is the claim.
    ("report: correct a year",
     {"kind": "report", "before": {"year": {"year_built": 1965}}, "after": {"year": 1985},
      "source_note": "cornerstone says 1985"}),
    ("report: flag, no value",
     {"kind": "report", "before": {"year": {"year_min": 1958, "year_max": 1972}}, "after": {},
      "source_note": "far too old for this block"}),
    ("report: correct + flag",
     {"kind": "report", "before": {"year": {"year_built": 1965}, "name": "Wrong"},
      "after": {"year": 1985}, "source_note": "both wrong"}),
    ("report: missing name",
     {"kind": "report", "before": {"name": None}, "after": {"name": "Cascade"},
      "source_note": "it is the Cascade"}),
    ("report: no note",
     {"kind": "report", "before": {"year": {"year_built": 1965}}, "after": {"year": 1985},
      "source_note": ""}),
    ("report: disputes nothing",
     {"kind": "report", "before": {}, "after": {"year": 1985}, "source_note": "x"}),
    ("report: undisputed field",
     {"kind": "report", "before": {"year": {"year_built": 1965}},
      "after": {"year": 1985, "name": "X"}, "source_note": "x"}),
    ("report: unreportable field",
     {"kind": "report", "before": {"levels": 3}, "after": {}, "source_note": "x"}),
    ("report: bad year property",
     {"kind": "report", "before": {"year": {"year_guess": 1965}}, "after": {}, "source_note": "x"}),
    ("report: year as a number",
     {"kind": "report", "before": {"year": 1965}, "after": {}, "source_note": "x"}),
    ("report: empty year object",
     {"kind": "report", "before": {"year": {}}, "after": {"year": 1985}, "source_note": "x"}),
    ("report: name as a number",
     {"kind": "report", "before": {"name": 42}, "after": {}, "source_note": "x"}),
    ("unknown kind",
     {"kind": "vandalism", "before": {"year": None}, "after": {"year": 1968}}),

    # ── phase 4: orphans are NOT accepted off the wire ───────────────────────
    # An orphan waives the evidence floor and names its own `derived_from`, so
    # both sides must refuse one here no matter how well-formed it looks —
    # detect_splits.py writes them, /api/suggest never does. docs §6.
    ("orphan off the wire",
     {"kind": "orphan", "before": {"year": None}, "after": {"year": 1965},
      "derived_from": "1000"}),
    ("orphan, no derived_from",
     {"kind": "orphan", "before": {"year": None}, "after": {"year": 1965}}),

    # ── evidence: the kind sets the floor, the link is shape-checked ─────────
    ("plaque with a link",     {"source_kind": "plaque"}),
    ("plaque with nothing",    {"source_kind": "plaque", "source_url": None}),
    ("online with no link",    {"source_kind": "online", "source_url": None}),
    ("local with a note",      {"source_kind": "local", "source_url": None,
                                "source_note": "I grew up in this block"}),
    ("local with no note",     {"source_kind": "local", "source_url": None}),
    ("local with only a link", {"source_kind": "local", "source_note": ""}),
    ("retired kind",           {"source_kind": "cornerstone"}),
    ("http link",              {"source_url": "http://example.com/page"}),
    ("javascript link",        {"source_url": "javascript:alert(1)"}),
    ("ip literal link",        {"source_url": "https://169.254.169.254/meta-data"}),
    ("localhost link",         {"source_url": "https://localhost/admin"}),
    ("hostless link",          {"source_url": "https://intranet/wiki"}),
    ("userinfo link",          {"source_url": "https://user@evil.example.com/x"}),
    ("link at cap",            {"source_url": "https://a.example.com/" + "x" * 478}),
    ("link over cap",          {"source_url": "https://a.example.com/" + "x" * 479}),
    ("link with spaces",       {"source_url": "https://example .com/x"}),
    ("blank link, has note",   {"source_kind": "local", "source_url": "   ",
                                "source_note": "neighbour told me"}),
]

# ── reviewer edits (docs §7) ─────────────────────────────────────────────────
# A reviewer may replace what a queued submission claims, and the replacement is
# validated by the same two implementations — so they have a third thing to
# agree on. (kind, observed, after) → the entry that gets stored.
EDIT_CASES = [
    ("edit a year",            ("suggestion", {"year": None}, {"year": 1972})),
    ("edit to a bound",        ("suggestion", {"year": None}, {"year_max": 1972})),
    ("edit to a span",         ("suggestion", {"year": None},
                                {"year_min": 1958, "year_max": 1972})),
    ("edit to nothing",        ("suggestion", {"year": None}, {})),
    ("edit to a blank string", ("suggestion", {"name": None}, {"name": "   "})),
    ("edit, year and bound",   ("suggestion", {"year": None}, {"year": 1960, "year_min": 1958})),
    ("edit, out of range",     ("suggestion", {"year": None}, {"year": 3000})),
    ("edit, float year",       ("suggestion", {"year": None}, {"year": 1968.5})),
    ("edit, approx refused",   ("suggestion", {"year": None}, {"year": 1965, "approx": True})),
    # a report may still only propose for what it disputed
    ("report edit, disputed",  ("report", {"year": {"year_built": 1965}}, {"year": 1972})),
    ("report edit, undisputed",
     ("report", {"year": {"year_built": 1965}}, {"year": 1972, "name": "X"})),
    ("report edit, name only", ("report", {"name": "Wrong"}, {"name": "Right"})),
    # an orphan may still only carry a year
    ("orphan edit, year",      ("orphan", {"year": None}, {"year": 1972})),
    ("orphan edit, a name",    ("orphan", {"year": None}, {"year": 1972, "name": "X"})),
]

EDIT_RUNNER = r'''
import { validateReviewEdit, SubmissionError } from './functions/api/_shared.js';
const cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map(([kind, observed, after]) => {
  try {
    return { ok: true, entry: validateReviewEdit(kind, observed, after) };
  } catch (e) {
    if (e instanceof SubmissionError) return { ok: false, status: e.status };
    throw e;
  }
})));
'''

JS_RUNNER = r'''
import { validateSubmission, SubmissionError } from './functions/api/_shared.js';
const cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map(body => {
  try {
    const r = validateSubmission(body);
    return { ok: true, entry: r.entry, kind: r.kind, before: r.before,
             source_url: r.source_url, source_kind: r.source_kind };
  } catch (e) {
    if (e instanceof SubmissionError) return { ok: false, status: e.status };
    throw e;
  }
})));
'''


def python_result(body):
    try:
        r = validate_submission(body)
        # `before` is compared too now: for a report it is the disputed fields
        # and the values they held, which the merge checks staleness against, so
        # a difference there is as real a drift as a different entry.
        return {'ok': True, 'entry': r['entry'], 'kind': r['kind'], 'before': r['before'],
                'source_url': r['source_url'], 'source_kind': r['source_kind']}
    except SubmissionError as e:
        return {'ok': False, 'status': e.status}


def main():
    if not shutil.which('node'):
        print('node not on PATH — skipping parity check')
        return 0

    bodies = [{**VALID, **patch} for _, patch in CASES]

    runner_mjs = str(paths.ROOT / '.parity_runner.mjs')
    with open(runner_mjs, 'w') as f:
        f.write(JS_RUNNER)
    try:
        out = subprocess.run([shutil.which('node'), runner_mjs, json.dumps(bodies)],
                             capture_output=True, text=True)
    finally:
        os.remove(runner_mjs)

    if out.returncode:
        print('node runner failed:\n' + out.stderr)
        return 1
    js_results = json.loads(out.stdout)

    failures = []
    for (name, _), body, js in zip(CASES, bodies, js_results):
        py = python_result(body)
        # Compare the decision and, when accepted, the normalised entry. Message
        # wording is allowed to differ; the ANSWER is not.
        same = py['ok'] == js['ok'] and (
            (py.get('entry') == js.get('entry')
             and py.get('kind') == js.get('kind')
             and py.get('before') == js.get('before')
             and py.get('source_url') == js.get('source_url'))
            if py['ok'] else py['status'] == js['status'])
        verdict = (f"accept {py['kind'][:4]} "
                   + json.dumps(py.get('entry'), sort_keys=True)) if py['ok'] \
            else f"reject {py['status']}"
        print(f"{'✓' if same else '✗ DRIFT'} {name:28} py={verdict}"
              + ('' if same else f"   js={json.dumps(js, sort_keys=True)}"))
        if not same:
            failures.append(name)

    # ── the same diff, for reviewer edits ────────────────────────────────────
    edits = [args for _, args in EDIT_CASES]
    edit_mjs = str(paths.ROOT / '.parity_edit.mjs')
    with open(edit_mjs, 'w') as f:
        f.write(EDIT_RUNNER)
    try:
        out = subprocess.run([shutil.which('node'), edit_mjs, json.dumps(edits)],
                             capture_output=True, text=True)
    finally:
        os.remove(edit_mjs)
    if out.returncode:
        print('node edit runner failed:\n' + out.stderr)
        return 1

    print()
    for (name, (kind, observed, after)), js in zip(EDIT_CASES, json.loads(out.stdout)):
        try:
            py = {'ok': True, 'entry': validate_review_edit(kind, observed, after)}
        except SubmissionError as e:
            py = {'ok': False, 'status': e.status}
        same = py['ok'] == js['ok'] and (
            py.get('entry') == js.get('entry') if py['ok'] else py['status'] == js['status'])
        verdict = ('accept ' + json.dumps(py.get('entry'), sort_keys=True)) if py['ok'] \
            else f"reject {py['status']}"
        print(f"{'✓' if same else '✗ DRIFT'} edit: {name:22} py={verdict}"
              + ('' if same else f"   js={json.dumps(js, sort_keys=True)}"))
        if not same:
            failures.append('edit: ' + name)

    print()
    if failures:
        print(f'{len(failures)} case(s) drifted: {", ".join(failures)}')
        print('Fix docs/submission-schema.md first, then both implementations.')
        return 1
    print(f'{len(CASES)} submission + {len(EDIT_CASES)} edit cases — Python and JS agree')
    return 0


if __name__ == '__main__':
    sys.exit(main())
