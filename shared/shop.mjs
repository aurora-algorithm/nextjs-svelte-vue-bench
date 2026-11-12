// The page logic all three apps share, so they do exactly the same work: filter by the search box, grow the list
// to 1,000 rows, and take 10% off every price.

export const ROWS = 1000;

export const price = (cents) => `$${(cents / 100).toFixed(2)}`;

export const matches = (product, query) => product.name.toLowerCase().includes(query.trim().toLowerCase());

/** 1,000 rows built from the 100 products (10 sizes of each), ids 1..1000 in order. */
export const makeRows = (products) => {
  const rows = [];
  for (let size = 0; size < ROWS / products.length; size++) {
    for (const p of products) {
      rows.push({ ...p, id: size * products.length + p.id, name: `${p.name} ${size + 1}`, priceCents: p.priceCents + size * 100 });
    }
  }
  return rows;
};

export const discount = (rows) => rows.map((r) => ({ ...r, priceCents: Math.round(r.priceCents * 0.9) }));
