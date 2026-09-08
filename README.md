# Urban Layers: Yerevan through time

A map of Yerevan's ~76,000 buildings coloured by when they were built, with a
public form for contributing a year and a review queue behind it.

**Live: [urbanlayers.xyz](https://urbanlayers.xyz)**

Most buildings have no year — that is the point of the project. OSM tags supply
about fifty; the rest are researched by hand or, where two models agree strongly
enough, inferred. Nothing is published as a fact unless the evidence supports
saying so out loud.

## The tree

```
pipeline/   the Python: fetch → merge → serve. paths.py resolves everything
web/        the site (index.html) and the review queue (review.html), sharing
            one map engine. Served at / by pipeline/server.py
functions/  Cloudflare Pages Functions — the name is load-bearing, it is what
            makes functions/api/suggest.js answer /api/suggest
data/
  source/   irreplaceable and tracked: hand-researched years, provenance,
            water, inferred eras
  cache/    re-downloadable: the Geofabrik extract, the Overpass response
  local/    dev state: the offline twin of the D1 queue
build/      regenerable in ~2 minutes
public/     the deploy artifact, assembled by build_public.sh
exp/        local only, gitignored: the era classifier and the one-off
            generators that produce data/source files. Not needed to build
tests/      no framework; run any of them from anywhere
docs/       build-and-deploy.md is the operational reference
```

**Which directory a file is in tells you whether it survives a delete.** Only
`data/source/` holds work that cannot be regenerated.

## Getting started

Python 3.12 or newer.

```bash
pip install -r requirements.txt     # requests + osmium, and nothing else
python3 pipeline/fetch_buildings.py    # ~10s, live OSM → build/
python3 pipeline/server.py 8003     # editor at /, public site at /public/
```

That is the whole dependency list. The era classifier that produced the
inferred spans needs the scientific stack on top, but it lives in `exp/`, which
is not in this repository — nothing about rebuilding the map needs it.

Nothing here is importable as a package — the scripts run directly, and find
each other because running one puts its own directory on `sys.path`.

`server.py` serves `web/` as `/` and routes the data paths to where they
actually live, so the URLs the browser sees are the same ones the deployed site
serves. The whole submit → review → approve loop runs offline with no Cloudflare
account.

Building and deploying for real, the review queue, split detection, the
Cloudflare configuration, and the gotchas that each cost a broken deploy:
**`docs/build-and-deploy.md`**. The submission rules — implemented three times,
in `web/map.js`, `functions/api/suggest.js` and `pipeline/apply_queue.py` — are
specified once in `docs/submission-schema.md`, which is the authority.

## Tests

```bash
for f in tests/*.py; do python3 "$f"; done
```

No framework, no `PYTHONPATH`, no required working directory. Run
`tests/test_parity.py` after touching `pipeline/submission.py`,
`functions/api/_shared.js` or `docs/submission-schema.md` — it proves the Python
and JS validators still agree.

## Licence

Two licences, because the code and the data are not the same thing and only one
of them is mine to license.

**Code — MIT** (`LICENSE`). Everything in `pipeline/`, `web/`, `functions/`,
`tests/` and the build scripts. Take it, fork it, map another city.

**Data — ODbL 1.0** (`LICENSE.data`), © OpenStreetMap contributors.
`data/source/`, `build/` and the tiles in `public/`. Building footprints come
from OSM, and the years researched by hand here are merged into an OSM-derived
database, which makes them a Derivative Database — so they are ODbL too, and
anyone may take the dataset. Attribution is required wherever it is shown.

Note that ODbL is **share-alike, not non-commercial**: §3.1 says the rights
"explicitly include commercial use, and do not exclude any field of endeavour."
Selling something built on this data is fine. Publishing an *improved database*
without releasing it under ODbL is not. A rendered map image is a Produced Work
rather than a Derivative Database, so it carries the attribution requirement but
not share-alike.

The wordmark face, `fonts/Armeniapedia-Kisat.ttf` © 2016 Raffi Kojian, is free
for personal and commercial use and is shipped unmodified.

Third-party libraries keep their own licences: MapLibre GL JS (BSD-3-Clause),
osmium (BSD-2-Clause), requests (Apache-2.0) and certifi (MPL-2.0). That is the
whole list — the map builds on three Python packages and one JS one.

Contributions: `CONTRIBUTING.md`.
