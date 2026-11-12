// Writes shared/products.json and shared/img/*.svg: the 100 products every app renders, byte for byte the same.
import { mkdirSync, writeFileSync } from 'node:fs';

const KINDS = [
  ['Headphones', '#4F7CFF'], ['Backpack', '#2EAD6B'], ['Keyboard', '#F2A93B'], ['Desk lamp', '#E0533D'],
  ['Water bottle', '#21A6C9'], ['Sneakers', '#9B5DE5'], ['Mouse', '#5C6BC0'], ['Notebook', '#C98B2E'],
  ['Speaker', '#D6457A'], ['Monitor stand', '#3F9E8F'],
];
const STYLES = ['Classic', 'Pro', 'Mini', 'Travel', 'Studio', 'Everyday', 'Max', 'Air', 'Urban', 'Lite'];
const slug = (kind) => kind.toLowerCase().replace(/ /g, '-');

const products = Array.from({ length: 100 }, (_, i) => {
  const [kind] = KINDS[i % 10];
  return {
    id: i + 1,
    name: `${STYLES[Math.floor(i / 10)]} ${kind}`,
    kind,
    priceCents: 999 + ((i * 7919) % 19000),
    rating: Math.round((3 + ((i * 37) % 21) / 10) * 10) / 10,
    reviews: 12 + ((i * 131) % 980),
    image: `/img/${slug(kind)}.svg`,
  };
});
writeFileSync(new URL('./products.json', import.meta.url), JSON.stringify(products, null, 1) + '\n');

mkdirSync(new URL('./img/', import.meta.url), { recursive: true });
for (const [kind, color] of KINDS) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 120" width="160" height="120">` +
    `<rect width="160" height="120" rx="12" fill="${color}22"/>` +
    `<circle cx="80" cy="60" r="34" fill="${color}"/>` +
    `<text x="80" y="68" font-family="Arial" font-size="22" font-weight="700" fill="#fff" text-anchor="middle">${kind[0]}</text></svg>\n`;
  writeFileSync(new URL(`./img/${slug(kind)}.svg`, import.meta.url), svg);
}
console.log(`wrote ${products.length} products`);
