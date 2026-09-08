-- D1 schema for the public suggestion queue.
--
--   wrangler d1 create <your-d1-database>
--   wrangler d1 execute <your-d1-database> --remote --file=schema.sql
--
-- Mirrors queue.json, which server.py writes locally (see submission.py for the
-- shape both share). Kept deliberately flat: the queue is a few tens of rows a
-- week at most, and anything cleverer would be built for a scale this will
-- never reach.
CREATE TABLE IF NOT EXISTS submissions (
  submission_id  TEXT PRIMARY KEY,
  osm_id         TEXT NOT NULL,
  lng            REAL NOT NULL,
  lat            REAL NOT NULL,
  -- 'suggestion' (fills empty fields), 'report' (disputes something already
  -- shown), or 'orphan' (a year whose building stopped existing, re-proposed
  -- onto the footprints that replaced it — phase 4, docs §6). Defaulted so rows
  -- written before phase 3 read correctly.
  kind           TEXT NOT NULL DEFAULT 'suggestion',
  -- the normalised suggestions.json entry, as JSON. Empty {} for a report that
  -- flags a field without proposing a replacement.
  entry          TEXT NOT NULL,
  -- what the SUBMITTER claimed, when a reviewer has since edited `entry`.
  -- Written once, on the first edit, and never overwritten: provenance.json
  -- records `claim` as "what that submission proposed", and an edit that
  -- replaced it in place would credit a stranger with a year they never
  -- claimed — permanently, and under ODbL. NULL means nobody edited it.
  entry_original TEXT,
  -- for an orphan: the OSM id the year was inherited from. A COLUMN rather than
  -- a note because source_note is purged after review (docs §4) and this is the
  -- whole provenance of the claim — it has to outlive that.
  derived_from   TEXT,
  -- What the submitter's tiles showed. For a suggestion every value is null
  -- (the additive rule); for a report it is the disputed fields and the values
  -- they held. Either way apply_queue.py re-checks it against a fresh build and
  -- skips anything the data has moved out from under.
  before_json    TEXT NOT NULL,
  -- what the evidence IS: 'plaque' | 'online' | 'local'. Rows written before
  -- the split also hold 'cornerstone' | 'document' | 'resident' | 'other'.
  source_kind    TEXT NOT NULL,
  -- the link that carries it, https only and shape-checked before storage
  source_url     TEXT,
  -- what that link answered when it was submitted ("http 200", "no response").
  -- A note for the reviewer, never a gate: a 403 to an automated HEAD says more
  -- about the site's bot policy than about the evidence.
  link_status    TEXT,
  -- REQUIRED at submit, PURGED after review — it can identify a person
  -- ("I live here" + a building id) and must never reach suggestions.json,
  -- which is a Derived Database under ODbL. See docs/submission-schema.md §4.
  source_note    TEXT,
  submitter_hash TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'pending',
  submitted_at   INTEGER NOT NULL,
  reviewed_at    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_status ON submissions(status, submitted_at);
-- so a bad run can be found and reverted as a set
CREATE INDEX IF NOT EXISTS idx_submitter ON submissions(submitter_hash);

-- Phase 3 added `kind` to an existing table. On a database created before that:
--   wrangler d1 execute <your-d1-database> --remote \
--     --command "ALTER TABLE submissions ADD COLUMN kind TEXT NOT NULL DEFAULT 'suggestion'"
--   wrangler d1 execute <your-d1-database> --remote \
--     --command "ALTER TABLE submissions ADD COLUMN source_url TEXT"
--   wrangler d1 execute <your-d1-database> --remote \
--     --command "ALTER TABLE submissions ADD COLUMN link_status TEXT"
--
-- Phase 4 added reviewer edits and orphans. On an existing table:
--   wrangler d1 execute <your-d1-database> --remote \
--     --command "ALTER TABLE submissions ADD COLUMN entry_original TEXT"
--   wrangler d1 execute <your-d1-database> --remote \
--     --command "ALTER TABLE submissions ADD COLUMN derived_from TEXT"
