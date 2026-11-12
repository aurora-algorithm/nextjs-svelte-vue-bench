# Next.js vs SvelteKit vs Nuxt: the same shop page, on default settings

Code and per-run results behind the "Next.js vs SvelteKit vs Nuxt: the same shop page on default settings, three tests" Short.

## What is tested
One shop page, built the same way in all three frameworks from the same files in `shared/` (`tools/sync_shared.mjs`
copies them into each app): 100 products rendered on the server, a search box that filters as you type, a
"Show 1,000" button (grows the list to 1,000 cards) and a "10% off" button (changes all 1,000 prices). The page reads
`?q=`, so it renders on every request in all three. The page logic (`shared/shop.mjs`), CSS and images are shared;
each framework writes the page its own way:

| App | Framework | How the page gets its data |
|---|---|---|
| `next/` | Next.js 16.4.6 (App Router), React 19.3.1 | a server `page.jsx` passes the products to a `'use client'` `Shop` |
| `svelte/` | SvelteKit 3.1.1, Svelte 5.57.3, Vite 8.3.7, adapter-node 6.0.1 | `+page.server.js` load |
| `nuxt/` | Nuxt 4.6.4, Vue 3.5.45, Nitro 2.13.6 | `server/api/products.get.js` + `useFetch` in `pages/index.vue` |

Each app also has `/hello`, a page with one counter button, to weigh the framework's own JavaScript.

Per round, each framework (order rotates every round) runs four steps (`tools/session.py`):

1. **build**: a clean `next build` / `vite build` / `nuxt build`, wall time.
2. **ssr**: the default production server (`next start`, `node build/index.js`, `node .output/server/index.mjs`; one
   Node process each) pinned to logical CPUs 0, 2, 4, 6; oha pinned to CPUs 8-15; 8 s warm-up, then 20 s with 64
   connections on `GET /`. Records req/s, latency and server memory.
3. **browser**: headless Chrome (`tools/browser.mjs`, playwright-core 1.65.0 over CDP) on CPUs 8-15, CPU slowed 4x
   with `Emulation.setCPUThrottlingRate`, viewport 412x915. 10 fresh contexts per round. `ready` is the time from
   navigation start until the page's mount hook (`useEffect` / `onMount` / `onMounted`) set `window.__ready`. The
   two clicks are timed from the click until the DOM change is seen (MutationObserver) and the next frame has painted.
4. **sizes** (round 1 and the plain round): every script the page and `/hello` load, compressed by the script itself
   (gzip -9, brotli -11) so all three are weighed at the same settings.

Checks: every server's HTML carries the same 100 cards (id, name and price; the sha256 matches across frameworks in
every round), and every browser run saw 100 cards, then 1,000, and the same last price after "10% off".

## Setup
From `results/nsv-i7-20261109/meta.json` and the per-run files:
- **Machine:** Intel i7-13700F, RTX 4070 PC, Windows 11 (native, no Docker), Balanced power plan.
- **Versions:** Node 24.13.0 · oha 1.16.0 · Chrome 157.0.8103.40 · framework versions as in the table above.
- **Load:** 64 connections · 8 s warm-up · 20 s measured · 10 browser loads per round.
- **Runs:** 5 rounds with oha's live screen recorded (`round1`-`round5`, one `.cast` each) plus 1 plain round with
  `oha --no-tui` (`plain/`), to check that recording the screen did not move the numbers. Round 1 also films one
  extra, unmeasured browser run (`round1/*-film/`).
- **Quiet machine:** before every measured step the script waits until the benchmark's CPUs are idle. In this session
  the limit was mean under 12% and max under 60% (`BENCH_GATE_MEAN` / `BENCH_GATE_MAX`, saved in `meta.json`), because
  a Windows service process (WmiPrvSE.exe) kept using about one core on the oha/Chrome side; the server CPUs stayed
  idle. Each reading is saved as `busy_before` in `runs.jsonl`.

## Results (medians of the 5 recorded rounds)
Computed from `results/nsv-i7-20261109/runs.jsonl`: server numbers are the median of the 5 rounds; browser numbers
are the median of all 50 loads; script sizes are from round 1 (`round1/*-sizes.json`), 1 KB = 1,024 bytes.

| | Next.js | SvelteKit | Nuxt |
|---|---|---|---|
| Pages a second (oha, 64 connections) | 572 | 1,924 | 1,038 |
| p50 / p99 latency | 111 / 138 ms | 22 / 169 ms | 60 / 88 ms |
| Server memory (median during load) | 393 MB | 328 MB | 381 MB |
| "Show 1,000", click to painted, 4x CPU slowdown | 197 ms | 166 ms | 136.5 ms |
| "10% off" on 1,000 prices | 69 ms | 47 ms | 54 ms |
| Fresh load until the page's code ran | 342 ms | 247 ms | 250 ms |
| First contentful paint | 132 ms | 132 ms | 128 ms |
| JavaScript sent, brotli (shop page / `/hello`) | 112.9 / 112.4 KB | 31.3 / 30.7 KB | 69.3 / 64.6 KB |
| Clean build | 2.5 s | 2.8 s | 4.2 s |

Plain round (`oha --no-tui`) req/s: Next.js 566, SvelteKit 1,871, Nuxt 1,042, each within 3% of the recorded median.

## Reproduce
On Windows (CPU pinning uses the logical CPU numbers of a 16-thread P-core part; edit `BUILD_CPUS`, `SERVER_CPUS` and
`OHA_CPUS` at the top of `tools/session.py` for another CPU). Needs Node 24, Python 3 with `psutil` and `pywinpty`,
oha on `PATH` (or `OHA=...`), and Google Chrome (or `CHROME=path/to/chrome`).

```bash
node shared/make_products.mjs && node tools/sync_shared.mjs
npm ci && (cd next && npm ci) && (cd svelte && npm ci) && (cd nuxt && npm ci)
pip install psutil pywinpty
python tools/session.py results/my-session 5     # about 17 minutes; writes runs.jsonl and the per-round files
```

The quiet-gate limits default to mean under 5% and max under 15%; set `BENCH_GATE_MEAN` and `BENCH_GATE_MAX` to change
them.

## Settings people may argue about
- Every framework runs on its out-of-the-box settings and its default start command. No framework option is changed,
  and nothing is lazy-loaded. The page reads `?q=`, so all three render it on every request.
- Next.js uses the App Router with a server page and one client component holding the whole shop.
- Each server is one Node process on four physical cores; none of them runs in cluster mode.
- The script sizes are compressed by the bench at gzip -9 and brotli -11, not taken from what each server sent.
- `ready` is this bench's own timer (the page's mount hook ran), not Lighthouse's Time to Interactive.
- oha and the server share one machine, on separate cores.
