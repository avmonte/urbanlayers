// POST /api/review — approve, reject or note one queued submission, optionally
// replacing what it claims.
//
// Approving only MARKS the row. The merge into suggestions.json is
// apply_queue.py's job, because that is the one place that can see the built
// dataset and therefore the one place additivity can actually be guaranteed.
// Doing it here would mean a second, weaker implementation of the rule.
//
// Gated on Cloudflare Access, like /api/queue, and refuses if Access is not
// configured rather than accepting decisions from anyone — see _access.js.
import { json, validateReviewEdit, SubmissionError } from './_shared.js';
import { requireAccess } from './_access.js';

export async function onRequestPost({ request, env }) {
  const denied = await requireAccess(request, env);
  if (denied) return denied;

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: 'malformed JSON' }, 400);
  }

  const submissionId = String(body.submission_id ?? '');
  const decision = body.decision;
  if (!submissionId) return json({ ok: false, error: 'submission_id is required' }, 400);
  // 'noted' is the outcome for a flag — a report that says a value is wrong
  // without proposing a right one. Nothing to merge, so approving it would file
  // it as done while the data stayed wrong; rejecting it would say the reporter
  // was mistaken. See docs/submission-schema.md §5.
  if (!['approved', 'rejected', 'noted'].includes(decision))
    return json({ ok: false, error: 'decision must be "approved", "rejected" or "noted"' }, 400);

  // ── the reviewer's edit ────────────────────────────────────────────────────
  //
  // Approve and Reject answer the wrong question when a claim is NEARLY right:
  // three fragments of a split rarely share one year, and a report can name the
  // right building and the wrong decade. Before this the only path was to
  // reject and re-key the value in the local editor, which severed the link
  // between a submission and what it became. See docs §7.
  const edit = body.entry;
  let entry = null;
  if (edit !== undefined && edit !== null) {
    if (decision !== 'approved')
      return json({ ok: false, error: 'only an approval can carry an edited entry' }, 400);

    // The row is needed before the edit can be judged: what a claim may propose
    // depends on its kind and, for a report, on the fields it disputed.
    const row = await env.DB.prepare(
      'SELECT kind, entry, before_json, status FROM submissions WHERE submission_id = ?'
    ).bind(submissionId).first();
    if (!row) return json({ ok: false, error: 'no such submission' }, 404);
    if (row.status !== 'pending')
      return json({ ok: false, error: `already ${row.status}` }, 409);

    let observed = {};
    try {
      observed = JSON.parse(row.before_json) || {};
    } catch {
      // a row written before this column was trusted; an edit can still be
      // judged for shape, only the report-scope check loses its reference
      observed = {};
    }

    try {
      entry = validateReviewEdit(row.kind || 'suggestion', observed, edit);
    } catch (err) {
      if (err instanceof SubmissionError) return json({ ok: false, error: err.message }, 400);
      throw err;
    }

    // An edit that changes nothing is not an edit. Saying so keeps
    // `entry_original` meaning "what the submitter actually claimed" rather
    // than "the last time somebody pressed the button".
    if (canonical(entry) === canonical(safeParse(row.entry))) entry = null;
  }

  // Guarded on status so a stale review page can't silently re-decide a row
  // someone already handled — the reviewer is told instead.
  //
  // entry_original is written ONCE, and only when the claim actually changed:
  // provenance.json records `claim` as "what that submission proposed", and an
  // edit that overwrote it in place would credit a stranger with a year they
  // never claimed — permanently, and under ODbL. See docs §7.
  const result = entry
    ? await env.DB.prepare(
        `UPDATE submissions
            SET status = ?, reviewed_at = ?,
                entry_original = COALESCE(entry_original, entry),
                entry = ?
          WHERE submission_id = ? AND status = 'pending'`
      ).bind(decision, Math.floor(Date.now() / 1000), JSON.stringify(entry), submissionId).run()
    : await env.DB.prepare(
        `UPDATE submissions SET status = ?, reviewed_at = ?
          WHERE submission_id = ? AND status = 'pending'`
      ).bind(decision, Math.floor(Date.now() / 1000), submissionId).run();

  if (!result.meta.changes) {
    const row = await env.DB.prepare(
      'SELECT status FROM submissions WHERE submission_id = ?'
    ).bind(submissionId).first();
    if (!row) return json({ ok: false, error: 'no such submission' }, 404);
    return json({ ok: false, error: `already ${row.status}` }, 409);
  }

  return json({ ok: true, submission_id: submissionId, status: decision, edited: !!entry });
}

const safeParse = text => { try { return JSON.parse(text) || {}; } catch { return {}; } };

// Key order is not meaning: {year, approx} and {approx, year} are the same
// claim, and comparing their raw JSON would record an edit nobody made.
const canonical = obj =>
  JSON.stringify(Object.fromEntries(Object.entries(obj).sort(([a], [b]) => (a < b ? -1 : 1))));
