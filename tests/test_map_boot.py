#!/usr/bin/env python3
"""Boots map.js and clicks a building — run: python3 test_map_boot.py

`node --check` proves map.js PARSES. It says nothing about whether the names it
uses exist, and that is the failure that actually shipped: a range delete took
SOURCE_KINDS, EVIDENCE_FLOOR and tYear out with the block above them, every test
passed, and the map rendered perfectly while no building would open a popup —
because the click handler threw before setHTML ran, into a console nobody was
reading.

So this drives the real path: build the chrome, boot initBuildingMap for each
mode, fire map's `load`, then fire a click on a building layer and require that
popup HTML actually came out. A missing identifier anywhere along that path is
a ReferenceError, and a ReferenceError fails the test.

maplibre and the DOM are stubbed rather than emulated — the point is to execute
map.js's own code, not to check MapLibre works. The data is synthesised too, so
this runs in a fresh clone with no build.
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
import paths

HARNESS = r'''
import fs from 'fs';

const MODE = process.argv[2];
const errors = [];
const el = (id) => ({
  id, style: {}, textContent: '', innerHTML: '', value: '', checked: false,
  classList: { toggle: () => false, add(){}, remove(){}, contains: () => false },
  dataset: {}, appendChild(){}, addEventListener(){}, setAttribute(){},
  removeAttribute(){}, querySelector: () => null, querySelectorAll: () => [],
  remove(){}, insertAdjacentHTML(){}, focus(){},
  getBoundingClientRect: () => ({ width: 200, height: 20, left: 0, top: 0 }),
});
// Resolves any selector to a generic element, so code that walks the popup
// runs instead of bailing at the first `if (!el) return`. Without this the
// wiring — evidence fields, submit handlers — is never executed at all.
const deep = () => new Proxy(el('deep'), {
  get(t, p) {
    if (p === 'querySelector') return () => deep();
    if (p === 'querySelectorAll') return () => [deep()];
    if (p === 'closest') return () => deep();
    if (p === 'parentNode' || p === 'firstElementChild') return deep();
    return t[p];
  },
});
const els = new Map();
let bodyHTML = '';
global.document = {
  documentElement: { style: { setProperty(){} }, lang: 'en', dataset: {},
    classList: { add(){}, remove(){}, toggle: () => false, contains: () => false },
    setAttribute(){}, removeAttribute(){} },
  // dataset carries the Turnstile site key the public form reads off <body>.
  body: { insertAdjacentHTML: (_, h) => { bodyHTML += h; },
          classList: { add(){}, remove(){} }, dataset: { turnstileSiteKey: '' } },
  getElementById: (id) => { if (!els.has(id)) els.set(id, el(id)); return els.get(id); },
  querySelectorAll: () => [...bodyHTML.matchAll(/data-i18n(?:-placeholder)?="([^"]+)"/g)].map(() => el('i18n')),
  querySelector: () => null,
  createElement: () => el('created'),
  addEventListener(){},
};
global.window = { addEventListener(){}, matchMedia: () => ({ matches: false, addEventListener(){} }) };
global.location = { href: 'http://localhost:8000/', search: '', hash: '', pathname: '/' };
global.history = { replaceState(){} };
Object.defineProperty(globalThis, 'navigator', { value: { languages: ['en'] }, configurable: true });
global.localStorage = { getItem: () => null, setItem(){}, removeItem(){} };
global.requestAnimationFrame = (f) => { f(); return 1; };
global.cancelAnimationFrame = () => {};

// Synthesised so this needs no build: one dated building, one span, one bucket.
const STATS = { total: 3, bounds: [44.3, 40.0, 44.6, 40.3], build: 'test',
  known: 1, suggested: 1, community: 1, inferred: 1, unknown: 0,
  min_year: 1900, max_year: 2020,
  year_index: [[1900, 1900, 0, 1], [1960, 1960, 2, 1], [1958, 1972, 3, 1]] };
const WATER = { type: 'FeatureCollection', features: [] };
global.fetch = async (url) => ({ ok: true,
  json: async () => (String(url).includes('stats') ? STATS : WATER) });

const handlers = [];
let popupHTML = null;
class Map_ {
  constructor(){}
  on(a, b, c){ handlers.push({ ev: a, layer: typeof b === 'string' ? b : null, fn: c || b }); }
  once(a, b){ handlers.push({ ev: a, fn: b }); }
  addSource(){} addLayer(){} removeLayer(){} removeSource(){}
  setPaintProperty(){} setLayoutProperty(){} setFilter(){}
  getSource(){ return { setData(){} }; }
  getLayer(){ return true; }
  getCanvas(){ return { style: {} }; }
  setFeatureState(){} removeFeatureState(){}
  queryRenderedFeatures(){ return []; }
  project(){ return { x: 0, y: 0 }; }
  unproject(){ return { lng: 44.5, lat: 40.18 }; }
  fitBounds(){} setMaxBounds(){} setMinZoom(){} setMaxZoom(){}
  getZoom(){ return 13; } getCenter(){ return { lng: 44.5, lat: 40.18 }; }
  getBounds(){ return { getWest: () => 44.3, getSouth: () => 40.0, getEast: () => 44.6, getNorth: () => 40.3 }; }
  addControl(){} easeTo(){} flyTo(){} resize(){} remove(){}
  dragRotate = { disable(){} };
  touchZoomRotate = { disableRotation(){} };
  scrollZoom = {}; keyboard = {}; boxZoom = {}; doubleClickZoom = {};
}
class Popup_ {
  constructor(){}
  setLngLat(){ return this; }
  setHTML(h){ popupHTML = h; return this; }
  setDOMContent(){ return this; }
  addTo(){ return this; } remove(){ return this; }
  isOpen(){ return false; } on(){ return this; }
  getElement(){ return deep(); }
}
global.maplibregl = {
  Map: Map_, Popup: Popup_,
  Marker: class { constructor(){} setLngLat(){ return this; } addTo(){ return this; } remove(){} },
  NavigationControl: class {},
  LngLatBounds: class { constructor(){} extend(){ return this; } isEmpty(){ return false; } },
};

const src = fs.readFileSync(process.argv[3], 'utf8');
try {
  new Function(src + `\ninitBuildingMap({ mode: ${JSON.stringify(MODE)}, tiles: true });`)();
} catch (e) { errors.push('init: ' + e.message); }

for (const h of handlers.filter(h => h.ev === 'load')) {
  try { h.fn({}); } catch (e) { errors.push("map 'load': " + e.message); }
}
await new Promise(r => setTimeout(r, 80));

const clicks = handlers.filter(h => h.ev === 'click' && h.layer);

// Both fixtures matter, and the first one is the one that broke. A building
// with NO year renders the suggest form, which is what reaches SOURCE_KINDS and
// EVIDENCE_FLOOR; a building that already has one is suppressed by the additive
// rule, so clicking only that kind exercises none of it. 96% of the city is the
// first kind, which is also what anyone clicks in order to contribute.
const FIXTURES = {
  'no data': { id: 1, properties: { id: 31621516, addr_street: 'Street', addr_number: '1' } },
  'has year': { id: 2, properties: { id: 31621517, addr_street: 'Street', addr_number: '2',
                                     year_built: 1961, year_tag: 'suggested', community: 1 } },
  // The written-out year shapes, which are the only thing that reaches tYear:
  // "after 1958" and "before 1972" are sentences, not truncated ranges.
  'open lo': { id: 3, properties: { id: 31621518, year_min: 1958 } },
  'open hi': { id: 4, properties: { id: 31621519, year_max: 1972 } },
  'era span': { id: 5, properties: { id: 31621520, year_min: 1958, year_max: 1972 } },
};
let sizes = {};
for (const c of clicks) {
  for (const [label, feat] of Object.entries(FIXTURES)) {
    popupHTML = null;
    try { c.fn({ features: [feat], lngLat: { lng: 44.5, lat: 40.18 }, point: { x: 1, y: 1 } }); }
    catch (e) { errors.push(`click ${label} on ${c.layer}: ${e.message}`); continue; }
    if (!popupHTML) errors.push(`click ${label} on ${c.layer}: no popup HTML`);
    else sizes[label] = popupHTML.length;
  }
}

console.log(JSON.stringify({
  mode: MODE,
  chromeIds: [...bodyHTML.matchAll(/id="([^"]+)"/g)].map(m => m[1]),
  clickLayers: clicks.map(c => c.layer),
  sizes,
  errors,
}));
'''

KINDS = ('no data', 'has year', 'open lo', 'open hi', 'era span')


def main():
    node = shutil.which('node')
    if not node:
        print('node not on PATH — skipping map boot check')
        return 0

    harness = paths.ROOT / '.map_boot.mjs'
    harness.write_text(HARNESS, encoding='utf-8')
    failures = []
    try:
        for mode in ('public', 'review'):
            out = subprocess.run([node, str(harness), mode, str(paths.WEB / 'map.js')],
                                 capture_output=True, text=True)
            if out.returncode:
                print(f'  ✗ {mode}: harness failed\n{out.stderr}')
                failures.append(f'{mode}: harness failed')
                continue
            r = json.loads(out.stdout.strip().splitlines()[-1])
            sizes = r['sizes']
            ok = not r['errors'] and r['clickLayers'] and len(sizes) == len(KINDS)
            shown = ', '.join(f'{k}={v}c' for k, v in sizes.items()) or 'none'
            print(f"  {'✓' if ok else '✗'} {mode:7} chrome={len(r['chromeIds'])} ids, "
                  f"click layers={len(r['clickLayers'])}, popups: {shown}")
            for e in r['errors']:
                print(f'      ✗ {e}')
                failures.append(f'{mode}: {e}')
            for kind in KINDS:
                if kind not in sizes:
                    failures.append(f'{mode}: clicking a "{kind}" building produced no popup')
    finally:
        harness.unlink(missing_ok=True)

    print()
    if failures:
        for f in failures:
            print(f'  {f}')
        return 1
    print('map.js boots and opens a popup in every mode')
    return 0


if __name__ == '__main__':
    sys.exit(main())
