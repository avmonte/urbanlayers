#!/usr/bin/env python3
"""Merge approved public suggestions into suggestions.json.

This is where the additive rule is actually enforced. The client only renders
inputs for empty fields and the Function only checks shapes — neither can see
the built dataset, so neither can promise that a field was really empty. This
can, and does:

    a field is open  ⟺  the built feature has no value for it
                        AND the submission's `before` agreed at submit time

Both must hold. If the build says a field is filled but `before` said empty,
someone filled it in between and the submission has silently become a
CORRECTION — which is the separate Phase 3 flow, not this one. Those are
reported and skipped, never applied.

    python3 apply_queue.py                      # dry run — prints, changes nothing
    python3 apply_queue.py --apply              # write it
    python3 apply_queue.py --revert <sub-id>    # undo one submission
    python3 apply_queue.py --revert-submitter <id>     # undo a whole run

Dry run by default, same as bulk_suggest.py: the first form shows what it would
do and touches nothing.

Why revert is exact
-------------------
Additivity guarantees every applied field was absent beforehand, so undoing an
application is deleting the keys it wrote — there is no previous value to
restore and no way to get it wrong. That is the payoff for giving up in-place
corrections, and it is what makes a coordinated run of plausible-but-wrong
submissions survivable: they all land on blank buildings, break no rule, and
come out again as a set via --revert-submitter.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

import submission

import paths
from paths import rel

SUGGESTIONS_FILE = paths.SUGGESTIONS
PROVENANCE_FILE = paths.PROVENANCE
SUBMITTERS_FILE = str(paths.SUBMITTERS)
QUEUE_FILE = paths.QUEUE
GEOJSON_FILE = paths.BUILDINGS
BACKUP_SUFFIX = '.bak'


def load_json(path, default=None):
    if not os.path.exists(path):
        return {} if default is None else default
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    # sort_keys + indent 2 is load-bearing, not cosmetic: it keeps
    # suggestions.json diffing line-by-line, so a bot commit from CI and a local
    # edit merge cleanly instead of conflicting on one reformatted blob.
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


def load_queue(path):
    """The queue, from either place it can come from.

    Two shapes reach this script and they are not the same:

      queue.json          what server.py writes locally — {submission_id: record}
      a D1 export         what production actually holds. `wrangler d1 execute
                          --json` answers with [{"results": [row, ...]}], and a
                          row is flat SQL columns: osm_id rather than id, entry
                          and before_json as JSON *strings*.

    Normalising here rather than at the call site means the rest of the script
    never learns which one it got, and the local loop stays a true rehearsal of
    the production one instead of a similar-looking thing that diverges at the
    step that matters.
    """
    raw = load_json(path)

    # `wrangler --json` prints API failures as a JSON object on stdout, so a
    # redirect captures the error instead of the queue. Silently reading that as
    # "an empty queue" would mean a build that quietly applies nothing and looks
    # exactly like a build with nothing to apply.
    if isinstance(raw, dict) and 'error' in raw:
        detail = (raw['error'] or {}).get('text') or raw['error']
        notes = '; '.join(n.get('text', '') for n in (raw['error'] or {}).get('notes') or [])
        sys.exit(f"{path} holds an API error, not a queue: {detail} {notes}\n"
                 "Re-run the export from docs/build-and-deploy.md — nothing was applied.")

    # a D1 export: a list of statement results, each with its own rows
    if isinstance(raw, list):
        rows = [row for statement in raw for row in (statement.get('results') or [])]
    elif isinstance(raw, dict) and 'results' in raw:
        rows = raw['results']
    else:
        return raw, False               # already queue.json's shape

    queue = {}
    for row in rows:
        queue[row['submission_id']] = {
            'id': str(row['osm_id']),
            'lng': row['lng'],
            'lat': row['lat'],
            # Without this every report read from D1 arrives looking like a
            # suggestion, and the additive check rejects it for proposing a value
            # over a field that is not empty — which is exactly what a report is
            # for. Defaulted for rows written before the column existed.
            'kind': row.get('kind') or 'suggestion',
            'entry': json.loads(row['entry']),
            # What the SUBMITTER claimed, when a reviewer has since edited the
            # entry. NULL for the overwhelming majority; when set, it is the only
            # copy of the original claim and provenance has to keep it — see
            # docs/submission-schema.md §7.
            'entry_original': (json.loads(row['entry_original'])
                               if row.get('entry_original') else None),
            'before': json.loads(row['before_json'] or '{}'),
            'source_kind': row.get('source_kind'),
            'source_note': row.get('source_note'),
            'submitter_hash': row.get('submitter_hash'),
            'derived_from': row.get('derived_from'),
            'status': row.get('status'),
            'submitted_at': row.get('submitted_at'),
        }
    return queue, True


def submitter_id(submitter_hash):
    """An opaque, publishable handle for one submitter.

    submitter_hash is SHA-256(SUBMITTER_SALT + ':' + IP), truncated. That is
    pseudonymous, not anonymous: IPv4 is only 2^32 wide, so anyone who ever gets
    the salt can brute-force every published hash back to an address, and a
    repository keeps what it publishes forever. provenance.json is committed, so
    what goes in it is 'contributor-07' and the hash stays in data/local/.

    The map is append-only and stable across runs, which is all --revert-submitter
    needs: it groups a run, it never has to identify anyone. Delete the file and
    the ids simply start again from one — no map data depends on it.
    """
    if not submitter_hash:
        return None
    # detect_splits.py stamps a sentinel rather than a hash, precisely because
    # nobody submitted those. It identifies a machine, so it passes through:
    # anonymising it would lose the one thing it exists to say.
    if not re.fullmatch(r'[0-9a-f]{16}', submitter_hash):
        return submitter_hash
    known = load_json(SUBMITTERS_FILE)
    if submitter_hash in known:
        return known[submitter_hash]
    new_id = f'contributor-{len(known) + 1:02d}'
    known[submitter_hash] = new_id
    os.makedirs(os.path.dirname(SUBMITTERS_FILE), exist_ok=True)
    save_json(SUBMITTERS_FILE, known)
    return new_id


def load_built_features(path):
    """{osm id: properties} from the built dataset — the openness oracle.

    fetch_buildings.py has already merged OSM tags, suggestions.json and
    inference into each feature and dropped null-valued keys, so a missing key
    here IS the definition of open. Nothing else needs consulting.
    """
    if not os.path.exists(path):
        sys.exit(f"{path} not found — run fetch_buildings.py first.\n"
                 "Without the built dataset there is no way to check whether a "
                 "field is open, and applying blind is exactly what this script "
                 "exists to prevent.")
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return {str(f['properties']['id']): f['properties'] for f in data['features']}


# The keys a year shape writes, grouped: applying or reverting a year means all
# of them together, never a stray 'approx' left behind to change how it renders.
YEAR_KEYS = ('year', 'approx', 'year_min', 'year_max')

# What a queue `kind` is called once it is a durable provenance record. The two
# names differ because they answer different questions: the queue says what the
# submitter was doing, provenance says what the write DID to the file.
PROVENANCE_KINDS = {'report': 'correction', 'orphan': 'orphan', 'suggestion': 'suggestion'}


def fields_of(entry):
    """The suggestions.json keys this entry would write."""
    return tuple(k for k in entry)


def check_applicable(built, osm_id, rec):
    """Can this submission still be applied? A list of reasons it cannot.

    Two kinds, one question — "is the data still what this submission was
    written against?" — asked in opposite directions:

        suggestion  every field it writes must still be EMPTY (the additive
                    rule, docs/submission-schema.md §1)
        report      every field it disputes must still hold EXACTLY the value
                    the reporter saw (§5)

    Either way a mismatch means somebody changed the data in between, and the
    submission is about a version of it that no longer exists. Skipped and
    reported, never applied over the newer value.
    """
    entry, before = rec['entry'], rec.get('before') or {}
    props = built.get(osm_id)
    if props is None:
        # Same failure mode fetch_buildings.py's orphan check reports: an id
        # that matches no building. Applying it would write an entry nothing
        # can ever render.
        return [f'building {osm_id} is not in the build (deleted, redrawn, or outside the boundary)']

    if rec.get('kind') == 'report':
        # The whole check is `before` vs the build: a report names what it
        # disputes and what it saw, and submission.py owns the comparison so the
        # rule lives in one place.
        return submission.matches_observed(props, before)

    # An orphan falls through to the additive check below, and that is the point
    # rather than an omission. Its successor is a fresh OSM id with an empty
    # year, so "is this field still empty?" is exactly the right question — and
    # asking it here is what stops a re-homed year landing on a building that
    # someone has meanwhile researched properly. See docs §6.
    reasons = []
    for field in fields_of(entry):
        # 'approx' has no independent existence — it qualifies 'year', and
        # is_open already treats the whole year shape as one field.
        if field == 'approx':
            continue
        if not submission.is_open(props, field):
            current = (props.get('year_built') or props.get('year_est')
                       or props.get('year_min') or props.get('year_max')
                       ) if field in YEAR_KEYS else props.get(field)
            reasons.append(f'{field} is no longer empty (now {current!r}) — '
                           f'that is a report now, not a suggestion')
    for field, value in before.items():
        if value not in (None, ''):
            reasons.append(f'{field} was already filled when submitted')
    return reasons


# ── combining claims ─────────────────────────────────────────────────────────
#
# A photograph never proves a construction year. It proves a BOUND: a building
# visible in a 1948 photo existed by 1948, and one missing from a 1944 photo
# went up after 1944. Two such photos are two claims, and together they say more
# than either alone — 1944-1948.
#
# So a second claim about a building must not overwrite the first. Overwriting
# made more evidence produce a WORSE answer: "after 1936" plus a later "before
# 1942" left the map showing only "before 1942", throwing away a bound somebody
# had researched.
#
# Two claims can also be irreconcilable — "before 1942" landing on "after 1944".
# One of those sources is wrong, and which one is a judgement about archives, not
# something this script can settle. Those are reported and left alone, the same
# way a stale submission is.

def year_interval(entry):
    """What an entry claims about the year, as (lo, hi).

    A zero-width interval is an exact year. (None, None) means the entry claims
    nothing about the year at all — including a legacy approx year, which is a
    guess at a point rather than a bound on one, and so constrains nothing: real
    evidence arriving later replaces it rather than arguing with it.
    """
    if entry.get('year') is not None and not entry.get('approx'):
        return entry['year'], entry['year']
    if entry.get('year') is not None:      # {'year': Y, 'approx': True} — legacy
        return None, None
    return entry.get('year_min'), entry.get('year_max')


def as_year_entry(lo, hi):
    """(lo, hi) back into the keys suggestions.json stores."""
    if lo is not None and lo == hi:
        # a zero-width span is an exact year, the same collapse parse_year_shape
        # makes — "1965-1965" reads as vaguer than what is actually known
        return {'year': lo, 'approx': False}
    out = {}
    if lo is not None:
        out['year_min'] = lo
    if hi is not None:
        out['year_max'] = hi
    return out


def merge_years(current, claim):
    """Fold a new year claim into what a building already says.

    Returns (year_keys, conflict) — exactly one of them is meaningful. Bounds
    intersect: the latest "after" and the earliest "before" both survive, which
    is what makes evidence converge instead of taking turns.
    """
    old_lo, old_hi = year_interval(current)
    new_lo, new_hi = year_interval(claim)
    if new_lo is None and new_hi is None:
        return {}, None                      # the claim says nothing about the year
    if old_lo is None and old_hi is None:
        return as_year_entry(new_lo, new_hi), None

    lo = max((v for v in (old_lo, new_lo) if v is not None), default=None)
    hi = min((v for v in (old_hi, new_hi) if v is not None), default=None)
    if lo is not None and hi is not None and lo > hi:
        return None, (f'says {describe(new_lo, new_hi)}, but this building already '
                      f'says {describe(old_lo, old_hi)} — the two cannot both be true, '
                      f'so one of the sources is wrong')
    return as_year_entry(lo, hi), None


def describe(lo, hi):
    """A (lo, hi) interval in the words the map uses for it."""
    if lo is not None and lo == hi:
        return str(lo)
    if lo is not None and hi is not None:
        return f'{lo}-{hi}'
    return f'after {lo}' if lo is not None else f'before {hi}'


def write_entry(suggestions, osm_id, entry, overwrite_conflicts=False):
    """Fold one submission's entry into suggestions.json.

    Returns (replaced, conflict). A conflict means nothing was written and the
    caller should skip the submission: two claims about this building cannot both
    be true, and choosing between them is a judgement about sources.

    `overwrite_conflicts` settles that judgement in favour of the NEWER claim
    rather than stopping, and is the default. On a project where the reviewer is
    also the researcher, a conflict is not two strangers disagreeing — it is the
    same person having found something better since, and stopping to arbitrate
    against yourself on every build is friction carrying no safety. The value
    that gets overwritten is still recorded in `replaced`, so --revert restores
    it exactly and nothing is lost.

    Not a plain dict.update(), for two separate reasons.

    A year is FOLDED, not overwritten — bounds intersect, so a building already
    known to be "after 1936" that gains a "before 1942" ends up at 1936-1942
    rather than losing the older bound. See merge_years above for why that
    matters more than it sounds.

    And whatever the fold produces replaces the whole year shape rather than
    updating into it. An entry holds ONE shape — 'year' + 'approx', or
    'year_min'/'year_max' — and classify_year() in fetch_buildings.py reads
    year_min FIRST, so a leftover bound from the previous shape would keep the
    map rendering the old range and ignore the new value entirely.

    The returned `replaced` is what the entry held before, and it is what
    revert() puts back.
    """
    current = suggestions.setdefault(osm_id, {})

    merged, conflict = merge_years(current, entry)
    if conflict:
        if not overwrite_conflicts:
            return None, conflict
        # The new claim wins whole, rather than being folded. Folding intersects
        # bounds, and the point of overwriting is that the OLD bounds are being
        # disbelieved — carrying them into the answer would preserve exactly the
        # value being rejected.
        merged = {k: v for k, v in entry.items() if k in YEAR_KEYS}

    keys = set(entry) - set(YEAR_KEYS)
    if merged:
        keys |= set(YEAR_KEYS)
    replaced = {k: current[k] for k in keys if k in current}
    for key in keys:
        current.pop(key, None)
    current.update({k: v for k, v in entry.items() if k not in YEAR_KEYS})
    current.update(merged)
    return replaced, None


def apply_submissions(args):
    # Truncated up front, not just written at the end: every path out of this
    # function has to leave the file meaning "what THIS run applied". Two of them
    # return early (nothing outstanding, and a dry run), and a caller that marked
    # D1 from a leftover file would be marking rows against a merge that did not
    # happen on this pass.
    if args.applied_ids:
        open(args.applied_ids, 'w', encoding='utf-8').close()

    queue, from_d1 = load_queue(args.queue)
    suggestions = load_json(SUGGESTIONS_FILE)
    provenance = load_json(PROVENANCE_FILE)
    built = load_built_features(args.geojson)

    # Idempotency: every application is recorded, so a re-run applies nothing
    # twice even if the queue still says "approved".
    applied_ids = {rec['submission_id']
                   for records in provenance.values() for rec in records}

    approved = [(sid, rec) for sid, rec in sorted(queue.items(),
                                                  key=lambda kv: kv[1].get('submitted_at', 0))
                if rec.get('status') == 'approved' and sid not in applied_ids]

    if not approved:
        print('Nothing to apply — no approved submissions outstanding.')
        return 0

    applied, skipped, flags, conflicts = [], [], [], []
    for sid, rec in approved:
        osm_id, entry = rec['id'], rec['entry']
        reasons = check_applicable(built, osm_id, rec)
        if reasons:
            skipped.append((sid, osm_id, reasons))
            continue

        # A report with nothing in `after` is a flag: "this is wrong, I don't
        # know the right answer". There is no data to merge, so it is listed for
        # the maintainer and left in the queue rather than silently marked done.
        if not entry:
            flags.append((sid, osm_id, rec))
            continue

        if args.apply:
            replaced, conflict = write_entry(suggestions, osm_id, entry,
                                             args.overwrite_conflicts)
            if conflict:
                conflicts.append((sid, osm_id, conflict))
                continue
            provenance.setdefault(osm_id, []).append({
                'submission_id': sid,
                # The opaque id, never the hash — see submitter_id(). Same
                # reasoning as source_note below: provenance.json is committed.
                'submitter': submitter_id(rec.get('submitter_hash')),
                # source_kind is kept; source_note is NOT. The note is required
                # and can identify a person ("I live here" + a building id), and
                # suggestions.json is a Derived Database under ODbL — share-alike
                # would carry that detail into every downstream copy, forever.
                'source_kind': rec.get('source_kind'),
                'fields': sorted(fields_of(entry)),
                # 'suggestion' filled something empty; 'correction' overwrote
                # something. That is the difference between a revert that
                # deletes and a revert that restores, so it is recorded here
                # rather than looked up in D1 — where notes are purged, rows age
                # out, and this file is the durable record. It also makes every
                # overwrite this project has ever made greppable as a class.
                #
                # 'orphan' reverts by deletion like a suggestion, but is its own
                # label because it is NOT a contribution: it is this project's
                # own year, re-homed after an OSM split. Counting it as community
                # work would inflate the one number on the map that means people
                # — see load_community_years in fetch_buildings.py.
                'kind': PROVENANCE_KINDS.get(rec.get('kind'), 'suggestion'),
                # The claim itself, as submitted — not the value the map ended up
                # showing. Those are different things now that claims combine: a
                # building at "1936-1942" may hold two claims, neither of which
                # said that. This is the record of who claimed what; the fold of
                # them is what suggestions.json carries.
                'claim': dict(entry),
                # A reviewer may correct a claim before approving it (docs §7).
                # When that happened, `claim` above is the REVIEWER's words, so
                # the submitter's own are kept beside them — otherwise this file
                # would credit a stranger with a year they never claimed,
                # permanently and under ODbL.
                **({'claim_original': dict(rec['entry_original']), 'edited': True}
                   if rec.get('entry_original') else {}),
                # for an orphan: the building this year used to describe
                **({'derived_from': rec['derived_from']}
                   if rec.get('derived_from') else {}),
                # what was overwritten, and the ONLY thing that can put it back.
                # Empty when the displayed value came from OSM or inference
                # rather than suggestions.json — there revert is still deletion.
                **({'replaced': replaced} if replaced else {}),
                # disputed but not corrected: flagged fields ride along on a
                # report that fixed something else, so the doubt is not lost
                **({'flagged': sorted(set(rec.get('before') or {})
                                      - {submission.logical_field(k) for k in entry})}
                   if rec.get('kind') == 'report'
                   and set(rec.get('before') or {}) - {submission.logical_field(k) for k in entry}
                   else {}),
                'submitted_at': rec.get('submitted_at'),
                'applied_at': int(time.time()),
            })
            # Retention: the note has done its job at review time.
            rec.pop('source_note', None)
            rec['status'] = 'applied'
        applied.append((sid, osm_id, entry))

    verb = 'Applied' if args.apply else 'Would apply'
    print(f"{verb} {len(applied)} submission(s):")
    for sid, osm_id, entry in applied:
        print(f"  {sid}  building {osm_id:>12}  {entry}")

    # Flags carry no data, so nothing above will ever mention them again. This
    # list is the only place they surface, and they stay 'approved' in the queue
    # until the value is fixed by hand — being marked applied would file them as
    # done when nothing has been done.
    if flags:
        print(f"\n{len(flags)} flagged, nothing proposed — fix these by hand "
              f"in the editor, they stay in the queue:")
        for sid, osm_id, rec in flags:
            disputed = ', '.join(sorted(rec.get('before') or {}))
            note = (rec.get('source_note') or '').strip()
            print(f"  {sid}  building {osm_id:>12}  disputes {disputed}")
            if note:
                print(f"      “{note}”")

    # Only reachable under --keep-conflicts. By default an irreconcilable claim
    # overwrites rather than waiting for a decision: nothing moved and nobody
    # edited in between, so it is the same researcher having found something
    # better, and the replaced value is in provenance.json either way.
    if conflicts:
        print(f"\n{len(conflicts)} left queued — irreconcilable with what the map "
              f"shows, and --keep-conflicts asked to be told rather than decide:")
        for sid, osm_id, reason in conflicts:
            print(f"  {sid}  building {osm_id:>12}")
            print(f"      {reason}")

    if skipped:
        # Both kinds land here, for the same reason in opposite directions: a
        # suggestion whose field is no longer empty, or a report whose disputed
        # value is no longer the one being disputed. Somebody edited in between.
        print(f"\nSkipped {len(skipped)} — the data moved since they were submitted:")
        for sid, osm_id, reasons in skipped:
            print(f"  {sid}  building {osm_id:>12}")
            for reason in reasons:
                print(f"      {reason}")

    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply.")
        return 0

    # The ids a caller needs to mark applied in D1, for a script that cannot read
    # the sentence below. build_public.sh tests this file rather than the exit
    # code, which is 0 whether or not anything was applied. Still no network
    # here — see the comment further down.
    if args.applied_ids:
        with open(args.applied_ids, 'w', encoding='utf-8') as f:
            f.write(''.join(f'{sid}\n' for sid, _, _ in applied))

    if applied:
        for path in (SUGGESTIONS_FILE, PROVENANCE_FILE):
            if os.path.exists(path):
                shutil.copy2(path, str(path) + BACKUP_SUFFIX)
        save_json(SUGGESTIONS_FILE, suggestions)
        save_json(PROVENANCE_FILE, provenance)
        if from_d1:
            # The export is a copy; the real rows are in D1 and this script has
            # no network. Marking them there is a separate, explicit step — and
            # it is the step that also drops source_note, which must not outlive
            # review (docs/submission-schema.md §4).
            ids = "', '".join(sid for sid, _, _ in applied)
            print(f"\n✓ {rel(SUGGESTIONS_FILE)} and {rel(PROVENANCE_FILE)} updated "
                  f"(backups at *{BACKUP_SUFFIX})")
            print("\n  Now mark them applied in D1 and purge the notes:\n")
            # One line, quoted once. Wrapping it for width produced something
            # that looked copy-pasteable and wasn't: the continuation became a
            # second shell command.
            db = os.environ.get('D1_DATABASE', '<your-d1-database>')
            print(f"    npx wrangler d1 execute {db} --remote --command "
                  f"\"UPDATE submissions SET status='applied', source_note=NULL "
                  f"WHERE submission_id IN ('{ids}')\"")
        else:
            save_json(args.queue, queue)
            print(f"\n✓ {rel(SUGGESTIONS_FILE)} and {rel(PROVENANCE_FILE)} updated "
                  f"(backups at *{BACKUP_SUFFIX})")
        print("\n  Run fetch_buildings.py to see it on the map.")
    return 0


def revert(args):
    """Undo what one submission — or one submitter's whole run — wrote.

    Exact by construction, in two ways depending on what was applied:

        suggestion   the fields were empty before, so undoing is deleting the
                     keys that application wrote
        correction   something was there, so undoing is restoring the `replaced`
                     values recorded at apply time, then deleting the rest

    Which one it was is in the record's `kind`, and the previous values are in
    its `replaced` — neither is inferable afterwards, which is why both are
    written (docs/submission-schema.md §5). A correction over a value that came
    from OSM or inference records no `replaced` and reverts by deletion: the
    underlying tag or era call reappears on the next build, which IS the old
    value returning.

    An entry left with nothing in it is dropped, matching how server.py treats
    an emptied form.
    """
    suggestions = load_json(SUGGESTIONS_FILE)
    provenance = load_json(PROVENANCE_FILE)

    def matches(rec):
        if args.revert:
            return rec['submission_id'] == args.revert
        # Accepts what provenance publishes ('contributor-07') or the raw hash
        # off a D1 row, which is resolved through the local map when it exists.
        wanted = load_json(SUBMITTERS_FILE).get(args.revert_submitter,
                                                args.revert_submitter)
        return rec.get('submitter') == wanted

    hits = [(osm_id, rec) for osm_id, records in provenance.items()
            for rec in records if matches(rec)]
    if not hits:
        target = args.revert or args.revert_submitter
        print(f'Nothing to revert — no application recorded for {target}')
        return 1

    print(f"{'Reverting' if args.apply else 'Would revert'} {len(hits)} application(s):")
    for osm_id, rec in hits:
        replaced = rec.get('replaced') or {}
        action = f"drops {', '.join(rec['fields'])}"
        if replaced:
            action += f", restores {replaced}"
        print(f"  {rec['submission_id']}  building {osm_id:>12}  "
              f"[{rec.get('kind', 'suggestion')}] {action}")
        if not args.apply:
            continue
        entry = suggestions.get(osm_id, {})
        for field in rec['fields']:
            entry.pop(field, None)
        # order matters: a correction's replaced keys can overlap the fields it
        # wrote (year → year), so the restore has to happen after the removal
        entry.update(replaced)
        if entry:
            suggestions[osm_id] = entry
        else:
            suggestions.pop(osm_id, None)
        provenance[osm_id] = [r for r in provenance[osm_id]
                              if r['submission_id'] != rec['submission_id']]
        if not provenance[osm_id]:
            provenance.pop(osm_id)

    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply.")
        return 0

    for path in (SUGGESTIONS_FILE, PROVENANCE_FILE):
        if os.path.exists(path):
            shutil.copy2(path, str(path) + BACKUP_SUFFIX)
    save_json(SUGGESTIONS_FILE, suggestions)
    save_json(PROVENANCE_FILE, provenance)
    print(f"\n✓ Reverted (backups at *{BACKUP_SUFFIX}). "
          f"Run fetch_buildings.py to see it on the map.")
    return 0


parser = argparse.ArgumentParser(
    description='Merge approved public suggestions into suggestions.json.',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""examples:
  %(prog)s                                  dry run: what would be applied
  %(prog)s --apply                          write it
  %(prog)s --revert 4a083db29f05 --apply    undo one submission
  %(prog)s --revert-submitter contributor-07 --apply   undo a whole run
""")
parser.add_argument('--apply', action='store_true',
                    help='actually write; without it this is a dry run')
parser.add_argument('--revert', metavar='SUBMISSION_ID',
                    help='undo one applied submission')
parser.add_argument('--revert-submitter', metavar='SUBMITTER',
                    help="undo every application from one submitter — the id "
                         "provenance.json records (contributor-07), or the raw "
                         "submitter_hash from a D1 row")
parser.add_argument('--applied-ids', metavar='PATH',
                    help='write the submission ids that were applied to PATH, one per '
                         'line, for a caller that has to mark them in D1 afterwards '
                         '(build_public.sh does). Written empty when nothing applied.')
parser.add_argument('--queue', default=QUEUE_FILE, metavar='PATH',
                    help=f'queue.json from server.py, or a `wrangler d1 execute --json` '
                         f'export from production (default: {rel(QUEUE_FILE)})')
parser.add_argument('--geojson', default=GEOJSON_FILE, metavar='PATH',
                    help=f'built dataset used as the openness oracle (default: {rel(GEOJSON_FILE)})')
parser.add_argument('--keep-conflicts', dest='overwrite_conflicts',
                    action='store_false', default=True,
                    help='leave a submission queued when its claim cannot be '
                         'reconciled with what the map already shows, instead of '
                         'letting the newer claim win. The default overwrites; the '
                         'replaced value is recorded in provenance.json, so '
                         '--revert puts it back exactly.')

if __name__ == '__main__':
    args = parser.parse_args()
    if args.revert and args.revert_submitter:
        parser.error('--revert and --revert-submitter are different questions — pick one')
    sys.exit(revert(args) if (args.revert or args.revert_submitter)
             else apply_submissions(args))
