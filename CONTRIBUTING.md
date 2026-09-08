# Contributing

Two ways in, and they are governed differently.

## Building years

Use the form on [urbanlayers.xyz](https://urbanlayers.xyz). It posts to a review
queue; nothing reaches the map until an approved row is merged. Years and their
provenance become part of an OpenStreetMap-derived database, so they are
published under **ODbL 1.0** like the rest of the data — see the licence section
of `README.md`.

## Code

By submitting a pull request you agree that your contribution is licensed under
the **MIT License** (`LICENSE`), and that you have the right to license it that
way.

That one sentence is the whole agreement — there is no CLA to sign. It exists so
the licence of every line in the repo is answerable without tracking down past
contributors.

Before opening a PR:

```bash
for f in tests/*.py; do python3 "$f"; done
```

`tests/test_parity.py` is the one that matters most — run it after touching
`pipeline/submission.py`, `functions/api/_shared.js` or
`docs/submission-schema.md`, since it proves the Python and JS validators still
agree.

### Four things that will otherwise cost you a rejected PR

**Never hand-edit `data/source/*.json`.** Those files are written by
`pipeline/apply_queue.py` from approved queue rows, and every year in them has a
matching entry in `provenance.json` saying where it came from and what it
replaced. A year typed straight into `suggestions.json` has no provenance and
cannot be reverted, so it will be asked out of the PR even when it is correct.
Send it through the form instead.

**The submission rules are implemented three times on purpose** — in
`web/map.js` (so the browser can reject early), `functions/api/suggest.js` (so
the server never trusts the browser) and `pipeline/apply_queue.py` (so a merge
never trusts either). That duplication is the design, not debt to be cleaned up.
`docs/submission-schema.md` is the specification; change it and all three, or
none, and let `test_parity.py` confirm it.

**Adding a dependency needs a sentence in the PR.** The pipeline is "requests +
osmium, and nothing else" deliberately — it is what lets someone rebuild the
whole map without the scientific stack. New packages are not banned, but say
what the stdlib could not do.

**Open an issue before a large change.** Anything that moves files between the
directories in `pipeline/paths.py`, changes the tile build, or touches the
review queue is worth ten lines of discussion first. It is a small project with
one maintainer, and it is better to hear "not this way" before a weekend than
after one.

Style: match the file you are editing. The comments here explain *why* a thing
is the way it is, not what the line does; that is a deliberate choice and
patches that keep it read better against the rest.

## Conduct

`CODE_OF_CONDUCT.md` — the Contributor Covenant, unmodified. It applies to
issues, pull requests and the review queue alike.
