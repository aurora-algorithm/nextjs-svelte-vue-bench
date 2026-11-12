'use client';

import { useEffect, useState } from 'react';
import { discount, makeRows, matches, price } from '../lib/shop.mjs';

export function Shop({ products, initialQuery }) {
  const [query, setQuery] = useState(initialQuery);
  const [rows, setRows] = useState(products);
  useEffect(() => {
    window.__ready = performance.now();
  }, []);
  const visible = rows.filter((p) => matches(p, query));
  return (
    <main className="shop">
      <h1>Shop</h1>
      <input className="search" placeholder="Search products" value={query} onChange={(e) => setQuery(e.target.value)} />
      <div className="bar">
        <span className="count">{visible.length} products</span>
        <button id="more" onClick={() => setRows(makeRows(products))}>Show 1,000</button>
        <button id="sale" onClick={() => setRows(discount(rows))}>10% off</button>
      </div>
      <ul className="grid">
        {visible.map((p) => (
          <li className="card" key={p.id} data-id={p.id}>
            <img src={p.image} width="160" height="120" alt={p.kind} loading="lazy" />
            <h2>{p.name}</h2>
            <span className="price">{price(p.priceCents)}</span>
            <span className="rating">★ {p.rating} ({p.reviews})</span>
          </li>
        ))}
      </ul>
    </main>
  );
}
