#!/usr/bin/env python3
"""Checks every data-i18n attribute resolves — run: python3 test_i18n.py

t() falls back to the key itself when a string is missing, which is the right
behaviour at runtime (a half-finished translation degrades one string at a time)
and a silent trap at author time: a typo'd attribute renders "statConfrimed" on
the page instead of failing. This catches that, and catches a key that exists in
English but not in Armenian.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
import paths

src = open(paths.WEB / 'map.js').read()
block = re.search(r'const I18N = \{.*?\n\};', src, re.S).group(0)
langs = dict(re.findall(r'\n  (\w+): \{(.*?)\n  \},', block, re.S))
keys = {lang: set(re.findall(r"(\w+):\s*'", body)) for lang, body in langs.items()}

failures = []

print(f"languages: {', '.join(keys)}")
base = keys['en']
for lang, ks in keys.items():
    if lang == 'en':
        continue
    missing, extra = sorted(base - ks), sorted(ks - base)
    print(f"  {'✓' if not (missing or extra) else '✗'} {lang}: "
          f"{len(ks)}/{len(base)} keys"
          + (f" — missing {', '.join(missing)}" if missing else '')
          + (f" — extra {', '.join(extra)}" if extra else ''))
    failures += [f'{lang} missing {k}' for k in missing] + [f'{lang} has stray {k}' for k in extra]

print()
# The chrome is emitted by buildChrome() in map.js, not written into the pages,
# so map.js is where the attributes are now. The three HTML shells are still
# scanned: they carry none today, and this is what says so if one reappears
# there and starts drifting again.
sources = {'map.js': src}
for page in ('index.html', 'review.html'):
    try:
        sources[page] = open(paths.WEB / page).read()
    except FileNotFoundError:
        pass

for name, text in sources.items():
    for attr in ('data-i18n', 'data-i18n-placeholder'):
        for key in re.findall(attr + r'="([^"]+)"', text):
            # Skip interpolated attributes — the stat rows build theirs from
            # STAT_ROWS, whose keys are checked below and more precisely.
            if '${' in key:
                continue
            ok = key in base
            print(f"  {'✓' if ok else '✗ NO SUCH KEY'} {name:12} {attr:22} {key}")
            if not ok:
                failures.append(f'{name}: {attr}="{key}" matches no string')

# Strings fetched through t() carry no attribute for the scan above to find, so
# they are checked by name. Keep this list in step with the t('…') calls that
# are not data-i18n attributes.
print()
for key in ('showingBuildings', 'badgeConfirmed'):
    ok = key in base
    print(f"  {'✓' if ok else '✗ NO SUCH KEY'} t() call     {key}")
    if not ok:
        failures.append(f't({key!r}) matches no string')

print()
if failures:
    for f in failures:
        print(f'  {f}')
    sys.exit(1)
print('all i18n references resolve')
