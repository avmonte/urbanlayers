#!/usr/bin/env bash
#
# Build the deployable public site into public/.
#
#   ./build_public.sh              full build — apply approvals, data, tiles, UI
#   ./build_public.sh --no-apply   full build, but leave the review queue alone
#   ./build_public.sh --ui-only    UI only, reusing the tiles already in public/
#   ./build_public.sh --water      also re-extract water.geojson from the PBF
#   ./build_public.sh --help
#
# The public build differs from a plain local build in one way:
#
#   vector tiles    32MB of GeoJSON becomes ~2,100 small z/x/y tiles, so a
#                   visitor downloads only the few KB covering their current view
#                   rather than the whole dataset.
#
# It used to differ in a second: --no-infer held the khrushchevka/brezhnevka
# estimates back, because publishing a guess as if it were a fact is how a map
# like this loses trust. They ship now, but not as facts — an era call is
# published as the span its construction programme ran for (1958–1972,
# 1968–1991), never as a single year the map would render like a date. See
# classify_year in fetch_buildings.py for the shapes a year comes in, and
# ERA_RANGE in exp/research/infer.py (local only, not in this repository) for
# where the spans come from.
#
# Everything here is regenerated from tracked inputs, so public/ is gitignored.
# Nothing here assumes a laptop — given tippecanoe and a wrangler login it runs
# the same anywhere. (.github/workflows/tests.yml runs the test suite, not this:
# a full build downloads an extract and writes back to data/source/.)

set -euo pipefail

BUILD_DIR=build           # intermediates — the GeoJSON tippecanoe consumes
OUT_DIR=public            # what actually gets deployed
WATER_FILE=data/source/water.geojson   # tracked — see "Water" below

BUILD_TILES=1
REBUILD_WATER=0
APPLY_QUEUE=1

# Your own Cloudflare resource names — the D1 database holding the review queue,
# and the Pages project the site deploys to. Deliberately not hard-coded: a fork
# has its own, and naming someone else's in a public repository hands out their
# *.pages.dev origin, which is the URL that reaches the site without going
# through their custom domain. Set them in the environment (a shell profile, a
# .envrc, CI secrets) or pass them inline:
#
#   D1_DATABASE=my-queue PAGES_PROJECT=my-site ./build_public.sh
#
# Only the review-queue step needs D1_DATABASE; without it the build still makes
# the whole site and says why it skipped.
D1_DATABASE="${D1_DATABASE:-}"
PAGES_PROJECT="${PAGES_PROJECT:-}"

# Spelled out rather than sed'd back out of the header comment above: a line
# range there silently starts printing unrelated prose the moment anyone edits it.
usage() {
  cat <<'USAGE'
Build the deployable public site into public/.

  ./build_public.sh              full build — apply approvals, data, tiles, UI
  ./build_public.sh --no-apply   full build, but leave the review queue alone
  ./build_public.sh --ui-only    UI only, reusing the tiles already in public/
  ./build_public.sh --water      also re-extract water.geojson from the PBF
  ./build_public.sh --help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    # A UI change — map.js, map.css, index.html — cannot alter a single tile:
    # tiles come from buildings.geojson and nothing else. Rebuilding them to
    # ship a CSS tweak costs a PBF parse plus a full tippecanoe run for a
    # byte-identical result, so this skips straight to the copy step.
    --ui-only) BUILD_TILES=0 ;;
    # Water is cached (see below); this is how you refresh it.
    --water)   REBUILD_WATER=1 ;;
    # Build exactly what suggestions.json already holds. For rebuilding after a
    # UI or pipeline change, for reproducing a build, and for any machine that
    # cannot commit the files the merge writes — see the block below.
    --no-apply) APPLY_QUEUE=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
  shift
done

if [ "$BUILD_TILES" = 1 ]; then
  command -v tippecanoe >/dev/null || {
    echo "tippecanoe not found — brew install tippecanoe" >&2
    exit 1
  }
fi

# ── Water ────────────────────────────────────────────────────────────────────
#
# water.geojson is tracked in git and NOT rebuilt by default.
#
# It is two named features — Yerevan Lake and the Hrazdan (see the allowlist in
# fetch_water.py) — and extracting them means a full pass over a 53MB PBF, which
# is most of a minute to produce a 23KB file whose contents only change when
# somebody edits one of those two objects in OSM. That is not a build step, it's
# an occasional refresh, so the output is committed like any other small input
# and rebuilt on demand with --water.
if [ "$REBUILD_WATER" = 1 ] || [ ! -f "$WATER_FILE" ]; then
  [ -f "$WATER_FILE" ] || echo "▸ $WATER_FILE missing — extracting it"
  echo "▸ Extracting water…"
  python3 fetch_water.py
  echo
fi

# ── Approved suggestions ─────────────────────────────────────────────────────
#
# Pull what has been approved in the review UI and merge it before the dataset is
# built, so one command takes a contribution from "approved" to "on the map".
# Doing it by hand is three commands ("Merging by hand" in
# docs/build-and-deploy.md), and forgetting the
# third one is how fifteen rows sat in D1 marked `approved` long after they had
# been applied, getting re-pulled on every merge for weeks.
#
# THIS STEP WRITES TRACKED FILES: apply_queue.py updates suggestions.json and
# provenance.json, and then D1 is told those rows are done. Those two facts have
# to stay in sync, so COMMIT THE RESULT. On a machine that cannot commit — CI,
# someone else's checkout — pass --no-apply, or the D1 rows end up marked applied
# against a merge nobody kept, and the suggestion is lost from both sides.
#
# Never fatal. A laptop with no network, no wrangler or no Cloudflare login still
# builds the site from whatever suggestions.json already holds; it just says so
# loudly, because a silent skip here means shipping without somebody's approved
# contribution and never knowing.
if [ "$APPLY_QUEUE" = 1 ] && [ "$BUILD_TILES" = 0 ]; then
  echo "▸ --ui-only: skipping the review queue (no dataset is rebuilt, so an"
  echo "  applied suggestion could not reach the tiles anyway)"
  echo
  APPLY_QUEUE=0
fi

if [ "$APPLY_QUEUE" = 1 ] && [ -z "$D1_DATABASE" ]; then
  echo "▸ D1_DATABASE is not set — skipping the review queue. The site still"
  echo "  builds from whatever suggestions.json already holds; set D1_DATABASE"
  echo "  to your database name to pull approvals. See docs/build-and-deploy.md."
  echo
  APPLY_QUEUE=0
fi

if [ "$APPLY_QUEUE" = 1 ]; then
  echo "▸ Applying approved suggestions…"
  APPLIED_IDS=$(mktemp)
  QUEUE_ERR=$(mktemp)
  QUEUE_TMP=$(mktemp)
  # shellcheck disable=SC2064  # expand the paths now, not at trap time
  trap "rm -f '$APPLIED_IDS' '$QUEUE_ERR' '$QUEUE_TMP'" EXIT

  QUEUE_SQL="SELECT * FROM submissions WHERE status='approved'"

  # Two things make this more than one command.
  #
  # `wrangler --json` reports API failures as JSON on STDOUT, not stderr — so a
  # failed pull writes an {"error": ...} object straight over the queue export
  # and says nothing on the channel you would look at. Hence a temp file that is
  # only moved into place once it parses as a D1 result set (a list), and hence
  # showing the file, not just stderr, when it does not.
  #
  # And the failure this actually caught in the wild is transient: a Cloudflare
  # "Authentication error [code: 10000]" on a session that was authenticated a
  # minute earlier and a minute later. One retry turns a lost build into a pause.
  pull_queue() {
    npx wrangler d1 execute "$D1_DATABASE" --remote --json --command "$QUEUE_SQL" \
      > "$QUEUE_TMP" 2>"$QUEUE_ERR" || return 1
    python3 -c "import json,sys; sys.exit(0 if isinstance(json.load(open(sys.argv[1])), list) else 1)" \
      "$QUEUE_TMP" 2>/dev/null
  }

  if pull_queue || { echo "  … the queue read failed, retrying once"; sleep 3; pull_queue; }; then
    mv "$QUEUE_TMP" data/local/queue_export.json

    # WHICH dataset the merge checks against is not a detail. apply_queue.py
    # asks "is this field still empty / does it still hold the value that was
    # reported", and it has to ask that of the data the submitter was actually
    # looking at — which is the build the deployed tiles were cut from, i.e.
    # $BUILD_DIR/buildings.geojson.
    #
    # Its default is ./buildings.geojson, the LOCAL EDITOR's build, which is
    # whatever state the last local build produced and can be days stale. Left
    # to the default it rejected a valid report for disagreeing with a value the
    # published map had shown for a day, and — worse in the other direction —
    # could apply a suggestion over a field that has since been filled.
    ORACLE="$BUILD_DIR/buildings.geojson"
    if [ -f "$ORACLE" ]; then
      python3 pipeline/apply_queue.py --queue data/local/queue_export.json --apply \
        --applied-ids "$APPLIED_IDS" --geojson "$ORACLE"
    else
      # A first build in a fresh clone: nothing has been built yet, so there is
      # no oracle and no way to check openness. Skipping is right; failing the
      # build over it is not, and apply_queue.py exits non-zero here.
      echo "  ⚠ no built dataset yet to check against — approvals will be applied"
      echo "    on the next build, once $BUILD_DIR/buildings.geojson exists"
    fi

    # Marking them in D1 is what stops the next build applying them again — the
    # merge itself is idempotent (provenance.json remembers), so a failure here
    # costs a re-pull, not correctness. It is also what drops source_note, which
    # must not outlive review: docs/submission-schema.md §4.
    if [ -s "$APPLIED_IDS" ]; then
      IDS=$(tr '\n' ',' < "$APPLIED_IDS" | sed "s/,$//; s/,/', '/g")
      MARK_SQL="UPDATE submissions SET status='applied', source_note=NULL WHERE submission_id IN ('$IDS')"
      if npx wrangler d1 execute "$D1_DATABASE" --remote --command "$MARK_SQL" \
           > "$QUEUE_TMP" 2>"$QUEUE_ERR"; then
        echo "  ✓ marked applied in D1, notes purged"
      else
        echo "  ⚠ applied locally, but could not mark them in D1 — they will be"
        echo "    re-pulled next build and skipped as already applied. Re-run the"
        echo "    UPDATE from docs/build-and-deploy.md (Retention and stale rows):"
        cat "$QUEUE_ERR" "$QUEUE_TMP" | sed 's/^/      /' | head -8
      fi
      echo "  ⚠ data/source/ changed (suggestions, provenance) — COMMIT IT"
    fi
  else
    echo "  ⚠ could not read the review queue, twice. Building with the"
    echo "    suggestions already in suggestions.json; any approval made since"
    echo "    the last build is NOT in this build. What came back:"
    # both streams: the JSON error arrives on stdout, the transport error on stderr
    cat "$QUEUE_ERR" "$QUEUE_TMP" | sed 's/^/      /' | head -12
  fi
  echo
fi

# ── Data and tiles ───────────────────────────────────────────────────────────

if [ "$BUILD_TILES" = 1 ]; then
  rm -rf "$OUT_DIR"
  mkdir -p "$BUILD_DIR" "$OUT_DIR"

  echo "▸ Building dataset…"
  # Defaults to --source overpass: LIVE OSM, current to the minute. The
  # Geofabrik extract is cut once a day and published hours later, so a pbf
  # build could not contain an edit made the same day however often it ran —
  # which for this project's loop (split a building, review the pieces) was the
  # whole cost. --source pbf still works when Overpass is unreachable.
  python3 pipeline/fetch_buildings.py --out-dir "$BUILD_DIR"

  echo
  echo "▸ Converting to vector tiles…"
  # Individual z/x/y tiles, NOT a single .pmtiles archive. PMTiles is read by HTTP
  # range request, and Cloudflare Pages ignores Range entirely — it answers each one
  # with the whole file, so a 17MB archive was downloaded in full on every request.
  # Separate tiles need no ranges, get cached per-tile by the CDN, and work on any
  # static host. ~2,100 files here, well under Pages' 20,000 limit.
  #
  # -Z10: below z10 the city is a smudge and individual buildings are meaningless.
  # -z16 is enough to click one precisely. These MUST match the minzoom/maxzoom in
  # map.js, or MapLibre will request tiles that were never generated.
  tippecanoe -e "$OUT_DIR/tiles" \
    -l buildings \
    -Z10 -z16 \
    --drop-densest-as-needed \
    --extend-zooms-if-still-dropping \
    --no-tile-size-limit \
    --no-tile-compression \
    --force \
    "$BUILD_DIR/buildings.geojson" 2>&1 | tail -3
else
  # --ui-only overwrites files in place instead of the usual rm -rf, so the
  # tiles survive. They have to already be there: without them this would
  # produce a deployable-looking directory that renders an empty map.
  [ -d "$OUT_DIR/tiles" ] || {
    echo "--ui-only needs tiles in $OUT_DIR/tiles, and there are none." >&2
    echo "Run ./build_public.sh once to build them." >&2
    exit 1
  }
  mkdir -p "$BUILD_DIR"
  # stats.json is copied below and pairs with the tiles, not with the UI, so it
  # must be the one that built them.
  [ -f "$BUILD_DIR/stats.json" ] || {
    echo "--ui-only needs $BUILD_DIR/stats.json from the build that made those tiles." >&2
    echo "Run ./build_public.sh once to regenerate both together." >&2
    exit 1
  }
  echo "▸ UI only — reusing $(find "$OUT_DIR/tiles" -name '*.pbf' | wc -l | tr -d ' ') existing tiles"
fi

# --no-tile-compression is load-bearing. tippecanoe gzips tiles by default, which
# a browser only decodes if the response carries Content-Encoding: gzip — and
# Cloudflare Pages IGNORES that header in _headers, because it manages compression
# itself. The tiles then arrive as gzip bytes labelled as protobuf, MapLibre fails
# to parse them, and the map renders empty with no error. Raw tiles sidestep the
# whole negotiation; the CDN still compresses them in transit on its own terms.
#
# Cached for a year and never revalidated, which is only safe because the tile
# URL carries the build id (?v=<hash of buildings.geojson>, see BUILD_ID in
# fetch_buildings.py and the tile source in map.js). New data means a new URL,
# so a cached tile is only ever served to a page that asked for exactly that
# version. It used to be max-age=86400 on a bare path, and that combination is
# what kept an approved suggestion invisible to its own contributor for a day.
cat > "$OUT_DIR/_headers" <<'HEADERS'
/tiles/*
  Content-Type: application/x-protobuf
  Cache-Control: public, max-age=31536000, immutable
HEADERS

echo
echo "▸ Assembling $OUT_DIR/…"
cp "$BUILD_DIR/stats.json" "$OUT_DIR/stats.json"
# Not tiled: 17 features, 6KB gzipped, and it never changes. Splitting that
# across z/x/y tiles would cost more in requests than it saves in bytes.
cp "$WATER_FILE" "$OUT_DIR/water.geojson"
cp web/map.js web/map.css "$OUT_DIR/"

# The wordmark face, shipped unmodified: 11KB unsubsetted, small enough that
# subsetting would cost more effort than it saves in bytes.
mkdir -p "$OUT_DIR/fonts"
cp fonts/Armeniapedia-Kisat.ttf "$OUT_DIR/fonts/"
# The site, copied under its own name. It used to be view.html renamed on the
# way out, because index.html was a local editor that must never be published.
# The editor is gone, so there is nothing to rename around any more.
cp web/index.html "$OUT_DIR/index.html"

# The suggestion API. A full build does `rm -rf public`, so anything not copied
# here is simply absent from the deploy — and a missing Function does not fail
# the build, it produces a working map whose suggest button 404s. Bindings
# (DB, RATE_LIMIT, TURNSTILE_SECRET, SUBMITTER_SALT) live in the Pages project
# settings, not in this repo: see docs/build-and-deploy.md.
#
# The rm is load-bearing. `cp -R src dst` copies src INTO dst when dst already
# exists, so on a --ui-only build (which does not rm -rf public/) this nested a
# second copy at functions/functions/ and left the REAL one untouched — a Function
# you had just edited would not deploy, silently, while a stale one kept serving.
rm -rf "$OUT_DIR/functions"
cp -R functions "$OUT_DIR/functions"

# review.html is protected by Cloudflare Access, NOT by anything in the file.
# If the Access policy is ever removed this page and /api/queue publish the
# queue, source_note included — which can identify submitters. Verify with a
# private window after any change to the project's Access settings.
cp web/review.html "$OUT_DIR/review.html"

# The Turnstile site key is public by design (it identifies the widget; the
# secret key is a binding and never leaves Cloudflare). Left as a placeholder
# when unset so a local build works with the challenge simply absent — the
# Function skips verification when TURNSTILE_SECRET is unset too, which is what
# keeps `python3 pipeline/server.py` a complete development environment.
if [ -n "${TURNSTILE_SITE_KEY:-}" ]; then
  # macOS sed needs the empty -i argument; GNU sed does not accept it.
  sed -i '' -e "s|__TURNSTILE_SITE_KEY__|$TURNSTILE_SITE_KEY|g" \
    "$OUT_DIR/index.html" 2>/dev/null || \
  sed -i -e "s|__TURNSTILE_SITE_KEY__|$TURNSTILE_SITE_KEY|g" "$OUT_DIR/index.html"
  echo "  Turnstile site key baked in"
else
  echo "  TURNSTILE_SITE_KEY unset — the challenge will not render (fine locally)"
fi

# Without a 404.html, Cloudflare Pages answers any unmatched path with 200 +
# index.html. A tile that was never generated (tippecanoe only writes tiles where
# features exist) then arrives as HTML, and MapLibre fails to parse it with
# "Unimplemented type: 4". With this file present, Pages returns a real 404 and
# MapLibre treats the tile as empty, which is the truth.
cat > "$OUT_DIR/404.html" <<'NOTFOUND'
<!doctype html>
<meta charset="utf-8">
<title>Not found — Urban Layers: Yerevan through time</title>
<style>
  body { background:#000; color:#bbb; font:15px/1.6 system-ui,sans-serif;
         display:grid; place-items:center; height:100vh; margin:0; }
  a { color:#d6c41d; }
</style>
<div>
  <p>That page doesn’t exist.</p>
  <p><a href="/">Back to the map</a></p>
</div>
NOTFOUND

echo
echo "✓ $OUT_DIR/ ready to deploy:"
ls -lh "$OUT_DIR" | awk 'NR>1 && $9 != "tiles" {printf "    %-22s %s\n", $9, $5}'
printf "    %-22s %s in %s files%s\n" "tiles/" \
  "$(du -sh "$OUT_DIR/tiles" | cut -f1)" \
  "$(find "$OUT_DIR/tiles" -name '*.pbf' | wc -l | tr -d ' ')" \
  "$([ "$BUILD_TILES" = 1 ] || echo '  (reused)')"
echo
echo "  Preview locally : python3 pipeline/server.py 8003   → http://localhost:8003/$OUT_DIR/"
echo "  Deploy          : wrangler pages deploy $OUT_DIR/"
