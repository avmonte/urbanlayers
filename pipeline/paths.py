"""Every path this project reads or writes, resolved from the repo root.

Before this file, each script carried its own bare filename constants
(`SUGGESTIONS_FILE = 'suggestions.json'`) which Python resolved against the
*current working directory*. That made the directory you happened to be standing
in part of the interface: `detect_splits.py` needed `PYTHONPATH=. python3 …`,
the classifier reached back up with `"../armenia.osm.pbf"`, and the tests split
into "these run from tests/, that one runs from the root" — not by design, just
by whichever directory each script's literals happened to assume.

Resolving from `__file__` instead means a script works from anywhere, and there
is one place to look when asking where something lives.

The directories encode the distinction that matters most here, which the
filesystem previously did not show at all:

    SOURCE   irreplaceable. Hand-researched years, the provenance record,
             hand-drawn water. Losing these loses work that cannot be redone.
    CACHE    re-downloadable. Big, slow, and gone-without-consequence: the
             Geofabrik extract and the cached Overpass response.
    BUILD    regenerable in about two minutes from SOURCE + CACHE.
    LOCAL    mutable dev state — the offline twin of the D1 queue. Disposable,
             but not an output of anything.

"Can I delete this?" is answered by which of those a file sits in, rather than
by reading sixty lines of .gitignore prose.
"""
from pathlib import Path

# The repo root. Every other path hangs off this, so this is the only line that
# needs to change if this module itself is ever moved.
ROOT = Path(__file__).resolve().parent.parent

# ── Directories ─────────────────────────────────────────────────────────────
SOURCE = ROOT / 'data' / 'source'
CACHE = ROOT / 'data' / 'cache'
LOCAL = ROOT / 'data' / 'local'
BUILD = ROOT / 'build'
WEB = ROOT / 'web'
PIPELINE = ROOT / 'pipeline'
FONTS = ROOT / 'fonts'
FUNCTIONS = ROOT / 'functions'
PUBLIC = ROOT / 'public'

# ── Source records — irreplaceable ──────────────────────────────────────────
# suggestions.json is the whole point of the project: years researched by hand,
# one entry per OSM id. provenance.json is what tells an accepted public
# contribution apart from a maintainer edit, and holds the value a correction
# replaced — it is the only thing that makes --revert possible.
SUGGESTIONS = SOURCE / 'suggestions.json'
PROVENANCE = SOURCE / 'provenance.json'
# Model-backed khrushchevka/brezhnevka calls from the era classifier in exp/.
INFERRED = SOURCE / 'inferred_buildings.json'
# Backdrop, not data — the Hrazdan and Yerevan Lake. Never changes.
WATER = SOURCE / 'water.geojson'
# queue_export.json used to sit here. It does not any more: a raw D1 dump carries
# source_note and submitter_hash, and this directory is published. See LOCAL.

# ── Caches — re-downloadable, never committed ───────────────────────────────
# 53MB from Geofabrik, only read on the --source pbf fallback path.
PBF = CACHE / 'armenia.osm.pbf'
# The live Overpass response. Cached so a rebuild need not ask a shared public
# service twice for data that has not changed, and so a build is reproducible.
OVERPASS_CACHE = CACHE / 'overpass_buildings.json'

# ── Local dev state ─────────────────────────────────────────────────────────
# What server.py writes in place of D1, so the whole submit → review → approve
# loop runs with no Cloudflare account.
QUEUE = LOCAL / 'queue.json'
# The last D1 export pulled by build_public.sh. It is the queue in the shape
# wrangler answers with, which means it still carries source_note (free text a
# submitter wrote, which can identify them) and submitter_hash (a salted hash of
# their IP). Neither may be published, and this repository is published — so the
# export lives here, and provenance.json is the durable record of what landed.
QUEUE_EXPORT = LOCAL / 'queue_export.json'
# hash -> opaque contributor id, so provenance.json can name a submitter well
# enough to revert their run without publishing anything derived from an IP.
# Losing it costs the ability to map an id back to a D1 row, nothing on the map.
SUBMITTERS = LOCAL / 'submitters.json'

# ── Build outputs ───────────────────────────────────────────────────────────
# The dataset the map renders, and the openness oracle apply_queue.py checks a
# submission against. These are the names written *inside* an --out-dir; the
# constants below are the default location.
BUILDINGS = BUILD / 'buildings.geojson'
STATS = BUILD / 'stats.json'

# Bare names, not paths: fetch_buildings.py writes these through out_path() so
# they land in whichever --out-dir it was given.
BUILDINGS_NAME = 'buildings.geojson'
STATS_NAME = 'stats.json'
ORPHANS_NAME = 'orphans.json'
REPORT_NAME = 'needs_data.csv'


def rel(p):
    """A path as it reads in a message — relative to the repo root.

    Every constant here is absolute, which is the point: a script works from
    any directory. Printing them raw would put the reader's home directory in
    build output that used to say plainly `suggestions.json`, so anything
    user-facing goes through here.
    """
    p = Path(p)
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)          # outside the repo — an explicit --out-dir, say
