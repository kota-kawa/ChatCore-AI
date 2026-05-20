import assert from "node:assert/strict";
import test from "node:test";

import { buildSitemapXml, PUBLIC_SITEMAP_ROUTES } from "../pages/sitemap.xml";

test("sitemap includes public crawlable application pages", () => {
  const sitemap = buildSitemapXml("https://example.com/", "2026-05-20T00:00:00.000Z");

  assert.match(sitemap, /^<\?xml version="1\.0" encoding="UTF-8"\?>/);
  assert.match(sitemap, /<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9">/);

  for (const route of PUBLIC_SITEMAP_ROUTES) {
    assert.match(sitemap, new RegExp(`<loc>https://example\\.com${route.path}</loc>`));
  }

  assert.match(sitemap, /<loc>https:\/\/example\.com\/prompt_share<\/loc>/);
  assert.match(sitemap, /<loc>https:\/\/example\.com\/memo<\/loc>/);
});

test("sitemap escapes XML-sensitive origin values", () => {
  const sitemap = buildSitemapXml("https://example.com?a=1&b=2", "2026-05-20T00:00:00.000Z");

  assert.match(sitemap, /<loc>https:\/\/example\.com\?a=1&amp;b=2\/<\/loc>/);
});
