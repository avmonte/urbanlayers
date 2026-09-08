// POST /api/suggest — queue one public suggestion.
//
// The local equivalent is handle_public_suggest in server.py, which writes the
// same records to queue.json so the whole submit → review → approve loop runs
// offline. Keep the two in step; server.py is what you will actually develop
// against, because every `wrangler pages deploy` mints an immutable hash URL
// and debugging against those cost this project hours once already.
//
// Nothing here touches suggestions.json. A public submission only becomes data
// through apply_queue.py, which is the one place the additive rule can be
// enforced (it needs the built dataset; the edge has none).
import { validateSubmission, SubmissionError, submitterHash, json } from './_shared.js';

// Generous on purpose. Yerevan has plenty of shared NATs, and a block that
// catches a whole café is worse than the queue noise it prevents — everything
// is moderated anyway, so the failure mode of being too loose is a slightly
// longer review, while too tight silently loses real contributors.
const RATE_LIMIT = 20;
const RATE_WINDOW_SECONDS = 3600;

// Does the submitted link answer? Recorded on the row for the reviewer, and
// NEVER used to refuse a submission: Wikipedia returns 403 to a bare automated
// HEAD that a browser gets 200 for, so a hard gate here would reject real
// sources and blame the contributor for someone else's bot policy.
//
// Safe to run only because parse_source_url/sourceUrl already refused IP
// literals, localhost and non-https — fetching a user-supplied URL is otherwise
// how a public form becomes a probe of a private network. redirect:'manual' so
// a 302 to somewhere interesting is reported, not followed.
async function probeLink(url) {
  if (!url) return null;
  try {
    const res = await fetch(url, {
      method: 'HEAD',
      redirect: 'manual',
      signal: AbortSignal.timeout(4000),
      // some sites answer a bare fetch with 403; identify ourselves honestly
      headers: { 'User-Agent': 'UrbanLayersBot/1.0 (+https://urbanlayers.xyz)' },
    });
    return `http ${res.status}`;
  } catch (err) {
    // a timeout or a DNS failure is information too — it just is not a verdict
    return `no response (${(err && err.name) || 'error'})`;
  }
}

async function verifyTurnstile(token, secret, ip) {
  const body = new FormData();
  body.append('secret', secret);
  body.append('response', token || '');
  if (ip) body.append('remoteip', ip);
  const res = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify',
                          { method: 'POST', body });
  const data = await res.json();
  return data.success === true;
}

export async function onRequestPost({ request, env }) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: 'malformed JSON' }, 400);
  }

  // Honeypot: the field is hidden, so a real form leaves it empty. Answer
  // exactly as if it worked. Telling a submitter they were filtered turns this
  // endpoint into an oracle for tuning past the filter.
  if (String(body.website ?? '').trim()) return json({ ok: true });

  const ip = request.headers.get('CF-Connecting-IP') || '';

  // Turnstile failure is the one rejection an honest client can hit and
  // recover from, so unlike spam it gets a real status and a real message.
  if (env.TURNSTILE_SECRET) {
    const passed = await verifyTurnstile(body.turnstile_token, env.TURNSTILE_SECRET, ip);
    if (!passed) return json({ ok: false, error: 'verification failed — please try again' }, 403);
  }

  // Rate limit AFTER Turnstile, so a flood of unverified requests can't burn
  // through an honest submitter's allowance from the same NAT.
  if (env.RATE_LIMIT && ip) {
    const key = `rl:${ip}`;
    const count = Number(await env.RATE_LIMIT.get(key)) || 0;
    if (count >= RATE_LIMIT) return json({ ok: true });   // silent drop, see above
    await env.RATE_LIMIT.put(key, String(count + 1), { expirationTtl: RATE_WINDOW_SECONDS });
  }

  let entry;
  try {
    entry = validateSubmission(body);
  } catch (err) {
    if (err instanceof SubmissionError) return json({ ok: false, error: err.message }, err.status);
    throw err;
  }

  const submissionId = crypto.randomUUID().replace(/-/g, '').slice(0, 12);
  const linkStatus = await probeLink(entry.source_url);
  await env.DB.prepare(
    `INSERT INTO submissions (submission_id, osm_id, lng, lat, kind, entry, before_json,
                              source_kind, source_url, link_status, source_note,
                              submitter_hash, status, submitted_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)`
  ).bind(
    submissionId, entry.id, entry.lng, entry.lat, entry.kind,
    JSON.stringify(entry.entry), JSON.stringify(entry.before),
    entry.source_kind, entry.source_url, linkStatus, entry.source_note,
    await submitterHash(request, env.SUBMITTER_SALT || ''),
    Math.floor(Date.now() / 1000),
  ).run();

  return json({ ok: true, submission_id: submissionId });
}
