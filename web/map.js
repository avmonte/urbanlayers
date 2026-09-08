// Shared map engine for index.html (the public map) and review.html.
// Both pages call initBuildingMap({ mode }) after loading maplibre-gl and
// this file — that single flag is the only thing that differs between them:
// the suggest-a-year popup form, its /suggest network calls, and a couple of
// wording tweaks. Everything else (layers, colors, popup, hover) is common,
// so edit it here once instead of in both files.

// `tiles: true` serves the data as z/x/y vector tiles instead of one 32MB
// buildings.geojson, so the browser fetches only the few KB covering the current
// view. That's what the public site uses; see the dataReady block below for what
// changes as a result.
// ── Language ────────────────────────────────────────────────────────────────
//
// The people who know when a given Soviet block went up are, disproportionately,
// older residents of it — the least likely to fill in a form written in English.
// For a phase whose entire output is public contributions, this is closer to a
// functional requirement than a nicety.
//
// TRANSLATIONS NEED A NATIVE REVIEW before launch. They are written to be
// literal and plain rather than idiomatic; `hy` especially deserves a second
// pair of eyes on tone (a form that reads as machine-translated will be trusted
// less than one written in English).
const I18N = {
  en: {
    name: 'Name', street: 'Street', number: 'No.',
    year: 'year', from: 'from', to: 'to',
    // Two ways to answer, not three. "approx" asked people to grade their own
    // certainty on a scale nobody shares — and the two answers it sat between
    // are the only two most people actually have.
    exact: 'I know exactly', range: 'I know a range',
    // A range takes both bounds, and either one on its own: filling only "from"
    // says "after 1958", only "to" says "before 1972". The empty box IS the
    // open end, which is why the hint has to be on screen — nothing else tells
    // you the second box is optional.
    rangeHint: 'Fill in just one side if that\'s all you know',
    // How a half-open range reads back. Templates, because the word does not
    // sit on the same side of the number in every language: Armenian says
    // "1958-ից հետո", not "հետո 1958".
    beforeYear: 'before {y}', afterYear: 'after {y}',
    // "~1965" is notation, not language. It reads as precision to somebody who
    // knows the convention and as noise to everybody else, and this map is for
    // the second group — the people who know when a block went up, not the
    // people who read datasets. The stored value is unchanged; only the word is.
    approxYear: 'around {y}',
    sourceLabel: 'How do you know?',
    // three kinds of evidence, and what each one is asked to bring. The kind
    // says what is being claimed; the link or the note is what we were handed.
    src_plaque: 'A plaque or date on the building',
    src_online: 'A published source',
    src_local: 'Local knowledge',
    urlPlaceholder: 'https://…',
    notePlaceholder: 'Anything that helps us check it',
    noteRequired: 'Please say a little more',
    sourceRequired: 'Please say how you know',
    urlRequired: 'Please add a link to the source',
    urlBad: 'That does not look like a web address — it should start with https://',
    localNoteRequired: 'Please say how you know — a sentence is enough',
    submit: 'Suggest', submitting: 'Sending…',
    thanks: 'Thank you — sent for review',
    // "approved" and "visible" are different days: the site rebuilds on a
    // schedule, so saying only "approved" reads as a promise the map breaks.
    thanksDetail: 'Someone checks every suggestion by hand. If it\'s accepted it appears on the map at the next rebuild, usually within a day.',
    pending: 'You suggested a year here — waiting for review',
    pendingReport: 'You reported this — waiting for review',
    thanksLive: 'Your suggestion is on the map — thank you.',
    // ── reporting something wrong (phase 3) ──────────────────────────────
    reportOpen: 'Report an error',
    reportWhat: 'What is wrong here?',
    factYear: 'Year', factName: 'Name', factAddress: 'Address',
    factMissing: 'not shown',
    // Every report needs a note, unlike a suggestion: somebody has to decide
    // between two claims about one building, and a dropdown cannot carry that.
    reportNote: 'What is wrong, and how do you know?',
    reportSend: 'Send report',
    reportPickOne: 'Tick what is wrong first',
    reportNoteRequired: 'Please say what is wrong',
    reportThanks: 'Thank you — sent for review',
    reportThanksDetail: 'Someone checks every report by hand. You can leave the value blank if you only know that it is wrong.',
    reportUnknownHint: 'Leave a value blank if you know it is wrong but not what is right',
    yearRange: 'Year must be between 1–2030',
    rangeBackwards: 'The range ends before it starts',
    nothingSuggested: 'Add something before sending',
    failed: 'Could not send — please try again',
    // Chrome — the legend, stats and loader. Translating only the form would be
    // half a job: a contributor who needs Armenian to answer the questions needs
    // it to find them too.
    loading: 'Loading building data…',
    loadingSub: '100k+ Yerevan buildings',
    legendTitle: 'Construction year',
    filterLabel: 'Show buildings between years',
    lightMode: 'Light mode',
    languageLabel: 'Language',
    contactLead: 'Something wrong rather than missing —',
    contactLink: 'get in touch',
    badgeConfirmed: 'Confirmed',
    showingBuildings: 'Showing {n} buildings',
  },
  hy: {
    name: 'Անվանում', street: 'Փողոց', number: 'Համար',
    year: 'տարի', from: 'սկսած', to: 'մինչև',
    exact: 'Գիտեմ ճշգրիտ', range: 'Գիտեմ մոտավոր',
    rangeHint: 'Եթե գիտեք միայն մի սահմանը, լրացրեք միայն այն',
    beforeYear: '{y}-ից առաջ', afterYear: '{y}-ից հետո',
    approxYear: 'մոտ {y}',
    sourceLabel: 'Որտեղի՞ց գիտեք',
    src_plaque: 'Շենքի վրայի ցուցանակը կամ տարեթիվը',
    src_online: 'Հրապարակված աղբյուր',
    src_local: 'Տեղական տեղեկություն',
    urlPlaceholder: 'https://…',
    urlRequired: 'Խնդրում ենք ավելացնել աղբյուրի հղումը',
    urlBad: 'Սա վավեր վեբ հասցե չէ — այն պետք է սկսվի https://-ով',
    localNoteRequired: 'Խնդրում ենք նշել, թե որտեղից գիտեք',
    notePlaceholder: 'Ցանկացած տեղեկություն, որը կօգնի մեզ ստուգել',
    noteRequired: 'Խնդրում ենք մի փոքր մանրամասնել',
    sourceRequired: 'Խնդրում ենք նշել՝ որտեղից գիտեք',
    submit: 'Առաջարկել', submitting: 'Ուղարկվում է…',
    thanks: 'Շնորհակալություն — առաջարկն ուղարկվել է ստուգման',
    thanksDetail: 'Յուրաքանչյուր առաջարկ ստուգվում է ձեռքով։ Ընդունվելու դեպքում այն կհայտնվի քարտեզում հաջորդ թարմացումից հետո՝ սովորաբար մեկ օրվա ընթացքում։',
    pending: 'Այս շենքի համար տարեթիվ եք առաջարկել — սպասում է ստուգման',
    pendingReport: 'Այս շենքի մասին սխալ եք հաղորդել — սպասում է ստուգման',
    thanksLive: 'Ձեր առաջարկն արդեն քարտեզի վրա է — շնորհակալություն։',
    reportOpen: 'Հաղորդել սխալի մասին',
    reportWhat: 'Ի՞նչն է սխալ',
    factYear: 'Տարեթիվ', factName: 'Անվանում', factAddress: 'Հասցե',
    factMissing: 'նշված չէ',
    reportNote: 'Ի՞նչն է սխալ, և որտեղի՞ց գիտեք',
    reportSend: 'Ուղարկել',
    reportPickOne: 'Նախ նշեք, թե ինչն է սխալ',
    reportNoteRequired: 'Խնդրում ենք նշել, թե ինչն է սխալ',
    reportThanks: 'Շնորհակալություն — հաղորդումն ուղարկվել է ստուգման',
    reportThanksDetail: 'Յուրաքանչյուր հաղորդում ստուգվում է ձեռքով։ Եթե միայն գիտեք, որ տվյալը սխալ է, կարող եք արժեքը դատարկ թողնել։',
    reportUnknownHint: 'Թողեք դատարկ, եթե գիտեք, որ տվյալը սխալ է, բայց չգիտեք ճիշտ արժեքը',
    yearRange: 'Տարեթիվը պետք է լինի 1–2030 միջակայքում',
    rangeBackwards: 'Վերջի տարեթիվը պետք է լինի սկզբի տարեթվից հետո',
    nothingSuggested: 'Ուղարկելուց առաջ որևէ տվյալ ավելացրեք',
    failed: 'Չհաջողվեց ուղարկել — խնդրում ենք կրկին փորձել',
    loading: 'Բեռնվում են շենքերի տվյալները…',
    loadingSub: 'Երևանի ավելի քան 100 000 շենք',
    legendTitle: 'Կառուցման տարեթիվ',
    filterLabel: 'Ցուցադրել այս տարիների միջև կառուցված շենքերը',
    lightMode: 'Լուսավոր տեսք',
    languageLabel: 'Լեզու',
    contactLead: 'Սխալ տվյալ նկատեցի՞ք։',
    contactLink: 'կապվեք մեզ հետ',
    badgeConfirmed: 'Հաստատված',
    showingBuildings: 'Ցուցադրվում է {n} շենք',
  },
};

// ?lang= wins (so a link can force one), then a saved choice, then the browser.
// Falling back per-key rather than per-language means a half-finished
// translation degrades to English one string at a time instead of all at once.
const LANG = (() => {
  const forced = new URLSearchParams(location.search).get('lang');
  if (forced && I18N[forced]) return forced;
  try {
    const saved = localStorage.getItem('lang');
    if (saved && I18N[saved]) return saved;
  } catch (e) { /* private mode — fall through to the browser's preference */ }
  for (const tag of navigator.languages || [navigator.language || '']) {
    const base = String(tag).toLowerCase().split('-')[0];
    if (I18N[base]) return base;
  }
  return 'en';
})();

const t = key => (I18N[LANG] && I18N[LANG][key]) || I18N.en[key] || key;
// A year folded into a string that carries it: t('afterYear') is "after {y}" in
// English and "{y}-ից հետո" in Armenian, because the word does not sit on the
// same side of the number in both.
const tYear = (key, year) => t(key).replace('{y}', year);

// What the evidence IS — three kinds, in the order the form offers them. The
// kind is not a statement about how it is attached: a plaque reaches us as a
// link to a photo of it (and, once uploads exist, as a photo taken on the
// spot), a published source as a URL or a scan. Must match SOURCE_KINDS in
// submission.py and functions/api/_shared.js.
const SOURCE_KINDS = ['plaque', 'online', 'local'];
// What each kind has to arrive with — and a plaque arrives with nothing.
//
// "There is a plaque on this building and it says 1965" is a claim a reviewer
// can go and check: Street View, or the walk past it. Demanding a link to a
// photo of it asks somebody standing in front of the thing to go and find
// somebody else's picture of it, which is the wrong way round. Once photo
// upload exists, that is where the photo goes.
const EVIDENCE_FLOOR = { plaque: null, online: 'url', local: 'note' };

// `mode` says what the page IS; `tiles` is a separate axis (where the data comes
// from), which is why it stays its own flag rather than becoming a third mode.
//
//   public   index.html, the deployed site — the suggest form, but only over
//            fields that are EMPTY, posting to /api/suggest for review. Nothing
//            it sends appears on the map until apply_queue.py merges it.
//   review   review.html — pending submissions as pins, approve/reject.
//            Protected by Cloudflare Access, not by anything in this file.


// ── The chrome, built once for both pages ──────────────────────────────────
//
// legend, stats, loader and banner used to be copy-pasted into each page, and
// they drifted exactly as copies do: only view.html ever got the data-i18n
// attributes, so the other pages were stuck in English with no language
// selector at all, and review.html had quietly lost its "Community
// Contributions" row.
//
// The markup lives here now and the pages are shells. The two pages share the
// map furniture — legend, year filter, theme, loader — and differ only where
// the job differs, which is what the `mode` branches below are: every one of
// them is a thing a reviewer needs and a visitor must not get, or the reverse.
// Collapsing them to one template once cost review.html its queue count and its
// "only what's pending" toggle, leaving initReviewQueue() writing to elements
// that were not on the page; the branches are named so that stays visible.
//
// The review-only strings are English and carry no data-i18n: that page is one
// maintainer behind Cloudflare Access, and translating a queue nobody else can
// open is work with no reader. The furniture it shares with the public map
// still follows the language selector, because it is the same markup.
function buildChrome(mode = 'public') {
  const isReview = mode === 'review';

  // The address is harvestable as written; that is the cost of a link needing
  // no JS and no service in the middle. On review it is replaced by the one
  // thing an approval does not do by itself: reach the map.
  const contact = isReview ? `
    <hr class="legend-divider">
    <p class="legend-contact">
      Approving marks the row. Run
      <code>python3 pipeline/apply_queue.py --apply</code>
      to merge approved suggestions into <code>suggestions.json</code> — that is
      where the additive rule is enforced.
    </p>` : `
    <hr class="legend-divider">
    <p class="legend-contact">
      <span data-i18n="contactLead"></span>
      <a data-i18n="contactLink"
         href="mailto:gev.urbanlayers@proton.me?subject=Urban%20Layers%3A%20Yerevan%20through%20time"></a>
    </p>`;

  // The count is the point of the review panel, so it sits outside
  // #legend-extra where it is readable without expanding anything. An
  // unreviewed queue is the failure mode that kills the whole phase —
  // contributors who see nothing happen stop contributing and do not come
  // back — and it fails silently unless the number is somewhere you look.
  // initReviewQueue() fills it.
  const reviewCount = isReview
    ? '<div id="review-count" class="review-count">…</div>' : '';

  // Six pending submissions in a city of 76,000 buildings are not findable by
  // eye. This outlines the ones waiting on you and drops the rest to a
  // backdrop; wired in initReviewQueue().
  const pendingOnly = isReview ? `
    <hr class="legend-divider">
    <label class="map-toggle">
      <input type="checkbox" id="pending-only">
      <span class="map-switch"></span>
      Only what's pending
    </label>` : '';

  // The colour ramp is the visitor's key to the whole map, so it stays above
  // the fold there. On review the queue count has that spot and the ramp moves
  // in with the rest of the detail.
  const gradient = `
    <div class="legend-gradient"></div>
    <div class="legend-labels"><span>≤1900</span><span>1960</span><span>2020+</span></div>`;

  document.body.insertAdjacentHTML('afterbegin', `
<div id="loader">
  <div class="spinner"></div>
  <strong data-i18n="loading"></strong>
  ${isReview ? '<p>Pending suggestions</p>' : '<p data-i18n="loadingSub"></p>'}
</div>

${isReview ? '' : '<div id="banner"><div id="wordmark">ՈւՌԲԱՆ ԼԷԵՐԶ</div></div>'}

<div id="map"></div>

<div id="legend">
  <div class="legend-header">
    ${isReview ? '<h3>Review queue</h3>' : '<h3 data-i18n="legendTitle"></h3>'}
    <button id="legend-toggle" class="legend-toggle" type="button"
            aria-expanded="false" aria-controls="legend-extra" aria-label="Toggle legend details">
      <span class="legend-toggle-chevron">⌃</span>
    </button>
  </div>
  ${isReview ? reviewCount : gradient}

  <div id="legend-extra">
    <hr class="legend-divider">
    ${isReview ? gradient + '\n    <hr class="legend-divider">' : ''}
    <label class="year-filter-label" data-i18n="filterLabel"></label>
    <div class="year-filter-row">
      <input type="number" id="year-filter-from" class="year-filter-input" data-i18n-placeholder="from">
      <span class="year-filter-sep">–</span>
      <input type="number" id="year-filter-to" class="year-filter-input" data-i18n-placeholder="to">
    </div>
    <div class="year-range-slider">
      <div class="year-range-track"></div>
      <div class="year-range-fill" id="year-range-fill"></div>
      <input type="range" id="year-range-min">
      <input type="range" id="year-range-max">
    </div>

    <!-- Directly under the handles, because it is what they describe: how many
         dated buildings fall inside the selected range, recomputed on every
         drag from the year index in stats.json. The whole string is written
         from JS so the number can sit wherever the translation puts it. -->
    <div id="stats"></div>${pendingOnly}
    <hr class="legend-divider">
    <label class="map-toggle">
      <input type="checkbox" id="theme-toggle">
      <span class="map-switch"></span>
      <span data-i18n="lightMode"></span>
    </label>
    <hr class="legend-divider">
    <label class="year-filter-label" for="lang-select" data-i18n="languageLabel"></label>
    <!-- Language names stay in their own language and are never translated —
         someone looking for Armenian is looking for "Հայերեն", not for whatever
         the current interface language calls it. -->
    <select id="lang-select" class="lang-select">
      <option value="en">English</option>
      <option value="hy">Հայերեն</option>
    </select>${contact}
  </div>
</div>
`);
}

// Remember a deliberate language choice, and re-render with it. A reload is the
// honest way to do this: every string is baked at popup-build time, so swapping
// the table under a live page would leave half the UI in the old one.
function wireLanguageSelect() {
  const sel = document.getElementById('lang-select');
  if (!sel) return;
  sel.value = LANG;
  sel.addEventListener('change', () => {
    try { localStorage.setItem('lang', sel.value); } catch (e) { /* private mode */ }
    const url = new URL(location.href);
    url.searchParams.set('lang', sel.value);
    location.href = url.toString();
  });
}

function initBuildingMap({ mode = 'public', tiles = false }) {
  const isPublic = mode === 'public';
  const isReview = mode === 'review';
  // the public map offers a form; review reads and approves
  const hasForm = isPublic;

  // Before any getElementById below: the page is a shell until this runs.
  buildChrome(mode);
  wireLanguageSelect();

  // Chrome is translated by attribute rather than by a table of element ids, so
  // adding a string is one attribute instead of two edits that can drift apart.
  // buildChrome() emits those attributes on everything both pages share, so the
  // public map translates whole — where previously only view.html did, because
  // it was the only page anyone had remembered to add the attributes to. The
  // review-only furniture carries no attributes and stays English on purpose.
  //
  // Translating only the popup form would have been half a job: someone who
  // needs Armenian to answer the questions needs it to find them.
  function applyChromeTranslations() {
    document.documentElement.lang = LANG;
    for (const el of document.querySelectorAll('[data-i18n]'))
      el.textContent = t(el.dataset.i18n);
    for (const el of document.querySelectorAll('[data-i18n-placeholder]'))
      el.placeholder = t(el.dataset.i18nPlaceholder);
  }
  applyChromeTranslations();
  // A building carries its year in one of these shapes (see classify_year in
  // fetch_buildings.py), and the map has to respect the difference rather than
  // flatten them all to one number:
  //
  //   year_built            exact          1965
  //   year_est              approximate    ~1965      (legacy — no longer offered)
  //   year_min + year_max   a closed span  1958–1972  (an era call)
  //   year_min alone        open at the top    after 1958
  //   year_max alone        open at the bottom before 1972
  //
  // POINT_YEAR is the first two — a single number either way. Everything else is
  // an interval, treated as one everywhere it can be, and collapsed to a scalar
  // only where that is unavoidable (the colour ramp).
  //
  // The two open shapes are what the suggest form now writes: someone who does
  // not know the year usually knows a side of it, and "after 1958" is a fact,
  // where the closed span they used to have to invent around it was not.
  const POINT_YEAR = ['coalesce', ['get', 'year_built'], ['get', 'year_est']];
  const HAS_LO = ['!=', ['get', 'year_min'], null];
  const HAS_HI = ['!=', ['get', 'year_max'], null];
  const IS_RANGE = ['any', HAS_LO, HAS_HI];
  // An open bound is ONE known year, so it becomes a zero-width interval at
  // that year — the bound stands in for the end it leaves open. "After 1958"
  // therefore behaves on the slider and the ramp exactly like 1958 does, which
  // is the only year anybody asserted about it. The alternative — widening the
  // open end to the edge of the data — would leave "before 1972" lit up at
  // every handle position from the 13th century on, which claims far more than
  // the submitter did. The popup is where the "before" is still said out loud.
  const SPAN_LO = ['coalesce', ['get', 'year_min'], ['get', 'year_max']];
  const SPAN_HI = ['coalesce', ['get', 'year_max'], ['get', 'year_min']];
  // every building as an interval: a single-number one — a point year, or an
  // open bound — is a zero-width range, which makes the filter below one
  // comparison for every shape
  const YEAR_LO = ['case', IS_RANGE, SPAN_LO, POINT_YEAR];
  const YEAR_HI = ['case', IS_RANGE, SPAN_HI, POINT_YEAR];
  // the one place a range must become a scalar: you cannot paint an interval
  // along a colour ramp. A khrushchevka lands on 1965, mid-era, which is where
  // it belongs — the popup is what tells you the span. An open bound's two ends
  // are the same year, so this collapses to that year for free.
  const YEAR_EXPR = ['case',
    IS_RANGE, ['/', ['+', SPAN_LO, SPAN_HI], 2],
    POINT_YEAR];

  const COLOR_STOPS = [
    1880, '#7b2d98',
    1950, '#214e91',
    2020, '#d6c41d',
  ];
  // no-data buildings need a different grey depending on theme so they stay
  // visible against either background — dark theme is the default
  const NO_DATA_COLORS = { dark: '#2f2f2f', light: '#c6c6c6' };
  const MAP_BACKGROUND = { dark: '#000000', light: '#eef0f2' };
  // One flat colour for every piece of water, lake and river alike: the exact
  // inverse of the background. Nothing on the era ramp is anywhere near pure
  // white or pure black, so water can never be mistaken for a building — it
  // reads as the city being cut away rather than as another data value.
  const WATER_COLORS = { dark: '#bdbdbd', light: '#bdbdbd' };
  let theme = 'dark';

  // whether a building counts as "on" for the current year filter: always
  // true with no bounds (fromYear/toYear both null), otherwise it needs a
  // year AND its interval must OVERLAP [fromYear, toYear] (either bound can
  // be omitted independently). Buildings that don't match are never hidden —
  // they're just recolored/dimmed exactly like no-data buildings already
  // are, via the same expressions below.
  //
  // Overlap, not containment, is the point of having ranges at all: dragging
  // the slider to 1958–1962 has to show the khrushchevkas, because one of them
  // really might have gone up in 1959. Testing a midpoint instead would hide
  // every one of them unless the handles happened to straddle 1965. For a
  // building with a single year lo == hi, so this reduces to exactly the
  // point-in-range test it always was.
  // The JS twin of yearMatchExpr, for counting instead of painting. It sums
  // stats.json's year_index — [lo, hi, bucket, count] per distinct span — so
  // the counters answer for the WHOLE city at any handle position, not for
  // whatever tiles happen to be loaded. Buckets are documented where the index
  // is built, in fetch_buildings.py.
  //
  // 247 spans, so this runs in microseconds and can sit in the drag path.
  function countInRange(index, fromYear, toYear) {
    if (!index) return null;
    const out = { confirmed: 0, community: 0, inferred: 0, total: 0 };
    for (const [lo, hi, bucket, n] of index) {
      if (fromYear !== null && hi < fromYear) continue;   // ends before we start
      if (toYear !== null && lo > toYear) continue;       // starts after we end
      if (bucket === 2) out.community += n;
      else if (bucket === 3) out.inferred += n;
      else out.confirmed += n;                            // 0 known + 1 suggested
      out.total += n;
    }
    return out;
  }

  function yearMatchExpr(fromYear, toYear) {
    const clauses = [['!=', YEAR_LO, null]];
    if (fromYear !== null) clauses.push(['>=', YEAR_HI, fromYear]);
    if (toYear !== null) clauses.push(['<=', YEAR_LO, toYear]);
    return clauses.length === 1 ? clauses[0] : ['all', ...clauses];
  }
  // A building's era colour depends only on its year, never on where the filter
  // handles are, so this is uploaded once per layer and never repainted. Dated
  // buildings therefore keep their colour whether in range or not — being out of
  // range shows as a fade to 0.15/0.12 opacity rather than a switch to grey, and
  // the slider only ever has to touch opacity. That keeps the expensive
  // per-feature interpolate out of the hot path entirely.
  //
  // To restore grey-when-out-of-range, wrap this per layer as
  //   ['case', yearMatchExpr(from, to), RAMP_COLOR, NO_DATA_COLORS[theme]]
  // and repaint that colour alongside the opacities in refreshYearPaint —
  // at the cost of re-evaluating it for every dated feature on every frame.
  const RAMP_COLOR = ['interpolate', ['linear'], YEAR_EXPR, ...COLOR_STOPS];
  // How hard a dated building recedes once it falls outside the year range.
  // Now that out-of-range buildings keep their era colour instead of going grey
  // (see RAMP_COLOR above), the fade is the only thing separating the selection
  // from everything else, so it's pushed well below the no-data greys further
  // down — deselected buildings should read as fainter than "we just don't know
  // about this one". These two numbers are the dial: raise them to bring the
  // ghosts back up, drop them toward 0 to make the selection stand alone.
  const OUT_FILL_OPACITY = 0.06;
  const OUT_EDGE_OPACITY = 0.05;

  // known/estimated years render identically — the popup's ~ prefix and
  // confidence badge are what signal an estimate, not a dimmer building
  function fillOpacityExpr(fromYear, toYear) {
    return ['case', yearMatchExpr(fromYear, toYear), 0.88, OUT_FILL_OPACITY];
  }
  function glowOpacityExpr(fromYear, toYear) {
    return ['case', yearMatchExpr(fromYear, toYear), 0.35, 0];
  }
  function edgeOpacityExpr(fromYear, toYear) {
    return ['case', yearMatchExpr(fromYear, toYear), 0.95, OUT_EDGE_OPACITY];
  }

  // ~96% of buildings have no year at all, and yearMatchExpr is false for every
  // one of them at every filter setting — their grey is identical no matter
  // where the handles sit. Kept in the same layers as the dated buildings they'd
  // still be re-evaluated on every slider move (data-driven paint is recomputed
  // per feature, per tile), so they're split into their own statically-painted
  // layers below. A slider drag then touches ~4k features instead of ~106k.
  // deliberately the same null test yearMatchExpr uses, rather than ['has',...]:
  // apply_queue.py writes an explicit null into the field it isn't using,
  // and ['has'] counts a null-valued key as present, which would file a building
  // under "dated" with no year to render.
  const HAS_YEAR = ['!=', YEAR_LO, null];
  const NO_YEAR = ['==', YEAR_LO, null];
  // A building whose year is one open bound — "after 1958" — is drawn hollow:
  // the era colour on the outline, the no-data grey inside. A solid block reads
  // as "we know when this went up", and for these we know one side of it and
  // nothing else; the building could sit anywhere on the open side of that
  // number. So it gets its colour, at the year it named, without the filled
  // body that would state a date the submitter never claimed.
  const IS_OPEN_BOUND = ['all', IS_RANGE, ['!', ['all', HAS_LO, HAS_HI]]];
  // everything else with a year: an exact date, a legacy ~year, or an era span,
  // all of which have two ends and get the solid treatment
  const HAS_YEAR_SOLID = ['all', HAS_YEAR, ['!', IS_OPEN_BOUND]];
  // the constants these layers freeze in — they're what the expressions above
  // resolve to for a feature with no year, so the two paths render identically
  const NO_DATA_FILL_OPACITY = 0.15;
  const NO_DATA_EDGE_OPACITY = 0.12;

  // null/undefined, or a real value — one test, because the tile path drops a
  // null-valued key entirely while the GeoJSON path writes an explicit null
  const has = v => v !== null && v !== undefined;

  // confidence isn't stored in the data (see fetch_buildings.py) — it's fully
  // derivable from year_built/year_est/year_min/year_max/year_tag, in either
  // data path
  function deriveConfidence(p) {
    if (p.year_tag === 'suggested') return 'suggested';
    if (has(p.year_built)) return 'known';
    if (has(p.year_est)) return 'inferred';
    if (has(p.year_min) || has(p.year_max)) return 'inferred';
    return null;
  }

  // the year fields as a plain [lo, hi] interval, the JS twin of YEAR_LO/YEAR_HI
  // above — [null, null] when the building has no year at all, and [y, y] for a
  // single known year, whether that is a date or an open bound standing in for
  // the end it leaves open
  function yearBounds(p) {
    if (has(p.year_min) || has(p.year_max))
      return [p.year_min ?? p.year_max, p.year_max ?? p.year_min];
    const y = p.year_built ?? p.year_est;
    return has(y) ? [y, y] : [null, null];
  }

  // A building's year as plain text, in whatever shape it holds — the single
  // place that decides how a year READS. The popup wraps it in its own classes
  // and the report form shows it as the value being disputed; both have to say
  // the same thing about the same building, so neither formats its own.
  function yearLabel(p) {
    if (has(p.year_min) || has(p.year_max)) {
      if (has(p.year_min) && has(p.year_max)) return `${p.year_min}-${p.year_max}`;
      return has(p.year_min) ? tYear('afterYear', p.year_min) : tYear('beforeYear', p.year_max);
    }
    if (has(p.year_built)) return String(p.year_built);
    if (has(p.year_est)) return tYear('approxYear', p.year_est);
    return '';
  }

  // Same shape as stats.json, counted client-side when every feature is in
  // memory. Only the GeoJSON path can do this — and it has to, because the
  // counters must move the moment you save an edit.
  function countStats(features) {
    const stats = { total: features.length, known: 0, suggested: 0, community: 0,
                    inferred: 0, unknown: 0, min_year: null, max_year: null };
    for (const f of features) {
      const c = deriveConfidence(f.properties);
      stats[c === null ? 'unknown' : c]++;
      // A subset of `suggested`, counted the same way fetch_buildings.py does:
      // the `community` flag is set only where an accepted public submission
      // supplied the year, so this never double-counts a bucket.
      if (c === 'suggested' && f.properties.community) stats.community++;
      // reduce rather than Math.min(...years): spreading a 100k-element array
      // can overflow the call stack.
      // A ranged building contributes both bounds — the slider has to be able
      // to reach either end of an era, not just its middle.
      const [lo, hi] = yearBounds(f.properties);
      if (lo !== null) {
        if (stats.min_year === null || lo < stats.min_year) stats.min_year = lo;
        if (stats.max_year === null || hi > stats.max_year) stats.max_year = hi;
      }
    }
    return stats;
  }

  const map = new maplibregl.Map({
    container: 'map',
    style: {
      version: 8,
      sources: {},
      layers: [{
        id: 'background',
        type: 'background',
        paint: { 'background-color': '#000000' }
      }]
    },
    center: [44.5136, 40.1872],
    zoom: 13,
    // No zoom buttons or compass: scroll/pinch/double-tap cover zooming, and the
    // canvas still takes +/- and arrow keys once focused. Rotation and pitch are
    // switched off with them — a flat colour-by-year map gains nothing from a
    // bearing, and without a compass button an accidental two-finger twist while
    // pinching would leave the map askew with no visible way to straighten it.
    dragRotate: false,
    pitchWithRotate: false
  });
  map.touchZoomRotate.disableRotation(); // keeps pinch-zoom, drops the twist

  // ── URL state ──────────────────────────────────────────────────────────────
  //
  // Two shapes, because they answer different questions:
  //
  //   #13/40.1872/44.5136              a view    — "look at this part of town"
  //   #b=524357988@44.5136,40.1872,17  a building — "look at THIS building"
  //
  // The building form carries coordinates as well as the id, and has to. With
  // vector tiles a feature only exists once its tile is loaded, so an id alone
  // is unresolvable: there is no index to look it up in and no way to know where
  // to fly. The coordinates make the link work before the data arrives, and the
  // id is then matched against what actually rendered.
  //
  // This is also what makes moderation possible at all — a queued submission
  // stores exactly these three numbers, so a reviewer lands on the building
  // instead of hunting for it.
  const HASH_VIEW = /^#(\d+(?:\.\d+)?)\/(-?\d+(?:\.\d+)?)\/(-?\d+(?:\.\d+)?)$/;
  const HASH_BUILDING = /^#b=(\d+)@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)(?:,(\d+(?:\.\d+)?))?$/;

  function parseHash(hash = location.hash) {
    let m = HASH_BUILDING.exec(hash);
    if (m) return { id: m[1], lng: +m[2], lat: +m[3], zoom: m[4] ? +m[4] : 17 };
    m = HASH_VIEW.exec(hash);
    if (m) return { zoom: +m[1], lat: +m[2], lng: +m[3] };
    return null;
  }

  // replaceState, not a hash assignment: panning the map must not fill the back
  // button with every intermediate position. A deep link the user actually
  // opened is already in history, and closing the popup should return them to
  // the map rather than to the previous building.
  let suppressHashWrite = false;
  function writeHash(hash) {
    if (suppressHashWrite || location.hash === hash) return;
    history.replaceState(null, '', hash || location.pathname + location.search);
  }

  function writeViewHash() {
    const c = map.getCenter();
    writeHash(`#${map.getZoom().toFixed(2)}/${c.lat.toFixed(5)}/${c.lng.toFixed(5)}`);
  }

  function buildingHash(id, lngLat) {
    return `#b=${id}@${lngLat.lng.toFixed(6)},${lngLat.lat.toFixed(6)},`
         + `${Math.max(16, map.getZoom()).toFixed(0)}`;
  }

  // Applied before the data loads so the map never flashes the default view
  // first. A building link jumps to its coordinates now; opening the popup waits
  // for the feature to actually render (see openDeepLink below).
  const initialHash = parseHash();
  if (initialHash) {
    map.jumpTo({ center: [initialHash.lng, initialHash.lat], zoom: initialHash.zoom });
  }

  // Without this, a failing tile source is silent: MapLibre reports source and
  // tile errors through this event rather than throwing, so the page just sits
  // there with no buildings and no clue why. Shown on the page as well as logged,
  // because the console isn't always to hand (Safari hides it by default).
  map.on('error', e => {
    const err = (e && e.error) || e;
    console.error('[map error]', err);
    let box = document.getElementById('map-error');
    if (!box) {
      box = document.createElement('div');
      box.id = 'map-error';
      box.style.cssText = 'position:fixed;left:10px;top:10px;z-index:9999;max-width:70vw;' +
        'background:#2a0f0f;color:#ffb4b4;border:1px solid #a33;border-radius:6px;' +
        'padding:8px 10px;font:12px/1.4 ui-monospace,monospace;white-space:pre-wrap';
      document.body.appendChild(box);
    }
    const line = (err && err.message) || String(err && err.type || err);
    if (!box.textContent.includes(line)) {
      box.textContent += (box.textContent ? '\n' : '⚠ ') + line;
    }
  });

  map.on('load', () => {
    const themeToggle = document.getElementById('theme-toggle');
    let refreshBuildingPaint = null; // set once the buildings layers exist, below
    let refreshWaterPaint = null;    // likewise, and stays null if water.geojson is missing

    function applyTheme() {
      document.documentElement.dataset.theme = theme;
      map.setPaintProperty('background', 'background-color', MAP_BACKGROUND[theme]);
      if (refreshWaterPaint) refreshWaterPaint();
      if (refreshBuildingPaint) refreshBuildingPaint();
    }

    themeToggle.addEventListener('change', () => {
      theme = themeToggle.checked ? 'light' : 'dark';
      applyTheme();
    });
    applyTheme();

    // The legend collapses on every screen now, so this is the normal way in
    // to the year filter and the counts rather than a small-screen affordance.
    const legend = document.getElementById('legend');
    const legendToggle = document.getElementById('legend-toggle');
    legendToggle.addEventListener('click', () => {
      const expanded = legend.classList.toggle('legend-expanded');
      legendToggle.setAttribute('aria-expanded', String(expanded));
    });

    const loadJSON = (url) => fetch(url).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status} on ${url} — run fetch_buildings.py first`);
      return r.json();
    });

    // The two data paths. GeoJSON keeps every feature in memory, which is what
    // lets the local editor recolor a building the instant it's saved and recount
    // the totals live. PMTiles only ever holds the tiles on screen, so nothing can
    // be counted or patched client-side there — the totals and the slider bounds
    // come from stats.json, computed by fetch_buildings.py at build time.
    const dataReady = tiles
      ? loadJSON('stats.json').then(stats => ({ geojson: null, stats }))
      : loadJSON('buildings.geojson').then(geojson => ({ geojson, stats: countStats(geojson.features) }));

    // Backdrop, not data: the Hrazdan and Yerevan Lake are what let you tell
    // where you are on a map with no labels and 106k identical grey footprints.
    // It's one small static file (17 features, 6KB gzipped) rather than part of
    // the tileset, because it never changes and there is no view small enough to
    // be worth fetching a fraction of it.
    //
    // Deliberately not fatal. Water is decoration, and a missing water.geojson
    // (nobody has run fetch_water.py yet) must not stop the actual map from
    // rendering — dataReady's .catch shows a "run fetch_buildings.py" screen,
    // which would be entirely the wrong advice here.
    const waterReady = loadJSON('water.geojson').catch(() => null);

    Promise.all([dataReady, waterReady])
      .then(([{ geojson, stats }, water]) => {
        document.getElementById('loader').style.display = 'none';
        document.getElementById('stats').style.display = 'block';

        const fmt = n => n.toLocaleString();
        // One line, not a breakdown: how many buildings the handles are
        // currently lighting up. The count is of DATED buildings — the ones the
        // filter can actually include or exclude — since the ~74k with no year
        // are drawn faded at every handle position and never change.
        function setShowing(n) {
          const el = document.getElementById('stats');
          if (el) el.textContent = t('showingBuildings').replace('{n}', fmt(n));
        }

        // The build-time snapshot, for the moment before the first paint: the
        // slider opens at full range, so this is the same number countInRange
        // gives for [null, null], and refreshYearPaint takes over from here.
        setShowing(stats.known + stats.suggested + stats.inferred);

        // Keep the viewport inside the area that actually has tiles. Beyond it
        // there's nothing to draw — panning off into empty space just looks
        // broken, and every such tile request is a 404 (or worse on Pages, a
        // 200 serving index.html). minZoom matches the tiles' own -Z10; below
        // that no tiles were ever generated.
        //
        // stats.bounds only exists on the tiled build — countStats() doesn't
        // compute it — so the local editor stays unconstrained, which is what
        // you want when checking data at the edges.
        if (stats.bounds) {
          const [w, s, e, n] = stats.bounds;
          const pad = 0.01; // ~1km of breathing room so edge buildings aren't jammed against the frame
          map.setMaxBounds([[w - pad, s - pad], [e + pad, n + pad]]);
        }
        map.setMinZoom(10);
        map.setMaxZoom(19); // tiles stop at z16; MapLibre overzooms them, but past
                            // ~19 it's just blur with no more detail to reveal

        // ODbL requires visible credit wherever this data is shown. Declaring it on
        // the source (rather than as a loose UI string) means the attribution
        // control picks it up automatically and it stays attached to the data if
        // the layers or controls are ever rearranged. MapLibre credits itself, and
        // its bundle carries its own @license banner, so nothing is needed for it.
        // The wordmark face is credited as a courtesy — its terms ask for nothing.
        const ATTRIBUTION =
          '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors · ' +
          '<a href="https://opendatacommons.org/licenses/odbl/" target="_blank">ODbL</a> · ' +
          'wordmark <a href="https://www.armeniapedia.org/wiki/Armenian_Fonts" target="_blank">Armeniapedia Kisat</a> © Raffi Kojian';

        if (tiles) {
          // Plain z/x/y tiles rather than a single .pmtiles archive: a PMTiles file
          // is read by HTTP range request, and Cloudflare Pages ignores Range
          // entirely — it answers every one with the whole 17MB file. Individual
          // tiles need no ranges, are cached per-tile by the CDN, drop the pmtiles
          // dependency, and work on any static host.
          //
          // promoteId reuses the OSM id as the feature id, which is what
          // setFeatureState keys off for hover. It replaces generateId (vector
          // sources have no such option) and is actually better: an id from the
          // data is stable across tiles, so a building straddling a tile boundary
          // highlights as one building rather than two halves.
          map.addSource('buildings', {
            type: 'vector',
            // the {z}/{x}/{y} placeholders are appended AFTER resolving the base:
            // new URL() percent-encodes braces (%7Bz%7D), which MapLibre then
            // never substitutes, so every tile request 404s on a literal path
            //
            // ?v= is the build id from stats.json — a hash of the data the tiles
            // were cut from (see BUILD_ID in fetch_buildings.py). Tiles are
            // cached hard, and without this a contributor whose suggestion was
            // just approved keeps seeing their own building grey: the browser
            // holds the tile it fetched before the merge and never asks again.
            // A new build changes the id, which changes the URL, which is a
            // cache miss — and a build that changed nothing keeps the id, so
            // nobody re-downloads 29MB for free. Absent (an older stats.json):
            // no query string, exactly the behaviour that shipped before.
            tiles: [new URL('tiles/', location.href).href + '{z}/{x}/{y}.pbf'
                    + (stats.build ? `?v=${stats.build}` : '')],
            minzoom: 10,   // must match build_public.sh's -Z/-z, or MapLibre asks
            maxzoom: 16,   // for tiles that were never generated
            // Confine requests to the area tiles were actually built for.
            // tippecanoe only writes tiles where features exist, and Cloudflare
            // Pages answers a missing file with 200 + index.html rather than a
            // 404 — MapLibre then tries to parse HTML as protobuf and reports
            // "Unimplemented type: 4". Bounds stop those requests being made.
            ...(stats.bounds ? { bounds: stats.bounds } : {}),
            promoteId: 'id',
            attribution: ATTRIBUTION
          });
        } else {
          map.addSource('buildings', {
            type: 'geojson',
            data: geojson,
            generateId: true,
            attribution: ATTRIBUTION,
            // default is 128 — a wide skirt of geometry duplicated into every
            // neighbouring tile. The widest thing drawn here is the 4px glow with
            // 6px of blur, so 32 covers it with far less per-tile geometry to
            // tessellate, hold, and re-upload on each repaint.
            buffer: 32
          });
        }

        // vector tiles address features by layer name inside the tile; a GeoJSON
        // source has no such concept, so this is spread into each addLayer call
        const SRC_LAYER = tiles ? { 'source-layer': 'buildings' } : {};

        // ── water: pure backdrop ────────────────────────────────────────────
        //
        // Added before every building layer, which is the whole of what puts it
        // underneath — MapLibre draws in insertion order, so nothing here needs
        // a beforeId.
        //
        // These layers are never interactive. Every hover, cursor and popup
        // handler further down is registered against FILL_LAYERS by name, and
        // both queryRenderedFeatures calls pass that same list, so water is not
        // hit-tested at all: no pointer cursor, no highlight, no popup. Clicking
        // the river counts as clicking empty map and closes an open popup, which
        // is what you want from a background. Keep it that way — adding 'water'
        // to FILL_LAYERS is all it would take to break it.
        if (water) {
          map.addSource('water', { type: 'geojson', data: water, attribution: ATTRIBUTION });

          map.addLayer({
            id: 'water-fill',
            type: 'fill',
            source: 'water',
            filter: ['!=', ['geometry-type'], 'LineString'],
            paint: { 'fill-color': WATER_COLORS[theme] }
          });

          // Rivers are drawn as lines rather than given a width in metres: OSM
          // maps the Hrazdan as a centreline, and at z10 a true-width river
          // would be sub-pixel and vanish. Widening with zoom keeps it legible
          // across the whole range instead.
          map.addLayer({
            id: 'water-line',
            type: 'line',
            source: 'water',
            filter: ['==', ['geometry-type'], 'LineString'],
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: {
              'line-color': WATER_COLORS[theme],
              'line-width': ['interpolate', ['exponential', 1.6], ['zoom'],
                             10, 1, 13, 3, 16, 9, 19, 26]
            }
          });

          refreshWaterPaint = () => {
            map.setPaintProperty('water-fill', 'fill-color', WATER_COLORS[theme]);
            map.setPaintProperty('water-line', 'line-color', WATER_COLORS[theme]);
          };
        }

        // ── no-data buildings: static paint, never rebuilt by the year filter ──
        // no glow counterpart: glowOpacityExpr resolves to 0 for these, so the
        // halo layer would be invisible anyway.
        map.addLayer({
          id: 'buildings-fill-nodata',
          type: 'fill',
          source: 'buildings',
          ...SRC_LAYER,
          filter: NO_YEAR,
          paint: {
            'fill-color': NO_DATA_COLORS[theme],
            'fill-opacity': NO_DATA_FILL_OPACITY
          }
        });

        map.addLayer({
          id: 'buildings-edge-nodata',
          type: 'line',
          source: 'buildings',
          ...SRC_LAYER,
          filter: NO_YEAR,
          paint: {
            'line-color': NO_DATA_COLORS[theme],
            'line-width': 0.8,
            'line-opacity': NO_DATA_EDGE_OPACITY
          }
        });

        // ── open bounds: grey body, era-coloured edge ─────────────────────────
        // The interior is the no-data grey at the no-data opacity, statically —
        // the same paint a building with no year at all gets, because that is
        // what the inside of this one is: unknown. Only the edge layer below
        // picks it up in colour. Static like the no-data layers, so the slider
        // never repaints it; what responds to the filter is the outline.
        map.addLayer({
          id: 'buildings-fill-openbound',
          type: 'fill',
          source: 'buildings',
          ...SRC_LAYER,
          filter: IS_OPEN_BOUND,
          paint: {
            'fill-color': NO_DATA_COLORS[theme],
            'fill-opacity': NO_DATA_FILL_OPACITY
          }
        });

        // ── dated buildings: the only layers the year filter has to repaint ──
        // Open bounds are excluded from the fill and the glow — the two things
        // that would make one read as solid — and included in the edge, which is
        // what carries their colour.
        map.addLayer({
          id: 'buildings-fill',
          type: 'fill',
          source: 'buildings',
          ...SRC_LAYER,
          filter: HAS_YEAR_SOLID,
          paint: {
            'fill-color': RAMP_COLOR,
            'fill-opacity': fillOpacityExpr(null, null)
          }
        });

        // wide blurred line = glow halo
        map.addLayer({
          id: 'buildings-glow',
          type: 'line',
          source: 'buildings',
          ...SRC_LAYER,
          filter: HAS_YEAR_SOLID,
          paint: {
            'line-color': RAMP_COLOR,
            'line-width': 4,
            'line-blur': 6,
            'line-opacity': glowOpacityExpr(null, null)
          }
        });

        // tight bright edge
        map.addLayer({
          id: 'buildings-edge',
          type: 'line',
          source: 'buildings',
          ...SRC_LAYER,
          filter: HAS_YEAR,
          paint: {
            'line-color': RAMP_COLOR,
            // a hollow building is only its outline, so the outline carries a
            // little more weight — at z13 a small block is a few pixels across,
            // and a 0.8px edge around a grey body would read as no data at all.
            // Static, like the colour: it never changes with the slider.
            'line-width': ['case', IS_OPEN_BOUND, 1.4, 0.8],
            'line-opacity': edgeOpacityExpr(null, null)
          }
        });

        // hover border — wide blurred white glow
        map.addLayer({
          id: 'buildings-hover-glow',
          type: 'line',
          source: 'buildings',
          ...SRC_LAYER,
          paint: {
            'line-color': '#ffffff',
            'line-width': ['case', ['boolean', ['feature-state', 'hover'], false], 6, 0],
            'line-blur':  4,
            'line-opacity': 0.45
          }
        });

        // hover border — sharp bright edge
        map.addLayer({
          id: 'buildings-hover-edge',
          type: 'line',
          source: 'buildings',
          ...SRC_LAYER,
          paint: {
            'line-color': '#ffffff',
            'line-width':   ['case', ['boolean', ['feature-state', 'hover'], false], 1.5, 0],
            'line-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.9, 0]
          }
        });

        // ── year filter — historical snapshot ───────────────────────────────────
        // a two-sided range: buildings outside [from, to] grey out the same
        // way no-data buildings already render — nothing is ever hidden,
        // only recolored. Either bound can be left blank. Two number fields
        // and a dual-handle slider (two overlaid native <input type=range>,
        // see map.css) both drive the same state and stay in sync, so people
        // who'd rather type a year than drag a handle can just do that.
        const fromInput = document.getElementById('year-filter-from');
        const toInput = document.getElementById('year-filter-to');
        const rangeMin = document.getElementById('year-range-min');
        const rangeMax = document.getElementById('year-range-max');
        const rangeFill = document.getElementById('year-range-fill');

        // both data paths land here: counted from the features when they're all in
        // memory, read from stats.json when they aren't
        const dataMinYear = stats.min_year ?? 1800;
        const dataMaxYear = stats.max_year ?? new Date().getFullYear();

        rangeMin.min = rangeMax.min = dataMinYear;
        rangeMin.max = rangeMax.max = dataMaxYear;
        rangeMin.value = dataMinYear;
        rangeMax.value = dataMaxYear;
        fromInput.placeholder = `${dataMinYear}`;
        toInput.placeholder = `${dataMaxYear}`;

        function parseYearOr(input, fallback) {
          const v = parseInt(input.value, 10);
          return Number.isFinite(v) ? Math.max(dataMinYear, Math.min(v, dataMaxYear)) : fallback;
        }

        function updateRangeFill() {
          const span = dataMaxYear - dataMinYear || 1;
          const lo = Math.min(+rangeMin.value, +rangeMax.value);
          const hi = Math.max(+rangeMin.value, +rangeMax.value);
          rangeFill.style.left = `${((lo - dataMinYear) / span) * 100}%`;
          rangeFill.style.width = `${((hi - lo) / span) * 100}%`;
        }
        updateRangeFill();

        // the expensive half: six data-driven expressions, re-evaluated per
        // feature per tile. Only the dated buildings are in these layers now.
        function refreshYearPaint() {
          const fromYear = parseYearOr(fromInput, null);
          const toYear = parseYearOr(toInput, null);

          // colour is static on all three layers now (see addLayer) — only
          // opacity depends on where the handles are
          map.setPaintProperty('buildings-fill', 'fill-opacity', fillOpacityExpr(fromYear, toYear));
          map.setPaintProperty('buildings-glow', 'line-opacity', glowOpacityExpr(fromYear, toYear));
          map.setPaintProperty('buildings-edge', 'line-opacity', edgeOpacityExpr(fromYear, toYear));

          // The counters describe the same selection the paint just made, so
          // they are refreshed from the same two numbers rather than left to
          // report a city-wide total that the handles have stopped describing.
          const counts = countInRange(stats && stats.year_index, fromYear, toYear);
          if (counts) setShowing(counts.total);
        }

        // the cheap half: a constant colour, so only the theme can change it —
        // no need to touch these while the slider moves
        function refreshNoDataPaint() {
          map.setPaintProperty('buildings-fill-nodata', 'fill-color', NO_DATA_COLORS[theme]);
          map.setPaintProperty('buildings-edge-nodata', 'line-color', NO_DATA_COLORS[theme]);
          // the hollow shapes' interiors are the same grey, and follow it
          map.setPaintProperty('buildings-fill-openbound', 'fill-color', NO_DATA_COLORS[theme]);
        }

        refreshBuildingPaint = function () {
          refreshYearPaint();
          refreshNoDataPaint();
        };

        // A native range input fires `input` continuously while dragging, about
        // once per frame, and each refreshYearPaint() rebuilds paint buffers for
        // every feature in every loaded tile. One rebuild per event queues far
        // more work than can drain, so the map goes on catching up long after
        // the handle stopped — that's the lag. Coalescing to at most one rebuild
        // per frame keeps the newest handle position and drops the superseded
        // ones, which are about to be overwritten anyway.
        let paintFrame = null;
        function scheduleYearPaint() {
          if (paintFrame !== null) return;
          paintFrame = requestAnimationFrame(() => {
            paintFrame = null;
            refreshYearPaint();
          });
        }

        function syncFromSliders() {
          fromInput.value = rangeMin.value;
          toInput.value = rangeMax.value;
          updateRangeFill();
          scheduleYearPaint();
        }
        function syncFromInputs() {
          rangeMin.value = parseYearOr(fromInput, dataMinYear);
          rangeMax.value = parseYearOr(toInput, dataMaxYear);
          updateRangeFill();
          scheduleYearPaint();
        }

        rangeMin.addEventListener('input', () => {
          if (+rangeMin.value > +rangeMax.value) rangeMin.value = rangeMax.value;
          syncFromSliders();
        });
        rangeMax.addEventListener('input', () => {
          if (+rangeMax.value < +rangeMin.value) rangeMax.value = rangeMin.value;
          syncFromSliders();
        });
        fromInput.addEventListener('input', syncFromInputs);
        toInput.addEventListener('input', syncFromInputs);

        // ── popup ────────────────────────────────────────────────────────────
        // name/address can come from an approved submission (see apply_queue.py)
        // as well as raw OSM tags, so escape before dropping either into innerHTML
        function escapeHTML(s) {
          return String(s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
          }[c]));
        }

        // ── The additive rule, client side ───────────────────────────────────
        //
        // A field is open for public suggestion iff the built feature has no
        // value for it. Anything the map DISPLAYS is a claim, and changing a
        // claim is a correction — a separate flow, not this one. So an inferred
        // era span closes the year exactly as a confirmed date does: no
        // confidence-tier reasoning anywhere in this path.
        //
        // The JS twin of is_open() in submission.py. This one is UX — it decides
        // which inputs to draw. It is NOT the guarantee: a hostile client can
        // post anything, so additivity is enforced in apply_queue.py, which is
        // the only place that can see the built dataset. See
        // docs/submission-schema.md §1.
        const YEAR_PROPS = ['year_built', 'year_est', 'year_min', 'year_max'];
        // the same field under the names a SUBMISSION uses (docs/submission-schema.md
        // §2), which is what the pending marker records
        const YEAR_KEYS = ['year', 'approx', 'year_min', 'year_max'];
        const filled = v => v !== null && v !== undefined && v !== '';

        function fieldIsOpen(p, field) {
          if (field === 'year') return !YEAR_PROPS.some(k => filled(p[k]));
          return !filled(p[field]);
        }

        // What the additive form may ask for: the missing year, and nothing else.
        //
        // Name and address left this list when the report flow arrived. A name
        // invited people to invent a label ("5-storey block") where the address
        // already identifies the building, and an address is something the map
        // is usually only half-right about — half-right is a correction, which
        // is what the report form is for. Both still reach the data through a
        // report, where a blank fact is simply one whose current value is empty.
        //
        // This list is the whole mechanism: an input renders only for a field in
        // `open`, the submitted `before` is built from `open`, and a pending
        // marker can only block on a field that is in it.
        const PUBLIC_FIELDS = ['year'];
        const openFields = p => PUBLIC_FIELDS.filter(f => fieldIsOpen(p, f));

        // ── "you already suggested this" ─────────────────────────────────────
        //
        // A queued suggestion cannot change the map: the tiles are prebuilt and
        // nothing is published before review. Correct, and it reads exactly like
        // failure — so people submit again, and the queue fills with duplicates
        // of the same building. Remembering it locally is the whole fix.
        //
        // Per-browser and best-effort by design. It is a courtesy, not a record;
        // the queue is the record.
        //
        // A marker has to END, though, and the map itself is the only signal
        // this browser gets: nothing tells it a submission was approved. So the
        // marker records WHICH fields were suggested, and once the build shows
        // those fields filled the review is demonstrably over — see landedPending
        // below. Without that the note outlived the thing it described by up to
        // PENDING_TTL_MS, telling a contributor their year was under review for
        // two months after it went live.
        const PENDING_KEY = 'mappio-pending';
        const PENDING_TTL_MS = 60 * 24 * 3600 * 1000;   // long enough to outlast a slow review

        // {id: {at, fields}}. Entries written before this shape existed are bare
        // timestamps; normalised here so nothing downstream has to know that.
        function readPending() {
          try {
            const raw = JSON.parse(localStorage.getItem(PENDING_KEY)) || {};
            const cutoff = Date.now() - PENDING_TTL_MS;
            const out = {};
            for (const [id, value] of Object.entries(raw)) {
              const entry = typeof value === 'number' ? { at: value, fields: null } : value;
              // A marker still waiting for review expires — a queue this small
              // should never take 60 days, and a note about a submission nobody
              // acted on eventually just misinforms. One that LANDED is the
              // opposite: it records that this browser put something on the map,
              // which does not stop being true, so the TTL does not touch it.
              if (entry && (entry.landed || entry.at > cutoff)) out[id] = entry;
            }
            return out;
          } catch (e) {
            return {};   // private mode, or someone else's key — not worth reporting
          }
        }

        function writePending(all) {
          try {
            localStorage.setItem(PENDING_KEY, JSON.stringify(all));
          } catch (e) { /* the form still worked; only the reminder is lost */ }
        }

        // `was` is a report's observed values (the same object it sent as
        // `before`). A suggestion has none: the field was empty, and there is
        // nothing to compare against.
        function markPending(id, fields, was) {
          const all = readPending();
          all[id] = { at: Date.now(), fields, ...(was ? { was } : {}) };
          writePending(all);
        }

        // Kept, not deleted: the thank-you is the only acknowledgement this site
        // can ever give somebody, and it should still be there the next time
        // they show the building to a friend.
        function markLanded(id) {
          const all = readPending();
          if (!all[id]) return;
          all[id] = { ...all[id], landed: true };
          writePending(all);
        }

        // Does the build this browser is looking at still show what the map
        // showed the tiles it still has? The JS twin of matches_observed() in
        // submission.py, and the same question the merge asks.
        function stillShows(p, was) {
          for (const [field, value] of Object.entries(was)) {
            if (field === 'year') {
              const now = {};
              for (const key of YEAR_PROPS) if (filled(p[key])) now[key] = p[key];
              const then = value || {};
              const keys = new Set([...Object.keys(now), ...Object.keys(then)]);
              for (const key of keys) if (now[key] !== then[key]) return false;
            } else if ((p[field] || null) !== (value || null)) {
              return false;
            }
          }
          return true;
        }

        // Has the thing this marker describes reached the map?
        //
        // The two kinds cannot be asked the same question, and asking the wrong
        // one is a bug I shipped: a SUGGESTION lands when the field it filled
        // stops being empty, but a REPORT disputes a field that was never empty,
        // so "is it still open?" answers no the instant the report is sent —
        // the contributor got thanked for a correction nobody had reviewed yet,
        // and the note was consumed before the real thing arrived.
        //
        // A report lands when the VALUE stops being the one it disputed, which
        // is exactly what the merge checks before applying it. A rejected report
        // never lands: the value stays, and the marker retires with the TTL.
        //
        // A legacy marker names no fields, so the only safe read is the whole
        // form being closed.
        function landedPending(entry, open, p) {
          // once acknowledged it stays acknowledged, whatever happens to the
          // value afterwards — somebody else's later correction does not undo
          // the fact that this browser contributed
          if (entry.landed) return true;
          if (entry.was) return !stillShows(p, entry.was);
          return entry.fields ? entry.fields.every(f => !open.includes(f)) : !open.length;
        }

        function publicFormHTML(p) {
          const open = openFields(p);
          const pending = readPending()[p.id];
          let landedHTML = '';
          if (pending) {
            if (!landedPending(pending, open, p)) {
              return `<div class="p-edit p-pending">${
                escapeHTML(t(pending.was ? 'pendingReport' : 'pending'))}</div>`;
            }
            // It made it. This is the only acknowledgement the site can give,
            // so it is written into the marker rather than shown once and lost.
            if (!pending.landed) markLanded(p.id);
            landedHTML = `<p class="p-landed">${escapeHTML(t('thanksLive'))}</p>`;
          }
          // Nothing left to add is the common case — most of what this map knows
          // about a building it already shows — and it needs no words: the popup
          // simply ends after the year and the address. It used to say so, and
          // point at the contact link for corrections, but the legend carries
          // that line for the whole map now, so in the popup it was the same
          // sentence repeated once per building.
          //
          // The one thing still worth a line here is a suggestion that just went
          // live, which is about THIS building and appears once.
          if (!open.length) {
            return landedHTML ? `<div class="p-edit p-nothing">${landedHTML}</div>` : '';
          }

          const textInput = (field, cls, cap) => open.includes(field) ? `
                <input class="${cls}" type="text" maxlength="${cap}"
                       placeholder="${escapeHTML(t(field === 'name' ? 'name'
                                       : field === 'addr_street' ? 'street' : 'number'))}">` : '';

          // Two answers, not three: the year, or the range it falls in.
          // "approx" is gone — it asked a contributor to grade their own
          // certainty on a scale nobody shares.
          //
          // The range is two boxes and BOTH are optional. Filling both is a
          // span; filling one is the half-open claim that side makes — "after
          // 1958", "before 1972" — which is what somebody who watched the block
          // go up actually knows. Nothing asks them which; the empty box says
          // it. The hint is on screen because an input that is allowed to stay
          // empty has to say so.
          const modeOption = value => `
                  <label class="p-year-mode-opt">
                    <input type="radio" name="p-year-mode" value="${value}"
                           ${value === 'exact' ? 'checked' : ''}><span>${escapeHTML(t(value))}</span>
                  </label>`;
          const yearHTML = open.includes('year') ? `
              <div class="p-year-mode">
                ${modeOption('exact')}${modeOption('range')}
              </div>
              <div class="p-edit-year-row">
                <input class="p-suggest-input" type="number" inputmode="numeric" min="1" max="2030"
                       placeholder="${escapeHTML(t('year'))}">
                <span class="p-suggest-sep">–</span>
                <input class="p-suggest-to" type="number" inputmode="numeric" min="1" max="2030"
                       placeholder="${escapeHTML(t('to'))}">
              </div>
              <div class="p-year-hint">${escapeHTML(t('rangeHint'))}</div>` : '';

          const addrRow = (open.includes('addr_street') || open.includes('addr_number')) ? `
              <div class="p-edit-addr-row">
                ${textInput('addr_street', 'p-edit-street', 200)}
                ${textInput('addr_number', 'p-edit-number', 20)}
              </div>` : '';


          return `
            <div class="p-edit p-public">
              ${landedHTML}
              ${textInput('name', 'p-edit-name', 200)}
              ${addrRow}
              ${yearHTML}
              ${evidenceHTML()}
              <!-- Honeypot: hidden from people, irresistible to naive bots. A
                   filled one is answered with a cheerful 200 and dropped, so the
                   endpoint never becomes an oracle for tuning past the filter. -->
              <input class="p-website" type="text" name="website" tabindex="-1"
                     autocomplete="off" aria-hidden="true">
              <div class="p-turnstile"></div>
              <button class="p-edit-save" type="button">${escapeHTML(t('submit'))}</button>
              <div class="p-edit-msg"></div>
            </div>`;
        }

        // ── reporting something wrong (phase 3) ──────────────────────────────
        //
        // The popup's own facts become the form. A row per fact — the year, the
        // name, the address — each showing what the map currently says, each
        // with a checkbox, and each revealing an input prefilled with that value
        // when ticked. Nobody has to describe what they are looking at; they
        // point at it.
        //
        // Ticking a fact and typing a replacement is a correction. Ticking it
        // and leaving the value blank is a flag — "this is wrong, I don't know
        // what's right" — which is the commonest thing a person walking past a
        // building actually knows, and it is worth more than an empty queue.
        // Both can appear in one report: see docs/submission-schema.md §5.
        function reportFormHTML(p) {
          const addr = [p.addr_street, p.addr_number].filter(Boolean).join(' ');
          const current = { year: yearLabel(p), name: p.name || '', address: addr };

          // What the map shows for this fact, or a plain "not shown" — a report
          // about a MISSING name is a legitimate report, so an empty fact still
          // gets a row.
          const row = (fact, inputs) => `
              <label class="p-fact">
                <input type="checkbox" class="p-fact-tick" data-fact="${fact}">
                <span class="p-fact-name">${escapeHTML(t('fact' + fact[0].toUpperCase() + fact.slice(1)))}</span>
                <span class="p-fact-now">${current[fact]
                  ? escapeHTML(current[fact]) : `<em>${escapeHTML(t('factMissing'))}</em>`}</span>
              </label>
              <div class="p-fact-input" data-fact="${fact}">${inputs}</div>`;

          // The year keeps the same two-answer control the suggest form uses —
          // an exact year, or a range with either bound — because a wrong year
          // is as often "not that decade" as "not that year".
          const yearInputs = `
                <div class="p-year-mode">
                  <label class="p-year-mode-opt">
                    <input type="radio" name="p-report-year-mode" value="exact" checked>
                    <span>${escapeHTML(t('exact'))}</span></label>
                  <label class="p-year-mode-opt">
                    <input type="radio" name="p-report-year-mode" value="range">
                    <span>${escapeHTML(t('range'))}</span></label>
                </div>
                <div class="p-edit-year-row">
                  <input class="p-suggest-input" type="number" inputmode="numeric" min="1" max="2030"
                         placeholder="${escapeHTML(t('year'))}">
                  <span class="p-suggest-sep">–</span>
                  <input class="p-suggest-to" type="number" inputmode="numeric" min="1" max="2030"
                         placeholder="${escapeHTML(t('to'))}">
                </div>`;

          return `
            <div class="p-edit p-report">
              <p class="p-report-what">${escapeHTML(t('reportWhat'))}</p>
              ${row('year', yearInputs)}
              ${row('name', `<input class="p-edit-name" type="text" maxlength="200"
                       placeholder="${escapeHTML(t('name'))}" value="${escapeHTML(p.name || '')}">`)}
              ${row('address', `<div class="p-edit-addr-row">
                  <input class="p-edit-street" type="text" maxlength="200"
                         placeholder="${escapeHTML(t('street'))}" value="${escapeHTML(p.addr_street || '')}">
                  <input class="p-edit-number" type="text" maxlength="20"
                         placeholder="${escapeHTML(t('number'))}" value="${escapeHTML(p.addr_number || '')}">
                </div>`)}
              <p class="p-report-hint">${escapeHTML(t('reportUnknownHint'))}</p>
              ${evidenceHTML()}
              <input class="p-website" type="text" name="website" tabindex="-1"
                     autocomplete="off" aria-hidden="true">
              <div class="p-turnstile"></div>
              <button class="p-edit-save p-report-send" type="button">${escapeHTML(t('reportSend'))}</button>
              <div class="p-edit-msg"></div>
            </div>`;
        }

        // What the map showed this reporter, in the shape parse_observed() in
        // submission.py expects: the disputed fields, and the values they held.
        // The year is an object of whichever properties were set, because which
        // one it is IS the claim — "1958-1972" and "1965" are different
        // statements, and a report has to say which it disagrees with.
        function observedFor(p, facts) {
          const before = {};
          for (const fact of facts) {
            if (fact === 'year') {
              before.year = {};
              for (const key of YEAR_PROPS) if (filled(p[key])) before.year[key] = p[key];
            } else if (fact === 'address') {
              before.addr_street = p.addr_street || null;
              before.addr_number = p.addr_number || null;
            } else {
              before.name = p.name || null;
            }
          }
          return before;
        }

        // The evidence block, shared by the suggest form and the report form —
        // they ask for a different thing about the building but the same thing
        // about how you know it, and two copies of this drifted apart once
        // already.
        //
        // The picker chooses what the evidence IS; the fields below it follow.
        // A link for a plaque or a published source, a note for local
        // knowledge, and the other field stays available rather than hidden:
        // somebody with a link AND something to say should not have to choose.
        function evidenceHTML() {
          const options = SOURCE_KINDS.map(kind =>
            `<option value="${kind}">${escapeHTML(t('src_' + kind))}</option>`).join('');
          return `
              <label class="p-source-label">${escapeHTML(t('sourceLabel'))}</label>
              <select class="p-source-kind">
                <option value="" selected disabled></option>
                ${options}
              </select>
              <input class="p-source-url" type="url" inputmode="url" maxlength="500"
                     placeholder="${escapeHTML(t('urlPlaceholder'))}">
              <input class="p-source-note" type="text" maxlength="500"
                     placeholder="${escapeHTML(t('notePlaceholder'))}">`;
        }

        // Reads the evidence block and validates it against the floor, so the
        // person is told what is missing before a round trip. The server decides
        // for real — this is the same rule stated twice on purpose, and
        // test_parity.py keeps the two honest.
        function readEvidence(root, msg) {
          const kind = root.querySelector('.p-source-kind').value;
          const url = root.querySelector('.p-source-url').value.trim();
          const note = root.querySelector('.p-source-note').value.trim();
          if (!kind) { msg.textContent = t('sourceRequired'); return null; }
          if (url && !/^https:\/\/[^\s/]+\.[^\s/]+/.test(url)) {
            msg.textContent = t('urlBad'); return null;
          }
          const needs = EVIDENCE_FLOOR[kind];
          if (needs === 'url' && !url) { msg.textContent = t('urlRequired'); return null; }
          if (needs === 'note' && !note) { msg.textContent = t('localNoteRequired'); return null; }
          // only the field this kind asked for is sent; the other is hidden, and
          // whatever an earlier selection left in it is not evidence for this one
          return {
            source_kind: kind,
            source_url: needs === 'url' ? url : null,
            source_note: needs === 'note' ? note : '',
          };
        }

        // One field, and only the one the chosen kind needs. Nothing is asked for
        // until a kind is picked, and a plaque asks for nothing at all — the
        // form ends there and the button is the next thing you touch.
        function wireEvidence(root) {
          const select = root.querySelector('.p-source-kind');
          const apply = () => {
            const needs = EVIDENCE_FLOOR[select.value];
            root.classList.toggle('needs-url', needs === 'url');
            root.classList.toggle('needs-note', needs === 'note');
          };
          select.addEventListener('change', apply);
          apply();
        }

        function popupHTML(p, lngLat) {
          // derived per-feature rather than precomputed: with vector tiles there's
          // no full feature list to walk up front (see deriveConfidence)
          const confidence = deriveConfidence(p);
          // which year shape this building carries. Both a suggestion and an era
          // call can be any of them, so the shape and where it came from are two
          // separate questions — the shape decides how the year reads, the
          // confidence decides what the badge says.
          const hasLo = has(p.year_min);
          const hasHi = has(p.year_max);
          const isRange  = hasLo || hasHi;
          const isOpen   = isRange && !(hasLo && hasHi);
          const isApprox = !isRange && has(p.year_est);
          const suggestedLabel = t('badgeConfirmed');
          // A closed span uses a hyphen, not the en dash used elsewhere — at
          // 21px bold the dash runs into the digit before it and reads as one
          // long number. An open one is written out as the sentence it is:
          // "1958–" is a truncation, "after 1958" is a claim.
          const rangeText = yearLabel(p);
          // A year that reads as a sentence — "around 1965", "before 1928" — needs
          // the smaller, wrapping treatment; a bare number or a span does not.
          const rangeClass = `p-year range${isOpen ? ' open' : ''}`;
          const approxClass = 'p-year range open';

          let yearHTML, confHTML;
          if (confidence === 'suggested') {
            if (isRange) {
              yearHTML = `<div class="${rangeClass}" style="color:inherit">${rangeText}</div>`;
              confHTML = `<div class="p-conf suggested">✓ ${suggestedLabel}</div>`;
            } else if (isApprox) {
              yearHTML = `<div class="${approxClass}" style="color:inherit">${yearLabel(p)}</div>`;
              confHTML = `<div class="p-conf suggested">✓ ${suggestedLabel}</div>`;
            } else {
              yearHTML = `<div class="p-year">${p.year_built}</div>`;
              confHTML = `<div class="p-conf suggested">✓ ${suggestedLabel}</div>`;
            }
          } else if (p.year_built !== null && p.year_built !== undefined) {
            yearHTML = `<div class="p-year">${p.year_built}</div>`;
            confHTML = `<div class="p-conf known">✓ Confirmed</div>`;
          } else if (isRange) {
            // no ~ and no single number: the range IS the answer, and writing
            // it as "~1965" would claim a precision the classifier never had.
            // The era name (year_tag is "era:khrushchevka") is deliberately not
            // shown: the span is the useful part, and the label is jargon.
            yearHTML = `<div class="${rangeClass}" style="color:inherit">${rangeText}</div>`;
            confHTML = `<div class="p-conf inferred">≈ Inferred</div>`;
          } else if (isApprox) {
            confHTML = `<div class="p-conf inferred">≈ Inferred</div>`;
            yearHTML = `<div class="${approxClass}" style="color:inherit">${yearLabel(p)}</div>`;
          } else {
            yearHTML = `<div class="p-year no-data">—</div>`;
            confHTML = `<div class="p-conf none">No year data</div>`;
          }

          // Most buildings have no name, and an address is what identifies one
          // anyway — so it moves up into the name's slot rather than leaving the
          // popup headed by a bare year. It is then NOT repeated in the line
          // below: the same street and number printed twice, once bold and once
          // faint, reads as two different facts about the building.
          //
          // A building with neither keeps just its year, which is all there is.
          const addr     = [p.addr_street, p.addr_number].filter(Boolean).join(' ');
          const title    = p.name || addr;
          const nameHTML = title ? `<div class="p-name">${escapeHTML(title)}</div>` : '';
          const addrHTML = addr && p.name ? `<div class="p-addr">${escapeHTML(addr)}</div>` : '';

          const gmaps = `https://www.google.com/maps?q=${lngLat.lat.toFixed(6)},${lngLat.lng.toFixed(6)}`;

          // The one form this popup can offer: the additive public form, which
          // only ever asks for fields that are still empty. Review reads and
          // approves; it does not suggest.
          const editHTML = isPublic ? publicFormHTML(p) : '';

          // Always offered, on every building, whatever else the popup holds:
          // the additive form can only ever ask for what is missing, so this is
          // the only route to anything the map already claims. Nothing is
          // displayed on a building with no data at all, so nothing to dispute.
          const reportHTML = isPublic && (has(p.year_built) || has(p.year_est)
                || has(p.year_min) || has(p.year_max) || p.name || addr)
            ? `<button class="p-report-open" type="button">${escapeHTML(t('reportOpen'))}</button>`
            : '';

          return `${yearHTML}${confHTML}${nameHTML}${addrHTML}${editHTML}${reportHTML}
                  <a class="p-gmaps" href="${gmaps}" target="_blank">Open in Google Maps ↗</a>`;
        }


        // POST one public suggestion to the review queue.
        //
        // Nothing here changes the map: the submission is
        // queued, and only apply_queue.py can turn it into data. That is the
        // whole point of the phase, and it is also why the confirmation below
        // has to be explicit about what happens next — a silent success reads
        // exactly like a silent failure.
        async function postSuggestion(payload) {
          const res = await fetch('/api/suggest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          let body = {};
          try { body = await res.json(); } catch (e) { /* keep the status below */ }
          if (!res.ok || !body.ok) throw new Error(body.error || t('failed'));
          return body;
        }

        // Turnstile renders explicitly, not implicitly: its auto-scan runs at page
        // load and this markup is injected into a popup long after. Absent script
        // (local dev, or no key) is fine — the Function skips verification when
        // TURNSTILE_SECRET is unset, which is what keeps server.py a complete
        // development environment. Shared by the suggest form and the report form.
        function renderTurnstile(holder) {
          const siteKey = document.body.dataset.turnstileSiteKey;
          if (!window.turnstile || !holder || !siteKey || siteKey.startsWith('__')) return null;
          return window.turnstile.render(holder, { sitekey: siteKey, size: 'compact' });
        }

        // The report form, wired. Swaps itself in over whatever the popup was
        // showing — the facts stay visible above it, which is the point of
        // reporting from the popup rather than a separate page.
        function wireReportForm(feat, lngLat) {
          const el = popup.getElement();
          if (!el) return;
          const form = el.querySelector('.p-report');
          if (!form) return;
          const p = feat.properties;
          const q = sel => form.querySelector(sel);
          const msg = q('.p-edit-msg');
          const sendBtn = q('.p-report-send');
          const turnstileId = renderTurnstile(q('.p-turnstile'));
          wireEvidence(form);

          // a fact's inputs only exist once it is ticked — an untouched form
          // should read as three statements about the building, not nine inputs
          const ticked = () => [...form.querySelectorAll('.p-fact-tick:checked')]
            .map(box => box.dataset.fact);
          for (const box of form.querySelectorAll('.p-fact-tick')) {
            box.addEventListener('change', () => {
              const slot = form.querySelector(`.p-fact-input[data-fact="${box.dataset.fact}"]`);
              slot.classList.toggle('shown', box.checked);
            });
          }
          const yearRow = q('.p-edit-year-row');
          for (const radio of form.querySelectorAll('.p-year-mode input')) {
            radio.addEventListener('change', () => yearRow.classList.toggle(
              'range-mode', form.querySelector('.p-year-mode input:checked').value === 'range'));
          }

          const readYear = input => {
            if (!input) return null;
            const raw = input.value.trim();
            if (raw === '') return null;
            const y = parseInt(raw, 10);
            return Number.isFinite(y) && y >= 1 && y <= 2030 ? y : NaN;
          };

          sendBtn.addEventListener('click', async () => {
            const facts = ticked();
            if (!facts.length) { msg.textContent = t('reportPickOne'); return; }

            // Proposed replacements, for whichever ticked facts got a value. A
            // ticked fact with nothing typed stays in `before` and out of
            // `after`: that is exactly what a flag is on the wire.
            const after = {};
            if (facts.includes('year')) {
              const ranged = form.querySelector('.p-year-mode input:checked').value === 'range';
              const from = readYear(q('.p-suggest-input'));
              const to = ranged ? readYear(q('.p-suggest-to')) : null;
              if (Number.isNaN(from) || Number.isNaN(to)) { msg.textContent = t('yearRange'); return; }
              if (from !== null && to !== null && from > to) {
                msg.textContent = t('rangeBackwards'); return;
              }
              if (!ranged) {
                if (from !== null) { after.year = from; after.approx = false; }
              } else if (from !== null && from === to) {
                after.year = from; after.approx = false;
              } else {
                if (from !== null) after.year_min = from;
                if (to !== null) after.year_max = to;
              }
            }
            if (facts.includes('name')) {
              const value = q('.p-edit-name').value.trim();
              if (value && value !== (p.name || '')) after.name = value;
            }
            if (facts.includes('address')) {
              const street = q('.p-edit-street').value.trim();
              const number = q('.p-edit-number').value.trim();
              if (street && street !== (p.addr_street || '')) after.addr_street = street;
              if (number && number !== (p.addr_number || '')) after.addr_number = number;
            }

            const evidence = readEvidence(form, msg);
            if (!evidence) return;

            sendBtn.disabled = true;
            msg.textContent = t('submitting');
            try {
              await postSuggestion({
                kind: 'report',
                id: p.id,
                lng: lngLat.lng,
                lat: lngLat.lat,
                before: observedFor(p, facts),
                after,
                ...evidence,
                website: q('.p-website').value,
                turnstile_token: turnstileId !== null ? window.turnstile.getResponse(turnstileId) : '',
              });
              // the same local note a suggestion leaves, over the disputed
              // fields: it clears itself once the map stops showing what was
              // reported, which is precisely when the report has been acted on
              markPending(p.id, facts.map(f => f === 'address' ? 'addr_street' : f),
                          observedFor(p, facts));
              form.innerHTML = `<div class="p-thanks"><strong>${escapeHTML(t('reportThanks'))}</strong>
                                <p>${escapeHTML(t('reportThanksDetail'))}</p></div>`;
            } catch (err) {
              sendBtn.disabled = false;
              msg.textContent = err.message;
              if (turnstileId !== null) window.turnstile.reset(turnstileId);
            }
          });
        }

        function wirePublicForm(feat, lngLat) {
          const el = popup.getElement();
          if (!el) return;
          const form = el.querySelector('.p-public');
          if (!form) return;              // pending, or nothing left to add

          const p = feat.properties;
          const open = openFields(p);
          const q = sel => el.querySelector(sel);
          const saveBtn = q('.p-edit-save');
          const msg = q('.p-edit-msg');
          const yearRow = q('.p-edit-year-row');
          const yearInput = q('.p-suggest-input');
          const toInput = q('.p-suggest-to');
          const yearHint = q('.p-year-hint');
          wireEvidence(form);

          const turnstileId = renderTurnstile(q('.p-turnstile'));   // see the helper

          const currentMode = () => {
            const checked = el.querySelector('.p-year-mode input:checked');
            return checked ? checked.value : 'exact';
          };

          // the second box and its hint belong to the range alone, and the first
          // box is only a "from" once there is a second one after it
          for (const radio of el.querySelectorAll('.p-year-mode input')) {
            radio.addEventListener('change', () => {
              const ranged = currentMode() === 'range';
              yearRow.classList.toggle('range-mode', ranged);
              if (yearHint) yearHint.classList.toggle('shown', ranged);
              yearInput.placeholder = ranged ? t('from') : t('year');
            });
          }

          // '' → null, a valid year → the number, anything else → NaN, which the
          // caller reports rather than silently sending. Same contract as the
          // editor's readYear.
          function readYear(input) {
            if (!input) return null;
            const raw = input.value.trim();
            if (raw === '') return null;
            const y = parseInt(raw, 10);
            return Number.isFinite(y) && y >= 1 && y <= 2030 ? y : NaN;
          }

          saveBtn.addEventListener('click', async () => {
            const after = {};

            if (open.includes('year')) {
              const ranged = currentMode() === 'range';
              const from = readYear(yearInput);
              const to = ranged ? readYear(toInput) : null;
              if (Number.isNaN(from) || Number.isNaN(to)) { msg.textContent = t('yearRange'); return; }
              if (from !== null && to !== null && from > to) {
                msg.textContent = t('rangeBackwards'); return;
              }
              if (!ranged) {
                if (from !== null) { after.year = from; after.approx = false; }
              } else if (from !== null && from === to) {
                // a zero-width span is just an exact year — the server stores it
                // as one, so send it as one
                after.year = from;
                after.approx = false;
              } else {
                // whichever bounds were given. An empty box sends no key at all:
                // its absence is what makes the range open at that end, and the
                // popup reads it back as "after 1958" / "before 1972".
                if (from !== null) after.year_min = from;
                if (to !== null) after.year_max = to;
              }
            }

            for (const [field, cls] of [['name', '.p-edit-name'],
                                        ['addr_street', '.p-edit-street'],
                                        ['addr_number', '.p-edit-number']]) {
              const input = q(cls);
              if (input && input.value.trim()) after[field] = input.value.trim();
            }

            if (!Object.keys(after).length) { msg.textContent = t('nothingSuggested'); return; }
            const evidence = readEvidence(form, msg);
            if (!evidence) return;

            saveBtn.disabled = true;
            msg.textContent = t('submitting');
            try {
              await postSuggestion({
                kind: 'suggestion',
                id: p.id,
                lng: lngLat.lng,
                lat: lngLat.lat,
                // Every field the form offered, asserted empty. The server
                // rejects a non-null one outright: it would mean this client
                // drew an input over a field that already had a value.
                before: Object.fromEntries(open.map(f => [f, null])),
                after,
                ...evidence,
                website: q('.p-website').value,
                turnstile_token: turnstileId !== null
                  ? window.turnstile.getResponse(turnstileId) : '',
              });
              // year / year_min / year_max / approx are four spellings of the
              // one field fieldIsOpen() knows about, so they collapse to 'year'
              markPending(p.id, [...new Set(Object.keys(after).map(
                k => YEAR_KEYS.includes(k) ? 'year' : k))]);
              // "Accepted" and "visible" are different days — the site rebuilds
              // on a schedule. Saying only "thanks" invites the conclusion that
              // the suggestion was ignored when the map looks unchanged tomorrow.
              form.innerHTML = `<div class="p-thanks"><strong>${escapeHTML(t('thanks'))}</strong>
                                <p>${escapeHTML(t('thanksDetail'))}</p></div>`;
            } catch (err) {
              saveBtn.disabled = false;
              msg.textContent = err.message;
              if (turnstileId !== null) window.turnstile.reset(turnstileId);
            }
          });
        }

        const popup = new maplibregl.Popup({
          closeButton: true,
          closeOnClick: false,
          maxWidth: '260px',
          offset: 8
        });

        // setFeatureState identifies a feature by source + id, and for a vector
        // source it also REQUIRES sourceLayer — omitting it throws
        // "The sourceLayer parameter must be provided for vector source types".
        // A geojson source must not carry one, hence the same tiles flag again.
        const featureRef = id => tiles
          ? { source: 'buildings', sourceLayer: 'buildings', id }
          : { source: 'buildings', id };

        // Buildings are split across THREE fill layers (dated, no-data, and the
        // hollow half-open bounds — see the filters above), so every interaction
        // has to be registered on all of them. The no-data layer holds ~96% of
        // buildings, including every one you'd click in order to suggest a year
        // for it; the open-bound layer holds the ones a contributor already
        // touched, which are exactly the ones somebody wants to read.
        //
        // Hit-testing is per LAYER, not per feature: a building drawn only by a
        // layer missing from this list is unclickable and has no popup, silently.
        // Adding a fill layer means adding it here — that is the whole contract.
        const FILL_LAYERS = ['buildings-fill', 'buildings-fill-nodata',
                             'buildings-fill-openbound'];


        // hover — border only, no popup
        let hoveredId = null;
        for (const layer of FILL_LAYERS) {
          map.on('mousemove', layer, e => {
            map.getCanvas().style.cursor = 'pointer';
            const id = e.features[0].id;
            if (hoveredId === id) return;
            if (hoveredId !== null)
              map.setFeatureState(featureRef(hoveredId), { hover: false });
            hoveredId = id;
            map.setFeatureState(featureRef(hoveredId), { hover: true });
          });

          map.on('mouseleave', layer, e => {
            // crossing from one fill layer to the other fires mouseleave here
            // even though the pointer is still over a building — only drop the
            // highlight once it has actually left both
            if (map.queryRenderedFeatures(e.point, { layers: FILL_LAYERS }).length) return;
            map.getCanvas().style.cursor = '';
            if (hoveredId !== null)
              map.setFeatureState(featureRef(hoveredId), { hover: false });
            hoveredId = null;
          });

          // click — show popup
          map.on('click', layer, e => openBuildingPopup(e.features[0], e.lngLat));
        }

        // The single way a building popup opens, so a click and a deep link
        // produce identically wired results — same form, same URL. Anything that
        // only happened on click would be missing exactly where a reviewer needs
        // it, since moderation arrives by link.
        function openBuildingPopup(feat, lngLat) {
          popup.setLngLat(lngLat).setHTML(popupHTML(feat.properties, lngLat)).addTo(map);
          if (isPublic) {
            wirePublicForm(feat, lngLat);
            // "Report an error" swaps the popup's form area for the report form
            // — the facts above it stay on screen, which is the whole reason to
            // report from the popup instead of a separate page. One way in, so
            // the button removes itself rather than toggling back and forth
            // over a half-filled form.
            const el = popup.getElement();
            const openBtn = el && el.querySelector('.p-report-open');
            if (openBtn) {
              openBtn.addEventListener('click', () => {
                const existing = el.querySelector('.p-edit');
                if (existing) existing.remove();
                openBtn.insertAdjacentHTML('beforebegin', reportFormHTML(feat.properties));
                openBtn.remove();
                wireReportForm(feat, lngLat);
              });
            }
          }
          writeHash(buildingHash(feat.properties.id, lngLat));
        }

        // click on empty map — close popup
        map.on('click', e => {
          const hits = map.queryRenderedFeatures(e.point, { layers: FILL_LAYERS });
          if (!hits.length) popup.remove();
        });

        // The URL follows the map, but only while no building is open — a
        // building link must survive the pan that MapLibre does to fit its popup
        // on screen, or opening one would immediately overwrite it with a view.
        popup.on('close', () => writeViewHash());
        map.on('moveend', () => { if (!popup.isOpen()) writeViewHash(); });

        // A building link jumped to the right place before the data loaded; the
        // popup has to wait for the feature to actually render, which is what
        // 'idle' means here.
        function openDeepLink({ id, lng, lat }) {
          const lngLat = new maplibregl.LngLat(lng, lat);
          const hits = map.queryRenderedFeatures(map.project(lngLat), { layers: FILL_LAYERS });
          const feat = hits.find(f => String(f.properties.id) === String(id));
          if (feat) {
            openBuildingPopup(feat, lngLat);
            return;
          }
          // tippecanoe drops features from dense tiles (--drop-densest-as-needed),
          // so the building can genuinely not be rendered at this zoom even though
          // the link is correct. Marking the spot is honest; silently opening the
          // wrong neighbouring building would not be.
          suppressHashWrite = true;
          new maplibregl.Marker({ color: '#d6c41d' }).setLngLat(lngLat).addTo(map);
          suppressHashWrite = false;
        }

        if (initialHash && initialHash.id) map.once('idle', () => openDeepLink(initialHash));

        // A deep link followed WITHIN the page changes location.hash without
        // reloading, so without this the link only ever worked on a cold load —
        // pasting one into the address bar worked, clicking one did nothing.
        // The review popup's "open the building" link is exactly that case.
        //
        // writeHash uses replaceState, which fires no hashchange, so the map
        // updating the URL cannot re-enter this.
        window.addEventListener('hashchange', () => {
          const target = parseHash();
          if (!target) return;
          map.easeTo({ center: [target.lng, target.lat], zoom: target.zoom });
          if (target.id) map.once('idle', () => openDeepLink(target));
        });

        // ── Review mode ──────────────────────────────────────────────────────
        //
        // Pending submissions render as their own pins, and the review popup is
        // built entirely from the submission — not from the building feature.
        // That works because the additive rule guarantees every field it touches
        // was empty, so `before` carries nothing to diff against and there is
        // nothing to look up. It also means review does not depend on the
        // building being present in the tile at this zoom, which
        // --drop-densest-as-needed makes a real possibility.
        //
        // Protected by Cloudflare Access, not by anything in this file. See
        // docs/build-and-deploy.md — if that policy is ever removed, this page and
        // /api/queue publish the queue, source_note included.
        function reviewPinFC(pending) {
          return {
            type: 'FeatureCollection',
            features: pending.map(s => ({
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [s.lng, s.lat] },
              properties: { ...s, entry: JSON.stringify(s.entry) },
            })),
          };
        }

        // Feature ids are OSM ids (promoteId), and the queue carries them as
        // strings — the cast is what makes the match work at all.
        const pendingFilter = pending =>
          ['in', ['id'], ['literal', pending.map(s => Number(s.id))]];

        // One submission's year, in the words the map itself would use — an
        // entry's keys are the same shapes yearLabel reads off a feature, so the
        // reviewer sees "after 1958", never "1958–undefined".
        function entryYearText(entry) {
          if (entry.year_min !== undefined || entry.year_max !== undefined)
            return yearLabel({ year_min: entry.year_min ?? null,
                               year_max: entry.year_max ?? null });
          if (entry.year === undefined) return null;
          return entry.approx ? tYear('approxYear', entry.year) : String(entry.year);
        }

        // The logical fields a reviewer may edit on one submission, which are
        // exactly the fields that submission is allowed to propose — the same
        // rule validate_review_edit() enforces server-side, mirrored here so the
        // form cannot offer an input the merge would refuse. See docs §7.
        const YEAR_EDIT_KEYS = ['year', 'approx', 'year_min', 'year_max'];
        const logicalField = k => (YEAR_EDIT_KEYS.includes(k) ? 'year' : k);

        function editableFields(kind, entry, before) {
          // a report may only touch what it disputed; an orphan only ever a year
          if (kind === 'report') return Object.keys(before);
          if (kind === 'orphan') return ['year'];
          return [...new Set(Object.keys(entry).map(logicalField))];
        }

        // The year, as the three boxes the shapes are actually made of. Filling
        // the wrong pair is caught by parseYearShape on the way in ("a year and
        // a bound are different shapes"), so this stays a plain form rather than
        // a mode switch — a reviewer changing 1965 to 1972 types in one box.
        function yearEditorHTML(entry) {
          const box = (name, label, value) => `
            <label class="r-edit-field">
              <span>${label}</span>
              <input type="number" class="r-edit" data-field="${name}"
                     min="1" max="2030" step="1"
                     value="${value === undefined || value === null ? '' : escapeHTML(String(value))}">
            </label>`;
          return `<div class="r-edit-years">
              ${box('year', 'exact', entry.year)}
              ${box('year_min', 'after', entry.year_min)}
              ${box('year_max', 'before', entry.year_max)}
            </div>`;
        }

        function reviewPopupHTML(s) {
          const entry = typeof s.entry === 'string' ? JSON.parse(s.entry) : s.entry;
          const before = (typeof s.before === 'string' ? JSON.parse(s.before) : s.before) || {};
          const isReport = s.kind === 'report';
          const isOrphan = s.kind === 'orphan';
          const yearText = entryYearText(entry);

          // A suggestion is a list of proposed values. A report is a list of
          // DISAGREEMENTS, and a reviewer deciding one needs both halves on
          // screen — what the map says now, and what this person says instead.
          // `before` carries the first half already (it is what the staleness
          // check is made of), so the diff costs nothing to show.
          const rows = [];
          if (isReport) {
            if ('year' in before) {
              const was = yearLabel({
                year_built: before.year?.year_built ?? null,
                year_est: before.year?.year_est ?? null,
                year_min: before.year?.year_min ?? null,
                year_max: before.year?.year_max ?? null,
              });
              rows.push(['Year', `${was || '—'} → ${yearText || 'FLAGGED, no value'}`]);
            }
            for (const [key, label] of [['name', 'Name'], ['addr_street', 'Street'],
                                        ['addr_number', 'No.']]) {
              if (!(key in before)) continue;
              const was = before[key] || '—';
              rows.push([label, `${was} → ${entry[key] ?? 'FLAGGED, no value'}`]);
            }
          } else {
            if (yearText) rows.push(['Year', yearText]);
            for (const [key, label] of [['name', 'Name'], ['addr_street', 'Street'],
                                        ['addr_number', 'No.']]) {
              if (entry[key] !== undefined) rows.push([label, entry[key]]);
            }
          }

          const when = new Date((s.submitted_at || 0) * 1000).toISOString().slice(0, 10);
          // A flag proposes nothing. It used to render without an Approve button
          // at all, because approving would have filed it as done while merging
          // nothing — but that was a limit of a read-only card. A reviewer who
          // can EDIT can answer the question the flag asked, so Approve is
          // offered and stays disabled until they have actually typed a value.
          const isFlag = isReport && !Object.keys(entry).length;

          const fields = editableFields(s.kind, entry, before);
          const textEditor = (key, label) => `
            <label class="r-edit-field r-edit-text">
              <span>${label}</span>
              <input type="text" class="r-edit" data-field="${key}"
                     value="${entry[key] === undefined ? '' : escapeHTML(String(entry[key]))}">
            </label>`;

          return `
            <div class="r-review">
              ${isOrphan ? `<div class="r-kind r-orphan">ORPHAN — inherited from ${
                escapeHTML(String(s.derived_from || '?'))}, confirm it fits this piece</div>` : ''}
              ${isReport ? `<div class="r-kind${isFlag ? ' r-flag' : ''}">${
                isFlag ? 'FLAG — nothing proposed, answer it below or note it'
                       : 'CORRECTION — overwrites live data'
              }</div>` : ''}
              <div class="r-proposal">
                ${rows.map(([k, v]) =>
                  `<div class="r-row"><span>${k}</span><strong>${escapeHTML(String(v))}</strong></div>`).join('')}
              </div>
              <div class="r-editor">
                ${fields.includes('year') ? yearEditorHTML(entry) : ''}
                ${fields.includes('name') ? textEditor('name', 'Name') : ''}
                ${fields.includes('addr_street') ? textEditor('addr_street', 'Street') : ''}
                ${fields.includes('addr_number') ? textEditor('addr_number', 'No.') : ''}
              </div>
              <div class="r-source r-source-${escapeHTML(s.source_kind)}">
                ${escapeHTML(t('src_' + s.source_kind) || s.source_kind)}
              </div>
              ${s.source_url ? `<a class="r-link r-source-url" href="${escapeHTML(s.source_url)}"
                 target="_blank" rel="noopener noreferrer nofollow">${
                   escapeHTML(s.source_url.replace(/^https:\/\//, '').slice(0, 60))}↗</a>
                 <span class="r-link-status">${escapeHTML(s.link_status || 'not checked')}</span>` : ''}
              ${s.source_note ? `<p class="r-note">“${escapeHTML(s.source_note)}”</p>` : ''}
              <div class="r-meta">${when} · ${escapeHTML(String(s.submitter_hash || '').slice(0, 8))}</div>
              <!-- Judging a submitted year often means looking at the building,
                   and satellite/Street View is the fastest way to do that. The
                   normal popup has had this all along; the review popup — the
                   one place it matters most — did not. -->
              <a class="p-gmaps" target="_blank"
                 href="https://www.google.com/maps?q=${Number(s.lat).toFixed(6)},${Number(s.lng).toFixed(6)}"
                >Open in Google Maps ↗</a>
              <div class="r-actions">
                <button class="r-approve" type="button" data-id="${escapeHTML(s.submission_id)}"
                        ${isFlag ? 'disabled' : ''}>Approve</button>
                ${isFlag ? `<button class="r-noted" type="button" data-id="${escapeHTML(s.submission_id)}">Noted</button>` : ''}
                <button class="r-reject" type="button" data-id="${escapeHTML(s.submission_id)}">Reject</button>
              </div>
              <a class="r-link" href="#b=${escapeHTML(String(s.id))}@${s.lng},${s.lat},18">Open the building ↗</a>
              <div class="r-msg"></div>
            </div>`;
        }

        async function initReviewQueue() {
          const box = document.getElementById('review-count');
          let pending = [];
          try {
            const res = await fetch('/api/queue');
            const body = await res.json();
            if (!body.ok) throw new Error(body.error || `HTTP ${res.status}`);
            pending = body.pending || [];
          } catch (err) {
            if (box) box.textContent = `Queue unavailable — ${err.message}`;
            return;
          }

          // The count exists so an unreviewed queue is visible rather than
          // merely true. A queue nobody looks at is how contributors learn to
          // stop contributing.
          if (box) box.textContent = pending.length
            ? `${pending.length} pending`
            : 'Nothing pending';

          map.addSource('queue', { type: 'geojson', data: reviewPinFC(pending) });
          map.addLayer({
            id: 'queue-pins',
            type: 'circle',
            source: 'queue',
            paint: {
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 4, 16, 9],
              'circle-color': '#d6c41d',
              'circle-stroke-width': 1.5,
              'circle-stroke-color': '#000',
            },
          });

          // ── "only what's pending" ───────────────────────────────────────────
          //
          // A pin marks where a submission is, but the building under it still
          // looks like every other building. This outlines the ones actually
          // waiting on you and drops everything else to a backdrop, so a queue
          // of six in a city of 76,000 is findable by eye.
          //
          // Filtered by feature id, which promoteId has already set to the OSM
          // id — so this needs no extra data, just the ids the queue already
          // carries. They arrive as strings and must be numbers to match.
          map.addLayer({
            id: 'queue-highlight',
            type: 'line',
            source: 'buildings',
            ...(tiles ? { 'source-layer': 'buildings' } : {}),
            filter: pendingFilter(pending),
            layout: { visibility: 'none' },
            paint: {
              'line-color': '#d6c41d',
              'line-width': ['interpolate', ['linear'], ['zoom'], 12, 1.5, 17, 3],
              'line-opacity': 0.9,
            },
          }, 'queue-pins');

          const pendingOnly = document.getElementById('pending-only');
          if (pendingOnly) {
            const DIMMED = 0.05;
            pendingOnly.addEventListener('change', () => {
              const on = pendingOnly.checked;
              map.setLayoutProperty('queue-highlight', 'visibility', on ? 'visible' : 'none');
              if (on) {
                for (const [layer, prop] of [['buildings-fill', 'fill-opacity'],
                                             ['buildings-edge', 'line-opacity'],
                                             ['buildings-glow', 'line-opacity'],
                                             ['buildings-fill-nodata', 'fill-opacity'],
                                             ['buildings-edge-nodata', 'line-opacity'],
                                             ['buildings-fill-openbound', 'fill-opacity']]) {
                  map.setPaintProperty(layer, prop, DIMMED);
                }
              } else {
                // hand the dated layers back to the slider and the rest back to
                // their constants, rather than guessing at what they were
                refreshYearPaint();
                map.setPaintProperty('buildings-fill-nodata', 'fill-opacity', NO_DATA_FILL_OPACITY);
                map.setPaintProperty('buildings-edge-nodata', 'line-opacity', NO_DATA_EDGE_OPACITY);
                map.setPaintProperty('buildings-fill-openbound', 'fill-opacity', NO_DATA_FILL_OPACITY);
              }
            });
          }

          map.on('mouseenter', 'queue-pins', () => { map.getCanvas().style.cursor = 'pointer'; });
          map.on('mouseleave', 'queue-pins', () => { map.getCanvas().style.cursor = ''; });

          map.on('click', 'queue-pins', e => {
            const s = e.features[0].properties;
            popup.setLngLat(e.lngLat).setHTML(reviewPopupHTML(s)).addTo(map);

            const el = popup.getElement();
            const msg = el.querySelector('.r-msg');
            const entry0 = typeof s.entry === 'string' ? JSON.parse(s.entry) : s.entry;
            const inputs = [...el.querySelectorAll('.r-edit')];
            const approve = el.querySelector('.r-approve');

            // What the boxes say now, in the `after` shape /api/suggest speaks —
            // so the reviewer's edit is validated by the very same code that
            // validated the submission (docs §7).
            function editedAfter() {
              const after = {};
              for (const input of inputs) {
                const raw = input.value.trim();
                if (!raw) continue;
                after[input.dataset.field] =
                  input.type === 'number' ? Number(raw) : raw;
              }
              return after;
            }

            // Key order is not meaning, so both sides are compared sorted —
            // otherwise reopening a card and pressing Approve would record an
            // edit nobody made.
            const canonical = o => JSON.stringify(Object.entries(o)
              .filter(([, v]) => v !== undefined && v !== false)
              .sort(([a], [b]) => (a < b ? -1 : 1)));
            const isEdited = () => canonical(editedAfter()) !== canonical(entry0);

            // A flag has nothing to approve until somebody answers it.
            if (approve && approve.disabled) {
              for (const input of inputs) {
                input.addEventListener('input', () => {
                  approve.disabled = !Object.keys(editedAfter()).length;
                });
              }
            }

            for (const [cls, decision] of [['.r-approve', 'approved'], ['.r-reject', 'rejected'],
                                           ['.r-noted', 'noted']]) {
              const button = el.querySelector(cls);
              // Not every card carries every button — a flag has no plain
              // Approve path and nothing else has "Noted". Before this guard the
              // missing one threw on null, which cost a flag card ALL of its
              // buttons: the throw landed before the rest were ever wired.
              if (!button) continue;
              button.addEventListener('click', async ev => {
                const submissionId = ev.currentTarget.dataset.id;
                ev.currentTarget.disabled = true;
                msg.textContent = '…';
                try {
                  const res = await fetch('/api/review', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      submission_id: submissionId, decision,
                      // only on an approval, and only when it actually differs:
                      // the server records the submitter's original claim the
                      // first time an entry changes, and an edit nobody made
                      // would overwrite that meaning
                      ...(decision === 'approved' && isEdited()
                          ? { entry: editedAfter() } : {}),
                    }),
                  });
                  const body = await res.json();
                  if (!body.ok) throw new Error(body.error || `HTTP ${res.status}`);
                  // Approving only marks the row — apply_queue.py is what turns
                  // it into data, and it is the only thing that can enforce
                  // additivity. Say so, or a reviewer will look for the change
                  // on the map and not find it.
                  msg.textContent = decision === 'approved'
                    ? (body.edited ? 'Approved with your edit — run apply_queue.py to merge it'
                                   : 'Approved — run apply_queue.py to merge it')
                    : decision === 'noted' ? 'Noted' : 'Rejected';
                  pending = pending.filter(x => x.submission_id !== submissionId);
                  map.getSource('queue').setData(reviewPinFC(pending));
                  // the outline has to follow the pin, or a building you just
                  // handled stays highlighted as though it were still waiting
                  map.setFilter('queue-highlight', pendingFilter(pending));
                  if (box) box.textContent = pending.length ? `${pending.length} pending`
                                                            : 'Nothing pending';
                  setTimeout(() => popup.remove(), 900);
                } catch (err) {
                  msg.textContent = err.message;
                  ev.currentTarget.disabled = false;
                }
              });
            }
          });
        }

        if (isReview) initReviewQueue();

      })
      .catch(err => {
        document.getElementById('loader').innerHTML =
          `<div style="color:#f88;font-size:15px">⚠ ${err.message}</div>`;
      });
  });
}
