#!/usr/bin/env python3
"""Validation for public suggestions — THE authority.

docs/submission-schema.md is the written spec; this module is its executable
form. The same rules exist in map.js (which inputs to render) and in the
Cloudflare Function (which requests to accept), and three implementations
drift. This one wins: it is the last gate before anything reaches
suggestions.json, and the only one that can see the built dataset.

Imported by:
    server.py       — the local /api/suggest stub, so the whole submit → review
                      → approve loop runs offline with no Worker and no D1
    apply_queue.py  — the merge, where additivity is actually enforced

Nothing here talks to a network or a database on purpose: it takes a decoded
payload and returns a normalised one, so both callers can share it and tests
need no fixtures.
"""

YEAR_MIN, YEAR_MAX = 1, 2030

# What the evidence IS. Closed enum, so the queue sorts by evidence quality
# before a word is read. NOT an anti-abuse measure — a bot fills a select
# instantly; Turnstile and the rate limit do that job. See §2.
#
# Deliberately NOT a statement about how the evidence is attached. A plaque can
# reach us as a link to somebody's photo of it or as a photo the submitter took
# standing in front of the building; a published source can be a URL or a scan.
# The kind says what is being claimed, the attachment says what we were handed,
# and conflating the two was the mistake in the first version of this list.
SOURCE_KINDS = ('plaque', 'online', 'local')

# What each kind must arrive with. This is the evidence floor: a submission that
# cannot meet it is not reviewable, and an unreviewable submission is worse than
# none — it costs a reviewer the same attention and can never be resolved.
#
#   plaque   nothing. "There is a plaque on this building and it says 1965" is
#            a claim a reviewer can go and check — Street View, or the walk past
#            it. Asking somebody standing in front of the thing to go and find
#            somebody else's photo of it is the wrong way round; once upload
#            exists, that is where their own photo goes.
#   online   a link. Without it there is no published source, only an assertion
#            that one exists somewhere.
#   local    a note. Nothing else can carry "I grew up in this block".
EVIDENCE_FLOOR = {'plaque': None, 'online': 'url', 'local': 'note'}

# The kinds a photo will satisfy once uploads are wired. Named now so the rule
# lives in one place when that lands, rather than being rediscovered.
SOURCE_PHOTO_OK = ('plaque', 'online')

# The five kinds this project used before the split above. Rows in D1 and 81
# records in provenance.json still carry them, and they have to keep rendering:
# 'document' alone accounts for 74 applied contributions. Read-only — nothing
# accepts these on the wire any more.
LEGACY_SOURCE_KINDS = {
    'cornerstone': 'plaque',
    'document': 'online',
    'resident': 'local',
    'local': 'local',
    'other': 'local',
}

URL_MAX = 500

# Everything a submission may carry, with its trimmed length cap. These are the
# only keys ever copied out of `after` — an unknown key is dropped, never stored.
TEXT_FIELDS = {'name': 200, 'addr_street': 200, 'addr_number': 20}
YEAR_FIELDS = ('year', 'approx', 'year_min', 'year_max')
SUGGESTABLE = tuple(TEXT_FIELDS) + YEAR_FIELDS

NOTE_MAX = 500

# The two kinds of submission, and the whole difference between phase 2 and 3:
#
#   suggestion  every field it touches was EMPTY. Additive, revertible by
#               deleting what it wrote.
#   report      the submitter says something already displayed is wrong. It
#               names the disputed fields in `before` with the values it saw,
#               and MAY propose replacements in `after`.
#
# Within one report a field with a proposed value is a correction and a field
# without one is a flag ("wrong, I don't know the right answer"). That is a
# per-FIELD distinction, not a per-submission one — somebody who can fix the
# year but only doubt the name sends one report, not two — so it is deliberately
# not a third kind here. What gets recorded per applied write, in
# provenance.json, is 'suggestion' or 'correction'.
#
# 'orphan' is the third kind and the only one no person sends: a year whose
# building stopped existing, re-proposed onto the footprints that replaced it.
# See docs/submission-schema.md §6. It is additive exactly like a suggestion —
# every successor is a fresh OSM id with an empty year — so it needs no separate
# rule at merge time; what differs is where it came from and what it may carry.
KINDS = ('suggestion', 'report', 'orphan')

# What /api/suggest will accept off the wire. An orphan waives the evidence
# floor and names its own `derived_from`, so accepting one from the public would
# be a hole straight through §2 — they are written by detect_splits.py, with the
# same credentials as any other maintainer task.
PUBLIC_KINDS = ('suggestion', 'report')

# The logical fields a person can talk about, as fieldIsOpen()/openFields() in
# map.js and is_open() below use them: one 'year', whatever shape it is in.
REPORTABLE = ('year', 'name', 'addr_street', 'addr_number')

# The four ways a year can sit on a built feature. A report's `before` carries
# whichever of these are non-null, so the merge can check the value is still
# what the reporter was looking at.
YEAR_PROPS = ('year_built', 'year_est', 'year_min', 'year_max')


class SubmissionError(ValueError):
    """Rejected. `status` is what the HTTP layer should answer.

    400 is reserved for what no honest client can produce; a submitter who
    simply mistyped a year gets 400 too, because the form should have caught it
    and a client that didn't is broken. Spam is never reported as spam — see
    the drop path in server.py / the Function.
    """

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _year(value, field):
    """None, or an int inside the range every year shape shares."""
    if value is None:
        return None
    if isinstance(value, bool):          # bool is an int subclass; 'True' is not a year
        raise SubmissionError(f'{field} must be a number')
    # int(1968.5) silently truncates to 1968, which would accept a submission
    # nobody made and disagree with the edge (Number.isInteger rejects it).
    # Caught by test_parity.py.
    if isinstance(value, float) and not value.is_integer():
        raise SubmissionError(f'{field} must be a whole year')
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise SubmissionError(f'{field} must be a number')
    if not (YEAR_MIN <= year <= YEAR_MAX):
        raise SubmissionError(f'{field} must be between {YEAR_MIN} and {YEAR_MAX}')
    return year


def parse_year_shape(after):
    """The year shapes, collapsed to the entry keys suggestions.json stores.

    At most one shape per submission (see classify_year in fetch_buildings.py):

        exact       {"year": 2015, "approx": False}
        after 1958  {"year_min": 1958}
        before 1972 {"year_max": 1972}
        span        {"year_min": 1958, "year_max": 1972}

    The form offers the first three. A span with both bounds is still accepted
    and still stored — it is the shape era inference writes, and old
    submissions carry it — but nothing in the UI can produce one any more: a
    contributor who does not know the year was being asked to invent a second
    number to sit beside the one they did know, and an open bound is the claim
    they actually have. See the form in map.js.

    "approx" (~1965) is likewise readable but no longer writable: existing
    entries keep rendering, and a submission that asks for a new one is
    rejected rather than quietly downgraded to an exact year, which would be
    this module inventing a precision on someone's behalf.

    Returns {} when no year was suggested at all — legitimate, since a
    submission may be an address alone.
    """
    year = _year(after.get('year'), 'year')
    year_min = _year(after.get('year_min'), 'year_min')
    year_max = _year(after.get('year_max'), 'year_max')

    if after.get('approx'):
        raise SubmissionError('approximate years are no longer accepted — '
                              'send an exact year, or a bound')
    if year_min is not None or year_max is not None:
        if year is not None:
            raise SubmissionError('a year and a bound are different shapes — send one')
        if year_min is not None and year_max is not None:
            if year_min > year_max:
                raise SubmissionError('range bounds are the wrong way round')
            if year_min == year_max:
                # A zero-width span is just an exact year. Stored as a range it
                # would render "1965-1965" and read as vaguer than was meant.
                return {'year': year_min, 'approx': False}
            return {'year_min': year_min, 'year_max': year_max}
        # one bound, one open end: the missing key IS the claim ("after 1958"),
        # so it is left out rather than stored as a null that would read as a
        # closed span with a hole in it
        return {'year_min': year_min} if year_min is not None else {'year_max': year_max}

    if year is not None:
        return {'year': year, 'approx': False}
    return {}


def parse_source_url(value):
    """A submitted link, validated by SHAPE only. None when absent.

    Strict about what a link may be, silent about whether it answers. Those are
    different questions and only the first one belongs here:

      * https only. http is a downgrade nobody needs for a citation, and the
        other schemes are attacks — javascript:, data:, file:.
      * a real hostname with a dot in it, so "localhost", bare "intranet" and
        IP literals are refused. A submitted URL is fetched by the Worker to
        report whether it answers (§6), and a fetch of a private address is the
        classic way to turn a public form into a probe of somebody's network.

    Whether the page RESPONDS is deliberately not decided here. Wikipedia
    answers 403 to a bare automated HEAD while a browser gets 200, so a
    reachability test is a signal for the reviewer and never a reason to refuse
    a submission — it would blame the contributor for someone else's bot policy.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise SubmissionError('source_url must be text')
    url = value.strip()
    if not url:
        return None
    if len(url) > URL_MAX:
        raise SubmissionError(f'source_url must be {URL_MAX} characters or fewer')
    if not url.startswith('https://'):
        raise SubmissionError('the link must start with https://')
    # whitespace anywhere means it is not one URL, and the pieces around it are
    # not checked by anything below
    if any(ch.isspace() for ch in url):
        raise SubmissionError('that does not look like a web address')

    authority = url[len('https://'):].split('/')[0]
    # user@host is how a link is made to READ as one site and go to another —
    # "https://www.hinyerevan.com@evil.example.com/x" is the evil host, and the
    # review card shows the string. A citation never needs credentials.
    if '@' in authority:
        raise SubmissionError('the link must not contain a username')
    host = authority.split(':')[0].lower()
    if not host or '.' not in host or host.endswith('.'):
        raise SubmissionError('that does not look like a web address')
    # an IP literal is never a citation, and is the shape an SSRF probe takes
    if all(part.isdigit() for part in host.split('.')):
        raise SubmissionError('the link must point at a website, not an IP address')
    if host in ('localhost', 'localhost.localdomain') or host.endswith('.local'):
        raise SubmissionError('the link must point at a public website')
    return url


def check_evidence(source_kind, source_url, source_note):
    """The floor: does this submission carry what its kind requires?

    One rule for suggestions and reports alike. Phase 3 required a note on every
    report on the grounds that a reviewer is deciding between two claims — but a
    link to the page that shows the right year IS that evidence, and demanding
    prose beside it was friction without a purpose.

    A plaque has no floor at all, and that is deliberate rather than an
    oversight: the claim names a physical thing on a specific building, which is
    the most checkable evidence in this whole system.
    """
    needs = EVIDENCE_FLOOR.get(source_kind)
    if needs == 'url' and not source_url:
        raise SubmissionError('a published source needs a link to it')
    if needs == 'note' and not source_note:
        raise SubmissionError('please say how you know — a sentence is enough')


def parse_text_fields(after):
    """name/addr_street/addr_number, trimmed and length-checked.

    A field present but blank is dropped rather than stored: there is no clear
    operation in this API (docs/submission-schema.md §2), so an empty string
    means "not suggested", never "erase what's there".
    """
    out = {}
    for field, cap in TEXT_FIELDS.items():
        value = after.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            raise SubmissionError(f'{field} must be text')
        value = value.strip()
        if not value:
            continue
        if len(value) > cap:
            raise SubmissionError(f'{field} must be {cap} characters or fewer')
        out[field] = value
    return out


def logical_field(key):
    """The field name a submission key talks about.

    'year', 'approx', 'year_min' and 'year_max' are four spellings of one fact,
    which is the vocabulary `before`, is_open() and the client's openFields()
    all share. Text fields are already their own name.
    """
    return 'year' if key in YEAR_FIELDS else key


def parse_observed(before):
    """A report's `before` → the disputed fields and the values they had.

    This is the half of a report that makes it checkable. The submitter is
    saying "the map showed me THIS and it is wrong", so the merge has to be able
    to ask, later and against a fresh build, whether it still shows that. If it
    doesn't, somebody already changed the value and the report is about a
    version of the data that no longer exists.

        {"year": {"year_built": 1965}, "name": null}

    A text field is its string, or null when the fact is simply missing (a
    report can be "there is no name and there should be"). The year is an object
    of whichever YEAR_PROPS were set, because which one it is *is* the claim:
    "1958-1972" and "1965" are different statements about the building.
    """
    if not isinstance(before, dict):
        raise SubmissionError('before must be an object')
    if not before:
        raise SubmissionError('a report has to say which field is wrong')

    observed = {}
    for field, value in before.items():
        if field not in REPORTABLE:
            raise SubmissionError(f'{field} is not a field that can be reported')
        if field == 'year':
            if value is None:
                observed[field] = {}
                continue
            if not isinstance(value, dict):
                raise SubmissionError('before.year must be an object of year properties')
            year = {}
            for prop, raw in value.items():
                if prop not in YEAR_PROPS:
                    raise SubmissionError(f'{prop} is not a year property')
                parsed = _year(raw, prop)
                if parsed is not None:
                    year[prop] = parsed
            observed[field] = year
        else:
            if value is None:
                observed[field] = None
                continue
            if not isinstance(value, str):
                raise SubmissionError(f'before.{field} must be text')
            observed[field] = value.strip()
    return observed


def matches_observed(properties, observed):
    """Does this built feature still show what the report was written against?

    Returns a list of human-readable reasons it does not; empty means the report
    still applies. The mirror of is_open() for phase 3, and used by the same
    caller (apply_queue.py) at the same moment — see docs/submission-schema.md §5.
    """
    reasons = []
    for field, was in observed.items():
        if field == 'year':
            now = {k: properties[k] for k in YEAR_PROPS
                   if properties.get(k) is not None}
            if now != (was or {}):
                reasons.append(
                    f'the year is now {now or "empty"}, not {was or "empty"} as reported '
                    f'— somebody changed it after this was submitted')
        else:
            now = properties.get(field)
            if (now or None) != (was or None):
                reasons.append(
                    f'{field} is now {now!r}, not {was!r} as reported '
                    f'— somebody changed it after this was submitted')
    return reasons


def validate_submission(body, kinds=PUBLIC_KINDS):
    """A decoded request body → the normalised submission to queue.

    Raises SubmissionError for anything malformed. Does NOT check additivity:
    that needs the built dataset and belongs to apply_queue.py, which is the
    only place it can actually be guaranteed.

    `kinds` defaults to what the PUBLIC WIRE may send, so a caller that forgets
    to think about it gets the safe answer. detect_splits.py passes KINDS to
    write an orphan; nothing reachable from /api/suggest ever should.
    """
    if not isinstance(body, dict):
        raise SubmissionError('expected a JSON object')

    raw_id = body.get('id')
    if raw_id is None:
        raise SubmissionError('id is required')
    osm_id = str(raw_id).strip()
    if not osm_id.isdigit() or len(osm_id) > 20:
        raise SubmissionError('id must be an OSM id')

    try:
        lng, lat = float(body['lng']), float(body['lat'])
    except (KeyError, TypeError, ValueError):
        raise SubmissionError('lng and lat are required')

    kind = body.get('kind', 'suggestion')
    if kind not in kinds:
        raise SubmissionError(f'kind must be one of: {", ".join(kinds)}')

    before = body.get('before') or {}
    after = body.get('after') or {}
    if not isinstance(after, dict):
        raise SubmissionError('after must be an object')

    entry = {**parse_text_fields(after), **parse_year_shape(after)}

    if kind == 'orphan':
        # Additive like a suggestion — every successor of a split is a fresh OSM
        # id with an empty year — so `before` is all nulls and §1's rule applies
        # unchanged. Two things differ, and both are in docs §6.
        if not isinstance(before, dict):
            raise SubmissionError('before must be an object')
        filled = sorted(k for k, v in before.items() if v not in (None, ''))
        if filled:
            raise SubmissionError(
                f'these fields already have a value and cannot be suggested: {", ".join(filled)}')
        # A split is exactly the moment a name and an address stop being shared:
        # one entrance becomes 42/1 and 42/3, and the school name belongs to one
        # piece rather than all three. Inheriting them would spray a confident
        # wrong address across the new buildings, so a year is all that travels.
        carried = sorted({logical_field(k) for k in entry} - {'year'})
        if carried:
            raise SubmissionError(
                'an orphan can only inherit a year, not: ' + ', '.join(carried))
        if not entry:
            raise SubmissionError('an orphan with no year inherits nothing')
        observed = {k: None for k in before}
    elif kind == 'suggestion':
        # `before` is the submitter's view of every field the form offered. Each
        # must be empty: a non-null one means the client rendered an input for a
        # field that already had a value, which the additive rule forbids. That
        # is a broken or hostile client, not a user error — and it is now also a
        # client that should have sent a report instead.
        if not isinstance(before, dict):
            raise SubmissionError('before must be an object')
        filled = sorted(k for k, v in before.items() if v not in (None, ''))
        if filled:
            raise SubmissionError(
                f'these fields already have a value and cannot be suggested: {", ".join(filled)}')
        if not entry:
            raise SubmissionError('nothing was suggested')
        observed = {k: None for k in before}
    else:
        # A report disputes what is already there, so `before` carries values
        # rather than nulls, and it is the list of disputed fields as well.
        observed = parse_observed(before)
        # Proposing a value for a field the report does not dispute would be a
        # correction nobody described and nothing checked — the merge tests
        # staleness only against `before`.
        undisputed = sorted({logical_field(k) for k in entry} - set(observed))
        if undisputed:
            raise SubmissionError(
                'a report can only propose values for the fields it disputes: '
                + ', '.join(undisputed))

    # Required, and required for a reason: a year with no evidence behind it is
    # unreviewable. See docs/submission-schema.md §2.
    #
    # An orphan inherits its parent's evidence, and the parent may predate the §2
    # split — 'document' alone accounts for 74 applied contributions — so a
    # legacy kind is readable here where the wire would refuse it.
    source_kind = body.get('source_kind')
    allowed = SOURCE_KINDS + tuple(LEGACY_SOURCE_KINDS) if kind == 'orphan' else SOURCE_KINDS
    if source_kind not in allowed:
        raise SubmissionError(f'source_kind must be one of: {", ".join(allowed)}')

    source_note = (body.get('source_note') or '').strip()
    if len(source_note) > NOTE_MAX:
        raise SubmissionError(f'source_note must be {NOTE_MAX} characters or fewer')
    source_url = parse_source_url(body.get('source_url'))

    derived_from = None
    if kind == 'orphan':
        # The parent id IS the provenance of an inherited year, and it is the
        # reason the evidence floor is waived rather than met: §2's floor exists
        # so a stranger's claim is reviewable, and this one is checkable by
        # opening the building it came from. Demanding a note as well would
        # demand something that may already be gone — notes are purged after
        # review (§4), and the parent's very likely has been.
        derived_from = str(body.get('derived_from') or '').strip()
        if not derived_from.isdigit() or len(derived_from) > 20:
            raise SubmissionError('derived_from must be the OSM id the year came from')
        if derived_from == osm_id:
            raise SubmissionError('an orphan cannot inherit from itself')
    else:
        check_evidence(source_kind, source_url, source_note)

    return {
        'id': osm_id,
        'lng': lng,
        'lat': lat,
        'kind': kind,
        # kept as submitted so apply_queue.py can re-check it against the build
        # at approval time: for a suggestion, that a field is still empty; for a
        # report, that the value being disputed is still the one on the map
        'before': observed,
        'entry': entry,
        'source_kind': source_kind,
        'source_url': source_url,
        'source_note': source_note,
        'derived_from': derived_from,
    }


def validate_review_edit(kind, observed, after):
    """A reviewer's replacement for a queued claim → the entry to store.

    Approve and Reject answer the wrong question when a claim is NEARLY right —
    three fragments of a split rarely share one year, and a report can name the
    right building and the wrong decade. The reviewer has the evidence on screen;
    before this the only path was to reject and re-enter the value by hand in the
    hand-editing suggestions.json, which severed the link between a submission
    and what it became.

    Validated exactly as a submitted entry, because it becomes one. The per-kind
    restrictions are the same ones validate_submission applies, for the same
    reasons — a reviewer may correct a claim, not convert it into a different
    kind of claim:

        report   only the fields it disputes (§5). Widening it would propose a
                 value for a field whose staleness nothing checked.
        orphan   a year only (§6).

    Additivity is deliberately NOT re-checked here, and must not be:
    apply_queue.py re-tests every field against the build at merge time and is
    still the only thing that can. An edit changes what is claimed, never
    whether the claim is allowed.
    """
    if not isinstance(after, dict):
        raise SubmissionError('after must be an object')

    entry = {**parse_text_fields(after), **parse_year_shape(after)}
    if not entry:
        # An entry edited down to nothing is a rejection, and should be sent as
        # one. Storing it would file the submission as approved and then merge
        # nothing, which reads as done and is not.
        raise SubmissionError('an edit cannot empty the claim — reject it instead')

    if kind == 'report':
        undisputed = sorted({logical_field(k) for k in entry} - set(observed or {}))
        if undisputed:
            raise SubmissionError(
                'a report can only propose values for the fields it disputes: '
                + ', '.join(undisputed))
    elif kind == 'orphan':
        carried = sorted({logical_field(k) for k in entry} - {'year'})
        if carried:
            raise SubmissionError(
                'an orphan can only inherit a year, not: ' + ', '.join(carried))

    return entry


def is_open(properties, field):
    """Is `field` open for suggestion on this built feature?

    The additive rule, in one line: anything the map displays is a claim, and
    changing a claim is a correction (Phase 3), not a suggestion. Inference
    counts as displayed — an era span is as closed as a confirmed year.

    fetch_buildings.py has already merged OSM tags, suggestions.json and
    inference into each feature and drops null-valued keys, so absence here is
    the whole test. No tier logic, no separate OSM lookup.
    """
    if field in ('year', 'year_min', 'year_max', 'approx'):
        return not any(properties.get(k) is not None
                       for k in ('year_built', 'year_est', 'year_min', 'year_max'))
    return properties.get(field) is None
