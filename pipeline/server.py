#!/usr/bin/env python3
"""Static file server for mappio, plus the local stand-in for the submission
queue so the whole submit -> review -> approve loop runs with no Cloudflare
account.

Run this instead of `python -m http.server`:
    python server.py [port]

Submissions land in data/local/queue.json, the offline twin of the D1 table.
Nothing here writes suggestions.json: only apply_queue.py does, and only from
an approved row. That is the whole point — there is no trusted write path any
more, so the local loop is the same loop a visitor goes through.

suggestions.json entries still carry a year in one of the shapes the map
renders (see classify_year in fetch_buildings.py), and which keys an entry
carries is what says which:

    exact   {"year": 2015, "approx": false}       →  "2015"
    after   {"year_min": 1958}                    →  "after 1958"
    before  {"year_max": 1972}                    →  "before 1972"
    span    {"year_min": 1958, "year_max": 1972}  →  "1958-1972"
    approx  {"year": 1965, "approx": true}        →  "~1965"   (legacy, read-only)

The public form writes the first three; a span is what era inference writes,
and the ~year is legacy — both still render, neither is offered any more. The
shapes are mutually exclusive, so an entry never holds both "year" and a bound.
Any of them is authoritative over the OSM tag; everything but the exact year
renders as an estimate rather than a confirmed one. name/addr_street/addr_number
override the corresponding OSM tag; a field that isn't present comes from OSM.
"""
import hashlib
import http.server
import json
import os
import re
import sys
import time
import urllib.parse
import uuid

import submission

import paths
from paths import rel

INFO_FIELDS = ('name', 'addr_street', 'addr_number')
YEAR_MIN, YEAR_MAX = 1, 2030

# ── The public-suggestion queue, locally ─────────────────────────────────────
#
# In production these three routes are a Cloudflare Function writing to D1. Here
# they are the same routes over a JSON file, for one reason: without them the
# only way to exercise submit → review → approve is to deploy, and that is
# expensive to get wrong: every `wrangler pages deploy` mints an immutable hash
# URL that serves its build forever, and hours once went into reloading a
# frozen copy of a broken one (docs/build-and-deploy.md, Gotchas).
#
# So the loop runs offline. server.py already exists to make local preview match
# production — Cache-Control, Range, application/x-protobuf — and this is the
# same idea applied to the API. Validation is not reimplemented here: both this
# and apply_queue.py import submission.py, which is the authority.
QUEUE_FILE = paths.QUEUE

# Salts the per-submitter hash so queue.json never holds a raw client address.
# Regenerated per process, because locally the hash only needs to group one
# session's submissions — the production Function uses a persistent secret so
# a run of bad submissions stays revertable as a set across days.
SUBMITTER_SALT = uuid.uuid4().hex

RANGE_RE = re.compile(r'^bytes=(\d*)-(\d*)$')


class _CappedReader:
    """Wraps a file so copyfile() stops at the end of the requested range.

    SimpleHTTPRequestHandler copies until EOF, which for a range request would
    send the rest of the archive after the requested slice.
    """

    def __init__(self, fp, remaining):
        self._fp = fp
        self._remaining = remaining

    def read(self, size=-1):
        if self._remaining <= 0:
            return b''
        if size is None or size < 0:
            size = self._remaining
        chunk = self._fp.read(min(size, self._remaining))
        self._remaining -= len(chunk)
        return chunk

    def close(self):
        self._fp.close()


def parse_year_field(value):
    """None, or the value as a year the form would accept."""
    if value is None:
        return None
    year = int(value)
    if not (YEAR_MIN <= year <= YEAR_MAX):
        raise ValueError('year out of range')
    return year


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    # queue.json lives in data/local/, which is dev state and therefore absent
    # from a fresh clone — the first submission is what creates it.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


# Where each top-level URL segment actually lives. The browser's URLs are the
# contract — map.js asks for 'buildings.geojson' and 'water.geojson' relative to
# the page, and those strings are also what the deployed site serves — so the
# front end moved into web/ without a single line changing inside it. This table
# is the whole cost of that: one lookup, resolved before the stdlib handler ever
# sees the path.
#
# Anything not listed falls through to web/, which is why the three HTML pages,
# map.js and map.css need no entry.
ROUTES = {
    'buildings.geojson': paths.BUILD,   # only a tiles:false build reads this
    'stats.json':        paths.BUILD,   # counters, slider bounds, year index
    # The map asks for tiles relative to the page, so the page at / asks for
    # /tiles/. tippecanoe writes them straight into public/, so that is where
    # they come from — which also means / needs a build to have run, exactly
    # like the deployed site does. Without this the page loads, the legend
    # fills in, and not one building draws.
    'tiles':             paths.PUBLIC,
    'water.geojson':     paths.SOURCE,  # tracked backdrop, not an output
    'fonts':             paths.ROOT,    # the wordmark faces, served as /fonts/
    'public':            paths.ROOT,    # the assembled site, previewed as-is
}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        # web/ is the document root; ROUTES sends the data paths elsewhere.
        kw.setdefault('directory', str(paths.WEB))
        super().__init__(*a, **kw)

    def translate_path(self, path):
        """Map a URL onto the tree, per ROUTES.

        Delegates to the stdlib for the actual resolution rather than joining
        anything by hand — that is what keeps `..` from escaping the directory —
        and only swaps which directory it resolves against.
        """
        top = urllib.parse.urlparse(path).path.lstrip('/').split('/', 1)[0]
        target = ROUTES.get(urllib.parse.unquote(top))
        if target is None:
            return super().translate_path(path)
        saved, self.directory = self.directory, str(target)
        try:
            return super().translate_path(path)
        finally:
            self.directory = saved

    def end_headers(self):
        # Every file here is edited in place during development — map.js/map.css
        # by hand, buildings.geojson by fetch_buildings.py — and the default
        # handler sends no Cache-Control at all. Browsers then fall back to
        # heuristic freshness (~10% of the file's age), so a day-old map.js gets
        # cached for hours WITHOUT revalidating: you end up running yesterday's
        # front-end against today's data and nothing you regenerate has any
        # effect. 'no-cache' still allows caching, it just forces a revalidation
        # (If-Modified-Since) every time, so edits always land.
        self.send_header('Cache-Control', 'no-cache, must-revalidate')
        self.send_header('Accept-Ranges', 'bytes')
        super().end_headers()

    def guess_type(self, path):
        if str(path).endswith('.pbf'):
            return 'application/x-protobuf'
        return super().guess_type(path)

    def send_head(self):
        """Add single-range (206 Partial Content) support.

        buildings.pmtiles is a single-file tile archive that the browser reads by
        asking for byte ranges — that's the entire point of the format, since it
        means only the tiles in view get downloaded. The stdlib handler ignores
        the Range header and answers 200 with the whole file, so the map would
        pull all 16MB (or fail outright) without this. Real static hosts do it
        natively; this only exists so local testing matches production.
        """
        rng = self.headers.get('Range')
        if not rng:
            return super().send_head()

        m = RANGE_RE.match(rng.strip())
        path = self.translate_path(self.path)
        if not m or not os.path.isfile(path):
            return super().send_head()  # multi-range or a directory — let the default answer

        size = os.path.getsize(path)
        start_s, end_s = m.groups()
        if start_s == '':                       # "bytes=-N" — the final N bytes
            n = int(end_s or 0)
            start, end = max(0, size - n), size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
        end = min(end, size - 1)

        if start >= size or start > end:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.end_headers()
            return None

        fp = open(path, 'rb')
        fp.seek(start)
        length = end - start + 1
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(length))
        self.end_headers()
        return _CappedReader(fp, length)

    def do_GET(self):
        # The review UI asks for the pending queue; everything else is a file.
        if self.path.split('?')[0] == '/api/queue':
            self.handle_queue()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/suggest':
            self.handle_public_suggest()
        elif self.path == '/api/review':
            self.handle_review()
        else:
            self.send_error(404)

    # ── helpers ──────────────────────────────────────────────────────────────

    def read_json_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(length) or b'{}')

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def submitter_hash(self):
        """A stable, non-identifying handle for whoever is submitting.

        Its only job is to make a run of plausible-but-wrong submissions
        revertable as a set: additivity does not stop that attack, since every
        such entry lands on a blank building and breaks no rule. The raw address
        is never stored.
        """
        return hashlib.sha256(
            f'{SUBMITTER_SALT}:{self.client_address[0]}'.encode()).hexdigest()[:16]

    # ── public suggestion queue ──────────────────────────────────────────────

    def handle_public_suggest(self):
        """Queue one public suggestion. Mirrors functions/api/suggest.js.

        Nothing here writes to suggestions.json — only apply_queue.py does.
        A public submission only ever becomes data
        by going through apply_queue.py, which is where additivity is enforced.
        """
        try:
            body = self.read_json_body()
        except json.JSONDecodeError:
            self.send_json({'ok': False, 'error': 'malformed JSON'}, 400)
            return

        # Honeypot: a real form leaves it empty because it is hidden. Answer
        # exactly as if it worked — never tell a submitter they were filtered,
        # or the endpoint becomes an oracle for tuning past the filter.
        if (body.get('website') or '').strip():
            self.send_json({'ok': True})
            return

        try:
            entry = submission.validate_submission(body)
        except submission.SubmissionError as err:
            self.send_json({'ok': False, 'error': str(err)}, err.status)
            return

        queue = load_json(QUEUE_FILE)
        submission_id = uuid.uuid4().hex[:12]
        queue[submission_id] = {
            **entry,
            'status': 'pending',
            'submitted_at': int(time.time()),
            'submitter_hash': self.submitter_hash(),
        }
        save_json(QUEUE_FILE, queue)
        print(f"  queued {submission_id}  building {entry['id']}  {entry['entry']}")
        self.send_json({'ok': True, 'submission_id': submission_id})

    def handle_queue(self):
        """Pending submissions, for the review UI.

        Behind Cloudflare Access in production. Locally there is no auth, which
        is fine and is also why server.py must never be the public build — the
        same reason the review page is behind Access (see build_public.sh).
        """
        queue = load_json(QUEUE_FILE)
        pending = [{'submission_id': sid, **rec}
                   for sid, rec in queue.items() if rec.get('status') == 'pending']
        pending.sort(key=lambda r: r.get('submitted_at', 0))
        self.send_json({'ok': True, 'pending': pending})

    def handle_review(self):
        """Approve or reject one queued submission.

        Approving only marks it: the merge into suggestions.json is
        apply_queue.py's job, because that is the one place that can see the
        built dataset and therefore the one place additivity can be guaranteed.
        Doing it here would mean a second, weaker implementation of the rule.
        """
        try:
            body = self.read_json_body()
            submission_id = str(body['submission_id'])
            decision = body['decision']
        except (KeyError, json.JSONDecodeError, TypeError):
            self.send_json({'ok': False,
                            'error': 'expected {submission_id, decision}'}, 400)
            return

        # 'noted' acknowledges a flag: nothing to merge, and neither approving
        # nor rejecting says the true thing. See docs/submission-schema.md §5.
        if decision not in ('approved', 'rejected', 'noted'):
            self.send_json({'ok': False,
                            'error': 'decision must be "approved", "rejected" or "noted"'}, 400)
            return

        queue = load_json(QUEUE_FILE)
        record = queue.get(submission_id)
        if record is None:
            self.send_json({'ok': False, 'error': 'no such submission'}, 404)
            return
        if record.get('status') != 'pending':
            # Not an error worth failing on, but the reviewer should know they
            # are looking at a stale queue rather than assume their click landed.
            self.send_json({'ok': False,
                            'error': f"already {record['status']}"}, 409)
            return

        # A reviewer may correct a claim before approving it, and the edit is
        # validated by the same module that validated the submission — see
        # docs/submission-schema.md §7. Mirrors functions/api/review.js so the
        # offline loop stays a true rehearsal of the deployed one.
        edited = False
        edit = body.get('entry')
        if edit is not None:
            if decision != 'approved':
                self.send_json({'ok': False,
                                'error': 'only an approval can carry an edited entry'}, 400)
                return
            try:
                entry = submission.validate_review_edit(
                    record.get('kind') or 'suggestion', record.get('before') or {}, edit)
            except submission.SubmissionError as err:
                self.send_json({'ok': False, 'error': str(err)}, err.status)
                return
            # An edit that changes nothing is not an edit: entry_original has to
            # keep meaning "what the submitter claimed", not "the last time
            # somebody pressed the button".
            if entry != record.get('entry'):
                record.setdefault('entry_original', record.get('entry'))
                record['entry'] = entry
                edited = True

        record['status'] = decision
        record['reviewed_at'] = int(time.time())
        save_json(QUEUE_FILE, queue)
        self.send_json({'ok': True, 'submission_id': submission_id,
                        'status': decision, 'edited': edited})



if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8007
    print(f"serving {paths.rel(paths.WEB)}/ as /  ·  site: /public/  ·  review: /review.html")
    http.server.test(HandlerClass=Handler, port=port)
