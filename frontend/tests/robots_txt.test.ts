import assert from "node:assert/strict";
import test from "node:test";

import { buildRobotsTxt } from "../pages/robots.txt";

test("robots.txt allows crawlable HTML pages so page-level noindex can be read", () => {
  const robots = buildRobotsTxt("https://example.com");

  for (const path of [
    "/admin",
    "/login",
    "/register",
    "/settings",
    "/memo",
    "/prompt_share/category/coding",
    "/prompt_share/manage_prompts",
    "/google-login",
    "/google-callback",
    "/logout",
  ]) {
    assert.equal(robots.includes(`Disallow: ${path}\n`), false);
  }
});

test("robots.txt still blocks internal API endpoints and advertises the sitemap", () => {
  const robots = buildRobotsTxt("https://example.com");

  assert.match(robots, /^User-agent: \*\nAllow: \//);
  assert.match(robots, /Disallow: \/api\//);
  assert.match(robots, /Disallow: \/admin\/api\//);
  assert.match(robots, /Disallow: \/memo\/api\//);
  assert.match(robots, /Disallow: \/prompt_manage\/api\//);
  assert.match(robots, /Disallow: \/prompt_share\/api\//);
  assert.match(robots, /Disallow: \/search\//);
  assert.match(robots, /Sitemap: https:\/\/example\.com\/sitemap\.xml/);
});

test("robots.txt exempts prompt reference images from the API-wide block", () => {
  const robots = buildRobotsTxt("https://example.com");

  // og:imageと構造化データのimageが指す作例画像は /prompt_share/api/media/ 配下なので、
  // Allowで例外にしないと画像検索とリッチリザルトから外れる。
  // The reference images behind og:image and the structured-data image live under
  // /prompt_share/api/media/, so without this Allow they drop out of image search and rich results.
  assert.match(robots, /Allow: \/prompt_share\/api\/media\//);
  assert.ok(
    robots.indexOf("Allow: /prompt_share/api/media/") < robots.indexOf("Disallow: /prompt_share/api/")
  );
});
