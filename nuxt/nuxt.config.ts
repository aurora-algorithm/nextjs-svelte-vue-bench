export default defineNuxtConfig({
  compatibilityDate: '2026-11-01',
  css: ['~~/shared/shop.css'],
  app: { head: { title: 'Shop', htmlAttrs: { lang: 'en' } } },
  devtools: { enabled: false },
  telemetry: false,
});
