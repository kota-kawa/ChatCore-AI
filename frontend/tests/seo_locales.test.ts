import assert from "node:assert/strict";
import test from "node:test";

import { localizedAbsoluteUrl, localizePublicPath } from "../lib/seo";
import { resolvePageLocale } from "../lib/i18n/config";
import nextConfig from "../next.config.mjs";

test("Next.js exposes English under /en without automatic locale redirects", () => {
  assert.deepEqual(nextConfig.i18n, {
    locales: ["ja", "en"],
    defaultLocale: "ja",
    localeDetection: false
  });
});

test("public paths use unprefixed Japanese URLs and /en English URLs", () => {
  assert.equal(localizePublicPath("/help", "ja"), "/help");
  assert.equal(localizePublicPath("/help", "en"), "/en/help");
  assert.equal(localizePublicPath("/", "en"), "/en");
});

test("locale path conversion is idempotent and preserves query strings and hashes", () => {
  assert.equal(localizePublicPath("/en/help?topic=account#login", "en"), "/en/help?topic=account#login");
  assert.equal(localizePublicPath("/en/help?topic=account#login", "ja"), "/help?topic=account#login");
});

test("absolute canonical URLs retain their origin while changing locale paths", () => {
  assert.equal(
    localizedAbsoluteUrl("https://example.com/shared/prompt/42?ref=search", "en"),
    "https://example.com/en/shared/prompt/42?ref=search"
  );
  assert.equal(
    localizedAbsoluteUrl("https://example.com/en/shared/prompt/42", "ja"),
    "https://example.com/shared/prompt/42"
  );
});

test("route locales override conflicting cookies and Accept-Language headers", () => {
  assert.equal(resolvePageLocale("en", "chatcore_locale=ja", "ja"), "en");
  assert.equal(resolvePageLocale("ja", "chatcore_locale=en", "en"), "ja");
  assert.equal(resolvePageLocale(undefined, "chatcore_locale=en", "ja"), "en");
});
