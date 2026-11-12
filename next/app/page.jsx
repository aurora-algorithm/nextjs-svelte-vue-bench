import products from '../lib/products.json';
import { Shop } from './Shop';

// Reads ?q= so a shared search link opens filtered: the page renders on every request.
export default async function Page({ searchParams }) {
  const { q = '' } = await searchParams;
  return <Shop products={products} initialQuery={q} />;
}
