<script setup>
import { computed, onMounted, ref, shallowRef } from 'vue';
import { discount, makeRows, matches, price } from '~~/shared/shop.mjs';

// Reads ?q= so a shared search link opens filtered: the page renders on every request.
const route = useRoute();
const { data: products } = await useFetch('/api/products');
const query = ref(String(route.query.q ?? ''));
const rows = shallowRef(products.value);
const visible = computed(() => rows.value.filter((p) => matches(p, query.value)));
onMounted(() => {
  window.__ready = performance.now();
});
</script>

<template>
  <main class="shop">
    <h1>Shop</h1>
    <input v-model="query" class="search" placeholder="Search products" />
    <div class="bar">
      <span class="count">{{ visible.length }} products</span>
      <button id="more" @click="rows = makeRows(products)">Show 1,000</button>
      <button id="sale" @click="rows = discount(rows)">10% off</button>
    </div>
    <ul class="grid">
      <li v-for="p in visible" :key="p.id" class="card" :data-id="p.id">
        <img :src="p.image" width="160" height="120" :alt="p.kind" loading="lazy" />
        <h2>{{ p.name }}</h2>
        <span class="price">{{ price(p.priceCents) }}</span>
        <span class="rating">★ {{ p.rating }} ({{ p.reviews }})</span>
      </li>
    </ul>
  </main>
</template>
