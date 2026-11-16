// node --test tests/web_runtime  — the shipped browser runtime (ADR-118).
// Runs llm_localize/web_runtime/i18n.js in a vm context with a fake window.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const SRC = readFileSync(
  fileURLToPath(new URL('../../llm_localize/web_runtime/i18n.js', import.meta.url)), 'utf8');

function storage(init = {}) {
  const m = new Map(Object.entries(init));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
  };
}

class El {
  constructor(tag, attrs = {}, kids = []) {
    this.nodeType = 1; this.tagName = tag; this.attrs = { ...attrs }; this.childNodes = kids;
    this.id = attrs.id || '';
  }
  getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  get textContent() { return this.childNodes.map((k) => k.nodeValue ?? k.textContent).join(''); }
  set textContent(v) { this.childNodes = [{ nodeType: 3, nodeValue: v }]; }
  matches(sel) {
    return sel.split(',').some((s) => { const a = s.match(/^\[(.+)\]$/); return a && a[1] in this.attrs; });
  }
  closest() { return null; }
  querySelectorAll() { return []; }
}
function text(v) { return { nodeType: 3, nodeValue: v }; }

function makeDoc(elements = []) {
  const head = { kids: [], appendChild(n) { this.kids.push(n); } };
  return {
    readyState: 'complete', cookie: '', head,
    documentElement: { lang: '', dir: '' },
    createElement: (tag) => new El(tag),
    getElementById: (id) => head.kids.find((k) => k.id === id) || null,
    addEventListener() {},
    querySelectorAll: (sel) => elements.filter((e) => e.matches(sel)),
  };
}

function codeOf(u) { return decodeURIComponent(u.split('/').pop().replace(/\.json$/, '')); }

async function load({ href = 'http://localhost:8000/', config = {}, catalogs = {}, local = {}, session = {},
  nav = 'en-US', elements = [] } = {}) {
  const url = new URL(href);
  const requested = [];
  const win = {
    I18N_CONFIG: config,
    location: {
      href, search: url.search, pathname: url.pathname, hostname: url.hostname,
      assign(u) { win.assigned = u; },
    },
    navigator: { language: nav },
    localStorage: storage(local), sessionStorage: storage(session),
    document: makeDoc(elements),
    URL, URLSearchParams,
    fetch: async (u) => {
      requested.push(u);
      const code = codeOf(u);
      return code in catalogs ? { ok: true, json: async () => catalogs[code] } : { ok: false };
    },
    XMLHttpRequest: class {
      open(m, u) { this.u = u; }
      send() {
        requested.push(this.u);
        const code = codeOf(this.u);
        this.status = code in catalogs ? 200 : 404;
        this.responseText = JSON.stringify(catalogs[code] || {});
      }
    },
  };
  win.window = win;
  vm.runInNewContext(SRC, win);
  await win.i18n.whenReady();
  return { win, i18n: win.i18n, requested };
}

const EN = {
  hi: 'Hello {name}',
  files: '{n, plural, =0 {No files} one {# file} other {# files}}',
  who: '{g, select, female {She} male {He} other {They}} left',
  nested: '{n, plural, one {# set of {k, plural, one {# card} other {# cards}}} other {# sets}}',
  place: '{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}',
  only_en: 'English only',
};
const PL = {
  hi: 'Cześć {name}',
  files: '{n, plural, =0 {Brak plików} one {# plik} few {# pliki} many {# plików} other {# pliku}}',
  only_en: '',
};
const AR = {
  files: '{n, plural, zero {لا ملفات} one {ملف} two {ملفان} few {# ملفات} many {# ملفًا} other {# ملف}}',
};

test('version header and API', async () => {
  const { i18n } = await load({ catalogs: { en: EN } });
  assert.match(SRC.slice(0, 120), /llm-localize web runtime v\d+\.\d+\.\d+/);
  assert.equal(i18n.version, SRC.match(/v(\d+\.\d+\.\d+)/)[1]);
  assert.equal(i18n.locale, 'en');
});

test('ICU subset: args, plural =n and #, select, nested, selectordinal', async () => {
  const { i18n } = await load({ catalogs: { en: EN } });
  assert.equal(i18n.t('hi', { name: 'Ann' }), 'Hello Ann');
  assert.equal(i18n.t('files', { n: 0 }), 'No files');
  assert.equal(i18n.t('files', { n: 1 }), '1 file');
  assert.equal(i18n.t('files', { n: 7 }), '7 files');
  assert.equal(i18n.t('who', { g: 'female' }), 'She left');
  assert.equal(i18n.t('who', { g: 'x' }), 'They left');
  assert.equal(i18n.t('nested', { n: 1, k: 3 }), '1 set of 3 cards');
  assert.equal(i18n.t('place', { n: 2 }), '2nd');
  assert.equal(i18n.t('place', { n: 13 }), '13th');
  assert.equal(i18n.t('missing.key'), 'missing.key');
  assert.equal(i18n.format('{a} and {b}', { a: 1 }), '1 and ');
});

test('Polish plural categories and fallback to source', async () => {
  const { i18n } = await load({
    href: 'http://localhost/?lang=pl', config: { locales: ['en', 'pl'] }, catalogs: { en: EN, pl: PL },
  });
  assert.equal(i18n.locale, 'pl');
  const got = [0, 1, 2, 5, 22, 25, 1.5].map((n) => i18n.t('files', { n }));
  assert.deepEqual(got, ['Brak plików', '1 plik', '2 pliki', '5 plików', '22 pliki', '25 plików', '1.5 pliku']);
  assert.equal(i18n.t('only_en'), 'English only'); // empty value falls back
  assert.equal(i18n.t('who', { g: 'male' }), 'He left'); // missing key falls back
});

test('Arabic plural categories and RTL', async () => {
  const { i18n, win } = await load({
    href: 'http://localhost/?lang=ar', config: { locales: ['en', 'ar'] }, catalogs: { en: EN, ar: AR },
  });
  assert.deepEqual([0, 1, 2, 3, 11, 100].map((n) => i18n.t('files', { n })),
    ['لا ملفات', 'ملف', 'ملفان', '3 ملفات', '11 ملفًا', '100 ملف']);
  assert.equal(i18n.dir, 'rtl');
  assert.equal(win.document.documentElement.dir, 'rtl');
  assert.equal(win.document.documentElement.lang, 'ar');
});

test('CJK text scale is injected once; latin gets none', async () => {
  const { win } = await load({
    href: 'http://localhost/?lang=zh', config: { locales: ['en', 'zh'] }, catalogs: { en: EN },
  });
  const styles = win.document.head.kids.filter((k) => k.id === 'i18n-text-scale');
  assert.equal(styles.length, 1);
  assert.match(styles[0].textContent, /html:lang\(zh\) body\{zoom:1\.15\}/);
  assert.equal(win.document.documentElement.dir, 'ltr');
  const pl = await load({ href: 'http://localhost/?lang=pl', config: { locales: ['en', 'pl'] } });
  assert.equal(pl.win.document.head.kids.length, 0);
});

test('QA locale: URL only, held for the tab, never persisted, not offered', async () => {
  const { i18n, win } = await load({
    href: 'http://localhost/?lang=en-xx', config: { locales: ['en', 'pl'] },
    catalogs: { en: EN, 'en-XX': { hi: 'XXXXX {name}' } },
  });
  assert.equal(i18n.locale, 'en-XX');
  assert.equal(i18n.isQa, true);
  assert.equal(i18n.t('hi', { name: 'A' }), 'XXXXX A');
  assert.deepEqual([...i18n.locales], ['en', 'pl']);
  assert.equal(win.localStorage.getItem('app_lang'), null);
  assert.equal(win.sessionStorage.getItem('app_lang_qa'), 'en-XX');
  // Next page in the same tab, no ?lang: still the QA locale.
  const next = await load({ config: { locales: ['en', 'pl'] }, session: { app_lang_qa: 'en-XX' } });
  assert.equal(next.i18n.locale, 'en-XX');
  // Picking a real language clears it.
  const real = await load({
    href: 'http://localhost/?lang=pl', config: { locales: ['en', 'pl'] }, session: { app_lang_qa: 'en-XX' },
  });
  assert.equal(real.i18n.locale, 'pl');
  assert.equal(real.win.sessionStorage.getItem('app_lang_qa'), null);
  // A QA code in localStorage is ignored.
  const stored = await load({ config: { locales: ['en', 'pl'] }, local: { app_lang: 'en-XX' } });
  assert.equal(stored.i18n.locale, 'en');
});

test('locale order: path prefix, ?lang, storage, prefs, navigator', async () => {
  const cfg = { locales: ['en', 'pl', 'de'], pathPrefix: true, cookie: true, prefsKey: 'p' };
  const at = async (opts) => (await load({ config: cfg, ...opts })).i18n.locale;
  assert.equal(await at({ href: 'http://localhost/de/x.html?lang=pl' }), 'de');
  assert.equal(await at({ href: 'http://localhost/en-XX/x.html' }), 'en-XX');
  assert.equal(await at({ href: 'http://localhost/x.html?lang=pl', local: { app_lang: 'de' } }), 'pl');
  assert.equal(await at({ local: { p: '{"lang":"de"}' } }), 'de');
  assert.equal((await load({ config: { locales: ['en', 'pl'] }, nav: 'pl-PL' })).i18n.locale, 'pl');
  assert.equal((await load({ config: { locales: ['en', 'pl'], navigator: false }, nav: 'pl-PL' })).i18n.locale, 'en');
});

test('setLocale persists real locales and keeps the path prefix', async () => {
  const { i18n, win } = await load({
    href: 'http://localhost/en/a.html?lang=en&x=1',
    config: { locales: ['en', 'pl'], pathPrefix: true, cookie: true, prefsKey: 'p' },
  });
  i18n.setLocale('en-XX');
  assert.equal(win.assigned, undefined);
  i18n.setLocale('pl');
  assert.equal(win.localStorage.getItem('app_lang'), 'pl');
  assert.equal(JSON.parse(win.localStorage.getItem('p')).lang, 'pl');
  assert.match(win.document.cookie, /app_lang=pl/);
  assert.equal(win.assigned, 'http://localhost/pl/a.html?x=1');
});

test('sync mode loads before returning, url template', async () => {
  const { i18n, requested } = await load({
    href: 'http://localhost/?lang=pl',
    config: { locales: ['en', 'pl'], sync: true, url: '/api/locales/{locale}' },
    catalogs: { en: EN, pl: PL },
  });
  assert.deepEqual(requested, ['/api/locales/en', '/api/locales/pl']);
  assert.equal(i18n.t('hi', { name: 'A' }), 'Cześć A');
});

test('applyDOM sets text and attributes, never clobbers child elements', async () => {
  const plain = new El('button', { 'data-i18n': 'hi' }, [text('Hello')]);
  const withIcon = new El('a', { 'data-i18n': 'hi' }, [new El('i'), text(' Hello')]);
  const attr = new El('input', { 'data-i18n-placeholder': 'only_en', placeholder: 'x' });
  const { win } = await load({
    href: 'http://localhost/?lang=pl', config: { locales: ['en', 'pl'] },
    catalogs: { en: EN, pl: PL }, elements: [plain, withIcon, attr],
  });
  win.i18n.applyDOM();
  assert.equal(plain.textContent, 'Cześć {name}');
  assert.equal(withIcon.childNodes.length, 2);
  assert.equal(attr.getAttribute('placeholder'), 'English only');
});

test('overlay gating: localhost + ?translate=1, remembered, off with ?translate=0', async () => {
  const overlay = { enabled: true, api: 'http://127.0.0.1:8770/', project: 'demo' };
  const off = await load({ config: { overlay } });
  assert.equal(off.i18n.overlay, false);
  assert.equal(off.win.__LLM_TRANSLATOR__, undefined);
  const remote = await load({ href: 'https://app.example.com/?translate=1', config: { overlay } });
  assert.equal(remote.i18n.overlay, false);
  const on = await load({ href: 'http://127.0.0.1:5000/?translate=1', config: { overlay } });
  assert.equal(on.i18n.overlay, true);
  assert.equal(on.win.__LLM_TRANSLATOR__.project(), 'demo');
  const script = on.win.document.head.kids.find((k) => k.tagName === 'script');
  assert.equal(script.src, 'http://127.0.0.1:8770/overlay.js');
  assert.equal(on.win.localStorage.getItem('llm_overlay'), '1');
  const again = await load({ config: { overlay }, local: { llm_overlay: '1' } });
  assert.equal(again.i18n.overlay, true);
  const stop = await load({ href: 'http://localhost/?translate=0', config: { overlay }, local: { llm_overlay: '1' } });
  assert.equal(stop.i18n.overlay, false);
  assert.equal(stop.win.localStorage.getItem('llm_overlay'), null);
  const disabled = await load({ href: 'http://localhost/?translate=1', config: { overlay: { enabled: false } } });
  assert.equal(disabled.i18n.overlay, false);
});

test('overlay applyTranslation updates the live catalogue', async () => {
  const { win, i18n } = await load({
    href: 'http://localhost/?translate=1', config: { overlay: { enabled: true } }, catalogs: { en: EN },
  });
  win.__LLM_TRANSLATOR__.applyTranslation({ key: 'hi', value: 'Howdy {name}' });
  assert.equal(i18n.t('hi', { name: 'B' }), 'Howdy B');
});
