<script>
  import { onMount } from 'svelte';
  import { discount, makeRows, matches, price } from '#lib/shared/shop.mjs';

  let { data } = $props();
  let query = $state(data.initialQuery);
  let rows = $state.raw(data.products);
  const visible = $derived(rows.filter((p) => matches(p, query)));
  onMount(() => {
    window.__ready = performance.now();
  });
</script>

<main class="shop">
  <h1>Shop</h1>
  <input class="search" placeholder="Search products" bind:value={query} />
  <div class="bar">
    <span class="count">{visible.length} products</span>
    <button id="more" onclick={() => (rows = makeRows(data.products))}>Show 1,000</button>
    <button id="sale" onclick={() => (rows = discount(rows))}>10% off</button>
  </div>
  <ul class="grid">
    {#each visible as p (p.id)}
      <li class="card" data-id={p.id}>
        <img src={p.image} width="160" height="120" alt={p.kind} loading="lazy" />
        <h2>{p.name}</h2>
        <span class="price">{price(p.priceCents)}</span>
        <span class="rating">★ {p.rating} ({p.reviews})</span>
      </li>
    {/each}
  </ul>
</main>
