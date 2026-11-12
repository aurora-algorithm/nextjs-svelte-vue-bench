import products from '#lib/shared/products.json';

// Reads ?q= so a shared search link opens filtered: the page renders on every request.
export function load({ url }) {
  return { products, initialQuery: url.searchParams.get('q') ?? '' };
}
