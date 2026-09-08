// Validation shared by the queue endpoints.
//
// This is the JS half of docs/submission-schema.md. The Python half is
// submission.py, and THAT ONE WINS: it is the last gate before data reaches
// suggestions.json and the only one that can see the built dataset. Anything
// here is a fast reject at the edge, not a guarantee.
//
// In particular this cannot check the additive rule — it has no dataset, and
// shipping 76k ids to the edge is not worth it. apply_queue.py enforces it.

export const YEAR_MIN = 1, YEAR_MAX = 2030;
// What the evidence IS — not how it is attached. A plaque can arrive as a link
// to someone's photo of it or as a photo the submitter took; conflating the two
// was the mistake in the first version of this list. Mirrors submission.py.
export const SOURCE_KINDS = ['plaque', 'online', 'local'];
// what each kind must arrive with, or it is not reviewable
// a plaque asks for nothing — the claim names a physical thing on a specific
// building, which a reviewer can check. Mirrors EVIDENCE_FLOOR in submission.py.
export const EVIDENCE_FLOOR = { plaque: null, online: 'url', local: 'note' };
export const URL_MAX = 500;
export const TEXT_FIELDS = { name: 200, addr_street: 200, addr_number: 20 };
export const NOTE_MAX = 500;

// The two kinds of submission. `suggestion` fills empty fields (phase 2);
// `report` disputes something already displayed (phase 3), naming the fields in
// `before` with the values it saw and optionally proposing replacements in
// `after`. A disputed field with a proposed value is a correction, one without
// is a flag — per field, not per submission, so one report can do both. Mirrors
// KINDS in submission.py.
//
// `orphan` (phase 4) is the third kind: a year whose building stopped existing,
// re-proposed onto the footprints that replaced it. It is never constructed
// here — detect_splits.py writes orphans straight to the queue, because one
// waives the evidence floor and names its own `derived_from`, and accepting
// that off the wire would be a hole through §2. So this file knows the name (to
// review one) and validateSubmission refuses it (to receive one).
export const KINDS = ['suggestion', 'report', 'orphan'];
export const PUBLIC_KINDS = ['suggestion', 'report'];
export const REPORTABLE = ['year', 'name', 'addr_street', 'addr_number'];
export const YEAR_PROPS = ['year_built', 'year_est', 'year_min', 'year_max'];
const YEAR_KEYS = ['year', 'approx', 'year_min', 'year_max'];
const logicalField = key => (YEAR_KEYS.includes(key) ? 'year' : key);

export class SubmissionError extends Error {
  constructor(message, status = 400) { super(message); this.status = status; }
}

export const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });

function year(value, field) {
  if (value === null || value === undefined) return null;
  // typeof true === 'boolean', but Number(true) is 1 — reject before coercing
  if (typeof value === 'boolean') throw new SubmissionError(`${field} must be a number`);
  const n = Number(value);
  if (!Number.isInteger(n)) throw new SubmissionError(`${field} must be a number`);
  if (n < YEAR_MIN || n > YEAR_MAX)
    throw new SubmissionError(`${field} must be between ${YEAR_MIN} and ${YEAR_MAX}`);
  return n;
}

// The year shapes, collapsed to the keys suggestions.json stores: an exact
// year, or a bound with one end left open ("after 1958"), or — from era
// inference and older submissions, never from the form — a closed span.
// Mirrors parse_year_shape() in submission.py, docstring included; keep them in
// step, and test_parity.py proves they are.
function parseYearShape(after) {
  const y = year(after.year, 'year');
  const lo = year(after.year_min, 'year_min');
  const hi = year(after.year_max, 'year_max');

  // approx (~1965) still renders where it exists, but can no longer be written:
  // downgrading the request to an exact year would invent a precision instead
  if (after.approx)
    throw new SubmissionError('approximate years are no longer accepted — send an exact year, or a bound');
  if (lo !== null || hi !== null) {
    if (y !== null)
      throw new SubmissionError('a year and a bound are different shapes — send one');
    if (lo !== null && hi !== null) {
      if (lo > hi) throw new SubmissionError('range bounds are the wrong way round');
      // a zero-width span is just an exact year, and reads as vaguer than meant
      if (lo === hi) return { year: lo, approx: false };
      return { year_min: lo, year_max: hi };
    }
    // the absent key is the open end, and the open end is the claim
    return lo !== null ? { year_min: lo } : { year_max: hi };
  }
  if (y !== null) return { year: y, approx: false };
  return {};
}

function parseTextFields(after) {
  const out = {};
  for (const [field, cap] of Object.entries(TEXT_FIELDS)) {
    const value = after[field];
    if (value === null || value === undefined) continue;
    if (typeof value !== 'string') throw new SubmissionError(`${field} must be text`);
    const trimmed = value.trim();
    // blank means "not suggested" — there is no clear operation in this API
    if (!trimmed) continue;
    if (trimmed.length > cap)
      throw new SubmissionError(`${field} must be ${cap} characters or fewer`);
    out[field] = trimmed;
  }
  return out;
}

// A report's `before` → the disputed fields and the values they had. Mirrors
// parse_observed() in submission.py, docstring included: the year is an object
// of whichever YEAR_PROPS were set, because which one it is *is* the claim.
function parseObserved(before) {
  if (!before || typeof before !== 'object' || Array.isArray(before))
    throw new SubmissionError('before must be an object');
  const fields = Object.keys(before);
  if (!fields.length) throw new SubmissionError('a report has to say which field is wrong');

  const observed = {};
  for (const field of fields) {
    if (!REPORTABLE.includes(field))
      throw new SubmissionError(`${field} is not a field that can be reported`);
    const value = before[field];
    if (field === 'year') {
      if (value === null || value === undefined) { observed[field] = {}; continue; }
      if (typeof value !== 'object' || Array.isArray(value))
        throw new SubmissionError('before.year must be an object of year properties');
      const seen = {};
      for (const [prop, raw] of Object.entries(value)) {
        if (!YEAR_PROPS.includes(prop))
          throw new SubmissionError(`${prop} is not a year property`);
        const parsed = year(raw, prop);
        if (parsed !== null) seen[prop] = parsed;
      }
      observed[field] = seen;
    } else {
      if (value === null || value === undefined) { observed[field] = null; continue; }
      if (typeof value !== 'string') throw new SubmissionError(`before.${field} must be text`);
      observed[field] = value.trim();
    }
  }
  return observed;
}

// A submitted link, validated by SHAPE only — mirrors parse_source_url() in
// submission.py, including why: whether the page ANSWERS is a separate question,
// decided later and never used to refuse a submission (Wikipedia 403s a bare
// automated HEAD that a browser gets 200 for). The host rules also keep the
// reachability probe off private addresses.
function sourceUrl(value) {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string') throw new SubmissionError('source_url must be text');
  const url = value.trim();
  if (!url) return null;
  if (url.length > URL_MAX)
    throw new SubmissionError(`source_url must be ${URL_MAX} characters or fewer`);
  if (!url.startsWith('https://'))
    throw new SubmissionError('the link must start with https://');
  if (/\s/.test(url))
    throw new SubmissionError('that does not look like a web address');
  const authority = url.slice('https://'.length).split('/')[0];
  // user@host reads as one site and goes to another; a citation never needs it
  if (authority.includes('@'))
    throw new SubmissionError('the link must not contain a username');
  const host = authority.split(':')[0].toLowerCase();
  if (!host || !host.includes('.') || host.endsWith('.'))
    throw new SubmissionError('that does not look like a web address');
  if (host.split('.').every(part => /^\d+$/.test(part)))
    throw new SubmissionError('the link must point at a website, not an IP address');
  if (host === 'localhost' || host === 'localhost.localdomain' || host.endsWith('.local'))
    throw new SubmissionError('the link must point at a public website');
  return url;
}

export function validateSubmission(body) {
  if (!body || typeof body !== 'object')
    throw new SubmissionError('expected a JSON object');

  const osmId = String(body.id ?? '').trim();
  if (!/^\d{1,20}$/.test(osmId)) throw new SubmissionError('id must be an OSM id');

  // Number(null) === 0 and Number('') === 0, so a missing coordinate would
  // sail through Number.isFinite as a valid point in the Gulf of Guinea.
  // Caught by test_parity.py.
  const missing = v => v === null || v === undefined || v === '';
  if (missing(body.lng) || missing(body.lat))
    throw new SubmissionError('lng and lat are required');
  const lng = Number(body.lng), lat = Number(body.lat);
  if (!Number.isFinite(lng) || !Number.isFinite(lat))
    throw new SubmissionError('lng and lat are required');

  const kind = body.kind ?? 'suggestion';
  if (!PUBLIC_KINDS.includes(kind))
    throw new SubmissionError(`kind must be one of: ${PUBLIC_KINDS.join(', ')}`);

  const before = body.before && typeof body.before === 'object' ? body.before : {};
  const after = body.after && typeof body.after === 'object' ? body.after : {};
  const entry = { ...parseTextFields(after), ...parseYearShape(after) };

  let observed;
  if (kind === 'suggestion') {
    // Every `before` value must be empty. A filled one means the client rendered
    // an input for a field that already had a value — which the additive rule
    // forbids, so the client is broken or hostile, not the user mistaken, and it
    // is a client that should have sent a report instead.
    const filled = Object.keys(before).filter(k => before[k] !== null && before[k] !== '');
    if (filled.length)
      throw new SubmissionError(
        `these fields already have a value and cannot be suggested: ${filled.sort().join(', ')}`);
    if (!Object.keys(entry).length) throw new SubmissionError('nothing was suggested');
    observed = Object.fromEntries(Object.keys(before).map(k => [k, null]));
  } else {
    observed = parseObserved(body.before);
    // Proposing a value for a field the report does not dispute would be a
    // correction nobody described and nothing checked — the merge tests
    // staleness only against `before`.
    const undisputed = [...new Set(Object.keys(entry).map(logicalField))]
      .filter(f => !(f in observed)).sort();
    if (undisputed.length)
      throw new SubmissionError(
        `a report can only propose values for the fields it disputes: ${undisputed.join(', ')}`);
  }

  if (!SOURCE_KINDS.includes(body.source_kind))
    throw new SubmissionError(`source_kind must be one of: ${SOURCE_KINDS.join(', ')}`);

  const note = String(body.source_note ?? '').trim();
  if (note.length > NOTE_MAX)
    throw new SubmissionError(`source_note must be ${NOTE_MAX} characters or fewer`);
  const url = sourceUrl(body.source_url);

  // The evidence floor: a submission that cannot be checked at all is worse
  // than none — it costs a reviewer the same attention and can never be
  // resolved. A link satisfies a plaque or a published source; only a note can
  // carry "I grew up in this block".
  const needs = EVIDENCE_FLOOR[body.source_kind];
  if (needs === 'url' && !url)
    throw new SubmissionError('a published source needs a link to it');
  if (needs === 'note' && !note)
    throw new SubmissionError('please say how you know — a sentence is enough');

  return {
    id: osmId, lng, lat, kind,
    before: observed,
    entry, source_kind: body.source_kind, source_url: url, source_note: note,
  };
}

// A reviewer's replacement for a queued claim → the entry to store. Mirrors
// validate_review_edit() in submission.py; see docs/submission-schema.md §7.
//
// Validated exactly as a submitted entry, because it becomes one. The per-kind
// restrictions are the ones validateSubmission applies, for the same reasons: a
// reviewer may correct a claim, not convert it into a different kind of claim.
//
// Additivity is deliberately NOT re-checked here and must not be —
// apply_queue.py re-tests every field against the build at merge time and is
// still the only thing that can. An edit changes what is claimed, never whether
// the claim is allowed.
export function validateReviewEdit(kind, observed, after) {
  if (!after || typeof after !== 'object')
    throw new SubmissionError('after must be an object');

  const entry = { ...parseTextFields(after), ...parseYearShape(after) };
  if (!Object.keys(entry).length)
    // An entry edited down to nothing is a rejection and should be sent as one.
    // Storing it would file the submission as approved and then merge nothing.
    throw new SubmissionError('an edit cannot empty the claim — reject it instead');

  if (kind === 'report') {
    const undisputed = [...new Set(Object.keys(entry).map(logicalField))]
      .filter(f => !(f in (observed || {}))).sort();
    if (undisputed.length)
      throw new SubmissionError(
        `a report can only propose values for the fields it disputes: ${undisputed.join(', ')}`);
  } else if (kind === 'orphan') {
    const carried = [...new Set(Object.keys(entry).map(logicalField))]
      .filter(f => f !== 'year').sort();
    if (carried.length)
      throw new SubmissionError(`an orphan can only inherit a year, not: ${carried.join(', ')}`);
  }

  return entry;
}

// A stable, non-identifying handle for a submitter, so a run of
// plausible-but-wrong submissions can be reverted as a set. Additivity does not
// stop that attack — every such entry lands on a blank building and breaks no
// rule. SUBMITTER_SALT must be a persistent secret, or the grouping only lasts
// as long as one deploy.
export async function submitterHash(request, salt) {
  const ip = request.headers.get('CF-Connecting-IP') || '';
  const bytes = new TextEncoder().encode(`${salt}:${ip}`);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0'))
    .join('').slice(0, 16);
}
