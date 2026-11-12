// Copies shared/ (products, page logic, CSS, images) into each app, so every app builds from the same bytes.
import { cpSync, mkdirSync } from 'node:fs';

const root = new URL('../', import.meta.url);
const targets = {
  next: { lib: 'next/lib/', img: 'next/public/img/' },
  svelte: { lib: 'svelte/src/lib/shared/', img: 'svelte/static/img/' },
  nuxt: { lib: 'nuxt/shared/', img: 'nuxt/public/img/' },
};
for (const { lib, img } of Object.values(targets)) {
  mkdirSync(new URL(lib, root), { recursive: true });
  for (const f of ['products.json', 'shop.mjs', 'shop.css']) cpSync(new URL(`shared/${f}`, root), new URL(lib + f, root));
  cpSync(new URL('shared/img/', root), new URL(img, root), { recursive: true });
}
console.log('shared files copied into next, svelte, nuxt');
