// Cloudflare Access enforcement for the moderation endpoints.
//
// The policy in the Zero Trust dashboard is what decides WHO may in; this file
// only insists that the decision actually happened. That distinction matters:
// without it these endpoints FAIL OPEN — no policy, or a policy someone removes
// later, and /api/queue quietly serves the whole queue (source notes included)
// to anyone who finds the URL.
//
// So the rule here is the opposite: no verifiable Access identity, no answer.
// A misconfiguration takes the review UI offline, which is loud and harmless.
// The alternative is silent and is not.
//
// Access puts a signed JWT on every request that passes it, in the
// Cf-Access-Jwt-Assertion header (and the CF_Authorization cookie). It is signed
// by your team's keys, so it cannot be forged by sending the header yourself.

const CERT_TTL_MS = 60 * 60 * 1000;     // the signing keys rotate rarely
let certCache = { at: 0, keys: null, team: null };

const b64urlToBytes = s => {
  const b64 = s.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(s.length / 4) * 4, '=');
  return Uint8Array.from(atob(b64), c => c.charCodeAt(0));
};

async function teamKeys(teamDomain) {
  const fresh = certCache.keys && certCache.team === teamDomain
    && Date.now() - certCache.at < CERT_TTL_MS;
  if (fresh) return certCache.keys;

  const res = await fetch(`https://${teamDomain}/cdn-cgi/access/certs`);
  if (!res.ok) throw new Error(`could not fetch Access certs (HTTP ${res.status})`);
  const { keys } = await res.json();
  certCache = { at: Date.now(), keys, team: teamDomain };
  return keys;
}

async function verifyJWT(token, teamDomain, audience) {
  const parts = token.split('.');
  if (parts.length !== 3) throw new Error('malformed token');
  const [rawHeader, rawPayload, rawSignature] = parts;

  const header = JSON.parse(new TextDecoder().decode(b64urlToBytes(rawHeader)));
  if (header.alg !== 'RS256') throw new Error(`unexpected algorithm ${header.alg}`);

  const jwk = (await teamKeys(teamDomain)).find(k => k.kid === header.kid);
  if (!jwk) throw new Error('token signed by an unknown key');

  const key = await crypto.subtle.importKey(
    'jwk', jwk, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
  const signed = new TextEncoder().encode(`${rawHeader}.${rawPayload}`);
  if (!await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, b64urlToBytes(rawSignature), signed))
    throw new Error('bad signature');

  const payload = JSON.parse(new TextDecoder().decode(b64urlToBytes(rawPayload)));
  const now = Math.floor(Date.now() / 1000);
  if (payload.exp && payload.exp < now) throw new Error('token expired');
  if (payload.nbf && payload.nbf > now) throw new Error('token not yet valid');
  if (payload.iss !== `https://${teamDomain}`) throw new Error('wrong issuer');
  // The audience tag is per-application. Without this check a valid token for
  // ANY app in your Access account would open the review queue.
  const aud = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!aud.includes(audience)) throw new Error('token is for a different application');

  return payload;
}

/** null when the caller is authorised; a Response to return when they are not. */
export async function requireAccess(request, env) {
  const teamDomain = env.ACCESS_TEAM_DOMAIN;
  const audience = env.ACCESS_AUD;

  // Fail CLOSED when unconfigured. This is the whole point of the file: an
  // unprotected review queue must be an outage, not a silent leak.
  if (!teamDomain || !audience) {
    return new Response(JSON.stringify({
      ok: false,
      error: 'review is not configured: set ACCESS_TEAM_DOMAIN and ACCESS_AUD, '
           + 'and put a Cloudflare Access policy on /review* and /api/*. '
           + 'See docs/build-and-deploy.md.',
    }), { status: 503, headers: { 'Content-Type': 'application/json' } });
  }

  const token = request.headers.get('Cf-Access-Jwt-Assertion')
    || (request.headers.get('Cookie') || '').match(/CF_Authorization=([^;]+)/)?.[1];
  if (!token) {
    return new Response(JSON.stringify({ ok: false, error: 'not signed in' }),
                        { status: 401, headers: { 'Content-Type': 'application/json' } });
  }

  try {
    await verifyJWT(token, teamDomain, audience);
    return null;
  } catch (err) {
    return new Response(JSON.stringify({ ok: false, error: `access denied: ${err.message}` }),
                        { status: 403, headers: { 'Content-Type': 'application/json' } });
  }
}
