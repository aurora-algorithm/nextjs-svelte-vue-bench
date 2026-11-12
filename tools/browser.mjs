// Measures one running shop server in real Chrome (headless, the installed Chrome, via playwright-core + CDP).
//
// Every run opens a fresh browser context (empty cache) with the CPU slowed 4x (Chrome's own CPU throttle, the
// setting Lighthouse uses for a mid-range phone), loads the page, then clicks the page's own buttons the way
// js-framework-benchmark does:
//   ready   ms from navigation start until the page's code has run (window.__ready, set in useEffect / onMount /
//           onMounted: from then on the search box and buttons work)
//   fcp     first contentful paint
//   create  click "Show 1,000" -> 1,000 cards on screen, painted (MutationObserver + next frame)
//   update  click "10% off" -> all 1,000 prices changed, painted
// With --sizes it also records every script the page and /hello load, raw and compressed by us (gzip -9, brotli
// -11), so all three are compared at the same compression whatever their servers send.
// With --film DIR it records one separate, unmeasured run as a video (Playwright recordVideo) for the Short.
//
// usage: node tools/browser.mjs --url http://127.0.0.1:8080 --runs 10 --out runs.json [--sizes sizes.json] [--film DIR]
import { mkdirSync, writeFileSync } from 'node:fs';
import { brotliCompressSync, constants, gzipSync } from 'node:zlib';
import { chromium } from 'playwright-core';

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const URL_BASE = arg('url');
const RUNS = Number(arg('runs', '10'));
const OUT = arg('out');
const SIZES = arg('sizes');
const FILM = arg('film');
const CPU_SLOWDOWN = 4;
const VIEWPORT = { width: 412, height: 915 };
const CHROME = process.env.CHROME ?? (process.platform === 'win32'
  ? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
  : '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');

if (!URL_BASE || !OUT) {
  console.error('usage: node tools/browser.mjs --url URL --runs N --out FILE [--sizes FILE] [--film DIR]');
  process.exit(2);
}

/** Clicks `selector` and resolves with ms until `done()` holds in the DOM and the next frame has painted. */
const clickTimed = (page, selector, done) =>
  page.evaluate(
    ([sel, doneSrc]) =>
      new Promise((resolve, reject) => {
        const isDone = new Function(`return (${doneSrc})()`);
        const grid = document.querySelector('.grid');
        const timer = setTimeout(() => reject(new Error(`${sel}: no change in 30 s`)), 30000);
        let dom = 0;
        const t0 = performance.now();
        const finish = () => {
          dom = performance.now() - t0;
          observer.disconnect();
          requestAnimationFrame(() => setTimeout(() => {
            clearTimeout(timer);
            resolve({ ms: performance.now() - t0, dom_ms: dom });
          }, 0));
        };
        const observer = new MutationObserver(() => {
          if (!dom && isDone()) finish();
        });
        observer.observe(grid, { childList: true, subtree: true, characterData: true, attributes: true });
        document.querySelector(sel).click();
      }),
    [selector, done.toString()],
  );

// Strings that only one library's production build carries, to label which file holds what.
const MARKERS = { 'react-dom': 'react.dev/errors', next: '__NEXT_', vue: 'vuejs.org', nuxt: '__NUXT', svelte: 'svelte.dev/e/', sveltekit: 'sveltekit' };

/** Screencast frames of the filmed run, with their wall-clock time in ms (the marks use the same clock). */
const FRAMES = [];

const lastPrice = () => document.querySelector('.grid li:last-child .price')?.textContent ?? '';

async function openPage(browser, film) {
  // The filmed run draws at 2x and keeps every screencast frame (JPEG + its timestamp) so the recording stays sharp in
  // a 1080-wide frame; it is never measured.
  const context = await browser.newContext({ viewport: VIEWPORT, ...(film ? { deviceScaleFactor: 2 } : {}) });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU_SLOWDOWN });
  if (film) {
    mkdirSync(`${film}/frames`, { recursive: true });
    let n = 0;
    cdp.on('Page.screencastFrame', async ({ data, metadata, sessionId }) => {
      const name = `${String(n++).padStart(5, '0')}.jpg`;
      writeFileSync(`${film}/frames/${name}`, Buffer.from(data, 'base64'));
      FRAMES.push({ name, t_ms: metadata.timestamp * 1000 });
      await cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
    });
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 90, maxWidth: VIEWPORT.width * 2, maxHeight: VIEWPORT.height * 2, everyNthFrame: 1 });
  }
  return { context, page };
}

async function oneRun(browser, film) {
  const marks = {};
  let shoot = async () => {};
  const mark = async (name) => {
    marks[name] = Date.now();
    await shoot(name);
  };
  const { context, page } = await openPage(browser, film);
  // Sharp 2x stills of the filmed run at each mark (the screencast frames come at 1x).
  if (film) shoot = (name) => page.screenshot({ path: `${film}/${name}.png` }).then(() => {});
  try {
    await mark('goto');
    await page.goto(`${URL_BASE}/`, { waitUntil: 'load' });
    await page.waitForFunction(() => window.__ready !== undefined, null, { timeout: 30000 });
    const load = await page.evaluate(() => ({
      ready_ms: window.__ready,
      fcp_ms: performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? null,
      cards: document.querySelectorAll('.grid li').length,
    }));
    if (load.cards !== 100) throw new Error(`expected 100 cards, saw ${load.cards}`);
    await mark('ready');
    if (film) await page.waitForTimeout(600);
    await mark('click_more');
    const create = await clickTimed(page, '#more', () => document.querySelectorAll('.grid li').length === 1000);
    await mark('created');
    if (film) {
      // Scroll down the grown list so the recording shows the 1,000 cards, then back up for the price change.
      for (let i = 0; i < 12; i++) {
        await page.mouse.wheel(0, 400);
        await page.waitForTimeout(60);
      }
      await mark('scrolled');
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(400);
    }
    const before = await page.evaluate(lastPrice);
    await mark('click_sale');
    const update = await clickTimed(page, '#sale', new Function(`return () => (document.querySelector('.grid li:last-child .price')?.textContent ?? '') !== ${JSON.stringify(before)}`)());
    const after = await page.evaluate(lastPrice);
    const count = await page.evaluate(() => document.querySelector('.count').textContent);
    await mark('updated');
    if (film) await page.waitForTimeout(800);
    await mark('end');
    return { marks_ms: marks, ...load, create_ms: create.ms, create_dom_ms: create.dom_ms, update_ms: update.ms, update_dom_ms: update.dom_ms,
      last_price_before: before, last_price_after: after, count_text: count };
  } finally {
    await context.close();
  }
}

/** Every script a fresh load of `path` fetches, with its size raw and compressed here at fixed settings. */
async function scriptSizes(browser, path) {
  const context = await browser.newContext({ viewport: VIEWPORT });
  const page = await context.newPage();
  const bodies = [];
  page.on('response', async (res) => {
    if (res.request().resourceType() === 'script') bodies.push(res.body().then((b) => ({ url: res.url(), body: b })));
  });
  await page.goto(`${URL_BASE}${path}`, { waitUntil: 'networkidle' });
  if (path === '/') await page.waitForFunction(() => window.__ready !== undefined);
  const files = (await Promise.all(bodies)).map(({ url, body }) => ({
    url: url.replace(URL_BASE, ''),
    has: Object.entries(MARKERS).filter(([, m]) => body.includes(m)).map(([k]) => k),
    raw: body.length,
    gzip: gzipSync(body, { level: 9 }).length,
    brotli: brotliCompressSync(body, { params: { [constants.BROTLI_PARAM_QUALITY]: 11 } }).length,
  }));
  const html = await (await context.request.get(`${URL_BASE}${path}`)).body();
  await context.close();
  const sum = (k) => files.reduce((n, f) => n + f[k], 0);
  return { path, files, raw: sum('raw'), gzip: sum('gzip'), brotli: sum('brotli'), html_raw: html.length,
    html_gzip: gzipSync(html, { level: 9 }).length };
}

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
try {
  if (SIZES) {
    const sizes = { page: await scriptSizes(browser, '/'), hello: await scriptSizes(browser, '/hello') };
    writeFileSync(SIZES, JSON.stringify(sizes, null, 1));
  }
  if (FILM) {
    // Marks and frames carry wall-clock ms, so make_data.py can find each click in the frames.
    const run = await oneRun(browser, FILM);
    writeFileSync(`${FILM}/film.json`, JSON.stringify({ ...run, frames: FRAMES }, null, 1));
  }
  const runs = [];
  for (let i = 0; i < RUNS; i++) runs.push(await oneRun(browser, null));
  writeFileSync(OUT, JSON.stringify({ chrome: browser.version(), cpu_slowdown: CPU_SLOWDOWN, viewport: VIEWPORT, runs }, null, 1));
  const med = (k) => runs.map((r) => r[k]).sort((a, b) => a - b)[Math.floor(runs.length / 2)];
  console.log(`ready ${med('ready_ms').toFixed(0)} ms  create ${med('create_ms').toFixed(0)} ms  update ${med('update_ms').toFixed(0)} ms`);
} finally {
  await browser.close();
}
