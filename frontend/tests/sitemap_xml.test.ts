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

// 動的に渡した個別プロンプトページが、ルート別のlastmodとともにサイトマップへ追加されることを確認する
// Verify that dynamically passed individual prompt pages are appended to the sitemap with their per-route lastmod
test("sitemap appends dynamic prompt routes with per-route lastmod", () => {
  const sitemap = buildSitemapXml("https://example.com", "2026-05-20T00:00:00.000Z", [
    { path: "/shared/prompt/42", changefreq: "weekly", priority: "0.6", lastmod: "2026-06-01T00:00:00.000Z" },
    { path: "/shared/prompt/abc", changefreq: "weekly", priority: "0.6" }
  ]);

  // 静的ルートは引き続き含まれる / Static routes are still present
  assert.match(sitemap, /<loc>https:\/\/example\.com\/<\/loc>/);
  // 個別プロンプトページがloc・lastmodとともに出力される / Individual prompt pages are emitted with loc and lastmod
  assert.match(sitemap, /<loc>https:\/\/example\.com\/shared\/prompt\/42<\/loc>\n\s*<lastmod>2026-06-01T00:00:00\.000Z<\/lastmod>/);
  // lastmod未指定のルートはグローバルlastmodにフォールバックする / Routes without lastmod fall back to the global lastmod
  assert.match(sitemap, /<loc>https:\/\/example\.com\/shared\/prompt\/abc<\/loc>\n\s*<lastmod>2026-05-20T00:00:00\.000Z<\/lastmod>/);
});
