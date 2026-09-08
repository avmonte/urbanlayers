// GET /api/queue — pending submissions, for the review UI.
//
// Returns source_note, which is free text a submitter wrote and can identify
// them. Everything here is gated on Cloudflare Access proving who is asking,
// and refuses outright if Access is not configured — see _access.js for why
// failing closed is the only safe default for this endpoint.
//
// The POLICY (who is allowed) lives in the Zero Trust dashboard; this file only
// insists the check happened. See docs/build-and-deploy.md.
import { json } from './_shared.js';
import { requireAccess } from './_access.js';

export async function onRequestGet({ request, env }) {
  const denied = await requireAccess(request, env);
  if (denied) return denied;

  const { results } = await env.DB.prepare(
    `SELECT submission_id, osm_id, lng, lat, kind, entry, entry_original, before_json,
            source_kind, source_url, link_status, source_note, submitter_hash,
            derived_from, submitted_at
       FROM submissions WHERE status = 'pending' ORDER BY submitted_at ASC`
  ).all();

  return json({
    ok: true,
    pending: results.map(r => ({
      submission_id: r.submission_id,
      id: r.osm_id, lng: r.lng, lat: r.lat,
      kind: r.kind,
      entry: JSON.parse(r.entry),
      before: JSON.parse(r.before_json),
      // the OSM id an orphan's year came from, so the review card can link to
      // the building that used to hold it — docs/submission-schema.md §6
      derived_from: r.derived_from,
      source_kind: r.source_kind,
      source_url: r.source_url,
      link_status: r.link_status,
      source_note: r.source_note,
      submitter_hash: r.submitter_hash,
      submitted_at: r.submitted_at,
    })),
  });
}
