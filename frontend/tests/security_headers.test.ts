import assert from "node:assert/strict";
import test from "node:test";

import nextConfig from "../next.config.mjs";

test("Next.js responses deny framing with CSP and X-Frame-Options", async () => {
  const headersFactory = nextConfig.headers;
  if (typeof headersFactory !== "function") {
    throw new Error("next.config.mjs must define a headers() function");
  }

  const headerRules = await headersFactory();
  const allPathsRule = headerRules.find((rule) => rule.source === "/:path*");
  assert.ok(allPathsRule);

  const headers = new Map(allPathsRule.headers.map((header) => [header.key, header.value]));

  assert.equal(
    headers.get("Content-Security-Policy"),
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'",
  );
  assert.equal(headers.get("X-Frame-Options"), "DENY");
  assert.equal(headers.get("X-Content-Type-Options"), "nosniff");
  assert.equal(headers.get("Referrer-Policy"), "strict-origin-when-cross-origin");
});
