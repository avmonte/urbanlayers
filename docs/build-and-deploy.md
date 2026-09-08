# Build and deploy — operational reference

**Point a new session at this file instead of letting it scan the repo.**
Everything needed to build, deploy, configure and drive the review queue is
here, with the flags spelled out. Commands come first, then the configuration
that lives in the Cloudflare dashboard rather than in this repo.

**No secrets in this file.** Names and shapes only.

Live site: **https://urbanlayers.xyz**

Your own Cloudflare resource names go in the environment, not in this file — a
fork has its own, and a project's `*.pages.dev` origin is the URL that reaches a
site without passing through its custom domain, so it is not something to
publish. `build_public.sh` reads both:

```bash
export D1_DATABASE=<your-d1-database>     # the review queue
export PAGES_PROJECT=<your-pages-project> # what the site deploys to
```

Every `wrangler` command below is written against those.

---

## The normal case

```bash
./build_public.sh                                                    # apply queue → data → tiles → public/
npx wrangler pages deploy public/ --project-name="$PAGES_PROJECT" --commit-dirty=true
git add data/source/ && git commit    # suggestions, provenance
```

**The commit is not optional.** `build_public.sh` writes `suggestions.json` and
`provenance.json` *and then tells D1 those rows are applied*. Skip the commit and
the contribution is lost from both sides — D1 thinks it is done, the repo never
recorded it. The script says `⚠ COMMIT THEM` when this applies.

Verify what actually went live (not the per-deploy hash URL — see Gotchas):

```bash
curl -s https://urbanlayers.xyz/stats.json
```

---

## `./build_public.sh`

| flag | effect | when |
|---|---|---|
| *(none)* | apply approved queue → rebuild data → tiles → assemble `public/` | the normal build |
| `--no-apply` | everything, but do not touch the review queue | CI, a second checkout, reproducing an earlier state — anywhere that cannot commit the result |
| `--ui-only` | copy UI only, reuse existing tiles | anything under `web/`. Implies `--no-apply` (no dataset is rebuilt, so an applied row could not reach the tiles) |
| `--water` | also re-extract `water.geojson` | only when Yerevan Lake or the Hrazdan changed upstream |

Takes ~2 minutes with tiles, seconds with `--ui-only`. Needs `tippecanoe` on PATH
for anything that builds tiles.

It also copies `functions/` into `public/`, so the API deploys with the site. A
deploy without it produces a working map whose suggest button 404s.

## Data source — live OSM by default

`pipeline/fetch_buildings.py` (invoked by the build) reads **live OSM via Overpass**,
current to the minute.

| flag | effect |
|---|---|
| `--source overpass` | **default.** Live OSM, ~10 s, ~57 MB, cached to `overpass_buildings.json` |
| `--source pbf` | Geofabrik's daily extract. **Cut once a day ~20:21 UTC and published hours later**, so an edit made today cannot appear in a pbf build today. Fallback only |
| `--no-refresh` | rebuild from the cached response, no network. This is what makes a build reproducible |
| `--no-infer` | drop the khrushchevka/brezhnevka era spans |
| `--out-dir DIR` | where to write `buildings.geojson` / `stats.json` / `needs_data.csv` (default `build/`) |

If Overpass fails (504s happen) the build **falls back to the cache loudly** and
carries on — the map is stale, not broken. Re-run later for fresh data.

Do not run the 57 MB query in a loop; it is a shared public service. One fetch
per build is fine, per commit is not.

Era spans come from `inferred_buildings.json`, which is tracked. It is written
by the classifier in `exp/research/`, which is local to a maintainer's machine
and not in this repository; `fetch_buildings.py` only reads its output, so a
build needs the JSON and never the classifier.

## `pipeline/apply_queue.py` — the merge

Runs inside `build_public.sh`; use it directly to preview or to undo.

| flag | effect |
|---|---|
| *(none)* | **dry run.** Prints what would be applied, writes nothing |
| `--apply` | actually write |
| `--queue PATH` | `queue.json` from `server.py`, or a `wrangler d1 execute --json` export (default `queue.json`) |
| `--geojson PATH` | the openness oracle — the built dataset it checks fields against (default `build/buildings.geojson`) |
| `--keep-conflicts` | leave irreconcilable claims queued instead of overwriting. **Default is to overwrite** — the newer claim wins, the replaced value goes to `provenance.json`, `--revert` puts it back |
| `--revert SUBMISSION_ID --apply` | undo one applied submission |
| `--revert-submitter HASH --apply` | undo a whole run — the safety net for a bad batch |
| `--applied-ids PATH` | write applied ids, for a caller that marks D1 afterwards |

**The dry run cannot show conflicts.** `write_entry` only runs under `--apply`,
so conflicts surface only on a real write. To preview one safely, copy
`suggestions.json` + `provenance.json` to a temp dir and `--apply` there.

**Which oracle matters.** It must be the build the submitter was looking at.
There is now only one — `build/buildings.geojson`, which the editor and the
public build share — and it is the default, so a manual run needs no `--geojson`
at all. Pass one only to check against a variant built into another `--out-dir`.

Exception: a submission on a way created *since the last build* is not in the
oracle and gets skipped as "not in the build". Apply those against a live-patched
set — see `pipeline/osm_live.py` below.

---

## The review queue (D1)

The queue lives in D1; `suggestions.json` lives in this repo. Approving in the
browser only marks the row — nothing reaches the map until a merge runs.

Review in the browser at `/review.html` (behind Cloudflare Access). Cards are
editable — approving can carry a corrected `entry`; the submitter's original is
kept in `entry_original` / `claim_original`.

`status` values: `pending` → `approved` / `rejected` / `noted` → `applied`.
`noted` is for a flag (a report proposing no value).

```bash
# what is waiting
npx wrangler d1 execute "$D1_DATABASE" --remote --json \
  --command "SELECT status,kind,COUNT(*) n FROM submissions GROUP BY status,kind"

# approve everything pending
npx wrangler d1 execute "$D1_DATABASE" --remote \
  --command "UPDATE submissions SET status='approved', reviewed_at=$(date +%s) WHERE status='pending'"
```

### Merging by hand

`build_public.sh` does this for you — it pulls the approved rows, runs
`apply_queue.py --apply`, and marks them applied in D1 with their notes purged,
all before it builds the dataset. It never fails the build over this: no network
or no wrangler login means a loud warning and a build from whatever
`suggestions.json` already holds.

The manual version is still the right tool when you want to see what would land
before it lands:

```bash
# 1. pull what you approved
npx wrangler d1 execute "$D1_DATABASE" --remote --json \
  --command "SELECT * FROM submissions WHERE status='approved'" > queue_export.json

# 2. see what it would do (reads the export directly; writes nothing)
python3 pipeline/apply_queue.py --queue data/local/queue_export.json

# 3. write it — re-checks that every field is STILL empty before applying
python3 pipeline/apply_queue.py --queue data/local/queue_export.json --apply
```

Step 3 prints the `wrangler` command to mark those rows applied and purge their
notes. Run it, or they will be applied again on the next pull. Then rebuild and
deploy as usual to put them on the map.

### Retention and stale rows

`source_note` is required at submit and must not outlive review (ODbL
share-alike would carry it into every downstream copy — see
`docs/submission-schema.md` §4). `apply_queue.py` drops it on merge. Purge
reviewed rows periodically:

```bash
npx wrangler d1 execute "$D1_DATABASE" --remote --command \
  "UPDATE submissions SET source_note = NULL WHERE status != 'pending'"
```

**Stale `approved` rows.** Rows already applied but never marked stay `approved`
and get re-pulled on every build. Harmless — `provenance.json` refuses to
re-apply them — but to clear:

```bash
npx wrangler d1 execute "$D1_DATABASE" --remote --command \
  "UPDATE submissions SET status='applied', source_note=NULL WHERE status='approved'"
```

---

## Split detection (`pipeline/detect_splits.py`)

Finds years whose building was split or redrawn in OSM, and re-proposes them onto
the successors as `kind: 'orphan'` rows. See `docs/submission-schema.md` §6.

```bash
python3 pipeline/detect_splits.py --old build/buildings.geojson.prev --new build/buildings.geojson
python3 pipeline/detect_splits.py --old ... --new ... --write /tmp/orphans.sql
npx wrangler d1 execute "$D1_DATABASE" --remote --file=/tmp/orphans.sql
```

| flag | effect |
|---|---|
| `--old` / `--new` | the two builds to compare |
| `--write PATH` | emit queue INSERTs (idempotent — deterministic ids, `INSERT OR IGNORE`) |
| `--local` | queue into `queue.json` for the offline loop |

**Keep a copy of the previous build** (`cp build/buildings.geojson
build/buildings.geojson.prev`) before rebuilding, or there is nothing to diff
against.

It proposes; it never applies. Geometry cannot distinguish a genuine split from
an outline that was covering two buildings and got corrected — the same nodes,
the same coordinates, the same tiling — so it deliberately uses no tag or
address heuristic and a person decides. Expect false positives and reject them.

## `pipeline/osm_live.py` — patch a build to live OSM

Mostly superseded now the default source is Overpass. Still the way to get a
**pre-edit footprint** (via Overpass augmented diff) without having kept the old
build, and the way to build an oracle containing ways created since the last
build.

```bash
python3 pipeline/osm_live.py                                   # dry run: what changed
python3 pipeline/osm_live.py --write build/live.geojson        # last build, patched to live
python3 pipeline/osm_live.py --old-shapes build/old.geojson    # pre-edit footprints
```

`--since` overrides the timestamp, `--cache PATH` reuses a saved response,
`--prev PATH` picks the build to patch.

---

## Tests

No framework, no `PYTHONPATH`, and the working directory does not matter:

```bash
for f in tests/*.py; do python3 "$f"; done
```

Each test puts `pipeline/` on `sys.path` itself and resolves everything through
`paths.py`, so any of them runs from anywhere. This used to be a real trap —
`test_parity.py` had to run from the repo root while the rest had to run from
`tests/` — and it was a symptom of the bare-filename constants, not of the tests.

Run `test_parity.py` after touching **any** of `submission.py`,
`functions/api/_shared.js`, or `docs/submission-schema.md` — it proves the Python
and JS validators still agree (68 submission + 14 edit cases).

---

# Configuration

Everything the project needs that does **not** live in this repo. Without this
section, rebuilding from a fresh clone is archaeology: the bindings below are
invisible in the code, and a missing one fails at runtime rather than at build.

## Bindings

Set under **Pages → your project → Settings → Functions**. All are required for
`/api/suggest`; the code degrades rather than crashes when the optional ones are
absent, which is what makes local development possible.

| Name | Type | Required | What breaks without it |
|---|---|---|---|
| `DB` | D1 database | **yes** | every endpoint 500s |
| `RATE_LIMIT` | KV namespace | no | no per-IP limit; moderation is the only defence |
| `TURNSTILE_SECRET` | secret | no | the challenge is skipped entirely |
| `SUBMITTER_SALT` | secret | **yes in production** | submitter grouping is not stable, so `apply_queue.py --revert-submitter` cannot find a run |
| `ACCESS_TEAM_DOMAIN` | plain text | **yes** | `/api/queue` and `/api/review` refuse with 503 — the review UI is offline |
| `ACCESS_AUD` | plain text | **yes** | same; and without it any Access app in your account would open the queue |

`SUBMITTER_SALT` must be a **persistent** random string. Rotating it re-anonymises
every future submission and orphans the grouping of past ones — so a bad run
submitted before a rotation can no longer be reverted as a set. Generate once:

```bash
openssl rand -hex 32
npx wrangler pages secret put SUBMITTER_SALT --project-name="$PAGES_PROJECT"
```

## D1

```bash
npx wrangler d1 create "$D1_DATABASE"
npx wrangler d1 execute "$D1_DATABASE" --remote --file=schema.sql
```

Then bind it as `DB`.

## Turnstile

Create a widget at **Turnstile → Add site**. It gives two keys:

- **site key** — public, goes in the HTML. Baked in by `build_public.sh` from
  `TURNSTILE_SITE_KEY` in the environment; safe to commit if you prefer.
- **secret key** — the `TURNSTILE_SECRET` binding above. Never in the repo.

## Access (the review UI)

`/review.html`, `/api/queue` and `/api/review` expose the queue — including
`source_note`, free text a submitter wrote that can identify them — and let the
reader approve or reject. Two things guard them, and you need both:

**1. The Access policy** decides who may in. Zero Trust → Access → Applications:

- a self-hosted application covering `/review*`, `/api/queue` and `/api/review`
  on **both** your custom domain and the `*.pages.dev` origin — a policy on one
  hostname does not cover the other, and the origin answers the same paths
- policy: allow → emails → your address
- free for up to 50 users

**2. The Functions verify it.** `functions/api/_access.js` checks the signed JWT
Access attaches to every request that passes it — signature against your team's
keys, plus issuer, expiry and audience. Set two variables from the application's
**Overview** tab:

```
ACCESS_TEAM_DOMAIN   yourteam.cloudflareaccess.com
ACCESS_AUD           the Application Audience (AUD) tag
```

`ACCESS_AUD` is per-application and is not optional: without it a valid token for
*any* Access application in your account would open the review queue.

**These endpoints fail closed.** With the variables unset they answer 503 and
serve nothing. That is deliberate — an unprotected review queue should be an
outage you notice, not a leak you don't. If the review UI ever says
"review is not configured", this is why.

**Verify after any change** by opening `/api/queue` in a private window. It must
challenge you, never return JSON.

> Approving is not publishing. It flips a database row; nothing reaches the map
> until you run `apply_queue.py` yourself. So even a total failure here is queue
> vandalism and a note leak — bad, but not map vandalism.

---

## Gotchas

These each cost a broken deploy or an hour. None are obvious.

**Deploying**

1. **Every deploy mints an immutable `<hash>.<project>.pages.dev`** that serves
   that build forever. Only the bare project URL follows the latest deploy.
   Check the live site, never the hash URL, before concluding a fix did not
   work. Hours were once lost reloading a frozen copy of a broken build.
2. **`TURNSTILE_SITE_KEY` is unset**, so `public/index.html` ships the literal
   `__TURNSTILE_SITE_KEY__` placeholder and the bot challenge does not render.
   The live site has always been this way; moderation is the only defence. Set
   the env var and rebuild to turn it on.
3. **There is no privileged write path.** The local editor is gone: every
   change reaches `data/source/suggestions.json` through the review queue and
   `apply_queue.py`, maintainer included. `web/index.html` is the site itself,
   copied to `public/` under the same name — no rename on the way out.

**The Pages platform**

4. **Cloudflare Pages ignores `Range` requests entirely.** Verified: a 7-byte
   range request on a 17MB file returned the whole 17MB, `200`, no
   `accept-ranges` — even after caching. This makes **PMTiles unusable on
   Pages**, since the format is built on range requests. (GitHub Pages *does*
   return proper `206`s.) Hence individual tile files.
5. **Cloudflare Pages ignores `Content-Encoding` in `_headers`.** It manages
   compression itself. tippecanoe gzips tiles by default, so tiles arrived as
   gzip bytes labelled `application/x-protobuf`, MapLibre failed to parse them,
   and the map rendered empty **with no error**. Hence
   `--no-tile-compression` — load-bearing, not a tuning choice.

**Tiles and MapLibre**

6. **`new URL('tiles/{z}/{x}/{y}.pbf', base)` percent-encodes the braces** into
   `%7Bz%7D`, which MapLibre never substitutes. Resolve the directory first,
   then append the template.
7. **`setFeatureState` needs `sourceLayer` for vector sources** and must *not*
   have it for GeoJSON. See `featureRef()`.
8. **`map.on('error')` is the only way to see tile failures** — they don't
   throw. There's an on-page red error box as well, since Safari hides its
   console.

Where the two data paths diverge, all flagged in comments:

| | GeoJSON | Vector tiles |
|---|---|---|
| layers | — | need `source-layer` |
| feature state | `{source, id}` | `{source, sourceLayer, id}` |
| feature ids | `generateId: true` | `promoteId: 'id'` (stable across tiles) |
| live edits | `setData()` | impossible — tiles are prebuilt |

**The repo**

9. **`git check-ignore` exits 0 if *any* path matches**, so it will happily
   report success while one of the paths you passed is not ignored at all. It
   also reports nothing for a **tracked** file, whatever `.gitignore` says —
   ignore rules only ever apply to untracked paths.
10. **`.gitignore` has no trailing comments.** `public/ # note` is a literal
    pattern and silently ignores nothing.
11. Which directory a file sits in says whether it survives a delete.
    `data/source/` is irreplaceable and tracked — commit it after any build that
    applied. `data/cache/` is re-downloadable, `build/` and `public/` are
    regenerated, `data/local/` is dev state; all four are ignored.

## Local preview

```bash
python3 pipeline/server.py 8003  # editor → localhost:8003/  ·  site → /public/
python3 pipeline/apply_queue.py  # dry run against data/local/queue.json
```

`server.py` serves `web/` as `/` and routes the data paths to where they
actually live — `buildings.geojson` and `stats.json` from `build/`,
`water.geojson` from `data/source/` — so the URLs the browser sees are the same
ones the deployed site serves. The whole loop runs with no Cloudflare account at
all: it serves the same three API routes over `data/local/queue.json`, so
submit → review → approve works offline. Always check `localhost:8003/public/` before deploying — same code
path, much faster loop.

`npx wrangler pages dev public/` runs the real Functions when you need to test
Turnstile or D1 specifically. Prefer `server.py` for everything else: it is
faster and it does not consume a deploy.

## Still to do

- [ ] point the GoDaddy domain at Pages (apex needs Cloudflare nameservers —
      GoDaddy has no CNAME flattening; copy MX records first if email is on it)
- [ ] decide contributor credit before launch — retroactively thanking
      anonymous submitters is impossible (Phase 2 item #14)
