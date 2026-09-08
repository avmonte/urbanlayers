# Public submission schema

**This file is the authority.** The rules below are implemented three times —
`map.js` (client), `functions/api/suggest.js` (Worker), `apply_queue.py` (merge)
— and three implementations drift. When they disagree, **`apply_queue.py` wins**:
it is the last gate before data enters `suggestions.json`, and it is the only one
that can see the built dataset. Change this file first, then the three.

---

## 0. Two kinds of submission

| `kind` | means | `before` | phase |
|---|---|---|---|
| `suggestion` (default) | fills fields that are **empty** | every field the form offered, all `null` | 2 |
| `report` | says something **already displayed** is wrong | the disputed fields, with the values the reporter saw | 3 |
| `orphan` | a year whose building **stopped existing** — re-homed onto the footprints that replaced it | every field, all `null` (the successor is a new id and carries nothing) | 4 |

Within one report, a disputed field **with** a proposed value in `after` is a
*correction*; one **without** is a *flag* ("wrong, I don't know the right
answer"). That is a per-field distinction, not a per-submission one — somebody
who can fix the year but only doubt the name sends one report, not two — so
there is no third `kind`. What is recorded per applied write, in
`provenance.json`, is `suggestion` or `correction`.

`orphan` is the only kind that is **not** submitted by a person. Splitting a
building in OSM mints new ids for the pieces, and the year that described the
original then belongs to no building at all — it does not orphan visibly, it
just stops being rendered, because a new id with no suggestion is
indistinguishable from a building nobody has researched. `detect_splits.py`
finds those and re-proposes the year onto each successor, one row per piece, so
the loss surfaces as a review queue instead of as silence.

An orphan is additive exactly like a suggestion — every successor is a fresh id
with an empty year — so it goes through §1's rule unchanged. What differs is
where it came from and what may be inherited: §6.

§1–§4 below describe suggestions. §5 describes reports. §6 describes orphans.

## 1. What may be suggested — the additive rule

> **A field is open for public suggestion iff the built feature has no value for
> it.**

Anything the map *displays* is a claim, and changing a claim is a correction.
Corrections are the separate "report error" flow (Phase 3), not this one. So
inferred era spans count as present and are **closed**, exactly like a confirmed
year — no confidence-tier reasoning anywhere in this path.

Because `fetch_buildings.py` has already merged OSM tags, `suggestions.json` and
inference into each feature, the built feature is the single oracle. No separate
OSM lookup, no tier logic:

```
open(field) := built_feature.properties[field] is absent
```

Openness is checked **twice**, and both must agree:

| Where | Against | Purpose |
|---|---|---|
| client (`map.js`) | the feature in the loaded tile | only render inputs for open fields |
| merge (`apply_queue.py`) | the current build **and** the submission's `before` | the actual guarantee |

The client check is UX and is **not** a security boundary — a hostile POST can
carry any field. The Worker cannot check openness either: it has no dataset, and
shipping 76k ids to it is not worth it. Additivity is enforced at merge or
nowhere.

If a field is non-empty at merge time but was empty in `before`, someone filled
it in between. The submission has become a correction: **flag, do not apply.**

## 2. Wire format

`POST /api/suggest`

```json
{
  "id": "524357988",
  "lng": 44.5136,
  "lat": 40.1872,
  "before": { "year": null, "addr_street": null, "addr_number": null },
  "after":  { "year": 1968, "approx": false },
  "source_kind": "plaque",
  "source_url": "https://www.hinyerevan.com/photos/10907",
  "source_note": "",
  "turnstile_token": "…",
  "website": ""
}
```

- `before` — what the submitter's tiles showed for every field the form offered.
  Every value MUST be `null`; a non-null one means the client offered a closed
  field and the submission is rejected outright.
- `after` — only the fields being suggested. Absent means "not suggested", never
  "clear". **There is no clear operation in this API.**
- `website` — honeypot. Must be empty. Non-empty → accept with `200` and drop.

### Year shapes

Exactly one shape per submission, never more (mirrors `classify_year` in
`fetch_buildings.py` and `handle_suggest` in `server.py`):

| shape | keys | renders | offered by the form |
|---|---|---|---|
| exact | `year`, `approx: false` | `2015` | yes |
| after | `year_min` alone | `after 1958` | yes |
| before | `year_max` alone | `before 1972` | yes |
| span | `year_min` + `year_max` | `1958-1972` | no — era inference, and older submissions |
| approx | `year`, `approx: true` | `~1965` | no — legacy, rejected on submit |

The form asks two questions, not three: do you know the year, or do you know a
side of it. `approx` asked people to grade their own certainty on a scale
nobody shares, and a closed range asked someone who knew one number to invent a
second — both invited a made-up number where an open bound is a fact somebody
actually holds. The two retired shapes still **render** wherever they already
exist in `suggestions.json`; only new ones are refused.

An open bound stores **one** key. The other is absent, not null: its absence is
the claim.

`year_min == year_max` collapses to exact — a zero-width span reads as vaguer
than what was meant.

### Field rules

| field | type | rule |
|---|---|---|
| `id` | string | digits only, ≤ 20 chars |
| `lng` / `lat` | number | finite; required. Not bounds-checked — the coordinates only place a review pin, and the real guard is that `apply_queue.py` rejects an `id` that is not in the build |
| `year`, `year_min`, `year_max` | int | `1 ≤ y ≤ 2030`, whole numbers only |
| `approx` | bool | must be false or absent — a truthy one is rejected |
| `year_min`/`year_max` | int | at least one; `min ≤ max` when both are sent |
| `name` | string | trimmed, 1–200 chars. Still accepted, but **the public form no longer asks for it** — most buildings have no name, and the popup shows the address in that slot instead (`PUBLIC_FIELDS` in map.js). Names reach the data through a report, and the ones already there still render |
| `addr_street` | string | trimmed, 1–200 chars |
| `addr_number` | string | trimmed, 1–20 chars |
| `source_kind` | enum | see below — **required** |
| `source_url` | string | https only, shape-checked; **required** for `online` |
| `source_note` | string | ≤ 500 chars; **required** for `local` |

A submission with an empty `after` is rejected: there is nothing to suggest.

### Evidence: `source_kind`, `source_url`, `source_note`

`source_kind` says what the evidence **is**. It is deliberately *not* a claim
about how that evidence is attached — a plaque reaches us as a link to somebody's
photo of it, or (once uploads exist) as a photo taken standing in front of the
building; a published source is a URL or a scan. Conflating the two was the
mistake in the first version of this list.

| value | label (en) | must arrive with | field shown |
|---|---|---|---|
| `plaque` | a plaque or date on the building | nothing | none |
| `online` | a published source | `source_url` | link |
| `local` | local knowledge | `source_note` | note |

**The evidence floor.** One rule for suggestions and reports alike, and the form
shows exactly one field — the one that kind requires, and nothing at all for a
plaque.

A plaque having no floor is deliberate. "There is a plaque on this building and
it says 1965" names a physical thing at a specific address, which a reviewer can
check with Street View or a walk past it — the most checkable evidence in this
system. Asking somebody standing in front of the thing to go and find someone
else's photo of it is the wrong way round; once photo upload exists, that is
where their own photo goes.

This also replaces the phase 3 rule that every report needed a note: a link to
the page showing the right year *is* that evidence, and demanding prose beside
it was friction.

**`source_url` is validated by shape, never by whether it answers.**

| rule | why |
|---|---|
| `https://` only | http is a downgrade nobody needs for a citation; `javascript:`, `data:` and `file:` are attacks |
| a hostname with a dot, no IP literals, no `localhost`/`.local` | the Worker fetches this URL to report whether it answers, and fetching a private address is how a public form becomes a probe of somebody's network |
| no `user@host` | `https://hinyerevan.com@evil.example.com/x` reads as one site and goes to another, and the review card shows the string |
| no whitespace, ≤ 500 chars | whitespace means it is not one URL |

**Reachability is a signal, not a gate.** The Worker sends one `HEAD` with a
4-second timeout and stores the result in `link_status` ("http 200",
"no response (TimeoutError)"). It never refuses a submission: Wikipedia answers
`403` to a bare automated HEAD that a browser gets `200` for, so a hard gate
would reject real sources and blame the contributor for someone else's bot
policy. The reviewer sees the status next to a link they can simply click.

`source_kind` is **not** an anti-abuse measure; a bot fills a select instantly.
Turnstile and the per-IP rate limit do that work. Its value is review triage and
making a person pause to ask whether they actually know.

**Retired kinds.** `cornerstone`, `resident`, `document` and `other` are refused
on the wire but still render: rows in D1 and 81 records in `provenance.json`
carry them, `document` alone accounting for 74 applied contributions. The
read-only mapping lives in `LEGACY_SOURCE_KINDS` (`submission.py`).

## 3. Responses

Always `200` with `{"ok": true}` for anything accepted **or silently dropped**
(honeypot, rate limit, spam heuristics). Never tell a submitter their submission
was rejected as spam — that builds a filter oracle.

`400` is only for malformed requests that no honest client can produce (bad JSON,
missing `id`, a closed field in `before`). `403` for a failed Turnstile check,
since an honest client can hit that and needs to retry.

## 4. After approval

- the open fields in `after` are merged into `suggestions.json`, in the entry
  shape `server.py` documents. Untouched fields are never written.
- `provenance.json` records `{osm_id: {submission_id, submitter,
  source_kind, submitted_at, approved_at}}`. It is a **sibling** file:
  `fetch_buildings.py` reads a fixed shape from `suggestions.json` and must not
  be given new keys.
- it is also the only thing that can tell an accepted public suggestion apart
  from the maintainer's own research — both land in `suggestions.json` in the
  same shape. `fetch_buildings.py` reads it for exactly that (`load_community_years`)
  to count the map's "Community Contributions" row, and takes **ids only**:
  `submitter` must never reach `buildings.geojson`, the tiles or `stats.json`,
  all of which are published under ODbL. See Retention below.
- `submitter` exists so a run of plausible-but-wrong submissions can be reverted
  as a set. Additivity does not stop that attack — every such entry lands on a
  blank building and breaks no rule.
- it is an **opaque id** (`contributor-07`), not `submitter_hash`. The hash is
  SHA-256(`SUBMITTER_SALT` + `:` + IP) truncated to 64 bits, which is
  pseudonymous rather than anonymous: IPv4 is 2^32 wide, so whoever holds the
  salt can brute-force any published hash back to an address. `provenance.json`
  is committed and a repository keeps what it publishes forever, so the hash
  stops at `data/local/submitters.json` and only the id is written.
  `apply_queue.py --revert-submitter` takes either.

### Retention

`source_note` is required and can identify a person ("I live here" + a building
id). It **must not** enter `suggestions.json`: that file is a Derived Database
under ODbL, and share-alike would carry a stranger's personal detail into every
downstream copy, permanently.

- on approval: `provenance.json` keeps `source_kind` only; `source_note` is dropped
- the D1 row (note included) is purged on a schedule
- the raw `wrangler d1 execute --json` export carries the note *and* the hash, so
  it is written to `data/local/queue_export.json` and is not tracked. This
  repository is itself a published artifact — the rule that keeps a stranger's
  detail out of `suggestions.json` keeps it out of the repo for the same reason

---

## 5. Reports (phase 3)

A report is the only way to change a value the map already shows. It carries
`kind: "report"`, and `before` stops being a list of nulls:

```json
{
  "kind": "report",
  "id": "524357988",
  "lng": 44.5136, "lat": 40.1872,
  "before": { "year": { "year_built": 1965 }, "name": "Wrong name" },
  "after":  { "year": 1985 },
  "source_kind": "plaque",
  "source_url": "https://www.hinyerevan.com/photos/10907",
  "source_note": "the date above the entrance reads 1985",
  "turnstile_token": "…", "website": ""
}
```

- **`before` is the disputed set.** Its keys are the fields being reported, from
  `year`, `name`, `addr_street`, `addr_number`; its values are what the reporter
  saw. A field missing from `before` cannot be corrected — `after` may only
  propose values for fields the report disputes, because staleness is checked
  against `before` and nothing else.
- **The year is an object of the properties that were set** (`year_built`,
  `year_est`, `year_min`, `year_max`), not a bare number, because which one it is
  *is* the claim: `1958-1972`, `~1965` and `1965` are three different statements
  about the building, and a report has to say which one it disagrees with.
- **`null` is a legitimate observed value**, and `{}` a legitimate observed year:
  "there is no name here and there should be" is a report like any other.
- **A note is always required**, not only for `source_kind: "other"`. Accepting a
  suggestion is accepting a gift; accepting a report is deciding between two
  claims about one building, and a dropdown value cannot carry that.
- **`after` may be empty.** That is a pure flag: nothing to merge, everything to
  look at. Flags are never applied by `apply_queue.py` — they are a work queue.

### Staleness — the mirror of the additive rule

Additivity asks "is this field still empty?". A report asks the same question
about a value:

```
applicable(report) := every field in `before` still holds exactly the value it records
```

Checked in `matches_observed()` (`submission.py`), by the same caller and at the
same moment as `is_open()`. A value changed between submit and merge means the
report describes a version of the data that no longer exists; it is skipped and
reported, never applied over the newer value.

### Claims combine; they do not overwrite

A photograph never proves a construction year. It proves a **bound**: a building
visible in a 1948 photo existed by 1948, one missing from a 1944 photo went up
after 1944. Two photos are two claims, and together they say more than either
alone.

So a second claim is folded into the first, in `merge_years()`
(`apply_queue.py`). Bounds intersect — the latest "after" and the earliest
"before" both survive:

| on the map | new claim | result |
|---|---|---|
| after 1936 | before 1942 | **1936-1942** |
| 1944-1972 | before 1948 | **1944-1948** |
| after 1936 | after 1944 | after 1944 |
| after 1948 | before 1948 | **1948** (bounds that meet are an exact year) |
| 1944-1948 | 1946 | 1946 |
| after 1944 | before 1942 | **conflict** |
| 1953 | 1948 | **conflict** |

Overwriting was the earlier behaviour and it was wrong in a way that is easy to
miss: a building known to be "after 1936" that gained a "before 1942" ended up
showing only "before 1942". **More evidence produced a worse answer.**

A conflict means two claims cannot both be true, so one of the sources is wrong
— which is a judgement about archives, not something a merge can settle. Those
are reported, left in the queue, and the map keeps what it had.

**Every claim is recorded.** A provenance record carries `claim` (what that
submission actually proposed) alongside `replaced` (what the entry held before
it). Those are now different things: a building showing `1936-1942` may hold two
claims, neither of which said that. `suggestions.json` carries the fold;
`provenance.json` carries who claimed what.

A legacy `approx` year is a guess at a point rather than a bound on one, so it
constrains nothing: real evidence replaces it rather than arguing with it.

### What applying one costs

A suggestion can be undone by deleting the keys it wrote. A correction cannot —
something was there before. So every applied correction records, in
`provenance.json`, both its `kind` and the `replaced` values it overwrote, and
`--revert` restores them instead of deleting. Without that pair, one accepted
bad correction is unrecoverable and `--revert-submitter` stops being a safety
net. See the header of `apply_queue.py`.

---

## 6. Orphans (phase 4)

A year in `suggestions.json` is keyed by OSM id, so it survives exactly as long
as that id does. Editing the map upstream is what ends it:

| edit in OSM | id | what happens to the year |
|---|---|---|
| move nodes, retag | preserved | nothing — safe |
| delete the building | gone | `orphans.json` reports it, `not_in_osm` |
| **redraw** (delete + retrace) | **new id** | reported as a deletion; the successor is bare |
| **split into N** | one id may survive, N−1 are new | **nothing is reported at all** |
| merge two | one id orphaned | reported |
| way → multipolygon | way *N* → relation *M* | reported as a deletion |

The split is the dangerous row, and it is the common one when the reason for
editing is bad geometry. A year that described one building now describes a
fragment of it, and the other fragments carry nothing — but no count changes, no
orphan is recorded, and no warning fires. The data does not go wrong; it goes
quiet, which is worse.

### Getting data new enough to compare

Geofabrik cuts `armenia-latest.osm.pbf` **once a day**, around 20:21 UTC, and
publishes some hours later — verified from the replication headers, where
sequence 3032 → 3035 spans three days. `fetch_buildings.py` makes it worse by
downloading only when the file is **absent**, so a cached extract sits at
whatever day it was fetched until somebody deletes it.

That is fine for rendering and useless for this loop: split a building, see the
pieces come back for review. Two tools close the gap, and they are not
alternatives — they do different things:

| | brings you to | cost |
|---|---|---|
| `pyosmium-up-to-date armenia.osm.pbf` | Geofabrik's latest daily cut | seconds, a few small diffs |
| `osm_live.py` | **live OSM, minutes old** | one Overpass query |

`osm_live.py` asks Overpass for an **augmented diff** since the PBF's own
replication timestamp and patches the last build with it. The augmented diff
rather than a plain `(changed:…)` query, for two reasons that both matter here:

- a plain query returns what exists *now*, so a **deleted** building is simply
  absent from the answer and cannot be told from one that never changed
- an augmented diff returns `<old>` **and** `<new>` geometry for every modified
  way — so a split's parent arrives carrying the footprint it had *before* the
  split, which is exactly what the successor scan needs

So orphans are found **geometrically**, by comparing two consecutive builds:
for every building in the previous build that carried a year, which buildings in
the new build sit inside its old footprint?

| successors | reading | what is emitted |
|---|---|---|
| 1, same id | untouched | nothing |
| 1, new id | redrawn | one orphan onto the successor |
| ≥ 2 | **split** | one orphan per successor |
| 0 | deleted, or moved out of scope | nothing — `orphans.json` already says so |

### What may be inherited

**Year fields only.** `name`, `addr_street` and `addr_number` are never
inherited, and that is the rule most worth stating: a split is precisely the
moment those diverge. One entrance becomes 42/1 and 42/3, and the school name
belongs to one of the three pieces rather than to all of them. Copying them
would spray a confident wrong address across two new buildings.

The year shape is copied verbatim — an exact year stays exact, a bound stays a
bound. Inheritance never sharpens a claim: three fragments of a building known
only as "after 1958" are each known only as "after 1958".

### What an orphan carries

- **`derived_from`** — the OSM id of the building the year came from. Required;
  it is the whole provenance of the claim, and it is a **column**, not a note,
  because `source_note` is purged after review (§4 Retention) and this must
  outlive that.
- **`source_kind` / `source_url`** — inherited from the parent, because the
  parent's evidence *is* the evidence. A legacy kind is accepted here (the
  parent may predate the §2 split) where the public wire would refuse it.
- **The evidence floor does not apply.** §2's floor exists so a stranger's claim
  is reviewable; an orphan's parent id is fully checkable, and the parent's note
  may already have been purged, so demanding one would be demanding something
  that no longer exists.

### Orphans never come off the wire

`/api/suggest` accepts `suggestion` and `report` and nothing else. An orphan is
written to the queue by `detect_splits.py`, which runs beside the build with the
same credentials as any other maintainer task. This is not a formality: an
orphan waives the evidence floor and may name any `derived_from` it likes, so
accepting one from the public would be a hole straight through §2.

`submission_id` is derived from parent id + successor id + the entry, so the
detector is idempotent — running it twice over the same split collides on the
primary key instead of queueing the same claim again.

---

## 7. Reviewer edits

Approve and Reject answer the wrong question when a claim is *nearly* right.
Three fragments of a split rarely all share one year; a report can name the
right building and the wrong decade. The reviewer holds the evidence on screen
and could simply fix it — before this, the only path was to reject, then
re-enter the value by hand in suggestions.json, which lost the link between the
submission and what it became.

So a decision may carry a replacement `entry`. It is validated **exactly** as a
submitted one — same year shapes, same field rules, same per-kind restrictions:

- a **report** may still only propose values for fields it disputes (§5); the
  reviewer cannot widen it into fields nobody checked
- an **orphan** may still only carry a year (§6)
- an empty result is refused — an entry edited down to nothing is a rejection,
  and should be sent as one

Additivity is **not** re-checked here and must not be: `apply_queue.py` re-tests
every field against the build at merge time, and it is still the only thing that
can. An edit changes what is claimed, never whether the claim is allowed.

### The claim stays attributable

`provenance.json` records `claim` — "what that submission actually proposed".
If a reviewer's edit overwrote it in place, that record would credit a stranger
with a year they never claimed, permanently and under ODbL. So the original is
kept:

- D1 keeps **`entry_original`**, written once, on the first edit only. A second
  edit does not overwrite it — the submitter's words are what it holds.
- `provenance.json` gains **`claim_original`** and `edited: true` on any applied
  submission whose entry a reviewer changed.

A reviewer correcting a contributor is a normal and good thing. Recording it as
though the contributor had been right the first time is not.
